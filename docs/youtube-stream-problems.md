# YouTube stream: why it keeps not starting

Collected on 15 November 2026 from every chat session since the stream was
built (20 October), the commits and the code. Twitch has worked on almost
every one of these nights; YouTube has failed on at least seven.

## The short version

The laptop's side (picking the picture, encoding it, sending it) has mostly
worked. Most failures happened after that, on YouTube's side, where a
healthy incoming stream still has to become a **live broadcast** before
viewers see anything. Four separate things have stopped that, one after
another:

1. **No broadcast going live** (24 Oct to 2 Nov). YouTube got the video and
   showed "healthy", but the broadcast sat at "Preparing stream" or
   "ready", or had already ended.
2. **Dual stream switched on** in YouTube Studio (30 Oct and 1 Nov). Both
   previews hung on "Preparing stream".
3. **The broadcast only starts when a stream begins.** A broadcast opened
   while the stream is already running stays at "ready", and YouTube
   refuses to start it by hand (`403 invalidTransition`). The encoder has
   to be restarted. This happened on 2 Nov and again tonight, 15 Nov.
4. **The Google sign-in expired** (15 Nov). The laptop needs that sign-in
   to open a broadcast each night, and Google answered "Token has been
   expired or revoked".

On top of those, I (Claude) said "it's live" several times without looking
at the channel page, so the user ended up finding the failures. On
2 November they said this was the fourth night in a row they'd had to ask.

## Night by night

| Date | What the user saw | What was really wrong | What was done |
|---|---|---|---|
| 21 Oct | Asked if we were live on YouTube | Only Twitch was set up; no YouTube key | The user got the stream key from Studio; streaming to both started 21 Oct (23afa55) |
| 22 Oct | "you told me twitch and youtube would start when the patrol starts" | It went on air only with the first kept frame, which came late after a 7° GoTo miss | Nothing; it started once frames came in |
| 24 Oct | Moon on Twitch, not on YouTube | The stream stopped after 2 quiet minutes during each move. Every restart made YouTube start a **new broadcast**, so the open page was an old one. Studio said "not connected" until a new run started | Gave the channel's `/live` link. Not fixed: the stream still stopped between steps |
| 24 Oct, later | Nothing on 8080, YouTube or Twitch | The lucky-imaging Moon video didn't count as "imaging", so the stream turned itself off | Started a normal run; then made Moon videos keep the stream on air (f3b4151) |
| 30 Oct | "still seeing noting on youtube or twitch … stop calling me a liar" | I said three times that it was going out, based on bytes leaving the laptop. Studio: health "Excellent" but both previews stuck on "Preparing stream" since 02:07; the channel never went live. **Dual stream (New)** had been switched on | Apologised; suggested turning Dual stream off. Not done that night |
| 1 Nov | "how come i can never see the live stream on youtube?" | Same thing: ingest connected, broadcast `isUpcoming`, "This live event will begin in a few moments", Dual stream still on | Dual stream switched off at 23:02; **live at 23:05**. Keyframes set to every 2 s. "Keep Dual stream off" written into `docs/streaming.md` (fa1267b). The YouTube API sign-in was set up the same night (23:47) |
| 2 Nov | "i think this is the 4th night in a row i have had to ask why i cant see anyting on youtube" | YouTube **ends a broadcast** when the stream pauses (the stream stopped after 5 quiet minutes at 19:03) and doesn't open a new one. Every broadcast on the channel was "complete" | `youtube.py` opens a broadcast when there is none (92ede92); broadcasts are made with auto-stop off so a pause doesn't end them. Then found the auto-start problem (point 3 above), so the broadcast is now opened **before** the stream starts sending (`open_youtube_first`) |
| 2 Nov | YouTube title still said "Nova hunt" | The user was on the ended broadcast; a restart for testing had made a new one | Use `youtube.com/@TelescopeYoke/live`, which always goes to the current one |
| 4 Nov | "https://www.youtube.com/@TelescopeYoke still says im live" | After the night ended (05:24) the stream went **back on air three times** because post-night processing (restack, patrol sweep, depth runs) looked like a run. The last broadcast was left open | Only a capture makes a run current; every stop ends the YouTube broadcast (132ca6d); `./stream.py youtube-end` added (a02372e) |
| 12 Nov | (Asked for) stream off during cloud watching | The cloud watch's frames put the stream on air | Cloud-watch frames no longer count (6b54a72) |
| 13 Nov | "streams dont sem to be running" | The AMD graphics card hung when the laptop woke from sleep at 22:04; the stream's start-up test of the card got stuck | Falls back to encoding on the processors (3518785). **I said "YouTube and Twitch went live again at 23:20" without checking the channel page** |
| 15 Nov | "youtube stream does not seem to be up", then "still not seeing anything on youtube" | Laptop sending fine since 19:50. Google refused the sign-in (`invalid_grant: Token has been expired or revoked`), so no broadcast was opened | 87b18fd: a refused sign-in is now noticed and a google.com/device code goes to Telegram every 30 min. The user's code wasn't used in time, so I approved it in Chrome at 21:03. The broadcast then sat at "ready" (point 3 again) until **I restarted the encoder at 21:10; live within a minute** |

