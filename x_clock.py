import argparse
import asyncio
import datetime
import logging
import os
import random
import socket
import sys
import time
from dataclasses import dataclass, field
from io import BytesIO

import aiohttp_cors
from aiohttp import web
from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFont
from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import AsyncIOOSCUDPServer
from rgbmatrix import RGBMatrix, RGBMatrixOptions
from webcolors import HTML4_NAMES_TO_HEX, hex_to_rgb, name_to_rgb

try:
    import RPi.GPIO as GPIO

    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False


def color_to_rgb(color):
    """
    :param color: Color specified as either an HTML color name or a hex value
    :return: A tuple of the equivalent RGB values
    """
    try:
        try:
            return name_to_rgb(color)
        except ValueError:
            # Try HEX
            return hex_to_rgb(color if color[0] == "#" else f"#{color}")
    except ValueError:
        logging.warning(f"Color {color} cannot be parsed!")
        return None


RANDOM_COLORS = [hex_to_rgb(x) for x in HTML4_NAMES_TO_HEX.values()]


class MatrixBase:
    def __init__(self, *args, **kwargs):
        self.parser = argparse.ArgumentParser()

        self.parser.add_argument(
            "-r",
            "--led-rows",
            action="store",
            help="Display rows. 16 for 16x32, 32 for 32x32. Default: 32",
            default=32,
            type=int,
        )
        self.parser.add_argument(
            "--led-cols",
            action="store",
            help="Panel columns. Typically 32 or 64. (Default: 32)",
            default=64,
            type=int,
        )
        self.parser.add_argument(
            "-c",
            "--led-chain",
            action="store",
            help="Daisy-chained boards. Default: 1.",
            default=1,
            type=int,
        )
        self.parser.add_argument(
            "-P",
            "--led-parallel",
            action="store",
            help="For Plus-models or RPi2: parallel chains. 1..3. Default: 1",
            default=1,
            type=int,
        )
        self.parser.add_argument(
            "-p",
            "--led-pwm-bits",
            action="store",
            help="Bits used for PWM. Something between 1..11. Default: 11",
            default=11,
            type=int,
        )
        self.parser.add_argument(
            "-b",
            "--led-brightness",
            action="store",
            help="Sets brightness level. Default: 100. Range: 1..100",
            default=100,
            type=int,
        )
        self.parser.add_argument(
            "-m",
            "--led-gpio-mapping",
            help="Hardware Mapping: regular, adafruit-hat, adafruit-hat-pwm",
            choices=["regular", "adafruit-hat", "adafruit-hat-pwm"],
            type=str,
        )
        self.parser.add_argument(
            "--led-scan-mode",
            action="store",
            help="Progressive or interlaced scan. 0 Progressive, 1 Interlaced (default)",
            default=1,
            choices=range(2),
            type=int,
        )
        self.parser.add_argument(
            "--led-pwm-lsb-nanoseconds",
            action="store",
            help="Base time-unit for the on-time in the lowest significant bit in nanoseconds. Default: 130",
            default=130,
            type=int,
        )
        self.parser.add_argument(
            "--led-show-refresh",
            action="store_true",
            help="Shows the current refresh rate of the LED panel",
        )
        self.parser.add_argument(
            "--led-slowdown-gpio",
            action="store",
            help="Slow down writing to GPIO. Range: 1..100. Default: 1",
            choices=range(3),
            default=2,
            type=int,
        )
        self.parser.add_argument(
            "--led-no-hardware-pulse",
            action="store",
            help="Don't use hardware pin-pulse generation",
        )
        self.parser.add_argument(
            "--led-rgb-sequence",
            action="store",
            help="Switch if your matrix has led colors swapped. Default: RGB",
            default="RGB",
            type=str,
        )
        self.parser.add_argument(
            "--led-pixel-mapper",
            action="store",
            help='Apply pixel mappers. e.g "Rotate:90"',
            default="",
            type=str,
        )
        self.parser.add_argument(
            "--led-row-addr-type",
            action="store",
            help="0 = default; 1=AB-addressed panels;2=row direct",
            default=0,
            type=int,
            choices=[0, 1, 2],
        )
        self.parser.add_argument(
            "--led-multiplexing",
            action="store",
            help="Multiplexing type: 0=direct; 1=strip; 2=checker; 3=spiral; 4=ZStripe; 5=ZnMirrorZStripe; 6=coreman; 7=Kaler2Scan; 8=ZStripeUneven (Default: 0)",
            default=0,
            type=int,
        )
        self.args = None
        self.matrix = None

    def process(self):
        self.args = self.parser.parse_args()

        options = RGBMatrixOptions()

        if self.args.led_gpio_mapping is not None:
            options.hardware_mapping = self.args.led_gpio_mapping
        options.rows = self.args.led_rows
        options.cols = self.args.led_cols
        options.chain_length = self.args.led_chain
        options.parallel = self.args.led_parallel
        options.row_address_type = self.args.led_row_addr_type
        options.multiplexing = self.args.led_multiplexing
        options.pwm_bits = self.args.led_pwm_bits
        options.brightness = self.args.led_brightness
        options.pwm_lsb_nanoseconds = self.args.led_pwm_lsb_nanoseconds
        options.led_rgb_sequence = self.args.led_rgb_sequence
        options.pixel_mapper_config = self.args.led_pixel_mapper
        options.drop_privileges = False
        if self.args.led_show_refresh:
            options.show_refresh_rate = 1

        if self.args.led_slowdown_gpio is not None:
            options.gpio_slowdown = self.args.led_slowdown_gpio
        if self.args.led_no_hardware_pulse:
            options.disable_hardware_pulsing = True

        self.matrix = RGBMatrix(options=options)

        return True


