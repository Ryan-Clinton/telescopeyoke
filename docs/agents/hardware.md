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
"altair"`. Run on the real Hypercam 183C on Windows 11 on 2026-10-04, on a
USB 2 lead, with SDK 60.31589.20260531 and the camera's firmware
1.4.1.20170111. Indoors, with no telescope and no lens. It has not been run
on Linux, and no star has been through it.

What was seen:

- **Windows needs nothing installed for the driver.** Plugged in, the camera
  appears as `ALTAIRH183C` (USB `16D0:0C78`) and Windows gives it its own
  WinUSB driver at once. Altair's library finds it under that driver, as
  `ALTAIRH183C(USB2.0)`. AltairCapture was never installed.
- **Altair's SDK cannot be fetched unattended.** Their site gives it only to
  a logged-in visitor, by a link that expires. `camera_setup.py` takes the
  two files from a zip the person has downloaded.
- **The frame buffer is passed as a C string pointer.** The wrapper declares
  it `c_char_p` and refuses a ctypes array ("argument 2: wrong type"); the
  array's memory is cast. The made-up wrapper in the tests refuses the same.
- **Frames are 5440 x 3648, RGGB, 12 bits at the bottom of each 16-bit
  value** (0 to 4094 seen, bottom bits in use). Nothing has to be shifted on
  this camera with this SDK. The code still checks every session.
- **The camera stamps nothing on its frames.** Sequence number, timestamp and
  exposure time in the frame information all read 0. So the guard that tells
  a late frame by the camera's clock does nothing on this camera
  (`frame_clock_usable` stays unset), and the other guards carry it:
  cancelling and flushing after a time-out, and throwing away a frame that
  comes back before its shutter could have closed.
- **Readout speed 2, the highest and the camera's own setting, is the
  quickest.** For a 1 s exposure a frame took 17.3 s at speed 0, 11.7 s at
  speed 1 and 8.7 s at speed 2. `[camera] readout_speed` is therefore left
  unset. Grain was not compared: the sensor was in room light and burnt out.
- **The slow frames are the camera on USB 2, not INDI.** Triggered one at a
  time, a 0.1 s exposure arrives in 3.5 s and a 1 s exposure in 8.7 s,
  much as through INDI on Linux (about 4 s plus five times the exposure).
- **Free-running is quicker than triggering, and is not used yet.** With the
  camera left running (`ALTAIRCAM_OPTION_TRIGGER` 0) full frames arrived
  every 1.14 s at 0.1 s exposure and every 6.35 s at 1 s. That would speed
  focusing about three times and imaging by about a quarter. It needs its
  own way of telling which exposure a frame belongs to, so it is a separate
  piece of work.

Still to do on real hardware:

- **Compare a frame with the INDI route's on the same star field:** the
  Bayer pattern reads RGGB on both, but which way up the picture is has not
  been compared. A flipped frame would send plate-solved corrections the
  wrong way, so do that before `goto --solve` is trusted with this route.
- **Gain:** that the numbers mean the same as the INDI driver's.
- **A USB 3 lead**, which the camera supports and has never had.
- **Linux**, with `backend = "altair"`.

How it works, for whoever changes it:

- The sequence is: raw mode, full bit depth, software trigger, pull mode with
  a callback; then per frame set exposure and gain, discard anything
  waiting, trigger one, wait, pull one.
- Bit alignment is settled only by certain evidence: a value above 4095 means
  the 12 bits are shifted up, a value using the bottom four bits means they
  are not. A dark frame showing neither is judged by itself.
- The wait for a frame is `12 + 6 x exposure` seconds, the INDI route's
  figure. The measurements above sit well inside it.

## Windows

- The handset's lead is found among the COM ports by its adapter's name; no
  port is ever guessed. Seen for real on Windows 11: the tested FTDI lead
  appears as "USB Serial Port (COM5)", maker FTDI, and `serial_match =
  "FTDI"` finds it among three ports. Nothing has been sent to the handset
  from Windows yet.
- The webcam is asked for 1280x720. A DirectShow camera that does not offer
  that size will give no picture; untried on a real one.
- A preview under `web/` cannot be replaced while the web server has it
  open; `host.replace_preview` retries for a second and then keeps the old
  one. Nothing else may use it.
- Speech is one PowerShell kept open for the run, fed a phrase per line.
- Helper programs are started with `CREATE_NO_WINDOW` (`host.QUIET`).
