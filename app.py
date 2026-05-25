"""
Copyright (c) 2026 Mat Booth.

This file is part of the Settlers of EMF app for the Tildagon
(see https://github.com/mbooth101/emf-settlers).

License: MIT
"""
import math

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

    def __init__(self, duration=1000):
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

    def draw(self, ctx):
        ctx.save()

        # Display message
        ctx.font_size = 25
        ctx.text_align = ctx.CENTER
        ctx.text_baseline = ctx.TOP
        ctx.rgb(0.9, 0.9, 0.9).move_to(0, 15).text("Awaiting GPS Fix")

        # Display icon
        ctx.line_width = 5
        ctx.translate(0, -20).rotate(math.pi / 4).rgba(1, 0.75, 0, 1 * self.throb)
        ctx.begin_path()
        ctx.arc(0, 0, 20, 0, math.pi, False)
        ctx.close_path().stroke()
        ctx.move_to(0, 0).line_to(0, -10).stroke()
        ctx.arc(0, -12, 4, 0, 2 * math.pi, False).fill()

        ctx.restore()


class HexpansionMissingStatus(Throbber):

    def draw(self, ctx):
        ctx.save()

        # Display message
        ctx.font_size = 25
        ctx.text_align = ctx.CENTER
        ctx.text_baseline = ctx.TOP
        ctx.rgb(0.9, 0.9, 0.9).move_to(0, 15).text("No GPS Hexpansion")

        # Display icon
        ctx.line_width = 5
        ctx.translate(0, -20).rgba(0.93, 0.14, 0, 1 * self.throb)
        ctx.begin_path().move_to(0, -20)
        for vert in [ (20, -20), (20, 20), (0, 20), (-20, 8), (-20, -8) ]:
            ctx.line_to(*vert)
        ctx.close_path().stroke()

        ctx.restore()


class Speed:

    # Conversion factors from knots and dial ranges
    UNITS = [
        {'unit': "kts", 'factor': 1.0, 'range': [10, 20]},
        {'unit': "mph", 'factor': 1.151, 'range': [10, 20]},
        {'unit': "km/h", 'factor': 1.852, 'range': [15, 30]},
        {'unit': "m/s", 'factor': 0.514, 'range': [5, 10]},
    ]

    def __init__(self):
        # Current speed from GPS
        self.speed = 0.0

        # Selected display units and dial range
        self.units = 1
        self.range = 0

        self.valid = False

    def select_next_units(self, direction):
        self.units = (self.units + direction) % len(Speed.UNITS)

    def select_next_range(self, direction):
        self.range = (self.range + direction) % len(Speed.UNITS[self.units]['range'])

    def draw(self, ctx):
        ctx.save()
        ctx.rgb(1, 1, 1)

        # Render units indicator widget
        ctx.font_size = 25
        ctx.text_align = ctx.CENTER
        ctx.text_baseline = ctx.MIDDLE
        ctx.begin_path().move_to(0, 64).line_to(-10, 70).line_to(10, 70).close_path().fill()
        ctx.move_to(0, 85).text(Speed.UNITS[self.units]['unit'])
        ctx.begin_path().move_to(0, 106).line_to(-10, 100).line_to(10, 100).close_path().fill()

        # Render speed read out
        if self.valid:
            ctx.font_size = 65
            ctx.text_align = ctx.RIGHT
            ctx.text_baseline = ctx.MIDDLE
            spd_pos = (ctx.text_width("0.0") / 2, 5)
            speed_converted = self.speed * Speed.UNITS[self.units]['factor']
            ctx.move_to(*spd_pos).text(f"{speed_converted:.1f}")

        ctx.restore()

        ctx.save()

        # Render dial graticules
        sectors = 5
        max_speed = Speed.UNITS[self.units]['range'][self.range]
        arc_extent = math.pi * 2 - math.pi / 3
        arc_sector = arc_extent / sectors
        ctx.line_width = 8
        ctx.font_size = 22
        ctx.text_align = ctx.CENTER
        ctx.text_baseline = ctx.MIDDLE
        ctx.rgb(1, 1, 1)
        for i in range(sectors + 1):
            rot = math.pi / 6 + arc_sector * i
            spd = int((max_speed / sectors) * i)
            ctx.save()
            ctx.move_to(-(math.sin(rot) * 80), math.cos(rot) * 80).text(f"{spd}")
            ctx.rotate(rot)
            ctx.move_to(0, 120).line_to(0, 95).stroke()
            ctx.restore()

        ctx.restore()


    def _handle_gps_event(self, e):
        self.valid = e.position is not None
        self.speed = e.speed


class Speedo(app.App):

    STATUS_MISSING = HexpansionMissingStatus()
    STATUS_WAIT = WaitingForFixStatus()

    def __init__(self):
        self.button_states = Buttons(self)
        self.speed = Speed()

        self.gps = None
        self.status = None

        self._find_gps_module()

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
        # Get GPS app from hexpansion EEPROM
        self.gps = get_app_by_vid_pid(0xCAFE, 0x1295)
        # Subscribe to GPS events
        if self.gps:
            eventbus.on(self.gps.GPSEvent, self.speed._handle_gps_event, self)

    def update(self, delta):
        # Exit the app
        if self.button_states.get(BUTTON_TYPES["CANCEL"]):
            self.button_states.clear()
            self.minimise()

        # Units selection
        if self.button_states.get(BUTTON_TYPES["UP"]):
            self.speed.select_next_units(1)
            self.button_states.clear()
        if self.button_states.get(BUTTON_TYPES["DOWN"]):
            self.speed.select_next_units(-1)
            self.button_states.clear()

        # Dial range selection
        if self.button_states.get(BUTTON_TYPES["RIGHT"]):
            self.speed.select_next_range(1)
            self.button_states.clear()
        if self.button_states.get(BUTTON_TYPES["LEFT"]):
            self.speed.select_next_range(-1)
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

        # Update status message
        if self.status:
            self.status.update(delta)

    def draw(self, ctx):
        ctx.rgb(0.13, 0.19, 0.09).rectangle(-120, -120, 240, 240).fill()

        self.speed.draw(ctx)

        # Render status message/speed readout
        if self.status:
            self.status.draw(ctx)

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
            self._find_gps_module()

    async def _unmounted(self, e: HexpansionUnmountedEvent):
        if e.port == self.gps.config.port:
            eventbus.remove(self.gps.GPSEvent, self.speed._handle_gps_event, self)
            self.gps = None
            self.speed.valid = False


__app_export__ = Speedo # pylint: disable=invalid-name
