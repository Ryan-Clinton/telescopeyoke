# Three idle hours after a job finished, 24 November 2026

The image-processing session (`de112d71`) started a star-removal test on 20 data sets at 17:06 UT
as job `amstars`. It finished at 20:37:20. Nothing more was started until 23:31, when the owner asked
for a progress report. The desktop sat idle for three hours with known work waiting: why the blend
leaves the brightest stars on 6 of the sets.

## Timeline, from the records

| UT | What happened | Evidence |
|---|---|---|
| 17:06:04 | `amstars` queued and started under this session, needing the GPU | `cache/jobs/20261124-170603-amstars-7a639b/process.json`: `session` de112d71…, `started` |
| 19:57 | The stall check said 23 minutes without output; the agent looked, found it working, acked it and ended its turn, knowing the next step was the bright-star diagnosis once the run ended | the session's transcript; the ack in `cache/jobs/acks.jsonl` |
| 20:37:20 | `amstars` exited 0; `./ty jobs` turned that into a `done` event needing the agent | `process.json`: `phase` exited, `exit_code` 0, `ended` 1795552640 |
| 20:37 to 23:31 | Nothing ran for this session; the agent's turn had ended | no job of this session's queued or running in `cache/jobs/` |
| 23:31 | The owner's message ran the UserPromptSubmit hook, which showed the `done` event; the agent read the results and started the diagnosis | the hook's text in the owner's message; job `brightdiag` |

## The nine questions

1. **Registered under the right session?** Yes: `session` in its record is this session's id.
2. **Completion event made?** Yes, at 20:37, shown later by the hook.
3. **A watcher running at 20:37?** No. The session never started `./ty jobs --watch`, though the
   scheduling session asked every session to around midday. None of its Monitors was after that.
4. **Did the event reach the session?** Only at 23:31, through the hook on the owner's message.
5. **Could anything wake the ended turn?** Not as set up. A turn that has ended is resumed only by a
   harness notification: a background command exiting, a Monitor line, a scheduled check-in, or a
   message. `./ty bg` runs the job detached, so its end is not one of those. The Stop hook
   (`keepgoing.py`) runs only as a turn ends, and at 19:57 a job was running, so it rightly let the
   turn end. Nothing was armed to wake it later.
6. **Busy-until set?** No. The owner said "schedule them and keep going until they are all done" in
   the late morning; the session made an hourly check-in instead, which it cancelled shortly before
   noon when it thought the work was finished, and it never ran `./ty jobs --busy-until`, though the hook asked it to.
7. **Why was the follow-on not queued?** The diagnosis needed the results to choose its stacks, and the
   agent planned to start it by hand on waking, with nothing to wake it. Once the results were
   expected, it could have been queued with `--after amstars` on the stacks already known to fail.
8. **Why was three hours of idle not acted on?** The idle and underused events (`IDLE_AFTER_S`, 120 s)
   are made only while a busy-until stands; none stood. And an idle event, like any other, still
   needs something to wake the turn.
9. **Was the latest framework running?** Yes: `amstars` ran with `core` 2026-11-24.3, the same as
   `jobs.py`'s `CORE` at the time.

**Where the chain broke:** the job, its record and its events worked. The session armed nothing that
could resume its ended turn (no watcher, no waiter, no check-in), set no busy-until, and queued no
follow-on.

## A limit in the tools

A Monitor stops after 30 minutes at most (the tool's own limit) and must be re-armed when its notice
of expiry arrives. On its own it cannot cover a four-hour job. A background command that waits for a
job to end, and exits then, re-invokes the session whenever it ends, however long that takes. This
session was woken that way many times on 24 November.

## What the session does now, every time it leaves work running

1. When the owner asks for work to go on: `./ty jobs --busy-until TIME "their words"` at once.
2. For every job it starts: a background waiter that exits when the job ends, plus
   `./ty jobs --watch` as a Monitor, re-armed on expiry. The waiter waits only while the job is live
   (`while ./ty jobs --state JOB | grep -qE '"phase": "(running|waiting|stalled|queued)"'; do sleep 20; done`),
   so any end state stops it. The first version listed end states instead and missed `done`, which
   is what `--state` reports for a job that succeeded (`look()` derives it), and `blocked` and
   `cancelled`: it would never have ended after a successful job. Found by review on 24 November and
   corrected in the live waiter at once.
3. A follow-on that can be named is queued with `--after JOB` instead of being kept in mind.

## Still open

Each of these steps rests on the session remembering it, which is what failed. The fix that does not
depend on memory belongs in the shared job code (`jobs.py`, the Stop hook `keepgoing.py`), which the
scheduling session built: a `--wait JOB` and a `--wait-event` command from the job state machine
itself, and a Stop hook that will not let a turn end with work running and nothing armed to wake it.
Those were put to the scheduling session on 24 November; they are not built yet.

## Proof on a real job

Armed at about 23:40 on the bright-star diagnosis (`brightdiag2`): busy-until 06:00, a background
waiter on that job, and the watcher. The turn then ended. The result, whether the session resumed
by itself when the job finished, is recorded below once it happens.
