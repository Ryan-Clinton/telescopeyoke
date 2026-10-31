# The live stream: running it

What exists and how to run it. Why it looks the way it does, and what is
still to come, is in [stream-look.md](stream-look.md), the design record.

On air since 20 October 2026 on Twitch, from the WASP-12 b transit run
(`docs/validation.md`, "Live stream on Twitch"). YouTube is built as a
destination, alone or beside Twitch, and not yet tried on air. The focus
and polar alignment looks and the focus tones were built on 22 October
2026 and have been seen only in the preview and the tests, not yet on air.

## What a viewer sees

A 1080p picture at 30 frames a second, made by `streamlook.py` from the
status page's own data:

- the running stack filling most of the screen, with the newest single
  exposure inset and a display stretch so the sky stays dark;
- a side panel: what the object is, in plain words from
  `stream-targets.toml`, the programme (a nova patrol's mosaic of fields, a
  transit's times and, once it is steady, its light curve) and the night's
  figures (frames kept, light collected, star size);
- a presenter (`streamstory.py`) that changes the panel's chapter in a loose
  broadcast clock: NOW, SCIENCE, HOW IT WORKS, TONIGHT and COMING UP; a LOOK
  CLOSELY or TELESCOPEYOKE line across the picture now and then; a larger
  explainer every five minutes (stacking, a transit, a nova, how the search
  works, and a comet the hunt recovered); and a slow crawl every ten;
- while the telescope focuses, the focus look: the focus curve as it is
  measured (star size against focuser position, the best so far ringed, the
  usual best as a line, the fitted focus once there is one), one star
  magnified at the start and now, the start, current and best HFR, "usual
  best 2.28 · tonight's best so far 2.19", "position 4 of 9", and the steps
  ticked off (measure, sweep, fit, verify; a walk-in has doughnuts, coming
  in, finest steps, done); with the focus run's tones as the stream's sound;
- while the mount is polar aligned, the polar look: a bullseye with the true
  pole at the centre, the axis at its measured azimuth and altitude errors
  and the drift limit as a square, picture 1, 2 and 3 ticked off, every
  round tonight as a bar (9.6° → 2.5° → 4.2° → 1.8° → 1.2° on 22 October
  2026), the error and the round before, the drift each axis causes in a
  frame, "target: under the drift limit", and what to do, said as clockwise
  or anticlockwise seen from above (never left or right);
- a card for ten seconds when either ends: "FOCUS COMPLETE 5.07 → 2.19 HFR,
  57% smaller stars", "FOCUS CHECK PASSED", "POLAR ALIGNMENT COMPLETE 9.6° →
  1.2°", or what went wrong in plain words (the curve rejected, focus sent
  back to the start, a picture that could not be plate-solved);
- across the top of the picture for four seconds, what has just changed:
  "MOVING TO THE MOON", "NOW OBSERVING: THE MOON" once it is there,
  "STACKING THE BEST FRAMES" (the director, below);
- a candidate's state without its place: "possible change detected",
  "second look", then the result, or "awaiting private review".

Nothing is made up: every word is curated or measured, and a figure that is
not known is left out. Nothing names the place, times are UTC, and no webcam
is ever shown.

## Running it

    ./stream.py key                once: paste the stream key (kept readable only by you)
    ./stream.py twitch-login       once: let it set the channel's title, category and tags,
                                   and answer in the chat (asks for chat:read and chat:edit)
    ./stream.py watch --install    run the watcher as a user service from boot (ty-stream)
    ./stream.py                    what it would do now, and why; sends nothing
    ./stream.py preview            every state at full and phone size, cache/stream-preview/
    ./stream.py scenes             each of the director's scenes, cache/stream-scenes/
    ./stream.py director           what it shows now and why (below)

It is off unless `[stream] enabled` in `config.toml` (the Settings screen),
with `[stream] service` "twitch", "youtube" or "custom", or several of them
(below). The watcher goes on
air when the camera has a picture under two minutes old, whatever takes it
(a run, a Moon video, the live view), while a Moon video is stacked or made
into the mineral Moon, or while the telescope is focusing or being polar
aligned (below). It stays on air between targets when the schedule's next
step is due within 15 minutes, stops at once when the night is over (the
schedule run out and nothing else happening), and otherwise stops when
nothing new has come for five. For each target it sets the Twitch title, category and tags.

## What is on screen, and why: the director

What the observatory is doing, and so what the stream shows, is decided in
one place, `director.py`, and kept in `cache/broadcast.json` every two
seconds. Before 31 October 2026 the stream read status.json, the activity
lines, the newest picture's age, the schedule and the lucky imaging's file
and worked it out afresh in several places. On 30 October the telescope was
filming the Moon while the stream named the last run (M31), said "Tonight
complete" and showed an empty picture.

