"""What the camera does while it is losing frames, looked at from every side
at once, for docs/camera-fault.md.

    ./camera_test.py --probe              run it now, at the configured readout speed
    [camera] probe_on_loss = true         run it by itself the first time a frame is lost

The fault that loses frames at readout speeds 1 and 2 comes and goes: for
days from 20 October 2026, for a quarter of an hour on 30 October, then
not once in 2,160 frames. Hours spent trying to make it happen taught
little, so when it does happen this runs straight away, in about ten
minutes, before it can clear:

1. where the camera is on USB, the USB controller's own state of each port
   (link state and errors, from debugfs), the camera's versions and
   temperature, the kernel's USB messages, and every setting the camera
   will tell (settings(): the exposure asked for and the one it says it
   used, the speed, every readable option);
2. a capture of the bus's traffic (usbmon) and of the USB controller's
   events (the xhci-hcd trace) for the whole probe;
3. whether a frame is still lost at the speed it was lost at, and if a
   frame came back too soon to be it (31 October 2026: a 16 s frame after
   10.3 s), when, and how much light it held; it is kept as early-16s.fits;
4. the shortest exposure that is lost (23 October: 1 s arrived, 2 s did not);
5. smaller frames, part of the sensor, at that exposure: is it the amount
   of data or the wait?
6. the camera's video mode, frames back to back instead of one triggered
   exposure;
7. one frame waited for for five minutes: lost, or only late (21 October:
   some came about 35 s late);
8. the same exposure at speeds 1 and 0;
9. the state of step 1 again, which settings changed, and a last frame at
   the speed it was lost at.

Nothing here changes a setting that outlasts the probe: the camera is
closed and opened again afterwards, as config.toml has it. Root is needed
for steps 1 and 2 (passwordless sudo); without it those parts are left out
and the rest still runs. The results go to cache/camera-probes/STAMP/, a
line in the camera-fault log, and the person's phone.
"""
import json
import subprocess
import time
from datetime import datetime
from pathlib import Path

import config

PROBES = config.camera_folder() / "cache" / "camera-probes"   # each camera its own
EXPOSURES = (0.5, 1.0, 1.5, 2.0, 4.0, 8.0)     # step 4, shortest first
ROIS = ((2048, 1536), (512, 512))              # step 5: width, height in the middle of the sensor
VIDEO = (0.05, 20)                             # step 6: exposure, frames
LONG_WAIT = 300.0                              # step 7: seconds


