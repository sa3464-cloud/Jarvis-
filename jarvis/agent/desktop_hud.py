"""Original kinetic hologram geometry and spring motion for the desktop overlay."""
from dataclasses import dataclass
import math


TRANSPARENT = '#010002'
PANEL = '#081924'
INK = '#d7f8ff'
MUTED = '#88b5c7'
WIDTH, HEIGHT = 651, 346
CORE_Y = 150
PANEL_W = 378
PANEL_Y, PANEL_H = 32, 278
COLORS = {
    'idle': '#75d8ff', 'listening': '#63ffe1', 'thinking': '#aabfff',
    'speaking': '#85ffef', 'executing': '#77d9ff', 'complete': '#7effbb',
    'error': '#ffa5a9',
}
VELOCITY = {
    'idle': 12, 'listening': 21, 'thinking': 95, 'speaking': 40,
    'executing': 66, 'complete': 32, 'error': 0,
}


@dataclass
class Spring:
    value: float
    target: float
    velocity: float = 0.0

    def advance(self, elapsed, stiffness=46, damping=13):
        # Small integration steps keep the spring stable after a slow frame.
        count = max(1, math.ceil(elapsed / .008))
        step = elapsed / count
        for _ in range(count):
            acceleration = stiffness * (self.target - self.value) - damping * self.velocity
            self.velocity += acceleration * step
            self.value += self.velocity * step
        if abs(self.target - self.value) < .01 and abs(self.velocity) < .04:
            self.value, self.velocity = self.target, 0
        return self.value


def core_x(side):
    return 119 if side == 1 else WIDTH - 119


def layout_target(x, y, work, expanded=False):
    left, top, right, bottom = work
    side = 1 if right - x >= x - left else -1
    low, high = left + 112, right - 112
    if expanded:
        if side == 1:
            high = min(high, right - PANEL_W - 104)
        else:
            low = max(low, left + PANEL_W + 104)
    center = (left + right) / 2
    x = min(max(x, low), high) if low <= high else center
    y = min(max(y, top + 124), bottom - 163)
    return x, y, side


def rectangle(x, y, radius):
    return (x - radius, y - radius, x + radius, y + radius)


