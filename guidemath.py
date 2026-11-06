"""The arithmetic a guider needs, shared by the photometric hold (shoot.py's
Hold, which moves the mount through the handset and watches the stacker's
frame shifts) and the guide camera's guider (guidecam.py, which pulses
through ST4 and watches a guide star). Each keeps its own loop; only this
is shared.

A direction's response is a "column": the vector, in pixels a second, that
a move that way gives the star or the frames. Each direction is kept on its
own (RA +, RA -, Dec +, Dec -), because whether the handset adds a variable
RA rate to tracking or replaces it is not known for this mount, and the Dec
gears' slack makes one Dec direction weaker after a reversal.
"""
import numpy as np


def drift_rate(track, last=6):
    """The drift, pixels a second, from the last few (time, x, y) rows: a
    straight line through each of x and y. Zero with fewer than 3 rows."""
    if len(track) < 3:
        return np.zeros(2)
    t = np.array([row[0] for row in track[-last:]], float)
    xy = np.array([row[1:3] for row in track[-last:]], float)
    if np.ptp(t) <= 0:
        return np.zeros(2)
    return np.array([np.polyfit(t, xy[:, k], 1)[0] for k in (0, 1)])


def slack(plus, minus, learnt_for, ratio, most):
    """The Dec gears' slack from two opposite moves of `learnt_for` seconds
    each, whose strengths (pixels a second) were `plus` and `minus`. With no
    tracking in Dec the motor moves as fast either way, so one much weaker
    than the other (by more than `ratio`) lost part of its move to slack.
    Returns (the strong direction's sign, seconds of slack, at most `most`),
    or None when the two are close enough to be no slack worth taking up."""
    strong, weak = max(plus, minus), min(plus, minus)
    if strong <= 0 or weak / strong > 1 / ratio:
        return None
    return (1 if plus >= minus else -1), min(learnt_for * (1 - weak / strong), most)


def solve(columns, want):
    """Seconds of move on RA and Dec (signed) that move by `want` pixels,
    each direction with its own column: columns[("RA", +1)] is what a
    second's move in RA's + direction does, and so on. The signs decide
    which columns apply and the columns decide the signs, so it settles in
    a few rounds. Raises numpy.linalg.LinAlgError when RA and Dec move the
    same way."""
    want = np.asarray(want, float)
    signs = (1, 1)
    for _ in range(3):
        m = np.column_stack([np.asarray(columns[("RA", signs[0])], float) * signs[0],
                             np.asarray(columns[("Dec", signs[1])], float) * signs[1]])
        seconds = np.linalg.solve(m, want)
        new = tuple(1 if s >= 0 else -1 for s in seconds)
        if new == signs:
            break
        signs = new
    return seconds
