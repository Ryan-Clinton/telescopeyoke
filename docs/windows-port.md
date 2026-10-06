# Running on Windows: specification

This is a work order for an agent (or a person) working on a Windows machine.
The aim is that someone with the tested gear (SynScan handset, Altair
Hypercam 183C, a webcam) can run telescopeyoke natively on Windows 10 or 11,
with no WSL and no ASCOM.

Read `AGENTS.md` first. Its safety rules and conventions apply to all of this.

## What was found

Nothing blocks a native port. Most of the project is plain Python over
astropy, numpy, scipy, Pillow, requests and pyserial, all of which ship
Windows wheels. Every Linux-specific line is listed below and each has a
Windows equivalent. One part needs new code rather than an adjustment:

- **The camera.** The INDI server and its drivers do not run on Windows, so
  `camera.py` needs a second way to get a frame. Altair publishes a camera
  SDK (`altaircamsdk_*.zip` from altairastro.help) whose listing names
  Windows x64/x86 and Python. It is the ToupTek SDK under Altair's name:
  one native library (`altaircam.dll`) and a ctypes wrapper (`altaircam.py`).

  On Windows the camera also needs Altair's device driver, which comes with
  the AltairCapture program (step 7).

None of this has been run on Windows yet. Facts marked "confirm" below come
from vendor pages and ToupTek SDK write-ups, not from opening the zip or
running the installer. SDK function names quoted below were read from
`altaircam.h` version 1.53.2, the header installed on the project's Linux
laptop; the SDK zip may be newer.

## Rules for this work

1. **Linux behaviour does not change.** The only tested hardware runs on
   Linux and cannot be re-tested from a Windows machine. Add a Windows path
   beside each Linux one; do not replace a working Linux path with a
   "portable" one, however tidy.
2. **Do not move a real mount.** Use `--demo` and `--dry-run`. A real move
   happens only when the person at the telescope asks for that move.
3. **No ASCOM, no WSL, no new framework.** Keep to the design principles in
   `AGENTS.md`. New dependencies allowed: `tzdata` (Windows only). Nothing
   else without a reason written in the pull request.
4. **Say what was proven.** The README's hardware table and "Current status"
   get a Windows row that says exactly what ran: tests only, or real gear.
5. **Vendor files are not committed.** `altaircam.py` and `altaircam.dll`
   belong to Altair. They go in `vendor/altair/`, and `vendor/` is ignored.
6. **Same contract, not the same quirks.** A Windows path has to give its
   callers what the Linux path gives them. It does not have to copy how the
   Linux path gets there: delays and retries that exist only to work round
   the INDI driver are not carried into the SDK backend.

## Where the Windows-specific code goes

Put the operating-system differences in one small module, `host.py`, with
plain functions that branch on `sys.platform == "win32"`. The Linux branch of
each is the code that exists today, moved unchanged. Callers stop caring
which system they are on.

| Function | Linux today | Windows |
|---|---|---|
| `serial_port(match)` | first `/dev/serial/by-id/*match*`, else `/dev/ttyUSB0` (`mount.py:95`, `doctor.py:78`) | `serial.tools.list_ports.comports()`; match against description, manufacturer and hwid; return `COMn` |
| `serial_access()` | `dialout` group check (`doctor.py:85`) | "does not apply": Windows has no such group. This says nothing about whether the port can be opened; a missing driver or another program holding it shows up when the port is opened |
| `camera_usb_link(match)` | `/sys/bus/usb/devices` speed and power saving (`doctor.py:152`) | a warning: speed and power saving cannot be read here, with the Device Manager advice in step 3 |
| `webcam_input()` | `-f v4l2 ... -i /dev/v4l/by-id/...` (`watch.py:22`) | `-f dshow -i video=<name>`, name from config |
| `has_webcam()` | `/dev/video*` (`doctor.py:193`) | config names one and `ffmpeg -list_devices true -f dshow -i dummy` lists that exact name (step 6) |
| `speak(words)` | `spd-say` (`focus.py:186`) | one background worker speaking phrases in order through PowerShell and `System.Speech` (step 6) |
| `play(path)` | the first of `pw-play`, `paplay`, `aplay`, `ffplay` | `winsound.PlaySound`, from the standard library |
| `replace_preview(partial, final)` | `os.replace` (`watch.py:41`, `snap.py:43`, `shoot.py:139`, `serve.py:172`) | the same, retried while the file is open elsewhere (step 1) |
| `processor_load()` | `os.getloadavg()` (`serve.py:123`) | `None`; the page leaves the row out |
| `temperature()` | `/sys/class/thermal` (`serve.py:125`) | `None` |
| `stop_program(name)` | `pkill -x` (`camera.py:99`) | not needed: only the INDI route uses it |

