#!/usr/bin/env python3
"""Guiding by PHD2: the guiding program almost everyone uses, on Windows or
Linux, with whatever guide camera and mount connection it already has.

PHD2 has a server for other programs (Tools > Enable Server; port 4400 for
its first instance). Over it this asks PHD2 to guide, dither, pause around a
GoTo and stop, and listens to PHD2's own record of every guide frame, so a
guided run's frames carry the same GUIDED, GUIDERMS and GUIDEMAX as with the
project's own guider. Supervisor answers shoot.py --guide exactly as
guider.Supervisor does; [guider] backend = "phd2" picks it, with
phd2_address = "HOST:PORT" (127.0.0.1:4400 unless set).

    ./phd2.py status        what PHD2 says it is doing; changes nothing

PHD2 keeps its own calibration, guide star, exposure and Dec guide mode:
this never changes them. It needs its camera and mount connected in PHD2
first. Built to PHD2's published protocol (EventMonitoring), tried against
the pretend PHD2 in simulator.py, not yet against PHD2 itself.
"""
import argparse
import collections
import itertools
import json
import math
import socket
import sys
import threading
import time

from interface import Refusal

PORT = 4400
SETTLE = {"pixels": 1.5, "time": 10, "timeout": 90}     # PHD2's own settle test, as NINA's defaults
LOST_WAIT_S = 300          # lost or stopped this long while a frame waits: guided imaging stops
CALL_S = 15.0
READOUT_S = 2.0            # a guide frame's download and pulses on top of its exposure
GAP_FACTOR = 2.0           # a gap between guide steps longer than this many cycles is time unguided


class Fault(Refusal):
    """PHD2 cannot guide as asked: guided imaging stops (a Refusal, as
    guider.Fault is, so shoot.py ends the guided run the same way)."""

    def __init__(self, message):
        super().__init__("INVALID_REQUEST", message)


class Phd2:
    """One connection to PHD2's server: calls and their answers, and every
    event PHD2 sends, kept with the time it came."""

    def __init__(self, address="127.0.0.1:4400", timeout=5.0):
        host, _, port = address.rpartition(":")
        self.address = address
        try:
            self.sock = socket.create_connection((host or "127.0.0.1", int(port or PORT)), timeout=timeout)
        except OSError as error:
            raise Refusal("INVALID_REQUEST", f"PHD2 is not answering at {address} ({error}). Start PHD2 and turn "
                          "on its server (Tools > Enable Server).") from None
        self.sock.settimeout(None)
        self.ids = itertools.count(1)
        self.answers, self.events = {}, collections.deque(maxlen=20000)
        self.changed = threading.Condition()
        self.closed = False
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        pending = b""
        try:
            while True:
                data = self.sock.recv(65536)
                if not data:
                    break
                pending += data
                while b"\n" in pending:
                    line, pending = pending.split(b"\n", 1)
                    try:
                        message = json.loads(line)
                    except ValueError:
                        continue
                    with self.changed:
                        if "jsonrpc" in message and "id" in message:
                            self.answers[message["id"]] = message
                        elif "Event" in message:
                            message["_seen"] = time.time()
                            self.events.append(message)
                        self.changed.notify_all()
        except OSError:
            pass
        with self.changed:
            self.closed = True
            self.changed.notify_all()

    def call(self, method, params=None, timeout=CALL_S):
        ident = next(self.ids)
        request = {"method": method, "id": ident}
        if params is not None:
            request["params"] = params
        self.sock.sendall((json.dumps(request) + "\r\n").encode())
        end = time.monotonic() + timeout
        with self.changed:
            while ident not in self.answers:
                left = end - time.monotonic()
                if left <= 0 or self.closed:
                    raise Fault(f"PHD2 did not answer {method}" + (" (the connection closed)" if self.closed else ""))
                self.changed.wait(left)
            answer = self.answers.pop(ident)
        if "error" in answer:
            raise Fault(f"PHD2 refused {method}: {answer['error'].get('message', answer['error'])}")
        return answer.get("result")

    def wait_event(self, names, since, timeout):
        """The first event named in `names` that came after `since`, or None."""
        end = time.monotonic() + timeout
        with self.changed:
            while True:
                for event in self.events:
                    if event["_seen"] >= since and event["Event"] in names:
                        return event
                left = end - time.monotonic()
                if left <= 0 or self.closed:
                    return None
                self.changed.wait(min(left, 1.0))

    def steps(self, start, end):
        """GuideStep and StarLost events seen between two times."""
        with self.changed:
            return [e for e in self.events
                    if e["Event"] in ("GuideStep", "StarLost") and start <= e.get("Timestamp", e["_seen"]) <= end]

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


def address():
    import config
    return str(config.hardware().get("guider", {}).get("phd2_address") or f"127.0.0.1:{PORT}")


