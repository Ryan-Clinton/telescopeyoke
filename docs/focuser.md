# The motor focuser

[Back to the README](../README.md)

A 28BYJ-48 stepper motor on the focuser's shaft, driven by an Arduino Nano
on a USB lead. `./focuser.py` loads the Nano and turns the motor. That is as
far as it goes yet: fitted to the 150P it has driven the drawtube in by a
turn of the motor, but nothing about it has been measured and `focus.py`
does not use it.

## Parts

| Part | Notes |
|---|---|
| 28BYJ-48 motor, 5 V, with its ULN2003 driver board | A 12 V one looks the same: read the label |
| Arduino Nano with a USB lead | A clone with the CH340 chip is what was used |
| Six jumper wires | Female to female if the Nano's pins are soldered on |
| Printed bracket, coupler and box | "Skywatcher 200P focuser" by AstroCosas, [thingiverse.com/thing:5468202](https://www.thingiverse.com/thing:5468202) (CC BY). Made for the 200P's single-speed focuser; the 150P's coupler fits a 4 mm shaft |

## Screws

All M3. The lengths are estimates, not yet tried in the parts.

| What | For | How many |
|---|---|---|
| M3 screws about 12 mm long, with nuts and washers | The motor's two ears, through the bracket's 3.5 mm slots | 2 |
| M3 grub screws, 4 to 6 mm, with M3 nuts | The coupler: a nut sits in each printed pocket and the grub screw goes through it onto the shaft. On the motor's shaft, onto one of the two flats | 2 |
| M3 screws with nuts | The box onto the bracket's upright, if the box is used | 4 |

The bracket itself is held by the focuser's own centre thumbscrew. That is
also the screw that sets how stiffly the drawtube moves, so it has to hold
the bracket without locking the tube.

## Wiring

The motor's white plug fits the driver board one way round. The rest:

| Nano | Driver board |
|---|---|
| D4 | IN1 |
| D5 | IN2 |
| D6 | IN3 |
| D7 | IN4 |
| 5V | + |
| GND | − (most boards print a minus sign, not "GND") |

Red for 5V and black for GND by custom; any four colours for the rest.
Leave the board's jumper cap on: it switches the motor's supply. Wire it
with the USB lead out.

## Loading and trying it

`arduino-cli` compiles the firmware in `firmware/focuser/`. Once, to install it:

    curl -fsSL -o /tmp/cli.tgz https://downloads.arduino.cc/arduino-cli/arduino-cli_latest_Linux_64bit.tar.gz
    tar -xzf /tmp/cli.tgz -C ~/.local/bin arduino-cli
    arduino-cli core update-index && arduino-cli core install arduino:avr

Then:

    ./focuser.py flash         load the firmware; tries the old bootloader, then the new
    ./focuser.py test          a quarter turn one way, then back
    ./focuser.py move 200      that many half-steps; 4096 is one turn, minus is the other way

On the 150P, with the motor in place of the knob on the bracket's side, a
plus move takes the drawtube out and a minus move brings it in. The motor
is too weak to harm anything at the end of the travel: it stalls and ticks.

The two shafts have to be in line. With the motor's ear screws done up
where they happened to sit, the printed coupler bound and the motor fell
short of every move, camera on or off. Slacken the ear screws, run the
motor so it settles where it wants to be, and tighten them there: draw
round the ears and tighten on the bench if the nuts cannot be reached on
the telescope. Screws left loose show as a quarter turn of nothing each
time the direction changes.

The firmware steps every 10 ms, twenty seconds to the half turn. At 2 ms the
motor turned on the bench but had too little pull for the drawtube.

The Nano's USB socket is the weak point. With the box hanging on the
telescope the lead's weight worked the plug loose, and the Nano came and
went every second or two until it was reseated: tie the lead to the tube.

The Nano cannot tell whether the motor turned, so watch the shaft. A motor
that buzzes without turning has two of the four signal wires swapped.

The Nano is found by its USB chip's name (`1a86`, the CH340), or by
`serial_match` under `[focuser]` in `config.toml`, or name it with `--port`.
Its orders are lines beginning with a colon, so bytes meant for a mount's
handset that reach it by mistake move nothing.
