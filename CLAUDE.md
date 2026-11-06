# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Read `AGENTS.md` first: it has the layout, the commands, the safety rules and
the conventions, and applies to every agent. `docs/agents/architecture.md` is
the one-page picture of how the scripts fit together. This file only adds
what is specific to Claude and to this particular user.

## Working with this user

- The nights are for discovery first (AGENTS.md): asked for the outlook or
  a plan, use the `discovery-night` skill and plan around `./ty night`'s
  `discovery` list.

- At the telescope, follow `docs/agents/setup-routine.md` step by step:
  set the handset first, then ask the user where the sky is clear.
- Run anything expected to take more than a minute in the background and
  carry on with the next task.
- There are no tests and no CI: the user had them removed on 4 November
  2026 after asking thirteen times for the testing to stop. Never write,
  run or restore tests, never add CI, never make a commit wait. Before a
  commit: `ruff check` on the changed files, then commit and push.
- The telescope's operational protections are not testing and stay:
  camera cooling (the slow ramp, never below -5 °C, the warm-up, stopping
  when the cooler fails), mount safety (`MOTION_LOCKED`, the limits, dry
  runs before moves, the demo and simulator), calibration integrity
  (matched masters, science refusing uncalibrated frames) and every
  fail-closed check (a filter the wheel has not confirmed, a sensor off
  target). Never weaken or remove one as part of cutting testing.
- A change to how a night's imaging runs (shoot.py's blocks, re-centring,
  the camera kept open, cloud handling) says in its commit what it does to
  all four: the framing of the target, the sensor's temperature, the
  minutes lost, and the mount's safety. On 5 November 2026 a fix to keep
  the sensor cold (no re-centre between filters) let M33's filters drift
  apart, and three more fixes that night undid it piece by piece.
- No one-off scripts for anything new that will be used every night
  (focusing, alignment, a new piece of hardware): write it as a project
  command before its first use, and use it only through that
  command. On 13
  October the motor focuser focused the telescope from an inline script
  that was never kept, and two nights later nothing knew it could.
- A result in a dated night file (`docs/nights/DATE/`) that changes what is
  proven is linked from `docs/validation.md`.
- Before advising on the telescope, look at what is plugged in rather than
  asking: `lsusb`, `./doctor.py --offline` (handset lead, handset set up,
  camera, INDI) and `./mount.py status`, which only reads. Then advise from
  that, and from what the user has already said.
- If the user talks about alignment and the mount or camera shows on USB,
  they are outside at the telescope in the cold. Give the next command to
  run, short; no questions they have already answered, no advice on getting
  the telescope outside, and no testing that makes them wait.
- No approval asking for the mount: what the user asks for and every slew of
  the night's plan go at once. When they
  ask for a move from beside the telescope ("swing to Vega"), that is the go:
  dry-run it and, if the dry run passes, send it at once. No warnings about
  the mount moving, cables or standing clear; they know. A pole swing is
  said in the same message as the move goes, as a fact, not a question.
- When the user says what they can see ("it's clear to the north, can see
  Polaris"), they are outside at the telescope and that is the go for the
  next step of the routine that fits it. Dry-run it and start it at once:
  no plan to approve, no "say go", no extra steps.
- Every observing night, keep running notes for the user's diary in
  `~/ryanclinton.uk/notes/DATE.md` (the evening's date): a bullet with the
  time and the figures after each step or result, without being asked. The
  titled diary entry is written from them only once the night is over.
- The other way round: once the user has asked for a step, run it at once,
  in the background, and keep it running; never wait for a second "go".
  The focuser and the camera are not the mount: "start the walk-in" is
  the go for that step and every retry of it. A step that cannot start (cloud, no stars) is retried by me until it
  can. On 1 November 2026 I waited for "go" on a walk-in already asked for
  and the cloud came in.

## Commands

There is no build step and no linter; the scripts run from the checkout.

```bash
./install.sh                                # distro packages
ruff check FILE.py                          # before a commit: mistakes, not style
```

## Things that span several files

- The motion lock is a file named `MOTION_LOCKED` in the repository root
  (ignored by git); its text is the reason shown in the refusal. `mount.py`
  checks it, `agent.py` reports it. Never create a way round it or remove it.
- `config.toml` holds the user's real site and is ignored. `config.load()`
  needs it; `config.hardware()` works without it and `config.example()`
  never reads it. `--demo` takes its site from `config.example()`.
- Every file a script keeps (frames, pictures, remembered measurements) is
  under `config.DATA`: the repository root for real, `rigs/NAME/` for a
  named rig (`config.RIG`, from `TY_RIG`, whose settings are
  `rigs/NAME.toml`), `demo/` in the demo (`config.DEMO`, from `TY_DEMO=1`).
  Never build a path to `frames/`, `web/`, `cache/` or `horizon/` from
  `ROOT`.
- A change to any `--json` output changes its file in `schemas/` with it.
- Anything kept that depends on the pixel scale or the camera's angle names
  the camera and light path it was made with, and is used again only when
  `config.light_path()` (profile, effective focal length) matches: the last
  plate solve (`mount.last_solve()`, which `agent`, `mosaic`, `shoot`'s drift
  assist and `mineral` read), a field's depth prior (`goals.prior_for`) and
  a kept mosaic plan (flagged when its field differs). `stacking.same_camera`
  reads every frame's header, not one per folder.
- The application is `app.py`: it runs `console.py`'s server in "app" mode and
  shows `console/index.html` in a GTK window (Ubuntu) or WebView2 (Windows).
  `console.py` alone serves the same page in "companion" mode, where the
  actions in `console.WORKSTATION` are refused. A screen for the application
  only is marked `data-only="app"` in the page.
- The measured skyline is one list of points in `cache/horizon.json`,
  written by `horizon.keep()` from either `horizon.py --trace` or
  `panorama.py save`. `config.load()` puts it in `cfg["horizon"]["skyline"]`
  (never `config.example()`), `sky.Night.horizon()` adds the margin with
  `horizon.limit()`, and the Horizon screen draws the same list.
- A setting the application can change is one row in `config.SETTINGS`
  (label, kind, help, limits); the Settings form, the checking and the
  writing all follow from that row.
- `ty` passes `mount`, `tonight`, `shoot`, `focus`, `solve` and `restack`
  straight through to those scripts' own `main()`. The rest are read-only
  views from `agent.py` and `doctor.py`, except `ty run`, which leaves an
  order for the imaging run through `shoot.tell()`.
