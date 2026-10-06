# Changes

What each release added, and what it has and has not been proven on. The
README's "Current status" is the full account.

## Not yet released

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
