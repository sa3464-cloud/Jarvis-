"""Server-only ElevenLabs client. No third-party Python dependencies."""
import json
import os
import re
import secrets
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
MAX_AUDIO = 12 * 1024 * 1024
MAX_TEXT = 4000


def settings():
    values = {}
    path = ROOT / '.env'
    if path.is_file():
        for line in path.read_text(encoding='utf-8').splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                key, value = line.split('=', 1)
                values[key.strip()] = value.strip().strip('\"\'')
    return {**values, **os.environ}


def configured():
    return bool(settings().get('ELEVENLABS_API_KEY'))


def _request(path, body, content_type, accept):
    key = settings().get('ELEVENLABS_API_KEY')
    if not key:
        raise RuntimeError('ElevenLabs key missing. Set ELEVENLABS_API_KEY in jarvis/.env.')
    request = Request('https://api.elevenlabs.io' + path, data=body, headers={
        'xi-api-key': key, 'Content-Type': content_type, 'Accept': accept,
    }, method='POST')
    try:
        with urlopen(request, timeout=60) as response:
            result = response.read(20 * 1024 * 1024 + 1)
            if len(result) > 20 * 1024 * 1024:
                raise RuntimeError('ElevenLabs response exceeded the size limit.')
            return result
    except HTTPError as error:
        if error.code == 400:
            try:
                detail = json.loads(error.read(16384)).get('detail', {})
                if isinstance(detail, dict) and detail.get('status') == 'api_key_id_used_as_api_key':
                    raise RuntimeError('The configured ElevenLabs value is a key ID. Replace it with the secret API key in jarvis/.env.') from None
            except (ValueError, AttributeError):
                pass
        messages = {401: 'ElevenLabs rejected the key.', 403: 'ElevenLabs permission denied.',
                    402: 'ElevenLabs credits unavailable.', 429: 'ElevenLabs rate or credit limit reached.'}
        raise RuntimeError(messages.get(error.code, f'ElevenLabs returned HTTP {error.code}.')) from None
    except (URLError, TimeoutError, OSError):
        raise RuntimeError('ElevenLabs unavailable. Check your connection and try again.') from None


def speak(text, *, approved=False):
    if not approved:
        raise PermissionError('Approve ElevenLabs credit use before generating speech.')
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT:
        raise ValueError(f'Speech text must contain 1–{MAX_TEXT} characters.')
    config = settings()
    # Eldrin — Crisp British Baritone, a male British English voice.
    voice = config.get('ELEVENLABS_VOICE_ID', '6WwXjDDEMyNmFG95zycZ')
    body = json.dumps({'text': text, 'model_id': config.get('ELEVENLABS_TTS_MODEL', 'eleven_multilingual_v2')}).encode()
    return _request('/v1/text-to-speech/' + quote(voice, safe='') + '?output_format=mp3_44100_128',
                    body, 'application/json', 'audio/mpeg')


def listen(audio, mime='audio/webm', *, approved=False):
    if not approved:
        raise PermissionError('Approve ElevenLabs credit use before transcription.')
    extensions = {'audio/webm': 'webm', 'audio/ogg': 'ogg', 'audio/mp4': 'mp4', 'audio/wav': 'wav', 'audio/mpeg': 'mp3'}
    mime = mime.split(';', 1)[0].strip().lower()
    if mime not in extensions or not audio or len(audio) > MAX_AUDIO:
        raise ValueError('Audio must be a supported recording under 12 MB.')
    boundary = 'jarvis' + secrets.token_hex(16)
    model = settings().get('ELEVENLABS_STT_MODEL', 'scribe_v1')
    if not re.fullmatch(r'[a-zA-Z0-9_]+', model):
        raise ValueError('Invalid transcription model configuration.')
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="model_id"\r\n\r\n{model}\r\n'
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="recording.{extensions[mime]}"\r\n'
            f'Content-Type: {mime}\r\n\r\n').encode() + audio + f'\r\n--{boundary}--\r\n'.encode()
    try:
        result = json.loads(_request('/v1/speech-to-text', body, f'multipart/form-data; boundary={boundary}', 'application/json'))
        text = result['text']
        if not isinstance(text, str):
            raise ValueError()
        return text
    except (ValueError, KeyError, TypeError):
        raise RuntimeError('ElevenLabs returned an invalid transcript.') from None