`stacking.cores()` already falls back when `/proc/cpuinfo` is missing; leave it.

`host.py` is for differences between the systems. A rule that holds on both,
such as which characters a folder name may contain, goes with the code that
uses it, not here.

## Work, in order

Each step ends in something that can be checked. Steps 1 to 3 need no
hardware at all.

### 1. It starts, and the tests pass

- `doctor.py:15` has `import grp` at the top of the file. `grp` does not
  exist on Windows, and `agent.py` imports `doctor`, so `ty`, `serve.py` and
  `mcp_server.py` all fail on start. Move the group check into `host.py`.
- `serve.py:123` calls `os.getloadavg()`, which Windows lacks.
- `sky.py` uses `zoneinfo`, and Windows has no time zone database. Add
  `"tzdata; sys_platform == 'win32'"` to `pyproject.toml`.
- **Text encoding.** About 70 `read_text`, `write_text` and `open` calls
  name no encoding and 19 scripts contain `°` and similar. Printing to a
  Windows console is already Unicode on every supported Python. Two things
  are not: text files opened without an encoding, and stdout when it is
  piped or redirected. Both use the Windows locale encoding (cp1252 here)
  until Python 3.15. So give every text read and write `encoding="utf-8"`,
  and make stdout and stderr UTF-8 when they are not a console, so `°`
  survives a pipe and `--json` output is always UTF-8. Do it once, in a
  place every entry point passes through, not by asking users to set
  `PYTHONUTF8`. Test it with a real redirect, in a test that runs on both
  systems: run `ty capabilities --json` as a child process with stdout
  sent to a file, then read the file back as UTF-8 and parse it.
- **Replacing a preview that is being read.** `watch.py:41`, `snap.py:43`,
  `shoot.py:139` and `serve.py:172` write a `.part` file and rename it over
  the real one so the web page never sees half a picture. On Windows the
  rename raises `PermissionError` while the web server has the old file
  open. `host.replace_preview(partial, final)` retries for about a second,
  then deletes the `.part` file, leaves the old preview in place and
  returns `False`; a missed preview must never stop an imaging run. The
  name is narrow on purpose. It is for files under `web/` that the next
  frame will replace anyway. Session records, the drift model, calibration
  masters and anything else that would be lost must never go through it: a
  failed write there is an error, as it is today.
- **Names that become folders.** `shoot.py:67`, `restack.py:56` and
  `process.py:106` build `frames/NAME/` from what the user typed with only
  the spaces removed. Windows refuses `< > : " / \ | ? *`, a trailing dot
  or space, and reserved names such as `CON`, `NUL`, `COM1` and `LPT1`. A
  comet's designation contains `/`, which goes wrong on Linux too. Add one
  function, used by all three and the same on both systems, that turns a
  target name into a folder name: refused characters become `-`, and a
  reserved name gets a `_` added. Names that are already safe (`M27`,
  `NGC7000`) must come out unchanged, so existing sessions are still found
  and a `frames/` folder copied between Linux and Windows still works.
