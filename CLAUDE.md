# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Read `AGENTS.md` first: it has the layout, the commands, the safety rules and
the conventions, and applies to every agent. `docs/agents/architecture.md` is
the one-page picture of how the scripts fit together. This file only adds
what is specific to Claude and to this particular user.

## Working with this user

- Run anything expected to take more than a minute in the background and
  carry on with the next task.
- Turn each procedure that works into a command in the project as soon as it
  works.
- Slew the real mount only when the user has asked for that move. Say first
  if the tube will swing over the pole.

## Commands

There is no build step and no linter; the scripts run from the checkout.

```bash
pip install ".[test]"                       # what CI installs; ./install.sh uses distro packages
pytest -q                                   # about three minutes on this laptop: background it
pytest -q tests/test_interface.py           # one file; this one takes seconds
pytest -q tests/test_mount.py::test_name    # one test
pytest -q -k meridian                       # tests matching a word
```

CI (`.github/workflows/tests.yml`) also runs these after the tests, on Python
3.11 to 3.14, so run them before pushing a change that touches the planner,
the mount or the JSON output:

```bash
./tonight.py --demo --top 5
./mount.py --demo zenith
./ty capabilities --json
./mount.py --demo zenith --dry-run --json
```

A demo step in CI has to hold at any hour: use the zenith, not a named object
that may have set.

## Things that span several files

- The motion lock is a file named `MOTION_LOCKED` in the repository root
  (ignored by git); its text is the reason shown in the refusal. `mount.py`
  checks it, `agent.py` reports it. Never create a way round it or remove it.
- `config.toml` holds the user's real site and is ignored. `config.load()`
  needs it; `config.hardware()` works without it and `config.example()`
  never reads it. Tests and `--demo` take their site from `config.example()`.
- Every file a script keeps (frames, pictures, remembered measurements) is
  under `config.DATA`: the repository root for real, `demo/` in the demo
  (`config.DEMO`, from `TY_DEMO=1`), and a scratch folder in the tests.
  `conftest.py` sets `TY_DATA` and `TY_CALIBRATION` before anything is
  imported, so a test cannot write into a real night's files even if its
  fixture forgets to redirect something. Never build a path to `frames/`,
  `web/` or `cache/` from `ROOT`.
- A change to any `--json` output touches three places together: the
  function, its file in `schemas/`, and `tests/test_interface.py`, which
  checks the envelope, the MCP tools' `outputSchema` and the scenarios in
  `evals/scenarios.json`.
- The application is `app.py`: it runs `console.py`'s server in "app" mode and
  shows `console/index.html` in a GTK window (Ubuntu) or WebView2 (Windows).
  `console.py` alone serves the same page in "companion" mode, where the
  actions in `console.WORKSTATION` are refused. A screen for the application
  only is marked `data-only="app"` in the page.
- A setting the application can change is one row in `config.SETTINGS`
  (label, kind, help, limits); the Settings form, the checking and the
  writing all follow from that row.
- `ty` passes `mount`, `tonight`, `shoot`, `focus`, `solve` and `restack`
  straight through to those scripts' own `main()`. The rest are read-only
  views from `agent.py` and `doctor.py`, except `ty run`, which leaves an
  order for the imaging run through `shoot.tell()`.
