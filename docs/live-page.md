# The public live page and the live stream

The telescope is public in two places while it works:

- **https://ryanclinton.uk/astrophotography/live/**, the person's own site.
  It went live on 20 October 2026.
- **Twitch** (and YouTube once its streaming check clears), sent by
  `stream.py`. It went live on 20 October 2026 at 01:20 UTC, on the WASP-12 b
  transit, and in its 1080p look from 01:43 UTC. The picture it sends is
  described in [stream-look.md](stream-look.md).

Both show what the status page (`serve.py`, port 8080) shows. Neither ever
shows where the telescope is: no site name (`serve.unplaced()` blanks it in
every `/api/v1` answer), no cloud map, no weather, and no webcam (all webcam
features are off unless switched on, `[webcam]`).

## The live page: what runs, and where

The site's own code builds and serves the page. This laptop never builds
or deploys the site. On the laptop, the site's piece lives outside this
repository:

- `ryanclinton-live.service`, a systemd user service, runs
  `~/ryanclinton-live/live_client.py`.
- The client opens an SSH tunnel whose key can reach only the site's relay
  port: no shell, no files. It sends changes over a websocket. The relay
  checks every field again, so neither end trusts the other.
- It sends pictures as WebP: the stack at 1600 px, and every third newest
  frame at 1200 px.

## What it reads from telescopeyoke (a contract)

The client reads these every second. Renaming or removing any of them
breaks the public page, so change them only together with the site:

| From | Fields |
|---|---|
| `web/status.json` | `name`, `title`, `age` (a run counts as live only while its newest frame is under 300 s old), `planned`, `captured`, `accepted`, `rejected`, `exposure`, `integration`, `finished`, `reasons`, `series` (`fwhm`, `stars`, `drift`, `accepted`), `schedule.steps` (`label`, `status`, `start`, `end`), `discovery` |
| `web/stack.jpg`, `web/latest.jpg` | the running stack and the newest frame |
| `http://127.0.0.1:8080/api/v1/night`, every 10 minutes | sunset, sunrise, darkness, moon, the clear window, sky brightness |

`tests/test_stacking.py` and `tests/test_schedule.py` check that the run's
fields and the schedule's fields are still there.

Anything added to `status.json` may reach the public page (`discovery` is
sent as it is), so keep everything in it fit to publish.

## The Twitch channel's title, category and tags

`twitch.py` sets them each time the stream starts and each time it moves to a
new target. A transit gets "Live telescope: timing a transit of the exoplanet
WASP-12 b, as it happens | TelescopeYoke", a patrol names the galaxy, and a
picture names its object. The category is always Science & Technology, and
the tags are Astronomy, Telescope, Space, Science and Astrophotography, plus
Exoplanet, or Nova and Galaxy, as the programme suits.

- **The app**: "TelescopeYoke", registered at dev.twitch.tv on 20 October
  2026 as a public client, with the redirect URL `http://localhost`. Its
  client ID is in config.toml as `[stream] twitch_client_id`. It is not a
  secret, and there is no client secret anywhere.
- **The sign-in**: `./stream.py twitch-login` asks Twitch for a device code,
  and the person approves it at twitch.tv/activate. It grants only
  `channel:manage:broadcast`. The tokens are kept in
  `~/.config/telescopeyoke/twitch.json`, readable only by the person, and are
  never shown. A public client's sign-in lasts while it is used at least once
  a month. When it has lapsed, the stream's log says to sign in again.
- **Failures** never stop the stream: the channel keeps the info it had.
