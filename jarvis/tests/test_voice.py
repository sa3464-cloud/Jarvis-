import io
import json
import unittest
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