class Supervisor:
    """guider.Supervisor's part, done by PHD2: started (or one already
    guiding used), paused around every GoTo and guiding again after, the
    Dec creep off while it guides, settled before each frame, each frame's
    guiding measured from PHD2's guide steps, dithers by PHD2. Every way it
    gives up is a Fault: a guided run never carries on unguided."""

    def __init__(self, exposure=2.0, say=print, site=None, dec_one_way=None, link=None, settle=None):
        self.say, self.site = say, site
        self.settle_rule = dict(SETTLE, **(settle or {}))
        self.link = link
        self.launched = self.active = False
        self.restarts = 0
        self.scale = None
        self.cycle = 2.0 + READOUT_S
        if dec_one_way:
            say("  guide: PHD2 keeps its own Dec guide mode; --dec-one-way is not passed to it")

    # -- the mount's Dec creep: off while PHD2 owns Dec (as guider.Supervisor)

    def creep_off(self):
        import mount
        try:
            mount.Mount(watch=False).dec_creep(0)
        except (OSError, SystemExit) as problem:
            raise Fault(f"The Dec creep could not be turned off for guiding ({problem}).") from None

    def creep_back(self):
        import mount
        try:
            scope = mount.Mount(watch=False)
            if self.site:
                scope.apply_drift_correction(self.site)
        except (OSError, SystemExit, KeyError, ValueError) as problem:
            self.say(f"  guide: the Dec creep could not be put back ({problem})")

    # -- PHD2

    def _connect(self):
        if self.link is None:
            try:
                self.link = Phd2(address())
            except Refusal as refusal:
                raise Fault(refusal.message) from None
        if not self.link.call("get_connected"):
            raise Fault("PHD2's camera and mount are not connected in PHD2: connect them there first.")
        self.scale = float(self.link.call("get_pixel_scale") or 0) or None
        # Which PHD2 equipment profile, camera and mount: with phd2_profile
        # set, any other profile is refused (a PHD2 guiding another telescope
        # would give this rig's frames its guiding).
        import config
        profile = (self._quiet_call("get_profile") or {}).get("name")
        wanted = config.hardware().get("guider", {}).get("phd2_profile")
        if wanted and profile != wanted:
            raise Fault(f"PHD2's equipment profile is {profile!r}, not {wanted!r} (phd2_profile under [guider]): "
                        "not this rig's guiding.")
        kit = self._quiet_call("get_current_equipment") or {}
        names = ", ".join(f"{part} {(kit.get(part) or {}).get('name')}" for part in ("camera", "mount")
                          if (kit.get(part) or {}).get("name"))
        self.identity = f"PHD2 (profile {profile or 'unnamed'}{'; ' + names if names else ''})"
        # The guide cycle PHD2 is set to, not one read from the gaps it leaves.
        exposure = self._quiet_call("get_exposure")
        self.cycle = (float(exposure) / 1000 if exposure else 2.0) + READOUT_S

    def _quiet_call(self, method):
        try:
            return self.link.call(method)
        except Fault:
            return None

    def _guide(self, why):
        """PHD2 guiding and settled, with its own calibration (made if it has
        none) and a star it chooses itself."""
        since = time.time()
        self.link.call("guide", {"settle": self.settle_rule, "recalibrate": False})
        done = self.link.wait_event(("SettleDone",), since, self.settle_rule["timeout"] + 300)
        if done is None:
            raise Fault(f"PHD2 did not settle {why} in time.")
        if done.get("Status", 0) != 0:
            raise Fault(f"PHD2 could not guide {why}: {done.get('Error') or 'it did not settle'}.")
        self.active = True

    def start(self):
        self._connect()
        state = self.link.call("get_app_state")
        self.creep_off()
        if state == "Guiding":
            self.say(f"  guide: PHD2 already guiding at {self.link.address}; using it")
            self.active = True
            return
        self.say(f"  guide: asking PHD2 at {self.link.address} to guide (its own calibration and star)")
        self._guide("at the start")
        self.launched = True
        self.say(f"  guide: PHD2 guiding{f', {self.scale:.2f} arcsec a guide pixel' if self.scale else ''}")

    def dither(self, size_arcsec, rng):
        """A dither by PHD2 (its own random direction), settled. Returns the
        size in the project's guide pixels (shoot.py says it in arcseconds
        through guider.SCALE) and PHD2's word."""
        import guider
        if not self.scale:
            raise Fault("PHD2 did not say its pixel scale, so a dither cannot be sized.")
        amount = size_arcsec * (0.5 + 0.5 * rng.random()) / self.scale
        since = time.time()
        self.link.call("dither", {"amount": round(amount, 2), "raOnly": False, "settle": self.settle_rule})
        done = self.link.wait_event(("SettleDone",), since, self.settle_rule["timeout"] + 60)
        if done is None or done.get("Status", 0) != 0:
            raise Fault(f"PHD2's dither did not settle: {(done or {}).get('Error') or 'no answer'}.")
        return (amount * self.scale / guider.SCALE, 0.0), f"PHD2, {amount:.1f} px, settled"

    def before_move(self):
        """PHD2 stopped, so no pulse goes while the mount slews. Before the
        guiding has started (the run's first GoTo) there is nothing to stop."""
        self.resume = self.active
        if self.active:
            self.link.call("stop_capture")
            self.active = False

    def after_move(self):
        """The creep the GoTo set off again, and PHD2 guiding on a star where
        it now is, if it was guiding before the move."""
        if getattr(self, "resume", False):
            self.resume = False
            self.creep_off()
            self._guide("after the GoTo")

    def settle(self, sleep=time.sleep):
        """True when PHD2 is guiding with its last guide steps inside its own
        settle distance; False if still guiding but not inside it after its
        settle time; a Fault when it has been lost or stopped LOST_WAIT_S."""
        begun, troubled = time.monotonic(), None
        while True:
            state = self.link.call("get_app_state")
            now = time.monotonic()
            if state != "Guiding":
                troubled = troubled or now
                if now - troubled > LOST_WAIT_S:
                    raise Fault(f"PHD2 has been {state} for {LOST_WAIT_S / 60:.0f} minutes: guided imaging stops.")
                if state in ("Stopped", "Looping") and self.restarts < 1:
                    self.recover(f"PHD2 {state.lower()}")
                    begun, troubled = time.monotonic(), None
                    continue
            else:
                troubled = None
                recent = [e for e in self.link.steps(time.time() - 3 * 60, time.time()) if e["Event"] == "GuideStep"][-3:]
                # The newest step fresh too: a stream that has stopped cannot
                # pass on steps from before it stopped.
                fresh = recent and time.time() - recent[-1].get("Timestamp", recent[-1]["_seen"]) <= GAP_FACTOR * self.cycle
                if fresh and len(recent) == 3 and all(math.hypot(e.get("RADistanceRaw", 0), e.get("DECDistanceRaw", 0))
                                                      < self.settle_rule["pixels"] for e in recent):
                    return True
                if now - begun > self.settle_rule["time"] * 3:
                    return False
            sleep(0.5)

    def recover(self, why):
        if self.restarts >= 1:
            raise Fault(f"PHD2 failed again ({why}): guided imaging stops.")
        self.restarts += 1
        self.say(f"  guide: {why}; asking PHD2 to guide again, once")
        self.creep_off()
        self._guide("after a fault")

    def during(self, start, end):
        """How guiding went from `start` to `end` (UTC seconds), in the keys
        guider.Supervisor.during gives: RMS and largest error in arcseconds
        from PHD2's raw distances, seconds without the star, coverage."""
        rows = self.link.steps(start - 1, end)
        steps = sorted((e.get("Timestamp", e["_seen"]), math.hypot(e.get("RADistanceRaw", 0), e.get("DECDistanceRaw", 0)))
                       for e in rows if e["Event"] == "GuideStep")
        rejected = sum(1 for e in rows if e["Event"] == "StarLost")
        scale = self.scale or 1.0
        errors = [d * scale for t, d in steps if t >= start]
        # Time unguided, from the steps' own times against the cycle PHD2 is
        # set to: every stretch between steps (and from the frame's start to
        # the first, and the last to its end) longer than GAP_FACTOR cycles
        # counts, less the one cycle a step would cover. Never judged from
        # the gaps themselves, which a stalled PHD2 would make long.
        cycle = self.cycle
        marks = [start] + [t for t, _ in steps if start <= t <= end] + [end]
        lost = sum((b - a) - cycle for a, b in zip(marks, marks[1:]) if b - a > GAP_FACTOR * cycle)
        covered = max(0.0, (end - start) - lost)
        state = self.link.call("get_app_state")
        ok, why = True, ""
        if state != "Guiding":
            ok, why = False, f"PHD2 was {state} at the frame's end"
        elif not errors:
            ok, why = False, "no guide step during it"
        elif rejected:
            ok, why = False, f"PHD2 lost the star {rejected} time(s) during it"
        elif lost > 0.5 * cycle:
            ok, why = False, f"{lost:.0f} s of it with no guide step"
        return {"rms": round(math.sqrt(sum(e * e for e in errors) / len(errors)), 2) if errors else None,
                "max": round(max(errors), 2) if errors else None,
                "lost_s": round(lost, 1), "rejected": rejected,
                "coverage": round(covered / (end - start), 3) if end - start >= 2 * cycle else None,
                "frames": len(steps), "guided": ok, "why": why, "by": getattr(self, "identity", "PHD2")}

    def stop(self):
        """PHD2 stopped if this run started it, and the creep put back; one
        found guiding is left guiding."""
        try:
            if self.launched and self.link:
                self.link.call("stop_capture")
        except Fault as problem:
            self.say(f"  guide: PHD2 did not take the stop ({problem})")
        finally:
            self.active = False
            if self.launched:
                self.creep_back()
            if self.link:
                self.link.close()


def status(link=None):
    """What PHD2 says: its state, whether its equipment is connected, its
    pixel scale. Reads only."""
    link = link or Phd2(address())
    try:
        return {"address": link.address, "state": link.call("get_app_state"),
                "equipment_connected": link.call("get_connected"),
                "pixel_scale": link.call("get_pixel_scale")}
    finally:
        link.close()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=["status"])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    seen = status()
    print(json.dumps(seen) if args.json else "\n".join(f"{k}: {v}" for k, v in seen.items()))


if __name__ == "__main__":
    try:
        main()
    except Refusal as refusal:
        sys.exit(refusal.message)