def sudo(command, run=subprocess.run):
    """A root command's output, or None when root is not to be had without
    a password."""
    try:
        done = run(["sudo", "-n", "sh", "-c", command], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout if done.returncode == 0 else None


def snapshot(run=subprocess.run):
    """Step 1 and 9: the USB controller's state of every port in use
    (xHCI PORTSC, decoded by the kernel: speed, link state U0 to U3,
    error flags), the camera's place on USB, and the kernel's USB lines
    of the last ten minutes."""
    import camera_test
    ports = sudo("for p in /sys/kernel/debug/usb/xhci/*/ports/port*; do echo \"$p $(cat $p/portsc)\"; done", run)
    kernel = None
    try:
        kernel = run(["journalctl", "-k", "--since", "-10min", "--no-pager", "-o", "short-precise"],
                     capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.TimeoutExpired):
        pass
    return {"time": datetime.now().isoformat(timespec="seconds"), "usb": camera_test.usb_state(),
            "ports": [line.split("/ports/")[-1] for line in (ports or "").splitlines() if "Speed=0" not in line]
            if ports is not None else None,
            "kernel_usb": [line for line in (kernel or "").splitlines() if "usb" in line.lower()][-30:]}


class Recorder:
    """Step 2: the bus's traffic (usbmon) and the USB controller's events
    (xhci-hcd trace events) into `folder`, for as long as it is open."""

    def __init__(self, folder, bus, run=subprocess.run, start=subprocess.Popen):
        self.folder, self.bus, self.run, self.start, self.running = Path(folder), bus, run, start, []

    def __enter__(self):
        self.folder.mkdir(parents=True, exist_ok=True)
        if self.bus is None or sudo("modprobe usbmon", self.run) is None:
            return self
        self._keep("usbmon.txt", f"/sys/kernel/debug/usb/usbmon/{self.bus}u")
        if sudo("echo > /sys/kernel/tracing/trace && echo 1 > /sys/kernel/tracing/events/xhci-hcd/enable",
                self.run) is not None:
            self._keep("xhci-trace.txt", "/sys/kernel/tracing/trace_pipe")
        time.sleep(1)
        return self

    def _keep(self, name, source):
        out = open(self.folder / name, "w", encoding="utf-8")
        self.running.append((self.start(["sudo", "-n", "cat", source], stdout=out), out, name))

    def __exit__(self, *exc):
        time.sleep(1)
        sudo("echo 0 > /sys/kernel/tracing/events/xhci-hcd/enable", self.run)
        for process, out, _ in self.running:
            process.terminate()           # sudo passes it on to cat
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
            out.close()

    def files(self):
        return [name for _, _, name in self.running]


def light(data):
    """How much light a frame holds: its mean and median, raw numbers."""
    import numpy as np
    return {"mean": round(float(np.mean(data)), 1), "median": round(float(np.median(data)), 1)}


def shot(cam, seconds, wait=None, keep=None):
    """One exposure, tried once: whether it arrived, after how long, how
    much light it held, and any frame that came back too soon to be it
    (31 October 2026: in the fault a 16 s frame came back after 10.3 s),
    with that frame's light too. With `keep`, a folder, the frame sent too
    soon is saved there as early-SECONDS.fits to be looked at."""
    began = time.perf_counter()
    try:
        data, _ = cam._expose(seconds, wait=wait)
        row = {"seconds": seconds, "arrived": True, "after_s": round(time.perf_counter() - began, 1),
               "light": light(data)}
    except Exception as problem:
        row = {"seconds": seconds, "arrived": False, "after_s": round(time.perf_counter() - began, 1),
               "problem": str(problem)}
    early = getattr(cam, "early_frame", None)
    if getattr(cam, "early", None) and early is not None:
        data = cam._normalise(early.copy())
        row["early"] = {"after_s": cam.early[0], "light": light(data)}
        if keep:
            from astropy.io import fits
            Path(keep).mkdir(parents=True, exist_ok=True)
            name = f"early-{seconds:g}s.fits"
            header = fits.Header()
            header["EXPTIME"] = (float(seconds), "seconds asked for")
            header["TY_BACK"] = (cam.early[0], "s from trigger to the frame arriving")
            fits.PrimaryHDU(data, header).writeto(Path(keep) / name, overwrite=True)
            row["early"]["file"] = name
    return row


def settings(cam):
    """Every setting the camera will tell: the named readings (the exposure
    asked for and the one it says it really used, the gain, the speed, the
    frame's size and region, the frame rate) and every option that can be
    read. Before and after the probe, and so in the fault and once it has
    cleared: what is different between the camera's two states."""
    handle, lib = cam.handle, cam.lib
    found = {}
    for name in ("get_ExpoTime", "get_RealExpoTime", "get_ExpTimeRange", "get_ExpoAGain", "get_Speed",
                 "get_HZ", "get_Mode", "get_Size", "get_FinalSize", "get_eSize", "get_Roi", "get_RawFormat",
                 "get_FrameRate", "get_Temperature", "get_AutoExpoEnable", "get_Negative"):
        try:
            value = getattr(handle, name)()
            found[name[4:]] = list(value) if isinstance(value, tuple) else value
        except Exception:
            pass
    # Writing these does something; reading them is not wanted either.
    unsafe = ("FLUSH", "FACTORY", "DEVICE_RESET", "RELOAD", "SEQUENCER_EXPOTIME", "SEQUENCER_EXPOGAIN",
              "EVENT_HARDWARE")
    for name in sorted(n for n in dir(lib) if n.startswith("ALTAIRCAM_OPTION_")):
        key = name[len("ALTAIRCAM_OPTION_"):]
        if key in unsafe or not isinstance(getattr(lib, name), int) or getattr(lib, name) >= 0x1000:
            continue
        try:
            found[f"option {key}"] = handle.get_Option(getattr(lib, name))
        except Exception:
            pass
    return found


def framed(cam, roi):
    """The camera sending only `roi` (width, height) from the middle of the
    sensor, or the whole of it again (None)."""
    handle = cam.handle
    handle.Stop()
    if roi:
        w, h = roi
        x, y = (cam.width - w) // 4 * 2, (cam.height - h) // 4 * 2
        handle.put_Roi(x, y, w, h)
        cam.width, cam.height = w, h
    else:
        handle.put_Roi(0, 0, 0, 0)
        cam.width, cam.height = cam._size()
    handle.StartPullModeWithCallback(cam._callback, cam)


def probe(cam, seconds=16.0, folder=None, say=print, take=snapshot, recorder=Recorder,
          exposures=EXPOSURES, rois=ROIS, video=VIDEO, long_wait=LONG_WAIT):
    """Steps 1 to 9 on an open altair.AltairCamera, at the speed it is set
    to now; `seconds` is the exposure that was lost. Returns what was found,
    also kept as probe.json in `folder`."""
    folder = Path(folder or PROBES / datetime.now().strftime("%Y%m%d-%H%M%S"))
    speed = cam.handle.get_Speed()
    found = {"lost_exposure_s": seconds, "speed": speed, "folder": str(folder)}
    say(f"Probing the camera while it loses frames (speed {speed}, {seconds:g} s): about ten minutes")
    found["before"] = take()
    try:
        found["camera"] = cam.details()
    except Exception as problem:
        found["camera"] = {"problem": str(problem)}
    found["temperature_c"] = temperature(cam)
    found["settings_before"] = settings(cam)
    usb = found["before"].get("usb") or {}
    bus = usb.get("port", "").split("-")[0] or None
    with recorder(folder, bus) as recording:
        found["still_lost"] = shot(cam, seconds, keep=folder)
        say(f"  {seconds:g} s at speed {speed}: {words(found['still_lost'])}")
        found["exposures"] = []
        for s in exposures:
            found["exposures"].append(shot(cam, s))
            say(f"  {s:g} s: {words(found['exposures'][-1])}")
        lost = [r["seconds"] for r in found["exposures"] if not r["arrived"]]
        test = min(lost) if lost else seconds
        found["shortest_lost_s"] = min(lost) if lost else None
        found["smaller_frames"] = []
        for roi in rois:
            try:
                framed(cam, roi)
                row = shot(cam, test)
            except Exception as problem:
                row = {"arrived": False, "problem": f"could not be set: {problem}"}
            finally:
                try:
                    framed(cam, None)
                except Exception:
                    pass
            found["smaller_frames"].append({"roi": list(roi), **row})
            say(f"  {roi[0]} x {roi[1]} pixels, {test:g} s: {words(row)}")
        exposure, count = video
        frames = 0
        try:
            for _ in cam.video(exposure, count):
                frames += 1
            found["video"] = {"asked": count, "arrived": frames}
        except Exception as problem:
            found["video"] = {"asked": count, "arrived": frames, "problem": str(problem)}
        say(f"  video, {count} frames of {exposure:g} s: {frames} arrived")
        found["long_wait"] = shot(cam, seconds, wait=long_wait)
        say(f"  {seconds:g} s, waited up to {long_wait:g} s: {words(found['long_wait'])}")
        found["speeds"] = []
        for level in sorted({1, 0} - {speed}, reverse=True):
            cam.handle.put_Speed(level)
            found["speeds"].append({"speed": level, **shot(cam, seconds)})
            say(f"  {seconds:g} s at speed {level}: {words(found['speeds'][-1])}")
        cam.handle.put_Speed(speed)
        found["last"] = shot(cam, seconds, keep=folder)
        say(f"  {seconds:g} s at speed {speed} again: {words(found['last'])}")
        found["captured"] = recording.files()
    found["after"] = take()
    found["temperature_after_c"] = temperature(cam)
    found["settings_after"] = settings(cam)
    found["settings_changed"] = {key: [found["settings_before"].get(key), value]
                                 for key, value in found["settings_after"].items()
                                 if found["settings_before"].get(key) != value}
    if "usbmon.txt" in found["captured"]:
        import camera_test
        device = device_number(usb.get("port"))
        if device is not None:
            lines = (folder / "usbmon.txt").read_text(encoding="utf-8", errors="replace").splitlines()
            found["usb_traffic"] = camera_test.usb_report(lines, device)
    found["summary"] = summary(found)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "probe.json").write_text(json.dumps(found, indent=1, default=str), encoding="utf-8")
    say(found["summary"])
    return found


