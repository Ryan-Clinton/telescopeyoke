# Changes

What each release added, and what it has and has not been proven on. The
README's "Current status" is the table, and `docs/validation.md` the full account.

## Not yet released

- **Polar alignment says what to do with your hands**
  (`docs/calibration.md`). Centre the azimuth bolts first. More than 2° out
  to one side: turn the whole tripod, drawn from above as a clock face, with
  the centimetres each foot moves when the feet's spacing is in the settings.
  Otherwise which bolt to turn in and about how far, each drawn as a clock
  face, once the mount's bolts have been learned: `./polaralign.py --turned`,
  or two boxes on the screen, say what was turned, and the effect of a turn
  is worked out from the next measurement. Nothing is assumed about which
  bolt does what. Not yet used on the real mount.
- **From box to first galaxy** (`docs/first-night.md`): a first night for
  someone who knows none of the words, with the explanations folded away and
  each step marked as proven on a real mount or not yet. Its companion,
  `docs/how-it-all-works.md`, explains afterwards what each step was.
- `./mount.py findhome` gives each place's own miss from the fit, and leaves
  out one place, never more, that sits far from what the rest agree on.
- Fixed: a handset lead that comes out, or was never in, is a refusal that
  says what to do (`MOUNT_NOT_CONNECTED`), where it was a traceback.
- **`./mount.py findhome` and `truehome`** (`docs/calibration.md`): after a
  polar alignment, one run of plate solves either side of the meridian
  gives where the home position really is, apart from a tube out of square
  and what is left of the polar error; the mount is then driven there for
  the joints to be marked, and a second run after a restart shows what is
  left. Nothing remembered from earlier is used, and nothing moves except on
  a measurement from the same session that fitted. Simulated mount only.
- `docs/calibration.md`: setting a mount up in order, from a rough level to
  a marked home, and why `settime` is not automatic.
- `./mount.py settime` gives the handset this computer's date and time and
  the site's position, so they need not be typed on its keypad: press ENTER
  through its start-up screens and run it. Moves nothing. Run once on the
  real handset, where it worked.
- `./mount.py nudge`: from home, tips the tube 5° on the Dec axis and brings
  it back, with the same dry run, lock and limits as any move. The smallest
  move there is, for a person beside the mount to see that it really turns.
- **The mount's word is checked.** After the night the motors stopped while
  the handset reported every move as made: a GoTo with centring whose
  correction changes nothing, a polar measurement or pointing survey whose
  plate solves come back the same, and a skyline survey whose pictures do
  not change now stop the mount and refuse with `MOUNT_NOT_MOVING`
  (`moved.py`). By day it only records what it sees: its first real frames
  showed the optics' own marks passing for an unchanged view.
- **Measurements in place of assumptions**, each one command, none yet run
  on the real mount: `./polaralign.py --repeat 5` (does the polar
  measurement repeat?), `./camera_test.py --timing` and `--trail` (how long
  is the shutter really open?), `./mount.py response` (does the drift answer
  the Dec motor in proportion?), `./mount.py pointing` (is one pointing
  correction for each side enough?), `./focus.py --report` (how quickly was
  a turn of the knob heard?).
- **`./ty characterise`**, and the application's **Rig knowledge** screen:
  what this rig has had measured about itself, and for each thing it has not,
  the command, or on the screen a "Measure this" button. A measurement that
  moves the mount is shown as a plan first.
- The check that the telescope turned keeps every judgement with its
  figures (`cache/moved_log.jsonl`: how far the mount was turned, how far
  the view was seen to move) and the two pictures behind every "same view"
  (`cache/moved/`), so its first thresholds can be set from real frames.
- `./polaris.py find` looks within 1.6° instead of 3° when `polaralign.py`
  put the axis close to the pole in the last fortnight.
- The README now opens with what makes telescopeyoke different (a home
  position set by eye, a manual focuser, a garden skyline, setting up before
  dark, a rough polar alignment, short exposures rebuilt from the raw
  frames), each marked with how far it is proven. "Current status" is a
  table; the night-by-night account has moved, whole, to
  `docs/validation.md`. "Three parts" has become "The scripts underneath".
- **Focusing by ear, reworked for quick frames** (`docs/focus.md`). A click
  and a tone for every frame measured, the tone higher as focus improves,
  with the camera already exposing the next frame. Three levels it moves
  between by itself: quick binned frames judged one at a time, then many
  stars on binned frames, then the full sensor with the readings steadied.
  Words only at the turning points: "Level two", "Level three. Fine focus",
  "Minimum passed. Reverse slightly", "Best focus", "Focus good. Hold".
  Sizes are also given in arcseconds, the levels are set in them, and each
  run that ends on "Focus good" teaches the next what good focus comes to.
  Every frame's capture, measuring and feedback times are printed and kept.
  Proven on made-up star fields only: no real camera has run it.
