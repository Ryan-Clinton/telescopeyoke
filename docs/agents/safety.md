# Safety

The mount is real machinery and the software cannot see what it is about to
hit. On the first night an agent sent an extra slew nobody had asked for,
while the handset was in a state where it moved the mount by the wrong
amount, and the telescope hit something clipped to a tripod leg. The rules
come from that.

## Rules

1. **A person asks for each move.** Agents plan and check; people decide.
2. **Check first.** `ty mount goto NAME --dry-run --json` says what would
   happen and applies every limit, with no hardware involved.
3. **Never weaken a limit to make a request succeed.** Report the refusal.
4. **Never remove `MOTION_LOCKED`,** and never work round it.
5. **`stop` is always allowed.**
6. **The handset must be set up** after every power-on. `mount.py` refuses
   otherwise (`HANDSET_NOT_SET_UP`).
7. **Never point near the Sun.**

## What enforces them today

The limits, the lock file and the handset check are in `mount.py` and covered
by tests against `simulator.py`. The web API and the MCP server offer no
motion at all. Rule 1 is a convention: nothing in the code can tell a person's
request from an agent's own idea when both run the same command.

## Planned: approval that an agent cannot grant itself

Not built. The design, for when motion is ever offered to agents through
MCP: a small daemon owns the serial port and holds `motion_armed_until`;
arming is only possible from a local, human-facing action (a key press at the
laptop, or a confirmation on the handset), never through the agent interface;
an unarmed request returns `MOTION_APPROVAL_REQUIRED`. A `--yes` flag or an
`arm` command that the agent can run itself is not a safety barrier and must
not be added.
