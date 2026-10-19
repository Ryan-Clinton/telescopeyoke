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
    for script, (default, instead, safe) in policy.COMMANDS.items():
        assert default in policy.CLASSES and set(instead.values()) | set(safe.values()) <= set(policy.CLASSES), script
    assert set(policy.TY.values()) <= set(policy.CLASSES)
    assert all(s in policy.COMMANDS for s in policy.TY_PASSES.values())


def test_a_safe_word_is_one_its_script_really_takes():
    # A script is only trusted with --dry-run or --plan when it has them.
    for script, (_, _, safe) in policy.COMMANDS.items():
        text = (ROOT / script).read_text(encoding="utf-8")
        for word in safe:
            assert f'add_argument("{word}"' in text, f"{script} has no {word}"


def test_a_dry_run_is_trusted_only_where_it_is_promised():
    assert policy.classify_text("./doctor.py --dry-run") == "read_only"     # read_only anyway
    assert policy.classify_text("./notify.py --test --dry-run") == "external"
    assert policy.classify_text("./sungrazer.py hunt --dry-run") == "local_write"
    assert policy.classify_text("./brokers.py --dry-run") == "local_write"


@pytest.mark.parametrize("line, kind", [
    ("./release.py --publish --help", "read_only"),
    ("./brokers.py --follow X --plan", "local_write"),
    ("./brokers.py --plan --follow X", "local_write"),
    ("./reference.py --make --help", "read_only"),
    ("./starwatch.py tabby --measure S --history", "local_write"),
    ("./starwatch.py tabby --history --measure S", "local_write"),
    ("./candidates.py M31 --reopen A --dismiss B --reason noise", "local_write"),
    ("./patrol.py m31-novae --sweep --plan", "read_only"),
    ("./mount.py --dry-run goto M27", "read_only"),
    ("./mount.py status --dry-run", "read_only"),
])
def test_combinations_resolve_the_same_whatever_their_order(line, kind):
    assert policy.classify_text(line) == kind


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
    ("./brokers.py --follow ZTF1 --plan", "local_write"),   # it fetches first
    ("./brokers.py --follow ZTF1", "hardware"),
    ("./unknown_new_thing.py", "hardware"),
    ("sudo -n -u facepipe -g dialout python3 mount.py goto Vega", "hardware"),
    ("sudo -n -u facepipe -g dialout python3 mount.py status", "read_only"),
    ("nice -n 10 ionice -c 3 ./restack.py frames/M31/a", "local_write"),
    ("timeout 15m ./shoot.py M31", "hardware"),
    ("python3 -m mount goto M27", "hardware"),
    ("python3 -m mount status", "read_only"),
    ("env TY_RIG=gary ./mount.py nudge", "hardware"),
    ("sudo --some-new-option x ./mount.py nudge", "hardware"),
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
    "ls\n./mount.py nudge",
    "git status\n  python3 shoot.py M31",
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
    allowed = {"No hardware": {"read_only", "local_write"}, "Planning a move": {"read_only"},
               "Moves the mount": {"hardware"}, "Uses the camera": {"hardware"}, "Reaches outside": {"external"}}
    for section, words in page_rows():
        kinds = next((v for k, v in allowed.items() if section.startswith(k)), None)
        if kinds is None:
            continue
        line = " ".join(["./" + words[0] if words[0].endswith(".py") else "./ty"] + [w for w in words[1:] if "[" not in w and "]" not in w])
        assert policy.classify_text(line) in kinds, f"{' '.join(words)} is under \"{section}\""


def test_running_the_schedule_is_hardware_and_planning_it_is_not():
    """schedule.py run starts moves when their time comes, so it is asked
    for like a patrol; adding to the plan or showing it moves nothing."""
    assert policy.classify(["./schedule.py", "run"]) == "hardware"
    assert policy.classify(["./schedule.py"]) == "read_only"
    assert policy.classify(["./schedule.py", "add", "x", "1", "--", "./mount.py", "goto", "M31"]) == "local_write"