- Changed: `focus.py` no longer speaks every reading, and `--tones` has gone,
  the click and tone being what it does unless `--quiet`. The Focus screen's
  sound choice is "Clicks and tones" or "Silent".
- The camera layer takes a purpose, `cam.use("focus_fast")`,
  `cam.use("focus_fine")` or `cam.use("imaging")`, and sets the binning
  itself on either route. A camera that will not bin carries on unbinned.
- The focusing sounds no longer need `ffplay`: Linux plays them with
  `pw-play`, `paplay`, `aplay` or `ffplay`, Windows by itself.
- **First night of polar alignment by plate solving on the real mount**
  (6 October 2026): from about 6° to 0.2° from the pole in five rounds.
  `./polaralign.py --step DEG` turns less between photographs, for a garden
  where the third would be of a house or a tree, and a round waits 5 s after
  each turn, not 30.
- **`focus.py` measures only the bright stars.** Far out of focus it had been
  reading the sky's grain. `--numbers` speaks each reading in place of the
  click and tone.
- **The pointing error is kept for each side of the meridian**, not as one
  figure reversed across the pole, which sent every first GoTo across the
  meridian 6° wide on the real mount.
- **`focus.py --field`** goes first to a bright star with many round it
  (it moves the telescope), and the meter no longer takes specks of grain
  for stars when the focuser is far out.
- **The final picture is framed where most frames sat**, not where the
  sharpest one happened to be, and the live run matches stars on a frame that
  has drifted past the rough line-up, so it knows how far it has drifted and
  re-centres when it should.
- **An object that fills the frame keeps its glow**: only a level is taken
  off its sky, and the colours are balanced on the stars alone.
- **The live picture is finished like the final one** from the fifth frame,
  and a run that cloud stops leaves the live view running.
- **`polaralign.py` keeps clear of what is known to be in the way** and goes
  back to where it started when a photograph will not solve.
- **A run says so when frames arrive faster than their exposure.** The 183C
  here exposes for about 0.63 of what it is asked; see the README.
- **`horizon.py --trace --torch`**: by night, with a torch fixed along the
  tube, what it lights is in the way and a dark frame with no stars is
  cloud. Tried on the real mount; the first survey was spoiled by cloud
  arriving, which it now notices.
- **`solve.py` tries again on a frame averaged in blocks** when stars too
  soft to be taken for stars leave the first try with nothing.
- **The skyline from a phone panorama** (`./panorama.py`, and the Horizon
  screen): the line between sky and everything else is found in the picture
  and can be redrawn, two marks tie it to the compass, and panoramas from
  other heights add doubt where near things sit differently. No motors, a
  few minutes. Found well in two real panoramas and badly in a third; not
  yet tied to the compass for real.
- **The planner uses a measured skyline directly**, from `cache/horizon.json`,
  raised by `margin` under `[horizon]` (2° unless changed). There is nothing
  to copy into `config.toml` any more; `use_survey = false` leaves it out.
- **`horizon.py --trace` looks less and says more.** It starts 30° apart and
  adds bearings only where the skyline bends; it starts from the skyline
  already measured and looks further only where that is wrong; by day each
  small square of a frame is judged by brightness, smoothness and colour
  against the day's own sky; a frame showing the top itself, by day or among
  stars, ends the search there; by day it waits only until two frames agree
  and reports how long that took; and every look's picture is kept, marked
  with what was not taken for sky. `--show` and `--forget` are new. On a
  made-up garden it takes about 60 looks from nothing and about 22 from a
  known skyline. None of this has been run on the real mount.
- The camera on a USB 3 lead, timed indoors: a full frame at a 1 s exposure
  in 1.54 s, against 9.3 s on USB 2. Figures in `docs/validation.md`. No
  night has been run on it yet.
- Fixed: `./camera_test.py --throughput` could leave the camera on native
  transfer, after which no frame could be read by anything. It now stops the
  exposure before changing back, and the camera is put back on FITS
  whenever it is opened.

## 0.2.1: two telescopes, and asking a controller what it is

For someone who already has a working setup, perhaps with two telescopes and
EQMOD: it fits beside what they have, and can find out safely whether it can
talk to their mount.

- **Rigs**: more than one telescope on one computer, each with its own
  settings (`rigs/NAME.toml`) and its own frames, pictures and measurements.
  `./app.py --new-rig NAME`, `./app.py --rig NAME`, `./ty --rig NAME ...`,
  and `./ty rigs` or the application's Rigs screen to see them all.