- **Line endings.** Add a `.gitattributes` that keeps LF in the repository
  (`* text=auto eol=lf`), or a Windows checkout will put CRLF after the
  shebang in `ty` and break it on Linux. Give the two Windows-only kinds
  their own endings in the same file: `*.cmd text eol=crlf` and
  `*.ps1 text eol=crlf`.
- **Worker processes.** `stacking.worker_pool` uses "spawn", which is right
  for Windows. Confirm every script that reaches it runs under
  `if __name__ == "__main__":` (all the entry points have the guard today).

Done when: `python -m pip install ".[test]"` then `python -m pytest -q`
passes on Windows with no hardware, on the oldest and newest supported
Python (3.11 and 3.14). The suite takes about 2.5 minutes on Linux.

### 2. Launching and installing

- `./ty` relies on a shebang. Add `ty.cmd` (`@python "%~dp0ty" %*`) so
  `ty status` works from PowerShell and cmd. The `.py` scripts run as
  `python mount.py ...`. The scripts keep running from the checkout, as
  `pyproject.toml` says; do not add installed commands or package entry
  points in this work.
- Add `install.ps1`, the counterpart of `install.sh`. It checks the Python
  version and that Python is 64-bit, runs `python -m pip install .` (not
  bare `pip`, which may belong to a different Python), and copies
  `config.example.toml` to `config.toml` if absent. It says what it did on
  each of those, then lists what is left to do by hand: AltairCapture for
  the camera driver, the SDK files in `vendor/altair/`, ASTAP, the D20 star
  database, and ffmpeg. It installs nothing with administrator
  rights and changes no system setting.
