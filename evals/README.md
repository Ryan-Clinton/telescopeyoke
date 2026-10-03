# Agent scenarios

`scenarios.json` lists situations an agent should handle well: what it is
asked, which tools it should reach for, the error it should meet, what a good
answer says, and what it must not do.

`tests/test_interface.py` sets up each situation against the simulated mount
and checks that the interface gives an agent the facts it needs: the right
error code, the lock reported, no motion tools on the read-only servers.

Running the scenarios with a real model in the loop (does it actually choose
those tools and give that answer?) is not automated yet. To try one by hand,
connect the MCP server (`docs/agents/mcp.md`), put the question to the model,
and compare with `good_answer` and `must_not`.