class Cleared(Exception):
    pass


@dataclass
class XClock(MatrixBase):
    image: Image = None  # Current PIL Image object representing the clock display
    font: ImageFont = None  # Font for PIL
    gpio_enabled: bool = False  # Is GPIO monitoring enabled
    glyphs: dict = field(
        default_factory=dict
    )  # Dictionary mapping characters to glyphs
    glitch_mode: int = 0  # Graphical glitch mode
    glitch_freq: int = 0  # Graphical glitch frequency (out of 10000)
    glitch_step: int = 0  # Graphical glistch step tracker
    glitch_intensity: int = 4  # The intensity of a graphical glitch
    blink_all: bool = False  # Blink all glyphs
    blink_dots: bool = True  # Blink just dots
    blink_state: bool = True  # Current blink state (True = visible)
    show_dots: bool = True  # Should dots be visible
    show_numbers: bool = True  # Should numbers be visible
    x_glitch_mode: int = 0  # X glitch mode
    x_glitch_step: int = 0  # Frame step in X glitch
    x_glitch_freq: int = 0  # X glitch frequency (out of 10000)
    x_glitch_frames: int = 0  # number of frames to hold X glitch
    x_glitch_number: int = 0  # Number of glyphs to replace with X
    x_positions: list = field(
        default_factory=list
    )  # Positions which should be replaced with X
    text_color: tuple = color_to_rgb("#29B6F6")  # Color of numbers / dots
    x_color: tuple = color_to_rgb("#C70000")  # Color of Xs
    background: tuple = (0, 0, 0)  # Background color
    framerate: float = 0.05  # Delay between frames
    fade_time: int = 10  # Time for fade to execute
    fade_elapsed: int = 0  # Current time of fade
    brightness: int = 0  # Current brightness
    last_brightness: int = 0  # Previous brightness before fade op
    target_brightness: int = 100  # Target brightness for Fade
    current_time: datetime = datetime.datetime.now()  # Current time cursor
    real_elapsed: float = 0  # Tracking real seconds elapsed from last frame
    tick: float = time.time()  # Track real time of each frame
    time_dilation_factor: float = 1  # Multiplier for time dilation. 1 = realtime
    numbers_glitch_step: int = 0  # Step in random number glitch
    fade_snap_next_brightness: int = 0  # Target brightness after fadesnap op
    fade_snap_time: datetime = None  # New time after fadesnap op
    fade_snap_clear_x: bool = False  # Clear X characters following a fadesnap
    freeze_time: datetime = None  # Freeze the clock on a given time
    scrolling_text: str = ""  # Current scrolling text
    text_scroll_offset: int = 0  # Current scroll position for text
    # Constants
    NUMBER_POSITIONS = [2, 15, 36, 49]  # Pixel left positions for each glyph
    GLITCH_MODE_OFF = 0  # No glitching
    GLITCH_MODE_ON = 1  # Glitching constantly
    GLITCH_MODE_RANDOM = 2  # Glitching at random intervals
    GLITCH_MODE_SINGLE = 3  # Glitch once

    def __post_init__(self):
        super(XClock, self).__init__()
        self.parser.add_argument(
            "--font", help="Path to a .pil font file", required=True
        )
        self.parser.add_argument(
            "--show-ip",
            action="store_true",
            help="Show IP address on startup",
        )
        self.parser.add_argument(
            "--gpio-pin",
            help="GPIO pin for show IP switch (default: 25)",
            type=int,
            default=25,
        )
        self.parser.add_argument(
            "--no-gpio", help="Disable GPIO switch monitoring", action="store_true"
        )

    def tick_tock(self):
        """
        Tracks the passage of time (dilated or otherwise)
        """
        tock = time.time()
        self.real_elapsed = tock - self.tick
        self.tick = tock
        dilated = self.real_elapsed * self.time_dilation_factor
        self.current_time += datetime.timedelta(seconds=dilated)

        # Blink
        if self.blink_dots or self.blink_all:
            if abs(dilated) > 1:
                # If the time dilation causes the tick to be more than a second
                # positive or negative, just blink every frame.
                self.blink_state = not self.blink_state
            else:
                # Otherwise blink every second.
                self.blink_state = self.current_time.microsecond >= 500000
            self.show_dots = self.blink_state
        if self.blink_all:
            self.show_numbers = self.blink_state

    @property
    def ip_address(self) -> str:
        """Get the local IP address"""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "NO IP"

    def draw_scrolling_text(self):
        """Draw scrolling text across the display"""
        d = ImageDraw.Draw(self.image)

        # Get text width using textbbox
        bbox = d.textbbox((0, 0), self.scrolling_text, font=self.font)
        text_width = bbox[2] - bbox[0]

        # Draw text at current scroll offset, raised by 5 pixels
        x_pos = self.matrix.width - self.text_scroll_offset
        y_pos = -5  # Raise text by 5 pixels to fit on screen
        d.text(
            (x_pos, y_pos), self.scrolling_text, font=self.font, fill=self.text_color
        )

        # Update scroll offset
        self.text_scroll_offset += 1

        # Reset when text has scrolled off screen
        if self.text_scroll_offset > text_width + self.matrix.width:
            self.text_scroll_offset = 0

    def update_clock(self):
        """
        Draws the clock or IP address
        """
        if self.scrolling_text:
            self.draw_scrolling_text()
        else:
            time_obj = self.freeze_time or self.current_time
            time_disp = time_obj.strftime("%H%M")
            if self.show_dots:
                self.draw_glyph(":", left=29)
            for pos, glyph in enumerate(time_disp):
                self.draw_glyph(glyph, pos)

    def draw_x(self):
        """
        Draws any X glyphs as appropriate
        """
        for pos in self.x_positions:
            self.draw_glyph("X", pos, color=self.x_color)

    def x_glitch(self):
        """
        Handles an X glitch
        """
        if self.x_glitch_step > 0:
            self.x_glitch_step -= 1
            if self.x_glitch_step <= 0:
                self.x_positions = []
        if self.x_glitch_mode == self.GLITCH_MODE_OFF:
            return
        elif self.x_glitch_mode == self.GLITCH_MODE_RANDOM:
            if self.x_glitch_step == 0:
                if random.randint(0, 10000) <= self.x_glitch_freq:
                    self.start_x_glitch()
                return
        elif self.x_glitch_mode == self.GLITCH_MODE_SINGLE:
            self.x_glitch_mode = self.GLITCH_MODE_OFF
            self.start_x_glitch()

    def start_x_glitch(self):
        """
        Initiate an X Glitch
        """
        x_positions = [0, 1, 2, 3]
        random.shuffle(x_positions)
        self.x_positions = x_positions[: self.x_glitch_number]
        self.x_glitch_step = self.x_glitch_frames

    def draw_glyph(self, glyph, pos=0, left=None, color=None):
        """
        Draw a glyph in a position

        :param glyph: The glyph to draw
        :param pos: The predefined position
        :param left: Alternatively, the left position in pixels
        :param color: The color of the glyph (or use the text color)
        """
        left = left or self.NUMBER_POSITIONS[pos]
        d = ImageDraw.Draw(self.image)
        d.rectangle((left, 0, left + 13, 32), self.background)
        d.bitmap((left, 0), self.glyphs[glyph], color or self.text_color)

    def do_glitch(self):
        """
        Handle graphical glitches
        """
        if self.glitch_step > 0:
            self.glitch_step -= 1
            self.make_glitch()
        if self.glitch_mode == self.GLITCH_MODE_OFF:
            return
        elif self.glitch_mode == self.GLITCH_MODE_ON:
            self.make_glitch()
        elif self.glitch_mode == self.GLITCH_MODE_RANDOM:
            if self.glitch_step == 0:
                if random.randint(0, 10000) <= self.glitch_freq:
                    self.glitch_step = random.randint(3, 7)
                return

    def make_glitch(self):
        """
        Create a graphical glitch
        """
        num_glitches = random.randint(
            int(self.glitch_intensity / 2), self.glitch_intensity
        )
        for i in range(num_glitches):
            glitch_row = random.randint(0, self.image.height)
            glitch_size = random.randint(2, 6)
            glitch_amount = random.randint(
                -(self.glitch_intensity * 2), (2 * self.glitch_intensity)
            )
            glitch = self.image.crop(
                (0, glitch_row, self.image.width, glitch_row + glitch_size)
            )
            glitch = ImageChops.offset(glitch, glitch_amount)
            self.image.paste(glitch, (0, glitch_row))

    # noinspection PyProtectedMember
    def generate_glyphs(self):
        """
        Convert the font to bitmaps for numeral, ":", and "X" character
        """
        if not self.font:
            self.font = ImageFont.load(self.args.font)
        image = Image.new("RGB", (13, 32))
        glyphs = list(range(10)) + [":", "X"]
        for i in glyphs:
            bitmap = image._new(self.font.getmask(str(i)))
            self.glyphs[str(i)] = bitmap.crop((0, 5, 13, 37))

    def gpio_state(self) -> bool:
        """
        Returns true if the GPIO pin is active (pulled low)
        """
        state = False
        if GPIO_AVAILABLE and not self.args.no_gpio:
            try:
                GPIO.setmode(GPIO.BCM)
                GPIO.setup(self.args.gpio_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
                pin_state = GPIO.input(self.args.gpio_pin)
                state = pin_state == GPIO.LOW
                logging.info(f"GPIO pin {self.args.gpio_pin} is low")
            except Exception as e:
                logging.warning(f"Failed to initialize GPIO: {e}")
        return state

    def process(self):
        """
        Some startup stuff
        """
        if not super().process():
            return False
        self.generate_glyphs()

        if self.args.show_ip or self.gpio_state():
            self.scrolling_text = self.ip_address

        return True

    def step_fade(self):
        """
        Determine brightness at a given time during a fade
        """
        if self.target_brightness != self.brightness:
            self.fade_elapsed += self.real_elapsed
            fade_pct = self.fade_elapsed / self.fade_time
            brightness_offset = (
                self.target_brightness - self.last_brightness
            ) * fade_pct
            self.brightness = (
                self.last_brightness + brightness_offset
                if fade_pct < 1
                else self.target_brightness
            )
            if self.fade_snap_time and self.brightness == self.target_brightness:
                if self.fade_snap_clear_x:
                    self.x_positions = []
                self.current_time = self.fade_snap_time
                self.fade_snap_time = None
                self.target_brightness = self.fade_snap_next_brightness

    def numbers_glitch(self):
        """
        Glitch all numbers to random numerals
        """
        if self.numbers_glitch_step:
            for pos in range(0, 4):
                self.draw_glyph(str(random.randint(0, 9)), pos)
            self.numbers_glitch_step -= 1

    def render(self):
        self.image = Image.new(
            "RGB", (self.matrix.width, self.matrix.height), color=self.background
        )
        self.tick_tock()
        if self.brightness == 0 == self.target_brightness:
            raise Cleared
        self.update_clock()

        self.numbers_glitch()
        self.x_glitch()
        self.draw_x()
        self.do_glitch()

        self.step_fade()

        if not self.show_numbers:
            raise Cleared

        if self.brightness != 100:
            e = ImageEnhance.Brightness(self.image)
            self.image = e.enhance(self.brightness / 100)

    async def async_run(self):
        """
        The main run loop
        """
        double_buffer = self.matrix.CreateFrameCanvas()

        while True:
            try:
                self.render()
                double_buffer.SetImage(self.image, 0)
                double_buffer = self.matrix.SwapOnVSync(double_buffer)
            except Cleared:
                self.matrix.Clear()
            await asyncio.sleep(self.framerate)

    @property
    def state(self):
        """
        Return comprehensive current state of the clock
        """

        def rgb_to_hex(rgb):
            """Convert RGB tuple to hex string without #"""
            return "{:02x}{:02x}{:02x}".format(rgb[0], rgb[1], rgb[2])

        current_time_obj = self.freeze_time or self.current_time

        return {
            "time": {
                "hour": current_time_obj.hour,
                "minute": current_time_obj.minute,
                "frozen": self.freeze_time is not None,
            },
            "appearance": {
                "brightness": int(self.brightness),
                "text_color": rgb_to_hex(self.text_color),
                "x_color": rgb_to_hex(self.x_color),
                "background": rgb_to_hex(self.background),
            },
            "effects": {
                "time_dilation": self.time_dilation_factor,
                "blink_dots": self.blink_dots,
                "blink_all": self.blink_all,
            },
            "glitches": {
                "visual_glitch_freq": self.glitch_freq,
                "visual_glitch_active": self.glitch_mode != self.GLITCH_MODE_OFF,
                "x_glitch_freq": self.x_glitch_freq,
                "x_glitch_active": self.x_glitch_mode == self.GLITCH_MODE_RANDOM,
                "x_glitch_number": self.x_glitch_number,
                "x_glitch_frames": self.x_glitch_frames,
            },
            "x_positions": self.x_positions,
        }


class OSCServer(XClock):
    """
    Extends the clock to have OSC control. Functions are documented in the README
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.parser.add_argument(
            "--ip", help="IP for the OSC Server to listen on", default="0.0.0.0"
        )
        self.parser.add_argument(
            "--port", help="Port for the OSC Server to listen on", default=1337
        )

        self.dispatcher = Dispatcher()
        self.dispatcher.set_default_handler(self.osc_recv)

    def get_server(self):
        return AsyncIOOSCUDPServer(
            (self.args.ip, self.args.port), self.dispatcher, asyncio.get_event_loop()
        )

    def osc_recv(self, cmd, *args):
        """
        Handle incoming OSC command
        """
        logging.info(f"Command received {cmd} ({args})")
        cmd = os.path.basename(cmd)
        try:
            getattr(self, f"set_{cmd}")(*args)
        except AttributeError:
            logging.error(f"Invalid command received {cmd}")
        except Exception as e:
            logging.error(f"Error processing command {cmd}: {e!r}")

    def set_random_glitch(self, freq=100, intensity=4):
        self.glitch_intensity = intensity
        if freq == -1:
            self.glitch_mode = self.GLITCH_MODE_ON
        elif freq == 0:
            self.glitch_mode = self.GLITCH_MODE_OFF
        else:
            self.glitch_mode = self.GLITCH_MODE_RANDOM
            self.glitch_freq = freq

    def set_random_x_glitch(self, freq, num=1, frames=1, color=None):
        if freq == 0:
            self.x_glitch_mode = self.GLITCH_MODE_OFF
            return
        self.set_single_x_glitch(num, frames, color)
        self.x_glitch_freq = freq
        self.x_glitch_mode = self.GLITCH_MODE_RANDOM

    def set_single_x_glitch(self, num=1, frames=1, color=None):
        self.set_x_color(color)
        self.x_glitch_number = num
        self.x_glitch_frames = frames
        self.x_glitch_mode = self.GLITCH_MODE_SINGLE

    def set_x_color(self, color):
        if color:
            self.x_color = color_to_rgb(color) or self.x_color

    def set_x_positions(self, positions="0000", color=None):
        if len(positions) != 4:
            logging.warning(f"Must specify four positions! {positions}")
            return
        self.x_glitch_mode = self.GLITCH_MODE_OFF
        self.x_glitch_step = 0
        positions_array = []
        for idx, pos in enumerate(positions):
            if pos == "X":
                positions_array.append(idx)
        self.set_x_color(color)
        self.x_positions = positions_array

    def set_color(self, color):
        self.text_color = color_to_rgb(color)

    def set_bg(self, color):
        self.background = color_to_rgb(color)

    def set_time(self, hour, minute):
        self.current_time = self.current_time.replace(
            hour=hour, minute=minute, second=0
        )
        self.freeze_time = None

    def set_freeze(self, enabled=1):
        if not enabled and self.freeze_time:
            self.current_time = self.freeze_time
            self.freeze_time = None
        elif enabled and not self.freeze_time:
            self.freeze_time = self.current_time

    def set_glitch_to(self, hour, minute, frames=5):
        self.set_time(hour, minute)
        self.numbers_glitch_step = frames

    def set_normal(self):
        self.x_glitch_mode = self.GLITCH_MODE_OFF
        self.set_freeze(0)
        self.set_blink_all(0)
        self.set_blink_dots(1)
        self.glitch_mode = self.GLITCH_MODE_OFF
        self.time_dilation_factor = 1
        self.current_time = self.current_time.replace(second=0)
        self.x_positions = []
        self.x_color = self.text_color

    def set_brightness(self, target, duration=0):
        self.last_brightness = self.brightness
        self.target_brightness = max(min(target, 100), 0)
        if duration == 0:
            self.brightness = target
            return
        self.fade_elapsed = 0
        self.fade_time = duration

    def set_fadesnap(self, hour, minute, duration=1, clear_x=False):
        self.fade_snap_next_brightness = self.brightness
        self.fade_snap_time = self.current_time.replace(
            hour=hour, minute=minute, second=0
        )
        self.set_brightness(0, duration)
        self.fade_snap_clear_x = clear_x
        self.freeze_time = None

    def set_time_dilation(self, factor=1):
        self.time_dilation_factor = factor

    def set_increment_time(self, minutes):
        self.current_time += datetime.timedelta(minutes=minutes)
        self.current_time = self.current_time.replace(second=0)

    def set_framerate(self, rate=0.05):
        self.framerate = rate

    def set_blink_dots(self, enabled=1):
        self.blink_dots = True if enabled == 1 else False
        self.show_dots = not self.blink_dots

    def set_blink_all(self, enabled=1):
        self.blink_all = True if enabled == 1 else False
        self.show_numbers = not self.blink_all

    def set_timenow(self, reset_dilation=None):
        if reset_dilation:
            self.time_dilation_factor = 1
        self.current_time = datetime.datetime.now()

    def set_display_text(self, text: str = ""):
        """Display arbitrary text by scrolling it across the display"""
        if text != self.scrolling_text:
            self.text_scroll_offset = 0
        self.scrolling_text = text

    def set_showip(self, enabled=1):
        """Toggle IP address display mode"""
        self.set_display_text("" if enabled == 0 else self.ip_address)


class HTTPServer(OSCServer):
    """Extends OSCServer to add HTTP functionality"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.parser.add_argument(
            "--http-port",
            help="Port for the HTTP preview server",
            type=int,
            default=8080,
        )
        self.latest_image = None

    def render(self):
        """Render the clock and store the latest image for HTTP serving"""
        try:
            super().render()
            self.latest_image = self.image.copy()
        except Cleared:
            self.latest_image = Image.new(
                "RGB", (self.matrix.width, self.matrix.height), color=self.background
            )
            raise

    async def http_preview_handler(self, request):
        """Serve the current display image as PNG"""
        if self.latest_image is None:
            return web.Response(status=404, text="No image available yet")

        # Scale up the image for better visibility (64x32 is tiny!)
        scale_factor = 8
        scaled_image = self.latest_image.resize(
            (
                self.latest_image.width * scale_factor,
                self.latest_image.height * scale_factor,
            ),
            Image.NEAREST,  # Use NEAREST to preserve pixel art look
        )

        # Convert to PNG bytes
        buffer = BytesIO()
        scaled_image.save(buffer, format="PNG")
        buffer.seek(0)

        return web.Response(body=buffer.read(), content_type="image/png")

    async def http_stream_handler(self, request):
        """Stream the display as MJPEG video"""
        response = web.StreamResponse()
        response.content_type = "multipart/x-mixed-replace; boundary=frame"
        await response.prepare(request)

        scale_factor = 8
        try:
            while True:
                if self.latest_image is not None:
                    # Scale up the image
                    scaled_image = self.latest_image.resize(
                        (
                            self.latest_image.width * scale_factor,
                            self.latest_image.height * scale_factor,
                        ),
                        Image.NEAREST,
                    )

                    # Convert to JPEG bytes
                    buffer = BytesIO()
                    scaled_image.save(buffer, format="JPEG", quality=95)
                    frame_data = buffer.getvalue()

                    # Send frame in multipart format
                    await response.write(
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n\r\n" + frame_data + b"\r\n"
                    )

                # Wait for next frame (match the clock's framerate)
                await asyncio.sleep(self.framerate)
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        finally:
            await response.write_eof()

        return response

    async def http_status_handler(self, request):
        """Return current clock status as JSON"""
        import json

        return web.Response(
            body=json.dumps(self.state), content_type="application/json"
        )

    async def async_run(self):
        """Start the HTTP server"""
        app = web.Application()

        # Configure CORS to allow browser access
        cors = aiohttp_cors.setup(
            app,
            defaults={
                "*": aiohttp_cors.ResourceOptions(
                    allow_credentials=True,
                    expose_headers="*",
                    allow_headers="*",
                    allow_methods="*",
                )
            },
        )

        # Add routes
        preview_route = app.router.add_get("/preview", self.http_preview_handler)
        stream_route = app.router.add_get("/stream", self.http_stream_handler)
        status_route = app.router.add_get("/status", self.http_status_handler)

        # Configure CORS for each route
        cors.add(preview_route)
        cors.add(stream_route)
        cors.add(status_route)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, host="0.0.0.0", port=self.args.http_port)
        await site.start()

        logging.info(f"HTTP server started on port {self.args.http_port}")

        try:
            await super().async_run()
        finally:
            await runner.cleanup()
            logging.info("HTTP server stopped")


async def async_main(server):
    runserver = server.get_server()
    try:
        transport, _ = await runserver.create_serve_endpoint()
        await server.async_run()
    except KeyboardInterrupt:
        logging.info("Exiting")
        sys.exit(0)
    finally:
        # noinspection PyUnboundLocalVariable
        transport.close()


def main():
    server = HTTPServer()

    logging.basicConfig(level=logging.INFO)

    if not server.process():
        server.parser.print_help()
        sys.exit(1)

    asyncio.run(async_main(server))


if __name__ == "__main__":
    main()