class Hologram:
    def __init__(self, canvas):
        self.canvas = canvas
        self.buttons = {}
        self.angle = 0.0
        self.speed = VELOCITY['idle']
        self.radius = 90.0

    def line(self, *points, color, width=1):
        self.canvas.create_line(*points, fill=color, width=width, tags='scene')

    def arc(self, x, y, radius, start, extent, color, width=1):
        self.canvas.create_arc(*rectangle(x, y, radius), start=start % 360, extent=extent,
                               style='arc', outline=color, width=width, tags='scene')

    def circle(self, x, y, radius, outline, fill='', width=1):
        self.canvas.create_oval(*rectangle(x, y, radius), outline=outline, fill=fill,
                                width=width, tags='scene')

    def text(self, x, y, value, size, color=INK, **options):
        self.canvas.create_text(x, y, text=value, fill=color, font=('Segoe UI', size),
                                tags='scene', **options)

    def chip(self, x, y, width, text, key, accent):
        box = (x - width / 2, y - 12, x + width / 2, y + 12)
        self.buttons[key] = box
        self.canvas.create_rectangle(*box, fill=PANEL, outline='#28556a', tags='scene')
        self.text(x, y, text, 9, accent)

    def draw_panel(self, x, extent, side, state, activity):
        if extent < 1:
            return
        near = x + side * 107
        edge = near + side * extent
        low, high = sorted((near, edge))
        self.line(x + side * 86, CORE_Y, near, CORE_Y, color='#397487')
        self.canvas.create_rectangle(low, PANEL_Y, high, PANEL_Y + PANEL_H,
                                     fill=PANEL, outline='#2c6175', tags='scene')
        self.line(low + 1, PANEL_Y + 1, high - 1, PANEL_Y + 1,
                  color=COLORS[state], width=2)
        if state in ('thinking', 'executing') and extent > 20:
            # This is activity, rather than a fabricated percent for remote tasks.
            width = (high - low) * .23
            start = low + (high - low - width) * activity
            self.line(start, PANEL_Y + PANEL_H - 4, start + width,
                      PANEL_Y + PANEL_H - 4, color=COLORS[state], width=2)

    def draw(self, side, state, compact, panel, waveform, energy, progress,
             now, elapsed, reduced=False, pulse=0):
        self.canvas.delete('scene')
        self.buttons.clear()
        x = core_x(side)
        accent = COLORS[state]
        motion = 0 if reduced else 1
        self.speed += (VELOCITY[state] - self.speed) * min(1, elapsed * 4)
        self.angle = (self.angle + self.speed * elapsed * motion) % 360
        phase = self.angle
        hover = math.sin(now * 1.9) * 4 * motion
        y = CORE_Y + hover
        energy = min(1, energy * 4)
        factor = 1 + (.055 if state == 'listening' else 0) + energy * .13
        target_radius = (37 if compact else 90) * factor
        self.radius += (target_radius - self.radius) * (1 if reduced else min(1, elapsed * 19))
        radius = self.radius
        self.draw_panel(x, PANEL_W * min(1, max(0, panel)), side, state, (now * .8 * motion) % 1)

        if not compact:
            self.canvas.create_oval(x - 77, y + 93, x + 77, y + 104,
                                    outline='#204959', width=1, tags='scene')
            for i in range(16):
                angle = (i * 137.5 + phase * .3) * math.pi / 180
                distance = 96 + (i % 4) * 3 + math.sin(now * 2 + i) * 3 * motion
                px, py = x + math.cos(angle) * distance, y + math.sin(angle) * distance
                self.circle(px, py, 1.8 if i % 5 == 0 else 1, '', accent if i % 5 == 0 else '#235466')
        self.circle(x, y, radius, '#1c5366')
        for offset in (0, 120, 240):
            self.arc(x, y, radius, phase + offset, 50, accent, 2)
            self.arc(x, y, radius * .9, -phase * 1.24 + offset, 74, '#387f93')
        for offset in (0, 90, 180, 270):
            self.arc(x, y, radius * .76, phase * .55 + offset, 34, '#4e9eb5', 2)
        for i in range(28 if not compact else 12):
            theta = (i / (28 if not compact else 12) * math.tau) + math.radians(phase) * .33
            start = radius * (.84 if i % 7 else .80)
            end = radius * .89
            self.line(x + math.cos(theta) * start, y + math.sin(theta) * start,
                      x + math.cos(theta) * end, y + math.sin(theta) * end,
                      color=accent if i % 7 == 0 else '#2a5970')
        if state == 'speaking' and progress > 0:
            self.arc(x, y, radius + 5, 90, -min(359.9, 360 * progress), accent, 2)
        if state == 'complete' and pulse > 0 and motion:
            self.circle(x, y, radius + 6 + (1 - pulse) * 13, accent, width=2 if pulse > .5 else 1)
        self.circle(x, y, radius * .64, '#398098', '#0a2635', width=2)
        self.circle(x, y, radius * .57, '#254d63', '#0b2231')
        if compact:
            self.text(x, y, 'J', 19, accent)
            self.text(x, y + 56, 'Restore', 9, MUTED)
            return
        self.text(x, y - 12, 'J A R V I S', 15, accent)
        if waveform and state in ('listening', 'speaking'):
            points = []
            for i, sample in enumerate(waveform):
                points.extend((x - 39 + i * 78 / max(1, len(waveform) - 1), y + 15 + sample * 24))
            if len(points) > 3:
                self.line(*points, color=accent, width=2)
        else:
            self.text(x, y + 14, 'A I   C O R E', 8, MUTED)
        self.text(x, 263, state.upper(), 10, accent)
        self.chip(x - 59, 292, 58, 'Dismiss' if panel > .6 else 'Panel', 'panel', INK)
        self.chip(x + 1, 292, 51, 'Minimize', 'minimize', INK)
        self.chip(x + 55, 292, 44, 'Hide', 'hide', INK)

    def button_at(self, x, y):
        return next((name for name, (left, top, right, bottom) in self.buttons.items()
                     if left <= x <= right and top <= y <= bottom), None)