- Windows may refuse to run the script ("running scripts is disabled on
  this system"). Do not change the user's execution policy. Document the
  one-off form in `docs/setup.md`:
  `powershell -ExecutionPolicy Bypass -File .\install.ps1`.
- Paths in `config.toml`. In a TOML string in double quotes `\` starts an
  escape, so `"C:\Program Files\astap"` is an error or the wrong path.
  Every Windows example in the documents and in `config.example.toml` uses
  forward slashes (`"C:/Program Files/astap"`), which Python accepts on
  Windows. Mention single quotes (`'C:\Program Files\astap'`) once as the
  other way.
- Help text and hints print `./mount.py ...`. Leave them; say once in
  `docs/setup.md` how that reads on Windows.

Done when: on a fresh Windows machine, `install.ps1` followed by
`python tonight.py --demo`, `python mount.py --demo goto M27`,
`ty capabilities --json` and `python serve.py --demo` all work, and the
status page loads from another machine on the network.

### 3. Doctor tells the truth on Windows

`doctor.py` should report, on Windows:

- The handset's COM port, or that none matched and which ports were seen.
- ASTAP and its star database, where step 5 looks for them.
- `ffmpeg`, and the focusing aid's sounds. (This step first asked for
  `ffplay` as a line of its own, for the tones. The sounds are now WAV files
  played by Windows itself through `host.play`, so `ffplay` is not needed.)
- The configured webcam, and speech.
- The camera, through whichever route `config.toml` selects. For the SDK
  route that is four lines: Python is 64-bit; `vendor/altair/altaircam.py`
  is there; `vendor/altair/altaircam.dll` is there and loads; a camera
  answers. A 32-bit DLL under 64-bit Python fails to load with "WinError
  193: not a valid Win32 application"; catch that and say to copy the DLL
  from the SDK's `win/x64` folder (confirm the folder's name in the zip).
  When no camera answers, say to install AltairCapture for the driver and
  check the camera shows in it.
- The camera's USB link. Speed and power saving cannot be read on Windows,
  so this is a warning that says what to do if frames are slow or cut off:
  in Device Manager, open the camera and the USB hub it hangs from, and on
  the Power Management tab untick "Allow the computer to turn off this
  device to save power". telescopeyoke does not change that setting itself.

No check may crash or print a Linux instruction (`usermod`, `/dev/...`) on
Windows.

Done when: `python doctor.py` and `python doctor.py --json` run clean on a
Windows machine with nothing plugged in, and each failure line says what to
do about it on Windows.

### 4. Mount

`mount.py` already speaks to the handset through pyserial at 9600 baud; only
finding the port is Linux-specific.

- Use `host.serial_port(match)`. `--port COM5` must keep overriding it.
- `[mount] serial_match` in `config.toml` matches the adapter's name. The
  tested lead is FTDI. A handset with its own USB socket shows up as a
  Prolific PL2303 port and needs Prolific's driver; document `serial_match =
  "Prolific"` for that case.
- If no port matches, refuse with `HANDSET_NOT_ANSWERING` and a message
  naming the COM ports that were seen. Do not fall back to a guessed port.

Done when: the simulator tests pass unchanged, and with a real handset
`python mount.py status` reads the position. `status` moves nothing.

### 5. Plate solver

`solve.py:26` hard-codes `astap_cli` and `/opt/astap`. ASTAP has a Windows
build, a separate command-line program, and the same D20 database.

- Add `[solver]` to config with `program` and `database`. Defaults in
  `config.py`: today's values on Linux. On Windows the program is the first
  of these that exists: what `config.toml` names; `astap_cli.exe` on `PATH`;
  `C:/Program Files/astap/astap_cli.exe`. The database defaults to the
  folder the program is in. ASTAP's documentation gives `C:\Program
  Files\astap` as the installer's folder for both the program and the D20
  database, and says the two must stay together if moved.
- The command-line program may be a separate download from the ASTAP
  installer (confirm). If only `astap.exe` is found, say that
  `astap_cli.exe` is the one needed.
- `doctor.check_star_database` looks in the same place, and when it finds
  nothing it names the folders it tried.
- The default folder has a space in it. `solve.py` passes the program and
  its arguments to `subprocess` as a list, and must keep doing so: never
  join them into one string, never `shell=True`. Add a test with the
  program and the database configured under a folder whose name has a
  space, checking each reaches the solver as one whole argument.

Done when: `python solve.py` on a saved frame gives the same position on
Windows as on Linux.

### 6. Webcam and sound

- `watch.py` builds its ffmpeg input from `host.webcam_input()`. Add
  `[webcam] device` to config for the DirectShow name. With no webcam
  configured, slews go ahead without pictures, as they do today on Linux
  when none is found.
- Listing DirectShow devices: `ffmpeg -list_devices true -f dshow -i dummy`
  prints the list on stderr and exits with an error, because `dummy` is not
  a device. Read stderr and ignore the exit code. The check is whether the
  configured name appears in that list; when it does not, show the names
  that were listed.
- `focus.py`'s click and tone are small WAV files it writes itself, played
  by `host.play`: Windows' own `winsound` there, with a newer sound cutting
  off one still playing; on Linux the first of `pw-play`, `paplay`, `aplay`
  or `ffplay`. (This step first used `ffplay` on both systems.)
- Speech goes through `host.speak`, and on Windows it must not start one
  PowerShell per phrase: each takes about a second to start, so phrases
  would overlap or come out of order, which makes focusing by ear useless.
  `host.speak(words)` puts the phrase on a queue and returns at once. One
  background worker speaks them one at a time, in order. The worker may be
  a thread that runs one PowerShell per phrase and waits for it, or one
  PowerShell kept open that reads phrases from its input; choose by what
  sounds right at the telescope. If the queue already holds a phrase when a
  new one arrives, drop the old one: the newest focus reading is the only
  one worth hearing. Only a waiting phrase is dropped; one that is being
  spoken is always finished, or rapid readings would cut every word short.
  The worker must not keep the program alive after focusing ends. On Linux
  `speak` stays the `spd-say` call it is today.
- **No console windows.** A helper program started in the background on
  Windows (PowerShell for speech, `ffmpeg` for the webcam, ASTAP) must not open a console window of its own. From a
  terminal it would not, but started from `serve.py` or `mcp_server.py`
  running without a console it can flash one up every few seconds. Start
  them with `creationflags=subprocess.CREATE_NO_WINDOW`, set in one place
  in `host.py` and passed nothing on Linux. The command the user typed
  still prints to its terminal as usual.

Done when: `python watch.py` saves a picture; `python focus.py` clicks, makes
tones and speaks; and during a focus run of twenty frames no two phrases overlap
and none is spoken out of order.

### 7. Camera through the Altair SDK

This is the only substantial new code.

**Shape.** Everything else uses the camera through one narrow interface in
`camera.py`, and that must not change:

```python
with Camera(gain=300) as cam:
    data, header = cam.frame(2.0)
```

- `data`: 2-D `uint16` raw Bayer mosaic, full sensor, no binning, values
  from 0 to `WHITE` (4095 for this 12-bit camera).
- `header`: has `EXPTIME`, `GAIN`, `DATE-OBS`, `BAYERPAT`, which
  `shoot.py`, `stacking.py` and `restack.py` read. `DATE-OBS` is the UTC
  time the exposure started, written as `2026-10-04T22:31:14.382`. The SDK
  backend reads the clock just before it triggers. Confirm the INDI driver
  means the start too, not the moment the download finished; if it does
  not, write down the difference in `docs/agents/hardware.md` and leave
  the INDI path alone.

Add `[camera] backend = "indi" | "altair"`. The default is `"indi"` on
Linux and `"altair"` on Windows. Put the SDK code in `altair.py`; `Camera`
picks one. The INDI path stays exactly as it is, and stays the default on
Linux for this piece of work even if the SDK route turns out faster there:
changing the Linux default is a separate decision, made after both have
been compared on real nights.

**Before any code: the Windows driver.** The DLL and the wrapper are not
enough on Windows. Altair's instructions say to install AltairCapture
first, because its installer puts the camera's Windows driver in place
(confirm on the Windows machine). telescopeyoke does not use AltairCapture
and this is not ASCOM: the program only supplies the driver, and gives a
way to prove the camera works before telescopeyoke is involved. The camera
should show in Device Manager without a warning mark, and AltairCapture
should show a picture from it. Then close AltairCapture, because only one
program can hold the camera.

**The files.** `vendor/altair/altaircam.py` and, beside it,
`vendor/altair/altaircam.dll` from the SDK's 64-bit Windows folder. The
wrapper is reported to load the DLL from its own folder (confirm by reading
it). 64-bit Python with the 64-bit DLL is the only supported pairing. On
Linux the wrapper goes in the same folder and loads the installed
`libaltaircam.so`.

**Which camera.** List the cameras (`Altaircam_EnumV2`). None: refuse with
`CAMERA_NOT_CONNECTED`. One: use it. Two or more: refuse and list each
one's name and serial number, unless `[camera] serial` in `config.toml`
names one of them. Never take the first of several.

**The sequence.** Use the SDK's pull mode with a callback: the SDK's own
thread collects the frame and tells the program one is ready.

```text
open     list cameras, choose one, open it
         auto exposure off
         raw mode on (ALTAIRCAM_OPTION_RAW; only settable before start)
         the sensor's full 12 bits, not the 8-bit mode
           (ALTAIRCAM_OPTION_BITDEPTH = 1), full sensor, no binning
         readout speed as configured (see "Readout speed" below)
         software trigger mode (ALTAIRCAM_OPTION_TRIGGER = 1)
         start pull mode with a callback (Altaircam_StartPullModeWithCallback)

frame    set the exposure time (microseconds) and the gain
         discard frames and "frame ready" events left from before
         note the UTC time, then trigger one exposure (Altaircam_Trigger(1))
         wait for the "frame ready" event, up to the time-out
         pull exactly one raw frame into a 16-bit buffer, with the pull
           call the SDK's own Python sample uses (Altaircam_PullImageV3 in
           1.53.2; a newer SDK may have a later one)
         shift to 0..WHITE if needed; build the header; return

