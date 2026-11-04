---
name: new-command
description: Turn a procedure that has just worked by hand into a proper telescopeyoke command. Use when the person says to make something a command, or when a procedure for the telescope has just worked through steps typed by hand.
compatibility: a telescopeyoke checkout
allowed-tools: Bash(./policy.py *) Bash(git status) Bash(git diff *)
---

# A new command

CLAUDE.md: nothing used every night (focusing, alignment, a new piece of
hardware) is ever run from an inline script; it is a command
before its first real use. Write it in the style of the file next to it
(AGENTS.md, "Conventions").

1. The script, `NAME.py`, beside the others, with a docstring that starts
   with what it does and lists its uses as `./NAME.py ...` lines, and
   `--json` through `interface.main`. If it touches the mount, focuser or
   camera, `--dry-run` that checks everything and touches nothing.
2. Its class in `policy.COMMANDS` (`read_only`, `local_write`, `hardware`,
   `external`), with any words that change it and its own safe words.
   `./policy.py ./NAME.py ...` says what it now is.
3. Anything it keeps goes through `records.write`, under `config.DATA`.
4. Its answer's schema in `schemas/NAME.schema.json`.
5. For hardware, a run in the demo (`--demo`, against the simulator).
6. A line in `docs/agents/commands.md`, under the section its class puts
   it in, and a row in AGENTS.md's "Layout".
7. If `ty` should pass it on, its entry in `ty`'s `PASS_THROUGH` and
   `policy.TY_PASSES`.
8. Before committing, `ruff check NAME.py`, the `code-reviewer` agent, and `motion-reviewer` if
   it moves anything.
9. Commit and push (memory: finished work is always pushed).
