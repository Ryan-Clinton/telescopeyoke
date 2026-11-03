---
name: discovery-night
description: Plan and run a night hunting for novae, new transients and strange stars (Tabby's star and its proposed companion's transit windows, AAVSO campaigns, exoplanet transits), with the week's papers on them and on SETI. Use when the person asks for tonight's outlook or plan, asks what to do tonight, asks to patrol M31 or M33, look for novae, or run a discovery night.
compatibility: telescopeyoke at the telescope, set up and focused (nightly-setup), with a reference for each field or a first night to make one
allowed-tools: Bash(./ty night) Bash(./ty night --json) Bash(./patrol.py * --plan) Bash(./starwatch.py * --plan) Bash(./ty candidates *) Bash(./ty watch-run --once)
---

# Discovery night

The night is `docs/discovery.md`, "Running a discovery night"; the patrol
is `docs/agents/setup-routine.md` step 6b.

0. Asked for the outlook or tonight's plan ("how's tonight looking"): start
   the research that needs no sky in the background, as the cloudy-day
   skill's A and B (`./archive.py screen`, `./seti.py sweep`), and say
   their results when they land (`./ty research` gives the surveys'
   coverage and the leads waiting, in one line); start
   `./brokers.py` in the background (about a minute: the surveys' new
   transients bright enough and up here tonight), run `./ty night` once
   (3 seconds), `./transits.py` and `./ty candidates` beside it, and read the last night's notes
   (`~/ryanclinton.uk/notes/DATE.md`): what was patrolled, looked at a
   second time and ruled out. Answer from all of them straight away. A
   candidate the notes rule out is dismissed at once (`python3
   candidates.py FIELD --dismiss ID --reason ... --note ...`), never
   planned for. That is
   the whole job: no patrol or starwatch plans, no reading docs or code, no
   other commands. The patrol plans only mean anything once it is dark;
   they belong to setup, step 1. Never fix or change code while answering:
   if something is broken, say so in a line at the end. Answer in this
   shape, nothing more:
   - One line: the verdict, the clear spell, when the Moon rises or sets,
     the dew. When the person is out with stars in view, their sky beats
     the forecast: give each programme's `best_time` where `best_in_clear`
     is empty, and say the forecast once, not as a reason to skip.
   - One line per `discovery` item, in its order: the programme, its
     `best_in_clear` time ("go about"), its length, and its `last_run`
     (when it was last done, and what the notes say it found). One marked NOT up
     while clear is said once as skipped tonight.
   - One line: the free time after the programmes, and the big targets
     for it from `best_tonight` (name with any `with`, what it is in a
     few words, its `frame_share` or `panels`, best time). The person
     asked for objects that fill the frame (14 October 2026). Say one
     with `nights_imaged` 0 is new, and a repeat adds to its stack.
   - One line per `other_fields` item, in its order (best value first):
     a fresh patrol field the programmes do not watch (its `field`, size,
     best time and direction), with its `why` in a few words: whether a
     reference is kept (none: tonight only makes it, later nights search
     it), when it was last watched, and any `supernova` in it (the
     reference will then hold it). Say plainly what the field can catch:
     novae in M31 and M33 only; elsewhere a supernova watch.
   - One line per `supernovae` item (bright ones on the Rochester list, up
     tonight): its name, host galaxy, magnitude and date, best time and
     direction. None, no line.
   - Any `discovery` item's `watch` with `tonight` true: its own line
     first, as the night's reason (Tabby inside a window of its proposed
     companion's transit: measure its level tonight and on the nights
     either side). Otherwise the next window, said once with its dates.
   - One line per `papers` paper on Tabby's star, dipping stars or SETI
     (its `abstract` read): what it claims, how sure (its own words), and
     what it changes for a programme; one line for how many others. A
     paper is something to read, never a result of ours. Once said, mark
     them read (`./literature.py --read ID...`).
   - One line for the `news` events (in-the-sky.org) that fall on tonight or
     the night planned: a Moon or planet approach or an occultation. The
     headlines only when asked for the news.
   - One line per whole transit from `./transits.py`: planet, depth, V,
     its window and middle altitude, and whether the timing is wanted
     (ExoClock's priority and its timings lately, and how many minutes the
     prediction may be out).
     Say any clash with a programme's go time. None, one line saying so.
   - One line per `campaigns` item (AAVSO Target Tool stars this camera
     can measure tonight, AAVSO's priority ones first, then the most
     overdue): its name and type, the section (an alert or campaign
     first), how overdue (`days_since_measured` against `cadence_days`)
     and best time. None, no line.
   - One line for the survey transients from `./brokers.py`, as soon as it
     finishes (never hold the answer for it): each one left, with its
     magnitude, whether it is brightening and its best time; none, say
     how many were looked at and that none was bright enough.
   - Any `sources` row whose `state` is `stale` or `unavailable`: one line
     naming the feed and when its data is from. Never give stale data as
     tonight's.
   - Only if `skyline_measured` is false: one line saying so.

1. `./patrol.py m31-panels --plan` (or `m31-novae`, `m33-novae`): read it
   out. Anything marked NO is said once; the focus line comes before going
   on. A panel's first good night becomes its reference by itself.
2. On their go: `./patrol.py m31-panels` in the background. Say it has
   started, then each panel's result; never a line per frame or per plate
   solve. Tell them at once only if frames stop being kept
   (`./ty watch-run --once` to check). The patrol moves the mount only through the project's
   own GoTo and imaging, with their checks.
3. When asked, or when the plan says it is due: `./starwatch.py tabby
   --plan`, then `./starwatch.py tabby` (a 10-minute look); `./transits.py`
   lists whole transits tonight, and one is taken only if they ask.
4. Each panel's answer: how deep it reached and how many candidates are
   unexplained. Show each `patrol-N.png` before calling anything a find.
   An unexplained candidate also goes to the person's phone by itself,
   and the patrol takes a second look at once.
5. For a candidate: `catalogue-researcher` with its place, then
   `candidate-vetter`. A claim is `/claim ID`, the person's to start.
6. At the end: `./patrol.py --sweep` searches anything not yet searched.

A candidate is only interesting once `./ty candidates` shows it seen on
more than one night.
