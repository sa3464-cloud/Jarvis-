import io
import json
import unittest
import wave
from unittest.mock import patch
from urllib.error import HTTPError

from jarvis.agent import voice


class SpeechErrorsTest(unittest.TestCase):
    def provider_failure(self, status, reason):
        body = json.dumps({'detail': {'status': reason}}).encode()
        return HTTPError('https://api.elevenlabs.io/', status, '', {}, io.BytesIO(body))

    def test_quota_401_triggers_the_quota_error(self):
        error = self.provider_failure(401, 'quota_exceeded')
        with (
            patch.object(voice, 'settings', return_value={'ELEVENLABS_API_KEY': 'test-key'}),
            patch.object(voice, 'urlopen', side_effect=error),
            self.assertRaises(voice.ElevenLabsQuotaError),
        ):
            voice.speak('Test', approved=True)

    def test_invalid_key_keeps_the_key_error(self):
        error = self.provider_failure(401, 'invalid_api_key')
        with (
            patch.object(voice, 'settings', return_value={'ELEVENLABS_API_KEY': 'test-key'}),
            patch.object(voice, 'urlopen', side_effect=error),
            self.assertRaisesRegex(RuntimeError, 'rejected the key'),
        ):
            voice.speak('Test', approved=True)


class WindowsMicrophoneTest(unittest.TestCase):
    def test_fallback_transcribes_only_the_audio_samples(self):
        samples = b'\x01\x00' * 16
        audio = io.BytesIO()
        with wave.open(audio, 'wb') as recording:
            recording.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
            recording.writeframes(samples)

        with patch.object(voice, '_windows_speech', return_value=b'Test') as recognize:
            self.assertEqual(voice.listen_locally(audio.getvalue(), approved=True), 'Test')
            self.assertEqual(recognize.call_args.args[1], samples)

    def test_fallback_rejects_invalid_audio_and_requires_approval(self):
        with patch.object(voice, '_windows_speech') as recognize:
            with self.assertRaises(ValueError):
                voice.listen_locally(b'not a recording', approved=True)
            with self.assertRaises(PermissionError):
                voice.listen_locally(b'not a recording')
            recognize.assert_not_called()
