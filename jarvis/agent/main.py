"""Loopback-only voice console: python -m jarvis.agent.main."""
import json
import argparse
import secrets
import socket
from threading import Lock
from time import monotonic
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from . import data, voice, conversation, tools

UI = data.ROOT / 'ui'
DASHBOARD_ASSETS = data.ROOT.parent / 'public-site' / 'dist'
PUBLIC_ORIGIN = 'https://seth-jarvis-command-center.sa3464.chatgpt.site'
EMBED_ACTIONS = {'chat', 'listen', 'listen/local', 'speak', 'speak/local', 'inbox', 'disconnect'}


class Pairing:
    """An in-memory, one-use invitation and one revocable embedded session."""
    code_lifetime = 5 * 60
    session_lifetime = 4 * 60 * 60

    def __init__(self):
        self.lock = Lock()
        self.invitation = ('', 0)
        self.session = ('', 0)

    def issue(self):
        with self.lock:
            code = secrets.token_urlsafe(18)
            self.invitation = (code, monotonic() + self.code_lifetime)
            return code

    @staticmethod
    def matches(value, record):
        token, expires = record
        return bool(token and monotonic() < expires and isinstance(value, str) and
                    value.isascii() and secrets.compare_digest(value, token))

    def connect(self, code):
        with self.lock:
            if not self.matches(code, self.invitation):
                return None
            self.invitation = ('', 0)
            token = secrets.token_urlsafe(32)
            self.session = (token, monotonic() + self.session_lifetime)
            return token

    def authorized(self, token):
        with self.lock:
            return self.matches(token, self.session)

    def revoke(self, token=None):
        with self.lock:
            if token is None:
                self.invitation = ('', 0)
            if token is None or self.matches(token, self.session):
                self.session = ('', 0)


