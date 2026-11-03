---
name: discovery-night
description: Plan and run a night hunting for novae, new transients and strange stars (Tabby's star and its proposed companion's transit windows, AAVSO campaigns, exoplanet transits), with the week's papers on them and on SETI. Use when the person asks for tonight's outlook or plan, asks what to do tonight, asks to patrol M31 or M33, look for novae, or run a discovery night.
compatibility: telescopeyoke at the telescope, set up and focused (nightly-setup), with a reference for each field or a first night to make one
allowed-tools: Bash(./ty outlook) Bash(./ty night) Bash(./ty night --json) Bash(./ty research) Bash(./ty research *) Bash(./ty context) Bash(./patrol.py * --plan) Bash(./starwatch.py * --plan) Bash(./ty candidates) Bash(./ty candidates *) Bash(./ty watch-run --once) Bash(./transits.py) Bash(./transits.py *) Bash(./brokers.py) Bash(./literature.py *) Bash(./archive.py screen *) Bash(./seti.py sweep *) Bash(./investigate.py) Bash(./investigate.py *)
---

# Discovery night

The night is `docs/discovery.md`, "Running a discovery night"; the patrol
is `docs/agents/setup-routine.md` step 6b.

0. Asked for the outlook or tonight's plan ("how's tonight looking"): one
   message of tool calls, all at once, then the answer:
   - one Bash call in the background (`run_in_background`), each job to
     its own log in the scratchpad (`S`) and its exit status printed, so
     one that fails is seen:
     `(./brokers.py > $S/brokers.log 2>&1; echo "brokers exit $?") &
     ./archive.py screen --batch 200 > $S/archive.log 2>&1; echo "archive exit $?";
     ./seti.py sweep KIC8462852 --blocks 3 > $S/seti.log 2>&1; echo "seti exit $?";
     ./investigate.py > $S/investigate.log 2>&1; echo "investigate exit $?"; wait`
     (the cloudy-day skill's A and B, the leads waiting, and the surveys'
     new transients). When it finishes, read the exit lines first: a
     non-zero one is said, with its log's last lines, in the follow-up;
   - `./ty outlook` (3 seconds: `./ty night`'s answer as short text, the
     recommendation first, the candidates seen on more than one night,
     the newest two unread papers on each topic and a count of the rest);
   - `./transits.py`;
   - the last night's notes (`~/ryanclinton.uk/notes/DATE.md`): what was
     patrolled, looked at a second time and ruled out, and how the sky
     really was (fog the forecast missed).

   Answer from those straight away. Use `./ty night --json` only for a
   field the outlook leaves out. A candidate the notes rule out is
   dismissed at once (`python3 candidates.py FIELD --dismiss ID --reason
   ... --note ...`), never planned for. That is the whole job: no patrol
   or starwatch plans, no reading docs or code, no other commands. The
   patrol plans only mean anything once it is dark; they belong to setup,
   step 1. When the background job finishes, say its results in their own
   short message: the brokers' line (below), and each lead
   `./investigate.py` looked into with its verdict. If something is
   broken, say so in a line at the end and fix it afterwards, in the
   background. Answer in this shape, nothing more:
   - First, the decision: `RECOMMENDATION`'s steps as one or two lines,
     what to do with the clear spell, in order, and why (a watch window,
     a lead, the programme's last run), and what is left out and why.
     Adjust it from the notes and say so: a field the fog spoilt last night
     is worth repeating, and a measurement that needs steady sky (Tabby's
     level, a transit) is not forced through fog. With no clear spell
     forecast, say so and that the research carries on; the person's own
     sky still beats the forecast. Then the detail below.
   - Before choosing anything, weigh the research against the sky, in
     `docs/discovery.md`'s order ("What the project is for"): a watch
     window tonight first; then any `research.observe_tonight` lead (still
     unexplained or only likely explained, watchable, up tonight), said
     with why it is interesting (`why_interesting`) and what one look
     would settle (whether the dips go on), and planned before the routine
     patrol; then the programmes. Say the research queue in one line
     (waiting, to ask again, unexplained), then the next lead to be looked
     into (`next to look into`, why it was flagged) and the most
     intriguing one already looked into (its verdict, and whether this
     telescope can watch it). Never give a likely-explained lead as the
     queue's best open one.
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
     (its `abstract` read): what it claims, how sure (its own words,
     quoted exactly and whole), and what it changes for a programme; one
     line for how many others, older ones counted, not listed. A
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
   - The `campaigns` (AAVSO Target Tool stars this camera can measure
     tonight): say how many and that AAVSO itself marks them priority (its
     Alerts / Campaigns section is what makes one wanted). Then one line
     each for the best two or three at most, chosen by AAVSO's priority,
     the time free after the programmes, and whether the star's range
     reaches this camera's depth (about G 17 clear, 16 in fog: a star that
     only gets that bright now and then is a look, not a sure measure).
     Its `days_since_measured` says how neglected it is, not how urgent.
     The rest as a count. None, no line.
   - The survey transients from `./brokers.py` come in the follow-up
     message when the background job finishes (never hold the answer for
     it): each one left, with its magnitude, whether it is brightening and
     its best time; none, say how many were looked at and that none was
     bright enough.
   - Any `sources` row whose `state` is `stale` or `unavailable` (the
     outlook's `STALE` lines): one line naming the feed and when its data
     is from. Never give stale data as tonight's. Never say "all sources
     fresh": the rows cover the feeds the outlook used, not the brokers
     still running.
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
