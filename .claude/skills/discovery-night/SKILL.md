---
name: discovery-night
description: Plan and run a night hunting for novae, new transients and strange stars (Tabby's star and its proposed companion's transit windows, AAVSO campaigns, exoplanet transits). Use when the person asks what is interesting tonight, for tonight's outlook or plan, what to do tonight, for the research or papers, asks to patrol M31 or M33, look for novae, or run a discovery night.
compatibility: telescopeyoke at the telescope, set up and focused (nightly-setup), with a reference for each field or a first night to make one
allowed-tools: Bash(./ty outlook) Bash(./ty night) Bash(./ty night --json) Bash(./ty research) Bash(./ty research *) Bash(./ty context) Bash(./patrol.py * --plan) Bash(./starwatch.py * --plan) Bash(./ty candidates) Bash(./ty candidates *) Bash(./ty watch-run --once) Bash(./transits.py) Bash(./transits.py *) Bash(./brokers.py) Bash(./literature.py *) Bash(./archive.py screen *) Bash(./seti.py sweep *) Bash(./investigate.py) Bash(./investigate.py *)
---

# Discovery night

The night is `docs/discovery.md`, "Running a discovery night"; the patrol
is `docs/agents/setup-routine.md` step 6b.

0. Asked what's interesting tonight, the outlook or tonight's plan: what
   to look at through the telescope, from now. One message of tool calls,
   all at once, then the answer:
   - one Bash call in the background (`run_in_background`), each job to
     its own log in the scratchpad (`S`) and its exit status printed:
     `(./brokers.py > $S/brokers.log 2>&1; echo "brokers exit $?") &
     ./archive.py screen --batch 200 > $S/archive.log 2>&1; echo "archive exit $?";
     ./seti.py sweep KIC8462852 --blocks 3 > $S/seti.log 2>&1; echo "seti exit $?";
     ./investigate.py > $S/investigate.log 2>&1; echo "investigate exit $?"; wait`
     (the research goes on; it is not the answer);
   - `./ty outlook` (3 seconds: the plan from now, the other choice, the
     sky, the candidates worth a second look, and only what is up tonight);
   - `./transits.py`;
   - the last night's notes (`~/ryanclinton.uk/notes/DATE.md`): what was
     patrolled and how the sky really was (fog the forecast missed).

   Answer from those at once, short and in plain words, at most about
   eight lines:
   - The plan (`PLAN`): when it can start (with the setup time when
     nothing is set up), the steps in order and why each, in a line or two.
     Adjust it from the notes and say so: a field the fog spoilt last night
     is worth repeating. With no steps, say why (no clear spell, or not
     enough left) and what to try if the sky clears where they are; their
     sky beats the forecast.
   - The other choice (`OR`): each big target in a few words, how much of
     the frame it fills or its mosaic, its best time, and whether it is new.
   - The sky in one line: the clear spell, the Moon, dew or fog.
   - A `CANDIDATE` not in the plan: one line, and whether it is worth
     swapping in.
   - Only when present: a `LEAD UP TONIGHT` (why it is interesting and what
     one look settles), a whole transit from `./transits.py` (planet, depth,
     window, whether the timing is wanted), a `SUPERNOVA` bright enough to
     catch (mag 14 or brighter) or in a field the plan visits, an `EVENT`,
     a `STALE` feed (never given as tonight's), `SKYLINE`.
   - Nothing else: no papers, no research queue, no AAVSO list, no
     background jobs. `./ty night --json` only for a field the outlook
     leaves out. A candidate the notes rule out is dismissed at once
     (`python3 candidates.py FIELD --dismiss ID --reason ... --note ...`),
     never planned for.

   When the background job finishes, a follow-up message only if there is
   something to say: a survey transient bright enough for this camera (its
   magnitude, whether it is brightening, its best time), a lead
   `./investigate.py` found unexplained and watchable, or a job that failed
   (its exit line and its log's last lines; fix it in the background).
   Otherwise nothing.

   Asked for the research or the papers: `./ty research` and `./ty night`'s
   `papers`. Then the research queue in one line (waiting, to ask again,
   unexplained), the next lead to look into and why it was flagged, the
   most intriguing one already looked into (never a likely-explained one as
   the best open one), and one line per paper on Tabby's star, dipping
   stars or SETI (its `abstract` read): what it claims, how sure in its own
   words quoted exactly and whole, and what it changes for a programme;
   then mark them read (`./literature.py --read ID...`). A paper is
   something to read, never a result of ours.

   Asked for more of the night (the programmes, other fields, AAVSO): from
   `./ty night`: each programme's `best_in_clear` time, length and
   `last_run`; `other_fields` (novae in M31 and M33 only, elsewhere a
   supernova watch); the AAVSO `campaigns` by AAVSO's priority and whether
   the star's range reaches about G 17 (16 in fog).

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