def temperature(cam):
    try:
        return cam.handle.get_Temperature() / 10
    except Exception:
        return None


def device_number(port, root=Path("/sys/bus/usb/devices")):
    try:
        return int((root / port / "devnum").read_text())
    except (OSError, TypeError, ValueError):
        return None


def words(row):
    if row.get("arrived"):
        return f"arrived after {row['after_s']:g} s"
    return f"LOST ({row.get('problem', 'no frame')})"


def light_line(found):
    """The frame sent too soon against a good frame of the same exposure,
    if both were seen: about 0.63 of the light would mean the exposure
    itself was cut short (as star trails showed on 13 October 2026). Raw
    means, black level included, so it only says something with light on
    the sensor; cap on, both are the black level."""
    early = (found.get("still_lost") or {}).get("early") or (found.get("last") or {}).get("early")
    good = next((r for r in found.get("speeds", []) if r.get("arrived") and r.get("light")), None)
    if not early or not good:
        return None
    return (f"sent too soon after {early['after_s']:g} s: mean {early['light']['mean']:g}; "
            f"speed {good['speed']} kept: mean {good['light']['mean']:g}")


def summary(found):
    """A few lines a person can read on their phone."""
    speed, seconds = found["speed"], found["lost_exposure_s"]
    lines = [f"Camera probe, speed {speed}, {seconds:g} s frames:"]
    if found["still_lost"]["arrived"] and found["last"]["arrived"]:
        lines.append("the fault had already cleared when the probe began.")
    shortest = found.get("shortest_lost_s")
    kept = [r["seconds"] for r in found["exposures"] if r["arrived"]]
    lines.append(f"shortest lost {shortest:g} s, longest kept {max(kept) if kept else 'none'}" if shortest
                 else f"every exposure from {found['exposures'][0]['seconds']:g} s arrived")
    for row in found["smaller_frames"]:
        lines.append(f"{row['roi'][0]} x {row['roi'][1]}: {'kept' if row.get('arrived') else 'lost'}")
    v = found["video"]
    lines.append(f"video: {v['arrived']} of {v['asked']}")
    w = found["long_wait"]
    lines.append(f"long wait: arrived after {w['after_s']:g} s" if w["arrived"] else "long wait: never arrived")
    for row in found["speeds"]:
        lines.append(f"speed {row['speed']}: {'kept' if row['arrived'] else 'lost'}")
    lines.append(f"at the end, speed {speed}: {'kept' if found['last']['arrived'] else 'still lost'}")
    if light_line(found):
        lines.append(light_line(found))
    if found.get("settings_changed"):
        lines.append("settings changed: " + ", ".join(sorted(found["settings_changed"])))
    if found.get("usb_traffic"):
        t = found["usb_traffic"]
        lines.append(f"USB: {t['asked']} asked, {t['completed']} came back, {t['still_waiting']} left waiting")
    lines.append(f"Kept in {found['folder']}")
    return "\n".join(lines)


