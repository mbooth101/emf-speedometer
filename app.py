"""
Copyright (c) 2026 Mat Booth.

This file is part of the Speedo app for the Tildagon
(see https://github.com/mbooth101/emf-speedometer).

License: MIT
"""
import math

import app
import settings

from events.input import Buttons, BUTTON_TYPES
from tildagonos import tildagonos
from system.eventbus import eventbus
from system.hexpansion.config import HexpansionConfig
from system.hexpansion.util import get_app_by_vid_pid
from system.hexpansion.events import HexpansionMountedEvent, HexpansionUnmountedEvent
from system.patterndisplay.events import PatternDisable, PatternEnable
from system.scheduler.events import RequestForegroundPushEvent, RequestForegroundPopEvent


def hsv_to_rgb(h, s, v):
    """Utility to convert HSV colours to RGB colours"""

    # If saturation is zero, then it's achromatic, we can just return a purely
    # greyscale value
    if s == 0.0:
        rgb = (v, v, v)
    else:
        # Hue may be given as an integer number of degrees or as a normalised
        # value between 0 and 1
        if isinstance(h, int):
            region = h // 60
            remainder = h / 60 - region
        else:
            region = int(h * 6.0) # Intentional truncation
            remainder = h * 6.0 - region
        a = v * (1.0 - s)
        b = v * (1.0 - remainder * s)
        c = v * (1.0 - (1.0 - remainder) * s)
        if region == 0:
            rgb = (v, c, a)
        elif region == 1:
            rgb = (b, v, a)
        elif region == 2:
            rgb = (a, v, c)
        elif region == 3:
            rgb = (a, b, v)
        elif region == 4:
            rgb = (c, a, v)
        else: # region == 5
            rgb = (v, a, b)
    return rgb


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

    LEDS = 12

    SECTOR_GREEN = (0.0, 0.75, 0.29)
    SECTOR_AMBER = (1.0, 0.75, 0.0)
    SECTOR_RED = (0.93, 0.14, 0.0)
    GRADIENT = [ SECTOR_RED, SECTOR_RED, SECTOR_AMBER, SECTOR_AMBER, SECTOR_GREEN, SECTOR_GREEN ]

    def __init__(self):
        # Current speed from GPS
        self.speed = 0.0
        self.display_speed = 0.0
        self.max_speed = 0

        # Selected display units and dial range
        self.units = 1
        self.range = 0

        self.valid = False

        # Get LED brightness from settings
        brightness = settings.get("pattern_brightness")
        if not brightness:
            brightness = 0.1

        # Pre-compute LED colours, honouring the system wide LED brightness
        # setting
        self.leds = []
        for i in range(Speed.LEDS):
            hue = int((i // 4) * (120 / 2))
            r,g,b = map(lambda x: int(x * 255), hsv_to_rgb(hue, 1.0, 1.0 * brightness))
            self.leds.append((r, g, b))
        self.leds = list(reversed(self.leds))

        self.update_display_speeds()

    def select_next_units(self, direction):
        self.units = (self.units + direction) % len(Speed.UNITS)
        self.update_display_speeds()

    def select_next_range(self, direction):
        self.range = (self.range + direction) % len(Speed.UNITS[self.units]['range'])
        self.update_display_speeds()

    def handle_gps_event(self, e):
        self.valid = e.position is not None
        self.speed = e.speed
        self.update_display_speeds()

    def update_display_speeds(self):
        self.display_speed = self.speed * Speed.UNITS[self.units]['factor']
        self.max_speed = Speed.UNITS[self.units]['range'][self.range]

        # Update LED gauge indicator
        speed_per_led = self.max_speed / (Speed.LEDS - 2)
        for i in range(Speed.LEDS):
            # Offset LED id by half the number of LEDs, since our zero is at
            # the bottom not the top
            led = int(i + Speed.LEDS / 2) % Speed.LEDS + 1

            if self.display_speed >= speed_per_led * i:
                tildagonos.leds[led] = self.leds[i]
            else:
                tildagonos.leds[led] = (0, 0, 0)
        tildagonos.leds.write()

    def draw(self, ctx):
        ctx.save()
        ctx.rgb(1, 1, 1)

        # Render units indicator selector widget
        ctx.font_size = 25
        ctx.text_align = ctx.CENTER
        ctx.text_baseline = ctx.MIDDLE
        ctx.begin_path().move_to(0, 64).line_to(-10, 70).line_to(10, 70).close_path().fill()
        ctx.move_to(0, 85).text(Speed.UNITS[self.units]['unit'])
        ctx.begin_path().move_to(0, 106).line_to(-10, 100).line_to(10, 100).close_path().fill()

        # Render speed read out in big at the centre of the screen
        if self.valid:
            ctx.font_size = 65
            ctx.move_to(0, 0).text(f"{self.display_speed:.1f}")

        ctx.restore()

        self._draw_indicator(ctx)
        self._draw_graticules(ctx)

    def _draw_indicator(self, ctx):
        """Draw the dial indicator arc"""

        ctx.save()

        # Rotate so the gap in the dial is at the bottom of the screen
        ctx.rotate(math.pi / 3)

        # Define a gradient for the indicator arc, but offset the start point
        # gradient by 90° so it's the same as an arc's start point
        ctx.conic_gradient(0, 0, math.pi / 2, 1)
        for idx, colour in enumerate(Speed.GRADIENT):
            ctx.add_stop((1 / 6) * idx, colour, 1.0)

        # The arc is bounded to these limits that contain the gradient, 5/6ths
        # of the circumference of the dial
        arc_min = math.pi / 3
        arc_max = 2 * math.pi

        # Filled arc
        ctx.begin_path()
        ctx.arc(0, 0, 120, arc_min, arc_max, False)
        ctx.arc(0, 0, 98, arc_max, arc_min, True)
        ctx.close_path().fill()

        # Outline
        ctx.rgb(1, 1, 1)
        ctx.begin_path()
        ctx.arc(0, 0, 120, arc_min, arc_max, False)
        ctx.arc(0, 0, 98, arc_max, arc_min, True)
        ctx.close_path().stroke()

        ctx.restore()

    def _draw_graticules(self, ctx):
        """Draw the dial graticules and scale labels"""

        ctx.save()

        # The extent of the dial arc is 5/6ths of the circumference of the dial
        arc_extent = 2 * math.pi - math.pi / 3

        # Dial arc is divided into sectors of equal size, for the major
        # graticules
        sectors = 5
        arc_sector = arc_extent / sectors

        # Number of major graticules includes a final one at the end of the
        # last sector
        graticules = sectors + 1

        # Render dial graticules
        ctx.font_size = 22
        ctx.text_align = ctx.CENTER
        ctx.text_baseline = ctx.MIDDLE
        ctx.rgb(1, 1, 1)

        # Iterate through double the number of graticules minus one so we can
        # draw intermediate minor graticules between the major graticules
        for i in range(graticules * 2 - 1):
            rot = math.pi / 6 + (arc_sector / 2) * i
            ctx.save()
            if i % 2:
                # Minor intermediate graticule
                ctx.line_width = 4
            else:
                # Major graticule and scale label
                spd = int((self.max_speed / sectors) * (i / 2))
                ctx.move_to(-(math.sin(rot) * 75), math.cos(rot) * 75).text(f"{spd}")
                ctx.line_width = 8
            ctx.rotate(rot)
            ctx.move_to(0, 120).line_to(0, 90).stroke()
            ctx.restore()

        ctx.restore()


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

    def _find_gps_module(self):
        # Get GPS app from hexpansion EEPROM
        self.gps = get_app_by_vid_pid(0xCAFE, 0x1295)
        # Subscribe to GPS events
        if self.gps:
            eventbus.on(self.gps.GPSEvent, self.speed.handle_gps_event, self)

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

    async def _pause(self, _: RequestForegroundPopEvent):
        # Re-enable firmware LED pattern when we minimise
        eventbus.emit(PatternEnable())

    async def _mounted(self, _: HexpansionMountedEvent):
        if not self.gps:
            self._find_gps_module()

    async def _unmounted(self, e: HexpansionUnmountedEvent):
        if e.port == self.gps.config.port:
            eventbus.remove(self.gps.GPSEvent, self.speed.handle_gps_event, self)
            self.gps = None
            self.speed.valid = False


__app_export__ = Speedo # pylint: disable=invalid-name
