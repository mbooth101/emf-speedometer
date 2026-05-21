import math
import os

import app
import settings

from events.input import Buttons, BUTTON_TYPES
from system.eventbus import eventbus
from system.hexpansion.config import HexpansionConfig
from system.hexpansion.util import get_app_by_vid_pid
from system.hexpansion.events import HexpansionMountedEvent, HexpansionUnmountedEvent
from system.patterndisplay.events import PatternDisable, PatternEnable
from system.scheduler.events import RequestForegroundPushEvent, RequestForegroundPopEvent


class Throbber:

    def __init__(self, duration):
        # Total duration of the animation in milliseconds
        self._duration = duration

        # How far into the animation we are, in milliseconds
        self._elapsed = 0

        # Animated value
        self.throb = 0

    def update(self, delta):
        self._elapsed += delta
        if self._elapsed > self._duration:
            self._elapsed = self._elapsed - self._duration

        # Sinusoidal wave, normalised to between 0 and 1
        self.throb = math.sin(((math.pi * 2) / self._duration) * self._elapsed)
        self.throb = (self.throb + 1) * 0.5

    def draw(self, ctx):
        pass


class WaitingForFixStatus(Throbber):

    def __init__(self):
        super().__init__(1000)
        self._msg = "Awaiting GPS Fix"

    def draw(self, ctx):
        ctx.save()

        # Display message
        ctx.font_size = 22
        ctx.text_align = ctx.CENTER
        ctx.text_baseline = ctx.MIDDLE
        ctx.rgb(0.9, 0.9, 0.9).move_to(0, 0).text(self._msg)

        # Display icon
        ctx.line_width = 5
        ctx.translate(0, 30).rotate(math.pi / 4).rgba(1, 0.75, 0, 1 * self.throb)
        ctx.begin_path()
        ctx.arc(0, 0, 20, 0, math.pi, False)
        ctx.close_path().stroke()
        ctx.move_to(0, 0).line_to(0, -10).stroke()
        ctx.arc(0, -10, 4, 0, 2 * math.pi, False).fill()
        ctx.restore()


class HexpansionMissingStatus(Throbber):

    def __init__(self):
        super().__init__(1000)
        self._msg = "No GPS Hexpansion"

    def draw(self, ctx):
        ctx.save()

        # Display message
        ctx.font_size = 22
        ctx.text_align = ctx.CENTER
        ctx.text_baseline = ctx.MIDDLE
        ctx.rgb(0.9, 0.9, 0.9).move_to(0, 0).text(self._msg)

        # Display icon
        ctx.line_width = 5
        ctx.translate(0, 20).rgba(0.93, 0.14, 0, 1 * self.throb)
        ctx.begin_path().move_to(0, 0)
        for vert in [ (20, 0), (20, 30), (0, 30), (-20, 20), (-20, 10) ]:
            ctx.line_to(*vert)
        ctx.close_path().stroke()
        ctx.restore()


class Speedo(app.App):

    UNITS = ["kts", "mph", "km/h", "m/s"]

    STATUS_MISSING = HexpansionMissingStatus()
    STATUS_WAIT = WaitingForFixStatus()

    def __init__(self):
        self.button_states = Buttons(self)
        self.gps = self._find_gps_module()
        self.status = None

        # Current speed and selected display units
        self.speed = 0
        self.units = 1

        # Position for speed readout text
        self.spd_pos = None

        # Subscribe to events
        eventbus.on_async(RequestForegroundPushEvent, self._resume, self)
        eventbus.on_async(RequestForegroundPopEvent, self._pause, self)
        eventbus.on_async(HexpansionMountedEvent, self._mounted, self)
        eventbus.on_async(HexpansionUnmountedEvent, self._unmounted, self)

        # Disable firmware LED pattern
        eventbus.emit(PatternDisable())

        # Get LED brightness from settings
        self.brightness = settings.get("pattern_brightness")
        if not self.brightness:
            self.brightness = 0.1

    def _find_gps_module(self):
        gps_app = get_app_by_vid_pid(0xCAFE, 0x1295)
        return gps_app or None

    def update(self, delta):
        # Exit the app
        if self.button_states.get(BUTTON_TYPES["CANCEL"]):
            self.button_states.clear()
            self.minimise()

        # Units selection
        if self.button_states.get(BUTTON_TYPES["UP"]):
            self.units = (self.units + 1) % len(Speedo.UNITS)
            self.button_states.clear()
        if self.button_states.get(BUTTON_TYPES["DOWN"]):
            self.units = (self.units - 1) % len(Speedo.UNITS)
            self.button_states.clear()

        # Check GPS module status
        if not self.gps:
            # GPS hexpansion module is not plugged in
            self.status = Speedo.STATUS_MISSING
        if self.gps and not self.gps.position:
            # GPS hexpansion is plugged, but there is no positioning fix
            self.status = Speedo.STATUS_WAIT
        if self.gps and self.gps.position:
            # There is a valid positioning fix
            self.status = None

        if self.status:
            self.status.update(delta)

        # Determine current speed
        self.speed = 0.0
        if not self.status:
            if self.units == 0:
                self.speed = self.gps.speed_kts
            if self.units == 1:
                self.speed = self.gps.speed_mph
            if self.units == 2:
                self.speed = self.gps.speed_kmh
            if self.units == 3:
                self.speed = self.gps.speed_ms

    def draw(self, ctx):
        ctx.save()
        ctx.rgb(0.13, 0.19, 0.09).rectangle(-120, -120, 240, 240).fill()

        # Render speed read out
        ctx.font_size = 70
        ctx.text_align = ctx.RIGHT
        ctx.text_baseline = ctx.MIDDLE
        spd_pos = (ctx.text_width("0.0") / 2, 0)
        ctx.rgb(1, 1, 1).move_to(*spd_pos).text(f"{self.speed:.1f}")

        # Render units indicator
        ctx.font_size = 25
        ctx.text_align = ctx.LEFT
        ctx.text_baseline = ctx.TOP
        ctx.rgb(0.9, 0.9, 0.9).move_to(spd_pos[0] + 5, 0).text(f"{Speedo.UNITS[self.units]}")

        # Render status message
        if self.status:
            ctx.translate(0, 40)
            self.status.draw(ctx)

        ctx.restore()

    async def _resume(self, _: RequestForegroundPushEvent):
        # Disable firmware LED pattern
        eventbus.emit(PatternDisable())

        # Get LED brightness from settings
        self.brightness = settings.get("pattern_brightness")
        if not self.brightness:
            self.brightness = 0.1

    async def _pause(self, _: RequestForegroundPopEvent):
        # Re-enable firmware LED pattern when we minimise
        eventbus.emit(PatternEnable())

    async def _mounted(self, e: HexpansionMountedEvent):
        if not self.gps:
            self.gps = self._find_gps_module()

    async def _unmounted(self, e: HexpansionUnmountedEvent):
        if e.port == self.gps.config.port:
            self.gps = None


__app_export__ = Speedo # pylint: disable=invalid-name