# --- the timed light ---------------------------------------------------------------

PULSE = 2.0          # seconds a pulse of light lasts
SETTLE = 1.0         # seconds for a light to settle before a steady frame


def short_wait(seconds):
    """How long a timed-light frame is waited for: long enough for speed
    0's 1.28 times and its readout, not the 108 s a lost 16 s frame gets."""
    return 2 * seconds + 10


def gathered(cam, seconds, wait=None):
    """The mean light of one exposure, and whether it was kept, sent too
    soon (and taken anyway, for its light), or not sent at all. A frame
    sent too soon is not waited on for long: twice the exposure and 10 s."""
    import numpy as np
    try:
        data, _ = cam._expose(seconds, wait=wait or short_wait(seconds))
        return {"mean": float(np.mean(data)), "back_s": cam.back_s, "kept": True}
    except Exception as problem:
        early = getattr(cam, "early_frame", None)
        if getattr(cam, "early", None) and early is not None:
            return {"mean": float(np.mean(cam._normalise(early.copy()))), "back_s": cam.early[0],
                    "kept": False, "sent_too_soon": True}
        return {"mean": None, "kept": False, "problem": str(problem)}


def pulsed(cam, seconds, switch, start, length, timer=None):
    """One exposure with the light on from `start` to `start + length`
    seconds after it is asked for, and off otherwise. When the light was
    really switched on and off is kept against the moment the camera was
    triggered (flash_on_s, flash_off_s), not against when the exposure was
    asked for: setting it up and emptying the pipes come between the two."""
    import threading
    timer = timer or threading.Timer
    times = {}

    def mark(lit):
        times.setdefault("on" if lit else "off", time.perf_counter())
        switch(lit)
    on, off = timer(start, mark, [True]), timer(start + length, mark, [False])
    on.start()
    off.start()
    try:
        row = gathered(cam, seconds)
    finally:
        on.cancel()
        off.cancel()
        on.join()
        off.join()
        switch(False)
    triggered = getattr(cam, "triggered", None)
    if triggered is not None:
        for edge in ("on", "off"):
            if edge in times:
                row[f"flash_{edge}_s"] = round(times[edge] - triggered, 3)
    return row


