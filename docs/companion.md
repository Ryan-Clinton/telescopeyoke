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

With Claude Code in the TelescopeYoke folder, asking "why did last night
go wrong?" runs the `night-review` skill, which finds the logs and runs
the companion for you.

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

What it cannot see without NINA's log: frames the capture program rejected
and never saved, and what the program did in a gap.

## NINA's own log

Given NINA's log (`%LOCALAPPDATA%\NINA\Logs`, one file a session), the
companion reads what NINA did: every exposure started and every file saved
(so exposures that were never saved show), each step of the sequencer with
when it began and ended or failed (autofocus, centring, slews, dithers,
meridian flips, waits, parking, reconnecting, as NINA's own source writes
them), the safety monitor's changes, the dome shutter, USB devices lost,
and errors. A gap between frames is then explained by what NINA logged in
it, with the minutes each step took:

```
python companion.py report "C:\path\to\frames" --phd2-log "...\PHD2_GuideLog_DATE.txt" --nina-log "...\NINA\Logs\DATE.log"
```

Each exposure is given its purpose: **autofocus** or **plate solving** by
the sequencer step it fell inside (or a plate solver's copy NINA saved of
it), **focusing** when the focuser moved before and after it within one
filter outside autofocus (a move at a filter change is that filter's focus
offset), else a **frame**. Only frames count against "saved", and only
frames NINA saved as files are judged.

Without the frames, the logs alone give a night of their own: exposures by
purpose, filter and length, how many frames were saved, the frames judged
by **NINA's own star detection** where its log has it (its HFR and star
count against that filter and length's best), the time in each kind of
step, events and errors, and
with PHD2's log how many exposures were guided all through, and any stretch
where PHD2 said it was guiding with far fewer guide steps than its cycle
makes:

```
python companion.py report --nina-log "...\DATE.log" --phd2-log "...\PHD2_GuideLog_DATE.txt" --night 2026-11-07
```

`--night` keeps one night (noon to noon) of a log covering several;
`--tz Europe/Rome` reads logs written on a computer in another zone (both
programs write their own local time).

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

**Real logs from other observatories**, read offline (19-20 November 2026,
companion as of commit `73c78d2` and after): logs their owners published on
GitHub, not copied here because they carry no licence. To check the same:

| Log | Where | What the companion read |
|---|---|---|
| A NINA 3.2 night and its PHD2 guide log (a dome observatory) | [digital-stargate-manual, session 2026-11-07](https://github.com/maininimassimo-bit/digital-stargate-manual/tree/HEAD/data/sessions/2026/11/2026-11-07_2026-11-08) | 3,346 exposures, 3,307 of them snapshots; the dome, the safety monitor, 19 USB removals, the camera's errors; PHD2 silent 00:37-00:43 while it said it was guiding (that night's PHD2 drove its own simulator camera) |
| A NINA 3.2 sequencer night | [the same, session 2026-09-13](https://github.com/maininimassimo-bit/digital-stargate-manual/tree/HEAD/data/sessions/2026/09/2026-09-13_2026-09-14) | M 27: 27 ten-minute lights told from 42 autofocus, 7 plate-solving and 13 focusing exposures; 23 of the 27 acceptable by NINA's own star detection |
| Two NINA 3.1 and 3.2 nights | [obsybox, logexploit](https://github.com/aegiskeller/obsybox/tree/HEAD/logexploit/zzz_logfiles) | sky flats, their wizard's trial exposures and a bias counted as calibration; a framing loop of 307 exposures never saved, said as such |
| Four PHD2 guide logs of good and bad guiding | [PHD2Insight, samples](https://github.com/ste7e/PHD2Insight/tree/HEAD/samples) | the good night with no star lost, 0.75" RMS; the bad one 243 lost, 0.99" |

What this is not: no third-party night with its frames, logs and guiding
together has been read, and the companion has not yet run live beside
anyone else's observatory.

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
