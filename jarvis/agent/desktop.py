"""Floating Windows JARVIS overlay. Run from JARVIS.pyw."""
import ctypes as ct
from ctypes import wintypes as wt
import json
import math
import os
import re
from queue import Empty, Queue
from threading import Thread
import time
import tkinter as tk
from tkinter import ttk
from urllib.error import HTTPError, URLError
from urllib.request import Request, ProxyHandler, HTTPRedirectHandler, build_opener
import wave

from . import tools, voice
from .desktop_audio import MIC_RATE, Microphone, Playback, input_devices
from .listening import BLOCK, Listening
from .desktop_hud import (TRANSPARENT, PANEL, INK, MUTED, WIDTH, HEIGHT, CORE_Y,
                          PANEL_W, PANEL_Y, PANEL_H, Hologram, Spring, core_x, layout_target)


TITLE = 'JARVIS Floating Core'
SHORTCUT = 'Ctrl+Alt+J'
FOLLOW_UP_SECONDS = 25
MIC_RETRY_SECONDS = 2
TASKS = {
    'read_inbox': ('Reading unread Gmail', 'Complete Google sign-in if your browser opens.'),
    'open_website': ('Opening website', 'Handing the link to your default browser.'),
}


class ConsoleError(RuntimeError):
    def __init__(self, code, message, reason=None):
        super().__init__(message)
        self.code = code
        self.reason = reason


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        return None


class Console:
    """Use the existing loopback server, including its Gmail and consent rules."""
    def __init__(self, port=8767):
        self.origin = f'http://127.0.0.1:{port}'
        self.token = ''
        self.cloud_recognition = True
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def request(self, path, body=None, mime='application/json', approved=False):
        headers = {'Content-Type': mime, 'Origin': self.origin,
                   'X-Jarvis-CSRF': self.token,
                   'X-Jarvis-Voice-Approved': 'yes' if approved else 'no'}
        try:
            with self.opener.open(Request(self.origin + path, data=body, headers=headers),
                                  timeout=5 if body is None else 250) as response:
                if path == '/api/speak':
                    if response.headers.get_content_type() != 'audio/wav':
                        raise ConsoleError(415, 'Restart the local Command Center to enable desktop audio.')
                    payload = response.read(21 * 1024 * 1024)
                    return payload
                return json.load(response)
        except HTTPError as error:
            reason = None
            with error:
                try:
                    payload = json.loads(error.read(16384))
                    message = payload.get('error', '')
                    reason = payload.get('code')
                except (AttributeError, ValueError):
                    message = ''
            raise ConsoleError(error.code, message or f'JARVIS returned HTTP {error.code}.', reason) from None
        except (URLError, OSError):
            raise ConsoleError(0, 'The local Command Center is unavailable. Start the JARVIS server and try again.') from None

    def status(self):
        response = self.request('/api/status')
        self.token = response['csrf']
        self.cloud_recognition &= response.get('voice_configured', True)
        return response

    def post(self, path, content, *, approved=False):
        binary = isinstance(content, bytes)
        body = content if binary else json.dumps(content).encode('utf-8')
        mime = 'audio/wav' if binary else 'application/json'
        if not self.token:
            self.status()
        try:
            return self.request(path, body, mime, approved)
        except ConsoleError as error:
            # Older servers used the same error for stale sessions and origin failures.
            legacy_session_error = error.reason is None and str(error).startswith('Request must originate')
            if error.code != 403 or not (error.reason == 'stale_session' or legacy_session_error):
                raise
        self.status()
        return self.request(path, body, mime, approved)

    def ask(self, question, history):
        return self.post('/api/chat', {'question': question, 'history': history})

    def transcribe(self, audio):
        if not self.token:
            self.status()
        if self.cloud_recognition:
            try:
                result = self.post('/api/listen', audio, approved=True)
                if result.get('uncertain') or result['text'].strip():
                    return result
            except ConsoleError as error:
                if error.code not in (402, 502):
                    raise
                self.cloud_recognition = False
        return {**self.post('/api/listen/local', audio, approved=True), 'provider': 'Windows'}

    def speech(self, text):
        return self.post('/api/speak', {'text': text, 'format': 'wav'}, approved=True)


