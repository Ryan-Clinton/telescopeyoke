#!/usr/bin/env python3
"""A read-only MCP server: lets a language model look at the telescope.

    ./mcp_server.py            speaks the Model Context Protocol on stdin/stdout

For Claude Code:   claude mcp add telescopeyoke -- /path/to/telescopeyoke/mcp_server.py
Other MCP hosts take the same command in their own configuration.

It offers the night plan, targets, the hardware's state, the current imaging
run, and a check of whether a GoTo would be allowed. It cannot move the mount,
take a picture or change anything: every tool here only reads. Moving the
telescope stays with a person at the command line.

The protocol is small enough to speak directly (newline-delimited JSON-RPC),
so this needs no extra library.
"""
import json
import sys
from pathlib import Path

import agent
import interface

PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
READ_ONLY = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True}
DEMO = {"demo": {"type": "boolean", "description": "Use made-up weather at the example site."}}

# name: (description, argument properties, required arguments, function, fetches from the internet)
TOOLS = {
    "get_agent_context": (
        "Start here. A short plain-text briefing: tonight's verdict, what hardware is "
        "connected, the current imaging run, and the rules about moving the mount.",
        DEMO, [], lambda a: {"text": agent.context(a.get("demo", False))}, True),
    "get_capabilities": (
        "What can be done right now (planner, mount, camera, plate solver, imaging), what is "
        "missing and why, and the motion limits.",
        {}, [], lambda a: agent.capabilities(), False),
    "get_status": (
        "The state of the mount, camera, imaging run and plate solver, each as a fixed word "
        "such as 'idle' or 'capturing'.",
        {}, [], lambda a: agent.status(), False),
    "get_night_plan": (
        "Tonight in brief: GO / MARGINAL / NO-GO, the clear window, darkness, the Moon, and "
        "the three best targets now.",
        DEMO, [], lambda a: agent.night(a.get("demo", False)), True),
    "list_targets": (
        "The best targets tonight, best first, with when and where each is best and why it "
        "ranks as it does.",
        {"limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
         "kind": {"type": "string", "description": "e.g. galaxy, planet, globular, nebula"},
         "now_only": {"type": "boolean", "description": "Only targets observable right now."},
         **DEMO}, [],
        lambda a: agent.targets(a.get("limit", 10), a.get("kind"), a.get("now_only", False),
                                a.get("demo", False)), True),
    "get_target": (
        "One catalogue object or bright star: where it is in the sky now, and whether a GoTo "
        "to it would be allowed.",
        {"name": {"type": "string", "description": "e.g. M27, NGC 7000, Ring Nebula, Vega"}, **DEMO},
        ["name"], lambda a: agent.target(a["name"], a.get("demo", False)), False),
    "get_current_session": (
        "The newest imaging run: frames taken, accepted and rejected, the newest frame's "
        "star quality, and why frames were dropped. Ask for frames only when investigating.",
        {"include_frames": {"type": "boolean", "default": False},
         "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50}}, [],
        lambda a: agent.session(a.get("include_frames", False), a.get("limit", 50)), False),
    "get_observing_state": (
        "One snapshot of what bears on the picture: sky, focus, tracking and the imaging run, "
        "with notes naming the likely cause when quality is falling (cloud, focus, tracking).",
        DEMO, [], lambda a: agent.observing(a.get("demo", False)), True),
    "simulate_goto": (
        "Check a GoTo without moving anything: is the target high enough and within the "
        "mount's limits, which side of the mount, and any warnings. This never moves the "
        "telescope; a person must run the real command.",
        {"target": {"type": "string"}}, ["target"],
        lambda a: _simulate(a["target"]), False),
}

RESOURCES = {
    "telescope://status": ("Hardware and imaging state", lambda: agent.status()),
    "telescope://capabilities": ("What can be done right now", lambda: agent.capabilities()),
    "telescope://night": ("Tonight in brief", lambda: agent.night()),
    "telescope://session/current": ("The newest imaging run", lambda: agent.session()),
    "telescope://observing": ("Sky, focus, tracking and imaging in one snapshot",
                              lambda: agent.observing()),
}


def _simulate(name):
    import config
    import mount
    site = (config.load() if config.FILE.exists() else config.example())["site"]
    plan = mount.plan_goto(name, site)
    plan.pop("side_note", None)
    return plan


# Which file in schemas/ describes each tool's data.
OUTPUT = {"get_agent_context": "context", "get_capabilities": "capabilities", "get_status": "status",
          "get_night_plan": "night", "list_targets": "targets", "get_target": "target",
          "get_current_session": "image-session", "get_observing_state": "observing",
          "simulate_goto": "goto-plan"}
SCHEMAS = Path(__file__).parent / "schemas"


def output_schema(tool):
    """The envelope with this tool's data spelt out. A refusal carries empty data."""
    read = lambda name: json.loads((SCHEMAS / f"{name}.schema.json").read_text(encoding="utf-8"))
    whole, data = read("envelope"), read(OUTPUT[tool])
    for key in ("$schema", "$id"):
        whole.pop(key, None)
        data.pop(key, None)
    whole["properties"]["data"] = {"anyOf": [data, {"type": "object", "maxProperties": 0}]}
    return whole


def tool_list():
    return [{"name": name, "description": description,
             "inputSchema": {"type": "object", "properties": properties, "required": required},
             "outputSchema": output_schema(name),
             "annotations": dict(READ_ONLY, openWorldHint=online)}
            for name, (description, properties, required, _, online) in TOOLS.items()]


def call_tool(name, arguments):
    if name not in TOOLS:
        raise KeyError(name)
    result = interface.run(name, lambda: TOOLS[name][3](arguments or {}))
    text = json.dumps(result, default=interface.jsonable)
    return {"content": [{"type": "text", "text": text}],
            "structuredContent": json.loads(text), "isError": not result["ok"]}


def handle(message):
    """Answer one JSON-RPC message; None for notifications."""
    method, params, ident = message.get("method"), message.get("params") or {}, message.get("id")
    if ident is None:
        return None   # a notification, such as notifications/initialized

    def reply(result):
        return {"jsonrpc": "2.0", "id": ident, "result": result}

    def fail(code, text):
        return {"jsonrpc": "2.0", "id": ident, "error": {"code": code, "message": text}}

    if method == "initialize":
        asked = params.get("protocolVersion")
        return reply({
            "protocolVersion": asked if asked in PROTOCOLS else PROTOCOLS[0],
            "capabilities": {"tools": {}, "resources": {}},
            "serverInfo": {"name": "telescopeyoke", "version": agent.VERSION},
            "instructions": "Read-only view of a telescope. Call get_agent_context first. "
                            "Nothing here moves the mount; use simulate_goto to check a move, "
                            "then ask the person to run it.",
        })
    if method == "ping":
        return reply({})
    if method == "tools/list":
        return reply({"tools": tool_list()})
    if method == "tools/call":
        try:
            return reply(call_tool(params.get("name"), params.get("arguments")))
        except KeyError:
            return fail(-32602, f"Unknown tool: {params.get('name')}")
    if method == "resources/list":
        return reply({"resources": [{"uri": uri, "name": name, "mimeType": "application/json"}
                                    for uri, (name, _) in RESOURCES.items()]})
    if method == "resources/read":
        uri = params.get("uri")
        if uri not in RESOURCES:
            return fail(-32002, f"Unknown resource: {uri}")
        result = interface.run(uri, RESOURCES[uri][1])
        return reply({"contents": [{"uri": uri, "mimeType": "application/json",
                                    "text": json.dumps(result, default=interface.jsonable)}]})
    return fail(-32601, f"Method not found: {method}")


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            answer = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        else:
            answer = handle(message)
        if answer is not None:
            sys.stdout.write(json.dumps(answer) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
