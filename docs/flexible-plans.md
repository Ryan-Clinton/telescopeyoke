# Flexible plans

Things go wrong at night and plans change: a camera jams, cloud comes over,
the house turns out to be in the way, a candidate needs a second look. A
change of plan should be one command, made while the night runs, never a
stopped runner and a file edited by hand. This page says how, and what is
left to build. It comes from the night of 1 to 2 November 2026, when nearly
every hitch came from changing the plan.

## What went wrong on 1 November 2026

- **Changing the plan meant stopping the runner.** To start a transit early,
  to insert the M31 second look, to finish M33 early: each time the runner
  was killed, `cache/schedule.json` edited by hand and the runner started
  again. Once a stopped step counted as failed and was nearly run again.
- **Private timers stopped the wrong run.** A `ty run stop` timed for 01:55
  to end M33 fired after M33 had already been stopped by hand, and ended the
  M31 second look nine minutes early.
- **Patrols counted frames, not time.** With the camera losing frames, a
  75-minute M33 patrol was heading for three hours and the plan's next
  targets.
- **A search held the telescope.** The patrol searched its stack before it
  let the mount go: seven minutes of an idle telescope.
- **A target behind the house.** TOI-2046 b was planned from a spot with no
  measured skyline, and the house corner took the whole transit.
- **Nothing filled a lost step.** When TOI-2046 b went, the telescope waited
  for a person to choose what next.

## Built

1. **Stop orders name their run** (`shoot.tell(order, run=TARGET)`). An
   order for another run is left for it, and one older than 10 minutes
   (`shoot.ORDER_STALE_S`) is thrown away. `./ty run stop` with no run named
   still stops whatever is running.
2. **Every step ends on its own clock, gracefully.** A step with `--until`
   tells its `shoot.py` or `patrol.py` how many minutes it has (`--minutes`),
   so it finishes after its frame and keeps its picture; the hard stop comes
   15 minutes later as a backstop only. `shoot.py --minutes` ends a run on
   time whatever the camera loses, and patrols pass their programme's time.
3. **The plan changes while it runs.** The runner reads the plan again before
   every step, so these act at once, with no restart:

       ./schedule.py next              end the running step gracefully, on to the next
       ./schedule.py skip N            leave out queued step N (its number as shown)
       ./schedule.py move N POS        put queued step N at place POS
       ./schedule.py add LABEL MIN --at POS -- COMMAND   insert a step at a place

4. **Patrols release the telescope by default.** Once the frames are in, the
   picture and the search go on in the background (`patrol.py --analyse`)
   and the schedule moves on; `--wait` holds the telescope for an immediate
   second look as before.

5. **The path checked before a target is planned.** Each step still to come
   that points at something (`shoot.py NAME`, `patrol.py PROGRAMME`, a
   `goto NAME`) has its target's bearing and height at the step's start,
   middle and end checked against the floor, the spot's blocked list and its
   measured skyline. `./schedule.py` prints a line under a step whose target
   is behind something, or that is checked without a skyline, and `add`
   says the same as the step goes in. From ralphie-side the house corner
   that took TOI-2046 b (bearings 333-340° to 70°) is in the spot's blocked
   list. The morning's daylight survey of 2 November was set aside (every
   look burnt out in the low Sun, `docs/validation.md`); the afternoon's
   survey was kept on the person's eye check
   (`horizon.py --use-aside`), so steps from there are checked against that
   skyline as well as the blocked list. It is too cautious in the
   south-west gap (bearings 210-228°) until a morning survey measures it.
6. **A lost step filled.** `./schedule.py fill` finds the first gap in the
   schedule from now (a wait of 10 minutes or more before a step that keeps
   to the clock, or the open time after the last step) and offers the first
   of tonight's discovery programmes, in the order they come best, that is
   up for the whole of it, fits it, has not been done tonight, and whose
   path is clear by item 5, as one `./schedule.py add ... --at N` command.
   `skip` makes the same offer, and so does the call that fetches the
   person when a step has failed its tries. It offers; the person, or I,
   take it with that one command.
7. **A runner takes up new code between steps.** `./schedule.py run` is one
   long process; when `schedule.py` changes on disk it starts again with the
   new code before its next step, the same process, plan and log. On 2
   November 2026 the runner started at 02:03 ran M81 and M82 and SN 2026sqf
   with the code from before steps were told their time: both were cut off
   at their end time by the backstop, unstacked, and stacked in the morning
   with `restack.py`.