class MonitorInfo(ct.Structure):
    _fields_ = [('size', wt.DWORD), ('monitor', wt.RECT), ('work', wt.RECT), ('flags', wt.DWORD)]


def screen_api():
    api = ct.windll.user32
    api.GetAncestor.argtypes = [wt.HWND, wt.UINT]
    api.GetAncestor.restype = wt.HWND
    api.MonitorFromPoint.argtypes = [wt.POINT, wt.DWORD]
    api.MonitorFromPoint.restype = wt.HANDLE
    api.GetMonitorInfoW.argtypes = [wt.HANDLE, ct.POINTER(MonitorInfo)]
    api.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ct.c_int, ct.c_int, ct.c_int, ct.c_int, wt.UINT]
    return api


def hotkey_listener(events):
    api = ct.windll.user32
    key = 0x44A0
    # Register on this thread only. Tk's own message loop stays untouched.
    registered = bool(api.RegisterHotKey(None, key, 0x4003, ord('J')))
    events.put(('shortcut', 0, registered))
    if registered:
        try:
            message = wt.MSG()
            while api.GetMessageW(ct.byref(message), None, 0, 0) > 0:
                if message.message == 0x0312 and message.wParam == key:
                    events.put(('toggle', 0, None))
        finally:
            api.UnregisterHotKey(None, key)


