"""Server-only voice providers. No third-party Python dependencies."""
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
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

ROOT = Path(__file__).resolve().parents[1]
MAX_AUDIO = 12 * 1024 * 1024
MAX_TEXT = 4000
MAX_OUTPUT = 20 * 1024 * 1024
FISH_TTS_MODEL = 's2.1-pro-free'


class SpeechFallback(RuntimeError):
    """Use the installed Windows voice if cloud speech is unavailable."""


class ElevenLabsQuotaError(SpeechFallback):
    """ElevenLabs cannot process the voice request with the available credits."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class WindowsSpeechError(RuntimeError):
    def __init__(self, reason, message):
        super().__init__(message)
        self.reason = reason


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


def _output_provider(config):
    return config.get('JARVIS_TTS_PROVIDER', 'elevenlabs').strip().lower() or 'elevenlabs'


def output_status():
    config = settings()
    provider = _output_provider(config)
    if provider == 'fish_audio':
        ready = bool(config.get('FISH_API_KEY') and config.get('FISH_AUDIO_REFERENCE_ID'))
    else:
        ready = provider == 'elevenlabs' and bool(config.get('ELEVENLABS_API_KEY'))
    return {'tts_provider': provider if provider in ('fish_audio', 'elevenlabs') else 'unavailable',
            'tts_configured': ready}


def _request(path, body, content_type, accept):
    key = settings().get('ELEVENLABS_API_KEY')
    if not key:
        raise RuntimeError('ElevenLabs key missing. Set ELEVENLABS_API_KEY in jarvis/.env.')
    request = Request('https://api.elevenlabs.io' + path, data=body, headers={
        'xi-api-key': key, 'Content-Type': content_type, 'Accept': accept,
    }, method='POST')
    try:
        with urlopen(request, timeout=60) as response:
            result = response.read(MAX_OUTPUT + 1)
            if len(result) > MAX_OUTPUT:
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


def pcm_wave(pcm, sample_rate=16000):
    """Wrap signed 16-bit mono PCM in a WAV container."""
    if not pcm or len(pcm) % 2:
        raise ValueError('Invalid PCM audio.')
    output = io.BytesIO()
    with wave.open(output, 'wb') as recording:
        recording.setparams((1, 2, sample_rate, 0, 'NONE', 'not compressed'))
        recording.writeframes(pcm)
    return output.getvalue()


def _fish_speech(config, text, wav):
    key = config.get('FISH_API_KEY')
    reference_id = config.get('FISH_AUDIO_REFERENCE_ID')
    if not key:
        raise SpeechFallback('Fish Audio key missing. Set FISH_API_KEY in jarvis/.env.')
    if not reference_id:
        raise SpeechFallback('Fish Audio voice missing. Set FISH_AUDIO_REFERENCE_ID in jarvis/.env.')
    body = {'text': text, 'reference_id': reference_id, 'format': 'pcm' if wav else 'mp3'}
    if wav:
        body['sample_rate'] = 16000
    request = Request('https://api.fish.audio/v1/tts', data=json.dumps(body).encode(),
                      headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json',
                               'model': FISH_TTS_MODEL}, method='POST')
    try:
        with build_opener(NoRedirect()).open(request, timeout=60) as response:
            audio = response.read(MAX_OUTPUT + 1)
            mime = response.headers.get_content_type()
    except HTTPError as error:
        error.close()
        messages = {
            401: 'Fish Audio rejected the API key.',
            402: 'Fish Audio speech credit is unavailable.',
            403: 'Fish Audio denied access to this voice or model.',
            404: 'Fish Audio could not find the configured voice.',
            429: 'Fish Audio reached its rate limit.',
        }
        raise SpeechFallback(messages.get(error.code, f'Fish Audio returned HTTP {error.code}.')) from None
    except (URLError, TimeoutError, OSError, ValueError):
        raise SpeechFallback('Fish Audio could not complete the speech request.') from None
    if not audio or len(audio) > MAX_OUTPUT or not (mime.startswith('audio/') or mime == 'application/octet-stream'):
        raise SpeechFallback('Fish Audio did not return usable audio.')
    if wav:
        if len(audio) % 2:
            raise SpeechFallback('Fish Audio returned incomplete PCM audio.')
        return pcm_wave(audio)
    return audio


def speak(text, *, approved=False, wav=False):
    if not approved:
        raise PermissionError('Enable voice for this session before generating speech.')
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT:
        raise ValueError(f'Speech text must contain 1–{MAX_TEXT} characters.')
    config = settings()
    provider = _output_provider(config)
    if provider == 'fish_audio':
        return _fish_speech(config, text, wav)
    if provider != 'elevenlabs':
        raise SpeechFallback('JARVIS_TTS_PROVIDER must be fish_audio or elevenlabs.')
    # Eldrin — Crisp British Baritone, a male British English voice.
    voice = config.get('ELEVENLABS_VOICE_ID', '6WwXjDDEMyNmFG95zycZ')
    body = json.dumps({'text': text, 'model_id': config.get('ELEVENLABS_TTS_MODEL', 'eleven_multilingual_v2')}).encode()
    audio_format = 'pcm_16000' if wav else 'mp3_44100_128'
    accept = 'audio/pcm' if wav else 'audio/mpeg'
    audio = _request('/v1/text-to-speech/' + quote(voice, safe='') + '?output_format=' + audio_format,
                     body, 'application/json', accept)
    return pcm_wave(audio) if wav else audio


def _windows_speech(script, input_bytes, failure_message, timeout):
    if os.name != 'nt':
        raise RuntimeError('The built-in speech fallback requires Windows.')

    powershell = Path(os.environ.get('SystemRoot', r'C:\Windows'))
    powershell /= 'System32/WindowsPowerShell/v1.0/powershell.exe'
    setup = '''
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
'''
    try:
        result = subprocess.run(
            [str(powershell), '-NoLogo', '-NoProfile', '-NonInteractive', '-Command', setup + script],
            input=input_bytes, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        raise WindowsSpeechError('timeout', failure_message) from None
    except OSError:
        raise WindowsSpeechError('launch', failure_message) from None
    if result.returncode:
        reason = 'missing_recognizer' if b'JARVIS_NO_RECOGNIZER' in result.stderr else 'engine'
        raise WindowsSpeechError(reason, failure_message)
    return result.stdout


def speak_locally(text):
    """Render a WAV with the installed Windows voice, entirely in memory."""
    unavailable = 'The built-in Windows voice could not generate audio.'
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
try {
    $engine = [System.Speech.Recognition.SpeechRecognitionEngine]::new()
} catch {
    $installed = [System.Speech.Recognition.SpeechRecognitionEngine]::InstalledRecognizers()
    if ($installed.Count -eq 0) {
        [Console]::Error.WriteLine('JARVIS_NO_RECOGNIZER')
        exit 1
    }
    $engine = [System.Speech.Recognition.SpeechRecognitionEngine]::new($installed[0].Id)
}
$audio = [System.IO.MemoryStream]::new()
try {
    [Console]::OpenStandardInput().CopyTo($audio)
    $audio.Position = 0
    # INPUT_SETUP
    $engine.LoadGrammar([System.Speech.Recognition.DictationGrammar]::new())
    $engine.EndSilenceTimeout = [timespan]::FromMilliseconds(1500)
    $engine.EndSilenceTimeoutAmbiguous = [timespan]::FromMilliseconds(1750)
    $result = $engine.Recognize([timespan]::FromSeconds(30))
    if ($result -and $result.Confidence -ge 0.35) { [Console]::Write($result.Text) }
} finally {
    $engine.Dispose()
    $audio.Dispose()
}
'''
    raw_input = '''
    $format = [System.Speech.AudioFormat.SpeechAudioFormatInfo]::new(
        16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,
        [System.Speech.AudioFormat.AudioChannel]::Mono)
    $engine.SetInputToAudioStream($audio, $format)
'''
    unavailable = 'Windows could not process this recording. Try a short sentence, or type your question.'
    try:
        result = _windows_speech(script.replace('# INPUT_SETUP', raw_input), samples, unavailable, timeout=40)
    except WindowsSpeechError as error:
        if error.reason in ('launch', 'missing_recognizer'):
            raise RuntimeError(_recognition_message(error)) from None
        # A fresh Windows engine can read the same validated data as a WAV file.
        alternate = script.replace('# INPUT_SETUP', '$engine.SetInputToWaveStream($audio)')
        try:
            result = _windows_speech(alternate, pcm_wave(samples), unavailable, timeout=40)
        except WindowsSpeechError as retry:
            raise RuntimeError(_recognition_message(retry)) from None
    return result.decode('utf-8').strip()


def _recognition_message(error):
    return {
        'timeout': 'Windows transcription timed out. Try a shorter sentence, or type your question.',
        'launch': 'JARVIS could not start Windows transcription. You can still type a question.',
        'missing_recognizer': 'Windows has no offline speech recognizer installed. You can still type a question.',
    }.get(error.reason, str(error))


def listen(audio, mime='audio/webm', *, approved=False):
    if not approved:
        raise PermissionError('Approve ElevenLabs credit use before transcription.')
    extensions = {'audio/webm': 'webm', 'audio/ogg': 'ogg', 'audio/mp4': 'mp4', 'audio/wav': 'wav', 'audio/mpeg': 'mp3'}
    mime = mime.split(';', 1)[0].strip().lower()
    if mime not in extensions or not audio or len(audio) > MAX_AUDIO:
        raise ValueError('Audio must be a supported recording under 12 MB.')
    boundary = 'jarvis' + secrets.token_hex(16)
    config = settings()
    model = config.get('ELEVENLABS_STT_MODEL', 'scribe_v2')
    if not re.fullmatch(r'[a-zA-Z0-9_]+', model):
        raise ValueError('Invalid transcription model configuration.')
    language = config.get('ELEVENLABS_STT_LANGUAGE', 'eng').strip().lower()
    fields = {'model_id': model, 'tag_audio_events': 'false'}
    if language != 'auto':
        if not re.fullmatch(r'[a-z]{2,3}', language):
            raise ValueError('Use a two- or three-letter transcription language code, or auto.')
        fields['language_code'] = language
    prefix = ''.join(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'
                     for name, value in fields.items())
    header = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="recording.{extensions[mime]}"\r\n'
              f'Content-Type: {mime}\r\n\r\n')
    body = (prefix + header).encode() + audio + f'\r\n--{boundary}--\r\n'.encode()
    try:
        result = json.loads(_request('/v1/speech-to-text', body, f'multipart/form-data; boundary={boundary}', 'application/json'))
        text = result['text']
        if not isinstance(text, str):
            raise ValueError()
        return text
    except (ValueError, KeyError, TypeError):
        raise RuntimeError('ElevenLabs returned an invalid transcript.') from None
