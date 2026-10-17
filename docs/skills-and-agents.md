# Claude skills, agents and hooks for telescopeyoke: a specification

[README](../README.md) · Guides: [First night](first-night.md) · [Setup](setup.md) · [Imaging](imaging.md) · [Calibration](calibration.md) · [Focus](focus.md) · Science: [Discovery](discovery.md) · [Validation](validation.md) · [Data](data.md) · Developers: [Contributing](../CONTRIBUTING.md) · [Agents](agents/README.md)

Not built. Written 17 October 2026. This specifies a suite of Claude Code
skills, subagents and hooks for the procedures this project already has, so
that any session on the laptop, or any person's own Claude, does them the
same way every time. It adds no new telescope behaviour: every step a skill
takes is an existing project command.

## Why, and why these three kinds

The procedures are already written down: `docs/agents/setup-routine.md`,
`docs/agents/claiming.md`, `docs/first-night.md`, the discovery night in
`docs/discovery.md`. What goes wrong is not missing knowledge but a session
that does not load it, or loads it late: an agent that asks a question the
person answered, hands them a command to type in the cold, or forgets to
watch a run. Claude Code has three places to put such things, and each
fits a different need (from the Claude Code docs' "Extend Claude Code"
page):

| Kind | What it is | Use it here for |
|---|---|---|
| **Skill** (`.claude/skills/NAME/SKILL.md`) | A procedure loaded into the session that is talking to the person, when its description matches what they said or when they type `/NAME` | Anything done *with* the person, step by step: setup, focusing, a run, a claim |
| **Subagent** (`.claude/agents/NAME.md`) | A separate Claude with its own context, its own tools and model, returning a summary; can run in the background | Long or noisy work where only the conclusion matters: watching a run, vetting a candidate, reviewing a change, the docs |
| **Hook** (`.claude/settings.json`, or a skill's or agent's frontmatter) | A command Claude Code runs on an event; a `PreToolUse` hook that exits 2 blocks the tool call | Rules that must hold every time, whatever the model thinks: the motion lock, no inline hardware scripts |

CLAUDE.md and AGENTS.md stay the always-on rules; a skill never restates
them, it points at them.

## What two research telescopes teach

Two published systems put language models in charge of real telescopes,
and both draw the same line this project already draws:

- **StarWhisper Telescope** (Wang and others, 2024) runs the Nearby Galaxy
  Supernovae Survey's ten amateur telescopes: an agent plans each night's
  list, hands it to N.I.N.A., runs the pipeline and a real-or-bogus
  classifier, and suggests follow-up. A person checks the list before it
  goes to the telescopes, confirms transients by eye, and makes the TNS
  report. The control code is written by hand, because a model's commands
  can be wrong; weather limits and stopping at dawn are fixed rules. What
  it could not handle was hardware: cold, cables, frozen software.
