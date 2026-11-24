# Spec: one way for every long job to report

Status: built 24 November 2026 (see "As built" at the end); not yet proven on a real night's jobs.

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

### What the owner has said

These are taken from the owner's messages to Claude Code in this project,
21 October to 24 November 2026, quoted as typed. Between 1 and 24 November
they asked for a progress report 29 times ("progress report", "check
progress", "eta?", "update please"), 10 of them on the night of
1 November alone. Each ask means the owner didn't know what a job was doing
and had to ask.

**The agent couldn't see what a job was doing:**
- 21 Oct, about the focus logging: "thats niot good enough fix the
  logging", then "15 minutews for a logging chager is ridiculious".
- 22 Oct, 03:45: "imaginmg still says what it was doing 2 nighs ago while i
  wait for it to sort itself out whith no comprehinsion of whats happening".
- 1 Nov, 00:19 to 02:02: "check progress", ten times in under two hours,
  from beside the telescope.
- 4 Nov, 11:55, after "progress report" got no answer: "you have 10 seconds
  before i kil this session if you are actully doing things i cant see you
  better tidy up".
- 19 Nov, 16:53: "ok tail the logs so i can see as well instead of me
  having to ask you 3 times".
- 19 Nov, 20:04: "your messages got lost in the logs what happened".
- 22 Nov, 23:43: "when i say progress report i mean progrees on the things
  you are workong on not things that dont concern you".
- 24 Nov, 02:13, quoting the agent's own answer: "Both tests are still
  running, but I can't yet confirm the colder dark test is cooling. … <<
  fix that".

**Jobs finished or waited, and nothing went on:**
- 3 Nov, 22:30: "yeah i said that hours ago its dark now and your still not
  done".
- 21 Nov, 19:21: "why ais the B and R waitign on the measurment?"
- 22 Nov, 23:44: "can you fill the next 8 to 10 hours with useful work?"
  Then 23 Nov, 11:57: "why is the cpu idle have i not been clear?"
- 24 Nov, 02:11: "shedule up some work to keep yourselg busy fo 6-8
  hours". The dark test then sat holding the camera from 03:18 to 07:28,
  and the planned video test after it was never done.
- 24 Nov, 07:57: "why have you been sitting for 5 hours instead of
  finishing it?"
- 24 Nov, 10:49: "why did the dark test not notify you it had finished for
  you to continue with the rest of the tasks?"

**Stopping with work left, questions saved for the end** (24 Nov, 11:45,
another session, on the free-tools tests): it stopped with three of four
tests done and two questions it had known for some time, then cancelled
its own check-ins. The owner: "'shedule them and keep going until they are
all done. negotiate cpu and gpu use with the 2 desktop sessions' do you
need to gogole the word shedule? was i not clear wenough?"

**And the ask behind this spec** (24 Nov, 10:54): "i have asked you to do
this before and you obviously didnt do it right. im getting very sick of
'i didnt do x because job y didnt report' or 'i cant tell you what is going
on right now becasue the script saves its logs to after its finished' … so
that i never get frustrated again after askin you for a progress report and
you telling me you are blind for 40 mins until the script completes."

The owner has also refused the opposite failure. On 17-18 October the
watchers passed on every line, and the owner called the console "still a pile of
garbage in my console" and "my console is full of crap agin". The design
has to answer both complaints: the agent can see everything, and the owner
is told only what needs them.

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
6. **The next job starts by itself.** When a job finishes, or lets go of
   what the next one needs, the next planned job starts without waiting for
   the agent to notice. On 24 November, knowing the darks had finished
   would not have been enough: the Moon video had to start too. Reporting
   alone only turns "I didn't know it had finished" into "I knew, but
   didn't start the next one".
7. **Never idle when asked to keep busy.** When the owner has asked for
   work until a given time, the agent is woken whenever nothing is running
   or queued before that time (23 November: "why is the cpu idle have i not
   been clear?").
8. **No turn ends with the work undone.** While the owner's ask for work
   stands, the agent is sent back when it would end its turn with nothing
   running or queued, or with an event not dealt with; a question for the
   owner is asked the moment it arises, while the rest goes on.
9. **Safety unchanged.** No new network listener. The read-only rules for
   the web server and the MCP server stand. The queue starts only work that
   was asked for, through the project's own commands, so their protections
   apply as they do now: the camera's cooling, `Mount.may_move` and its
   limits, and every fail-closed check.

## The design

### 1. The job and who writes what

A job is one run of a command. It is started by the agent, the console, a
timer, the queue or another job. Each job gets its own folder,
`cache/jobs/ID/`. The ID is `YYYYMMDD-HHMMSS-name-xxxxxx`, where `xxxxxx`
is six random hex characters, so two jobs with the same name started in
the same second still differ.

The record is split into files, and each file has exactly one writer. A
file is either replaced whole (`records.write`) or added to a line at a
time by that one writer, so no update is ever lost to two writers changing
the same file:

| File | Written only by | Holds |
|---|---|---|
| `process.json` | The launcher (`ty bg`) | What started it and why (the queue item, the person's ask). Command line, redacted with `agentlog.redact`. Host, process ID, the process's start time, the boot ID. Kind (below). Phase (queued, running, exited). The exit code and when. |
| `progress.json` | The job itself, from its main thread | Step k of n and its text. The current operation and how long it may take. Waiting, and what ends the wait. The result line. |
| `heartbeat` | The job's heartbeat thread | Nothing. Only the file's modified time changes, every 30 s. The thread never calls the camera, the mount or anything else. |
| `events.jsonl` | The job itself (the launcher writes its own `started` and `exited`) | One line per event that matters, each with its own ID. |
| `log.txt` | The process's stdout and stderr, through the launcher | Every line printed, written as it happens. |
| `acks.jsonl` | The agent, through `ty jobs --ack` | What was done about each event that woke it. |

**The ending is decided once, by the reader:**
- **Done:** exit code 0 and no `failed` event.
- **Failed:** a non-zero exit code, a `failed` event, or a process that
  printed a result and then exited with an error.
- **Vanished:** the process is gone, by its process ID and start time,
  which together are never reused, and no exit was recorded. This happens
  when it was killed, crashed or ran out of memory, or the computer
  restarted.

A command run without the launcher still writes `progress.json`,
`heartbeat` and `events.jsonl`. Its `atexit` and `excepthook` handlers then
write `process.json` once, at the end.

**Kinds:**
- **Finite:** a restack, the dark test, an imaging block. It has steps and
  an expected end.
- **Service:** the keeper, the stream, the status page. It has no end and
  no percentage. It reports its state (for example, the camera at -5 °C),
  and it fails only by stopping or by its own fault events.
- **Remote:** any job whose work runs on another computer (section 6).

Waiting is a phase any job can be in, not a kind of job.

`activity.py` keeps its calls and the console keeps its view.
`activity.doing` and `activity.imaging` also write the current operation
into the job's `progress.json`. `cache/activity.json` becomes a view built
from the job records, so there is one place the state is kept.

### 2. Alive is not the same as making progress

The reader keeps four times apart:
- `heartbeat`: the process is alive.
- `last_output`: the last line printed.
- `last_progress`: the last step, milestone or reading. A reading is an
  observation, such as the sensor's temperature, and counts as progress
  only when it changes.
- `phase_deadline`: how long the current operation may take, given by the
  job (`job.expect(150, "120 s dark")`).

The job has stalled when it has gone longer than its deadline plus a margin
with no progress, however often it prints or beats. A healthy 300 s
exposure is not a stall. A camera library that hangs while the heartbeat
goes on is. A command not yet changed, which sets no deadlines, is stalled
after 10 minutes with no output.

### 3. The calls a job makes

```python
with activity.job("darktest", steps=["-5", "-7.5", "-10"], expect_s=3 * 1500) as job:
    job.expect(150, "-7.5 °C: 120 s dark 4 of 6")       # the operation now, and its deadline
    job.say("cooling: -6.2 °C, target -7.5")            # log only
    job.step(2, "-7.5 °C")                              # progress
    job.milestone("last temperature done: -9.9 °C")     # wakes the agent
    job.waiting("holding cold up to 30 min", ask="./darktest.py --more TEMPS | --finish",
                holds=["camera"])
    job.resumed("taking -12 °C")
```

Entering the job also:
- prints a line at a time on stdout and stderr;
- installs the `excepthook` and `atexit` handlers;
- starts the heartbeat thread.

Children inherit `TY_JOB` and become child jobs, never sent to `DEVNULL`.

### 4. The launcher and the queue: `./ty bg`

```
./ty bg NAME [--after ID[:milestone|:released]] [--needs camera,mount,cpu,gpu] [--kind service] -- COMMAND...
```

The launcher:
- sets `PYTHONUNBUFFERED=1` and `TY_JOB`;
- writes the log to the job's `log.txt`;
- writes `process.json` and the `started` and `exited` events.

From the first day this covers every command, changed or not: output
written as it happens, a known log, the real exit code, and silence noticed.

**`--after` and `--needs` make it the queue.** The job is recorded as
`queued`, with what it waits for, and starts by itself as soon as:
- the job it is after has done, has reached the named milestone, or has
  released what it held (`:released`, for example darktest's hold letting
  go of the camera); and
- what it needs is free.

What a job holds comes from `job.waiting(..., holds=)`, the camera keeper,
and `Mount.may_move`'s owner file. A queued job never runs if the job it is
after failed. It is marked `blocked`, and the agent is woken. This is
`desktopqueue.py`'s model (lanes, `--after`, a failure stopping only what
waits on it, surviving a restart), brought to the laptop with the camera
and the mount as resources. The two share their code, and `desktopqueue.py`
keeps its CPU and GPU lanes.

On 24 November this would have read
`./ty bg moonvideo --after DARKTEST:released --needs camera -- ./ty lucky capture ...`,
and the video would have started without anyone being asked.

The queue starts only what was asked for. The commands it starts keep all
their own protections.

### 5. Events that wake the agent, kept until dealt with

These events are `wake` events: `done`, `failed`, `vanished`, `stalled`,
`milestone`, `waiting`, `blocked` and `idle` (section 7). Each one has an ID
and stays **open** until the agent records what it did about it:
`./ty jobs --ack EVENT "started the Moon video"`. Seeing an event is not
enough. The ack says the action, so "I knew, but did nothing" shows up as
an event still open.

- **`./ty jobs --watch`**, run by the agent as one Monitor for the session,
  prints one line for each new `wake` event, and nothing else.
- **On every one of the owner's messages and at the start of each
  session**, the `jobs.py` hook lists every event still open, however long
  ago it came. An event raised while no session was watching, before the
  Monitor started or across a context compaction, is still shown until it
  is dealt with.
- **A `waiting` event** says what else is queued behind what the job holds,
  so the decision it needs is plain.

### 6. Work on another computer

`remote.py` already runs the desktop's work over SSH. The changes:
- the remote command runs with output not held back, under `ty bg` on the
  desktop, in the desktop's own `cache/jobs/`;
- its lines come back through SSH into the local job's log as they happen;
- `./ty jobs` lists the desktop's jobs with `--remote HOST`, read over SSH,
  only when asked or when a local job of kind remote names one.

If the connection drops, the local job records `remote unreachable` as an
event and keeps asking every 2 minutes. The desktop job carries on under
its own launcher, and is read again when the desktop can be reached. The
desktop's own queue (`desktopqueue.py`) writes the same records.

### 7. The progress report: `./ty jobs`

`./ty jobs` gives the answer to "progress report", in this order:
1. **Open events** that need the agent or the owner.
2. **Running jobs**: name, step k of n, the current operation and its
   deadline, the last line and how old it is, the expected end.
3. **Waiting and blocked jobs**: why, what they hold, and what ends the
   wait.
4. **Queued jobs**: in order, what each is after and needs, and an
   estimate where it has one. Also the total time of queued work.
5. **The computer**: CPU, memory and disk free, and the GPU on the
   desktop, read the way `desktopqueue.py report` reads them now.
6. **The camera**: its owner, the sensor's temperature and target, from
   the keeper or the job holding it.
7. **The mount**: its owner, from `cache/mount-owner.json`.

`--json` comes with a schema, and `./ty jobs NAME --tail 20` shows one
job's last lines. It only reads, apart from `--ack`.

**Busy until:** `./ty jobs --busy-until 08:00 "the owner asked for 6-8
hours of work"` records the owner's ask. While it stands, an `idle` event
wakes the agent whenever nothing is running or queued.

### 8. Keeping to it

**`guard.py` blocks** a background project command the agent starts
without `ty bg`. The exceptions are commands `policy.py` classes as
read-only, `ty bg` and `ty jobs` themselves, and `mount.py stop`. The guard
only sees the agent's own commands, so the other ways jobs start are listed
and each one is changed to use the launcher:

| Entry point | What starts there now | Change |
|---|---|---|
| systemd timers | `storage.py --processed` (ty-archive), `schedule.py guard` (ty-night-end), `clouds.py --approach` (ty-satellite) | Their `ExecStart` runs through `ty bg`. |
| systemd services | `serve.py` (ty-serve), `stream.py` (ty-stream), the site's live stream | Recorded as `service` jobs. |
| The console | The commands in `console.WORKSTATION` and its table | Each one runs through `ty bg`, so the console and the agent see the same jobs. |
| Child processes | `schedule.py`'s blocks, the dawn flats and the camera release; `shoot.restack_later`; `patrol.py`'s commands, `history.py --keep` and `search_later` | Children through `ty bg` with `TY_JOB`. None sent to `DEVNULL`. |
| Remote | `remote.py`, `desktopqueue.py` | Section 6. |

Implementation starts with a full search of every `subprocess` call and
unit file, to confirm this list. The audit's list above is a start, not
proof that nothing is missed.

`AGENTS.md`, `CLAUDE.md` and the skills (`imaging-run`, `end-of-night`,
`discovery-night`, `nightly-setup`) say:
- start long jobs with `ty bg`, and queue what follows with `--after`;
- keep `./ty jobs --watch` running;
- answer a progress report from `./ty jobs`;
- ack each event with what was done.

### 9. Keeping it tidy

- **Old jobs:** a finished job's folder is kept for 30 days, then deleted.
  The folders of open, running, queued and waiting jobs are never deleted.
- **Logs:** each log is capped at 20 MB, with the oldest half dropped and
  the result line always kept.
- **Disk space:** if the data disk is below 5 GB free, logs are cut down
  first, before any frames are at risk. The disk filled on 2 November.
- **Redaction:** command lines and logged arguments go through
  `agentlog.redact`, as the decision record does.

### What every job promises

- Every line is written as it happens.
- During a long wait, a line at least every 5 minutes saying what it is
  waiting on and the latest reading.
- Step k of n, a deadline for the current operation, and an end time where
  one can be known.
- A `milestone` at any point a plan may continue from.
- A `waiting` event the moment it waits on a person or another command,
  saying what ends the wait and what it holds.
- Releasing what it holds as soon as it no longer needs it.
- One result line at the end.
- Children are never sent to `DEVNULL`.

Darktest's 4-hour hold becomes 30 minutes. Anything queued behind the
camera starts when the hold ends.

## The order of the work

1. **The job record**: the files and their single writers, the IDs, the
   reader's rules for the ending and for stalls, the schemas, and tidying.
   Then `ty bg` with `--after` and `--needs`, and `./ty jobs` with the
   resources. From this step every background job is covered.
2. **Events**: IDs, acks, `--watch`, the `jobs.py` hook, `--busy-until`
   and `idle`.
3. **Enforcement**: the guard's block, the search of every entry point,
   the timers, the console and the children moved onto `ty bg`, and the
   rules in `AGENTS.md`, `CLAUDE.md` and the skills.
4. **The scripts that cool the camera or take a night's minutes**:
   - `darktest` (its hold shortened, with `holds=`), `keeper` (as a
     service);
   - `calibrate` (darks and flats);
   - `shoot`, `schedule`, `patrol`;
   - `lucky`, `moon`.
5. **The long jobs that say nothing until the end**, and remote work:
   `restack`, `remote`, `desktopqueue`, `starwatch`, `precision`, `depth`,
   `transits`, `variables`, `archive`, `brokers`, `realbogus`, `plant`,
   `difference`.
6. **`runwatch.py` onto events**, and `cache/activity.json` built from the
   job records for the console and the status page.

## How it is shown to work

On the next real jobs, recorded in `docs/validation.md`:
- a cooled dark or flat run with a camera job queued behind it;
- a night's imaging schedule;
- a restack on the desktop;
- a night of work left running with `--busy-until`.

For each one, the record should show:
- a progress report given while it ran, with the figures of the last
  minute;
- the queued job starting by itself within a minute of the camera being
  released;
- the agent woken within a minute of each `wake` event, and every event
  acked with what was done;
- a job killed by hand reported as vanished;
- no `idle` time left unanswered while a busy-until stood.

## Out of scope

Tests and CI. A network service. A change to Python's `logging`
throughout. Retrying a failed job automatically: it is blocked and the
agent is woken. Anything that loosens the mount's or the camera's
protections.

## Decided after review

- The guard **blocks**, with the exceptions in section 8.
- Each job keeps **its own event file**, read together by the reader, so no
  two processes ever append to one file, on Linux or Windows.
- **10 minutes** is the stall limit only for commands that set no
  deadlines. Changed commands set one for each operation.
- **One source for the state**: the job records. `cache/activity.json`
  becomes a view of them, and the console's calls stay as they are.
- **A heartbeat thread** that only touches its file, kept apart from
  progress, so a hung camera call shows as a stall.
- The entry points are listed in section 8, and implementation starts by
  searching for any the list misses.

## As built (24 November 2026)

### Implemented

- **The job record** (`jobs.py`): `process.json` written by its launcher
  alone (or, for a job no launcher started, by the job itself),
  `progress.json`, `heartbeat` and `events.jsonl` by the job, the log
  through the launcher, which is its only writer and caps it (20 MB, 2 MB
  when the disk has under 5 GB free) in the foreground and the background
  alike; the console's records cap theirs too. IDs with a random suffix;
  a process is the one recorded only if its number, its start time
  (Linux's `/proc`, Windows' process times) and the boot (Linux's boot ID,
  Windows' boot time) all match.
- **Whose job it is.** Every job records the Claude Code session that
  started it (`CLAUDE_CODE_SESSION_ID`, inherited by its children); timers
  and the console start the house's jobs, which have none. `./ty jobs`,
  `--watch`, the message hook and the Stop hook show a session its own
  jobs and the house's, and its own busy-until (`cache/jobs/busy-SESSION.json`);
  `--ack` takes only an event that session can see; the Stop hook counts
  only its own. The computer, camera and mount are shown to every session,
  with a count of the jobs other sessions have going (`--all` shows them).
- **The queue** (`ty bg --after JOB[:ended|:released|:MILESTONE] --needs`):
  the decision to start and the start itself are made under one lock, and
  a started job holds what it needs from that moment. First come, first
  served among jobs that could start now: one still waiting on its own
  dependencies never holds up a later one.
- **Idle** means no work getting done: no finite or remote job of the
  session running, and nothing queued behind a running one. Waiting,
  stalled and blocked jobs do not count, however much they hold.
- **Acks** record what was done, against the event's lasting ID (a
  reopened `ID:still:N` is the same event), written under the file's lock
  since every session writes there. A waiting, stall or idle event still
  there 30 minutes after its ack opens again, and the report lists "acked,
  not resolved" apart. (Seen on 24 November: before this, acking a reopened
  event left it open.)
- **Deadlines and timeouts** are apart: an operation's deadline runs from
  when `expect()` began it, and new words or changing readings do not move
  it; with or without one, a job with no output and no progress for 10
  minutes has stalled; a live process with no heartbeat for 3 minutes is
  not responding.
- **Exclusive things** (camera, mount, GPU) are held by a job that is
  running, waiting or stalled, until it ends or releases them. First come,
  first served only among earlier jobs that could start now: their
  dependencies met and everything they need free.
- **Recovery keeps the chain**: a job queued again with `--requeue`
  records the one it replaces, and a job queued behind the lost one
  follows its replacement.
- **Underused resources**: while a busy-until stands, the report says when
  the CPU or GPU is mostly idle. A note for the session, not a scheduler.
- **The session over SSH**: the launcher and `remote.py` pass the session
  (and unbuffered output) to the other computer. Seen on 24 November: the
  jobs this session launched, detached ones included, carry its session;
  the timers carry none (the house's). An agent whose session is unknown is
  told so when it starts a job, rather than its job passing silently for
  the house's.
- **Kept only once it runs a minute** (`jobs.run_as`): restack, starwatch,
  transits, variables, archive, brokers, realbogus, plant, difference,
  depth, precision, so a quick look leaves no event.
- **Fewer wake events**: a child job's ending wakes only on failure; a
  timer's routine run only on failure, a run that keeps failing being one
  event.
- **Restarts**: the launcher keeps each command in full in `argv.json`,
  readable by this user only. A job lost with a restart shows as vanished
  and says `./ty jobs --requeue JOB`, which queues it again as it was
  asked. Never by itself: a camera or mount command waits for the agent or
  the person, and keeps its own protections.
- **Hooks**: `running.py` with each message; `keepgoing.py` sends the
  agent back at most three times in fifteen minutes (it cannot loop), and
  what is undone stays open in front of the agent with each message.
- **Scripts with real progress**: the dark test (each temperature, each
  dark, the hold), the keeper (its readings, ready), darks and flats (each
  frame), imaging runs (blocks, frames through `activity`), the schedule's
  steps, the dawn flats and warm-up, and the restack (measuring,
  registering, stacking with frames done every 25, saving, each with a
  deadline sized to the frames).
- **The console** records its actions and still starts each process
  itself, so Stop kills the process holding the mount's port.
- **Unit files** written through `jobs.py bg --wait`; the three installed
  timer units were updated in place.
- **Remote** stacks run under `nohup` and the launcher on the desktop; the
  laptop follows `jobs.py --state` every two minutes if the connection
  drops. `desktopqueue.py` runs each of its jobs through the launcher.

### A copy for every other project

On 24 November 2026 the job system was copied, made general, into
Ryan-Clinton/common (`common/jobs/`, its command `cj`, and the hooks
`jobs_running.py` and `jobs_keepgoing.py`, installed by common's
`claude/install.sh`). telescopeyoke keeps its own (`./ty bg`, `./ty jobs`,
its hooks), because it is public and common is private (the owner's
decision). A fix made to one is made to the other.

### Partly done

- **Windows**: process start times and the boot time are read on Windows,
  but no job has yet run there.

- **Progress inside the other long scripts**: starwatch, transits,
  variables, archive, brokers, realbogus, plant, difference, depth and
  precision have a record, a heartbeat, an ending and their own printed
  lines, but no steps or counts yet. Each gets them when it is next worked
  on; until then a stall in one is judged by 10 minutes without output.
- **The installed services** (the stream, the status page, new-hardware)
  run the old way until next installed: reinstalling would restart the
  live stream.
- **activity.py** keeps its own `cache/activity.json` for the console and
  the stream, fed alongside the job records rather than built from them.

### Not yet proven

On real work, none of this has been run through a night: a dark or flat
run with a job queued behind it, a night's schedule, a desktop stack with
the connection dropped, a restart with jobs queued, Windows. The first
real use is the -5 °C video test of 24 November (the keeper cooling, three
videos queued behind it, the warm-up after). Each is recorded in
`docs/validation.md` when it has been seen to work.
