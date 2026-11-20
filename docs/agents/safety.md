# Safety

## Rules

1. **No approval asking.** What the person asks for, and every slew of the
   night's plan, goes at once after its dry run.
2. **Check first.** `ty mount goto NAME --dry-run --json` says what would
   happen and applies every limit, with no hardware involved.
3. **Never weaken a limit to make a request succeed.** Report the refusal.
4. **Never remove `MOTION_LOCKED`,** and never work round it.
5. **`stop` is always allowed.**
6. **The handset must be set up** after every power-on. `mount.py` refuses
   otherwise (`HANDSET_NOT_SET_UP`).
7. **Never point near the Sun.**

## What enforces them today

The limits, the lock file and the handset check are in `mount.py`, in
`Mount.may_move` and the plan every aimed move passes; a change to them is
tried in the demo against `simulator.py` and proven at the telescope
(`docs/validation.md`). There are no automated tests. The web API and the MCP server offer no
motion at all. The control console (`console.py`) offers motion to a person
at this computer only: it listens on `127.0.0.1`, needs a key made at
start-up, shows the dry-run plan and moves only on that plan being
confirmed, and makes the plan again at the moment of confirming. It runs
`mount.py` and the other scripts as they are, so the limits and the lock
apply unchanged. A program on the same computer running `mount.py`
itself gets the same limits and lock, and while another command is moving
the mount its moves are refused (`MOUNT_IN_USE`: one command, with the
children it starts, holds the mount from its first move to its end). Rule 1 is a convention: nothing in the code can tell a person's
request from an agent's own idea when both run the same command.

**Weather is advice, not protection.** `clouds.py` and `rain.py` choose
when to observe and warn the house (`alert.py`); nothing here closes a
roof or covers a telescope. A telescope left out unattended needs its own
local protection, and TelescopeYoke should obey it, never stand in for it.

## Planned: approval that an agent cannot grant itself

Not built. The design, for when motion is ever offered to agents through
MCP: a small daemon owns the serial port and holds `motion_armed_until`;
arming is only possible from a local, human-facing action (a key press at the
laptop, or a confirmation on the handset), never through the agent interface;
an unarmed request returns `MOTION_APPROVAL_REQUIRED`. A `--yes` flag or an
`arm` command that the agent can run itself is not a safety barrier and must
not be added.
