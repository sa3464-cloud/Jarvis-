import io
import json
import unittest
import wave
from unittest.mock import MagicMock, patch
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

    def test_empty_recognition_retries_with_louder_pcm_and_silence(self):
        samples = b'\x00\x04\x00\xfc' * 8
        with patch.object(voice, '_windows_speech', side_effect=[b'', b'Try again']) as recognize:
            self.assertEqual(voice.listen_locally(voice.pcm_wave(samples), approved=True), 'Try again')
        first, retry = recognize.call_args_list
        self.assertEqual(first.args[1], samples)
        self.assertIn('SetInputToWaveStream', retry.args[0])
        with wave.open(io.BytesIO(retry.args[1]), 'rb') as recording:
            self.assertEqual(recording.readframes(16), b'\xe0\x2e\x20\xd1' * 8)
            self.assertEqual(recording.readframes(25600), b'\0\0' * 25600)

    def test_fallback_rejects_invalid_audio_and_requires_approval(self):
        with patch.object(voice, '_windows_speech') as recognize:
            with self.assertRaises(ValueError):
                voice.listen_locally(b'not a recording', approved=True)
            with self.assertRaises(PermissionError):
                voice.listen_locally(b'not a recording')
            recognize.assert_not_called()


class ElevenLabsMicrophoneTest(unittest.TestCase):
    def test_transcription_defaults_to_english_without_audio_event_tags(self):
        audio = voice.pcm_wave(b'\x00\x00')
        with (
            patch.object(voice, 'settings', return_value={}),
            patch.object(voice, '_request', return_value=b'{"text":"What is a resistor?"}') as request,
        ):
            self.assertEqual(voice.listen(audio, 'audio/wav', approved=True), 'What is a resistor?')
        body = request.call_args.args[1]
        self.assertIn(b'name="model_id"\r\n\r\nscribe_v2\r\n', body)
        self.assertIn(b'name="language_code"\r\n\r\neng\r\n', body)
        self.assertIn(b'name="tag_audio_events"\r\n\r\nfalse\r\n', body)
        self.assertIn(audio, body)

    def test_explicit_model_and_automatic_language_detection_are_supported(self):
        config = {'ELEVENLABS_STT_MODEL': 'scribe_v1', 'ELEVENLABS_STT_LANGUAGE': 'auto'}
        with (
            patch.object(voice, 'settings', return_value=config),
            patch.object(voice, '_request', return_value=b'{"text":""}') as request,
        ):
            self.assertEqual(voice.listen(b'audio', approved=True), '')
        body = request.call_args.args[1]
        self.assertIn(b'name="model_id"\r\n\r\nscribe_v1\r\n', body)
        self.assertNotIn(b'name="language_code"', body)


class FishAudioTest(unittest.TestCase):
    config = {'JARVIS_TTS_PROVIDER': 'fish_audio', 'FISH_AUDIO_REFERENCE_ID': 'fixture-voice',
              'FISH_API_KEY': 'fish-test-only', 'ELEVENLABS_API_KEY': 'eleven-test-only'}

    def test_fish_receives_configured_reference_and_uses_free_model(self):
        response = MagicMock()
        response.headers.get_content_type.return_value = 'audio/mpeg'
        response.read.return_value = b'fixture audio'
        with patch.object(voice, 'settings', return_value=self.config):
            with patch.object(voice, 'build_opener') as opener:
                opener.return_value.open.return_value.__enter__.return_value = response
                self.assertEqual(voice.speak('Test reply', approved=True), b'fixture audio')
                request = opener.return_value.open.call_args.args[0]
        self.assertEqual(request.full_url, 'https://api.fish.audio/v1/tts')
        self.assertEqual(request.get_header('Authorization'), 'Bearer fish-test-only')
        self.assertEqual(request.get_header('Model'), 's2.1-pro-free')
        self.assertEqual(json.loads(request.data),
                         {'text': 'Test reply', 'reference_id': 'fixture-voice', 'format': 'mp3'})

    def test_fish_pcm_is_wrapped_as_wav_for_desktop(self):
        pcm = b'\x01\x00' * 20
        response = MagicMock()
        response.headers.get_content_type.return_value = 'application/octet-stream'
        response.read.return_value = pcm
        with patch.object(voice, 'settings', return_value=self.config):
            with patch.object(voice, 'build_opener') as opener:
                opener.return_value.open.return_value.__enter__.return_value = response
                result = voice.speak('Test reply', approved=True, wav=True)
                request = opener.return_value.open.call_args.args[0]
        self.assertEqual(json.loads(request.data)['sample_rate'], 16000)
        self.assertEqual(json.loads(request.data)['format'], 'pcm')
        with wave.open(io.BytesIO(result)) as audio:
            self.assertEqual(audio.getframerate(), 16000)
            self.assertEqual(audio.readframes(audio.getnframes()), pcm)

    def test_missing_fish_key_falls_back_without_provider_requests(self):
        with patch.object(voice, 'settings', return_value={**self.config, 'FISH_API_KEY': ''}):
            with patch.object(voice, 'build_opener') as opener:
                with self.assertRaisesRegex(voice.SpeechFallback, 'Fish Audio key missing'):
                    voice.speak('Test reply', approved=True)
                opener.assert_not_called()
            self.assertEqual(voice.output_status(), {'tts_provider': 'fish_audio', 'tts_configured': False})

    def test_fish_does_not_send_text_before_voice_approval(self):
        with patch.object(voice, 'settings', return_value=self.config):
            with patch.object(voice, 'build_opener') as opener:
                with self.assertRaises(PermissionError):
                    voice.speak('Test reply')
                opener.assert_not_called()
