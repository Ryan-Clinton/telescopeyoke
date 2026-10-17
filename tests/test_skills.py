"""The Claude Code skills and agents in .claude/: well formed, naming only
commands and options that exist, and pre-approving nothing that moves."""
import functools
import re
import subprocess
import sys
from pathlib import Path

import pytest

import policy

ROOT = Path(__file__).resolve().parent.parent
SKILLS = sorted((ROOT / ".claude" / "skills").glob("*/SKILL.md"))
AGENTS = sorted((ROOT / ".claude" / "agents").glob("*.md"))
SKILL_FIELDS = {"name", "description", "when_to_use", "argument-hint", "arguments", "disable-model-invocation",
                "user-invocable", "allowed-tools", "disallowed-tools", "model", "effort", "context", "agent",
                "background", "hooks", "paths", "shell", "metadata", "license", "compatibility"}
AGENT_FIELDS = {"name", "description", "tools", "disallowedTools", "model", "permissionMode", "maxTurns", "skills",
                "mcpServers", "hooks", "memory", "background", "effort", "isolation", "color", "initialPrompt"}
MANUAL = {"first-night", "claim", "report-comet", "release"}    # outward-facing or broad: only /NAME starts them
WEB = {"WebFetch", "WebSearch"}


def split(path):
    """(frontmatter as {key: text}, body). The frontmatter here is flat
    key: value lines, which is all these files use."""
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path} has no frontmatter"
    head, body = text[4:].split("\n---\n", 1)
    fields = {}
    for line in head.splitlines():
        if line.strip():
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip()
    return fields, body


def ids(paths):
    return [str(p.relative_to(ROOT)) for p in paths]


@pytest.mark.parametrize("path", SKILLS, ids=ids(SKILLS))
def test_a_skill_is_well_formed(path):
    fields, body = split(path)
    assert set(fields) <= SKILL_FIELDS, set(fields) - SKILL_FIELDS
    assert fields["name"] == path.parent.name and re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", fields["name"])
    assert 0 < len(fields["description"]) <= 1024
    assert len(fields.get("compatibility", "")) <= 500
    assert len(body.splitlines()) < 150, "keep a skill short: the detail belongs in docs/"
    if fields["name"] in MANUAL:
        assert fields.get("disable-model-invocation") == "true"


@functools.cache
def options(script):
    done = subprocess.run([sys.executable, str(ROOT / script), "--help"], capture_output=True, text=True,
                          cwd=ROOT, timeout=120)
    return set(re.findall(r"--[a-z][a-z-]*", done.stdout))


def named_commands(text):
    """Each project command written in a skill, as its words."""
    for span in re.findall(r"`(\./[^`]+)`", text) + re.findall(r"Bash\((\./[^)]+)\)", text):
        words = span.split()
        if words[0] == "./ty" and len(words) > 1 and words[1] in policy.TY_PASSES:
            yield policy.TY_PASSES[words[1]], words[2:]
        elif words[0] == "./ty":
            yield "ty", words[1:]
        elif not re.search(r"[A-Z]{3,}", words[0]):    # ./NAME.py is a placeholder, not a command
            yield words[0][2:], words[1:]


@pytest.mark.parametrize("path", SKILLS, ids=ids(SKILLS))
def test_every_command_and_option_a_skill_names_exists(path):
    for script, words in named_commands(path.read_text(encoding="utf-8")):
        assert (ROOT / script).exists(), f"{path.parent.name} names {script}, which is not here"
        if script == "ty":
            continue
        for flag in (w for w in words if w.startswith("--")):
            assert flag in options(script), f"{path.parent.name}: {script} has no {flag}"


@pytest.mark.parametrize("path", SKILLS, ids=ids(SKILLS))
def test_a_skill_pre_approves_only_what_is_read_only(path):
    fields, _ = split(path)
    for rule in re.findall(r"Bash\(([^)]+)\)", fields.get("allowed-tools", "")):
        command = rule.replace("*", "X")
        assert policy.classify_text(command) in (None, "read_only"), f"{path.parent.name} pre-approves {rule}"
    assert not re.search(r"(^|\s)Bash(\s|$)", fields.get("allowed-tools", "")), "never all of Bash"


@pytest.mark.parametrize("path", AGENTS, ids=ids(AGENTS))
def test_an_agent_is_well_formed_and_has_the_fewest_tools(path):
    fields, _ = split(path)
    assert set(fields) <= AGENT_FIELDS, set(fields) - AGENT_FIELDS
    assert fields["name"] == path.stem and fields["description"]
    assert int(fields["maxTurns"]) > 0, "every agent stops"
    tools = set(re.findall(r"[A-Za-z]+", fields["tools"]))
    assert not (tools & WEB and tools & {"Bash", "Read", "Grep", "Glob"}), "the web apart from the checkout"
    if fields["name"] != "docs-keeper":
        assert not tools & {"Edit", "Write", "MultiEdit", "NotebookEdit"}, "only docs-keeper writes"


def test_every_skill_has_a_scenario_and_some_say_nothing_should_happen():
    import json
    scenarios = json.loads((ROOT / "evals" / "skills.json").read_text(encoding="utf-8"))
    names = {p.parent.name for p in SKILLS}
    assert {s["skill"] for s in scenarios} - {None} <= names, "a scenario for a skill that is not here"
    assert names <= {s["skill"] for s in scenarios}, "every skill has a scenario"
    assert sum(s["skill"] is None for s in scenarios) >= 2, "cases where nothing should start"
    for s in scenarios:
        assert s["must_not"] and s["says"] and s["good_answer"]
        if s["first"]:
            assert policy.classify_text(s["first"]) in (None, "read_only"), "a skill starts by looking"


@pytest.mark.parametrize("path", AGENTS, ids=ids(AGENTS))
def test_an_agent_with_a_shell_has_the_read_only_hook(path):
    import json
    fields, _ = split(path)
    if "Bash" not in fields["tools"]:
        return
    hooks = json.loads(fields["hooks"])["PreToolUse"]
    rules = [(e["matcher"], h) for e in hooks for h in e["hooks"]]
    assert any("Bash" in m and h["args"][-1] == "read-only-bash" and h.get("onFailure") == "block"
               for m, h in rules), f"{path.stem} has a shell without the read-only hook"


@pytest.mark.parametrize("path", AGENTS, ids=ids(AGENTS))
def test_an_agent_that_writes_has_the_docs_only_hook(path):
    import json
    fields, _ = split(path)
    if not set(re.findall(r"[A-Za-z]+", fields["tools"])) & {"Edit", "Write"}:
        return
    hooks = json.loads(fields["hooks"])["PreToolUse"]
    assert any("Edit" in e["matcher"] and h["args"][-1] == "docs-only" and h.get("onFailure") == "block"
               for e in hooks for h in e["hooks"])
