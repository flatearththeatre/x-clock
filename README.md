# X Clock

This is the source code to a digital clock which was part of the set on Flat Earth Theatre's November 2019 production of *X* by Alistair McDowall (https://www.flatearththeatre.com/shows/season-14/x/). The clock is controlled from QLab using OSC commands.

## Hardware
For our production, this was run on a Raspberry Pi 3B. The display was a 64x32 RGB LED panel with P4 spacing picked up from AliExpress, driven by a RGB bonnet from Adafruit. All powered by a 5V power supply. I 3D printed a bracket for attaching the electronics to the panel.

### Price Breakddown & Links
* Raspberry Pi 3B - $35 https://www.adafruit.com/product/3055 
* Panel - $18 https://www.aliexpress.com/item/32754106669.html?spm=a2g0s.9042311.0.0.5f944c4dNgMBuw
* Bonnet - $15 https://www.adafruit.com/product/3211
* PSU - $15 https://www.adafruit.com/product/1466
 
## Other Notes
While there's no reason this wouldn't work using the Pi's wireless controller I was paranoid and chose to connect to it using ethernet. Your mileage may vary.
 
Driving the panel relies on the library found here: https://github.com/hzeller/rpi-rgb-led-matrix. I followed the instructions in the repo for getting the library compiled and configured. I also use the puthonosc and webcolors libraries available from Pypi.

The font is a modified version of VCR OSD Mono which I found online. I made manual changes to the numerals, 'X', and ':' glyphs in FontForge and generated bitmap fonts. I didn't bother modifying other glyphs as they aren't used in the clock. 

## Usage
Starts up with current time at 100 brightness. By default the clock will advance in real time, though this may be adjusted (see OSC commands below).

Default OSC port: 1337

### OSC Commands Reference

Arguments in `[brackets]` are optional; default indicated with `=`.

* `/time hour minute` - Set the clock to *hour* and *minute*.
* `/brightness brightness [fade time]` - Set the *brightness* level (0-100). *fade* over a number of seconds.
* `/color color` - Set the text color to *color* where color is a valid 6-character hex code (omit '#') or an HTML color name.
* `/x_color color` - Set the text color to *color* for 'X' glyphs.
* `/bg color` - Set the background to *color*
* `/random_glitch freq` - Clock will glitch at random. *freq* is the frequency of a glitch occurring on any given frame. Chance out of 10000. 0 disables glitch.
* `/random_x_glitch freq [number=1] [length=1] [color]` - Will cause 'X' to appear in place of numbers at random. *freq* is same as above. *number* defines how many numbers to replace (1-4). *length* is how long the x is held in frames. *color* defines the color. 
* `/single_x_glitch [number=1] [length=1] [color]` - Will cause 'X' to appear in place of numbers exactly once. *freq* is same as above. *number* defines how many numbers to replace (1-4). *length* is how long the x is held in frames. *color* defines the color
* `/x_positions [positions='0000']` - Change sepecified number positions to 'X' indefinitely. *positions* is a string where the letter 'X' denotes a number to replace. Other letters are ignored and the number will be shown in that position. e.g. `X0X0` would display 'X' in the first and third positions. `ABCD` would clear the Xs and display the time.
* `/time_dilation [factor=1]` - Changes the rate at which time passes. *factor* is a multiplier. `2` would cause time to flow twice as fast, `0.5` would cause time to flow at half speed, `-10` would coause time to move in reverse at 10x speed, etc.
* `/increment_time minutes` - Changes the time on the clock by any number of *minutes*. Negatives are acceptable.
* `/framerate [rate=0.05]` - Changes the interval over which the clock is updated. Time still flows as normal (or as dialated), but the screen will update less frequently and effects will last longer. This is quite dangerous and is only inteded for debugging. Default is 0.05 seconds.
* `/normal` - Reset effects (glitches, time dilation, Xs).
* `/glitch_to hour minute [frames=5]` - Glitches all number positions to a random integer each frame for *frames* frames, then set time to *hour* and *minute*.
* `/fadesnap hour minuete [duration=1]` - Fades clock to 0 brightness over *duration* seconds, then set time to *hour* and *minute* and snap to previous brightness.
* `/blink_dots [enabled=1]` - Enables or disables the blinking ':' characters once per second. `0` to disable blinking
* `/blink_all [enabled=1]` - Enables or disables blinking all characters once per second. `0` to disable blinking
* `/freeze [enabled=1]` - Freeze the clock on the currently displayed time.
* `/timenow` - Set the clock to the current IRL time.

Commands which adjust time (`time_dilation`, `increment_time`, `time`, and `normal`) reset the (unseen) seconds to 0 to avoid weirdness.
