[README](../README.md) · [All docs](README.md) · [Hardware](hardware.md) · [Validation](validation.md)

# The companion: a second pair of eyes on an observatory that already works

For someone whose setup already runs a night (NINA, SGP, APT, SharpCap or
Ekos taking the frames, PHD2 guiding) and who wants to know, the morning
after or as it happens, what went wrong and why: `companion.py` watches,
measures and explains. **It never touches the observatory.** It reads the
frames the capture program saves and listens to PHD2; it has no command
that can move a mount, take a frame, turn a focuser or a wheel, or change
any setting. It can run beside a working setup on its first night.

## What it says

Every frame is measured: how many stars, how sharp (FWHM, in arcseconds
when the header gives the pixel size and focal length), how round, how
bright, how bright the sky is, the sensor's temperature against its
cooling target, and how guiding went during it (PHD2's RMS and any star
lost). Each frame is judged against the best frames of the same target and
filter that night, so no figure from another telescope is assumed. Then:

- **dimmed**: fewer or fainter stars (likely cloud or haze; the sky
  brighter too says which);
- **bright sky**: the stars are fine but the sky is brighter (the Moon,
  twilight, a light);
- **soft**: wider stars, with what is likeliest (guiding if its RMS was
  high, focus if the focuser's temperature has fallen since the best
  frames, otherwise focus or seeing);
- **trailed**: stars drawn out (guiding, or the wind, flexure or the mount
  when guiding looked normal);
- **off cooling target**: the sensor away from its set temperature;
- **guide star lost**: PHD2 lost its star during the frame;
- **no frames**: stretches with nothing saved, beyond the usual gap
  between frames, with what PHD2 was doing then (lost its star, stopped,
  dithering, a change of target or filter).

What it measured is always said apart from what it infers: "likely" means
the figures point that way, not that they prove it.

## Running it (Windows)

**The companion is not in the 0.4.0 download**: it was added on 19
November 2026, after that release. Until a release has it, take the
development version: on [the project's page](https://github.com/Ryan-Clinton/telescopeyoke),
Code > Download ZIP (or `git clone https://github.com/Ryan-Clinton/telescopeyoke`),
unpack it, and install as [Setup](setup.md) says for Windows (Python 3.11
or newer, then `install.ps1`). No `config.toml` is needed for this. Then,
in the TelescopeYoke folder:

```
python companion.py check "C:\path\to\tonights\frames"
```

says what it can read: how many frames, and what their headers give (the
target, filter, exposure, temperatures, pixel scale). Then either, live:

```
python companion.py watch "C:\path\to\tonights\frames" --phd2 127.0.0.1:4400
```

(PHD2's server on: Tools > Enable Server), which prints a line for each new
frame and a NOTE only when something changes; or the morning after:

```
python companion.py report "C:\path\to\tonights\frames" --phd2-log "C:\Users\NAME\Documents\PHD2\PHD2_GuideLog_DATE.txt"
```

which measures the night's frames and says where the time went, setup by
setup. `--json` gives the same as data.

Point it at **one night's lights**. Frames are only compared with others of
the same setup: the same night (noon to noon), target, filter, camera,
gain, exposure and pixel scale, so a folder holding several nights or
setups is split, never given one baseline. Frames can be FITS or XISF
(uncompressed or zlib). **In NINA**: Options > Imaging > Image file type
FITS, or XISF with compression none or zlib (LZ4 and Zstandard are not
read yet; `check` says so file by file).

## How to read a report

For each setup it gives four figures, kept apart:

- **measured**: the exposure time of every light frame it read;
- **acceptable**: what is left once the frames spoiled by something it can
  see are taken out, judged against that setup's own best frames that
  night (not against any standard, and not the same as fit for science);
- **unassessable**: frames it had nothing to judge against (fewer than
  three frames of that setup with stars, a capped camera for instance):
  never counted as good;
- **no frames**: stretches with nothing saved, beyond the usual gap
  between frames, **explained** when PHD2's log or a change of target or
  setup shows why, **unexplained** otherwise.

Every file found is accounted for: measured, or left out with why
(calibration frames, stacks, an unreadable or unsupported file). With
PHD2's log, a frame counts as guided only with guide steps all through it,
by the same rule TelescopeYoke's own PHD2 guiding uses (one step in a
five-minute frame is a guiding gap, not guiding).

What it cannot see: frames the capture program rejected and never saved,
and what the program did in a gap (focusing, a meridian flip, a download,
a camera recovery). That needs the program's own log, which is not read yet.

## A real report

The owner's own night of 5 November 2026 (the 183M, five targets, no
guiding then), read as if it were another observatory's, trimmed:

```
706 files: 693 light frames measured; 13 left out, no single-plane image (a stack or a colour picture).
M33 L (183m, gain 1500, 16 s) 00:23-01:41: 57 min measured; 37 min acceptable by its own best frames (139 of 213 frames), FWHM 3.86 px
    15 min (56 frames) dimmed: likely cloud or haze
    5 min (18 frames) trailed: likely the mount's tracking or the wind (no guiding to compare)
M33 G (183m, gain 1500, 16 s) 02:34-03:04: 27 min measured; 25 min acceptable by its own best frames (93 of 100 frames), FWHM 2.91 px
M81-M82 L (183m, gain 1500, 16 s) 04:21-04:51: 32 min measured; 13 min acceptable by its own best frames (50 of 119 frames), FWHM 2.18 px
    12 min (45 frames) dimmed: likely cloud or haze (the sky brighter too)
    6 min (22 frames) soft: likely focus or seeing
No frames 01:15-01:33 (18 min beyond the usual gap): not known: nothing it reads says (the capture program's own log would)
No frames 04:03-04:21 (19 min beyond the usual gap): changed from M106 L to M81-M82 L (measured)
Where the time went: no frames (explained) 44 min, dimmed 38 min, no frames (unexplained) 36 min, trailed 11 min, soft 6 min
```

That night's record agrees: five targets in one night gave 34 minutes of
M33 in L and little colour (`docs/nights/2026-11-04/183m-first-night.md`).
The 36 unexplained minutes are where the capture program's own log, which
the companion does not yet read, would have to say.

## What has been tried

On the owner's own real frames (5 November 2026, five targets, 693 frames:
it found the gaps between targets and filters, two 18-minute stretches with
no frames, and the soft, dimmed and trailed frames), and on a made-up night
in another program's style with known faults planted (cloud, soft focus
with a colder focuser, trailing with poor guiding, a gap where PHD2 lost
its star and stopped, the sensor off its target), each found and put down
to the right cause. Not yet beside anyone else's observatory.

## Or letting TelescopeYoke run it

The companion only watches. To have TelescopeYoke run the same equipment
(its plate-solved GoTo and centring, its imaging run and quality pass),
each part can be reached through its own ASCOM driver over Alpaca: in
`config.toml`, `[mount] link = "alpaca"`, `[camera]`, `[filterwheel]` and
`[focuser]` `backend = "alpaca"`, each with the driver's `address`
(`./alpaca.py find` lists them), and `[guider] backend = "phd2"` for PHD2
([Mounts](mounts.md), [Hardware](hardware.md), [Autoguiding](autoguiding.md)).
That is on the development branch only, and tried on ASCOM's simulator and
a pretend PHD2, never yet on real equipment: watch it first.
