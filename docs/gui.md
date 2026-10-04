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
| **A local page from the standard library's `http.server`** | Chosen. No new dependency, the same on both systems, reuses the status page's look, pictures and JSON, and Windows users already have a browser. |

**The console runs the existing commands; it contains no telescope logic.**
Each button starts one of the project's scripts as a separate process with
`--json`, exactly as a person would type it. So the console cannot do
anything the command line cannot, every limit and the `MOTION_LOCKED` file
apply unchanged, and there is still one implementation.

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
   a header. A request without it gets 403.
3. **Not reachable from other web pages.** Refuse any request whose `Host`
   header is not `127.0.0.1:PORT` or `localhost:PORT` (this stops DNS
   rebinding), and any action whose `Origin` header is present and is not
   the console's own. Send no CORS headers. Actions are `POST` only; `GET`
   never changes anything.
4. **A person confirms each move.** Pressing a move button runs the command
   with `--dry-run` and shows the plan: altitude, hour angle, side of the
   mount, and any warning such as "the tube will swing over the pole". The
   mount moves only when the person then presses Confirm on that plan. A
   refusal is shown with its message and advice, and offers no way round.
5. **Stop is always there.** A Stop button is on screen at all times, needs
   no confirmation, and works whatever else is running.

Be honest in the docs about what this does not do: a program running on the
same computer, including an agent, can start `mount.py` itself, as it can
today. The console adds no new way for an agent to move the mount, and
removes none. The approval design in `docs/agents/safety.md` is still not
built.

## How it works

```
browser (this computer) ── POST /do/goto ──► console.py ── starts ──► python mount.py goto M27 --json
        ▲                                        │                          │
        └────── GET /job (progress, result) ─────┘◄── stderr lines, stdout envelope
```

- **One job at a time.** `console.py` holds at most one running job that
  uses the mount or the camera. A second request while one runs is refused
  with a message naming the job. Read-only requests (status, targets) are
  never blocked.
- **Progress.** With `--json` each script prints progress on stderr and one
  envelope on stdout. The console keeps the stderr lines for the page's log
  and shows the envelope's result or error when the job ends.
- **Fixed commands only.** The console holds a table of the actions it
  offers and builds each command as a list of arguments. A target name must
  be one the catalogue knows (`mount.find_target`); numbers are checked
  against a range. Never pass a string from the browser to a shell.
- **Status.** The page reads the same answers as the existing API
  (`agent.status`, `agent.capabilities`, `agent.observing`, `agent.targets`)
  through the console's own `GET` routes, and shows the same pictures from
  `web/`.
- **Stop.** On Linux, `mount.py stop` can open the serial port while a slew
  is running. **On Windows a COM port can be opened by one process only**,
  so the console must end the running mount job first, then run
  `mount.py stop`. Do it that way on both systems. Measure how long Stop
  takes from press to the handset's reply and show it in the log; the aim is
  under two seconds. This cannot be proven against the simulator, so it is
  on the hardware check list below.
- **An imaging run** is stopped with `ty run stop`, which lets it finish its
  picture. The Stop button stops the mount; a separate "Finish run" button
  sends the order.
- **Closing the browser stops nothing.** Jobs belong to `console.py`. Closing
  `console.py` ends its running job and sends the mount a stop.

## What the first version offers

Keep it to what a night needs. One page, the status page's style.

| Area | Shows | Buttons |
|---|---|---|
| Tonight | verdict, clear window, best targets now | Go to (per target) |
| Mount | state, position, side, lock, limits | Stop, Home, Zenith, Go to NAME, with or without plate-solve centring |
| Camera | newest frame, star count | Take a frame, Start focusing aid / Stop it |
| Imaging | the run's progress, as the status page shows it | Start run (target, exposure, frames), Finish run, Re-centre |
| System | the doctor's checks, with its advice | Check again |
| Log | progress lines and results of the last jobs | |

If `MOTION_LOCKED` exists, the mount buttons are shown disabled with the
lock's reason. The console never creates or removes the lock.

**Not in this version:** editing `config.toml`, calibration frames, polar
alignment, the horizon survey, drift measurement, anything on a phone, any
access from another computer.

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

1. **Skeleton and safety.** `console.py`: the server on `127.0.0.1`, the
   key, the `Host` and `Origin` checks, the job runner, Stop, and a page
   with status and a log. Done when the tests below pass and
   `console.py --demo` shows live status.
2. **Mount.** Plan-then-confirm for Go to, Home and Zenith. Done when, in
   demo, a Go to shows its plan, moves the simulated mount after Confirm,
   and a refusal (below the altitude limit, locked) is shown without a way
   round.
3. **Camera and focusing.** Take a frame; start and stop the focusing aid.
4. **Imaging.** Start a run, watch it, Finish run, Re-centre.
5. **Documents.** README (a screenshot from `--demo` only: no photographs of
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
- A second job while one runs is refused; status requests still answer.
- Stop ends a running job and then runs the stop command, in that order.
- A move without a confirmed plan is refused. A plan is single-use and
  belongs to one command: confirming it twice, or confirming a different
  target, is refused.
- With `MOTION_LOCKED` present every move is refused and Stop still works.
- An unknown target name, or text with shell characters in it, never reaches
  a command line.
- Against `simulator.py`: Go to through the console ends where
  `mount.py --demo goto` ends.
- The existing suite still passes on Linux and Windows, and `serve.py` and
  `mcp_server.py` still offer no action.

## Checks only the person at the telescope can do

1. Stop during a real slew, on Linux and on Windows: how long it takes, and
   that the mount really stops.
2. A whole night from the console: Go to with centring, focus, a run,
   Finish run.
3. That the page stays usable in the dark: dim, red-friendly, large Stop.

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

A desktop toolkit, a phone app, accounts and logins, remote access over the
internet, a sequencing language, editing settings in the browser.
