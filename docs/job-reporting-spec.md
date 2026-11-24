# Spec: one way for every long job to report

Status: draft for review, 24 November 2026. Nothing here is built yet.

Reviewers (ChatGPT included): this project has no tests and no CI by the
owner's choice (`AGENTS.md`, "No testing, and why"). Do not suggest tests,
a test suite, CI or simulator runs as a check on this work. Review the
design, the gaps in it and the order of the work.

## The problem

The owner asks for a progress report and the agent can't say what is
happening. The other way round, a job finishes or stops to wait, and the
agent doesn't notice for hours. Each time the cause was the same: the
scripts and the agent have no shared way to say "this is where I am", "I
need someone" or "I've finished".

What it has cost:

| Date | What happened | Cause |
|---|---|---|
| 15 Oct 2026 | An imaging run went 65 minutes with no frame kept, and nobody said. | Nothing watched the run. `runwatch.py` was built after, for imaging runs only. |
| 18 Oct 2026 | The camera hung for six minutes in a patrol, and the owner noticed it first. | The agent's watcher looked for lines that a stalled camera never prints. |
| 17-18 Oct 2026 | Watcher lines filled the owner's console ("a pile of garbage"). | The watchers passed on every line. The rule since then has been to start routine jobs in the background and wait for them to exit, which led to the 24 Nov delay. |
| Oct 2026 | A watcher stayed silent through an hour of cloud. | `grep | awk` held its input back. |
| 24 Nov 2026, 01:55-02:30 | The owner asked how the colder dark test was going. The agent couldn't say whether the camera was cooling, because the log was empty for 30 minutes. | `darktest.py`'s output went to a file, where Python holds back what it prints until a block is full. |
| 24 Nov 2026, 03:18-07:28 | The darks finished at 03:18. The script then held the camera cold for 4 hours, waiting for more temperatures or `--finish`. The agent heard only at 07:28, when the script exited, and the Moon video test planned to follow it wasn't done. | The agent is told only when a job's process exits. A job that is waiting for someone has no way to say so. |

The fix after the 30-minute gap was narrow: one script and a memory note
saying "every script that cools the camera must not wait to log". That fixed
darktest, but not the next script.

## What the code does now (the audit)

- **The scripts:** 100 scripts have their own `main()`. None uses Python's
  `logging`. Each one prints, or doesn't, in its own way.
- **Output held back:** when output goes to a file, which is how every
  background job runs, Python holds back stdout until a block of about 8 KB
  is full.
  - Eight scripts turn that off for all their output (`mount`, `focus`,
    `keeper`, `polaralign`, `guidecam`, `skywatch`, `darktest`, and `host`
    sets only the encoding).
  - The rest rely on `flush=True` on each print, and mostly forget it:
    - `schedule.py`: 9 prints, 0 flushed.
    - `horizon.py`: 38 prints, 10 flushed.
    - `camera_test.py`: 31 prints, 5 flushed.
    - `focuser.py`: 16 prints, 2 flushed.
    - `clouds.py`: 14 prints, 1 flushed.
    - `colour.py`, `desktopqueue.py`: 6 prints each, none flushed.
- **Jobs that say nothing until the end:** many long jobs print only their
  final envelope: `restack`, `remote`, `starwatch`, `precision`, `depth`,
  `transits`, `variables`, `archive`, `brokers`, `realbogus`, `plant` and
  `difference`. A restack on the desktop or a patrol's search runs for many
  minutes with an empty log.
- **Child jobs thrown away:** some jobs start children whose output is
  discarded:
  - `shoot.restack_later` and the patrol's `history.py --keep` send theirs
    to `DEVNULL`, so when one fails there is no trace of it.
  - `schedule.py` passes its children's output through without saying
    which child wrote which line.
- **Log files:** they are named by hand each time the agent starts
  something. `cache/` now holds about 70 of them (`dectest-main-20261120`,
  `…b`, `…c`, `…d-cloudy`, `…e`, `…f`, `…-untracked`). There is no index,
  and nothing says which one is still being written.
- **Waiting:** when a job waits on a person or another command, it has no
  way to say so. Examples are darktest's hold, the schedule waiting for its
  next block, and a patrol waiting for clear sky. All of them look the same
  as working.
- **What already exists:**
  - `activity.py`: what each process is doing now, kept by process ID and
    nested ("Panel 3 of 8 · Moving to M31-P5"). 23 scripts use it, and the
    console shows it. This is the right base for the new system.
  - `runwatch.py`: watches imaging runs only. It prints a line only when
    something changes, which is the right pattern for the agent.
  - `notify.py`, `cache/sent.jsonl` and the `news.py` hook: messages to the
    phone, shown to the agent at the next message the owner sends.
  - `cache/agent-log.jsonl`: the hooks' decision record, which says what
    ran, not how far it has got.
  - `cache/events.jsonl`: the narrator's words for the stream. It is for
    the audience, not for the agent.
  - `keeper.py status` and `cache/activity.json`: state, but no history.
