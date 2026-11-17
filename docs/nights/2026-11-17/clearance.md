# Clearance across the mount's range: 17 November 2026

Indoors, the mount reached through the SynScan Wi-Fi adapter on the router,
the 183M, filter wheel, guide camera and motor focuser on the tube with
their leads taped down, the person beside the mount.

## Before the tube was moved

- **Low in the south, on the meridian** (20° up, Dec -15°): the camera end
  rubbed the RA motor, and the home from there stalled. At Dec -5° the
  plate under the 183M and the leads beneath it rested on the RA motor's
  box; at Dec +5° it was still close.
- **Straight up** (`./mount.py zenith`): the tube's mirror end met a
  tripod leg, and the person switched the mount off.

The cause, found by the person: the tube sat low in its rings to balance
the camera's weight, so both ends stuck out too far. Limits were added for
both and taken out again once the tube was moved.

## After the tube was moved a few centimetres up its rings

Still close to balanced. Each move was followed by `home`; all clear of the
legs and the RA motor, and the link held throughout:

| Move | Axes reached (RA, Dec) | Home took |
|---|---|---|
| Straight up | 90.1°, 55.1° | 35 s |
| Bearing 180°, 20° up | 90.1°, 345.1° | 40 s |
| Bearing 90°, 20° up | 11.9°, 16.3° | 30 s |
| Dec +40°, 1.5 h east | 67.6°, 40.0° | 29 s |
| Dec +60°, 7.4 h east | 339.1°, 60.0° | 18 s |
| Bearing 270°, 20° up | 348.3°, 163.7° | 30 s |
| Dec +40°, 1.5 h west | 292.6°, 140.0° | 29 s |
| Dec +60°, 7.4 h west | 21.1°, 120.0° | 18 s |

Low in the north (under the pole) is beyond the 7.5 h limit and was not
tried.

## Home on the Wi-Fi adapter

The old `home` turned each axis at fixed rates, starting a motor at 2.5°/s
at once: it buzzed, crawled and twice stalled. It now uses the board's own
move, which starts slowly, with both axes at once as a GoTo does (commits
321d06e, d5e5c51). Every home above used it.

## The adapter dropping

It stopped answering three times earlier in the evening, each as a move
began; each time the tube was hitting or about to hit something (the power
strip, the RA motor, the leg), and once the motor board restarted while
stalled. With nothing in the way it never dropped.
