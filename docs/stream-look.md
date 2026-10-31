# The live stream's picture: the design record

> **Design record.** For the stream as built and how to run it, see
> [streaming.md](streaming.md). Some sections below describe the design as it
> stood before it was built; where the two differ, streaming.md is the
> present.

Why the stream looks as it does, as specified and reviewed.

Status: built and on air on 20 October 2026, from 01:43 UTC on the WASP-12 b
transit. `streamlook.py` draws the picture, `stream-targets.toml` holds the words
about each object, and `stream.py` sends it; `./stream.py preview` draws each
state at full size and at a phone's size, on the night's real pictures where
there are some, with `cache/stream-preview/index.html` showing them all
together. The presenter (`streamstory.py`, "The story") and the chat's
commands (`streamchat.py`) were added the same night. Not built yet: the
target introduction, the tonight ribbon outside the between-targets card, the
reference/tonight view, the variable-star curve, and a catalogue's reason in a
candidate's result.

`stream.py` sends the telescope to Twitch (and later YouTube) whenever a run
is imaging. What it sends now (`./stream.py frame` saves a copy as
`cache/stream-preview.jpg`) is two pictures side by side: the stack and the
newest frame, with the target's name, "203 frames of 4 s kept" and the clock
underneath. That is correct, but a stranger arriving on the stream can't tell
what they are looking at, why, or whether anything is happening. The newest
frame is an unstretched pink-grey mush, and the bottom third of the screen
is empty.

## The direction, in one paragraph

> The stream should look like a quiet live science documentary, not a
> computer dashboard. The sky is always the hero. The graphics are dark,
> restrained, spacious and informative, and motion is slow and purposeful.
> A viewer who knows nothing about astronomy should understand within five
> seconds what they are seeing, why the telescope is looking at it, whether
> the observations are progressing, and what happens next.

Every choice below follows from that paragraph. Where an implementation
choice is not covered here, decide it by the same rule.

## Who it is for

Someone who clicks in from Twitch or from ryanclinton.uk
([live-page.md](live-page.md)) knowing nothing. Within five seconds they
should be able to answer:

1. What is that? (the object, in plain words)
2. Why tonight? (the programme: a transit being timed, a nova patrol, a picture)
3. Is it working? (live figures that change, and when the last exposure came)
4. What happens next? (the rest of tonight)

## Rules carried over (unchanged)

- **Nothing names or locates the place.** That means no site name, no
  latitude or longitude, no horizon picture, no cloud map, no weather and no
  webcam. All times are UTC and labelled "UTC", which astronomers use anyway
  and which does not give away the time zone. Sunrise and sunset are never
  shown as clock times, because with the date they give the latitude. Only
  "dawn in 2 h 10 min" is allowed.
- **The stream key appears nowhere**: not in the picture, the log or the tests.
- **No candidate position is ever shown**: no coordinates, no cut-out and no
  marker on the picture, until it has been vetted and reported. An unvetted
  position on a public stream is a claim nobody made.
- **Off unless `[stream] enabled`.** It streams only while the telescope is
  working, with the two additions under "Between targets" and "End of
  night".
- **Every word on screen comes from data or curated text.** Target
  descriptions and science captions are hand-written in the repository.
  Nothing is generated live, and nothing is guessed: a cause such as cloud is
  only named when the project has measured it.

## The video itself

| | Now | Proposed |
|---|---|---|
| Size | 1280 × 720 | **1920 × 1080** |
| Frames sent | 5 a second | **30 a second** |
| Bitrate | 2.5 Mbit/s | **5 Mbit/s** (Twitch suggests 4.5 for 1080p30; YouTube about 5 or more) |
| Keyframe | every 2 s | every 2 s (both services ask for 2 s) |
| Encoder | VAAPI on the Radeon (`renderD129`), else libx264 | the same |

Faint stars, galaxy structure, small text and a light curve are exactly
what compression smears at 720p and 2.5 Mbit/s.

The picture is still composed only when something changes: every 3 s, plus
the in-between frames of a fade. It goes to ffmpeg at **10 pictures a
second**, and ffmpeg's `fps=30` filter repeats each one up to 30. A raw
1080p picture is 6.2 MB, so 30 a second through the pipe would be 187 MB/s
for nothing; at 10 a second it is 62 MB/s. Composing must take under 200 ms,
and a fade's frames are made from two finished pictures by blending, not by
drawing again.

