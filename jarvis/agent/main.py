"""Loopback-only voice console: python -m jarvis.agent.main."""
import json
import argparse
import secrets
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from . import data, voice, conversation, tools

UI = data.ROOT / 'ui'


class LocalServer(ThreadingHTTPServer):
    # Windows SO_REUSEADDR permits multiple servers to share a listening port,
    # leaving requests routed unpredictably between old and new app versions.
    allow_reuse_address = False

    def server_bind(self):
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, code, body, mime='application/json'):
        if not isinstance(body, bytes):
            body = json.dumps(body).encode()
        self.send_response(code)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def local_host(self):
        return self.headers.get('Host') == f'127.0.0.1:{self.server.server_port}'

    def do_GET(self):
        if not self.local_host():
            return self.reply(403, {'error': 'Use the printed 127.0.0.1 URL.'})
        path = urlparse(self.path).path
        if path == '/api/status':
            return self.reply(200, {'voice_configured': voice.configured(), 'csrf': self.server.csrf,
                                    'demo': data.status()['demo'], 'model': conversation.status()})
        files = {'/': ('voice.html', 'text/html; charset=utf-8'), '/voice.js': ('voice.js', 'text/javascript'),
                 '/voice.css': ('voice.css', 'text/css'), '/voice-capture.js': ('voice-capture.js', 'text/javascript')}
        if path not in files:
            return self.reply(404, {'error': 'Not found'})
        name, mime = files[path]
        self.reply(200, (UI / name).read_bytes(), mime)

    def do_POST(self):
        origin = f'http://127.0.0.1:{self.server.server_port}'
        if (not self.local_host() or self.headers.get('Origin') != origin or
                not secrets.compare_digest(self.headers.get('X-Jarvis-CSRF', ''), self.server.csrf)):
            return self.reply(403, {'error': 'Request must originate from the local JARVIS page.'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if length <= 0 or length > voice.MAX_AUDIO:
                return self.reply(413, {'error': 'Request size invalid; maximum 12 MB.'})
            self.connection.settimeout(120)
            body = self.rfile.read(length)
            if len(body) != length:
                raise ValueError('Incomplete request.')
            approved = self.headers.get('X-Jarvis-Voice-Approved') == 'yes'
            if self.path == '/api/listen':
                try:
                    text = voice.listen(body, self.headers.get('Content-Type', ''), approved=approved)
                except voice.ElevenLabsQuotaError as error:
                    return self.reply(402, {'error': str(error)})
                return self.reply(200, {'text': text})
            if self.path == '/api/listen/local':
                return self.reply(200, {'text': voice.listen_locally(body, approved=approved)})
            payload = json.loads(body)
            if self.path == '/api/chat':
                return self.reply(200, tools.execute(payload.get('question'), payload.get('history', [])))
            if self.path == '/api/speak':
                speech_text = payload.get('text')
                wav = payload.get('format') == 'wav'
                try:
                    audio = voice.speak(speech_text, approved=approved, wav=wav)
                except voice.ElevenLabsQuotaError:
                    return self.reply(200, voice.speak_locally(speech_text), 'audio/wav')
                return self.reply(200, audio, 'audio/wav' if wav else 'audio/mpeg')
            if self.path == '/api/inbox':
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
        print('Voice requests consume ElevenLabs credits only after approval in the page.', flush=True)
        server.serve_forever()


if __name__ == '__main__':
    main()
