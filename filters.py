"""Filters in the light path (docs/mono-upgrade.md, items 5, 6 and 8): the
filter a step asks for, the change from one to another as one transaction,
each filter's focus offset from L, and what a filter's magnitudes are called.

Only a light path (train) with the filter wheel in it uses any of this; the
183C's has none, and nothing here is asked on it.

The filter belongs to the step's purpose, through the plan's goals
(goals.py: a programme's or planned target's [goals] filter, L when it says
nothing): discovery patrols in L against references in L, a transit in one
filter for its whole run, emission nebulae in narrowband, colour pictures as
LRGB blocks (schedule.py add --filters L:10,R:5,G:5,B:5, one step per block).

A change is one transaction, made while the camera is closed (before a
run's first frame, so no exposure is in flight): the focus offset is worked
out first (a filter with no usable offset stops the step before the wheel
turns), the wheel is moved, its position read back, the focuser moved by the
difference of the two filters' offsets (the last move inward, as every
walk-in approaches, so the gears' slack lies the same way), then a pause to
settle. Frames are labelled only with the position the wheel confirms each
time the camera opens, and only when that is the filter asked for
(shoot.in_the_path); a failed move stops the step.

The filters come in parfocal sets ([filterwheel] sets, by default
"L,R,G,B;SII,Ha,OIII", from Gary, 4 November 2026): within a set no offset,
and one offset from L's set to each other set. focus.py --walk-in
--prove-sets, once on the first clear night, walks in in every filter: a
filter further than the tolerance from its set's median gets its own offset
from then on, and the result is kept. focus.py --walk-in --offset FILTER
measures a set's offset once more: a walk-in in L, out OFFSET_BACK
half-steps, the wheel to FILTER and a walk-in there, the difference kept
with the night, the focuser's thermistor temperature and the side
approached from. An offset is used only when measured on at least NEEDED
different nights (each night's mean counted once), all approached inward,
with a spread (sample standard deviation) within the tolerance
([filterwheel] offset_tolerance, half-steps); otherwise a change between
sets needs a walk-in.
After a change, the first kept frame's star width is checked against the
last run in L: wider by more than [filterwheel] size_tolerance times means
refocus (REFOCUS_NEEDED), not carry on. Kept per camera and train, in
config.camera_folder()/cache/filter-focus-TRAIN.json.
"""
import os
import statistics
import time
from datetime import datetime

import config
import interface
import records

DEFAULT = "L"          # a step that names no filter: the most light, and the patrols' band
NEEDED = 3             # measurements of an offset, on different nights, before it is used
OFFSET_TOLERANCE = 16  # half-steps: the walk-in's finest move; provisional until steps per mm are measured
SIZE_TOLERANCE = 1.25  # a first frame this many times wider than the last in L means refocus
SETTLE_S = 2.0         # after the focuser's move, before the first exposure
OFFSET_BACK = 256      # half-steps out from L's focus before the walk-in in another filter


def settings(cfg=None):
    return (cfg or config.hardware()).get("filterwheel", {})


def wheel_in_train(cfg=None):
    """Whether the light path in use has the filter wheel in it."""
    return bool((cfg or config.hardware())["train"].get("filterwheel"))


def path(cfg=None):
    cfg = cfg or config.hardware()
    return config.camera_folder(cfg=cfg) / "cache" / f"filter-focus-{cfg['train']['name']}.json"


