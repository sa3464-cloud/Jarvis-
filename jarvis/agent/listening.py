"""Bounded, in-memory microphone conditioning and utterance detection."""
from array import array
import math

from .desktop_audio import MIC_RATE, signal


BLOCK = MIC_RATE // 25
PRE_ROLL = int(.36 * MIC_RATE)
TAIL = int(.24 * MIC_RATE)
MAX_SAMPLES = 30 * MIC_RATE


class Listening:
    def __init__(self, sensitivity=.55, suppression=.65, silence=.95):
        self.sensitivity, self.suppression, self.silence = sensitivity, suppression, silence
        self.noise = .002
        self.previous_level = 0.
        self.gain = 1.
        self.previous = self.filtered = 0.
        self.buffer = bytearray()
        self.candidate = self.start = None
        self.voiced = self.last_voice = 0
        self.level, self.waveform = 0., ()

    def push(self, pcm, *, playback=False, echo_found=False):
        values = array('h', pcm)
        if not values:
            return False
        # High-pass around 100 Hz to attenuate rumble and DC before detection.
        filtered = []
        previous, state = self.previous, self.filtered
        crossings = 0
        for sample in values:
            next_state = .96 * (state + sample - previous)
            crossings += (state < 0) != (next_state < 0)
            state = next_state
            previous = sample
            filtered.append(state)
        self.previous, self.filtered = previous, state
        self.waveform, self.level = signal(filtered)
        threshold = max(.0014, self.noise * (3.15 - 1.5 * self.sensitivity))
        if self.start is not None:
            threshold *= .72
        if playback:
            threshold = max(threshold * 1.5, .006 if echo_found else .025)
        # Sustained low-frequency rumble has too few crossings for a speech onset.
        voiced = self.level >= threshold and (self.start is not None or crossings >= len(values) * .009)
        if not playback:
            steady = abs(self.level - self.previous_level) <= max(.0001, self.level * .04)
            if not voiced or (self.start is None and steady):
                self.noise += (.20 if steady else .055) * (self.level - self.noise)
        self.previous_level = self.level
        if voiced and (self.start is not None or self.candidate is not None):
            self.gain += .15 * (min(8., max(.6, .085 / max(self.level, .001))) - self.gain)
        peak = max(map(abs, filtered))
        excess = max(0., 1. - self.noise / max(self.level, .0001))
        attenuation = 1. - self.suppression * (1. - excess ** 2)
        gain = min(self.gain * attenuation, 30000 / max(peak, 1.))
        processed = array('h', (round(value * gain) for value in filtered))
        offset = len(self.buffer) // 2
        self.buffer.extend(processed.tobytes())
        end = offset + len(values)
        if voiced:
            if self.candidate is None:
                self.candidate = offset
            self.voiced += len(values)
            self.last_voice = end
            if self.start is None and self.voiced >= (.24 if playback else .16) * MIC_RATE:
                self.start = self.candidate
        elif end - self.last_voice >= .08 * MIC_RATE and self.start is None:
            self.candidate = None
            self.voiced = 0
        if self.start is None:
            discard = max(0, (end if self.candidate is None else self.candidate) - PRE_ROLL)
            if discard:
                del self.buffer[:discard * 2]
                self.last_voice = max(0, self.last_voice - discard)
                if self.candidate is not None:
                    self.candidate -= discard
            return False
        # Longer phrases and quieter signals get more time for a thought pause.
        phrase = (self.last_voice - self.start) / MIC_RATE
        pause = self.silence + min(.35, phrase * .12) + (.12 if self.level < self.noise * 1.5 else 0.)
        return end - self.last_voice >= pause * MIC_RATE or end >= MAX_SAMPLES

    def take(self):
        first = max(0, self.start - PRE_ROLL)
        last = min(first + MAX_SAMPLES, self.last_voice + TAIL)
        return bytes(self.buffer[first * 2:last * 2])