- **The target** is what the telescope was last aimed at,
  `cache/target.json`: every GoTo writes it (`mount.py`), and so does any
  lucky-imaging video (`lucky.py capture`). The newer of this and a run
  that is imaging names the target. A run's status never names it once the
  telescope has been aimed somewhere else, and its frame counts, star size,
  stack and "coming up" are then left out.
- **A GoTo asked for is not a GoTo done.** The record says how far the aim
  has got, and the stream says only that much:

  | State | Written when | The stream |
  |---|---|---|
  | slewing | the GoTo sets off | MOVING TO THE MOON |
  | centring | it is plate-solving to centre (`--solve`) | CENTRING THE MOON |
  | reached | the mount says it has arrived, and its own reading of where it points is within 2° of the object (shown by the mount) | NOW OBSERVING: THE MOON |
  | centred | a plate solve found the object in the middle, or a Moon video found the disc in its frame (shown by the camera) | NOW OBSERVING: THE MOON |
  | filming | a lucky-imaging video of something no GoTo went to: the person aimed it | NOW OBSERVING |
  | off | the mount reads more than 2° from the object | names no target |
  | failed | the GoTo was refused, timed out or stopped, or still "slewing" 20 min later (its process killed) | names no target |

  A small move about a target already reached (a dither, centring the
  Moon) leaves the record as it is. `./stream.py director` says which state
  it is in and what showed it.
- **The target stays** until something else is aimed at: another GoTo; the
  mount sent home, to the zenith or to a position (`mount.py home`,
  `zenith`, `point` and the surveys clear it as they start); the night's
  end once the mount is parked (`schedule.py end`); or `./stream.py
  director --clear`. A record nothing cleared is dropped after 12 hours, as
  a safety net only.
- **Target, programme and activity are kept apart**: the Moon, lunar lucky
  imaging, capturing; M31-P3, nova patrol, imaging; WASP-12, exoplanet
  transit, imaging; the Moon, mineral Moon, mineral processing.
- **Which picture wins**, highest first:
  1. focusing or polar alignment, which have their own looks;
  2. a fresh frame from the camera (under two minutes old), whatever takes
     it. During an imaging run of the target its stack is the big picture
     with the frame inset, since the stack is made of those frames;
  3. a Moon video being stacked or made into the mineral Moon: its last
     frame, marked ● PROCESSING rather than paused;
  4. the GoTo moving;
  5. the end of the night, when the schedule has run out and nothing above
     it is happening: the stream stops;
  6. the current run's stack after its frames stop (cloud);
  7. nothing.
  The first three put the stream on air by themselves. The schedule never
  outranks the camera.
- **A change is announced** for four seconds in a band across the top of
  the picture, never instead of it: "NOW OBSERVING: THE MOON" for a new
  target; LUCKY IMAGING STARTED, STACKING THE BEST FRAMES, MINERAL COLOUR
  PROCESSING, RESULT READY, CHECKING FOCUS, POLAR ALIGNMENT, IMAGING STARTED
  or MOVING THE TELESCOPE for a new activity.

