# The live stream's picture: a spec

Status: proposed, 20 October 2026. Nothing here is built yet.

`stream.py` sends the telescope to Twitch (and later YouTube) whenever a run
is imaging. What it sends now (`./stream.py frame` makes a copy as
`cache/stream-preview.jpg`) is two pictures side by side: the stack, and the
newest frame. Under them are the target's name, "203 frames of 4 s kept" and
the clock. That is correct, but a stranger arriving on the stream can't tell
what they are looking at, why, or whether anything is happening. The newest
frame is an unstretched pink-grey mush, and the bottom third of the screen
is empty.

This spec is for a picture that looks finished, shows a little live data, and
tells a viewer in one glance what the telescope is doing and why.

## Who it is for

Someone who clicks in from Twitch or from ryanclinton.uk ([live-page.md](live-page.md)) knowing nothing.
Within five seconds they should be able to answer:

1. What is that? (the object, in plain words)
2. Why tonight? (the programme: a transit being timed, a nova patrol, a picture)
3. Is it working? (live figures that change, and when the last frame came)
4. What happens next? (the rest of tonight's schedule)

## Rules carried over (unchanged)

- Nothing names or locates the place. That means no site name, no latitude
  or longitude, no horizon picture, no cloud map, no weather and no webcam.
  Times are shown in UTC, which astronomers use anyway, so the stream does
  not even give away the time zone. Sunrise and sunset are never shown as
  clock times, because with the date they give the latitude. Only "dawn in
  2 h 10 min" is allowed.
- The stream key appears nowhere: not in the picture, the log or the tests.
- Candidates from a patrol are shown as counts only, never positions or
  cut-outs, until they have been vetted. An unvetted position on a public
  stream is a claim nobody made.
- Off unless `[stream] enabled`. It streams only while the telescope is
  working (see "Between targets" for the one change to that).

## Layout (1280 × 720, kept)

```
┌──────────────────────────────────────────────┬───────────────────────┐
│                                              │ WASP-12               │
│                                              │ a star with a hot     │
│                                              │ Jupiter in a 26 h orbit│
│          THE STACK (main picture)            │                       │
│          ~ 880 × 590                         │ TONIGHT: timing the   │
│                                              │ planet's transit      │
│                                   ┌────────┐ │                       │
│                                   │ newest │ │ [programme panel]     │
│                                   │ frame  │ │                       │
│                                   └────────┘ │ figures: frames, time,│
│                                              │ sharpness, stars      │
├──────────────────────────────────────────────┴───────────────────────┤
│ ● LIVE 02:21 UTC · last frame 3 s ago · Next: M31 P6 second look 06:25│
└──────────────────────────────────────────────────────────────────────┘
```

- **The stack is the main picture**, about 880 × 590, letterboxed on black.
  It's the thing worth looking at, and it gets better through the night.
- **The newest frame is a small inset**, about 240 × 160, in the stack's
  lower right with a thin border and the label "newest frame · 4 s". It is
  stretched the same way as the stack (black point and gamma taken from the
  frame's own background and noise), so it looks like a real frame of sky
  and not a pink sheet. It shows that the telescope is live.
- **A side panel**, 380 wide, has the object, the programme and the
  figures, in that order.
- **A footer line** shows "● LIVE", the UTC time, how long ago the last
  frame came, and the next step on tonight's schedule with its UTC start.

Colours are taken from the status page (dark blue-black background, pale
text, one accent colour) so the stream and the page look like one thing. The
font is DejaVu Sans, which is already installed and openly licensed; it
replaces PIL's default font. Text is at least 18 px, because Twitch viewers
watch at 480p on phones.

## The side panel

### The object

The name, then one line of plain words, then a second line of facts:

> **WASP-12**
> A star in Auriga with a giant planet that circles it in 26 hours
> 1,400 light years · magnitude 11.6

The words come from a hand-written table, `stream-targets.toml`, kept in the
repository. It has one entry per object the project images (M31, M33, M45,
WASP-12, …): `words`, `distance`, `magnitude`, and where useful `size`. An
object with no entry shows its name and its type from the catalogue
`tonight.py` already uses. A missing entry is never filled with made-up
facts, and the test checks every entry's fields are present and short
enough to fit.

### The programme: what is being done, and why

This panel changes with the kind of run. It is chosen from what is running:
the schedule step's label, the activity line (`activity.now()`), and which
programme made the run.

**A transit** (a planet listed by `transits.py` tonight for this star):

> **Timing the planet's transit**
> The planet passes in front of its star and dims it by 1.4 %.
> Ingress HH:MM · mid HH:MM · egress HH:MM UTC (from transits.py)
> [a small light curve: the star's brightness against time, with
>  the expected ingress/egress marked and a "now" line]

The light curve uses `transits.measure` on the session so far, run every 5
minutes in a separate process (it reads frames; it must not slow the
stream), and drawn as dots with the expected box shape behind them. Before
ingress, the panel says "Before ingress: measuring the star's steady light"
so that a flat line looks deliberate.

**A nova patrol** (patrol.py, M31 or M33):

> **Nova patrol: Andromeda's 8 panels**
> Looking for new stars against last month's pictures.
> [a small map of the panels: done ones filled, the current one outlined]
> Panel 6 of 8 · 2 candidates so far, being checked

The counts come from the status file's `discovery` sessions. A second look is
shown as "Second look at panel 8".

**A picture** (shoot.py run for an image):

> **Building a picture**
> Every frame is added to the stack; the noise falls as they add up.
> 1 h 12 min collected

### The figures

These are four small figures, each with a sparkline of the last 30 minutes
from the status `series`:

| Figure | From | Shown as |
|---|---|---|
| Frames kept | `accepted` / `captured` | "203 of 203 kept" |
| Time collected | `integration` | "13 min 32 s" |
| Sharpness | `series.fwhm` × the plate scale | "star size 6.8″" |
| Stars found | `series.stars` | "300" |

Tracking drift is left off: it means nothing to a viewer and plenty to us,
and we have the page for that.

## Between targets

At present the stream stops five minutes after the last frame and starts
again with a new run. A GoTo, a plate solve and a focus check take two to
six minutes, so a viewer sees the stream drop out between every target.

Proposed change: while the schedule runner is alive and its next step starts
within 15 minutes, the stream stays up and shows a card instead of the stack:

> **Moving to WASP-12**
> (or "Plate solving", "Checking focus": the words from `activity.now()`)
> The last picture: [the last stack, dimmed]
> Next: WASP-12 b transit, 4 s frames, from 01:50 UTC

It still stops after five minutes when nothing is running and nothing is
due, as now: at cloud, the end of the night, or the telescope put away.

## Holding the picture together

- The picture is drawn every 3 s, as now. Drawing it must take under 200 ms
  on the laptop, because the stacking needs the processors. The light curve
  and the sparklines are drawn from data already in memory; only the
  light-curve measurement reads frames, and it does so in its own process.
- Every piece degrades on its own. With no stack yet, the main picture says
  "The stack starts after the first few frames". With no series, the
  sparklines are left out. With no table entry, the object has its name
  only. Nothing is ever blank without a reason shown.
- The footer's "last frame N s ago" turns amber over 60 s and says "waiting
  for a frame (cloud?)" over 120 s, the same thresholds as the page.

## Not in this change

- Changing the Twitch or YouTube stream title or category per target. That
  needs an OAuth app on each service; it is a separate piece of work.
- Sound or music. The silent track stays, as the services need one.
- Chat or viewer interaction.
- Sending to two services at once (YouTube and Twitch). That is a separate
  change to `stream.py`'s output, not to the picture.

## Tests

- `frame()` for each kind of run (a transit, a patrol, a picture, and
  between targets) draws without error from a fixture status. The parts the
  run has are present, which is checked by drawing into a recorder rather
  than by reading pixels.
- No text drawn contains the site's name, its latitude or longitude, or the
  stream key. This test already exists for the current picture and is
  extended to every kind of run.
- Every entry in `stream-targets.toml` has its fields and fits its box.
- Drawing takes under 200 ms on a 1280 × 720 fixture (marked slow-sensitive).
- Times on the picture are UTC.
- The between-targets rule: with the schedule runner alive and the next step
  due within 15 min, `decide()` carries on and does not stop the stream.

## For review

1. Is UTC right for a public stream, or does local time read better to a
   viewer, given that it gives away the time zone?
2. Should a light curve go on a public stream before the measurement is
   checked? (A bad comparison star makes a fake dip.) A proposed rule: show
   it only once there are 30 minutes of points and the scatter is under half
   the expected depth; until then show "measuring".
3. Is 15 minutes the right gap to keep the stream up between targets?
4. Does anything in the side panel leak the place? The object list and
   times together hint at the latitude, as any astronomy stream does.
