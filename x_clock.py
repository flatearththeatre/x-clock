import argparse
import logging
import random
import time
import sys
import os
import datetime
from dataclasses import dataclass, field

from PIL import Image, ImageDraw, ImageFont, ImageChops, ImageEnhance
from pythonosc.osc_server import AsyncIOOSCUDPServer
from pythonosc.dispatcher import Dispatcher
from webcolors import name_to_rgb, hex_to_rgb, HTML4_NAMES_TO_HEX
import asyncio

sys.path.append(os.path.abspath(os.path.dirname(__file__) + '/..'))
from rgbmatrix import RGBMatrix, RGBMatrixOptions


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
            return hex_to_rgb(color if color[0] == '#' else f'#{color}')
    except ValueError:
        logging.warning(f'Color {color} cannot be parsed!')
        return None


RANDOM_COLORS = [hex_to_rgb(x) for x in HTML4_NAMES_TO_HEX.values()]


class MatrixBase(object):
    def __init__(self, *args, **kwargs):
        self.parser = argparse.ArgumentParser()

        self.parser.add_argument("-r", "--led-rows", action="store",
                                 help="Display rows. 16 for 16x32, 32 for 32x32. Default: 32", default=32, type=int)
        self.parser.add_argument("--led-cols", action="store", help="Panel columns. Typically 32 or 64. (Default: 32)",
                                 default=64, type=int)
        self.parser.add_argument("-c", "--led-chain", action="store", help="Daisy-chained boards. Default: 1.",
                                 default=1, type=int)
        self.parser.add_argument("-P", "--led-parallel", action="store",
                                 help="For Plus-models or RPi2: parallel chains. 1..3. Default: 1", default=1, type=int)
        self.parser.add_argument("-p", "--led-pwm-bits", action="store",
                                 help="Bits used for PWM. Something between 1..11. Default: 11", default=11, type=int)
        self.parser.add_argument("-b", "--led-brightness", action="store",
                                 help="Sets brightness level. Default: 100. Range: 1..100", default=100, type=int)
        self.parser.add_argument("-m", "--led-gpio-mapping",
                                 help="Hardware Mapping: regular, adafruit-hat, adafruit-hat-pwm",
                                 choices=['regular', 'adafruit-hat', 'adafruit-hat-pwm'], type=str)
        self.parser.add_argument("--led-scan-mode", action="store",
                                 help="Progressive or interlaced scan. 0 Progressive, 1 Interlaced (default)",
                                 default=1, choices=range(2), type=int)
        self.parser.add_argument("--led-pwm-lsb-nanoseconds", action="store",
                                 help="Base time-unit for the on-time in the lowest significant bit in nanoseconds. Default: 130",
                                 default=130, type=int)
        self.parser.add_argument("--led-show-refresh", action="store_true",
                                 help="Shows the current refresh rate of the LED panel")
        self.parser.add_argument("--led-slowdown-gpio", action="store",
                                 help="Slow down writing to GPIO. Range: 1..100. Default: 1", choices=range(3),
                                 default=2, type=int)
        self.parser.add_argument("--led-no-hardware-pulse", action="store",
                                 help="Don't use hardware pin-pulse generation")
        self.parser.add_argument("--led-rgb-sequence", action="store",
                                 help="Switch if your matrix has led colors swapped. Default: RGB", default="RGB",
                                 type=str)
        self.parser.add_argument("--led-pixel-mapper", action="store", help="Apply pixel mappers. e.g \"Rotate:90\"",
                                 default="", type=str)
        self.parser.add_argument("--led-row-addr-type", action="store",
                                 help="0 = default; 1=AB-addressed panels;2=row direct", default=0, type=int,
                                 choices=[0, 1, 2])
        self.parser.add_argument("--led-multiplexing", action="store",
                                 help="Multiplexing type: 0=direct; 1=strip; 2=checker; 3=spiral; 4=ZStripe; 5=ZnMirrorZStripe; 6=coreman; 7=Kaler2Scan; 8=ZStripeUneven (Default: 0)",
                                 default=0, type=int)
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
    glyphs: dict = field(default_factory=dict)  # Dictionary mapping characters to glyphs
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
    x_positions: list = field(default_factory=list)  # Positions which should be replaced with X
    text_color: tuple = color_to_rgb('#29B6F6')  # Color of numbers / dots
    x_color: tuple = color_to_rgb('#29B6F6')  # Color of Xs
    background: tuple = (0, 0, 0)  # Background color
    font: ImageFont = field(init=False)  # Font for PIL
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
    # Constants
    NUMBER_POSITIONS = [2, 15, 36, 49]  # Pixel left positions for each glyph
    GLITCH_MODE_OFF = 0  # No glitching
    GLITCH_MODE_ON = 1  # Glitching constantly
    GLITCH_MODE_RANDOM = 2  # Glitching at random intervals
    GLITCH_MODE_SINGLE = 3  # Glitch once

    def __post_init__(self):
        super(XClock, self).__init__()
        self.parser.add_argument("-i", "--image", help="The image to display", default="/tmp/foo.jpg")
        self.font = ImageFont.load(
            os.path.join(os.path.abspath(os.path.dirname(__file__)), 'font', 'VCROSDMono-42.pil'))

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
                self.blink_state = (self.current_time.microsecond >= 500000)
            self.show_dots = self.blink_state
        if self.blink_all:
            self.show_numbers = self.blink_state

    def update_clock(self):
        """
        Draws the clock
        """
        time_obj = self.freeze_time or self.current_time
        time_disp = time_obj.strftime('%H%M')
        if self.show_dots:
            self.draw_glyph(':', left=29)
        for pos, glyph in enumerate(time_disp):
            self.draw_glyph(glyph, pos)

    def draw_x(self):
        """
        Draws any X glyphs as appropriate
        """
        for pos in self.x_positions:
            self.draw_glyph('X', pos, color=self.x_color)

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
        self.x_positions = x_positions[:self.x_glitch_number]
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
        num_glitches = random.randint(int(self.glitch_intensity / 2), self.glitch_intensity)
        for i in range(num_glitches):
            glitch_row = random.randint(0, self.image.height)
            glitch_size = random.randint(2, 6)
            glitch_amount = random.randint(-(self.glitch_intensity * 2), (2 * self.glitch_intensity))
            glitch = self.image.crop((0, glitch_row, self.image.width, glitch_row + glitch_size))
            glitch = ImageChops.offset(glitch, glitch_amount)
            self.image.paste(glitch, (0, glitch_row))

    # noinspection PyProtectedMember
    def generate_glyphs(self):
        """
        Convert the font to bitmaps for numeral, ":", and "X" character
        """
        image = Image.new('RGB', (13, 32))
        glyphs = list(range(10)) + [':', 'X']
        for i in glyphs:
            bitmap = image._new(self.font.getmask(str(i)))
            self.glyphs[str(i)] = (bitmap.crop((0, 5, 13, 37)))

    def process(self):
        """
        Some startup stuff
        """
        self.generate_glyphs()
        return super(XClock, self).process()

    def step_fade(self):
        """
        Determine brightness at a given time during a fade
        """
        if self.target_brightness != self.brightness:
            self.fade_elapsed += self.real_elapsed
            fade_pct = self.fade_elapsed / self.fade_time
            brightness_offset = (self.target_brightness - self.last_brightness) * fade_pct
            self.brightness = self.last_brightness + brightness_offset if fade_pct < 1 else self.target_brightness
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

    async def async_run(self):
        """
        The main run loop
        """
        double_buffer = self.matrix.CreateFrameCanvas()

        while True:
            self.image = Image.new('RGB', (self.matrix.width, self.matrix.height), color=self.background)
            try:
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

                double_buffer.SetImage(self.image, 0)

                double_buffer = self.matrix.SwapOnVSync(double_buffer)
            except Cleared:
                self.matrix.Clear()

            await asyncio.sleep(self.framerate)