To see why the stream shows what it shows:

    ./stream.py director           the target, programme, activity, scene and picture, and what was left out
    ./stream.py frame --director   the picture it would send, with that written over it (never sent)
    ./stream.py scenes             every scene drawn from made-up examples, cache/stream-scenes/*.png

For example, during a Moon video after an M31 run, it prints:

    target:     Moon (moon)
    aim:        centred, shown by the camera
    programme:  lunar lucky imaging
    activity:   capturing
    scene:      moon_capture (priority 90, on air)
    image:      latest, newest picture 1 s old
    ignored:    status target M31: the telescope was aimed at Moon after it

## Focusing and polar alignment on air

The stream goes on air for these as it does for imaging, and shows each its
own way. What it shows comes from small files the two commands write as they
go, never from their log:

| File (under `cache/`) | Written by | What it holds |
|---|---|---|
| `focus_stream.json` | `focus.py --motor`, `--walk-in`, `--find`, `--sweep`, `--check` (`focus.Broadcast`) | kind, stage, steps, every reading with the focuser's position, start, current, best and usual HFR, the fit, how it ended and why |
| `focus_star_start.png`, `focus_star_now.png` | the same | the brightest star in a small square, at the start and now |
| `polar_stream.json` | `polaralign.py` (`polaralign.tell`) | stage (measuring, adjust, complete, failed), picture n of 3, a recheck or not, every round tonight, the error now and the round before, the drift per axis, the drift limit, the advice |

Focusing by ear (`./focus.py` with no `--motor`) and the focuser's own
measurements (`--measure-step`, `--measure-backlash`) write no stream file
and are not shown. `streamlook.focus_stream_state()` and
`polar_stream_state()` read them. The
stream is on air while a run is going (its process alive and its file
written in the last ten minutes), for 15 minutes after a polar measurement
that asks for an adjustment (a person turning the bolts: `polar_adjust`),
and for the ten-second card when either ends. Any activity line in
`activity.BROADCAST` keeps it on air too. Focus is shown first: polar
alignment needs it, and the two never run at once.

The activity lines name each stage (`activity.PHASES`): `focus_check`,
`focus_sweep`, `focus_walk`, `focus_find`, `focus_fit`, `focus_verify`,
`polar_measure`, `polar_recheck`, with `polar_adjust` from the polar file.
The between-targets checklist still counts every focus stage as "checking
focus" (`activity.step_of`).

Only what the code has is shown. The usual best is `focus.usual_best()`;
tonight's best is this run's and those in `cache/focus_runs.jsonl` from the
last twelve hours. The drift limit is polaralign's own: an error is left
alone when the drift it causes over one frame stays under a star's own size
(2 px; 1.25° for 16 s frames), and the drift shown is what polaralign
works out from 0.1 px a second per degree. The polar history starts again
when the last round is more than six hours old. The polar alignment's three
numbers (azimuth, altitude and the total) together hint at the latitude to
a few degrees, as the objects and times already do; nothing more is shown.

### The sound

While a focus run is on air, each new reading is heard as the focus aid's
own sound: a click and a tone, higher the sharper the stars (`focus.pitch`
of the usual best over the reading, so the top note is the usual best or
sharper), or two clicks for a reading with no stars. Between readings, and
for everything else, the sound is silence as before. The tones go to
ffmpeg as raw sound on a pipe of their own, written on their own thread and
paced by the clock, so the pictures never wait on them; a test sends both
through ffmpeg into a file and checks the sound is there. `[stream]
focus_tones = false` (the Settings screen: "Focus tones on the stream")
keeps the old silent track. It takes effect when the stream next starts.

## The broadcast's running order

A night on air runs in five parts, and each has its look:

Since 30 October 2026 no card takes the place of what the telescope sees
on air: the night-opens, between-targets and end-of-night cards below are
still drawn by `./stream.py preview` but not sent, and the stream stops at
once when the night is over.

1. **The night opens.** The first time the stream goes on air in a night
   (none in the last twelve hours, `cache/stream-night.json`) it holds a
   card for a minute (`OPEN_S`) before anything else: the forecast's
   verdict and mean cloud, the clear spell, the darkness, the Moon (how lit,
   waxing or waning, when it rises or sets) and what tonight will try (the
   schedule's steps, or else the discovery programmes in the clear), all
   from `agent.night()` (`./ty night`), times in UTC, never the site. The
   plan is read on its own thread, so going on air never waits for the
   forecast; with no plan there is no card.
2. **Setup and calibration.** Focusing and polar alignment, each with its
   own look and its result card; the GoTo and plate solve show on the
   between-targets card's checklist.
3. **Science.** The imaging runs: a nova patrol's mosaic, a transit's light
   curve, a picture building up, and a candidate's follow-up without its
   place.
4. **Background work.** Between targets, while the schedule has more due,
   the card with what comes next; the presenter's explainers (stacking, the
   search, a comet the hunt recovered) run through the science.
5. **The night's result.** The end card, for two minutes, then the stream
   stops: the fields observed and their names, frames kept, mosaic panels
   searched and possible changes, counted from tonight's sessions; the
   sharpest focus tonight (`cache/focus_runs.jsonl`); the polar alignment
   from its first round to its last (`cache/polar_stream.json`); and what
   is next, the candidates still open for a person to check. A figure not
   found is left out.

## YouTube and Twitch at once

    [stream]
    enabled = true
    service = ["youtube", "twitch"]     # or "youtube+twitch", which the Settings screen writes

    ./stream.py key youtube        YouTube's key, into ~/.config/telescopeyoke/stream-key-youtube
    ./stream.py key twitch         Twitch's, into stream-key-twitch (optional: see below)
    ./stream.py                    lists each destination and whether it has a key

Each service has its own key file, readable only by you. The plain
`stream-key` (`./stream.py key`) is the key when there is one service, as
before; with several it still counts as the Twitch key when
`stream-key-twitch` is missing, because it held the Twitch key first. It is
never taken as YouTube's.

The picture is encoded once and sent to both through ffmpeg's tee muxer,
each destination with `onfail=ignore`: if one service drops the stream, the
other stays on air, and the dropped one joins again at the watcher's next
start. A service with no key is left out with one line saying so, and the
stream goes to the rest. ffmpeg's own messages reach the log with every key
taken out (its errors print a failing address whole).

Two streams need twice the upload: about 10 Mbit/s at 1080p. Twitch's
bandwidth test measures one stream, so it can pass when two do not keep
up; the stream then falls behind, and the sustained-trouble rule below
takes both down to 720p together. The Twitch title, category, tags and chat
work as before whenever Twitch is among the destinations. YouTube starts
and ends its broadcast itself when the stream key has Auto-start and
Auto-stop on.

The video is encoded by the laptop's own video hardware (Intel Quick Sync,
through VAAPI). At the start it runs Twitch's bandwidth test; it drops to
720p only on sustained trouble (a minute behind, dropped frames, or three
breaks in ten minutes), never on a blip.

### The voice

TelescopeYoke speaks now and then over the stream's sound (`narrator.py`):
a sentence when something happens, never a running commentary. On a target
reached ("I've reached the Moon."), a GoTo setting off, a stage begun
("I'm lining up and combining the sharpest frames now."), a result, and a
decision ("The Moon has drifted 73 pixels in the picture, so I'm
re-centring it before the next burst. The same part of the Moon has to stay
inside the camera's fast region."). With nothing happening, at most every 6
min, the mission and its open question. Never two within 20 s.

Every sentence is a template in `stream-targets.toml` (`[voice]`) filled
with the measured state: first person, calm, plain about what is not known.
The speech is made by gTTS (as the house alerts are), on its own thread,
and mixed into the same sound as the focus tones; if it cannot be made (no
network), nothing is said and the pictures never wait. `[stream] narration
= false` in config.toml turns it off; it takes effect when the stream next
starts.

## Clips of the big moments

Every moment of the night (a target reached, a stage begun, a result, a
decision, the stream going on air) is kept in `cache/events.jsonl` by the
director. While on air, ffmpeg also writes what it sends into a rolling
ten-minute buffer (`cache/stream-buffer/`, 10 s pieces, overwritten as it
goes). A minute after each moment, `clips.py` joins the pieces from 20 s
before it to 60 s after into `clips/DATE-TIME-WORDS.mp4`, without encoding
again. Moments less than a minute apart share a clip, and the newest 40
clips are kept. They are material for highlights, Shorts and a
"previously" at the start of the next night. `[stream] clips = false`
turns it off.

## The phones' picture (9:16)

`./stream.py frame --vertical` draws the 9:16 picture as
`cache/stream-vertical.jpg`, and `./stream.py scenes` draws each scene that
way too (`NAME-vertical.png`). It is simpler than the main picture: the
camera's picture large, the target, the mission, where it has got, its
open question and the live marker, with no figures or panel.

YouTube's vertical live shows it in the Shorts feed. Once its stream key is
kept (`./stream.py key youtube-vertical`, from YouTube Studio's vertical
live stream), `stream.py watch` sends it alongside the main feed whenever
that is on air. It has its own ffmpeg and its own drawing thread, so it
never holds up the main feed, and it stops with it.

## The chat

`streamchat.py` answers a few commands in the Twitch chat, from the same
curated words and measured figures, at most one reply every 3 s and each
command once in 30 s:

    !what  !target  !next  !focus  !polar  !telescope  !camera  !nova  !transit  !help
    !why  !progress  !result  !moon  !candidate  !vote TOPIC

`!focus` says what the focus run is doing (its stage, position, current and
best HFR against the start and the usual best) or how tonight's last one
ended; `!polar` how far tonight's polar alignment has got (picture n of 3,
waiting for an adjustment, the error now, the rounds and where it began, and
the drift limit it aims for). Both read the same files as the picture.

The mission's commands and `!vote` are described in docs/stream-look.md
("Chat"). Viewers can ask the observatory what it is doing and choose what
it explains next; nothing they type can move or change anything, and a
vote for a target is only passed on to the person. It needs the chat permissions, so `./stream.py
twitch-login` must have been run since they were added (20 October 2026).

## When something goes wrong

- It shows the wrong target or the wrong picture: `./stream.py director`
  says what it decided and what it left out and why, and `./stream.py
  frame --director` draws it. A wrong target is usually a GoTo made outside
  the project's commands: `./stream.py director --clear`, or a GoTo through
  `./ty mount goto`, puts it right.
- The picture freezes: the watcher logs a drawing error once and carries
  on; `journalctl --user -u ty-stream` shows it. Restart it after changing
  `stream-targets.toml`'s layout (on 20 October old code met new words and
  froze the picture for nine minutes).
- The stream key or the Twitch sign-in lapses: it says so once, and keeps
  imaging. Neither is ever written to a log.
