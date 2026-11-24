import io
import unittest
from unittest.mock import Mock, patch
import wave

from jarvis.agent import voice
from jarvis.agent.desktop import Desktop
from jarvis.agent.desktop_audio import signal
from jarvis.agent.desktop_hud import Spring, layout_target, PANEL_W


class DesktopMotionTest(unittest.TestCase):
    def test_spring_accelerates_and_settles_at_target(self):
        spring = Spring(0, 180)
        initial = spring.advance(.025)
        spring.advance(.025)
        self.assertLess(0, initial)
        self.assertGreater(spring.value - initial, initial)
        for _ in range(150):
            spring.advance(.025)
        self.assertAlmostEqual(spring.value, 180, places=2)
        self.assertAlmostEqual(spring.velocity, 0, places=2)

    def test_panel_docks_on_monitor_left_of_primary(self):
        work = (-1280, 0, 0, 720)
        x, y, side = layout_target(-30, 180, work, expanded=True)
        self.assertEqual(side, -1)
        self.assertGreater(x - PANEL_W - 107, work[0])
        self.assertLess(x, 0)
        self.assertEqual(y, 180)


class DesktopAudioTest(unittest.TestCase):
    def test_confirmation_discards_mishearing_and_submits_only_the_confirmed_question(self):
        desktop = Mock()
        desktop.pending_voice = None
        desktop.hidden = False
        Desktop.hear(desktop, 'Open the wrong site')
        desktop.run.assert_called_once()
        desktop.submit.assert_not_called()
        Desktop.hear(desktop, 'No.')
        self.assertIsNone(desktop.pending_voice)
        desktop.submit.assert_not_called()
        Desktop.hear(desktop, ' Explain how a resistor works ')
        desktop.submit.assert_not_called()
        Desktop.hear(desktop, 'Yes, JARVIS!')
        desktop.submit.assert_called_once_with('Explain how a resistor works')
        self.assertIsNone(desktop.pending_voice)

    def test_voice_stop_command_does_not_start_a_chat_turn(self):
        desktop = Mock()
        Desktop.hear(desktop, 'Hey JARVIS, stop listening.')
        desktop.stop_voice.assert_called_once_with()
        desktop.submit.assert_not_called()

    def test_expired_confirmation_never_submits(self):
        desktop = Mock()
        desktop.pending_voice = ('Open the wrong site', 10)
        desktop.hidden = False
        with patch('jarvis.agent.desktop.time.monotonic', return_value=11):
            Desktop.hear(desktop, 'Yes')
        desktop.submit.assert_not_called()
        desktop.start_listening.assert_called_once()
        self.assertIsNone(desktop.pending_voice)

    def test_unrecognized_confirmation_discards_the_pending_question(self):
        desktop = Mock()
        desktop.pending_voice = ('Open the wrong site', 10)
        desktop.hidden = False
        Desktop.hear(desktop, '')
        desktop.submit.assert_not_called()
        desktop.start_listening.assert_called_once()
        self.assertIsNone(desktop.pending_voice)

    def test_waveform_and_energy_keep_actual_sample_sign_and_level(self):
        peaks, energy = signal([-16384, 16384, -16384, 16384], points=4)
        self.assertEqual(peaks, (-.5, .5, -.5, .5))
        self.assertEqual(energy, .5)

    def test_requested_pcm_is_wrapped_for_native_playback(self):
        pcm = b'\x01\x00\x02\x00'
        with (
            patch.object(voice, 'settings', return_value={'JARVIS_TTS_PROVIDER': 'elevenlabs'}),
            patch.object(voice, '_request', return_value=pcm) as provider,
        ):
            wav = voice.speak('A short reply.', approved=True, wav=True)
        self.assertIn('output_format=pcm_16000', provider.call_args.args[0])
        with wave.open(io.BytesIO(wav), 'rb') as recording:
            self.assertEqual((recording.getnchannels(), recording.getsampwidth(), recording.getframerate()),
                             (1, 2, 16000))
            self.assertEqual(recording.readframes(2), pcm)
