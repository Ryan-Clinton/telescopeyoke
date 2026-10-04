# Hardware notes

Tested setup: Sky-Watcher EQ3 Pro SynScan (handset firmware 3.35) on an FTDI
serial lead, Explorer 150P (750 mm), Altair Hypercam 183C on USB 2, a USB
webcam, Ubuntu 26.04.

Quirks worth knowing before changing code:

- **The handset answers serial commands while still on its version screen,**
  and then moves the mount by wrong amounts. Its clock shows year 2022 until
  set up; `mount.py` refuses on that.
- **The handset's GoTo overshoots next to the pole,** so `home` steers by the
  raw axis readout with fixed-rate slews.
- **Home position at this latitude:** counterweight bar at the lowest point
  of its swing, tube on top pointing at the pole.
- **West of the meridian the tube swings over the pole;** the Dec axis then
  reads past 90° and several signs reverse (`Mount.west()`).
- **After a slew the stars streak for up to 30 s** while the gears settle.
- **The camera's INDI device name contains a dot,** which the stock INDI
  command-line tools cannot address; hence `indi.py`.
- **Frames take about 4 s plus five times the exposure** with this driver on
  USB 2, and the driver needs `TIMEOUT_FACTOR` raised or long exposures fail.
- **The camera reports no temperature;** darks are scaled to each frame's hot
  pixels instead.
- **The web server never opens the mount's serial port.**

## The camera through Altair's library (`altair.py`)

The route used on Windows, and available on Linux with `[camera] backend =
"altair"`. **Nothing below has been run on a real camera yet**; it comes from
`altaircam.h` version 1.53.2 and from tests against a made-up copy of the
wrapper. Correct this section when the camera has been used.

- The sequence is: raw mode, full bit depth, software trigger, pull mode with
  a callback; then per frame set exposure and gain, discard anything
  waiting, trigger one, wait, pull one.
- **Still to confirm on the camera:** that the vendor's `altaircam.py` has
  the calls used (it was not available when this was written; they follow
  the header and ToupTek's wrapper, which Altair's is a renamed copy of);
  whether the 12 bits arrive at the bottom or the top of each 16-bit value
  (the code detects it from the first frame); that gain numbers mean the
  same as the INDI driver's; the Bayer pattern and which way up the frame
  is, compared with an INDI frame of the same star field. A flipped frame
  would send plate-solved corrections the wrong way, so do that comparison
  before `goto --solve` is trusted with this route.
- A frame that arrives sooner than the exposure could have finished is
  treated as a late one from an earlier exposure and thrown away.
- The wait for a frame is the INDI route's `12 + 6 x exposure` seconds, as an
  upper limit, until `./camera_test.py --throughput` has measured the real
  figure at each readout speed. Record those figures here.
- `[camera] readout_speed` is left unset: the camera keeps its own setting
  until the measurements say which level is best.

## Windows

- The handset's lead is found among the COM ports by its adapter's name; no
  port is ever guessed.
- A preview under `web/` cannot be replaced while the web server has it
  open; `host.replace_preview` retries for a second and then keeps the old
  one. Nothing else may use it.
- Speech is one PowerShell kept open for the run, fed a phrase per line.
- Helper programs are started with `CREATE_NO_WINDOW` (`host.QUIET`).
