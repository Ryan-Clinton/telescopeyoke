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
As it goes, a run (and `--check`, `--walk-in`, `--find`, `--sweep`) also
keeps its stage, readings and result in `cache/focus_stream.json`, with the
brightest star at the start and now, for the live stream's focus look
([streaming.md](streaming.md#focusing-and-polar-alignment-on-air)).

    ./focus.py --sweep               one sweep and fit, then back to the start: the curve only
    ./focus.py --find                far out, no star measuring: half a turn at a time in, then out, until stars do
    ./focus.py --measure-step        from focus, in until the stars are 2.5 times their size; a quarter of that is the step
    ./focus.py --measure-backlash    the slack, on the steep side of the curve, twice; half as much again is kept
    ./focus.py --walk-in             from a little outside focus, set by hand: in 64 then 32 half-steps at a
                                     time, slowly (40 ms a half-step), measuring each, to the sharpest;
                                     then back out past the best by the gears' slack (the measured backlash,
                                     or 256) and in to it, saying whether the motor lifted it;
                                     the collimation is checked on its first doughnuts (collimation.md)

No move of a run goes further than `[focuser] travel` (512 half-steps by
default, overshoot included) from where it started: a move beyond it is
refused before the motor turns. The Sharpie line marks focus, so focus is
always that close. On 23 October 2026, with focus "within microns", a sweep
on guessed sizes, stopped part way twice and started again, left the
drawtube about an inch out. Since then:

- `--motor` and `--sweep` refuse until the step and slack are measured
  (`--walk-in` to focus, then `--measure-step` and `--measure-backlash`),
  and refuse a sweep whose ends and overshoot would not fit in the travel;
- stars that measured at the start and are gone near it partway through a
  sweep stop the run and send the focuser back to the start: that is the
  focuser, not cloud;
- a run stopped part way (Ctrl-C, or a background stop's SIGTERM) lets the
  move under way finish and takes the focuser back to where it started.

The guesses, used only for the measuring, are a step of 64 and an overshoot
of 256, small enough to fit the travel. What is measured is kept in
`cache/focuser.json`. That slack was seen
before the night of 18 October 2026, when the motor's screws were tightened
to take up backlash, so it is likely less now: measure it again
(`--measure-backlash`) before trusting the starting figure.

A Sharpie line on the focuser's drawtube marks where focus was on 18 October
2026. With the drawtube at the line the stars are already close, so a focus
run starts in the right place instead of searching for it. A hair's breadth
either side of focus was the difference between a good reading and a poor
one on the focus aid, which is why the step has to be measured
(`--measure-step`): the starting 256 half-steps is many times the depth of
sharp focus at f/5.

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

## Checking the motor on the bench

How far the motor really turns, how much slack its gears have, and how
closely it comes back to a place can be measured with no stars, off a
camera looking down on the shaft:

    ./focuser.py bench --watch http://PHONE:4747/video     a phone running DroidCam
    ./focuser.py bench --watch /dev/video2                 a webcam
    ./focuser.py angle --pictures a.jpg b.jpg              the stick's angle in pictures already taken

On the shaft, a printed protractor cut out round the motor and a thin stick
(a cocktail stick) across its middle, turning with the shaft, blacked all
along with a marker: bare wood is too like the paper to be found. The camera
looks straight down from a few centimetres, held still, with the
protractor filling a good part of the picture. The stick is found as the
dark bar through the protractor's middle, and its centre line fitted along
its whole length, to about a fifth of a degree a picture. It is measured against the picture's own rows, so
a phone that switches lens by itself, which a Pixel does up close
(19 October 2026), shifts and zooms the picture without spoiling it; a
camera that turns would. Each answer is kept in
`cache/focuser-bench-DATE.json`, its pictures in `cache/focuser-bench/`,
each with a marked copy showing what was found.

A phone left with no viewer locks and stops sending, and the first frames
of a new connection come before its focus settles, so the run holds one
connection open for its whole length. The free DroidCam takes one viewer
at a time.

Off the telescope the gearbox has nothing to push against, so the slack
it shows is the gearbox's alone; on the focuser, under the drawtube's
load, the coupler and the focuser add theirs. The degrees a half-step is
and how closely it comes back carry over.

**On 19 October 2026**, the motor off the telescope on a stool, the
screws tightened the night before, watched by a Pixel 9 on DroidCam
(`cache/focuser-bench-20261019-2105.json`):

| | Measured |
|---|---|
| A half-step | 0.088° (45.1° for 512): 4088 to a turn, 4096 on paper |
| Slack, unloaded | 30 half-steps one way, 29 the other: about 2.6° |
| Back to the same place | within 0.10° over three trips of 256 out and back, about one half-step |
| Reading noise | 0.20° a picture: moves of 16 half-steps and more read cleanly, single moves of 4 (0.35°) barely |

The smallest turn a hand could give the knob was about 0.1° to 0.4°, and
that hair's breadth moved the focus aid's reading from 3 to 11 to 20, so
focus is that sensitive; the motor comes back within 0.1°. The slack is
some thirty half-steps, not the thousand seen before the screws were
tightened, so the 1536 overshoot is far more than needed: on the telescope
`./focus.py --measure-backlash` sets it, coupler and load included.

## When the motor cannot lift the drawtube

On 19 October 2026, with the camera's weight on the drawtube, the motor
moved it only downhill; uphill the drawtube did not move, nearly a turn of
lost motion after each reversal, at every speed from 5 to 40 ms a
half-step. Nobody saw whether the motor's shaft turned meanwhile (the Nano
only knows the steps were sent), so a stalled motor and a slipping coupler
are both still possible. The coupler had one grub screw of its two, as
built: the second was never fitted. A Sharpie line across the motor's
shaft, the coupler and the focuser's shaft tells them apart: all three
still in line and nothing moved is a stall; the line broken at the
coupler's motor end or focuser end is slip there. What worked: point where the weight pulls the drawtube in (M31,
east of the meridian, that night), set it a little out of focus by hand,
and let `./focus.py --walk-in` bring it in. It reached HFR 1.58, the
sharpest yet, and stops two moves past the best (at most 64 half-steps
inside it), since it cannot go back. Far out, the search (`--find`) now
follows the doughnuts' size and turns back the moment they grow. 