class LocalServer(ThreadingHTTPServer):
    # Windows SO_REUSEADDR permits multiple servers to share a listening port,
    # leaving requests routed unpredictably between old and new app versions.
    allow_reuse_address = False

    def __init__(self, *args, **kwargs):
        self.pairing = Pairing()
        super().__init__(*args, **kwargs)

    def server_bind(self):
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, code, body, mime='application/json', *, speech_notice=None):
        if not isinstance(body, bytes):
            body = json.dumps(body).encode()
        self.send_response(code)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        if speech_notice:
            self.send_header('X-Jarvis-Voice-Notice', speech_notice)
        path = urlparse(self.path).path
        ancestors = PUBLIC_ORIGIN if code == 200 and path == '/embedded' else "'none'"
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; "
                         f"media-src 'self' blob:; connect-src 'self'; frame-ancestors {ancestors}")
        if code == 200 and path == '/embed-ready' and self.probe_origin():
            self.send_header('Access-Control-Allow-Origin', PUBLIC_ORIGIN)
            self.send_header('Vary', 'Origin')
            if self.command == 'OPTIONS':
                self.send_header('Access-Control-Allow-Methods', 'GET')
                self.send_header('Access-Control-Allow-Private-Network', 'true')
        self.end_headers()
        self.wfile.write(body)

    def local_host(self):
        return self.headers.get('Host') == f'127.0.0.1:{self.server.server_port}'

    def probe_origin(self):
        return self.local_host() and self.headers.get('Origin') == PUBLIC_ORIGIN

    def do_OPTIONS(self):
        if (urlparse(self.path).path == '/embed-ready' and self.probe_origin() and
                self.headers.get('Access-Control-Request-Method') == 'GET'):
            return self.reply(200, b'')
        return self.reply(403, {'error': 'This endpoint is local only.'})

    def console_status(self, token):
        return {'voice_configured': voice.configured(), 'csrf': token, 'demo': data.status()['demo'],
                'model': conversation.status(), **voice.output_status()}

    def do_GET(self):
        if not self.local_host():
            return self.reply(403, {'error': 'Use the printed 127.0.0.1 URL.'})
        path = urlparse(self.path).path
        if path == '/embed-ready':
            if self.probe_origin():
                return self.reply(200, {'ready': True})
            return self.reply(403, {'error': 'This endpoint is for the JARVIS site.'})
        if path == '/api/status':
            return self.reply(200, self.console_status(self.server.csrf))
        if path == '/embedded':
            html = (UI / 'voice.html').read_text(encoding='utf-8')
            html = html.replace('data-mode="standalone"', 'data-mode="embedded"', 1)
            return self.reply(200, html.encode('utf-8'), 'text/html; charset=utf-8')
        files = {'/': (UI / 'voice.html', 'text/html; charset=utf-8'),
                 '/voice.js': (UI / 'voice.js', 'text/javascript'),
                 '/voice.css': (DASHBOARD_ASSETS / 'style.css', 'text/css'),
                 '/dashboard.js': (DASHBOARD_ASSETS / 'dashboard.js', 'text/javascript'),
                 '/voice-capture.js': (UI / 'voice-capture.js', 'text/javascript')}
        if path not in files:
            return self.reply(404, {'error': 'Not found'})
        file, mime = files[path]
        self.reply(200, file.read_bytes(), mime)

    def do_POST(self):
        origin = f'http://127.0.0.1:{self.server.server_port}'
        path = urlparse(self.path).path
        token = self.headers.get('X-Jarvis-CSRF', '')
        embedded = path.startswith('/api/embed/')
        if not self.local_host() or self.headers.get('Origin') != origin:
            return self.reply(403, {'code': 'origin_required',
                                    'error': 'Open the local JARVIS URL or use the paired console.'})
        if embedded:
            action = path.removeprefix('/api/embed/')
            if action == 'connect':
                if self.headers.get('X-Jarvis-Embedded') != 'yes':
                    return self.reply(403, {'error': 'Connect from the embedded local console.'})
            elif action not in EMBED_ACTIONS:
                return self.reply(404, {'error': 'Not found'})
            elif not self.server.pairing.authorized(token):
                return self.reply(401, {'error': 'Pair this local console again to continue.'})
        elif not token.isascii() or not secrets.compare_digest(token, self.server.csrf):
            return self.reply(403, {'code': 'stale_session',
                                    # The running desktop client may still match the older prefix.
                                    'error': 'Request must originate from the local JARVIS page. '
                                             'Your session changed; refresh the console and try again.'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            limit = 1024 if path == '/api/embed/connect' else voice.MAX_AUDIO
            if length <= 0 or length > limit:
                return self.reply(413, {'error': 'Request size invalid; maximum 12 MB.'})
            self.connection.settimeout(120)
            body = self.rfile.read(length)
            if len(body) != length:
                raise ValueError('Incomplete request.')
            approved = self.headers.get('X-Jarvis-Voice-Approved') == 'yes'
            if path == '/api/embed-code':
                return self.reply(200, {'code': self.server.pairing.issue()})
            if path == '/api/embed-revoke':
                self.server.pairing.revoke()
                return self.reply(200, {'disconnected': True})
            if embedded:
                if action == 'connect':
                    session = self.server.pairing.connect(json.loads(body).get('code'))
                    if not session:
                        return self.reply(401, {'error': 'This code is invalid, expired, or used. Generate a new code on your PC.'})
                    return self.reply(200, self.console_status(session))
                if action == 'disconnect':
                    self.server.pairing.revoke(token)
                    return self.reply(200, {'disconnected': True})
                path = '/api/' + action
            if path == '/api/listen':
                try:
                    text = voice.listen(body, self.headers.get('Content-Type', ''), approved=approved)
                except voice.ElevenLabsQuotaError as error:
                    return self.reply(402, {'error': str(error)})
                return self.reply(200, {'text': text})
            if path == '/api/listen/local':
                return self.reply(200, {'text': voice.listen_locally(body, approved=approved)})
            payload = json.loads(body)
            if path == '/api/chat':
                return self.reply(200, tools.execute(payload.get('question'), payload.get('history', [])))
            if path == '/api/speak/local':
                return self.reply(200, voice.speak(payload.get('text'), approved=approved, local=True), 'audio/wav')
            if path == '/api/speak':
                speech_text = payload.get('text')
                wav = payload.get('format') == 'wav'
                try:
                    audio = voice.speak(speech_text, approved=approved, wav=wav)
                except voice.SpeechFallback as error:
                    return self.reply(200, voice.speak_locally(speech_text), 'audio/wav', speech_notice=str(error))
                return self.reply(200, audio, 'audio/wav' if wav else 'audio/mpeg')
            if path == '/api/inbox':
                result = tools.read_inbox()
                return self.reply(200, {**result['card'], 'spoken': result['spoken']})
            self.reply(404, {'error': 'Not found'})
        except PermissionError as error:
            self.reply(403, {'error': str(error)})
        except (ValueError, TypeError, AttributeError):
            self.reply(400, {'error': 'Invalid request.'})
        except RuntimeError as error:
            self.reply(502, {'error': str(error)})
        except (OSError, TimeoutError):
            self.reply(502, {'error': 'Connection failed or timed out. Try again.'})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8767)
    args = parser.parse_args()
    with LocalServer(('127.0.0.1', args.port), Handler) as server:
        server.csrf = secrets.token_urlsafe(32)
        print(f'JARVIS voice console: http://127.0.0.1:{server.server_port}', flush=True)
        print('Voice requests are made only after approval in the app.', flush=True)
        server.serve_forever()


if __name__ == '__main__':
    main()