- **The agent's side:** Claude Code tells the agent about a background job
  only when it exits. A Monitor tells it about every line its command
  prints. The owner has rightly refused the noise of a line for each step.
  So the agent needs a quiet stream that carries only the events that need
  it.

## What the system must do

1. **Progress report at any time.** The agent can say what every running
   job is doing, how far it has got and when it should end, within a minute
   of the job doing it. It never has to wait for a job to finish.
2. **Wake the agent when it must act.** It is told within a minute when a
   job:
   - finishes or fails;
   - reaches a milestone the plan depends on (the last dark taken, a block
     ended);
   - starts waiting for a person or another command;
   - stops making progress (stalled or hung);
   - disappears without saying it ended (killed, crashed or out of memory).
3. **No noise.** Routine progress is written down but wakes nobody. The
   owner's console gets a line only for the events in requirement 2.
4. **One place.** Every job's record, log and events are kept in one known
   place under `config.DATA`, found by name, not by a file name made up on
   the night.
5. **Works for scripts not yet changed.** It must at least stop output being
   held back, keep the log, and report the exit and any silence, for every
   project command, from the first day.
6. **Moves nothing.** It reads and writes records only. No new network
   listener. The read-only rules for the web server and the MCP server stand.
   The camera's cooling, the mount's limits and every fail-closed check are
   not touched.

## The design

### 1. The job record, built on `activity.py`

A job is one command, started by the agent, the console, a timer or another
job. Each one gets a folder of its own, `cache/jobs/ID/` (ID =
`YYYYMMDD-HHMMSS-name`), holding:

- `state.json`, written with `records.write` and checked against a new
  schema:
  - what it is: name, command line, process ID, the parent job's ID;
  - when: started, last heartbeat;
  - its phase: running, waiting, done or failed;
  - progress: step k of n, the text of the current step, the last line
    printed and when;
  - when it expects to end, if known;
  - when waiting: why, and what would end the wait (for example,
    `./darktest.py --more` or `--finish`);
  - at the end: the exit code and a one-line result.
- `log.txt`: everything it prints, a line at a time as it happens.

There is also one shared `cache/jobs/events.jsonl`, with one line per event
that matters: `started`, `step`, `milestone`, `waiting`, `resumed`, `done`,
`failed`, `stalled` and `vanished`. Each line has the job's ID, the time, a
level (`log`, or `wake` for the events in requirement 2) and the words.

The API is in `activity.py`, so the console sees the same thing:

```python
with activity.job("darktest", steps=["-5", "-7.5", "-10"], expect_s=3 * 1500) as job:
    job.say("camera: cooling, sensor at -6.2 °C ...")   # log only
    job.step(2, "-7.5 °C: 120 s dark 4 of 6")           # progress, log only
    job.milestone("last temperature done: -9.9 °C")     # wakes the agent
    job.waiting("holding cold up to 4 h", ask="./darktest.py --more TEMPS | --finish")
    job.resumed("taking -12 °C")
# leaving the block: done, with the result line; an exception: failed, with the traceback's last line
```

When a job is entered:
- stdout and stderr print a line at a time;
- an `excepthook` and an `atexit` handler write `failed` or `done` even
  when the code forgets to;
- a heartbeat thread updates the record every 60 seconds.

