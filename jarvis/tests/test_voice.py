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
    def test_fallback_retries_with_canonical_wav_after_engine_error(self):
        samples = b'\x01\x00' * 16
        audio = voice.pcm_wave(samples)
        failure = voice.WindowsSpeechError('engine', 'An engine error occurred')
        with patch.object(voice, '_windows_speech', side_effect=[failure, b'Test']) as recognize:
            self.assertEqual(voice.listen_locally(audio, approved=True), 'Test')
        first, second = recognize.call_args_list
        self.assertEqual(first.args[1], samples)
        self.assertIn('SetInputToWaveStream', second.args[0])
        with wave.open(io.BytesIO(second.args[1]), 'rb') as recording:
            self.assertEqual(recording.readframes(16), samples)

    def test_missing_recognizer_has_actionable_error_and_no_retry(self):
        failure = voice.WindowsSpeechError('missing_recognizer', 'Offline recognition missing')
        with patch.object(voice, '_windows_speech', side_effect=failure) as recognize:
            with self.assertRaisesRegex(RuntimeError, 'no offline speech recognizer'):
                voice.listen_locally(voice.pcm_wave(b'\x00\x00'), approved=True)
            self.assertEqual(recognize.call_count, 1)

    def test_second_timeout_is_reported_after_recovery_attempt(self):
        failure = voice.WindowsSpeechError('timeout', 'Windows timed out')
        with patch.object(voice, '_windows_speech', side_effect=failure) as recognize:
            with self.assertRaisesRegex(RuntimeError, 'transcription timed out'):
                voice.listen_locally(voice.pcm_wave(b'\x00\x00'), approved=True)
            self.assertEqual(recognize.call_count, 2)

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
