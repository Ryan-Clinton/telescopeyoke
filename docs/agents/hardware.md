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
- **A late frame must not answer the next request.** Two guards, besides
  cancelling and flushing after a time-out. A frame that arrives sooner than
  the exposure could have finished is thrown away. And each frame carries
  the camera's own timestamp: once two good frames at least 1.5 s apart have
  shown that clock keeps time with the computer's, a frame the clock says
  was taken before the current trigger is thrown away too. If the stamps do
  not keep time they are never used. `./camera_test.py --capabilities`
  reports `frame_clock_usable`; check it reads true on the real camera,
  because until it does the second guard is doing nothing.
- **Bit alignment** is settled only by certain evidence: a value above 4095
  means the 12 bits are shifted up, a value using the bottom four bits means
  they are not. A dark frame showing neither is judged by itself and
  settles nothing. `--capabilities` reports `values_shifted_up`.
- The wait for a frame is the INDI route's `12 + 6 x exposure` seconds, as an
  upper limit, until `./camera_test.py --throughput` has measured the real
  figure at each readout speed. Record those figures here.
- `[camera] readout_speed` is left unset: the camera keeps its own setting
  until the measurements say which level is best.

## The mount without its handset (`direct.py`)

The SynScan Wi-Fi adapter and an EQDIR lead plug in where the handset would
and reach the motor board directly. The board counts motor steps and knows
nothing about the sky, so `direct.DirectHandset` answers the handset commands
`mount.py` sends and does the handset's sums itself.

Read from a real EQ3 through the Wi-Fi adapter (and nothing more: **no real
mount has been moved through this link**):

- The adapter answers on UDP port 11880. On the network it makes itself
  (`SynScan_WiFi_xxxx`, open) it is 192.168.4.1. It can also join the home
  network, and then answers a broadcast, which is how `direct.Udp.find`
  finds it.
- One message, one reply: `:e1\r` gives `=010703\r`. Numbers are six hex
  digits, low byte first. Version `010703` is model 3 (EQ3), firmware 1.07.
- 4,576,000 counts per turn on both axes, timer 35,477, high-speed ratio 16,
  35,200 counts per worm turn (130 teeth).
- Both counts read 0x800000 when the board is switched on. When first read
  they were exactly a quarter turn either side of that, with the motors
  stopped: another program (the SynScan app, most likely) had set them. So
  the counts mean nothing until home is recorded: `./mount.py sethome`.
- Status is three hex digits: the first says slewing or GoTo mode, backward,
  and high speed; the second running and blocked; the third whether the
  motors have been switched on.

Taken from the published protocol and other open software, not yet seen on
the mount: the orders (`F` switch on, `G` mode and direction, `H` counts to
turn, `M` where to slow, `I` step period, `J` go, `K` stop, `L` stop dead),
that the board refuses a change of mode while turning, and that "forward" on
the RA axis is the way the sky turns. **Which way the Dec motor turns is not
known for any mount until `./mount.py directions` has asked a person**, and
GoTo is refused until then.

What the handset did that this link does not: nothing is aligned on stars,
so pointing is as good as the home position and the polar alignment, exactly
as with the handset left unaligned; plate solving corrects it the same way.

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