def load(where=None):
    import json
    try:
        store = json.loads((where or path()).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        store = {}
    store.setdefault("measurements", [])
    store.setdefault("focused_for", None)
    store.setdefault("last_l", None)
    return store


def save(store, where=None):
    records.write(where or path(), store)


# --- the filter a step asks for --------------------------------------------------

def for_target(name):
    """The filter a target's goals ask for (goals.py), L when none says."""
    import goals
    import stacking
    return goals.of(stacking.folder_name(name)).get("filter") or DEFAULT


def blocks(text):
    """"L:10,R:5,G:5,B:5" as [("L", 10), ("R", 5), ...]: an LRGB set as one
    step per filter."""
    out = []
    for part in str(text).split(","):
        name, _, count = part.strip().partition(":")
        if not name or not count.strip().isdigit() or int(count) < 1:
            raise ValueError(f"{part!r}: a block is FILTER:FRAMES, such as L:10")
        out.append((name.strip(), int(count)))
    if not out:
        raise ValueError("no blocks given")
    return out


# --- focus offsets ------------------------------------------------------------------

def keep_measurement(name, offset, temperature=None, l_hfr=None, f_hfr=None, approach="in", night=None,
                     where=None, verified=False):
    store = load(where)
    store["measurements"].append({"filter": name, "offset": int(offset), "approach": approach,
                                  "verified": bool(verified),
                                  "night": night or datetime.now().strftime("%Y-%m-%d"),
                                  "temperature_c": temperature, "l_hfr": l_hfr, "f_hfr": f_hfr,
                                  "when": time.time()})
    save(store, where)
    return store


SETS = "L,R,G,B;SII,Ha,OIII"   # the parfocal sets (Gary, 4 November 2026): each focuses together


def sets(cfg=None):
    """The parfocal sets, from [filterwheel] sets: groups split by ";",
    filters by ","."""
    text = str(settings(cfg).get("sets") or SETS)
    return [[n.strip() for n in group.split(",") if n.strip()] for group in text.split(";") if group.strip()]


def key_of(name, store=None, cfg=None):
    """What a filter's offset is kept under: its parfocal set ("set L,R,G,B"),
    or the filter itself when it is in no set or the proving night found it
    outside its set's tolerance (store["own"])."""
    store = store if store is not None else load()
    if name in (store.get("own") or []):
        return name
    for group in sets(cfg):
        if name in group:
            return "set " + ",".join(group)
    return name


def offsets(store=None, tolerance=None):
    """The offsets from L, by parfocal set (or by filter, for one on its
    own): {key: {mean, spread, count, nights, usable, why, temperatures_c}}.
    L's set is 0 by definition. Each night counts once (its measurements'
    mean), and at least NEEDED nights, all approached inward, with a spread
    within the tolerance, are needed before an offset is used."""
    store = store if store is not None else load()
    tolerance = float(settings().get("offset_tolerance", OFFSET_TOLERANCE) if tolerance is None else tolerance)
    home = key_of(DEFAULT, store)
    by = {}
    for m in store["measurements"]:
        key = key_of(m["filter"], store)
        if key != home:
            by.setdefault(key, []).append(m)
    out = {}
    for key, ms in by.items():
        nightly = {}
        for m in ms:
            nightly.setdefault(m["night"], []).append(m["offset"])
        values = [statistics.mean(v) for v in nightly.values()]
        nights = len(values)
        spread = statistics.stdev(values) if nights > 1 else None
        sides = {m.get("approach", "in") for m in ms}
        why = None
        if nights < NEEDED:
            why = f"measured on {nights} night(s): {NEEDED} different nights are needed"
        elif sides != {"in"}:
            why = "not every measurement approached focus from the same side (inward)"
        elif spread > tolerance:
            why = f"spread {spread:.0f} half-steps, more than the tolerance of {tolerance:g}"
        # A first night: one measurement the person watched and marked
        # verified may be used on a run they start themselves, never on a
        # scheduled (unattended) one, and frames say it was provisional.
        checked = [m for m in ms if m.get("verified")]
        out[key] = {"mean": round(statistics.mean(values), 1), "spread": None if spread is None else round(spread, 1),
                    "count": len(ms), "nights": nights, "usable": why is None, "why": why,
                    "provisional": None if why is None or not checked else round(checked[-1]["offset"], 1),
                    "temperatures_c": [m.get("temperature_c") for m in ms]}
    return out


def offset_of(name, store=None, tolerance=None):
    """(half-steps from L, None) for a usable offset, or (None, why). Any
    filter in L's parfocal set is 0."""
    store = store if store is not None else load()
    key = key_of(name, store)
    if key == key_of(DEFAULT, store):
        return 0.0, None
    found = offsets(store, tolerance).get(key)
    if found is None:
        return None, f"no focus offset measured for {key}"
    if found["usable"]:
        return found["mean"], None
    if found.get("provisional") is not None and not os.environ.get("TY_SCHEDULED"):
        return found["provisional"], None          # attended only: the run notes it (TY_FOCPRV)
    return None, f"{key}: {found['why']}"


def prove_sets(positions, tolerance=None, where=None, night=None, temperature=None):
    """The proving night: `positions` is each filter's best focus (half-steps,
    the same run, all approached inward). Within each parfocal set, a filter
    further than the tolerance from its set's median gets its own offset
    (store["own"]); every filter's offset from L is kept as a measurement.
    Returns {"confirmed": [sets], "own": [filters], "positions"}."""
    tolerance = float(settings().get("offset_tolerance", OFFSET_TOLERANCE) if tolerance is None else tolerance)
    if DEFAULT not in positions:
        raise interface.Refusal("INVALID_REQUEST", "The proving night needs a walk-in in L: offsets are from L.")
    store = load(where)
    own, confirmed = [], []
    for group in sets():
        here = {n: positions[n] for n in group if n in positions}
        if not here:
            continue
        middle = statistics.median(here.values())
        out = [n for n, p in here.items() if abs(p - middle) > tolerance]
        own += out
        if not out and len(here) == len(group):
            confirmed.append(",".join(group))
    store["own"] = sorted(set(store.get("own") or []) | set(own))
    night = night or datetime.now().strftime("%Y-%m-%d")
    store["proof"] = {"night": night, "positions": positions, "own": own, "confirmed": confirmed,
                      "tolerance": tolerance, "temperature_c": temperature}
    for name, at in positions.items():
        if name != DEFAULT:
            store["measurements"].append({"filter": name, "offset": int(at - positions[DEFAULT]), "approach": "in",
                                          "night": night, "temperature_c": temperature, "when": time.time(),
                                          "proving": True})
    save(store, where)
    return {"confirmed": confirmed, "own": own, "positions": positions}


def provisional(name, store=None, tolerance=None):
    """True when `name`'s focus offset in use is a single verified
    measurement (a first night), not one proved on three nights."""
    store = store if store is not None else load()
    key = key_of(name, store)
    found = offsets(store, tolerance).get(key)
    return bool(found and not found["usable"] and found.get("provisional") is not None)


def steps_between(current, wanted, store=None, tolerance=None):
    """The focuser's move from focus in `current` to focus in `wanted`, in
    half-steps; REFOCUS_NEEDED when either has no usable offset."""
    if current == wanted:
        return 0
    moves = []
    for name in (current, wanted):
        value, why = offset_of(name, store, tolerance)
        if value is None:
            raise interface.Refusal("REFOCUS_NEEDED", f"No usable focus offset for {name} ({why}): it needs its "
                                    f"own walk-in (./focus.py --walk-in with {name} in the light path), or the "
                                    f"offset measured (./focus.py --walk-in --offset {name}) on {NEEDED} nights.")
        moves.append(value)
    return int(round(moves[1] - moves[0]))


def set_focused(name, where=None):
    store = load(where)
    store["focused_for"] = {"filter": name, "when": time.time()}
    save(store, where)


def keep_last_l(fwhm, where=None):
    store = load(where)
    store["last_l"] = {"fwhm": round(float(fwhm), 3), "when": time.time()}
    save(store, where)


def size_check(fwhm, store=None, tolerance=None):
    """After a change: None when the first frame's star width is within the
    tolerance of the last run in L, else why it needs refocusing. With no run
    in L kept yet, None and nothing to compare (said by the caller)."""
    store = store if store is not None else load()
    last = (store.get("last_l") or {}).get("fwhm")
    tolerance = float(settings().get("size_tolerance", SIZE_TOLERANCE) if tolerance is None else tolerance)
    if not last or fwhm is None:
        return None
    if fwhm > tolerance * last:
        return (f"the first frame's stars are {fwhm:.1f} px wide against {last:.1f} px in the last run in L, "
                f"more than {tolerance:g} times: refocus in this filter (./focus.py --walk-in) before going on")
    return None


# --- the change, one transaction ------------------------------------------------------

def _refused(why):
    return interface.Refusal("FILTER_NOT_CONFIRMED", f"Stopped before keeping a frame: {why}.")


def change(wanted, say=print, open_wheel=None, open_focuser=None, sleep=time.sleep, where=None, backlash=None):
    """Put filter `wanted` in the light path and the focus where it belongs,
    with the camera closed. Returns {"position", "name", "from", "steps",
    "changed"}. Refuses (FILTER_NOT_CONFIRMED, REFOCUS_NEEDED) rather than
    leave the light path in a state no frame should be kept in."""
    import sxwheel
    store = load(where)
    try:
        wheel = (open_wheel or sxwheel.Wheel.open)()
    except sxwheel.WheelError as problem:
        raise _refused(str(problem)) from None
    try:
        try:
            current, total = wheel.status()
            waited = 0.0
            while not total:                  # still on its power-up turn: it ends on filter 1
                if waited > sxwheel.TIMEOUT:
                    raise sxwheel.WheelError("the wheel never said how many filters it has")
                sleep(sxwheel.POLL)
                waited += sxwheel.POLL
                current, total = wheel.status()
            number = wheel.position(wanted, total)
        except sxwheel.WheelError as problem:
            raise _refused(str(problem)) from None
        names = sxwheel.names()
        here = names[current - 1] if 0 < current <= len(names) and names[current - 1] else None
        focused = (store.get("focused_for") or {}).get("filter") or here or wanted
        steps = steps_between(focused, wanted, store)       # before anything turns
        if current != number:
            say(f"filter: turning the wheel to {sxwheel.label(number)}")
            try:
                wheel.move(wanted)
            except sxwheel.WheelError as problem:
                raise _refused(f"the wheel did not reach {wanted}: {problem}") from None
        try:
            now, _ = wheel.status()
        except sxwheel.WheelError as problem:
            raise _refused(f"the wheel did not say where it is after the move: {problem}") from None
        if now != number:
            raise _refused(f"the wheel says filter {now or 'turning'} after a move to {sxwheel.label(number)}")
    finally:
        close = getattr(wheel, "close", None)
        if close:
            close()
    if steps:
        import focus
        import focuser
        slack = focus.focuser_settings()["backlash"] if backlash is None else backlash
        say(f"filter: focus {focused} to {wanted}, {steps:+d} half-steps (offsets from L)")
        try:
            motor = (open_focuser or focuser.Focuser.open)()
        except Exception as problem:
            raise interface.Refusal("REFOCUS_NEEDED", f"The focuser could not be opened to move from {focused}'s "
                                    f"focus to {wanted}'s ({problem}): no frames kept out of focus.") from None
        try:
            if steps > 0:
                motor.move(steps + slack)     # out past it, then in: the last move inward, as a walk-in
                if slack:
                    motor.move(-slack)
            else:
                motor.move(steps)
        except Exception as problem:
            raise interface.Refusal("REFOCUS_NEEDED", f"The focuser's move to {wanted}'s focus failed "
                                    f"({problem}): refocus before going on.") from None
        finally:
            close = getattr(motor, "close", None)
            if close:
                close()
        sleep(SETTLE_S)
    if focused != wanted:
        set_focused(wanted, where)
    return {"position": number, "name": wanted, "from": focused, "steps": steps, "changed": focused != wanted}


def turn_wheel(wanted, say=print, open_wheel=None):
    """The wheel to `wanted` and read back, nothing else (no focus move):
    for the focus-offset measurement, which focuses in each filter itself.
    Its position, or FILTER_NOT_CONFIRMED."""
    import sxwheel
    try:
        with (open_wheel or sxwheel.Wheel.open)() as wheel:
            number = wheel.move(wanted)
            now, _ = wheel.status()
    except sxwheel.WheelError as problem:
        raise _refused(f"the wheel did not reach {wanted}: {problem}") from None
    if now != number:
        raise _refused(f"the wheel says filter {now or 'turning'} after a move to {wanted}")
    say(f"filter {wanted} in the light path (position {number})")
    return number


def measure_offset(name, drive, walk, wheel_to, say=print, temperature=None, back=OFFSET_BACK, where=None,
                   verified=False):
    """One measurement of filter `name`'s focus offset from L, with the
    motor (`drive`, a focus.Settled), a walk-in (`walk(drive)`, returning
    focus.walk_in's result) and `wheel_to(filter)`: L in the path, a walk-in;
    out `back` half-steps; `name` in the path, a walk-in from there; the
    difference of the two best places, both approached inward, is kept with
    the night and the temperature. The drawtube is left at `name`'s focus."""
    if key_of(name, load(where)) == key_of(DEFAULT, load(where)):
        raise interface.Refusal("INVALID_REQUEST", f"{name} is in L's parfocal set ({key_of(DEFAULT, load(where))}): "
                                "its offset is 0. Measure a filter from the other set (Ha), or prove the sets "
                                "(--prove-sets).")
    wheel_to(DEFAULT)
    began = drive.moved                       # the drive counts half-steps from where the run began
    first = walk(drive)
    at_l = began + first["best_at"]           # a walk-in counts from where it started
    say(f"offset: L best at {at_l:+d} (HFR {first['best_hfr']}); out {back} half-steps, then {name}")
    drive.move(back)
    wheel_to(name)
    began = drive.moved
    second = walk(drive)
    at_f = began + second["best_at"]
    offset = at_f - at_l
    keep_measurement(name, offset, temperature=temperature, l_hfr=first["best_hfr"], f_hfr=second["best_hfr"],
                     where=where, verified=verified)
    set_focused(name, where)
    found = offsets(load(where)).get(key_of(name, load(where)), {})
    say(f"offset: {name} is {offset:+d} half-steps from L (HFR {second['best_hfr']}); "
        f"{found.get('count')} kept, mean {found.get('mean')}, "
        + ("usable" if found.get("usable") else f"not used yet: {found.get('why')}"))
    return {"filter": name, "offset": offset, "l_best_at": at_l, "f_best_at": at_f,
            "l_hfr": first["best_hfr"], "f_hfr": second["best_hfr"], "temperature_c": temperature, **found}


def prove_all(drive, walk, wheel_to, names=None, say=print, temperature=None, back=OFFSET_BACK, where=None):
    """The proving night's run: a walk-in in each filter (L first), backing
    out `back` half-steps before each after the first, so every focus is
    approached inward; then prove_sets() on the best places. The drawtube is
    left at the last filter's focus."""
    names = names or [n for group in sets() for n in group]
    names = [DEFAULT] + [n for n in names if n != DEFAULT]
    positions = {}
    for i, name in enumerate(names):
        if i:
            drive.move(back)
        wheel_to(name)
        began = drive.moved
        found = walk(drive)
        positions[name] = began + found["best_at"]
        say(f"sets: {name} best at {positions[name]:+d} (HFR {found['best_hfr']})")
    proved = prove_sets(positions, where=where, temperature=temperature)
    set_focused(names[-1], where)
    say("sets: " + (f"confirmed {'; '.join(proved['confirmed'])}" if proved["confirmed"] else "none confirmed")
        + (f"; on their own offset: {', '.join(proved['own'])}" if proved["own"] else ""))
    return proved


# --- what a filter's magnitudes are called (item 8) ---------------------------------

def band(header, cfg=None):
    """The instrumental band a frame or stack was taken in, named for what
    took it: "L (Optolong), 183M". None for a frame with no FILTER (the
    183C's, unfiltered colour, whose own wording stays). Never Gaia G, never V."""
    name = header.get("FILTER") if header is not None else None
    if not name:
        return None
    camera = str(header.get("INSTRUME") or config.LEGACY_CAMERA)
    makers = [m.strip() for m in str(settings(cfg).get("makers", "")).split(",")]
    position = header.get("FILTPOS")
    maker = makers[int(position) - 1] if position and 0 < int(position) <= len(makers) else ""
    return f"{name}{f' ({maker})' if maker else ''}, {camera.upper()}"


def band_key(header):
    """(camera, filter) a frame or stack belongs to, for pairing and for
    filing references and zero points."""
    camera = str(header.get("INSTRUME") or config.LEGACY_CAMERA) if header is not None else config.LEGACY_CAMERA
    return camera, (header.get("FILTER") or None) if header is not None else None