- **JW-ASTClaw** (2026, a solar telescope in China's Meridian Project)
  separates perception agents (data quality, cloud, flares) from one
  decision engine and an execution layer behind MCP, with a "zero-trust"
  safety design: a model's mistake cannot cause an unsafe telescope
  operation, and if the model fails the system falls back to rules that
  were validated without it.

So here: **agents perceive and advise, never move the telescope.** Every
move comes from the main session, through `mount.py`'s checks, at the
person's request (AGENTS.md, safety rule 1). Hooks make that structural,
not a matter of the model remembering it.

## Design rules for every skill and agent

1. **Commands only.** A step is a project command (`./mount.py settime`,
   `./focus.py --motor`), never inline Python and never a one-off script
   (CLAUDE.md). If a skill needs something no command does, the command is
   written first, with a test.
2. **Moves are the person's.** A skill may *name* a move; it runs it when
   the person has asked for it, or when their sky report fits the routine's
   next step, after its `--dry-run` passes. `allowed-tools` never
   pre-approves a command that moves the mount or the focuser.
3. **Agents never move anything.** Each agent's frontmatter carries the
   `no-motion` hook (below) whatever its tools.
4. **Outward-facing means manual.** A skill that fills in a form for the
   outside world (`claim`, `report-comet`) has `disable-model-invocation:
   true`: only the person's `/claim ID` starts it, and it stops before the
   send button.
5. **Short bodies, details by reference.** A SKILL.md says the order and
   the judgement; the detail stays in `docs/` and is read when needed. Under
   about 150 lines each (the docs' advice is under 500).
6. **Descriptions say when.** Each starts with what the person would say
   ("I'm outside", "can see Polaris", "how did last night go"), since that
   is what Claude matches.
7. **Portable where it can be.** `name` and `description` follow the Agent
   Skills standard (agentskills.io: lowercase, hyphens, the folder's name),
   so the steps work in another agent too; Claude-only fields (`hooks`,
   `disable-model-invocation`, `context`) are ignored elsewhere.
8. **Tested like code** (Testing, below).

## The skills

Each entry: when it starts, what it may run without asking, what it does,
and when it is finished.

### `nightly-setup`

- **Starts:** "I'm going out", "I'm at the telescope", any report of the
  sky ("clear to the north, can see Polaris"), or `/nightly-setup`.
- **Without asking:** `lsusb`, `./doctor.py --offline`, `./mount.py
  status`, every `--dry-run`, `./tonight.py`.
- **Does:** `docs/agents/setup-routine.md`, step by step: look at what is
  plugged in; dry-run the night indoors; `settime`; ask where it is clear;
  `nudge` and ask whether they saw it; GoTo a rich field there and
  `focus.py --motor` in the background; polar alignment only if the tripod
  moved; GoTo the first target. One short line to the person at a time,
  only what needs their hands or eyes.
- **Finished:** the first target centred, or the person stopping.
- **Uses:** `focus`, `polar-align`, then `imaging-run` or `discovery-night`.

### `first-night`

- **Starts:** `/first-night` only (it installs software).
- **Does:** `docs/first-night.md` and `docs/setup.md`: `./install.sh`, the
  site in `config.toml` (asked, never guessed, never committed), the ASTAP
  database, `doctor.py` until it is clean, the camera's first frame indoors,
  the handset's lead, then `nightly-setup` with every step explained once.
- **Finished:** a first picture of something, and the person knowing which
  command does what.

### `focus`

- **Starts:** "focus", "the stars look soft", or from `nightly-setup`.
- **Does:** checks the telescope points at a rich field the person said is
  clear (else asks for the GoTo); `./focus.py --motor` in the background;
  reports the HFR (2 to 2.5 is good on the 150P). Never asks for a hand on
  the knob when the motor is plugged in; `--field` only without it.

### `polar-align`

- **Starts:** "polar align", "the tripod moved", or from `nightly-setup`.
- **Does:** GoTo with `--solve` to a bright star in clear sky, then
  `./polaralign.py --step 12`; after each round, the bolt, the way and the
  amount in the program's own words, once, then `--turned`; until under
  0.5°. Never repeats the reminder to tighten (memory: the person tightens
  as they go).

### `imaging-run`

- **Starts:** "image M31", "start a run", "switch to M33".
- **Does:** the GoTo with `--solve` (after a passing dry run), `./shoot.py
  TARGET --frames 0 --recentre 8` in the background, then starts the
  `run-watcher` agent. Switching target: stop the run, GoTo at once, restack
  later; never wait for the old stack first.

### `discovery-night`

- **Starts:** "patrol M31", "look for novae", `/discovery-night`.
- **Does:** `./patrol.py m31-panels --plan` and reads out anything marked
  NO; on the go, the patrol in the background with `run-watcher`; at the
  right times `./starwatch.py tabby` and any whole transit from
  `./transits.py`; at the end `./patrol.py --sweep`. Says depth reached and
  unexplained candidates, and shows each picture before calling anything a
  find.

### `end-of-night`

- **Starts:** "packing up", "that's me done", dawn.
- **Does:** stops the run cleanly, parks only if asked, starts the restack
  on the desktop (`./restack.py SESSION --on desktop`) and the sweep, and
  says what to bring in first (the laptop if it is on battery: it sleeps
  after 15 minutes).

### `morning-summary`

- **Starts:** "how did last night go", "what did we get".
- **Does:** hands the reading to the `night-analyst` agent and gives the
  person its five lines: frames kept, depth, candidates new and open,
  anything that went wrong, what tonight should do.

### `cloudy-day`

- **Starts:** "it's cloudy", "what can we do today".
- **Does:** the comet hunt's latest (`sungrazer/hunt-ccor1.json`, and that
  the timer is running), `./brokers.py` for tonight's public transients,
  `./patrol.py --sweep --all-history` after any improvement, heavy restacks
  on the desktop, `./ty characterise` for which measurements are still
  missing.

### `claim`

- **Starts:** `/claim ID` only (`disable-model-invocation: true`).
- **Does:** `docs/agents/claiming.md`: a fresh `./report.py ID`, anything
  still wanting said first, the TNS search for the place, the form filled in
  the browser with the person logged in themselves, attachments, and stops
  before Submit with the fields it was unsure of. Hands the check of the
  candidate to `candidate-vetter` first if it has not been done tonight.

### `report-comet`

- **Starts:** `/report-comet N` only.
- **Does:** the comet half of `claiming.md`: `comet-checker` first; the
  Sungrazer form filled, the person's name and email typed only after they
  say so in the session; stops before the send.

### `troubleshoot`

- **Starts:** "it's not moving", "the camera's gone", "plate solve failed".
- **Does:** the read-only checks first (`lsusb`, `doctor.py --offline`,
  `mount.py status`, the kernel log), then the known causes in order:
  handset not past its start-up screens (it accepts commands and then moves
  wrongly), motors stalled while the handset reports moves, the dead USB-C
  port, cloud before focus before exposure for a failed solve, dimming
  stars as cloud or dew or haze (ask what the sky looks like first). Never
  removes the motion lock.

### `new-command`

- **Starts:** "make that a command", or when a procedure has just worked by
  hand.
- **Does:** the project's rule for anything used every night: the script
  with `--json` and `--dry-run` where it moves anything, its schema in
  `schemas/`, `tests/test_interface.py`, a test of its own, the line in
  `docs/agents/commands.md` and AGENTS.md's layout table, then the full test
  run on the desktop in the background.

### `release`

- **Starts:** `/release` only.
- **Does:** checks version, changelog, README, home page and download links
  agree, runs `./release.py` to build the zip, and stops: only a person
  runs `./release.py --publish`.

One more belongs to the author alone and is not in the repository: the
procedure for outside audit rounds of the code lives in the author's own
`~/.claude/skills/`, as its rules are kept out of the public repository.

## The agents

All are read-only on the telescope. Model and tools are chosen for the job.

| Agent | Model | Tools | Background | Returns |
|---|---|---|---|---|
| `run-watcher` | haiku | Bash (read-only commands), Read | yes | One line the moment frames stop being kept, stars dim or the run ends; nothing while all is well |
| `night-analyst` | sonnet | Bash, Read, Grep | no | The night in five lines from `patrol.json`, `frames.json`, `depth.json`, `candidates`, the logs |
| `candidate-vetter` | opus | Read, Bash, WebFetch | no | real / bogus / unsure, with the reasons: the pictures, the history, VSX, SkyBoT, the TNS search, Gaia |
| `comet-checker` | sonnet | Read, WebFetch | no | new / already found / cannot tell, against the Sungrazer and Cambridge lists |
| `code-reviewer` | opus | Read, Grep, Glob, Bash | no | Findings on a change against this project's own rules (below) |
| `motion-reviewer` | opus | Read, Grep, Glob | no | Any change to `mount.py`, `direct.py`, `simulator.py`, `polaralign.py` or `focuser.py` checked against AGENTS.md's safety invariants |
| `test-runner` | haiku | Bash | yes | The full suite run on the desktop; only the failures, with their first lines |
| `docs-keeper` | sonnet | Read, Edit, Grep | no | After a night changes what is proven: `validation.md` first, then the README's table, the guides and the home page, which follow it |
| `researcher` | sonnet | WebSearch, WebFetch, Read | no | ATels, TNS objects, papers on a target, with the sources |

Notes on each:

- **`run-watcher`** replaces the Monitor a session has to remember to arm
  (memory: a run once went 65 minutes with no frames kept and nobody said).
  It reads `frames.jsonl` and the camera's state every minute; it does not
  diagnose (dimming stars: it says so, and the main session asks the person
  what the sky looks like).
- **`candidate-vetter`** is the human-in-the-loop step StarWhisper keeps,
  done as far as a reader can before the person looks: it never dismisses
  or claims, it says which and why, and the person decides.
- **`code-reviewer`** knows this project's rules, which a general review
  does not: every kept JSON through `records.write`; a `--json` change in
  three places (function, schema, `test_interface.py`); no path built from
  `ROOT` into `frames/`, `web/`, `cache/` or `horizon/`; no new dependency
  without reason; the demo and tests still working.
- **`docs-keeper`** may edit only `docs/`, `README.md` and `CHANGELOG.md`
  (a frontmatter hook refuses any other path), so it cannot change code.

## The hooks

In `.claude/settings.json` (committed), each a short script in
`.claude/hooks/` with a test:

| Hook | Event and match | What it refuses |
|---|---|---|
| `motion-lock` | PreToolUse, Bash, Edit, Write | Any command or edit that removes, moves or empties `MOTION_LOCKED`, or edits the code that reads it to skip it |
| `no-inline-hardware` | PreToolUse, Bash | `python3 -` or `python3 -c` that imports `mount`, `direct`, `focuser`, `camera`, `indi` or `serial`: hardware only through project commands |
| `no-self-kill` | PreToolUse, Bash | `pkill -f` or `pgrep -f` on a name in the same command line (memory: it matched its own shell) |
| `no-secrets-out` | PreToolUse, Bash | Printing the `[telegram]` section or a token from `config.toml` to the conversation |
| `no-motion` | PreToolUse, Bash; in every agent's frontmatter | `mount.py` with a move (`goto`, `nudge`, `slew`, `park`, `zenith`, `findhome`...) and no `--dry-run`, `focuser.py` or `focus.py --motor` turning, `shoot.py`, `patrol.py` without `--plan`, `--dry-run` or `--analyse` |
| `push-reminder` | Stop | Nothing: says when the work tree has commits not pushed (memory: always push finished work) |

The hooks are the fixed rules JW-ASTClaw relies on: the model may forget a
rule; Claude Code does not skip a hook.

## Testing

`tests/test_skills.py`, run with the rest:

- every SKILL.md and agent file has valid frontmatter, a `name` matching its
  folder, a description under 1024 characters, and no field Claude Code
  does not know;
- every `./COMMAND` a skill names exists, and every flag it uses is in that
  command's `--help`;
- no skill's `allowed-tools` matches a moving command (the `no-motion`
  hook's own list), and `claim`, `report-comet` and `release` have
  `disable-model-invocation: true`;
- each hook script, fed the JSON Claude Code sends it, blocks what it should
  and passes what it should (`rm MOTION_LOCKED` blocked, `cat MOTION_LOCKED`
  passed).

`evals/scenarios.json` already holds agent scenarios; each skill adds one:
what the person says, which skill should start, and the first command it
should run (for `nightly-setup` from "clear to the north, can see Polaris":
`./doctor.py --offline`, then the routine's next step, no question).

## Building it, in order

1. **The hooks** (`motion-lock`, `no-inline-hardware`, `no-motion`,
   `no-self-kill`) and their tests: the safety net comes before anything
   that leans on it.
2. **`nightly-setup`, `focus`, `polar-align`, `imaging-run`** and the
   `run-watcher` agent: used every clear night.
3. **`claim`, `report-comet`**, `candidate-vetter`, `comet-checker`: speed
   matters when something is real.
4. **`discovery-night`, `end-of-night`, `morning-summary`**, `night-analyst`.
5. **`code-reviewer`, `motion-reviewer`, `test-runner`, `docs-keeper`,
   `new-command`, `release`**: the development side.
6. **`first-night`, `troubleshoot`, `cloudy-day`**, `researcher`.

Each step: the files, their tests, the line in `docs/agents/README.md`, and
a real use before the next step starts.

## Sources

- Claude Code docs: [Skills](https://code.claude.com/docs/en/skills),
  [Subagents](https://code.claude.com/docs/en/sub-agents),
  [Hooks](https://code.claude.com/docs/en/hooks),
  [Extend Claude Code](https://code.claude.com/docs/en/features-overview)
- [Agent Skills specification](https://agentskills.io/specification)
- [StarWhisper Telescope: an agent-based observation assistant](https://arxiv.org/abs/2412.06412),
  Wang and others; and its [journal version](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12592323/)
- [JW-ASTClaw: a multi-agent framework for an autonomous solar telescope](https://arxiv.org/abs/2607.13549)