def timed_light(cam, switch, seconds=12.0, pulse=PULSE, speeds=(0, 1, 2), say=print, folder=None,
                sleep=time.sleep, timer=None, lead=1.0):
    """How long the sensor really gathers light at each readout speed,
    against a clock, not against another speed (31 October 2026: in the
    fault, speed 2 frames held 0.51 of speed 0's light, but whether speed
    0 was exactly right was not known).

    `switch(on)` turns a light the camera sees on or off: the laptop's
    screen, or a Hue light. At each speed, four exposures of `seconds`:
    dark, the light on throughout, the light on for `pulse` seconds early
    in the exposure (from `lead` s), and the same pulse late (ending `lead`
    s before the time asked). The steady frame over the early pulse, both less the
    dark, times `pulse`, is how long the sensor gathered light; the late
    pulse over the early one says whether the exposure still ran at the
    end of the time asked (1) or had already stopped (0). A frame sent too
    soon is measured too. The light's own delay in switching is the same
    on and off, so it shifts the pulse but leaves its length."""
    folder = Path(folder or PROBES / ("timed-" + datetime.now().strftime("%Y%m%d-%H%M%S")))
    was = cam.handle.get_Speed()
    found = {"seconds": seconds, "pulse_s": pulse, "folder": str(folder), "speeds": []}
    say(f"Timed light: {seconds:g} s frames, a {pulse:g} s pulse, speeds {', '.join(map(str, speeds))}")
    try:
        for level in speeds:
            cam.handle.put_Speed(level)
            switch(False)
            sleep(SETTLE)
            dark = gathered(cam, seconds)
            switch(True)
            sleep(SETTLE)
            steady = gathered(cam, seconds)
            switch(False)
            sleep(SETTLE)
            early = pulsed(cam, seconds, switch, lead, pulse, timer)
            late = pulsed(cam, seconds, switch, seconds - lead - pulse, pulse, timer)
            row = {"speed": level, "dark": dark, "steady": steady, "early_pulse": early, "late_pulse": late,
                   "settings": timing_settings(cam)}
            means = [f["mean"] for f in (dark, steady, early, late)]
            if None not in means and means[2] - means[0] > 0:
                row["gathered_s"] = round(pulse * (means[1] - means[0]) / (means[2] - means[0]), 2)
                row["share_of_asked"] = round(row["gathered_s"] / seconds, 3)
                row["late_pulse_share"] = round((means[3] - means[0]) / (means[2] - means[0]), 2)
            found["speeds"].append(row)
            say("  " + timed_words(row))
    finally:
        switch(False)
        cam.handle.put_Speed(was)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "timed-light.json").write_text(json.dumps(found, indent=1, default=str), encoding="utf-8")
    found["summary"] = "\n".join([f"Timed light, {seconds:g} s asked:"] + [timed_words(r) for r in found["speeds"]]
                                 + [f"Kept in {folder}"])
    return found


