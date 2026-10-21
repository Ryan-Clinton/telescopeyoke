# The live stream: running it

What exists and how to run it. Why it looks the way it does, and what is
still to come, is in [stream-look.md](stream-look.md), the design record.

On air since 20 October 2026 on Twitch, from the WASP-12 b transit run
(`docs/validation.md`, "Live stream on Twitch"). YouTube is built as a
destination, alone or beside Twitch, and not yet tried on air.

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
air when a run's newest frame is under two minutes old, stays on air between
targets when the schedule's next step is due within 15 minutes, holds the
end-of-night card for two minutes, and stops when no frame has come for
five. For each target it sets the Twitch title, category and tags.

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

    !what  !target  !next  !telescope  !camera  !nova  !transit  !help

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