**Bandwidth.** The home upload has not been measured, so the size is chosen
once, at the start, by a test against the real ingest. On Twitch,
`bandwidth_test()` sends 20 s of 1080p to the stream key with
`?bandwidthtest=true`, which Twitch takes without showing it to anyone. If
that kept up (speed 0.95 or more, no more than a second's frames dropped),
the stream starts at 1080p; otherwise it starts at 1280 × 720, 30 fps and
3 Mbit/s. YouTube has no such test, so it starts at 1080p.

After that the size changes only on **sustained** failure, because
restarting ffmpeg at a new size interrupts the viewers. `stream.py` reads
ffmpeg's own progress reports (`-progress cache/stream-progress.txt`).
Encoder speed alone does not prove that the network is healthy, so it goes
down to 720p on any one of these:

- every speed report for 60 s is under 0.95;
- ffmpeg's `drop_frames` count rises by more than a second's frames in 60 s;
- ffmpeg's `frame` count stands still for 60 s, which is how a stalled
  connection shows even at speed 1;
- the stream breaks off (a write to ffmpeg fails) 3 times in 10 minutes.
  Each break retries after 30 s, never in a tight loop.

Each of these is said in the stream's log.

On the first night, 1080p held at speed 1.01 with no frames dropped, once
the drawing moved to its own thread: drawn on the feeding loop, it stalled
the feed to 0.79.

**Drawing.** A 1080p picture took about 0.7 s to draw at first, which is
over the 200 ms aimed for. Loading each font and size once
(`functools.lru_cache`), reading `stream-targets.toml` again only when it
changes, and stretching the pictures after shrinking them brought it to about
220 ms. It is still drawn on its own thread (`stream.Composer`) every 3 s,
and the loop feeding ffmpeg never waits for it. The new picture crossfades in over three pictures (300 ms).

## Layout (1920 × 1080)

```
┌─────────────────────────────────────────────────────────────────────────┐
│ TELESCOPEYOKE  live observatory                        ● LIVE  02:21 UTC│
│                                                                         │
│                                                  ┌────────────────────┐ │
│                                                  │ M31                │ │
│                                                  │ ANDROMEDA GALAXY   │ │
│                                                  │                    │ │
│              THE STACK (the hero)                │ NOVA PATROL        │ │
│              ~1300 × 870                         │ Searching tonight's│ │
│              "225 exposures combined"            │ image for stars    │ │
│                                                  │ that weren't here  │ │
│                                                  │ before.            │ │
│                                                  │                    │ │
│                                                  │ [programme graphic]│ │
│                                     ┌──────────┐ │                    │ │
│                                     │ONE       │ │ 203 / 211          │ │
│                                     │EXPOSURE  │ │ FRAMES KEPT        │ │
│                                     │4 s       │ │ 54 MIN             │ │
│                                     └──────────┘ │ LIGHT COLLECTED    │ │
│                                                  └────────────────────┘ │
│ ● LIVE        02:21:36 UTC              LAST EXPOSURE 3 s    NEXT · P7  │
└─────────────────────────────────────────────────────────────────────────┘
```

- **The sky is about three quarters of the screen.** The stack is about
  1300 × 870, with a small caption in its corner: "225 exposures combined".
- **The single exposure is an inset**, about 300 × 200 in the stack's lower
  right, labelled **ONE EXPOSURE · 4 s**, using the run's real exposure. Side
  by side with the stack, it teaches what stacking is: one exposure is faint
  and noisy, and the combined one keeps improving.
- **The side panel is about 430 wide**, with the object, the programme, its
  graphic and two or three figures, top to bottom.
- **Header**: a small "TELESCOPEYOKE live observatory" at the top left, the
  night-stage line in the middle, and the live state alone ("● LIVE") at the
  top right. There is no other logo.
- **Footer**: separate fields lined up by position, not joined with dots:
  how long ago the last exposure came (left), the UTC time (centre, the only
  clock on screen), and what is next (right).
- **Safe margins**: nothing important within 96 px of either side or 54 px
  of the top and bottom (5 %), as broadcast titles are kept.

### Colour

| Use | Colour |
|---|---|
| background | `#060A12` |
| panel | `#0B1220` |
| panel raised | `#111A2A` |
| main text | `#EEF4FF` (never pure white) |
| secondary text | `#A5B2C8` |
| accent (the one identity colour) | `#66C5FF` |
| live | `#63D68B` |
| attention | `#F2B95D` |
| problem (only something genuinely wrong) | `#EE6B73` |

Text contrast is about 7:1 against its panel or more, well above WCAG's
4.5:1, because the pictures under and around it are dark and low in
contrast. A test checks each text colour against its background.

### Type

The fonts are DejaVu Sans, Bold and Mono, which are already installed and
openly licensed. Sizes at 1080p:

| Text | Font | Size |
|---|---|---|
| Target name | Bold | 60 px |
| Programme name | Bold | 28 px |
| Body words | Sans | 24–25 px |
| Figure numbers | Bold | 46 px |
| Figure labels | Sans, capitals | 18 px |
| Footer, UTC time, exposure lengths | Mono | 21 px |

At the 720p fallback, every size is two thirds of this. Nothing is smaller
than 18 px at 1080p, because viewers watch inside a phone app.

**On a phone.** A 1080p stream in a phone's Twitch player is about 360 px
wide, a fifth of its size, so body text cannot be read there whatever its
size. What must read is the object's name and the figures, and a test keeps
them at least 10 and 8 px tall at that size. `./stream.py preview` draws
each state at 360 × 203 beside the full size, to judge the rest by eye.

**Less text.** Each object's `words` is one short sentence, always on screen.
Anything more goes into its `captions`, which are shown now and then.

## The stack looks its best

This is the piece most worth the effort. The stream gets its own **display
stretch**, made from the same stack the page shows. It never touches the FITS
files that the measurements use:

science stack → a non-destructive display transform → broadcast picture

The display stretch:

- keeps the sky dark and neutral without clipping faint structure (the
  black point sits a little under the background, never at it);
- lifts faint structure gently (an asinh stretch);
- neutralises a colour cast (scaling each channel's background to grey);
- tames bright stars before they clip (a soft shoulder);
- gives a slight saturation lift and a very mild local contrast;
- does no sharpening and adds no detail.

The single exposure gets the same display style, normalised independently from
its own background and noise. Its stretch is never the stack's parameters
reused, so that it looks like a real exposure of sky.

**The sky, not the object.** The background and noise are measured from the
darkest 60 % of the picture only (`sky_of`). That way a galaxy filling a
third of the frame, as M31 does, does not lift the sky's level and flatten
the galaxy.

**No pumping.** Each new exposure would otherwise jump in brightness and
colour as its own sky moved. So the calibration used for each role (the
stack, the single exposure) moves only a fifth of the way towards each new
picture's (`steady`).

**Cropping.** Scientific content is never cropped just to fill the box. A
picture is fitted whole and letterboxed by default. A crop for presentation
is allowed only where it is defined for that target. The blurred backdrop of
the between-targets card is not scientific content and may fill the
screen.

When a new stack arrives, it **crossfades over 350 ms** from the old one, so
the galaxy seems to come out of the dark through the night.

## The side panel

### The object

Its name, its common name in capitals, one or two plain sentences, then one
small line of facts:

> **M31**
> **ANDROMEDA GALAXY**
> The nearest large galaxy to the Milky Way. Its light has travelled about
> 2.5 million years to reach this camera.
> ~2.5 million light years · magnitude 3.4

> **WASP-12**
> A star with a giant planet so close that it circles in just over a day.
> ~1,400 light years · magnitude 11.6

These come from a hand-written table, **`stream-targets.toml`**, kept in the
repository. It has one entry for each object the project images, with these
fields:

- `common` (optional);
- `words`, in plain language and never catalogue prose ("spectral type G0V"
  is not for viewers);
- `distance` and `magnitude`;
- `captions`, the science captions below.

An object with no entry shows its name and its catalogue type only. A
missing entry is never filled with made-up facts. A test checks that every
entry has its fields and fits its box.

### The programme: a graphic only where the graphic is the science

There are no general telemetry graphs. Each programme gets the one graphic
that explains it, or none.

**Transit** (a planet `transits.py` lists tonight for this star):

> **WASP-12 b**
> **HOT JUPITER TRANSIT**
> The planet passes in front of its star and dims it by about 1.4 %.

The graphic is the light curve. The expected transit is drawn as a muted
box shape, using the ingress, middle and egress times from `transits.py`,
which are labelled under the axis. The measurements are brighter dots, and a
"NOW" marker shows the time. The key says **EXPECTED** and **LIVE
MEASUREMENTS**: the dots are never called a confirmed transit. The panel has
one state at a time:

- **MEASURING BASELINE**, with "18 min collected · transit begins in 32 min".
  This shows until there are 30 minutes of points and the scatter (in 5 min
  bins) is under half the expected depth.
- **LIVE PHOTOMETRY**: the dots, once the test above passes.
- **PHOTOMETRY PAUSED: LOW SIGNAL**, when the comparison stars' summed flux
  drops by more than 30 %, or frames are being rejected. It never says
  "cloud" unless the cloud sensor or the run's rejection reason says cloud.

A poor light curve is never shown just because one exists. The measurement
is `transits.measure` on the session so far, run every 5 minutes in its own
process, because it reads frames and must not slow the stream.

**Nova patrol** (patrol.py, M31 or M33):

> **NOVA PATROL · ANDROMEDA**
> Every star in this picture is being compared with an earlier night.

The graphic is the panel map, drawn from the patrol's own panel layout. A
done panel is filled, the current one is outlined and gently pulsing, and
the rest are open, with "5 / 8 searched" beside it. Candidates are counts
only, worded so they don't sound like discoveries:

- "2 possible changes, being checked automatically" (not "2 unexplained").
- "No confirmed new star yet", once vetting has rejected them.

At the start of each panel, for 10 seconds, the graphic becomes
**REFERENCE / TONIGHT**: two small views of the panel, the reference stack
(`reference.py`) and tonight's. They are whole panels, never a cut-out
around a candidate. This shows what "looking for new stars" means.

**Variable star** (starwatch.py): the brightness curve so far, with the
same rule of not showing it before there are enough points.

**A picture** (a shoot.py imaging run): "Every exposure is added to the
stack; the noise falls as they add up." The graphic is a thin progress arc
of the time collected against the time planned, if a time is planned.
Otherwise there is none.

**The Moon** (a run whose `object_kind` is `moon`, from `sky.object_kind`,
written into the session by `shoot.py`; older sessions fall back on the
name, so "Moon-Copernicus" is still the Moon). The first object with its own
mode, so a figure that means nothing for it is never shown (24 October 2026:
a Moon run's panel said STAR SIZE 9.3″):

> **THE MOON**
> Hundreds of short exposures are combined to make the surface cleaner and more detailed.
> TONIGHT'S MOON · Waxing · 97% illuminated · 12.9 days after new Moon

It is the Moon whenever the telescope was last aimed at it and got there
(`director.py`), not only when the last run's name says so; while the GoTo
is still moving the headline says MOVING TO THE MOON, and a GoTo that
failed or landed far off names no target. In the live
view, **LIVE VIEW** and "What the telescope sees now: a fresh frame every
few seconds, nothing stacked." While a lucky-imaging video is taken or
stacked (`lucky.py`, activity phase `lucky`), the words say instead that
short exposures freeze steadier moments and the sharpest fifth are
combined afterwards, and under them where it has got (`web/lucky.json`):

| Stage | Title | Figures |
|---|---|---|
| centring | FINDING THE MOON | centring the disc from its own picture |
| capturing | CAPTURING THE SHARPEST MOMENTS | 846 / 2,000 · 31 a second · 8 ms exposures |
| ranking | RANKING EVERY FRAME | 1,200 / 2,000 |
| stacking | CORRECTING THE ATMOSPHERE | 400 / 2,000 · 742 alignment regions |
| done | RESULT READY | best 400 of 2,000 frames |
| mineral (`mineral.py`, phase `mineral`) | REVEALING THE MOON'S SUBTLE COLOUR | 3 colour videos · checking the colour repeats from video to video |

While a video is stacked or made into the mineral Moon the camera is done
with: the header says ● PROCESSING, and its last frame stays the picture,
neither greyed nor called paused. The Moon's state comes from
`sky.moon_state` at the site, worked out live: never from
`stream-targets.toml`. Its LOOK CLOSELY lines follow the phase
(`streamstory.moon_notices`): from 90 % lit, short shadows, rays and maria;
otherwise the terminator. A line "THE MOON · 97% illuminated · altitude 31° ·
371,200 km away" joins them and leads the crawl. The story never says star
size or search depth for the Moon. Where the Moon is in the frame is not
measured, so features are never named at a place in the picture. A Moon
step on tonight's plan adds "TONIGHT: THE MOON" to the night-opens card.

### The figures

There are three at most, as large numbers with small labels and no graphs.
They depend on what is observed (`streamlook.figures_for`). Deep sky:

| Figure | From | Shown as |
|---|---|---|
| Frames kept | `accepted` / (`captured` − `waiting`) | **203 / 211** FRAMES KEPT |
| Light collected | `integration` | **54 MIN** LIGHT COLLECTED |
| Star size | the median `series.fwhm` of the last 10 kept frames × the plate scale, changed at most every 30 s | **5.8″** STAR SIZE |

The Moon (`moon_figures`), in this order, as many as fit:

| Figure | From | Shown as |
|---|---|---|
| Illuminated | `sky.moon_state` | **97%** ILLUMINATED |
| Distance (the age is in the line under the programme) | `sky.moon_state` | **371,200 KM** AWAY |
| Altitude | `sky.moon_state` | **31°** ALTITUDE |
| Frames kept, keep rate | as deep sky | **7 / 7** FRAMES KEPT, **100%** KEEP RATE |

When a figure changes, it crossfades over 300 ms rather than jumping. The
star size is held for 30 s at a time, so the flicker of seeing from frame to
frame does not make a healthy run look unsteady. When the programme needs
the room, the figures go first: the transit's light curve can leave room for
only one or two.
Tracking drift, star counts and roundness stay on the status page, which is
the place for them.

## Moments: short, then out of the way

The panel above is what is on screen most of the time. These appear for a
few seconds and then fade:

- **Target introduction, 7 s**, when a new target starts imaging. The
  newest stack (or the last one, dimmed) fills the screen behind it:

  ```
                M31
          ANDROMEDA GALAXY
   the nearest large galaxy to the Milky Way
       about 2.5 million light years away
          NOVA PATROL · PANEL 4
  ```

  It then dissolves into the normal layout over 400 ms.
- **Science captions** became the presenter's lines and chapters: see "The story".
- **Headline, 4 s**, when the target or the activity changes
  (`director.headline`, drawn by `streamlook.headline_band`): "NOW
  OBSERVING: THE MOON", "LUCKY IMAGING STARTED", "STACKING THE BEST FRAMES",
  "MINERAL COLOUR PROCESSING", "RESULT READY". A band across the top of the
  picture, over it and never instead of it; the presenter's line waits
  until it has gone.
- **Tonight ribbon, 10 s, every 15 minutes** and during every between-targets
  card:

  ```
  TONIGHT   M31 core ✓ ─ M31 panels ✓ ─ WASP-12 b ● ─ M31 P6 second look ○
  ```

  Done steps are dimmed, the current one is in the accent colour, and those
  to come are outlined. It comes from the schedule's steps.
- **Night stage**, a single short line under the header that changes through
  the night. Early: "Tonight's observing begins". Then "3 h 18 min observed
  · 5 fields done". Finally "Last target before dawn", when the schedule's
  last step is running.

## The story: a presenter, not a ticker

The panel and the picture above are correct, but they are an instrument
display. Someone arriving takes it all in within 30 seconds, and nothing
says that anything else is coming. NASA's and ESA's launch broadcasts keep
an audience through a long wait in the same way: they keep saying what you
are watching, why it matters, what has happened and what comes next.
`streamstory.py` is that presenter. It never adds a permanent ticker,
because a ticker becomes wallpaper.

**The broadcast clock.** From the stream's start, round and round (`CLOCK`,
4½ minutes):

```
NOW 45 s · SCIENCE 25 s · NOW 45 s · HOW IT WORKS 25 s · NOW 45 s · TONIGHT 20 s · NOW 45 s · COMING UP 20 s
```

During NOW the panel shows the programme as it is: the light curve, the
panel map. In the other chapters the programme's place in the panel shows
one card under that heading:

- **SCIENCE**: the object's `facts` and `why`, and the programme's
  `explainers` (what a nova is, what a transit is).
- **HOW IT WORKS**: the programme's `method`, how the telescope works
  (`[stories]`: stacking, plate solving, focus, discovery, the telescope),
  and cards made from the night's own measurements:
  - "This picture combines 225 exposures of 16 s each: 60 minutes of light
    from this one patch of sky."
  - how many frames have been set aside, and the main reason why;
  - the stars' measured size;
  - for a patrol, the depth measured by planted fake stars, for example
    "down to about magnitude 16.7: some 20,000 times fainter than the
    faintest star the eye can see".
- **TONIGHT**: the fields searched, the frames kept, the candidates awaiting
  review, and how long the night has run. With no candidate it says "No
  confirmed new star yet: most nights find none, and that is still a
  result", so that "0" reads as science rather than failure.
- **COMING UP**: the next step in plain words and when, for example "COMING
  UP IN ~12 MIN · WASP-12 b transit", with that object's own one-line
  description and what follows it. The footer's operational "NEXT" became
  "COMING UP" too.

**Between chapters**, a line goes across the top of the picture for 10 s
every 90 s. It is either a **LOOK CLOSELY** line from the object's `notice`
("Almost every sharp star in this picture is in our own galaxy, in front
of Andromeda"), or the presenter's own voice made from the run's state
("TELESCOPEYOKE · I'm searching this part of M31 for any star that wasn't
here before"). That voice is deterministic status, worded as a presenter
would say it. It never pretends to think.

**Explainers, 12 s every 5 minutes**, drawn over the dimmed picture:

- **What is stacking?** Tonight's own single exposure beside tonight's own
  stack.
- **What is a transit?** A star with the planet's shadow, and the dip in
  its brightness.
- **What is a nova?** White dwarf → gas builds up → it ignites.
- **How does the search work?** OLD SKY − TONIGHT = WHAT CHANGED. This one
  is labelled as a diagram, and its stars are drawn, never a real field or
  a real candidate.

- **The comet hunt.** When the comet hunt (`sungrazer.py hunt`) has, in
  the last 36 hours, found a comet that matches the Sungrazer Project's
  report of a known comet, the first, middle and last pictures of its
  movie, with the hunt's own figures: "On 19 October the comet hunt found
  a known Kreutz sungrazing comet by itself in 74 pictures from the
  GOES-19 satellite: 27 of them, over 7 hours." The same words join the
  HOW IT WORKS cards. A track that matches no report, or only someone's
  unconfirmed one, is never shown: like a nova candidate, it is the
  person's to check first (`streamstory.comet_hunt`).

Which explainers come depends on the programme. They are taken in turn.

**The crawl, 45 s every 10 minutes**: one slow line along the bottom, over
the footer, for example "TONIGHT · M31 nova patrol · 5 of 8 M31 fields
searched · next: WASP-12 b transit". It is drawn once
(`streamlook.crawl_strip`) and slid along at 70 px a second by
`stream.Composer` between the pictures it draws. It is never constant: it
runs and then it is gone.

**Rules.**

- Someone arriving sees a chapter, a line or an explainer within a minute.
  A test checks that the longest gap is 60 s.
- A card shown is not shown again until the rest of its pool has been
  (`Story.pick`). Each card stays the same through its slot.
- Every word is curated in `stream-targets.toml`, or made from a
  measurement. A number not measured is left out, never filled in. A test
  checks that a state with nothing measured gets no measured cards.
- A candidate's follow-up or a paused run takes the screen to itself, with
  no chapters, lines, explainers or crawl (PRIORITY below).

**Not every idea was a fact.** Some suggested lines were not true of this
project, so they are not used:

- "The telescope checks a possible change twice before bothering a human":
  the phone is told at once.
- "Each timing goes to ExoClock": sharing a timing is the person's
  decision.

Each line in `stream-targets.toml` was checked against a published source
before it went in.

**One lesson from the first night.** The running stream reads
`stream-targets.toml` live. When the file's shape changed under older code,
the picture stopped being drawn and froze for about 9 minutes, until the
stream was restarted on matching code. Change the file's shape only together
with the code, and restart the stream. A drawing error is now said once
("picture not drawn, the last one stays"), not every 3 s.

## Chat

`streamchat.py` answers a few commands in the Twitch chat, from the same
curated words and measured figures, so that a curious viewer can dig deeper
without the picture filling up: `!what`, `!target`, `!next`, `!focus`,
`!polar`, `!telescope`, `!camera`, `!nova`, `!transit` and `!help`. `!focus`
and `!polar` answer from the same files as the focus and polar looks.

- No command moves or changes anything, and an unknown command gets no
  answer.
- It answers at most once every 3 s, and each command at most once every
  30 s.
- It runs inside `stream.py watch` while the stream is on air.
- It needs the sign-in to include `chat:read` and `chat:edit`. Until the
  person runs `./stream.py twitch-login` again with those, it says once that
  the chat's commands are off.

## What wins the screen

Which picture is the main one, and which target it is, is the director's
answer (`director.py`; the order is in [streaming.md](streaming.md#what-is-on-screen-and-why-the-director)):
focusing or polar alignment, then a fresh frame from the camera, then a
Moon video being processed, then the GoTo, then a stopped run's stack. A
stale run's stack or figures never outrank the camera's fresh frame.

Within the picture, when two things want the same space, the one higher in this list wins
(`streamlook.PRIORITY`):

1. a problem or failure;
2. a candidate follow-up;
3. a target transition (introduction, between targets, end of night);
4. the programme graphic;
5. a science caption;
6. the figures, which take whatever room is left in the panel.

## Is it live? The age of the last exposure

The footer says so, worded calmly:

| Last exposure | Footer | Colour |
|---|---|---|
| under 30 s, or under twice the exposure length | ● LIVE | live |
| up to 120 s | ● WAITING FOR NEXT EXPOSURE | secondary |
| over 120 s | PAUSED · no new exposure for 2 min | attention |
| a Moon video being stacked or made into the mineral Moon | ● PROCESSING | live |

When the paused state is shown and the status page's checks show the
camera and mount connected, it adds "telescope still connected". It says
cloud only when the cloud sensor or the run's rejections say cloud.

While paused, the stack itself is a little dimmer and greyer (40 % towards
grey, 25 % darker). This shows that it is not updating without making it
look broken.

Each time the stack grows, a small "+1" (or "+N") appears for a moment
beside its "exposures combined" caption. That caption sits on a quiet,
see-through plate in a smaller type (19 px), so it reads as a caption and not
as another widget. The plates, the caption and the inset sit on the picture
itself, never on the letterbox bars beside a narrow picture.

## Between targets

Before this change the stream stopped five minutes after the last exposure
and started again with the next run, so it dropped out at every GoTo.

Built: while the schedule runner is alive and its next step starts
within 15 minutes, the stream stays up and shows a between-targets card. The
last stack fills the screen, cropped slightly, darkened by 40 % and lightly
blurred, with this over it:

```
NEXT TARGET
WASP-12
Hot Jupiter transit · imaging begins in about 4 min

✓ moving telescope
● confirming field        (plate solving)
○ checking focus
○ imaging
```

The checklist comes from `activity.phase()`, which maps each activity's own
name to an explicit phase (`activity.PHASES`): "Moving" is goto, "Plate
solving" is solve, "Patrol", "Imaging" and "Searching" are imaging, and the
focus stages ("Checking focus" is focus_check; "Focusing with the motor" is
focus_sweep, or focus_walk and focus_find by its mode; "Fitting the focus
curve" is focus_fit; "Checking the fitted focus" is focus_verify) all count
as the checklist's focus step (`activity.step_of`). It never parses the
words. The steps before the current one are ticked. This lives in
`activity.py` rather than `schedule.py` because the steps are set by
mount.py, solve.py and focus.py inside the schedule's commands, and
`activity.py` is where every process says what it is doing. The card then dissolves into the target introduction.

With nothing running and nothing due, the stream ends as now, after the
end-of-night card when the night has finished.

## Focusing and polar alignment

Built on 22 October 2026, seen so far in the preview and the tests only.
Setting up is part of the night, and worth watching: the stream goes on air
for it (`docs/streaming.md`, "Focusing and polar alignment on air"), and
each has a look of its own in place of the stack and the object panel.

### Focus

```
[ STAR SIZE (HFR)                                  ]   FOCUSING
[  ●                                       ●       ]   what this run does, in a line
[        ●                         ●               ]   5.07  AT THE START · HFR
[              ●           ●                       ]   2.40  NOW · HFR
[ - - - - - - - ◎ - - - - - - - - - USUAL BEST 2.28 ]   2.31  BEST SO FAR · HFR
[             BEST SO FAR 2.31                     ]   usual best 2.28 · tonight's best so far 2.19
  FOCUSER POSITION, half-steps from the start          position 4 of 9
[START] [NOW]  ONE STAR, MAGNIFIED                     ✓ measure  ● sweep  ○ fit  ○ verify
                                                       HOW FOCUSING WORKS (a card from [stories] focus)
```

- The curve is every reading, as focus.py measured it: the focuser's
  position against the HFR. The best so far is ringed and labelled, the
  usual best is a dashed line, the fitted focus a line once the fit is
  made, and the newest reading has an outline. Far out of focus, before any
  HFR measures, it draws the doughnuts' size instead, and says what the
  doughnut is.
- The two squares are the brightest star in view, magnified: as it was at
  the start of the run, and in the newest picture.
- The steps are the run's own (`focus.STAGES`): a check measures; a focus
  run measures, sweeps, fits and verifies; a walk-in has doughnuts, coming
  in, finest steps and done; the search for stars searches. A count is
  shown only where it is known: "picture 2 of 3" for a check, "position 4
  of 9" in a sweep, "step 3 of 4" in the search.
- When it ends a card is held for ten seconds (`streamlook.CARD_S`):
  FOCUS COMPLETE with the start and end HFR and how much smaller the stars
  are; FOCUS CHECK PASSED when it was left alone; FOCUS IS SOFT for a check
  that found it worth focusing; FOCUS CURVE REJECTED, FOCUS RETURNED TO
  START, NO STARS FOUND or FOCUS RUN STOPPED with what happened in plain
  words.

### Polar alignment

```
          TOO HIGH                ROUND BY ROUND               POLAR ALIGNMENT
     ( ( (  +  ) ) )              1 ███████████████ 9.6°       Waiting for the mount to be adjusted
 WEST   [drift limit]   EAST      2 ████ 2.5°                   1.8°  FROM THE POLE
          ●                       3 ███████ 4.2°                2.1°  AZIMUTH · WEST OF NORTH
          TOO LOW                 4 ███ 1.8°                    1.3°  ALTITUDE · TOO LOW
 + TRUE POLE  ● POLAR AXIS        WHAT TO DO                    the round before: 4.2°
                                  Turn the whole tripod 2.1°    drift in a 16 s frame: 3.4 px, 2.1 px
                                  clockwise, seen from above…   target: under the drift limit, 1.25°
```

- The bullseye has the true pole at its centre and the axis at its measured
  azimuth and altitude errors, as polaralign.py gives them: up is too high,
  east to the right as seen facing north. The drift limit is a square, since
  it holds on each axis alone. While a measurement is under way the last
  one is dimmed and the three pictures are ticked off in its place.
- Every round tonight is a bar, the newest in the accent colour.
- The advice is polaralign's, said for people not standing behind the
  mount: the whole tripod or the mount turned clockwise or anticlockwise
  seen from above, with centimetres at each foot where the tripod's figure
  is known, the polar axis raised or lowered, and a learned bolt named by
  the side it is on (west-side, east-side, rear, front). Never left or right.
- The cards: POLAR ALIGNMENT COMPLETE with the first round and the last
  when neither axis is worth a turn; POLAR MEASUREMENT FAILED with what
  happened (a picture that could not be plate-solved, the mount not
  turning, the two sides of the meridian disagreeing).

## Possible change detected

When a patrol's search finds an unexplained candidate, the programme panel
changes for as long as the follow-up lasts. There are never coordinates,
cut-outs or a marker.

1. **POSSIBLE CHANGE DETECTED**: "The software found a point of light that
   wasn't clear in the reference image. Taking another look now."
2. **SECOND LOOK UNDER WAY**: shown while `patrol.second_look` runs.
3. **RESULT**, from the second look's own search:
   - "Not confirmed: it did not appear again", when the second look found
     nothing unexplained;
   - "Still unexplained: kept for private checking", when it did. The person
     decides what is claimed and when (`/claim`).
   - "Not confirmed: a known asteroid / variable star", when a catalogue
     explained it. This one is not built yet.

The result is news for 5 minutes (`RESULT_S`). After that the panel goes back
to the patrol, with one small line in place of the counts: "1 candidate
awaiting private review".

This lets viewers watch the method (a candidate, a repeat observation,
catalogue checks, a result) without anything being published early.

## The night opens

The first time the stream goes on air in a night, a card holds for a
minute before anything else (`stream.Opening`, drawn by
`streamlook.open_card`), over the last stack darkened and blurred:

```
THE NIGHT OPENS
TONIGHT AT THE OBSERVATORY

THE SKY            forecast GO, 20% cloud on average
CLEAR SPELL        21:00 to 03:00 UTC, about 6 h
DARK               astronomical darkness from 18:50 to 04:40 UTC
THE MOON           34% lit, waxing, sets 23:10 UTC
TONIGHT WILL TRY   M31 nova patrol, M31 mosaic fields, WASP-12 b transit
```

Every line is from `agent.night()` and tonight's schedule; a line is left
out when its figure is not known (a time without its zone is never said),
and the site is never shown.

## End of night: the night's result

When the schedule's last step has ended, and nothing more is due before
dawn, the stream shows an end card for 2 minutes and then stops:

```
THE NIGHT'S RESULT
TONIGHT COMPLETE

6 fields observed: M31-P1, M31-P2, M31-P3, M31-P5, M31-P6, WASP-12
742 frames kept
8 M31 panels searched
no possible changes
sharpest focus tonight: HFR 2.19
polar alignment: 9.6° → 1.2° from the pole in 5 rounds
next: 3 candidates open for a person to check

[the night's best final stack]

TELESCOPEYOKE
```

The fields, frames, panels and possible changes are added up from tonight's
sessions, already in the status file's `discovery`; the focus from
`cache/focus_runs.jsonl` (the last twelve hours), the polar alignment from
`cache/polar_stream.json`, and the open candidates from the status file.
Nothing on the card is counted anywhere new, and a figure not found is left
out.

## Motion

Allowed: fades of 250–400 ms, figures crossfading, one gentle pulse on the
current panel or step, one faint flash of the inset's border when an
exposure arrives, and light-curve dots fading in.

Not allowed: sliding panels, spinning loaders, animated starfields, a
bouncing LIVE badge, glowing borders, or any games-overlay effect.

## Holding it together

- Each piece degrades on its own. With no stack yet, the stack area says
  "The picture builds up after the first few exposures". With no table
  entry, only the name is shown. With no graphic for a programme, the panel
  shows its words only. Nothing is ever blank without a reason shown.
- Composing stays under 200 ms. Fades are blends of finished pictures.
  Only the light-curve measurement reads frames, and it runs in its own
  process.

## Not in this change

Two of the items first listed here have since been built: the Twitch
title, category and tags set for each target (`twitch.py`, through an app
registered for the channel), and the chat's read-only commands
(`streamchat.py`). Still not done:

- The same for YouTube's title and category.
- Music. The track is silent except for the focus tones while the telescope
  focuses (`docs/streaming.md`, "The sound").
- Sending to YouTube and Twitch at once. That is a change to `stream.py`'s
  output, not to the picture.

## Tests

- `frame()` draws without error from a fixture status for each state:
  - a transit (in each of its three panel states);
  - a nova patrol (with no candidates, a possible change, a second look, and
    each result);
  - a variable star;
  - a picture;
  - between targets;
  - the end card;
  - the target introduction;
  - focusing (a sweep, a walk-in, each result card) and polar alignment
    (measuring, waiting for an adjustment, complete, failed), from their
    own files.
  The parts each state has are checked by drawing into a recorder, not by
  reading pixels.
- No text drawn in any state contains the site's name, its latitude or
  longitude, the stream key, or a candidate's RA or Dec.
- Every time drawn is UTC and labelled.
- Each text colour has at least 7:1 contrast with its background.
- Every important box lies inside the safe margins at 1080p and at 720p.
- Every `stream-targets.toml` entry has its fields and fits its box.
- Composing takes under 200 ms on a fixture.
- `decide()`:
  - carries on between targets while the runner is alive and the next step
    is due within 15 min;
  - holds the end card for 2 min, then stops;
  - stops as now otherwise.
- The fallback from 1080p to 720p happens on a slow `speed=` report and is
  logged.
- The director (`tests/test_director.py`): a matrix of fresh frame, target
  aimed at, old run and schedule, each with its scene and target (a fresh
  Moon frame after an M31 run, with the schedule run out, is the Moon live,
  never the end); target, programme and activity apart; focusing over the
  fresh frame; a paused run keeping its stack; a target named as observed
  only once reached (slewing, centring, reached, centred, off, failed, and
  a GoTo whose process was killed), each announced once; the headline on a change and
  gone after its seconds; an answer that cannot be worked out never
  stopping the stream.
- Every scene drawn as a viewer sees it (`streamlook.scenes`): the Moon's
  scenes show THE MOON, the disc and not a black box, none of the old
  run's figures, and PROCESSING rather than PAUSED while stacking.

## Still to decide

1. Is 15 minutes the right gap for keeping the stream up between targets?
2. Does anything shown leak the place? The objects and times together hint
   at the latitude, as on any astronomy stream; nothing more should.
3. The upload speed at home is unmeasured. The first night will show
   whether 1080p holds.
