# The motor focuser

[README](../README.md) · Guides: [First night](first-night.md) · [Setup](setup.md) · [Imaging](imaging.md) · [Calibration](calibration.md) · [Focus](focus.md) · Science: [Discovery](discovery.md) · [Validation](validation.md) · [Data](data.md) · Developers: [Contributing](../CONTRIBUTING.md) · [Agents](agents/README.md)

A 28BYJ-48 stepper motor on the focuser's shaft, driven by an Arduino Nano
on a USB lead. `./focuser.py` loads the Nano and turns the motor;
`./focus.py --motor` focuses with it, measuring the stars as it goes, with
nobody's hand on the telescope.

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

## Focusing with it

    ./focus.py --motor
    ./focus.py --motor --dry-run    only checks the focuser is plugged in; nothing turns

Point at a field with plenty of stars first (a rich cluster such as the
Double Cluster gives steadier readings than a lone bright star; `--motor`
focuses wherever the telescope is). It takes 1 s pictures at gain 1500 and
does what the established autofocus programs (N.I.N.A., Ekos's Linear 1
Pass) do, because one frame's HFR near focus jumps by half again from
seeing alone (18 October 2026: 4.9, 10.6, 5.5 over 96 half-steps), so no
single reading can say which way focus lies:

1. measures where it is (three frames); within 10% of the usual best it
   leaves focus alone (`--anyway` focuses regardless). The usual best only
   decides this: it is never the target, since a night of worse seeing has
   its own best;
2. goes out beyond the gears' slack and comes in to the top of a sweep, so
   every point is reached moving in and the slack never enters a reading;
3. sweeps in through nine positions a step apart, three frames at each,
   keeping each point's median and scatter, with a second's pause after
   each move for the tube to settle;
4. fits a hyperbola to the whole sweep, checked against two straight wings,
   and refuses a fit with too few points, no rise on one side, focus near an
   end of the sweep, R² under 0.8, a focus that moves by over half a step
   when any one point is left out, or wings that cross more than a step
   away. Focus off one end moves the next sweep that way; a flat sweep
   doubles the step; up to four sweeps;
5. goes out beyond the slack and in once to the fitted focus, so the last
   move is inward, and checks it with five frames: kept only if no worse
   than the start and near what the fit predicted (within the frames'
   scatter); otherwise back to where it started.

Every reading is numbered with its step and shown on the status page;
each sweep is drawn as text in the log. A run never goes more than two
turns from where it started. Each kept run is in `cache/focus_runs.jsonl`.

    ./focus.py --sweep               one sweep and fit, then back to the start: the curve only
    ./focus.py --measure-step        from focus, in until the stars are 2.5 times their size; a quarter of that is the step
    ./focus.py --measure-backlash    the slack, on the steep side of the curve, twice; half as much again is kept

Until measured, the step is 256 half-steps and the slack overshoot 1536:
the gears showed "well over a quarter turn" (1024) of slack, and the
overshoot must be larger than the slack, never smaller; too much costs only
time. What is measured is kept in `cache/focuser.json`.

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