TIMING_SETTINGS = ("ExpoTime", "RealExpoTime", "ExpTimeRange", "Speed", "HZ", "FrameRate", "option TRIGGER",
                   "option PRECISE_FRAMERATE", "option MAX_PRECISE_FRAMERATE", "option BANDWIDTH")


def timing_settings(cam):
    """The camera's settings that bear on timing, kept beside each measurement."""
    found = settings(cam)
    return {key: found[key] for key in TIMING_SETTINGS if key in found}


def scan(cam, switch, seconds=8.0, pulse=1.0, step=1.0, speeds=(0, 1, 2), say=print, folder=None,
         sleep=time.sleep, timer=None):
    """Where each exposure really starts and ends: one frame for each
    place of a `pulse` s flash, moved through the exposure and past its
    end (to 1.5 times the time asked) by `step` s, at each speed. The share
    of the brightest flash each frame caught marks the window the sensor
    gathered in: its start and end in seconds after the camera was
    triggered (each flash timed from the trigger itself, 1 November 2026;
    the scan of 31 October timed them from the request, a few tenths of a
    second earlier). A fixed scaling and a moved window shorten an exposure the same
    way; this tells them apart."""
    folder = Path(folder or PROBES / ("scan-" + datetime.now().strftime("%Y%m%d-%H%M%S")))
    was = cam.handle.get_Speed()
    found = {"seconds": seconds, "pulse_s": pulse, "step_s": step, "folder": str(folder), "speeds": []}
    say(f"Scan: {seconds:g} s frames, a {pulse:g} s flash moved by {step:g} s, "
        f"speeds {', '.join(map(str, speeds))}")
    try:
        for level in speeds:
            cam.handle.put_Speed(level)
            switch(False)
            sleep(SETTLE)
            dark = gathered(cam, seconds)
            places, offset = [], 0.0
            while offset < 1.5 * seconds:
                frame = pulsed(cam, seconds, switch, offset, pulse, timer)
                # Where the flash really fell, from the trigger, when it is known.
                places.append({"at_s": frame.get("flash_on_s", round(offset, 2)),
                               "lasted_s": round(frame["flash_off_s"] - frame["flash_on_s"], 3)
                               if "flash_off_s" in frame and "flash_on_s" in frame else pulse, **frame})
                offset += step
            row = {"speed": level, "dark": dark, "flashes": places, "settings": timing_settings(cam)}
            row.update(window(dark, places, pulse))
            found["speeds"].append(row)
            say("  " + scan_words(row))
    finally:
        switch(False)
        cam.handle.put_Speed(was)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "scan.json").write_text(json.dumps(found, indent=1, default=str), encoding="utf-8")
    found["summary"] = "\n".join([f"Scan, {seconds:g} s asked:"] + [scan_words(r) for r in found["speeds"]]
                                 + [f"Kept in {folder}"])
    return found


