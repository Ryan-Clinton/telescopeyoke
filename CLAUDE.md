# telescopeyoke: Claude-specific notes

Read `AGENTS.md` first: it has the layout, the commands, the safety rules and
the conventions, and applies to every agent. This file only adds how Claude
works with this particular user.

- Run anything expected to take more than a minute in the background and
  carry on with the next task.
- Turn each procedure that works into a command in the project as soon as it
  works.
- Slew the real mount only when the user has asked for that move. Say first
  if the tube will swing over the pole.

## ChatGPT audit loop

The user sometimes has ChatGPT audit this project and pastes its feedback
here. These rules apply whenever that happens.

**The loop.** The user pastes ChatGPT's feedback; Claude never talks to
ChatGPT directly. Every round, do all four steps in order:

- A. Split the feedback into code changes and docs-only suggestions. The test
  is whether applying it means editing code.
- B. Apply the code changes, then check it still builds. In this project
  that means every script still parses and imports, and anything that can be
  run without moving the mount or needing clear sky still runs
  (`pytest`, `./doctor.py`, `./tonight.py --offline`, `./mount.py status`,
  `./clouds.py`).
- C. Apply the docs suggestions, and update the docs to match anything new
  from B. Docs must match the code at the end of every round.
- D. Commit and push, without asking: ChatGPT reads the public repository,
  so a round is not finished until it is pushed. Then name the path the next
  round should look at, and say "Ready for ChatGPT round N+1." The next step
  is always another round until the user says "move on".

**Skip reasons (closed list).** Every suggestion gets applied unless one of
these five applies:

1. Blocker: impossible, or breaks something that works.
2. Forces fabrication: needs data that doesn't exist.
3. Conflicts with a stated design principle, which must be named.
4. Duplicates an existing capability, which must be named.
5. Too vague to turn into a concrete change.

"Scope", "effort", "manageability" and "architectural" are not valid reasons.
Every skip is argued openly in chat. If a capability belongs somewhere else,
name where and skip on that basis rather than bolting it on.

**Hygiene.**

- No dismissing or arguing with the feedback; suggestions are treated as
  requirements.
- If a suggestion is unclear, propose a follow-up prompt for ChatGPT instead
  of ignoring it.
- ChatGPT calling the work done or scoring it highly doesn't end the audit;
  only the user does.
- Rounds count by feedback batches the user pastes, not by internal rewrites.

**End-of-round summary (required format).**

```
## Round N complete
**Code changes applied:** <what>            OR  n/a — docs-only round
**Build status:** <clean / errors>          OR  n/a — no code touched
**Docs updated:** <sections>                (ALWAYS populated)
**Skipped suggestions:** <none / list, each with its named skip reason>

Path for next round: <path>
Ready for ChatGPT round N+1. Paste feedback when ready.
```

**Patterns to pre-empt.**

- "Add a metric" usually means derive it from data already held, not fetch
  new data.
- When renaming a public field, keep the old name working as a deprecated
  alias.
- Requests for a summary or report view are usually packaging of signals that
  already exist.
- Answer the obvious reviewer question in the output itself, so it doesn't
  come back every round.

**One limit specific to this project.** A suggestion that changes how the
mount moves is applied in code like any other, but it is not run on the real
mount without the user's go-ahead. Say so in the round summary when that
applies.