class OSCServer(XClock):
    """
    Extends the clock to have OSC control. Functions are documented in the README
    """

    def __init__(self, *args, **kwargs):
        super(OSCServer, self).__init__(*args, **kwargs)
        self.parser.add_argument("--ip", help="IP for the OSC Server to listen on", default="0.0.0.0")
        self.parser.add_argument("--port", help="Port for the OSC Server to listen on", default=1337)

        self.dispatcher = Dispatcher()
        self.dispatcher.set_default_handler(self.osc_recv)

    def get_server(self):
        return AsyncIOOSCUDPServer((self.args.ip, self.args.port), self.dispatcher, asyncio.get_event_loop())

    @property
    def state(self):
        """
        Vestige. Had an idea to save state in the event of a crash... Gave up on that.
        """
        return {
            'real_time'      : time.time(),
            'current_time'   : self.current_time.isoformat(),
            'glitch_mode'    : self.glitch_mode,
            'glitch_freq'    : self.glitch_freq,
            'x_glitch_mode'  : self.x_glitch_mode,
            'x_glitch_freq'  : self.x_glitch_freq,
            'x_glitch_number': self.x_glitch_number,
            'x_glitch_frames': self.x_glitch_frames,
            'x_color'        : self.x_color,
            'text_color'     : self.text_color,
        }

    def osc_recv(self, cmd, *args):
        """
        Handle incoming OSC command
        """
        logging.info(f'Command received {cmd} ({args})')
        cmd = os.path.basename(cmd)
        try:
            getattr(self, f'set_{cmd}')(*args)
        except AttributeError:
            logging.error(f'Invalid command received {cmd}')

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

    def set_x_positions(self, positions='0000', color=None):
        if len(positions) != 4:
            logging.warning(f'Must specify four positions! {positions}')
            return
        self.x_glitch_mode = self.GLITCH_MODE_OFF
        self.x_glitch_step = 0
        positions_array = []
        for idx, pos in enumerate(positions):
            if pos == 'X':
                positions_array.append(idx)
        self.set_x_color(color)
        self.x_positions = positions_array

    def set_color(self, color):
        self.text_color = color_to_rgb(color)

    def set_bg(self, color):
        self.background = color_to_rgb(color)

    def set_time(self, hour, minute):
        self.current_time = self.current_time.replace(
            hour=hour,
            minute=minute,
            second=0
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
            hour=hour,
            minute=minute,
            second=0
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


async def async_main(server):
    runserver = server.get_server()
    try:
        transport, protocol = await runserver.create_serve_endpoint()
        await server.async_run()
    except KeyboardInterrupt:
        logging.info('Exiting')
        sys.exit(0)
    finally:
        # noinspection PyUnboundLocalVariable
        transport.close()


def main():
    server = OSCServer()

    logging.basicConfig(level=logging.INFO)

    if not server.process():
        server.parser.print_help()
        sys.exit(1)

    asyncio.run(async_main(server))


if __name__ == "__main__":
    main()
