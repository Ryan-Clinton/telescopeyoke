# MCP server and web API

Both are read-only views of `agent.py`. Neither can move the mount, take a
picture or change anything.

## MCP

```bash
claude mcp add telescopeyoke -- /path/to/telescopeyoke/mcp_server.py
```

It speaks MCP over stdin/stdout with no extra library. Tools, all marked
read-only and idempotent:

| Tool | Use |
|---|---|
| `get_agent_context` | Start here: a short briefing |
| `get_capabilities` | What is available; motion limits |
| `get_status` | Mount, camera, imaging, solver states |
| `get_night_plan` | Verdict, clear window, Moon, best now |
| `list_targets` | Ranked targets (`limit`, `kind`, `now_only`) |
| `get_target` | One object: position now, whether a GoTo is allowed |
| `get_current_session` | The imaging run; frames only if asked |
| `simulate_goto` | Check a GoTo against the limits without moving |

Resources: `telescope://status`, `telescope://capabilities`,
`telescope://night`, `telescope://session/current`.

Every result is the standard envelope, as text and as structured content.
The annotations are hints to the host; the real safety is that no motion
tool exists.

## Web API

Served by `serve.py` beside the status page, GET only:

```
/api/v1/status   /api/v1/capabilities   /api/v1/night   /api/v1/context
/api/v1/targets?limit=10&kind=galaxy&now=1
/api/v1/target/M27
/api/v1/session/current?frames=1&limit=50
```

It is on the home network without a login, which is acceptable only because
it is read-only.