## Still open

- **The sign-in will probably expire again.** On 1 November the OAuth app
  was set up in Google Cloud project **`telescopeyoke`** as a "Testing" app
  (that night's message to the user: "your own app in testing").
  Google ends a Testing app's sign-ins after 7 days. Tonight's
  check of the consent screen, which showed "In production", was on a
  **different project** ("My First Project", `sage-ace-178811`), so it says
  nothing about ours. The fix: Google Cloud console, project
  `telescopeyoke`, Google Auth Platform, Audience, **Publish app**, then
  sign in once more (a sign-in made while the app was in Testing still
  expires). Until that's done, expect it to expire about 22 November.
  It isn't proven that Testing is the cause. The record doesn't show when
  the sign-in actually expired: it was made on 1 November and wasn't
  checked between 4 and 15 November.
- **A broadcast opened mid-stream still needs an encoder restart.** When the
  sign-in comes back while the stream is already running (tonight's
  case), `ensure_broadcast` opens a broadcast, YouTube refuses to start it
  (`403 invalidTransition`) and it waits at "ready" for the next stream
  start. 87b18fd doesn't restart the encoder after the phone sign-in. The
  stream should restart its ffmpeg itself once it has opened a broadcast
  that's sitting at "ready" (a few seconds' gap on Twitch).
- **The phone sign-in needs someone to act within 30 minutes.** Google
  won't let the laptop approve its own sign-in, so the best the laptop can
  do is send a code. That's the reason publishing the app matters.
- **"Sending" was taken for "live".** Several times the evidence was
  ffmpeg's progress, open connections, or Studio's "healthy". None of
  those means viewers can see it. The only check that counts is the public
  `youtube.com/@TelescopeYoke/live` page reporting `isLiveNow: true`.
  `YouTubeCheck` in `stream.py` now asks YouTube every 5 minutes and sends
  a Telegram message after 10 minutes with no live broadcast. Check it
  actually fires next time.

## Checks when YouTube is blank

1. `./youtube.py status`: is it signed in, is the stream "active / good",
   and is a broadcast `live`, or only `ready`, `testing` or `complete`?
2. "Not signed in" or `invalid_grant`: sign in again
   (`./stream.py youtube-login --client ~/.config/telescopeyoke/youtube-client.json`,
   or the Telegram code).
3. A broadcast at `ready` while the stream is active: restart the stream's
   encoder so YouTube sees a new stream start.
4. Stuck on "Preparing stream": check Dual stream is still off (Studio,
   Live, Stream settings).
5. Only call it live once `youtube.com/@TelescopeYoke/live` reports
   `"isLiveNow":true`.

The link to bookmark is **https://www.youtube.com/@TelescopeYoke/live**.
Each broadcast gets its own `watch?v=` address, so an old one goes stale
after any restart.