def window(dark, places, pulse):
    """The gathering window from a scan's frames. Each flash counts by the
    share of the brightest flash's light its frame holds; the window runs
    from the first flash's start to the last one's end, each trimmed by
    the part of it the frame missed."""
    if dark.get("mean") is None:
        return {}
    seen = [(p["at_s"], p["mean"] - dark["mean"]) for p in places if p.get("mean") is not None]
    full = max((light for _, light in seen), default=0)
    if full <= 0:
        return {}
    shares = [(at, max(0.0, min(1.0, light / full))) for at, light in seen]
    caught = [(at, share) for at, share in shares if share >= 0.1]
    if not caught:
        return {}
    lasted = {p["at_s"]: p.get("lasted_s", pulse) for p in places}
    (first, first_share), (last, last_share) = caught[0], caught[-1]
    start = first + lasted.get(first, pulse) * (1 - first_share)
    end = last + lasted.get(last, pulse) * last_share
    return {"starts_s": round(start, 2), "ends_s": round(end, 2), "gathers_s": round(end - start, 2),
            "shares": [[at, round(share, 2)] for at, share in shares]}


def scan_words(row):
    if "gathers_s" not in row:
        return f"speed {row['speed']}: no window found (frames lost, or no flash seen)"
    return (f"speed {row['speed']}: gathers from {row['starts_s']:g} s to {row['ends_s']:g} s after the "
            f"trigger, {row['gathers_s']:g} s")


def order_test(cam, seconds=16.0, speed=2, say=print):
    """Whether the order the camera is told things in decides its timing
    state (31 October 2026: in the fault speed 2 times its exposures as if
    by speed 0's clock, half as long; when healthy, a 16 s frame at speed 2
    comes back after 20.5 s, in the fault after 10.3 s). No light needed:
    when each frame comes back tells the state. Four ways of setting the
    same `speed` and exposure:
      usual           the speed, then the time (as every frame is taken)
      time first      the time, then the speed, the time not set again
      stream stopped  the speed set with the camera's stream stopped and
                      started again, as when it is opened
      via speed 0     speed 0 and then `speed`, then the time"""
    handle, found = cam.handle, {"seconds": seconds, "speed": speed, "ways": []}
    was = handle.get_Speed()
    say(f"Order test: {seconds:g} s frames at speed {speed}")

    def usual():
        handle.put_Speed(speed)
        return gathered(cam, seconds)

    def time_first():
        handle.put_Speed(0)
        handle.put_ExpoTime(max(1, round(seconds * 1e6)))
        handle.put_Speed(speed)
        try:
            data, _ = cam._expose(seconds, wait=short_wait(seconds), set_time=False)
            return {"back_s": cam.back_s, "kept": True}
        except Exception as problem:
            return {"back_s": cam.early[0] if getattr(cam, "early", None) else None, "kept": False,
                    "problem": str(problem)}

    def stream_stopped():
        handle.Stop()
        handle.put_Speed(speed)
        handle.StartPullModeWithCallback(cam._callback, cam)
        return gathered(cam, seconds)

    def via_speed_0():
        handle.put_Speed(0)
        handle.put_Speed(speed)
        return gathered(cam, seconds)
    try:
        for name, way in (("usual", usual), ("time first", time_first), ("stream stopped", stream_stopped),
                          ("via speed 0", via_speed_0), ("usual again", usual)):
            row = {"way": name, **{k: v for k, v in way().items() if k in ("back_s", "kept", "problem")}}
            back = row.get("back_s")
            row["state"] = (None if back is None else "short (the fault)" if back < 0.9 * seconds
                            else "full")
            found["ways"].append(row)
            say(f"  {name}: back after {back if back is not None else '?'} s, {row['state'] or 'nothing came'}")
    finally:
        handle.put_Speed(was)
    found["summary"] = "\n".join([f"Order test, {seconds:g} s at speed {speed}:"] +
                                  [f"{r['way']}: {r['state'] or 'nothing came'}" for r in found["ways"]])
    return found


