# Moving the comet hunt out: sungrazeryoke

The comet hunt (`sungrazer.py`) uses no telescope, mount or camera: it
reads GOES-19 CCOR-1 pictures from NOAA. It moves to its own private
repository, `Ryan-Clinton/sungrazeryoke`, and is then removed from
telescopeyoke entirely. Nothing in telescopeyoke reads its results
afterwards. Nothing below has been done yet except the history patches.

## What moves, with its history

The 16 commits that touch these paths, made with
`git format-patch --root HEAD -- PATHS` (only those paths' changes; no
other telescopeyoke history), applied in the new repository with `git am`:

- `sungrazer.py` (1,460 lines): archive and live fetch, look, hunt, form,
  submitted, replay
- `schemas/sungrazer.schema.json`
- `docs/discovery/comet-hunt-2026-10-19/` (the first known-comet match and
  its movies)

## Written new there

- `HANDOVER.md`: how it works, as facts: what it does, its data sources,
  its commands, its configuration, the results so far and the state it is
  in. No working rules or advice.
- `README.md`, `requirements.txt` (numpy, scipy, astropy, Pillow,
  requests), `.gitignore` (`data/`, `config.toml`).

## The helpers it uses, rewritten small

`sungrazer.py` uses seven things from four telescopeyoke modules. They
become one file of its own, not copies of the modules:

| From | Used | Becomes |
|---|---|---|
| `config` | `DATA`, `FILE` | `data/` and `config.toml` in its own folder |
| `interface` | `Refusal`, `main` (the `--json` envelope) | about 40 lines; only the error codes it raises (`NO_SESSION`, `INVALID_REQUEST`, `INTERNAL_ERROR`) |
| `records` | `write` (whole or not at all, provenance, schema check) | about 40 lines |
| `notify` | `send` (Telegram, waiting when told too many were sent) | about 50 lines, with `send = false` in its config |

## Data, copied before the hunt's 13:34 UTC tidy-up deletes it

- `hunt-ccor1.json`, `told-ccor1.json` (holds report_nu_20261108025621 as
  submitted, which later hunts follow)
- the four replay records `replay-report_nu_20261108025621-{l3,1b}-{24,6}h.json`,
  committed there under `results/replays/`
- the CCOR-1 pictures of 7 November and 18-19 October, archive level 3
  and live level 1B (about 2 GB), kept out of git

## Configuration

Its own `config.toml`: `[reporter]` (name, email, contributor) and
`[telegram]` (token, chat), copied from telescopeyoke's, with sending
off until the switch below.

## One hunt sends alerts at a time

- Telescopeyoke's `ty-sungrazer.timer` (every 6 hours) stays the only one
  sending until the new one is confirmed.
- The new project's timer is named `sungrazeryoke.timer` and is not
  installed until then; at the switch, its sending goes on and
  `ty-sungrazer.timer` is disabled in the same step.

## What comes out of telescopeyoke, after the switch

- `sungrazer.py`, `schemas/sungrazer.schema.json`, the `ty-sungrazer`
  timer and service
- `agent.py`: the comets in `ty candidates` (line 260) and in the night
  summary (line 1425)
- `streamstory.py`: the comet hunt's finds (lines 117-124)
- `policy.py`: the `sungrazer.py` entry (line 130)
- `.claude/skills/report-comet/`, `.claude/agents/comet-checker.md`
- the comet parts of `docs/discovery/results.md`, `docs/validation.md`,
  `docs/agents/claiming.md`, `docs/agents/commands.md`,
  `docs/skills-and-agents.md`, `docs/commands.md`, `evals/skills.json`
- `docs/discovery/comet-hunt-2026-10-19/` and this file

## Not carried over

telescopeyoke's `CLAUDE.md`, `AGENTS.md`, `.claude/` (skills, agents,
hooks) and its private memory.

## Later, as its own stage

- The replay of the 19 October comet (report_ms_20261019125628), archive
  and live.
- The move to the always-on server brokerblitzer (6 vCPUs, 7.7 GB, no
  swap): a user for the hunt only, a memory limit on its service, and no
  two runs at once. Measured on the laptop so far: a live 6-hour look
  takes 15 s of processor and 0.7 GB.
