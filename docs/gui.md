# A control console: specification

This is a work order for an agent (or a person). The aim is that someone who
is used to pressing buttons in NINA or SharpCap can run a night with
telescopeyoke without typing commands, on Windows or Linux.

Read `AGENTS.md` and `docs/agents/safety.md` first. Their rules apply to all
of this, and this document changes one of them deliberately (see "The rule
this changes").

## What was decided, and why

**A page in the browser, served to this computer only, by a new small
program `console.py`.** Not a desktop toolkit, and not controls added to the
existing status page.

| Option | Verdict |
|---|---|
| Controls on the existing page (`serve.py`) | No. That page is served to the whole home network with no login, and must stay read-only. |
| Tkinter | No new dependency, but a second look to maintain, poor at showing live pictures, and none of the existing page can be reused. On Ubuntu it is a separate package. |
| Qt (PySide6), NiceGUI, Flet, pywebview | Each is a large dependency or a framework. `CONTRIBUTING.md` rules those out. |
| **A local page from the standard library's `http.server`** | Chosen. No new dependency, the same on both systems, reuses the status page's pictures and JSON, and Windows users already have a browser. |

**The console runs the existing commands; it contains no telescope logic.**
Each button starts one of the project's scripts as a separate process with
`--json`, exactly as a person would type it. So the console cannot do
anything the command line cannot, every limit and the `MOTION_LOCKED` file
apply unchanged, and there is still one implementation.

**It does not replace the status page.** `serve.py` stays as it is: read
only, on the home network, for watching the night from indoors or a phone.
The console is for the person beside the telescope. Two programs with two
jobs is the design, not a stage on the way to one.

**It is built around what the person is doing now,** not a status page with
buttons added and not a wall of every control. The picture or the task is in
the middle, the state of the equipment is round the edge, and only the
controls that make sense in the present state are shown. The project is
small; the console should look it.

## The rule this changes

`AGENTS.md` says the web server and the MCP server are read-only and that
nothing which moves the mount may be added "without authentication designed
first". That stays true of `serve.py` and `mcp_server.py`: do not touch them.
The console is a third program, and this is its design:

1. **This computer only.** It listens on `127.0.0.1` and nowhere else. There
   is no option to listen on the network in this version. The person
   pressing the button is at the computer beside the telescope.
2. **A key made at start-up.** `console.py` makes a random key each time it
   starts, opens the browser at `http://127.0.0.1:PORT/?key=...`, and keeps
   the key in memory only. Every request that does anything must carry it in
   a header. A request without it gets 403. The page reads the key from the
   address once, keeps it for that browser tab (in `sessionStorage`, so that
   reloading the page still works; it is gone when the tab is closed), and at once rewrites the address
   without it (`history.replaceState`), so the key is not left in the
   browser's history, a bookmark, a copied address or a screenshot.
3. **Not reachable from other web pages.** Refuse any request whose `Host`
   header is not `127.0.0.1:PORT` or `localhost:PORT` (this stops DNS
   rebinding), and any action whose `Origin` header is present and is not
   the console's own. Send no CORS headers. Actions are `POST` only; `GET`
   never changes anything.
4. **The browser is told to trust nothing else.** Every response carries:

   ```
   Content-Security-Policy: default-src 'self'; img-src 'self' data:;
       style-src 'self'; script-src 'self'; connect-src 'self';
       frame-ancestors 'none'; base-uri 'none'; form-action 'self'
   X-Frame-Options: DENY
   X-Content-Type-Options: nosniff
   Referrer-Policy: no-referrer
   Cache-Control: no-store
   ```

   So the page has no inline scripts or styles, loads nothing from the
   internet, and cannot be shown inside another page. That rules out even
   `style="display:none"` on one element and a `<script>` block in the
   page: everything shown or hidden is done with classes, and all the
   JavaScript is in `console.js`. Because nothing is cached, a picture is
   fetched again with a plain request; no made-up query strings.
5. **A person confirms each move, on a plan.** Pressing anything that moves
   the mount first runs the command with `--dry-run` and shows the plan (see
   "The move plan"). The mount moves only when the person presses the
   confirm button on that plan. A refusal is shown with its message and
   advice, and offers no way round. Something that goes on moving the mount
   by itself afterwards (an imaging run that re-centres, the horizon survey,
   drift compensation) says so on its plan, in plain words, and the one
   confirmation covers it. What the person agrees to is a behaviour with
   stated bounds ("may re-centre M27 when it has drifted more than 20% of
   the frame"), not each motor command; a run must never stop to ask again
   while nobody is watching.
6. **Stop is always there.** A Stop button is on screen at all times, needs
   no confirmation, and works whatever else is running.

Be honest in the docs about what this does not do: a program running on the
same computer, including an agent, can start `mount.py` itself, as it can
today. The console adds no new way for an agent to move the mount, and
removes none. The approval design in `docs/agents/safety.md` is still not
built.

## How it works

```
browser (this computer) ── POST /api/plan/goto ──► console.py ── starts ──► python mount.py goto M27 --dry-run --json
        ▲                  POST /api/confirm/ID                              python mount.py goto M27 --json
        └────── GET /api/job (progress, result) ───┘◄── stderr lines, stdout envelope
```

- **One job at a time.** `console.py` holds at most one running job that
  uses the mount or the camera. A second request while one runs is refused
  with a message naming the job ("Camera busy: focusing"). Read-only
  requests are never blocked. This is the rule, not a first version of
  something cleverer: do not let jobs share the camera or the mount, queue
  behind one another, or run side by side.
- **Progress.** With `--json` each script prints progress on stderr and one
  envelope on stdout. The console keeps the stderr lines for the activity
  log and shows the envelope's result or error when the job ends.
- **Fixed commands only.** The console holds a table of the actions it
  offers (the tables under "The screens") and builds each command as a list
  of arguments. A target name must be one the catalogue knows
  (`mount.find_target`); numbers are checked against a range; a session
  folder must be one that exists under `frames/`. The browser never sends a
  command line, and nothing from it reaches a shell.
- **Stop.** On Linux, `mount.py stop` can open the serial port while a slew
  is running. **On Windows a COM port can be opened by one process only**,
  so the console must end the running mount job first, then run
  `mount.py stop`. Do it that way on both systems. Measure how long Stop
  takes from press to the handset's reply and show it in the log; the aim is
  under two seconds. This cannot be proven against the simulator, so it is
  on the hardware check list below.
- **Finishing a job is not Stop.** They are two different things in the job
  runner:
  - *Finish* (focusing, a camera test, calibration): ask the script to end
    as Ctrl+C would, so it closes the camera properly; wait a few seconds;
    kill it only if it has not gone. How a process is asked differs between
    Linux and Windows and belongs in `host.py`. A camera left open by a
    killed job can refuse the next one, so test that a second job starts
    after the first is finished this way.
  - *Stop*: end whatever holds the mount at once, without waiting, then run
    `mount.py stop`. In this order, exactly:
    1. Mark the job as being stopped by Stop.
    2. From that moment nothing may start or restart a job that opens the
       mount: no retry, no recovery, no queued confirm. Only `mount.py stop`.
    3. Kill the process that holds the serial port.
    4. Wait only until the system says that process has gone.
    5. Start `mount.py stop` at once.
    6. Report the time from the press to the handset's reply.

    The ban in step 2 lasts until `mount.py stop` has answered. A job runner
    that helpfully reopens the mount while Stop is under way would defeat it.
- **An imaging run** is finished with `ty run stop`, which lets it make its
  picture. Stop stops the mount; "Finish run" sends the order.
- **Closing the browser stops nothing.** Jobs belong to `console.py`. Closing
  `console.py` ends its running job and sends the mount a stop.

### Routes

`GET` routes only read. Each returns the project's usual envelope.

| Route | Answers from |
|---|---|
| `GET /api/state` | `agent.status`, `agent.capabilities`, the running job, the lock: everything the frame of the page needs, in one request |
| `GET /api/night`, `/api/targets`, `/api/target/NAME` | `agent.night`, `agent.targets`, `agent.target` |
| `GET /api/observing` | `agent.observing` |
| `GET /api/session` | `agent.session`, with the per-frame series |
| `GET /api/doctor` | `doctor.report` |
| `GET /api/job` | the running or last job: its name, progress lines, result |
| `GET /pictures/NAME` | the pictures in `web/` (`latest.jpg`, `stack.jpg`, `scope.jpg`) |

| Route | Does |
|---|---|
| `POST /api/plan/ACTION` | runs the action's dry run; returns the plan and a plan id |
| `POST /api/confirm/ID` | makes the plan again, and starts the job only if it is unchanged (see "The move plan"). An id works once, for the command it was made for, for two minutes |
| `POST /api/action/ACTION` | starts an action that does not move the mount |
| `POST /api/stop` | ends the mount job and stops the mount |

`ACTION` is a name from the console's table, never a script name or a path.

### Files

```
console.py              the server: key, checks, jobs, the table of actions
console/index.html      the one page
console/console.css     the whole look, both themes
console/console.js      navigation, polling, dialogs, sparklines
console/icons.svg       the few icons, as one sprite
```

Plain HTML, CSS and JavaScript. No npm, no bundler, no JavaScript library,
no framework. These files are part of the repository, so they go in a new
`console/` folder: `web/` is generated at run time, ignored by git, and
served to the whole network by `serve.py`, so nothing of the console may be
put there.

## The look

### The frame

The frame stays put; the middle changes with the task.

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ TELESCOPEYOKE  My back garden   ● GO · clear to 01:10       22:47   [ STOP ] │
├────────┬───────────────────────────────────────────┬─────────────────────────┤
│ Home   │                                           │ M27  Dumbbell Nebula    │
│ Targets│                                           │ ● IMAGING               │
│ Mount  │                                           │ 127 / 300               │
│ Focus  │                WORK AREA                  │ █████████░░░ 42%        │
│ Imaging│          newest frame or stack            │ 218 s kept · 87% kept   │
│ Tools  │                                           │                         │
│ System │                                           │ [ Finish ] [ Re-centre ]│
├────────┴───────────────────────────────────────────┴─────────────────────────┤
│ Mount TRACKING · Camera CAPTURING · Solver READY · FWHM 3.4 · 74 stars       │
│ ▸ 22:47:11  centred M27 to 1.8′                                    3 new  ︿ │
└──────────────────────────────────────────────────────────────────────────────┘
```

- **Top bar:** the name, the site's name from `config.toml`, tonight's
  verdict and clear window, the mount's and camera's state, the clock, and
  Stop. Always visible. Started with `--demo` it also shows **DEMO: no real
  telescope is being controlled**, plainly, so that neither the person nor a
  screenshot can mislead.
- **Left:** seven tasks, not seven scripts: Home, Targets, Mount, Focus,
  Imaging, Tools, System. Switching shows and hides sections of the one page
  with no reload. The address carries the task (`#home`, `#targets`, ...) so
  the browser's back button works.
- **Right:** one panel whose contents depend on the state (below).
- **Bottom:** one line of states and the newest measurements, and the
  activity log, folded to one line until opened.

**Measurements go stale.** FWHM, star count, drift, the focus reading and
the last plate solve are shown bare only while the job that makes them is
running. After that each carries its age ("FWHM 3.4 · 2 min ago"), and
after ten minutes it is taken off the bar. A number from twenty minutes ago
must never look like now.

### The right-hand panel

The same place, a different purpose in each state:

| State | Shows | Buttons |
|---|---|---|
| Idle | "No run". The best target now, its height and direction | Go to it, Start imaging |
| Moving | where it is going, height now and at the end, seconds so far | Stop |
| Focusing | the HFR, large; improving or worsening; tonight's best | Finish |
| Imaging | target, frames of those planned, a bar, seconds kept, share kept | Finish run, Re-centre |

### Restraint

This should look like an instrument, not a business dashboard. One dominant
work surface. Space, thin rules and the size and weight of type do the
grouping; a box is drawn only round a real group, never a box inside a box,
and not every number gets one. Corners rounded by 6 to 8 pixels at most. No
gradients, no shadows for decoration. The picture in the work area has no
frame at all, and the controls beside it are visibly secondary to it.

No emoji anywhere in the interface: they look different in every browser and
system. Icons come from `console/icons.svg`; otherwise use words or shapes
drawn in CSS.

### Type

No web font. The system's own:
`font-family: Inter, ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif`.
Numbers use `font-variant-numeric: tabular-nums` so they do not jiggle as
they change; only the activity log is monospace (`ui-monospace`).

### Screen size

Built for a laptop: it must work fully at 1366 × 768, and from 1280 × 720
up. Narrower than that, the navigation shrinks to icons and the right-hand
panel drops below the work area. Nothing is done for phone widths.

### Colour

Dark charcoal background, off-white text. Colour carries meaning and nothing
else: green for working and healthy, amber for warnings and for a plan
waiting to be confirmed, red for Stop and for faults only, and one muted blue
for ordinary buttons. No other button colours, so Stop cannot be mistaken.

### Night vision

A switch in the top bar puts one class on `<body>`: near-black background,
deep red and warm amber text, no blue anywhere, much lower brightness. A
second switch, "Dim pictures", shows frames and stacks at low brightness
until the pointer is on them: a bright stretched picture appearing does more
harm to dark-adapted eyes than any menu. Both switches are remembered in the
browser.

### Controls follow the state

Show what can be done now, not everything that exists.

| State | Main controls shown |
|---|---|
| Idle | Go to, Focus, Start imaging |
| Slewing | Stop |
| Focusing | Finish focusing |
| Imaging | Finish run, Re-centre, Drift assist on/off |

A control that cannot be used now is shown disabled **with the reason beside
it**, taken from `agent.capabilities` and the doctor's messages, for example
"Start imaging: ASTAP star database not found". Never a bare grey button.

### Notices

Things that finish or go wrong raise a small notice at the edge that fades:
"M27 centred to 1.3′", "Imaging started", "Focus has worsened", "Camera
disconnected". The warnings come from the note in `agent.observing`. A dialog
that blocks the page is used only when a person has to decide something,
which means the move plan.

### Three outcomes, three names

The page and the log keep these apart, in words and in colour:

| Outcome | Example | Shown as |
|---|---|---|
| Plan refused | "M27 is only 12° up; not slewing." | amber: nothing was started |
| Job failed | "Camera disconnected during focusing." | red: something went wrong |
| Job finished | "Focusing ended." | plain: it did what was asked |

A refusal is the limits working, not a fault, and must not look like one.

### The activity log

Folded, it shows the newest line and a count of unread ones. Open, it shows
the progress lines of recent jobs in plain words with their times. A "Show
technical details" switch shows the scripts' raw output and the JSON
envelopes, for finding faults.

### Keys

`G` targets, `F` focus, `I` imaging, `L` the log, `Esc` closes a drawer or a
plan. They do nothing while the cursor is in a text box. **No key moves the
mount**, and Confirm on a plan is never the focused button when the plan
opens, so Enter cannot move it by accident. `Ctrl+Shift+Space` is Stop.

## The move plan

Never the browser's own `confirm()` box. A card in the middle of the page:

```
┌───────────────────── MOVE PLAN ─────────────────────┐
│               M27  Dumbbell Nebula                   │
│                                                      │
│  Now                      Going to       [ webcam  ] │
│  Az 192°  Alt 48°         Az 221°        [ picture ] │
│                           Alt 61°                    │
│  Hour angle  +0.42 h      Side  WEST                 │
│                                                      │
│  ✓ Above the 20° altitude limit                      │
│  ✓ Within 5.75 h of the meridian                     │
│  ✓ 94° from the Sun                                  │
│  ⚠ The tube will swing over the pole.                │
│                                                      │
│              [ Cancel ]        [ GO TO M27 ]         │
└──────────────────────────────────────────────────────┘
```

- Everything on it comes from the dry run's answer and from
  `agent.capabilities`' limits. Warnings are shown in the script's own words.
- The webcam's newest picture of the telescope is shown beside the plan when
  there is a webcam, with its age. It does not make the move safe; it lets
  the person look before agreeing.
- The same card, with different words, is used for Home, Zenith, Compensate,
  starting an imaging run, the horizon survey and polar alignment. For
  those that keep moving the mount afterwards the card says so: "This run
  re-centres the mount by itself as the target drifts", "This moves the
  mount all over the sky, over the pole and back, for about an hour".
- A refusal uses the same card with no confirm button: the message, the
  advice, and Close.
- **Confirm makes the plan again before anything moves.** A plan describes
  the world when it was made, and the sky and the mount move on. The plan id
  holds the action, its parameters and when it was made. On Confirm the
  console runs the dry run once more. If the answer is the same in what
  matters (allowed, the side of the mount, the warnings, and height and hour
  angle within a degree) the job starts. If not, nothing moves: the page
  says "The situation has changed. Look at the new plan", shows the new
  plan, and gives it a new id to confirm.

Starting an imaging run says when and why the mount will move, not just that
it will. `shoot.py` centres the target before the first frame and re-centres
when the drift passes 20% of the frame, so the card reads:

```
START IMAGING M27

Before imaging
  The telescope slews to M27, plate-solves and centres it.
During imaging
  It may re-centre M27 when it has drifted more than 20% of the frame.
  Drift assist will adjust the Dec motor.          (only if switched on)
Capture
  300 frames · 2 s each · gain 1500

            [ Cancel ]        [ START M27 ]
```

With re-centring switched off the first two parts read "The mount will not
be moved", and the card needs no move confirmation.

## The screens

In the tables, **Moves** means the action goes through the move plan.

### Home: what to do now

Tonight's verdict, large. The clear window as a bar with "now" marked. The
Moon: how full, when it sets. The best target now as a card with its score,
kind, height and direction, best time, and "Details" and "Go to"; the next
few as one line each. All from `agent.night` and `agent.targets`.

Above it, one card from `agent.observing`, and it deserves care: it is what
this project knows that a plain hardware controller does not. Either
"Everything looks good", with the reasons (centred, focus near tonight's
best, most frames kept), or "Attention":

```
ATTENTION   Focus appears to be slipping.

HFR          3.3 → 4.6
Star count   72 → 70    steady
Tracking     steady

Likely focus, not cloud or tracking.            [ Start focusing ]
```

It shows the measurements that moved and the ones that did not, the likely
cause in the words `agent.observing` already gives, and one button for the
remedy: Start focusing for focus, "Look at the newest frame" for cloud. It
is plain diagnosis from numbers already measured; it must not claim more
than the note does. "Focus is the most likely cause: stars are wider while
their number and the drift are steady" is right. "Your focuser has slipped"
is not: the console cannot know that.

### Targets

A search box over the **whole catalogue**, not only tonight's ranked list: a
name, a second designation or a common name finds a target, as
`mount.find_target` already allows ("M27", "Dumbbell", "NGC 6853", "Vega").
Results are in two groups, "Best tonight" and "Catalogue". Something ranked
low, or not at all, can still be chosen; whether the mount may go there is
for the plan to say. Filters: up now,
galaxy, nebula, cluster, planet. Choosing one opens its details: score,
direction, best time, window and tags from its entry in `agent.targets`;
height now, and whether a GoTo is allowed now and if not why, from
`agent.target`. Nobody has to remember how a name is spelled.

| Control | Runs | Moves |
|---|---|---|
| Go to | `mount.py goto NAME` | yes |
| Centre with plate solve | `mount.py goto NAME --solve` | yes |

### Mount

Not a joystick. The state, position (RA, Dec, height, bearing), side of the
mount, the lock and the limits; the age of the last plate solve and the
pointing error it found; the drift model: the natural Dec drift, the
correction applied, what is left.

| Control | Runs | Moves |
|---|---|---|
| Go to target | opens Targets | |
| Home | `mount.py home` | yes |
| Zenith | `mount.py zenith` | yes |
| Sync from plate solve | `mount.py sync` | no (camera only) |
| Measure drift | `mount.py drift` | changes the Dec motor's creep: plan card |
| Compensate | `mount.py compensate` | yes |
| Read position | `mount.py status` | no |

If `MOTION_LOCKED` exists, the moving controls are disabled with the lock's
reason. The console never creates or removes the lock.

### Focus

A mode of its own, with almost nothing on it: the star, the HFR as a very
large number, whether it is improving or getting worse, tonight's best, a
short trail of the last readings, and the advice in the script's words
("minimum passed: turn back slightly", "best focus"). The readings come
from the file `focus.py` already writes; the trail is the readings the page
has seen since the aid started.

| Control | Runs | Moves |
|---|---|---|
| Start focusing (speech, tones or silent, chosen here) | `focus.py`, with `--tones` or `--quiet` | no |
| Finish focusing | ends the job | no |

Speech and tones are options the script is started with, so changing the
choice restarts the aid.

### Imaging

The richest screen. The picture in the middle with a switch between the live
stack and the last exposure (`web/stack.jpg`, `web/latest.jpg`), both side
by side on a wide screen. On the right the target, the state, frames taken of
those planned with a bar, seconds kept, share kept, exposure and gain. Below,
four measurements each with its newest value, a word (good, fair, poor) and a
sparkline from the run's series: FWHM, roundness, star count, drift. Then the
reasons frames were rejected, as counts. All from `agent.session` and
`agent.observing`.

Starting a run opens a sheet at the side, not a form page: target, exposure
(auto, or 1 to 4 s), frames, gain, re-centre on or off, drift assist on or
off. It shows the exposure time that would be kept and an estimate of how
long the run will take, worked out from the time between frames in the
newest saved run with this camera. With no earlier run it says the time is
not known yet; it does not guess.

| Control | Runs | Moves |
|---|---|---|
| Start run | `shoot.py NAME --frames N --exposure E --gain G`, with `--assist`, `--no-recentre` as chosen | yes, unless re-centre is off |
| Finish run | `ty run stop` | no |
| Re-centre | `ty run recentre` | the run moves the mount; it was agreed when the run started |
| Drift assist on / off | `ty run assist-on` / `assist-off` | changes the Dec motor's creep |

### Tools

The technical jobs, out of the way of a normal night. Each is one line with
what it does and a button.

| Group | Control | Runs | Moves |
|---|---|---|---|
| Alignment | Polar alignment measurement | `polaralign.py` | yes |
| | Horizon survey (grid, or follow the skyline; by night or by day) | `horizon.py`, with `--trace`, `--daylight` | yes |
| Camera | What the camera is | `camera_test.py --capabilities` | no |
| | Throughput | `camera_test.py --throughput` | no |
| | Gain sweep | `camera_test.py --gain-sweep` | no |
| Calibration | Dark, flat, bias frames | `calibrate.py dark\|flat\|bias` | no |
| Processing | Restack the last session | `restack.py NAME` | no |
| | Combine sessions | `restack.py NAME --all`, or chosen session folders | no |

Two of these get a picture for a result:

- **Polar alignment:** a small diagram of the pole and where the mount's
  axis really points, the total error, and for each of the two adjustments
  which way it is off and which way to turn the mount ("1.4° west: move the
  mount east"; "0.8° high: lower it"). No jargon unless a line is opened.
  Beneath it, what happens if it is left alone: the Dec drift the model in
  `tracking.py` predicts near the current target, and that the project can
  cancel most of that drift but not the slow turning of the field.
- **Horizon survey:** the skyline as a plot, height against bearing round
  from north, with what is blocked filled in. It is drawn from
  `cache/horizon.json` and from the `blocked` list in `config.toml`. On the
  Targets screen the chosen target's height through the night is drawn
  against it, with the altitude limit as a line and the moment it "clears
  the roof" marked: when it can really be seen from this garden, which
  height alone does not tell.

### System

The doctor's checks as a list with a tick, a warning or a cross each; a line
opens to show the doctor's advice. Disk space. "Check again" runs the
doctor.

Under Camera: model, sensor size and bit depth, how frames are fetched (INDI
or Altair's library), the USB link, the readout speed; and for a stated
exposure the time to deliver a frame, the whole cycle and the share of the
time spent exposing, from the last throughput test, with its date. A
"Benchmark" button runs the test again, so a different lead, port or
setting can be judged by its numbers.

## Small changes the scripts need first

The console only shows what the scripts report. These are additions; none
changes what a command does.

1. **Dry runs where they are missing.** `polaralign.py` has no `--dry-run`
   and no `--json`; it needs both before the console may offer it. Check
   `mount.py drift --dry-run`: it says nothing would move, which is true of
   the tube but not of the Dec motor's creep; the plan must say the creep
   will change.
2. **More on the plan.** `mount.py ... --dry-run` should also give the
   target's bearing and its distance from the Sun, so the plan card can show
   them. Where the mount is now comes from `mount.py status`, asked for only
   when no job holds the mount.
3. **What sets a target's window.** For "M31 clears your roof at 23:48",
   `agent.target` needs to say whether the start of the window is set by the
   altitude limit or by the blocked horizon. Until it does, the console does
   not say it.
   Drawing a target's height through the night needs the planner to give
   that curve, which it works out but does not report.
   The same goes for a target's distance from the Moon: the planner uses it
   in the score but does not report it, so the console shows it only once
   `agent.targets` does.
4. **Camera test results.** `camera_test.py` prints its results and keeps
   nothing. To show the last measured throughput on the System screen it
   needs to save them under `cache/`.

Each of these comes with its test, and the schemas kept in step.

## Launching

- `./console.py` on Linux, `python console.py` on Windows, and `ty console`
  on both. It prints the address and opens the browser.
- `--demo` drives the simulated mount and the made-up imaging run, so the
  whole console can be tried with nothing plugged in. Find out first whether
  the simulated mount keeps its position between two `mount.py --demo`
  processes; if it does not, say so on the page in demo mode.
- `--port`, default 8081, so it never collides with `serve.py` on 8080.
- `install.ps1` may offer a desktop shortcut. No installer, no service.

## Work, in order

Build the whole frame first, with all seven tasks in the navigation, so that
nothing added later needs it redesigned. A task not yet built is left out of
the navigation, not shown empty.

1. **Server and safety.** `console.py`: `127.0.0.1`, the key, the headers,
   the `Host` and `Origin` checks, the job runner with Finish and Stop, the
   routes. Done when the tests below pass.
2. **The frame, on demo data.** Top bar, navigation, right-hand panel,
   bottom bar, activity log, notices, both themes, the keys, at 1366 × 768.
3. **The picture workspace.** The Imaging screen's viewer and measurements,
   reading the demo run. The picture is the largest thing the page will ever
   show, so the frame is fitted round it before anything else is laid out.
   Home and System, which only read, follow. Done when `console.py --demo`
   shows a live Home, Imaging and System.
4. **Targets and Mount.** The picker, the move plan, Go to, Home, Zenith,
   refusals. Done when, in demo, a Go to shows its plan, moves the simulated
   mount after Confirm, and a refusal is shown without a way round.
5. **Focus.**
6. **Imaging's controls.** The start sheet and its plan, Finish, Re-centre,
   assist.
7. **Mount's technical controls and Tools,** after the script changes above.
   The two result pictures.
8. **Documents.** README (a screenshot from `--demo` only: no photographs of
   the garden), `docs/setup.md`, `AGENTS.md` (layout table, and safety
   invariant 2 reworded to name the console and its limits),
   `docs/agents/safety.md` ("What enforces them today"), `CONTRIBUTING.md`.
   The README's "Current status" says what has been run on real equipment.

## Tests (no hardware)

Start the console on a free port inside the test, with the job runner given
harmless commands or `--demo`.

- A request with no key, a wrong key, a foreign `Host`, or a foreign
  `Origin` is refused, for every action.
- No `GET` route starts a job or changes a file.
- The server is bound to `127.0.0.1`: assert the socket's address.
- A second job while one runs is refused; reading still answers.
- Stop ends a running job and then runs the stop command, in that order.
- Every action marked "Moves" above is refused without a confirmed plan. A
  plan works once, for one command, for two minutes: confirming it twice,
  late, or for a different target is refused.
- With `MOTION_LOCKED` present every move is refused and Stop still works.
- An unknown action, an unknown target, a session folder outside `frames/`,
  or text with shell characters in it never reaches a command line.
- Every action in the tables builds exactly the command written beside it.
- Against `simulator.py`: Go to through the console ends where
  `mount.py --demo goto` ends.
- Nothing under `console/` is served by `serve.py`, and `serve.py` and
  `mcp_server.py` still offer no action.
- The page's files load nothing from the internet and contain no inline
  script or style; every response carries the headers listed above.
- After loading, the address in the browser no longer holds the key.
- Finish asks the job to end and waits before killing it; Stop does not
  wait. After a finished camera job a second one starts.
- While Stop is under way, a confirm, a retry or any other request that
  would open the mount is refused, until `mount.py stop` has answered.
- Confirm runs the dry run again. If the new plan differs (make the target
  set between plan and confirm, or put `MOTION_LOCKED` in place), nothing
  starts and a new plan with a new id comes back.
- A refused plan, a failed job and a finished job are reported as three
  different outcomes.
- No emoji in the page's files.
- In demo the page says DEMO.
- The existing suite still passes on Linux and Windows.

## Checks only the person at the telescope can do

1. Stop during a real slew, on Linux and on Windows: how long it takes, and
   that the mount really stops.
2. A whole night from the console: Go to with centring, focus, a run,
   Finish run.
3. Night vision and "Dim pictures" in real darkness: readable, and no flash
   of a bright picture.
4. That Stop can be found and pressed at once, by someone who has not been
   told where it is.

## What is built, and what is not

Built: the server and its safety (steps 1), the frame (2), the picture
workspace with Home and System (3), Targets and Mount with the move plan
(4), Focus (5), Imaging's controls (6), and of step 7 the Mount screen's
technical controls, the horizon survey with its plot of blocked directions,
the camera tests, calibration and restacking.

Not built, because the scripts do not yet report what they need (see "Small
changes the scripts need first"): polar alignment in Tools; a target's
height through the night against the skyline; distance from the Sun and the
bearing on a move plan; distance from the Moon; the last throughput figures
on System; the estimate of how long a run will take.

Nothing has been used with a real mount or camera. In demo mode only the
mount actions run, against the simulated mount; the camera actions say they
need the real camera.

## To decide before starting

- **Use from indoors.** The project's author watches the status page from
  another computer in the house. A console that listens only on the
  computer beside the telescope cannot be used that way. This version keeps
  to that on purpose: moving the mount from another room means nobody is
  watching it, and the one collision so far happened that way. If control
  from indoors is wanted later, it needs a password, an encrypted link and
  the webcam picture beside every move button, and it is a separate piece of
  work.

## Out of scope

A desktop toolkit, a phone app, accounts and logins, access from another
computer or over the internet, a sequencing language, a joystick or any
hand-slewing control, editing settings in the browser.