def timed_words(row):
    if "gathered_s" not in row:
        return f"speed {row['speed']}: not measured (a frame lost, or no light from the pulse)"
    soon = " (sent too soon)" if row["steady"].get("sent_too_soon") else ""
    end = ("still gathering at the end" if row["late_pulse_share"] > 0.7 else
           "stopped before the end" if row["late_pulse_share"] < 0.3 else "partly gathering at the end")
    return (f"speed {row['speed']}: gathered for {row['gathered_s']:g} s, {row['share_of_asked']:.0%} of the "
            f"time asked{soon}; {end} (late pulse {row['late_pulse_share']:g} of the early one)")


class Screen:
    """The laptop's screen as the light: a window over the whole screen,
    black or white on a line sent to it, redrawn within a frame (about
    1/60 s); kept from dimming while it is up."""

    def __init__(self, start=subprocess.Popen, sleep=time.sleep):
        import shutil
        import sys
        command = [sys.executable, str(Path(__file__).resolve()), "screen"]
        if shutil.which("gnome-session-inhibit"):
            command = ["gnome-session-inhibit", "--inhibit", "idle", "--reason", "camera timed light"] + command
        self.process = start(command, stdin=subprocess.PIPE, text=True)
        sleep(3)                  # the window is up and full screen

    def __call__(self, on):
        self.process.stdin.write("on\n" if on else "off\n")
        self.process.stdin.flush()

    def close(self):
        try:
            self.process.stdin.write("quit\n")
            self.process.stdin.close()
        except OSError:
            pass
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()


class HueLight:
    """A Hue light as the light, switched with no fade; put back as it was."""

    def __init__(self, name):
        import alert
        s = alert.settings()
        self.bridge = alert.Bridge(s.get("hue_address"), s.get("hue_key"))
        self.light = alert.find_light(self.bridge, name)
        self.before = alert.state_of(self.light)

    def __call__(self, on):
        body = {"on": {"on": on}, "dynamics": {"duration": 0}}
        if on:
            body["dimming"] = {"brightness": 100.0}
        self.bridge.put(self.light["id"], body)

    def close(self):
        self.bridge.put(self.light["id"], self.before)


def show_screen():
    """The window Screen drives: full screen, black until told "on"."""
    import os
    import sys
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import GLib, Gtk
    lit = [False]
    window, area = Gtk.Window(title="camera timed light"), Gtk.DrawingArea()
    window.add(area)

    def draw(_, cr):
        cr.set_source_rgb(*((1, 1, 1) if lit[0] else (0, 0, 0)))
        cr.paint()
    area.connect("draw", draw)

    def read(*_):
        line = sys.stdin.readline()
        if line.strip() in ("", "quit"):
            # Gtk.main_quit() left the process alive once the window had been
            # shown (31 October 2026, Wayland), so it ends here outright.
            os._exit(0)
        lit[0] = line.strip() == "on"
        area.queue_draw()
        return True
    GLib.io_add_watch(GLib.IOChannel.unix_new(sys.stdin.fileno()), GLib.PRIORITY_HIGH,
                      GLib.IOCondition.IN | GLib.IOCondition.HUP, read)
    window.fullscreen()
    window.show_all()
    Gtk.main()


def after_loss(cam, seconds, problem, say=print):
    """Called by altair.py the first time a frame is lost while [camera]
    probe_on_loss is set: the probe, a line in the fault log, the person
    told, and the camera put back as config.toml has it."""
    import camera_test
    import notify
    say(f"camera: a {seconds:g} s frame was lost ({problem}); probing it before it clears")
    try:
        found = probe(cam, seconds, say=say)
    finally:
        cam.close()
        cam._open()
    camera_test.keep_fault({"probe": found["folder"], "speed": found["speed"], "exposure_s": seconds,
                            "summary": found["summary"]}, note="probe after a lost frame")
    notify.send(found["summary"], say=say)
    return found


if __name__ == "__main__":
    import sys
    if sys.argv[1:] == ["screen"]:
        show_screen()
