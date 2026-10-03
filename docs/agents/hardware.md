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
