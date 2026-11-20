# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

@AGENTS.md

`AGENTS.md`, imported above, has the layout, the commands, the safety rules
and the conventions, and applies to every agent. `docs/agents/architecture.md` is
the one-page picture of how the scripts fit together. This file only adds
what is specific to Claude.

## Working on this project

- Run anything expected to take more than a minute in the background and
  carry on with the next task.
- There are no tests and no CI, by the maintainer's choice: do not write,
  run or restore them, add CI, or make a commit wait on anything. Before a
  commit: `ruff check` on the changed files, then commit and push. What is
  proven is proven on the telescope, and recorded in `docs/validation.md`.
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
  that, and from what the person has already said.

## Someone else's telescope: suggestions

`CLAUDE.local.md` (ignored by git) holds one owner's own conventions with
their Claude: what their nights are for, where their notes go. A fresh
checkout has none of it. Some suggestions for a new rig:

- Asked to install, set up or get started, the `first-night` skill finds
  what is plugged in and what TelescopeYoke can do with it; `./ty onboard`
  says how far a setup has got and what is next.
- The owner's figures (focus, the focuser, the cooled camera, the filter
  slots) may not hold for another rig: `config.toml` and
  `./doctor.py --json` say what this one is.
- On a mount nobody has watched move yet, offer to say each move first.
- Ask what they want from the night; the discovery programmes are one
  choice among the Moon, planets and the deep sky.
- Someone whose own software already runs their nights (NINA, PHD2) and
  asks why one went badly: the `night-review` skill runs `companion.py`,
  which reads their frames and logs and touches nothing on their rig.

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