### 20 October 2026: too slow to see, not too stiff

In daylight, the camera level: twelve moves out at 20 ms a half-step and
forty at 40 ms, and nothing could be seen to turn. At those speeds the
motor turns once in three to six minutes, and through the 4 mm Crayford-style
shaft the drawtube moves a few hundredths of a millimetre a second: too
slow and too small to see. With the camera and bracket off, the focuser
turns easily by hand and its centre thumbscrew makes no difference to it;
the stiffness felt turning the motor's shaft by hand is the motor's own 64:1
gearbox, which is normal. So "nothing moved" did not show the focuser too
stiff, as first written here. To see a move, use a fast one with a strip
of tape on the coupler: `./focuser.py move 4096 --ms 3` turns once in
about 12 seconds. The coupler has one of its two grub screws; the second
is to be fitted.

The 150P's focuser is most likely a Crayford-style friction drive, not
rack and pinion (unconfirmed until seen from underneath:
[research notes](research/focuser-stiffness-2026-10-20.md)): a smooth 4 mm
shaft pressing on a flat on the drawtube, which spins without moving the
tube if the pressure is too little or the flat greasy. `./focuser.py look
--watch URL` keeps one picture from the phone, for marking which screw is
which.

### 20 October 2026, afternoon: the motor is not up to it

With moves fast enough to see (10 ms a half-step, a quarter turn in 10 s)
and the camera off: coupled to the focuser, the motor turned it inward but
outward managed about a sixteenth of a turn and stopped. The shafts are in
line by eye, and the focuser turns easily by hand. Run free, off the
focuser, out and back ten times, the motor itself was clearly weaker one
way: the owner could hold it back with a finger one way, much less the
other. A healthy 28BYJ-48 is the same both ways, so this one (or its
wiring or driver board) is faulty, and even healthy it is marginal for
this focuser. Decided: a stronger drive. In order of cost: a fresh
28BYJ-48 with a 3:1 to 5:1 gear or belt reduction; a NEMA 14 or NEMA 17
on a TMC2209 driver at 12 V, with a bracket for it (several to more than
ten times the torque, no gearing); or a ZWO EAF through INDI. The rest of
the project (`focus.py --motor`, `--walk-in`, the load test) stays.

### 20 October 2026, evening: two coils help, but not enough

With two coils on at every step (`:F1`, now what `Focuser.open()` always
asks for; `--half` for the old way), 10 ms a half-step, coupled: camera
off, outward went better than on half-steps at first, then struggled;
inward ran smoothly; camera on, outward did not move at all, on the
Nano's own short USB lead too, though it went with the slightest help by
hand. At 30 ms a half-step, two coils, camera on, it went outward and
inward unaided: `Focuser.open()` now sets 30 ms as well (`--ms` to try
another), so every move, focusing included, is on two coils at 30 ms. To tell
whether a slow move is turning, rest a finger and thumb lightly on the
focuser's other knob: the turn is felt long before it can be seen. The Nano
cannot tell: "moved +2048 half-steps" means the steps were sent, not that
the shaft turned.

