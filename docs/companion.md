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

Install TelescopeYoke as [Setup](setup.md) says for Windows (Python 3.11
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

which measures the night's frames and says where the time went, target by
target and filter by filter. `--json` gives the same as data. Frames can be
FITS or XISF (uncompressed or zlib; LZ4 and zstd are not read yet).

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
