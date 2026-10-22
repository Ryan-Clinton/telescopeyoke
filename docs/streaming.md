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
- a card between targets (the next target, a checklist of the GoTo, plate
  solve, focus and imaging) and one at the end of the night;
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

It is off unless `[stream] enabled` in `config.toml` (the Settings screen),
with `[stream] service` "twitch", "youtube" or "custom", or several of them
(below). The watcher goes on
air when a run's newest frame is under two minutes old, or while the
telescope is focusing or being polar aligned (below); stays on air between
targets when the schedule's next step is due within 15 minutes, holds the
end-of-night card for two minutes, and stops when nothing new has come for
five. For each target it sets the Twitch title, category and tags.

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

## The chat

`streamchat.py` answers a few commands in the Twitch chat, from the same
curated words and measured figures, at most one reply every 3 s and each
command once in 30 s:

    !what  !target  !next  !focus  !polar  !telescope  !camera  !nova  !transit  !help

`!focus` says what the focus run is doing (its stage, position, current and
best HFR against the start and the usual best) or how tonight's last one
ended; `!polar` how far tonight's polar alignment has got (picture n of 3,
waiting for an adjustment, the error now, the rounds and where it began, and
the drift limit it aims for). Both read the same files as the picture.

Viewers can ask the observatory what it is doing; nothing they type can move
or change anything. It needs the chat permissions, so `./stream.py
twitch-login` must have been run since they were added (20 October 2026).

## When something goes wrong

- The picture freezes: the watcher logs a drawing error once and carries
  on; `journalctl --user -u ty-stream` shows it. Restart it after changing
  `stream-targets.toml`'s layout (on 20 October old code met new words and
  froze the picture for nine minutes).
- The stream key or the Twitch sign-in lapses: it says so once, and keeps
  imaging. Neither is ever written to a log.