class Desktop:
    def __init__(self, root, console=None, mic_factory=Microphone, playback_factory=Playback, hotkey=True):
        self.root = root
        self.console = console or Console()
        self.mic_factory, self.playback_factory = mic_factory, playback_factory
        self.api = screen_api()
        self.events = Queue()
        self.history = []
        self.job = 0
        self.status = 'idle'
        self.panel = Spring(0, 0)
        self.compact = self.hidden = self.can_hide = False
        self.mic = self.playback = self.drag = None
        self.waveform = ()
        self.energy = self.progress = self.complete_until = 0.0
        self.last_frame = time.monotonic()
        self.window_position = None
        self.closed = False
        config = voice.settings()
        self.wake_enabled = config.get('JARVIS_WAKE_WORD', '0') == '1'
        self.active_until = 0.
        self.retry_mic_at = 0.
        self.speech_settings = []
        for key, default, low, high in (
            ('JARVIS_MIC_SENSITIVITY', .55, 0., 1.),
            ('JARVIS_NOISE_SUPPRESSION', .65, 0., 1.),
            ('JARVIS_SILENCE_SECONDS', .95, .55, 1.8),
            ('JARVIS_WAKE_SENSITIVITY', .55, 0., 1.),
        ):
            try:
                value = float(config.get(key, default))
            except ValueError:
                value = default
            self.speech_settings.append(max(low, min(high, value)))
        self.devices = dict(input_devices()) if mic_factory is Microphone else {'Default microphone': None}
        preferred = config.get('JARVIS_MIC_DEVICE')
        selected = next((label for label, device in self.devices.items()
                         if label == preferred or str(device) == preferred), next(iter(self.devices)))
        self.device = tk.StringVar(value=selected)
        self.diagnostics = tk.StringVar(value='Microphone muted')
        self.transcription = 'Waiting for speech'

        root.withdraw()
        root.title(TITLE)
        root.overrideredirect(True)
        root.attributes('-topmost', True)
        root.attributes('-transparentcolor', TRANSPARENT)
        root.configure(bg=TRANSPARENT)
        root.geometry(f'{WIDTH}x{HEIGHT}+10+10')
        self.canvas = tk.Canvas(root, width=WIDTH, height=HEIGHT, bg=TRANSPARENT,
                                borderwidth=0, highlightthickness=0)
        self.canvas.pack(fill='both', expand=True)
        self.hud = Hologram(self.canvas)
        self.panel_widget = self.build_panel()
        self.panel_window = self.canvas.create_window(0, 0, anchor='nw', window=self.panel_widget,
                                                       width=PANEL_W - 22, height=PANEL_H - 20, state='hidden')
        pointer = wt.POINT()
        self.api.GetCursorPos(ct.byref(pointer))
        work = self.work_area(pointer.x, pointer.y)
        left, top, right, bottom = work
        x, y, self.side = layout_target(right - 165, top + (bottom - top) * .34, work)
        self.x, self.y = Spring(x, x), Spring(y, y)
        animation = wt.BOOL(True)
        self.api.SystemParametersInfoW(0x1042, 0, ct.byref(animation), 0)
        self.reduced = not animation.value

        self.canvas.bind('<ButtonPress-1>', self.press)
        self.canvas.bind('<B1-Motion>', self.move)
        self.canvas.bind('<ButtonRelease-1>', self.release)
        self.canvas.bind('<space>', lambda event: self.activate_core())
        root.bind('<Escape>', lambda event: self.escape())
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.deiconify()
        root.update_idletasks()
        handle = self.canvas.winfo_toplevel().winfo_id()
        self.hwnd = self.api.GetAncestor(handle, 2) or handle
        self.place()
        if hotkey:
            Thread(target=hotkey_listener, args=(self.events,), daemon=True).start()
        if config.get('JARVIS_MIC_AUTOSTART') == '1':
            self.wake_enabled = True
            self.voice_enabled.set(True)
            self.start_listening()
        self.tick()

    def work_area(self, x, y):
        pointer = wt.POINT(round(x), round(y))
        monitor = self.api.MonitorFromPoint(pointer, 2)
        info = MonitorInfo()
        info.size = ct.sizeof(info)
        if self.api.GetMonitorInfoW(monitor, ct.byref(info)):
            rect = info.work
            return rect.left, rect.top, rect.right, rect.bottom
        return 0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight()

    def place(self):
        position = round(self.x.value - core_x(self.side)), round(self.y.value - CORE_Y)
        if position != self.window_position:
            # Native coordinates also support monitors left or above the primary one.
            self.api.SetWindowPos(self.hwnd, None, *position, 0, 0, 0x0015)
            self.window_position = position

    def build_panel(self):
        panel = tk.Frame(self.canvas, bg=PANEL)
        top = tk.Frame(panel, bg=PANEL)
        top.pack(fill='x')
        self.panel_status = tk.StringVar(value='JARVIS · READY')
        tk.Label(top, textvariable=self.panel_status, anchor='w', fg=INK, bg=PANEL,
                 font=('Segoe UI Semibold', 11)).pack(side='left', fill='x', expand=True)
        tk.Button(top, text='Exit', command=self.close, bg='#102d3d', fg=INK,
                  activebackground='#1b475d', activeforeground=INK, relief='flat').pack(side='right')
        self.reader = tk.Text(panel, wrap='word', height=5, bg='#06131f', fg=INK, padx=9, pady=7,
                              relief='flat', font=('Segoe UI', 10), highlightthickness=0)
        self.reader.pack(fill='both', expand=True, pady=(7, 6))
        self.display(f'Enable hands-free voice to talk or type below. Drag the core to move it. Use {SHORTCUT} to show or hide it.')
        self.entry = tk.Entry(panel, bg='#0c2636', fg=INK, insertbackground=INK,
                              relief='flat', font=('Segoe UI', 11))
        self.entry.pack(fill='x', ipady=4)
        self.entry.bind('<Return>', lambda event: self.send_entry())
        controls = tk.Frame(panel, bg=PANEL)
        controls.pack(fill='x', pady=(6, 0))
        self.voice_enabled = tk.BooleanVar(value=False)
        tk.Checkbutton(controls, text='Hands-free voice', variable=self.voice_enabled,
                       command=self.voice_toggled, highlightthickness=0,
                       bg=PANEL, fg=INK, activebackground=PANEL, activeforeground=INK,
                       selectcolor='#102d3d').pack(side='left')
        for label, action in (('Send', self.send_entry), ('Inbox', lambda: self.submit('Read my unread emails'))):
            tk.Button(controls, text=label, command=action, bg='#124258', fg=INK,
                      activebackground='#1b556a', activeforeground=INK,
                      relief='flat', padx=9).pack(side='right', padx=(5, 0))
        microphone = ttk.Combobox(panel, textvariable=self.device, values=list(self.devices), state='readonly',
                                  postcommand=self.refresh_microphones)
        self.microphone_selector = microphone
        microphone.pack(fill='x', pady=(4, 0))
        microphone.bind('<<ComboboxSelected>>', self.select_microphone)
        tk.Label(panel, textvariable=self.diagnostics, bg=PANEL, fg=MUTED, anchor='w',
                 font=('Segoe UI', 8)).pack(fill='x')
        return panel

    def display(self, text):
        self.reader.configure(state='normal')
        self.reader.delete('1.0', 'end')
        self.reader.insert('1.0', text)
        self.reader.configure(state='disabled')

    def change_state(self, state, label=None):
        self.status = state
        self.panel_status.set(label or f'JARVIS · {state.upper()}')

    def expand(self, expanded=True, move_aside=False):
        self.panel.target = float(expanded)
        if expanded:
            self.compact = False
            work = self.work_area(self.x.target, self.y.target)
            x = self.x.target
            if move_aside:
                x = work[2] - 123 if x > (work[0] + work[2]) / 2 else work[0] + 123
            self.x.target, self.y.target, self.side = layout_target(x, self.y.target, work, True)
        if self.reduced:
            self.panel.value = self.panel.target

    def press(self, event):
        self.canvas.focus_set()
        hit = self.hud.button_at(event.x, event.y)
        if hit:
            self.drag = ('button', hit)
        elif math.hypot(event.x - core_x(self.side), event.y - CORE_Y) <= (58 if self.compact else 113):
            self.drag = ('core', event.x_root, event.y_root, self.x.value, self.y.value, False)
        else:
            self.drag = None

    def move(self, event):
        if not self.drag or self.drag[0] != 'core':
            return
        _, start_x, start_y, x, y, moved = self.drag
        dx, dy = event.x_root - start_x, event.y_root - start_y
        if moved or math.hypot(dx, dy) >= 5:
            target = (x + dx, y + dy)
            self.x.target, self.y.target, _ = layout_target(*target, self.work_area(*target))
            self.drag = ('core', start_x, start_y, x, y, True)

    def release(self, event):
        drag, self.drag = self.drag, None
        if not drag:
            return
        if drag[0] == 'core':
            if not drag[-1]:
                self.activate_core()
            elif self.panel.target:
                self.expand()
            return
        if self.hud.button_at(event.x, event.y) != drag[1]:
            return
        if drag[1] == 'panel':
            self.expand(not self.panel.target)
        elif drag[1] == 'minimize':
            self.expand(False)
            self.compact = True
        elif drag[1] == 'hide':
            self.toggle_visibility()

    def toggle_visibility(self):
        if self.hidden:
            self.hidden = False
            self.root.deiconify()
            self.window_position = None
            self.place()
            return
        if not self.can_hide:
            self.expand()
            self.display(f'{SHORTCUT} is unavailable. Use Minimize to keep a small core on screen.')
            return
        if self.voice_enabled.get():
            self.stop_voice()
        self.root.withdraw()
        self.hidden = True

    def voice_toggled(self):
        if not self.voice_enabled.get():
            self.stop_voice()
        elif self.status in ('idle', 'complete', 'error'):
            self.start_listening()

    def stop_voice(self):
        self.job += 1
        self.voice_enabled.set(False)
        self.retry_mic_at = 0.
        self.active_until = 0.
        self.close_microphone()
        self.diagnostics.set('Microphone muted')
        if self.playback:
            self.playback.close()
            self.playback = None
        self.waveform, self.energy, self.progress = (), 0.0, 0.0
        self.change_state('idle')

    def escape(self):
        if self.voice_enabled.get():
            self.stop_voice()
        else:
            self.expand(False)

    def activate_core(self):
        if self.compact:
            self.compact = False
            return
        if self.status in ('listening', 'standby'):
            self.finish_listening()
            return
        if self.status in ('thinking', 'executing'):
            return
        if not self.voice_enabled.get():
            self.expand()
            self.display('Check Hands-free voice to start listening. You can also type below.')
            return
        if self.status == 'speaking':
            self.stop_voice()
            return
        self.start_listening()

    def close_microphone(self):
        if self.mic:
            self.mic.close()
            self.mic = None
        self.capture = None
        self.pending_pcm = bytearray()

    def select_microphone(self, event=None):
        if self.mic or self.retry_mic_at:
            self.close_microphone()
            self.start_listening()

    def refresh_microphones(self):
        if self.mic_factory is Microphone:
            devices = dict(input_devices())
            selected = self.device.get()
            if selected not in devices:
                devices[selected] = self.devices.get(selected)
            self.devices = devices
            self.microphone_selector.configure(values=list(devices))

    def start_listening(self):
        if self.mic:
            return
        try:
            if self.mic_factory is Microphone:
                devices = dict(input_devices())
                self.devices.update(devices)
                label = self.device.get()
                if label not in devices:
                    matches = [name for name in devices if name.rsplit(' [', 1)[0] == label.rsplit(' [', 1)[0]]
                    if len(matches) != 1:
                        raise RuntimeError('Selected microphone is disconnected.')
                    label = matches[0]
                    self.device.set(label)
                self.mic = self.mic_factory(devices[label])
            else:
                self.mic = self.mic_factory()
        except (RuntimeError, OSError) as error:
            self.microphone_failed(error)
            return
        self.retry_mic_at = 0.
        self.capture = Listening(*self.speech_settings[:3])
        self.pending_pcm = bytearray()
        self.last_input_at = time.monotonic()
        self.update_listening_state()

    def update_listening_state(self):
        if self.playback:
            self.change_state('speaking')
        elif self.wake_enabled and time.monotonic() >= self.active_until:
            self.change_state('standby', 'Standby · Say “Jarvis”')
        else:
            self.change_state('listening', 'Hands-free listening')

    def microphone_failed(self, error):
        self.close_microphone()
        self.retry_mic_at = time.monotonic() + MIC_RETRY_SECONDS
        self.diagnostics.set('Microphone unavailable · Reconnecting')
        if not self.playback:
            self.change_state('standby', 'Reconnecting microphone')
            self.expand()
            self.display(str(error))

    def read_microphone(self, now):
        pcm = self.mic.read()
        if pcm:
            self.last_input_at = now
        elif now - self.last_input_at >= MIC_RETRY_SECONDS:
            self.microphone_failed('No input from the microphone.')
            return
        if not self.playback and self.capture.candidate is None and self.status == 'listening':
            if self.wake_enabled and now >= self.active_until:
                self.update_listening_state()
        self.capture.silence = .60 if self.status == 'standby' else self.speech_settings[2]
        self.pending_pcm.extend(pcm)
        while len(self.pending_pcm) >= BLOCK * 2:
            chunk = bytes(self.pending_pcm[:BLOCK * 2])
            del self.pending_pcm[:BLOCK * 2]
            echo_found = False
            if self.playback:
                chunk, echo_found = self.playback.cancel_echo(chunk)
            done = self.capture.push(chunk, playback=bool(self.playback), echo_found=echo_found)
            self.waveform, self.energy = self.capture.waveform, self.capture.level
            noise = 20 * math.log10(max(self.capture.noise, .00001))
            level = 20 * math.log10(max(self.energy, .00001))
            self.diagnostics.set(f'Input {level:.0f} dBFS  ·  Noise {noise:.0f} dBFS  ·  {self.transcription}')
            if self.playback and self.capture.start is not None:
                self.playback.close()
                self.playback = None
                self.progress = 0.
                self.active_until = now + FOLLOW_UP_SECONDS
                self.update_listening_state()
            if done:
                self.finish_listening()
                break

    def finish_listening(self):
        if not self.capture or self.capture.start is None:
            self.expand()
            self.display('No speech detected yet. JARVIS is still listening.')
            return
        wake = self.status == 'standby'
        wav = voice.pcm_wave(self.capture.take())
        self.close_microphone()
        self.waveform, self.energy = (), 0.
        self.job += 1
        if wake:
            self.change_state('standby', 'Checking wake word locally')
            self.run('wake', lambda: voice.listen_locally(
                wav, approved=True, wake_sensitivity=self.speech_settings[3]))
        else:
            self.change_state('thinking', 'Transcribing your recording')
            self.expand()
            self.display('Transcribing your microphone recording…')
            self.run('transcript', lambda: self.console.transcribe(wav))

    def send_entry(self):
        self.submit(self.entry.get())

    def submit(self, question):
        if self.status in ('thinking', 'executing', 'speaking'):
            return
        question = question.strip()
        if not question:
            return
        try:
            action, _ = tools.intent(question)
        except ValueError as error:
            self.failed(str(error))
            return
        self.retry_mic_at = 0.
        self.close_microphone()
        self.job += 1
        self.entry.delete(0, 'end')
        self.question = question
        self.expand(move_aside=action in TASKS)
        if action in TASKS:
            title, detail = TASKS[action]
            self.change_state('executing', title)
            self.display(detail)
        else:
            self.change_state('thinking', 'JARVIS is thinking')
            self.display(question + '\n\nWaiting for a reply…')
        history = self.history.copy()
        self.run('answer', lambda: self.console.ask(question, history))

    def run(self, kind, operation):
        token = self.job

        def worker():
            try:
                self.events.put((kind, token, operation()))
            except (RuntimeError, OSError, ValueError) as error:
                self.events.put(('failed', token, str(error)))
            except Exception:
                self.events.put(('failed', token, 'JARVIS could not read the response. Please try again.'))

        Thread(target=worker, daemon=True).start()

    def completed(self):
        self.waveform, self.energy, self.progress = (), 0.0, 0.0
        self.complete_until = time.monotonic() + .85
        self.change_state('complete', 'Reply ready')

    def failed(self, message):
        self.stop_voice()
        self.change_state('error')
        self.expand()
        self.display(message)

    def hear(self, transcript):
        self.change_state('idle')
        text = transcript.strip()
        words = ' '.join(re.findall(r'[^\W_]+', text.lower()))
        if re.fullmatch(r'(?:(?:hey )?jarvis )?(?:stop listening|mute (?:the )?microphone)', words):
            self.stop_voice()
            self.display('Microphone stopped by voice command.')
            return
        if not self.voice_enabled.get() or self.hidden:
            return
        if not words:
            self.display('I didn’t catch that. Could you repeat what you said?')
        elif len(text) > 4000:
            self.display('That recording was too long. Try a shorter question.')
        else:
            self.active_until = time.monotonic() + FOLLOW_UP_SECONDS
            self.submit(text)
            return
        self.start_listening()

    def process_events(self):
        while True:
            try:
                kind, token, result = self.events.get_nowait()
            except Empty:
                return
            if kind == 'shortcut':
                self.can_hide = result
            elif kind == 'toggle':
                self.toggle_visibility()
            elif token != self.job:
                continue
            elif kind == 'failed':
                self.failed(result)
            elif kind == 'wake':
                if result and self.voice_enabled.get():
                    self.active_until = time.monotonic() + FOLLOW_UP_SECONDS
                    self.display('Listening. What can I do for you?')
                self.start_listening()
            elif kind == 'transcript':
                self.transcription = result.get('provider', 'Transcript')
                if result.get('uncertain'):
                    self.transcription += ' · unclear'
                self.hear(result['text'])
            elif kind == 'answer':
                text = result['answer']
                if not result.get('model_missing'):
                    self.history = [*self.history, {'role': 'user', 'content': self.question},
                                    {'role': 'assistant', 'content': text}][-20:]
                self.display(self.question + '\n\n' + text)
                if self.voice_enabled.get() and not self.hidden and result.get('spoken', '').strip():
                    self.change_state('thinking', 'Preparing spoken reply')
                    self.run('audio', lambda text=result['spoken']: self.console.speech(text))
                else:
                    self.completed()
            elif kind == 'audio' and self.voice_enabled.get() and not self.hidden:
                try:
                    self.playback = self.playback_factory(result)
                    self.change_state('speaking')
                    self.start_listening()
                except (RuntimeError, OSError, ValueError, wave.Error) as error:
                    self.failed(f'Audio unavailable · {error}')
            elif kind == 'audio':
                self.completed()

    def tick(self):
        if self.closed:
            return
        now = time.monotonic()
        elapsed = min(.05, now - self.last_frame)
        self.last_frame = now
        self.process_events()
        if self.mic:
            try:
                self.read_microphone(now)
            except (RuntimeError, OSError, ValueError) as error:
                self.microphone_failed(error)
        if self.playback:
            try:
                if self.playback.done:
                    self.playback.close()
                    self.playback = None
                    self.progress = 0.
                    self.active_until = now + FOLLOW_UP_SECONDS
                    self.update_listening_state()
                else:
                    self.progress, peaks, energy = self.playback.snapshot()
                    if not self.mic or self.capture.candidate is None:
                        self.waveform, self.energy = peaks, energy
            except (RuntimeError, OSError, ValueError) as error:
                self.failed(str(error))
        if self.retry_mic_at and now >= self.retry_mic_at and self.voice_enabled.get() and not self.hidden:
            self.start_listening()
        if self.status == 'complete' and now >= self.complete_until:
            self.change_state('idle')
            if self.voice_enabled.get() and not self.hidden:
                self.start_listening()
        for spring in (self.x, self.y, self.panel):
            if self.reduced:
                spring.value, spring.velocity = spring.target, 0
            else:
                spring.advance(elapsed)
        if not self.hidden:
            self.place()
            self.hud.draw(self.side, self.status, self.compact, self.panel.value, self.waveform,
                          self.energy, self.progress, now, elapsed, self.reduced,
                          max(0, (self.complete_until - now) / .85))
            edge = core_x(self.side) + (107 if self.side == 1 else -107 - PANEL_W)
            self.canvas.coords(self.panel_window, edge + 11, PANEL_Y + 10)
            state = 'normal' if self.panel.target and self.panel.value >= .985 else 'hidden'
            self.canvas.itemconfigure(self.panel_window, state=state)
            if state == 'normal':
                self.canvas.tag_raise(self.panel_window)
        self.root.after(25 if not self.hidden else 80, self.tick)

    def close(self):
        self.closed = True
        self.stop_voice()
        self.root.destroy()


def main():
    if os.name != 'nt':
        raise SystemExit('The floating JARVIS desktop requires Windows.')
    try:
        ct.windll.user32.SetProcessDpiAwarenessContext(ct.c_void_p(-4))
    except AttributeError:
        pass
    root = tk.Tk()
    Desktop(root)
    root.mainloop()


if __name__ == '__main__':
    main()
