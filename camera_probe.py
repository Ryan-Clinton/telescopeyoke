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
   temperature, and the kernel's USB messages;
2. a capture of the bus's traffic (usbmon) and of the USB controller's
   events (the xhci-hcd trace) for the whole probe;
3. whether a frame is still lost at the speed it was lost at;
4. the shortest exposure that is lost (23 October: 1 s arrived, 2 s did not);
5. smaller frames, part of the sensor, at that exposure: is it the amount
   of data or the wait?
6. the camera's video mode, frames back to back instead of one triggered
   exposure;
7. one frame waited for for five minutes: lost, or only late (21 October:
   some came about 35 s late);
8. the same exposure at speeds 1 and 0;
9. the state of step 1 again, and a last frame at the speed it was lost at.

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

PROBES = config.DATA / "cache" / "camera-probes"
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


def shot(cam, seconds, wait=None):
    """One exposure, tried once: whether it arrived, and after how long."""
    began = time.perf_counter()
    try:
        cam._expose(seconds, wait=wait)
        return {"seconds": seconds, "arrived": True, "after_s": round(time.perf_counter() - began, 1)}
    except Exception as problem:
        return {"seconds": seconds, "arrived": False, "after_s": round(time.perf_counter() - began, 1),
                "problem": str(problem)}


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
    usb = found["before"].get("usb") or {}
    bus = usb.get("port", "").split("-")[0] or None
    with recorder(folder, bus) as recording:
        found["still_lost"] = shot(cam, seconds)
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
        found["last"] = shot(cam, seconds)
        say(f"  {seconds:g} s at speed {speed} again: {words(found['last'])}")
        found["captured"] = recording.files()
    found["after"] = take()
    found["temperature_after_c"] = temperature(cam)
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
    if found.get("usb_traffic"):
        t = found["usb_traffic"]
        lines.append(f"USB: {t['asked']} asked, {t['completed']} came back, {t['still_waiting']} left waiting")
    lines.append(f"Kept in {found['folder']}")
    return "\n".join(lines)


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
