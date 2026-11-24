"""Server-only ElevenLabs client. No third-party Python dependencies."""
import io
import json
import os
import re
import secrets
import subprocess
import wave
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
MAX_AUDIO = 12 * 1024 * 1024
MAX_TEXT = 4000


class ElevenLabsQuotaError(RuntimeError):
    """ElevenLabs cannot process the voice request with the available credits."""


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
        codes = ()
        try:
            with error:
                payload = json.loads(error.read(16384))
            detail = payload.get('detail', payload)
            if isinstance(detail, dict):
                codes = (detail.get('status'), detail.get('code'))
        except (ValueError, AttributeError, OSError):
            pass
        if error.code == 402 or 'quota_exceeded' in codes or 'insufficient_credits' in codes:
            raise ElevenLabsQuotaError('ElevenLabs credits are unavailable. Check your usage and API key credit limit.') from None
        if 'api_key_id_used_as_api_key' in codes:
            raise RuntimeError('The configured ElevenLabs value is a key ID. Replace it with the secret API key in jarvis/.env.') from None
        if 'missing_permissions' in codes or 'insufficient_permissions' in codes:
            feature = 'Speech to Text' if path == '/v1/speech-to-text' else 'Text to Speech'
            raise RuntimeError(f'The ElevenLabs API key needs the {feature} permission.') from None
        messages = {401: 'ElevenLabs rejected the key.', 403: 'ElevenLabs permission denied.',
                    429: 'ElevenLabs rate limit reached.'}
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


def _windows_speech(script, input_bytes, failure_message, timeout):
    if os.name != 'nt':
        raise RuntimeError('ElevenLabs credits are unavailable. The built-in speech fallback requires Windows.')

    powershell = Path(os.environ.get('SystemRoot', r'C:\Windows'))
    powershell /= 'System32/WindowsPowerShell/v1.0/powershell.exe'
    setup = '''
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
'''
    try:
        result = subprocess.run(
            [str(powershell), '-NoLogo', '-NoProfile', '-NonInteractive', '-Command', setup + script],
            input=input_bytes, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError(failure_message) from None
    if result.returncode:
        raise RuntimeError(failure_message)
    return result.stdout


def speak_locally(text):
    """Render a WAV with the installed Windows voice, entirely in memory."""
    unavailable = 'ElevenLabs credits are unavailable, and the built-in Windows voice could not generate audio.'
    # User text is passed on stdin, separate from the PowerShell command.
    script = '''
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
$voice = New-Object System.Speech.Synthesis.SpeechSynthesizer
$audio = New-Object System.IO.MemoryStream
try {
    $voice.SetOutputToWaveStream($audio)
    $voice.Speak([Console]::In.ReadToEnd())
    $voice.SetOutputToNull()
    $audio.WriteTo([Console]::OpenStandardOutput())
} finally {
    $voice.Dispose()
    $audio.Dispose()
}
'''
    audio = _windows_speech(script, text.encode('utf-8', errors='replace'), unavailable, timeout=20)
    if audio[:4] != b'RIFF' or audio[8:12] != b'WAVE':
        raise RuntimeError(unavailable)
    return audio


def listen_locally(audio, *, approved=False):
    """Recognize a short 16 kHz mono WAV with the installed Windows recognizer."""
    if not approved:
        raise PermissionError('Enable voice for this session before transcribing audio.')
    invalid = 'Local transcription requires mono, 16-bit, 16 kHz WAV audio up to 31 seconds long.'
    try:
        with wave.open(io.BytesIO(audio), 'rb') as recording:
            frames = recording.getnframes()
            if (recording.getnchannels(), recording.getsampwidth(), recording.getframerate()) != (1, 2, 16000):
                raise ValueError(invalid)
            if not 0 < frames <= 31 * 16000:
                raise ValueError(invalid)
            samples = recording.readframes(frames)
    except (wave.Error, EOFError):
        raise ValueError(invalid) from None
    if len(samples) != frames * 2:
        raise ValueError(invalid)

    script = '''
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$engine = [System.Speech.Recognition.SpeechRecognitionEngine]::new()
$audio = [System.IO.MemoryStream]::new()
try {
    [Console]::OpenStandardInput().CopyTo($audio)
    $audio.Position = 0
    $format = [System.Speech.AudioFormat.SpeechAudioFormatInfo]::new(
        16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,
        [System.Speech.AudioFormat.AudioChannel]::Mono)
    $engine.SetInputToAudioStream($audio, $format)
    $engine.LoadGrammar([System.Speech.Recognition.DictationGrammar]::new())
    $engine.EndSilenceTimeout = [timespan]::FromMilliseconds(850)
    $engine.EndSilenceTimeoutAmbiguous = [timespan]::FromMilliseconds(900)
    $result = $engine.Recognize([timespan]::FromSeconds(30))
    if ($result) { [Console]::Write($result.Text) }
} finally {
    $engine.Dispose()
    $audio.Dispose()
}
'''
    unavailable = 'ElevenLabs credits are unavailable, and Windows could not transcribe the microphone recording.'
    return _windows_speech(script, samples, unavailable, timeout=40).decode('utf-8').strip()


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