close    cancel any trigger, stop, close the handle; safe to call twice
```

- **The callback must stay alive.** A ctypes callback handed to the SDK is
  only a pointer on the C side. If Python frees the callback object while
  the camera can still call it, events go missing or the program crashes.
  Keep it on the backend object from open to close.
- **The callback does almost nothing.** It runs on the SDK's thread. It
  records which event arrived and wakes the waiting `frame()`; the frame is
  pulled by the caller's thread. It also records
  `ALTAIRCAM_EVENT_DISCONNECTED`, `ALTAIRCAM_EVENT_ERROR` and
  `ALTAIRCAM_EVENT_TRIGGERFAIL`, so that `frame()` fails at once with the
  reason and does not sit out the whole time-out.
- **A late frame must never answer the next request.** If an exposure times
  out and the next one is started, the first frame may arrive late and be
  taken for the second. The "frame ready" event carries no number saying
  which trigger it answers, so the backend keeps its own count of
  exposures and knows at every moment whether it is waiting for one.
  - Before each trigger: discard waiting frames and events, add one to the
    count, and only then trigger.
  - A "frame ready" that arrives while no exposure is being waited for is
    discarded, never kept for later.
  - On a time-out: cancel the trigger (`Altaircam_Trigger(0)`), discard
    anything waiting in the camera and the library, stop waiting, and
    count the exposure as failed.
  - The frame information that comes with a pulled frame has a sequence
    number and a timestamp in 1.53.2 (`seq`, `timestamp`). If they prove
    reliable on this camera, also refuse a frame whose timestamp is
    earlier than the trigger it is supposed to answer.

  If the camera then takes the next exposure normally, carry on; if it
  fails twice running, close and reopen it once, then give up with the
  same error the INDI route gives.
- **The 12 bits and the 16-bit buffer are two different things.** The
  sensor measures 12 bits. The SDK hands each value over in a 16-bit
  number. `ALTAIRCAM_OPTION_BITDEPTH` chooses between the sensor's 8-bit
  mode and its full depth; it does not make the data 16-bit. Whether the
  12 bits sit at the bottom of the 16 (0 to 4095) or at the top (0 to
  65520) is for the SDK to say and for a real frame to confirm.
- **No windows popping up.** Nothing in this backend, and no helper process
  anywhere in the port, may open a console window of its own (step 6).

**The SDK is cross-platform, which removes most of the risk.** The same
`altaircam.py` loads `libaltaircam.so` on Linux, and that library is already
installed on the project's Linux laptop. So the backend can be written and
proven against the real camera on Linux with `backend = "altair"`, and the
INDI and SDK frames compared side by side, before it is ever run on Windows.

**Things to confirm against the SDK itself** (read `altaircam.py` and the
SDK's Python samples before writing code):

- The zip contains a Windows x64 `altaircam.dll` and `altaircam.py`, and
  the wrapper has the functions named in the sequence above. The header
  read for this document is 1.53.2; a newer SDK may have renamed some.
- That the sequence above really gives one timed raw exposure on this
  camera. The SDK's Python samples are the reference; if they do it
  differently, follow them and correct this document.
- **Discarding waiting frames.** In 1.53.2 this is `Altaircam_put_Option`
  with `ALTAIRCAM_OPTION_FLUSH` and a value that says what to discard: 1
  for frames held in the camera, 2 for frames held in the library, 3 for
  both. Confirm the values in the SDK that is actually used, and that a
  flush in software trigger mode does what the header says. Do not guess
  from the name.
- **Bit alignment.** The INDI driver delivers 0 to 4095. The SDK may deliver
  12 bits shifted up into 16. Normalise to 0 to `WHITE`, or dark and flat
  calibration and the saturation tests will be wrong.
- **Readout speed.** The SDK has speed levels from 0 to a maximum the
  camera reports (`Altaircam_get_MaxSpeed`, `Altaircam_put_Speed`). A
  faster level may shorten the time a frame takes to arrive and may add
  noise. `./camera_test.py --throughput` already times the readout speeds
  the INDI driver offers; make it do the same through the SDK backend, and
  for each level report, for a 1 s exposure: the time the shutter was
  open, the time the whole frame took, the difference, and the noise in a
  dark frame. Add `[camera] readout_speed` to config, a level number that
  only the SDK backend reads. Until the measurements exist its default is
  to leave the camera's own setting alone. The measured best level becomes
  the default only after it has been compared on the real camera, and the
  numbers go in `docs/agents/hardware.md`. Do not pick the maximum on the
  assumption that faster is better.
- **How the camera is connected.** The SDK reports the model, its own
  version, the firmware version, the camera's flags, and whether a USB 3
  camera is on a USB 2 port (`ALTAIRCAM_FLAG_USB30_OVER_USB20`). Show
  these, with the current and maximum readout speed, in `./camera_test.py
  --capabilities` when the SDK backend is in use. `doctor.py` gets one
  line from it: a warning when a USB 3 camera is on a USB 2 port, which is
  the same warning the Linux USB check gives today. The SDK also has a
  bandwidth setting on some models; record whether this camera has it,
  and do not make it a config option in this work.
- **Gain units.** `gain=300` and `gain=2000` are the INDI driver's numbers.
  The header gives the SDK's gain as a percentage ("such as 300"), and the
  INDI driver is a thin layer over the same library, so the numbers are
  expected to mean the same. Prove it: with the cap on, and again on an
  evenly lit view, take frames at gain 300 and 1500 through each backend
  and compare the median level and the noise. Add a conversion only if
  they differ.
- **Bayer pattern and orientation.** `camera.colour()` assumes RGGB with the
  INDI driver's row order. A vertical flip changes the pattern and mirrors
  the picture, which breaks colour and makes plate-solved corrections go
  the wrong way. This is a safety matter, not a cosmetic one: `goto
  --solve` turns a position measured in the picture into a movement of the
  mount. The comparison is in "Done when" below.
- **Exposure time-outs.** The INDI driver needed `TIMEOUT_FACTOR` raised on
  USB 2 and takes about 4 s plus five times the exposure to deliver a
  frame. Do not copy that into the SDK backend (rule 6). Measure how long
  the SDK takes on USB 2 and on USB 3, and set the wait from that with
  room to spare. Until it is measured, `12 + 6 * seconds` is the upper
  limit, as in `Camera.frame` now. No delay is added anywhere to imitate
  the INDI route.
- Only one program can hold the camera. Refuse with `CAMERA_NOT_CONNECTED`
  and a message saying to close the other program.

**Testing without the camera.** Add a fake SDK module to the tests that
serves made-up frames. Write one set of contract tests and run it against
both backends, the SDK backend over the fake SDK and the INDI backend over
a fake INDI server, so that nothing above `Camera` can tell them apart:

- the frame is `uint16`, two-dimensional, the full sensor size, and within
  0 to `WHITE`, including when the fake SDK serves 12 bits shifted up;
- the header has `EXPTIME`, `GAIN`, `DATE-OBS` and `BAYERPAT`; `EXPTIME`
  is the exposure asked for, to within a millisecond;
- `DATE-OBS` is the start of the exposure in UTC: with a fake camera that
  takes two seconds to deliver, `DATE-OBS` is the time of the trigger, not
  two seconds later;
- a "frame ready" that arrives when no exposure was asked for is not
  returned by the next `frame()`;
- no camera gives `CAMERA_NOT_CONNECTED`; two cameras and no `serial` gives
  a refusal that lists both;
- a time-out raises the same error from both backends;
- after a time-out, a frame that arrives late is not returned by the next
  `frame()`, and the camera still works;
- a disconnect during an exposure fails at once, not after the time-out;
- `close()` twice does no harm.

`camera_test.py` should work with both backends where its checks make sense
and decline politely where they are INDI-only.

Done when, on real hardware:

- `python snap.py` saves a correctly coloured picture; `python focus.py`
  measures a star; `python mount.py goto NAME --solve --dry-run` plans a
  move.
- With the telescope left pointing at the same star field, one frame from
  the INDI backend and one from the SDK backend (both on the Linux laptop,
  where both run) agree in: size; value range; Bayer pattern; which way is
  up and which way is left; and, after plate-solving each, the centre's
  position, the rotation, and the handedness of the picture (the sign of
  the determinant of the CD matrix that `solve.py` saves). Two frames can
  both solve and still be mirror images of each other, so the last three
  are the real test. If the SDK frame is flipped, flip it in `altair.py`
  so it matches the INDI frame, and correct the Bayer pattern to suit.
- For both backends on the same lead and port, a record in
  `docs/agents/hardware.md` of, for 1 s and 10 s exposures: the exposure
  asked for, the time from asking to having the frame, and the difference.
  This is what shows whether the slow frames on Linux come from the INDI
  route or from the camera and its lead.
- The same comparison passes between a frame taken on Windows and the INDI
  frame from Linux. The telescope will have moved, so compare only what
  does not depend on where it points: size, value range, Bayer pattern and
  handedness.

### 8. CI and documents

- Add `windows-latest` to the matrix in `.github/workflows/tests.yml`, on
  the same four Python versions as Linux (3.11 to 3.14). The Windows job
  runs `python -m pip install ".[test]"`, `python -m pytest -q`, then the
  demo commands in their Windows form: `python tonight.py --demo --top 5`,
  `python mount.py --demo zenith`, `.\ty.cmd capabilities --json` and
  `python mount.py --demo zenith --dry-run --json`. The Linux job's
  commands stay as they are.
- `serve.py` never exits, so it is not a CI step on its own. Cover it with
  a test that starts the demo server on a free port, fetches the page and
  stops it, if the suite has no such test already.
- CI has no camera. The contract tests in step 7 over the fake SDK are what
  runs there, on both systems.
- `README.md`: a Windows row in the hardware table, and a paragraph in
  "Current status". The row says which of three levels has been reached,
  and no more: tests pass in CI with no hardware; the camera has taken
  frames on Windows; mount and camera have been used together on Windows
  under the sky. Passing CI is the first level only. `docs/setup.md`: a Windows section. `docs/agents/
  hardware.md`: what was learned about the SDK.
- `AGENTS.md` describes the project as "for Linux"; change that once step 1
  is done, not before.

## Checks only the person at the telescope can do

These are not software work, and the port is not proven until they are done.

0. **Camera and mount each work on their own first.** Before running
   telescopeyoke: AltairCapture shows a picture from the camera, and Device
   Manager shows the handset's lead as a COM port (FTDI or Prolific) with
   no warning mark. Then close AltairCapture. This separates a Windows
   driver problem from a telescopeyoke fault.
1. **How the PC reaches the mount.** telescopeyoke talks to the SynScan
   *handset*. Someone who normally uses EQMod with an EQDIR lead straight
   into the mount has the handset unplugged. For telescopeyoke the handset
   goes back on, started up to its main menu with the date set, and
   connected to the PC by its own lead (USB on newer handsets, RJ12 to
   serial on older ones). The handset must not be in "PC Direct Mode".
2. **One program at a time.** Close EQMod, SharpCap, NINA and anything else
   holding the mount's COM port or the camera.
3. **Handset firmware.** The tested handset runs 3.35. Report any other
   version in a hardware report issue before trusting a GoTo.
4. **First real move.** `python mount.py goto NAME --dry-run` first, read
   what it plans, stand by the mount with a hand near the power, then run
   it. The motion limits and the `MOTION_LOCKED` file work the same on
   Windows.

## Out of scope

ASCOM and Alpaca, EQMod or direct motor-controller control, WSL, a Windows
service or installer package, other cameras or mounts.