- **`./doctor.py --report --probe PORT`** asks whatever is on a serial port
  you name what it is, as a SynScan handset and then as a motor board, with
  questions that only read. For controllers such as an EQStar, where nobody
  yet knows whether telescopeyoke can talk to them.
- The hardware report lists each serial port's adapter, maker and USB
  numbers, and whether the handset gives a position (never the position).
- On Windows the doctor says when ASCOM or EQMOD is installed, and that only
  one program can have the mount's port. Neither is used or changed.
- Azimuth by day from a remembered landmark (`landmark.py`).
- Fixed: the doctor stopped dead, instead of reporting it, when a mount
  reached without its handset did not answer.

**Proven on, and not**

Nothing has changed in what has run on real equipment since 0.2.0. Rigs have
been run only as tests, never with two real telescopes. `--probe` has never
met a real controller: finding out whether an EQStar or another EQMOD-style
controller answers is what it is for. The ASCOM and EQMOD notice has not run
on a computer that has them. `landmark.py` has not been run on the real
mount. The README's "Current status" has the rest.

## 0.2.0: the application and the demo

Everything since the first night, and the first release someone else can try
in one step with no telescope.

**Try it with nothing plugged in**

- **TelescopeYoke (demo)** is the whole thing on a pretend telescope: a
  pretend mount, camera and sky, with the real centring, focusing and
  stacking code running on them. Nothing real is connected or moved, and its
  files are kept in a folder of their own.
- One step to start it, from the release's zip. Ubuntu: `./install.sh
  --demo`. Windows: double-click `try-demo.cmd` (Python 3.11 or newer must
  be installed first).
- `./tour.py` records the demo being used; the animation in the README is
  what it wrote.

**New**

- **The application** (`app.py`): one window with everything in it, started
  from the applications menu on Ubuntu or the Start Menu on Windows. Every
  move is checked with a dry run and shown as a plan; nothing turns until you
  confirm it. `console.py` is the same observing screens as a page in a
  browser.
- **A Windows port.** It runs natively on Windows 10 and 11, with the camera
  read through Altair's own library instead of INDI.
- **A hardware report in one command**: `./doctor.py --report`, or "Write a
  hardware report" on the application's Doctor screen. It says what the
  computer is, what the handset says the mount is, and every check, with
  your location left out, and which release or commit it was run from.
  Nothing is moved to make it.
- **The mount without its handset**, through the SynScan Wi-Fi adapter or an
  EQDIR lead (`direct.py`).
- **A rewritten imaging pipeline**: every raw frame kept, poor frames
  rejected, stars lined up to a fraction of a pixel across a turning field,
  clipped and weighted stacking, a quality pass, calibration frames, and
  several sessions combined into one picture.
- **Focusing by ear**: many stars measured at once, and the result spoken.
- **Making the best of a rough polar alignment**: the drift is measured,
  predicted anywhere in the sky, and a motor is crept against it.
  `polaralign.py` measures the polar axis itself.
- **A horizon survey** that finds what blocks the sky, by night or by day.
- **For programs and AI agents**: `--json` from every script in one shape,
  `--dry-run` for anything that moves, the `ty` command, a read-only web API
  and a read-only MCP server.

**Proven on, and not**

- Under real stars, by the author, on Ubuntu: a Sky-Watcher EQ3 Pro SynScan
  (handset firmware 3.35), an Explorer 150P and an Altair Hypercam 183C.
  The planner, mount moves, plate solving, `goto --solve`, `sync`, camera
  frames and focusing have all run there.
- On Windows 11 the tests and the demo pass and the camera, a Hypercam
  183C, has taken frames indoors. **No mount has been driven from Windows**, and `try-demo.cmd` has
  not yet been run on a real Windows machine.
- The application has been used in the demo only, not with a real mount or
  camera. The stacking pipeline, the drift correction, polar alignment and
  the handset-free link were written or rewritten since they last met real
  equipment; the README says which is which.
- The two questions `--report` asks the handset (its firmware version and
  the mount's model) are from Sky-Watcher's published protocol and are
  tested against the simulated handset; no real handset has been asked yet.
- Nobody but the author has run it. EQ5, HEQ5 and EQ6 owners with a SynScan
  handset: a report from you, working or not, is the most useful thing this
  project could get.

Tests run on every push on Python 3.11 to 3.14, on Ubuntu and on Windows,
with no hardware.

## 0.1.0: first light

The first release: what worked on the first night under real stars. The
night planner, SynScan mount control through the handset, plate-solve
centring, a spoken focus aid, short-exposure stacking, a status page, a demo
mode with a simulated mount, and `doctor.py`.
