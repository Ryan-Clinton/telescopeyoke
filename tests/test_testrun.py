"""testrun.py: the counts and only the failures, from pytest's own output."""
import argparse
import subprocess

import pytest

import interface
import testrun

OUTPUT = """\
..F.s.
=================================== FAILURES ===================================
_________________________________ test_meridian _________________________________

    def test_meridian():
>       assert 1 == 2
E       assert 1 == 2

tests/test_mount.py:12: AssertionError
=========================== short test summary info ============================
FAILED tests/test_mount.py::test_meridian - assert 1 == 2
1 failed, 4 passed, 1 skipped in 3.21s
"""


def test_the_summary_is_the_counts_and_each_failure_in_short():
    counts, failures = testrun.summary(OUTPUT)
    assert counts == {"passed": 4, "failed": 1, "skipped": 1, "errors": 0, "seconds": 3.21}
    assert failures[0]["test"] == "tests/test_mount.py::test_meridian"
    assert failures[0]["why"] == "assert 1 == 2"
    assert any("assert 1 == 2" in line for line in failures[0]["first_lines"])


def fake(outputs):
    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        out = outputs.pop(0)
        return subprocess.CompletedProcess(command, 0 if "failed" not in out else 1, stdout=out, stderr="")
    return runner, calls


def test_on_the_desktop_it_copies_the_checkout_then_runs_there(monkeypatch):
    monkeypatch.setattr(testrun.remote, "python_on", lambda host: "telescopeyoke/.venv/bin/python")
    monkeypatch.setattr(testrun, "files", lambda: b"")    # the copy the tests run in has no git
    runner, calls = fake(["", OUTPUT])
    answer = testrun.run(argparse.Namespace(tests=["tests/test_mount.py"], k="meridian", here=False),
                         say=lambda s: None, runner=runner)
    assert calls[0][0] == "rsync" and calls[0][-1] == "desktop:telescopeyoke-laptop/tests/"
    assert calls[1][0] == "ssh" and "~/telescopeyoke/.venv/bin/python -m pytest" in calls[1][-1]
    assert "tests/test_mount.py -k meridian" in calls[1][-1] and "COLUMNS=1000" in calls[1][-1]
    assert answer["where"] == "desktop" and answer["failed"] == 1 and not answer["ok"]


def test_a_run_that_did_not_happen_is_a_refusal():
    runner, _ = fake(["no tests ran"])
    with pytest.raises(interface.Refusal, match="did not run"):
        testrun.run(argparse.Namespace(tests=[], k=None, here=True), say=lambda s: None, runner=runner)


def test_the_files_sent_are_the_checkout_and_not_what_git_ignores(tmp_path, monkeypatch):
    # its own repository, so it runs anywhere, the desktop's copy without .git included
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".gitignore").write_text("frames/\ncache/\nconfig.toml\n")
    for p in ("policy.py", "tests/test_new.py", "frames/a.fits", "cache/x.json", "config.toml"):
        (tmp_path / p).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / p).write_text("")
    subprocess.run(["git", "add", "policy.py"], cwd=tmp_path, check=True)    # one tracked, one new
    monkeypatch.setattr(testrun, "ROOT", tmp_path)
    sent = set(testrun.files().split(b"\0"))
    assert {b"policy.py", b"tests/test_new.py", b".gitignore"} <= sent
    assert not any(p.startswith((b"frames/", b"cache/")) or p == b"config.toml" for p in sent)


def test_not_in_a_git_checkout_is_a_refusal(tmp_path, monkeypatch):
    monkeypatch.setattr(testrun, "ROOT", tmp_path)
    with pytest.raises(interface.Refusal, match="not a git checkout"):
        testrun.files()


def test_a_reason_pytest_left_out_is_taken_from_the_exception():
    trimmed = OUTPUT.replace("FAILED tests/test_mount.py::test_meridian - assert 1 == 2",
                             "FAILED tests/test_mount.py::test_meridian")
    assert testrun.summary(trimmed)[1][0]["why"] == "assert 1 == 2"
