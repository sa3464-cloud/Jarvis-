from array import array
import json
import math
import random
import unittest
from unittest.mock import patch

from jarvis.agent import voice
from jarvis.agent.desktop_audio import MIC_RATE, Playback
from jarvis.agent.listening import BLOCK, Listening, PRE_ROLL


class ListeningTests(unittest.TestCase):
    def test_turns_with_quiet_speech_noise_and_attenuated_input(self):
        for name, volume, noise in [('quiet room', 2400, 0), ('fan noise', 1400, 220),
                                    ('soft voice', 170, 20), ('simulated far field', 270, 65)]:
            with self.subTest(name=name):
                detector = Listening()
                rng = random.Random(4)

                def block(index, speaking):
                    amplitude = volume * (.60 + .40 * abs(math.sin(index))) if speaking else 0
                    values = array('h')
                    for i in range(BLOCK):
                        t = (index * BLOCK + i) / MIC_RATE
                        hum = noise * math.sin(math.tau * 60 * t)
                        syllable = amplitude * (math.sin(math.tau * 190 * t) + .4 * math.sin(math.tau * 530 * t))
                        values.append(round(hum + syllable + rng.uniform(-noise / 4, noise / 4)))
                    return values.tobytes()

                for i in range(25):
                    self.assertFalse(detector.push(block(i, False)))
                self.assertIsNone(detector.start)
                self.assertLessEqual(len(detector.buffer), PRE_ROLL * 2)
                for i in range(25, 65):
                    # A half-second thought pause must stay in the same turn.
                    self.assertFalse(detector.push(block(i, not 37 <= i < 50)))
                self.assertIsNotNone(detector.start)
                for i in range(65, 110):
                    if detector.push(block(i, False)):
                        break
                else:
                    self.fail('The utterance never ended')
                audio = array('h', detector.take())
                self.assertGreater(len(audio), int(1.6 * MIC_RATE))
                self.assertLessEqual(max(map(abs, audio)), 30000)

    def test_short_keyboard_transient_does_not_trigger(self):
        detector = Listening()
        transient = array('h', [22000, -22000] + [0] * (BLOCK - 2)).tobytes()
        detector.push(transient)
        for _ in range(6):
            detector.push(bytes(BLOCK * 2))
        self.assertIsNone(detector.start)

    def test_echo_reference_removes_delayed_playback(self):
        rng = random.Random(12)
        playback = Playback.__new__(Playback)
        playback.rate = MIC_RATE
        playback.frames = 8000
        playback.samples = array('h', (rng.randrange(-12000, 12000) for _ in range(playback.frames)))
        playback.position = lambda: 6400
        start = 6400 - BLOCK - 800
        pcm = array('h', (sample // 2 for sample in playback.samples[start:start + BLOCK]))
        filtered, matched = playback.cancel_echo(pcm.tobytes())
        self.assertTrue(matched)
        self.assertLessEqual(max(map(abs, array('h', filtered))), 2)


class GroqTranscriptionTests(unittest.TestCase):
    def test_uncertain_whisper_result_does_not_become_a_command(self):
        config = {'GROQ_API_KEY': 'synthetic-key', 'GROQ_STT_PROMPT': 'JARVIS, Raspberry Pi'}
        with patch.object(voice, 'settings', return_value=config), patch.object(voice, 'build_opener') as opener:
            response = opener.return_value.open.return_value.__enter__.return_value
            response.read.return_value = json.dumps({'text': 'Open a website', 'segments': [
                {'no_speech_prob': .92, 'avg_logprob': -1.3},
            ]}).encode()
            result = voice.listen(b'wav', 'audio/wav', approved=True, details=True)
        request = opener.return_value.open.call_args.args[0]
        self.assertEqual(request.full_url, 'https://api.groq.com/openai/v1/audio/transcriptions')
        self.assertIn(b'whisper-large-v3', request.data)
        self.assertIn(b'Raspberry Pi', request.data)
        self.assertEqual(result, {'provider': 'Groq Whisper', 'text': '', 'uncertain': True})

    def test_groq_transport_failure_preserves_elevenlabs(self):
        with patch.object(voice, 'settings', return_value={'GROQ_API_KEY': 'test', 'ELEVENLABS_API_KEY': 'test'}), \
             patch.object(voice, '_groq_transcript', side_effect=RuntimeError), \
             patch.object(voice, '_request', return_value=b'{"text":"Hello"}'):
            result = voice.listen(b'wav', 'audio/wav', approved=True, details=True)
        self.assertEqual(result['provider'], 'ElevenLabs')
        self.assertEqual(result['text'], 'Hello')


if __name__ == '__main__':
    unittest.main()