A motor weaker one way than the other is not what a stalled 28BYJ-48 does
to itself (a stall does not harm a stepper's coils). Ways it happens, most
likely first:

1. **Two of the four signal wires in a different order** (D5 and D6 the
   usual pair): the coils are then fed out of turn, and the commonest
   report of a 28BYJ-48 strong one way and weak or dead the other is
   exactly this, cured by swapping the middle two. Checked that evening:
   the wiring was right, as in the table above.
2. **One coil or one driver channel weak**: the four lights on the driver
   board, at a slow speed, should each light in turn; with a multimeter,
   red to each of the other four wires reads the same (about 50 Ω on the
   5 V motor).
3. **A damaged plastic gear** in the 64:1 gearbox, least likely: a
   chipped tooth catches at one place in a turn, both ways, rather than
   making the motor weaker one way all the way round, which is what was
   felt.

A fresh 28BYJ-48 with its driver board (a few pounds, usually sold in
fives) settles 2 and 3 at once.

### 21 to 22 October 2026: inward only again, on the sky

With two coils at 30 ms, it still could not lift the drawtube out with the
camera on. A sweep's outward moves did not turn it, and `move 320` out
changed nothing. Each time, the person set it a little out by hand and
`--walk-in` brought it in. Over six runs the best was HFR 2.19, slightly
better than the usual 2.28 but well short of 19 October's 1.58, and each
run ended past focus because it cannot step back. The walk-in now starts
from doughnuts, takes 16 and then 8 half-step moves near focus, and
re-reads a cloud. Below 8 half-steps the seeing hides the difference.
[The night's record](nights/2026-10-21/focuser.md). On 24 October 2026 a
walk-in from the drawtube a millimetre past the line reached HFR 2.16 in
under two minutes and ended 24 half-steps inside it at 2.55. The person
asked for the move back to be tried rather than assumed impossible, so a
walk-in that ends past its best now makes that one move out, measures, and
says whether the drawtube rose (`back_out` in its result). On 23 October 2026 a `--motor` sweep on guessed sizes, stopped twice part way, left the drawtube about an inch from the line and lost the night ([the record](nights/2026-10-23/focus-runaway.md)): the sweep is now refused, and every move is held within `[focuser] travel`.

### 30 October 2026, evening: it lifts again

With the camera on the drawtube, the motor turned the focuser outward:
two moves of 64 half-steps (felt on the other knob as a small turn each),
then five of 512, 2,688 half-steps in all, and the person judged the knob
went over half a turn uphill without a stop. Two things had changed since
21–22 October; the test below settled which:

- The person found a group of six bent pins on the far side of the board
  that may have been touching each other, and straightened them.
- The Nano was plugged into the powered USB 3.2 hub (Realtek `0bda:0411`,
  its own supply) instead of the laptop.

The same evening, half a turn out (2,048 half-steps) with the Nano back on
the laptop's own port, pins straightened, moved the drawtube only a tiny
amount before it stuck; back on the hub, the same move went the whole half
turn. **The hub is the fix: keep the Nano on the powered hub.** The
laptop's port cannot give the 28BYJ-48 enough current to lift the
drawtube with the camera on, which fits everything since 19 October. The walk-in's move back out now goes out past the best by the gears'
slack and then in to it: a move of only the few half-steps it had gone
past was lost in the slack before the drawtube rose.

### Finding where the turn is lost (`./focuser.py load-test`)

In daylight, on the telescope with the camera on: the blacked stick and the
printed protractor on the focuser's other knob (it shares the motor's
shaft through the coupler), the phone looking straight down on it as on the
bench, then

    ./focuser.py load-test --watch http://PHONE:4747/video

It turns 256 half-steps (22.5°) three times out, three in and three out
again, reads how far the knob really turned each time, and says what share
of a steady move gets through each way and how much is lost at each
reversal. Run it with the tube level and with it pointing high, and once
with the camera off:

- the turn gets through both ways: nothing slips under that load;
- it slips one way only: the bracket swinging on the focuser's thumbscrew,
  or the coupler's grub screw; Sharpie marks across bracket and focuser and
  across coupler and shaft show which joint moved;
- it slips both ways: the coupler first; if it passes with the camera off,
  the 28BYJ-48 (about 30 mN·m, 300 gf·cm, measured on a ULN2003 board) is
  too weak for the focuser's friction and the camera's weight. Then: the motor run bipolar from an A4988 or
  DRV8825 (about twice the torque), a NEMA 14 or 17, or a spring taking
  the camera's weight off the drawtube.

Its answer and pictures are kept like the bench's, in
`cache/focuser-bench-DATE.json` and `cache/focuser-bench/`.

## Temperature (planned, not built)

The Hypercam 183C has no thermometer, and the cold, damp night of 17 October
2026 brought stronger stripes and long frames that never arrived
(`docs/banding.md`). Telling cold from damp needs the camera's temperature
against the dew point at the telescope, and the forecast's dew point is the
only one there is now. The Nano sits about 3 inches from the camera and uses
only D4 to D7, so it can carry both readings. Until then, each cooldown set
uses the darks themselves as a thermometer (their mean over their median,
and the share of hot pixels).

| Part | Measures | Wiring | Notes |
|---|---|---|---|
| **BME280** breakout (temperature, humidity, pressure) | the air at the telescope, and so the dew point | I²C: SDA to A4, SCL to A5, GND, and 3.3 V or 5 V as the board says | Buy this first: it answers most of the question alone. Outside the Nano's box on short wires, never sealed in it, away from the motor; a small hood (a bottle cap) keeps dew off it. |
| **10 kΩ NTC thermistor, B3950, 1 %** | the camera body | One leg to A0, the other to GND; a 10 kΩ resistor from A0 to 5 V | A flat head, metal tab, ring lug or bare epoxy bead, flat on the body near the front flange under aluminium tape. Not the magnetic kind (the body is not steel) nor the round steel tube (it barely touches). The 2 m lead can be cut short; its plug will not fit the Nano, so cut it off or use a matching socket. |

No screw of the camera's own is needed. Altair publish no body screw sizes,
and the body has no tripod hole: the only threads are the front T2
(M42x0.75) and the nosepiece insert. Some owners of ZWO cameras feed a
thermistor in through the ST4 port to sit under the sensor; that means
opening a camera that is not ours, so it is not done here. If a back-plate
screw turns out to suit, a ring lug under it is slightly better contact
than tape.

What the software will need, written with its test before the parts are
first used: a `:T` order in `focuser.ino` that answers with each reading;
`focuser.py` reading it; and `camera_test.py --cooldown` and the night's
log recording the camera's temperature and the dew margin measured at the
telescope. Later, the same readings can move the focus as the night cools.

### Parts ordered, 22 October 2026 (AliExpress, about a week to three weeks)

A stronger, solder-free drive for the Printables NEMA 17 bracket
([model 436129](https://www.printables.com/model/436129)), about £32 in all:

- the motor: a 17HS4401 NEMA 17 (40 mm, 0.4 N·m), the "no plug" version;
- the driver: two TMC2209s (one spare) on a red A4988/DRV8825
  screw-terminal carrier board;
- power: a 12 V 2 A supply with a 5.5 × 2.5 mm socket lead;
- the coupling: D20L25 elastic couplers, 4 × 5 and 5 × 6 mm (the focuser's
  shaft is not yet measured). The printed coupler's model
  (`Conector_Enfocador_SW_200P.stl`) has a 4.0 mm round bore 16 mm deep for
  the focuser and a 3 × 5 mm slot for the motor's flatted shaft. On 31
  October the 4 × 5 metal one replaced the printed coupler on the 28BYJ-48:
  it fits both shafts well, with a grub screw on the motor shaft's flat.
  The same afternoon the Nano went onto a screw-terminal board (IN1 to IN4
  on D4 to D7 as before) and `./focuser.py test` turned the focuser a
  quarter turn out and back, felt by hand; it was left 64 half-steps in
  from where it stood.
  Two other couplers came with bores far too big. The gear slack has not
  been measured with it on (`./focus.py --measure-backlash`);
- fixings: a Nano screw-terminal board and M3 screws.

For the camera's temperature (below) an M3 ring-lug 10 kΩ B3950 thermistor
and 10 kΩ resistors are on the way too. Jumper leads are on hand from the
old focuser.

If the motor arrives with a socket and no lead, a 4-pin NEMA 17 cable is
needed.

What the software needs on arrival: the Nano's firmware driving STEP/DIR/EN
instead of the ULN2003, and `focuser.py` and `focus.py` counting full steps
× microsteps instead of 28BYJ-48 half-steps, each with its test, before the
first use on the sky.

