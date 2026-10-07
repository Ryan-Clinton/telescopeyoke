# Focusing by ear

[Back to the README](../README.md)

`./focus.py` is built for a manual focuser in the dark: one hand on the knob,
eyes on the telescope, the laptop making the sounds.

    ./focus.py                 on stars
    ./focus.py --quiet         no sound; the readings are printed and shown
    ./focus.py --scene         on rooftops or trees, in daylight

## What you hear

Every frame, once it has been measured, makes one short sound. The camera
has already started on the next frame by then.

| Sound | Meaning |
|---|---|
| A click, then a tone | That frame has been measured. Anything turned after the click is in the next reading. The tone is higher the better the focus. |
| Two clicks, no tone | Too few stars in that frame to judge it. |
| A low buzz | No star in view at all. |

The tone runs from 250 Hz to 1600 Hz in 32 semitone steps, because the ear
hears pitch by ratio. Every sound is the same loudness: loudness that changed
with the reading would be heard as a change of pitch.

Words are kept for changes of state, and each is said once:

| Words | When |
|---|---|
| "Level two." | Separate stars can be measured: three readings in a row on many stars. |
| "Level three. Fine focus." | Three readings in a row at or under twice the size good focus comes to. |
| "Minimum passed. Reverse slightly." | The size fell at least twice, then rose past the best by more than the readings' own scatter. |
| "Best focus." | Coming back after that, the size is on the best again. Stop turning. |
| "Focus good. Hold." | Level 3 only: the minimum has been passed, and the last five readings all sit on the best. |
| "Worse. Go back." | After "Focus good", the size has grown again. |
| "Stars lost. Level one." / "Star lost." | Three frames in a row with nothing to judge. |
| "Level two." / "Level one." from level 3 | Three readings in a row over three times the size of good focus. |
| "Exposure increasing." | The frames were too dark and the exposure is being doubled. |

"Focus good" is never said for a focuser that has only been held still: until
the readings have gone through their lowest and out the other side, nothing
shows that the lowest seen is the lowest there is. So turn through focus
until "Minimum passed", come back until "Best focus", and wait for "Focus
good. Hold." It does not say "perfect": the air decides how small a star gets.

## The three levels

It starts on level 1 and moves between levels by itself.

| Level | Frames | Measured | Steadied over | A change is |
|---|---|---|---|---|
| 1 coarse | binned 2x2 | many stars if there are three; otherwise the brightest star, or the one big ring a star far out of focus makes | 1 reading | 10% |
| 2 stars | binned 2x2 | the middle half-flux radius of up to 40 stars | 2 readings | 6% |
| 3 fine | the full sensor | the same, on the middle of the frame (the whole frame if the middle has fewer than 10 stars) | 3 readings | 4% |

On every level a change must also beat three times the readings' own
scatter, which is worked out from the last eleven readings so that neither a
steady turn nor a turn made a step at a time is mistaken for it.

The tone starts afresh on each level, so the ear has the whole range to work
with at every stage. On a level, the same size always gives the same pitch:

- Level 1: lowest at one and a half times the first reading, highest at a quarter of it.
- Level 2: lowest at one and a half times the first reading, highest where level 3 begins.
- Level 3: lowest at three times the size of good focus, highest at 0.8 of it.

A field with fewer than three stars still reaches level 3, on its brightest
star alone.

## The size it reports

The half-flux radius (HFR) is the radius holding half of a star's light.
Smaller is sharper. It is given in pixels of the full-size brightness picture
(two of the sensor's pixels) whatever the camera was binned by, and in
arcseconds, worked out from the pixel size and focal length in `config.toml`.
On a 150P with the 183C a pixel is 1.32" and good focus is about HFR 2, or 2.6".

The levels are set in arcseconds, so they mean the same on another telescope.
The size good focus comes to starts as 2.6". Each run that ends on "Focus
good" is kept in `cache/focus_runs.jsonl`, and from then on the figure used is
the middle one of the last five such runs.

## Why binned frames

Focusing judges brightness alone, so what binning does to the camera's colour
pattern does not matter here. `focus.py` asks the camera layer for a purpose,
not a setting: `cam.use("focus_fast")` or `cam.use("focus_fine")`. `camera.py`
(INDI) and `altair.py` (Altair's library) turn that into 2x2 binning or the
full sensor. A camera that will not bin is opened afresh on the full sensor
and not asked again; the levels then work as described on full frames.
Imaging frames are never binned, and the camera is put back on the full
sensor when focusing ends and whenever it is opened.

## Timing

Each line printed, and each line of `cache/focus_frames.jsonl` (the last run,
one frame a line), carries:

| Figure | Meaning |
|---|---|
| `capture_s` | from asking for the exposure to the frame arriving |
| `process_s` | from the frame arriving to its sound |
| `feedback_s` | the two together: the soonest a turn of the knob can be heard |
| `cycle_s` | from one sound to the next |

`./focus.py --report` gives the middle figure of each for every level of the
last run, and says whether a turn was heard within 1.2 s on the two quick
levels, which is the aim. It takes no frames.

A turn is heard in full once the level's steadying has caught up: one
reading on level 1, two on level 2, three on level 3. `--json` gives the
middle figure of each over the run, and the Focus screen shows the newest.

## The Focus screen

The application's Focus screen shows the level, the size as a very large
number, a bar that follows the tone, the best on this level, the number of
stars, the scatter, the last words said and the timing. "✓ FOCUS GOOD" appears
when the aid says so. Nothing on it is needed: the sounds carry everything.

## Sound on each system

On Linux the sounds are small WAV files played by the first of `pw-play`,
`paplay`, `aplay` or `ffplay` found; on Windows by Windows itself. Speech is
`spd-say` on Linux and PowerShell on Windows. With no player the aid says so
at the start and speaks its changes of state without the click and tone.
`./doctor.py` reports both.

## What has and has not been tried

All of this has run only on made-up star fields and the demo's pretend
camera. On a real camera, none of the following has been tried from this
code yet:

- **Binning through INDI.** `camera_test.py` timed binned frames on the USB 3
  lead (0.70 s against 1.02 s for a full frame at 0.1 s exposures). The one
  time 2x2 was asked of an already open camera, the connection to the INDI
  server broke; whether binning caused it was not found out. The camera
  layer treats that as "will not bin" and carries on with full frames.
- **Binning through Altair's library** on Windows: written from the SDK's
  documentation, including that the frame's size is the library's "final
  size" once binning is on.
- **The timings.** The first real run's `capture_s` and `process_s` will say
  whether a smaller region of the sensor is worth adding.
- **The levels' thresholds** (twice and three times the size of good focus)
  and the tone's spans. They are first figures, to be changed by what real
  runs in `cache/focus_frames.jsonl` show.
