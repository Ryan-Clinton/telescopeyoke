"""Did the telescope really turn? What the mount says is not proof.

On 6 October 2026 the motors stopped being driven, with no sound, while the
handset went on reporting every GoTo as made. A survey looked at one lit
tree for half an hour and gave a different bearing for it each time. The
person standing beside it knew before the software did.

So anything that makes many moves unattended also looks at what the camera
sees: after a turn of more than a frame's width, the picture must not be the
one before.

    watch = moved.Watch()
    watch.check(lum, turned_deg, "bearing 120°, 40° up")    # after each move

Two pictures running that match, after turns that should have changed them,
is a refusal (MOUNT_NOT_MOVING), and the caller stops the mount. Where a
plate solve already says where the telescope is, that is the better proof,
and `unchanged()` judges it.

The thresholds here are first figures. They have been tried on made-up star
fields and textures, not yet on frames from the night it happened.
"""
import json
import math
import time

import numpy as np
from scipy import ndimage

import config
import interface

MOVED_FILE = config.DATA / "cache" / "mount_moved.json"    # when the camera last showed a move was real
LEAST = 0.5         # degrees: a smaller turn may leave the same things in view, and is not judged
STARS = 5           # stars a picture needs before its stars are gone by
MATCH = 4.0         # pixels within which a star is the same star
SHARE = 0.6         # of the stars before that must still be in place for "the same view"
SURE = 12.0         # how far the best fit of two textures must stand above the rest, in their spread
PATIENCE = 2        # matching pictures in a row before the mount is called stuck


def separation(az1, alt1, az2, alt2):
    """Degrees between two directions given as bearing and height."""
    a1, h1, a2, h2 = (math.radians(v) for v in (az1, alt1, az2, alt2))
    cosine = math.sin(h1) * math.sin(h2) + math.cos(h1) * math.cos(h2) * math.cos(a1 - a2)
    return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))


def _stars(lum):
    """(x, y) of the stars in a brightness picture. A median filter first:
    a hot pixel is in the same place in every frame and would pass for a
    star that never moves."""
    import stacking
    found = stacking.find_stars(ndimage.median_filter(lum.astype(np.float32), 3), limit=60)
    return found[:, :2]


def _texture(before, after):
    """(shift in pixels, how sure) between two pictures of something with
    detail in it: a tree, a wall, a roof. Both first lose their hot pixels,
    are averaged in 4x4 blocks and are stripped of their broad shading, so
    that what the sensor adds to every frame cannot make two different views
    look alike."""
    def coarse(image):
        rows, cols = image.shape[0] // 4 * 4, image.shape[1] // 4 * 4
        clean = ndimage.median_filter(image[:rows, :cols].astype(np.float32), 3)      # hot pixels out first
        small = clean.astype(np.float64).reshape(rows // 4, 4, cols // 4, 4).mean(axis=(1, 3))
        small -= ndimage.uniform_filter(small, 16)
        side = min(256, small.shape[0] // 2 * 2, small.shape[1] // 2 * 2)
        y0, x0 = (small.shape[0] - side) // 2, (small.shape[1] - side) // 2
        return small[y0:y0 + side, x0:x0 + side] * np.outer(np.hanning(side), np.hanning(side))
    a, b = np.fft.fft2(coarse(before)), np.fft.fft2(coarse(after))
    cross = b * np.conj(a)
    match = np.abs(np.fft.ifft2(cross / np.maximum(np.abs(cross), 1e-12)))
    y, x = np.unravel_index(np.argmax(match), match.shape)
    side = match.shape[0]
    dy, dx = (y - side if y > side // 2 else y), (x - side if x > side // 2 else x)
    return 4 * math.hypot(dx, dy), float((match[y, x] - match.mean()) / (match.std() + 1e-12))


def compare(before, after):
    """"same" if two brightness pictures show the same view, "changed" if
    they show different ones, None if neither has anything to go by (blank
    sky by day, cloud by night)."""
    if before.shape != after.shape:
        return None
    a, b = _stars(before), _stars(after)
    if len(a) >= STARS:
        if not len(b):
            return "changed"
        nearest = np.sqrt(((a[:, None, :] - b[None, :, :]) ** 2).sum(axis=2)).min(axis=1)
        return "same" if (nearest <= MATCH).mean() >= SHARE else "changed"
    if len(b) >= STARS:
        return "changed"
    shift, sure = _texture(before, after)
    if sure >= SURE:
        return "same" if shift <= 2 * MATCH else "changed"
    return None


def confirm(how):
    """Note that the camera has just shown a move to be real."""
    MOVED_FILE.parent.mkdir(parents=True, exist_ok=True)
    MOVED_FILE.write_text(json.dumps({"how": how, "saved": time.time()}), encoding="utf-8")


def refusal(what):
    return interface.Refusal(
        "MOUNT_NOT_MOVING",
        f"{what} The mount reports each move as made, but the telescope does not seem to be turning. "
        "Stopped. Watch one small move: does the tube turn, and does the motor sound? If not, check the "
        "mount's power and leads, switch it off and on, take the handset to its main menu and set the "
        "tube to home by hand.")


class Watch:
    """Holds the last picture and judges each new one against it."""

    def __init__(self, patience=PATIENCE):
        self.patience, self.before, self.stuck, self.verdicts = patience, None, 0, []

    def check(self, lum, turned_deg, where=""):
        """Call with the picture taken after a move of `turned_deg` since
        the last one. Returns the verdict; raises when the mount is stuck.
        The demo's sky does not turn with its mount, so nothing is judged there."""
        before, self.before = self.before, lum
        if before is None or turned_deg < LEAST or config.DEMO:
            return None
        verdict = compare(before, lum)
        self.verdicts.append(verdict)
        if verdict == "changed":
            self.stuck = 0
            confirm("the view changed after a move")
        elif verdict == "same":
            self.stuck += 1
            if self.stuck >= self.patience:
                raise refusal(f"The last {self.stuck + 1} pictures show the same view{' (' + where + ')' if where else ''}, "
                              f"though the mount was turned {turned_deg:.1f}° before this one.")
        return verdict


def unchanged(miss_before, miss_after, least=0.25):
    """True when a correction that should have taken out `miss_before` (hour
    angle, Dec, in degrees) left the miss as it was: a plate solve's proof
    that the telescope did not turn. A miss under `least` degrees is not
    judged; a turn that small can be lost in the gears' slack."""
    size = math.hypot(*miss_before)
    if size < least:
        return False
    return math.hypot(miss_after[0] - miss_before[0], miss_after[1] - miss_before[1]) < 0.25 * size