Children inherit `TY_JOB` (the parent's ID) and become child jobs, never
`DEVNULL`. The parent's record names them.

### 2. A launcher for every background job: `./ty bg NAME -- COMMAND...`

This is the one way the agent, and the console where it fits, starts
anything long. It:
- sets `PYTHONUNBUFFERED=1` and `TY_JOB`;
- writes the log to `cache/jobs/ID/log.txt`;
- writes `started` and, when the process exits, `done` or `failed` with the
  exit code.

Scripts not yet changed get requirement 5 at once: no output held back, a
known log, the exit recorded and silence noticed. Scripts that use
`activity.job` add steps, milestones and waiting states to the same record.

### 3. Reading it: `./ty jobs`

`./ty jobs` lists the running, waiting and recent jobs. For each one it
shows:
- its name and phase;
- step k of n and the step's text;
- the last line and how long ago it came;
- when it expects to end;
- if waiting, why and what ends it;
- its log's path.

`--json` comes with a schema. `./ty jobs NAME --tail 20` shows the last
lines of one job. It only reads.

Stall rules, applied when it reads:
- **Stalled:** no log line or step for longer than the job's own limit,
  which a script may set (a 300 s dark is not a stall). The default is 10
  minutes.
- **Vanished:** the process has gone with no `done` or `failed` written.
- **Waiting too long:** waiting for longer than it said it would.

### 4. Waking the agent: `./ty jobs --watch`

`./ty jobs --watch` prints one short line for each `wake` event, and the
stalled and vanished ones it finds. Otherwise it prints nothing. The agent
starts it as one Monitor at the start of each session and keeps it
running. It is the only Monitor needed for jobs, and it replaces the
practice of waiting for a process to exit. `runwatch.py` keeps its imaging
measures but writes them as events, so an imaging run wakes the agent
through the same watch.

### 5. In front of the agent at every message

A `UserPromptSubmit` and `SessionStart` hook, `jobs.py` beside `news.py`
and `sky.py`, adds a few lines to each of the owner's messages when any job
is running or waiting: name, phase, step, the last line's age, and when it
should end. So "progress report" is always answered from the state of that
moment. It prints nothing when no job is running.

### 6. The phone, only when a person is needed

A job may set `phone=True` on `waiting` and `failed`, for example the
schedule at night or a cooling fault. That event then also goes through
`notify.py`. It is off by default, so the phone gets no progress messages.

### 7. Keeping to it

`.claude/hooks/guard.py` warns when the agent starts a project command in
the background without `ty bg`. Whether it should block instead is an open
question. A new long-running script uses `activity.job` from its first
commit, as the camera's cooling rules are kept now. `AGENTS.md`,
`CLAUDE.md` and the skills get three rules:
- start long jobs with `ty bg`;
- keep `./ty jobs --watch` running;
- answer a progress report from `./ty jobs`, and never say "I can't tell
  until it finishes".

### What every job promises

- Every line is written as it happens.
- During a long wait, a line at least every 5 minutes saying what it is
  waiting on and the latest figure, for example "cooling: -6.2 °C, target
  -7.5".
- Step k of n, and an end time where one can be known.
- A `milestone` at any point a plan may continue from.
- A `waiting` event the moment it waits on a person or another command,
  saying what ends the wait.
- One result line at the end.
- Children are never sent to `DEVNULL`.

## The order of the work

1. `activity.job`, the job record and its schema, `./ty jobs`,
   `./ty jobs --watch` and `./ty bg`. Every background job is covered for
   output held back, the log, its exit and silence from this step.
2. The `jobs.py` hook, and the rules in `AGENTS.md`, `CLAUDE.md` and the
   skills (`imaging-run`, `end-of-night`, `discovery-night`,
   `nightly-setup`).
3. The scripts that cool the camera or take a night's minutes:
   - `darktest`, `keeper`;
   - `calibrate` (darks and flats);
   - `shoot`, `schedule`, `patrol`;
   - `lucky`, `moon`.
4. The long jobs that say nothing until the end: `restack`, `remote`,
   `desktopqueue`, `starwatch`, `precision`, `depth`, `transits`,
   `variables`, `archive`, `brokers`, `realbogus`, `plant`, `difference`.
   Also the children sent to `DEVNULL` in `shoot` and `patrol`.
5. `runwatch.py` onto events. The console and the status page show
   `./ty jobs`.
6. The hand-named logs in `cache/` are left as they are. New ones stop.

## How it is shown to work

On the next real jobs, recorded in `docs/validation.md`:
- a cooled dark or flat run;
- a night's imaging schedule;
- a restack on the desktop.

For each one, the record should show:
- a progress report given while it ran, with the figures of the last
  minute;
- the agent woken within a minute of the last step finishing and of a
  waiting state starting;
- a job killed by hand reported as vanished.

## Out of scope

Tests and CI. A network service. A change to Python's `logging`
throughout. Retrying jobs automatically. Anything that moves the mount or
changes the camera's cooling.

## Open questions for review

1. Should `guard.py` block a background project command that bypasses
   `ty bg`, or only warn?
2. One shared `events.jsonl` with appends a line at a time, or a file per
   job read together? Appends are atomic for short lines on Linux. What
   about Windows (`host.py`)?
3. Should the default stall limit be 10 minutes, and should each script
   name its own?
4. Should `activity.json` and the job records merge into one, or does the
   console keep its own file?
5. Is a heartbeat thread safe beside the camera's library calls and the
   keeper's streaming, or should the heartbeat come only from `say` and
   `step`?
6. Is anything in the audit missed: a job that runs long, waits or starts
   children and isn't named above?
