"""policy.py: every command has its class, and the worst is assumed when unsure."""
from pathlib import Path

import pytest

import policy

ROOT = Path(__file__).resolve().parent.parent


def test_every_runnable_script_has_a_class():
    runnable = {p.name for p in ROOT.glob("*.py") if '__name__ == "__main__"' in p.read_text(encoding="utf-8")}
    missing = runnable - set(policy.COMMANDS)
    assert not missing, f"give these a class in policy.COMMANDS: {sorted(missing)}"
    assert not set(policy.COMMANDS) - runnable - {"agent.py"}, "a class for a script that is gone"


def test_every_class_is_one_of_the_four():
    for script, (default, instead) in policy.COMMANDS.items():
        assert default in policy.CLASSES and set(instead.values()) <= set(policy.CLASSES), script
    assert set(policy.TY.values()) <= set(policy.CLASSES)
    assert all(s in policy.COMMANDS for s in policy.TY_PASSES.values())


def test_ty_passes_the_same_scripts_as_ty_does():
    text = (ROOT / "ty").read_text(encoding="utf-8")
    passed = text.split("PASS_THROUGH = {", 1)[1].split("}", 1)[0]
    for name in policy.TY_PASSES:
        assert f'"{name}"' in passed


@pytest.mark.parametrize("line, kind", [
    ("./mount.py goto M27", "hardware"),
    ("./mount.py goto M27 --dry-run", "read_only"),
    ("./mount.py status", "read_only"),
    ("./mount.py settime", "hardware"),
    ("./focus.py --motor", "hardware"),
    ("./focus.py --report", "read_only"),
    ("./patrol.py m31-panels --plan", "read_only"),
    ("./patrol.py m31-panels", "hardware"),
    ("./patrol.py --sweep --all-history", "local_write"),
    ("python3 shoot.py M31 --frames 0", "hardware"),
    ("py -3 mount.py nudge", "hardware"),
    (r"C:\telescopeyoke\mount.py goto Vega", "hardware"),
    (r"C:\telescopeyoke\mount.py status", "read_only"),
    (r"python C:\telescopeyoke\patrol.py --sweep", "local_write"),
    ("systemd-inhibit --what=sleep --why=x ./restack.py frames/M31/a --on desktop", "local_write"),
    ("timeout 900 ./polaralign.py --step 12", "hardware"),
    ("./ty mount goto Vega", "hardware"),
    ("./ty status --json", "read_only"),
    ("./ty run M31", "hardware"),
    ("./notify.py --test", "external"),
    ("./release.py --publish", "external"),
    ("./release.py", "local_write"),
    ("./candidates.py M31 --dismiss M31-1 --reason noise", "local_write"),
    ("./brokers.py --follow ZTF1 --plan", "read_only"),
    ("./brokers.py --follow ZTF1", "hardware"),
    ("./unknown_new_thing.py", "hardware"),
])
def test_commands_are_classed(line, kind):
    assert policy.classify_text(line) == kind


@pytest.mark.parametrize("line", [
    "./mount.py goto M27 --dry-run; ./mount.py goto M27",
    "./doctor.py --offline && ./mount.py nudge",
    "./tonight.py | ./shoot.py M31",
    "echo $(./mount.py goto M27)",
    "echo `./mount.py nudge`",
    'bash -c "./mount.py nudge"',
    "powershell -Command \"python mount.py goto Vega\"",
    "echo goto | xargs ./mount.py",
])
def test_the_worst_command_in_a_line_decides_and_hidden_ones_count_as_moving(line):
    assert policy.classify_text(line) == "hardware"


@pytest.mark.parametrize("line", ["ls -la", "git status", "grep goto mount.py", "pytest -q tests/test_mount.py",
                                  "cat MOTION_LOCKED"])
def test_lines_with_none_of_ours_have_no_class(line):
    assert policy.classify_text(line) is None


def test_a_line_that_cannot_be_read_is_taken_as_hardware():
    assert policy.classify_text("./mount.py goto 'M27") == "hardware"


def page_rows():
    """(section, command) for each row of docs/agents/commands.md naming one of ours."""
    import re
    section = None
    for line in (ROOT / "docs" / "agents" / "commands.md").read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            section = line[3:]
        found = re.match(r"\| `([^`]+)`", line)
        if found and section:
            # "home|zenith|compensate" is three commands; the first stands for them
            words = [w.replace("\\|", "|").split("|")[0] for w in found.group(1).split()]
            if words[0] == "ty" or words[0].endswith(".py"):
                yield section, words


def test_the_commands_page_files_each_command_under_what_it_may_do():
    allowed = {"Read-only": {"read_only", "local_write"}, "Planning a move": {"read_only"},
               "Moves the mount": {"hardware"}, "Uses the camera": {"hardware"}, "Reaches outside": {"external"}}
    for section, words in page_rows():
        kinds = next((v for k, v in allowed.items() if section.startswith(k)), None)
        if kinds is None:
            continue
        line = " ".join(["./" + words[0] if words[0].endswith(".py") else "./ty"] + [w for w in words[1:] if "[" not in w and "]" not in w])
        assert policy.classify_text(line) in kinds, f"{' '.join(words)} is under \"{section}\""
