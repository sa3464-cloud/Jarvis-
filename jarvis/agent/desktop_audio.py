"""In-memory Windows PCM I/O for the floating assistant."""
from array import array
import ctypes as ct
from collections import deque
import io
import math
import wave


MIC_RATE = 16000
DEFAULT_DEVICE = ct.c_uint32(-1)
BUFFER_DONE = 1
TIME_MS, TIME_SAMPLES, TIME_BYTES = 1, 2, 4


class WaveFormat(ct.Structure):
    _pack_ = 1
    _fields_ = [('format', ct.c_uint16), ('channels', ct.c_uint16),
                ('rate', ct.c_uint32), ('bytes_per_second', ct.c_uint32),
                ('alignment', ct.c_uint16), ('bits', ct.c_uint16), ('extra', ct.c_uint16)]


class WaveHeader(ct.Structure):
    _fields_ = [('data', ct.c_void_p), ('size', ct.c_uint32), ('recorded', ct.c_uint32),
                ('user', ct.c_size_t), ('flags', ct.c_uint32), ('loops', ct.c_uint32),
                ('next', ct.c_void_p), ('reserved', ct.c_size_t)]


class MediaTime(ct.Structure):
    # MMTIME consists of a type and a union that occupies eight bytes.
    _fields_ = [('kind', ct.c_uint32), ('value', ct.c_uint32), ('unused', ct.c_uint32)]


def _format(rate, channels=1):
    return WaveFormat(1, channels, rate, rate * channels * 2, channels * 2, 16, 0)


def _buffer(size, data=None):
    memory = ct.create_string_buffer(data, size) if data is not None else ct.create_string_buffer(size)
    return memory, WaveHeader(ct.addressof(memory), size)


def _check(code, operation):
    if code:
        raise RuntimeError(f'Windows could not {operation} (audio error {code}).')


def signal(samples, points=34):
    """Return signed peaks and RMS energy for a short window of PCM samples."""
    if not samples:
        return (), 0.0
    block = max(1, len(samples) // points)
    peaks = tuple(max(samples[i:i + block], key=abs) / 32768
                  for i in range(0, len(samples), block))[:points]
    energy = math.sqrt(sum(sample * sample for sample in samples) / len(samples)) / 32768
    return peaks, energy


def microphone_signal(pcm):
    return signal(array('h', pcm[-1280:]))


class Microphone:
    def __init__(self):
        self.api = ct.WinDLL('winmm')
        self.handle = ct.c_void_p()
        self.buffers = deque()
        self.prepared = []
        _check(self.api.waveInOpen(ct.byref(self.handle), DEFAULT_DEVICE, ct.byref(_format(MIC_RATE)),
                                   ct.c_size_t(0), ct.c_size_t(0), 0), 'open the microphone')
        try:
            for _ in range(8):
                slot = _buffer(MIC_RATE // 25 * 2)
                self._header('PrepareHeader', slot)
                self.prepared.append(slot)
                self._header('AddBuffer', slot)
                self.buffers.append(slot)
            _check(self.api.waveInStart(self.handle), 'start the microphone')
        except RuntimeError:
            self.close()
            raise

    def _header(self, operation, slot):
        action = getattr(self.api, 'waveIn' + operation)
        header = slot[1]
        _check(action(self.handle, ct.byref(header), ct.sizeof(header)), 'buffer the microphone')

    def read(self):
        ready = []
        while self.buffers and self.buffers[0][1].flags & BUFFER_DONE:
            slot = self.buffers.popleft()
            memory, header = slot
            ready.append(memory.raw[:header.recorded])
            header.recorded = 0
            self._header('AddBuffer', slot)
            self.buffers.append(slot)
        return b''.join(ready)

    def finish(self):
        if not self.handle:
            return b''
        self.api.waveInReset(self.handle)
        tail = b''.join(memory.raw[:header.recorded] for memory, header in self.buffers)
        self.close()
        return tail

    def close(self):
        if not self.handle:
            return
        self.api.waveInReset(self.handle)
        for _, header in self.prepared:
            self.api.waveInUnprepareHeader(self.handle, ct.byref(header), ct.sizeof(header))
        self.api.waveInClose(self.handle)
        self.handle = ct.c_void_p()
        self.buffers.clear()
        self.prepared.clear()


class Playback:
    def __init__(self, wav):
        with wave.open(io.BytesIO(wav), 'rb') as track:
            self.rate = track.getframerate()
            self.channels = track.getnchannels()
            self.frames = track.getnframes()
            if track.getsampwidth() != 2 or self.channels not in (1, 2) or not self.frames:
                raise ValueError('JARVIS gave Windows an unsupported audio format.')
            pcm = track.readframes(self.frames)
        if len(pcm) != self.frames * self.channels * 2:
            raise ValueError('JARVIS received an incomplete audio reply.')
        self.samples = array('h', pcm)[::self.channels]
        self.api = ct.WinDLL('winmm')
        self.handle = ct.c_void_p()
        self.memory, self.header = _buffer(len(pcm), pcm)
        self.prepared = False
        config = _format(self.rate, self.channels)
        _check(self.api.waveOutOpen(ct.byref(self.handle), DEFAULT_DEVICE, ct.byref(config),
                                    ct.c_size_t(0), ct.c_size_t(0), 0), 'open audio playback')
        try:
            header, size = ct.byref(self.header), ct.sizeof(self.header)
            _check(self.api.waveOutPrepareHeader(self.handle, header, size), 'prepare audio playback')
            self.prepared = True
            _check(self.api.waveOutWrite(self.handle, header, size), 'play the reply')
        except RuntimeError:
            self.close()
            raise

    @property
    def done(self):
        return bool(self.header.flags & BUFFER_DONE)

    def position(self):
        cursor = MediaTime(TIME_SAMPLES)
        _check(self.api.waveOutGetPosition(self.handle, ct.byref(cursor), ct.sizeof(cursor)),
               'read the audio playback position')
        if cursor.kind == TIME_BYTES:
            return cursor.value // (2 * self.channels)
        if cursor.kind == TIME_MS:
            return cursor.value * self.rate // 1000
        return cursor.value

    def snapshot(self):
        position = min(self.position(), self.frames)
        radius = self.rate // 48
        peaks, energy = signal(self.samples[max(0, position - radius):min(position + radius, self.frames)])
        return position / self.frames, peaks, energy

    def close(self):
        if not self.handle:
            return
        self.api.waveOutReset(self.handle)
        if self.prepared:
            self.api.waveOutUnprepareHeader(self.handle, ct.byref(self.header), ct.sizeof(self.header))
        self.api.waveOutClose(self.handle)
        self.handle = ct.c_void_p()
