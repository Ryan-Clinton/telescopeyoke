"""records.py: whole or not at all, one writer at a time, checked, stamped."""
import json
import multiprocessing
import sys

import jsonschema
import pytest

import records


def test_a_record_is_written_whole_and_leaves_no_part_behind(tmp_path):
    path = tmp_path / "a" / "b.json"
    records.write(path, {"x": 1})
    assert json.loads(path.read_text(encoding="utf-8")) == {"x": 1}
    assert not list(path.parent.glob("*.part"))


def test_a_failed_write_leaves_the_old_file_as_it_was(tmp_path):
    path = tmp_path / "b.json"
    records.write(path, {"x": 1})
    with pytest.raises(TypeError):
        records.write(path, {"x": object()})   # cannot be turned into JSON
    assert json.loads(path.read_text(encoding="utf-8")) == {"x": 1}


def test_a_record_that_does_not_match_its_schema_is_not_written(tmp_path):
    path = tmp_path / "candidates.json"
    records.write(path, {"name": "M31", "candidates": []}, schema="candidates")
    with pytest.raises(records.Rejected, match="candidates"):
        records.write(path, {"name": "M31"}, schema="candidates")
    assert json.loads(path.read_text(encoding="utf-8")) == {"name": "M31", "candidates": []}
    assert json.loads((tmp_path / "candidates.rejected.json").read_text(encoding="utf-8")) == {"name": "M31"}


def test_part_of_a_schema_can_be_checked_on_its_own(tmp_path):
    with pytest.raises(records.Rejected, match="reference"):
        records.write(tmp_path / "v1.json", {"version": "one"}, schema="reference#/$defs/version")


def test_a_stamped_record_says_which_code_made_it(tmp_path):
    written = records.write(tmp_path / "r.json", {"x": 1}, stamp=True, record_version=3)
    kept = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    assert kept == written and kept["x"] == 1
    p = kept["provenance"]
    jsonschema.validate(p, records.schema("provenance"))
    assert p["telescopeyoke"] == records.version() and p["record_version"] == 3
    assert p["python"] == ".".join(map(str, sys.version_info[:3]))
    assert set(p["libraries"]) == {"numpy", "scipy", "astropy"}
    if p["git_commit"]:
        assert len(p["git_commit"]) == 40 and records.code().startswith(p["telescopeyoke"] + "+" + p["git_commit"][:7])


def test_the_settings_fingerprint_leaves_the_site_and_the_bot_out(monkeypatch, tmp_path):
    import config
    base = {"site": {"latitude": 1.0}, "telegram": {"token": "a"}, "camera": {"gain": 100}}
    monkeypatch.setattr(config, "_read", lambda path: base)
    monkeypatch.setattr(config, "FILE", tmp_path / "config.toml")
    (tmp_path / "config.toml").write_text("", encoding="utf-8")
    first = records.fingerprint()
    base.update(site={"latitude": 2.0}, telegram={"token": "b"})
    assert records.fingerprint() == first
    base["camera"]["gain"] = 200
    assert records.fingerprint() != first


def adds(path, start, count):
    for n in range(start, start + count):
        records.change(path, lambda r: r["seen"].append(n), {"seen": []})


def test_two_processes_changing_one_record_lose_nothing(tmp_path):
    path = tmp_path / "book.json"
    workers = [multiprocessing.Process(target=adds, args=(path, start, 40)) for start in (0, 1000)]
    for w in workers:
        w.start()
    for w in workers:
        w.join(60)
        assert w.exitcode == 0
    seen = json.loads(path.read_text(encoding="utf-8"))["seen"]
    assert sorted(seen) == list(range(40)) + list(range(1000, 1040))


def test_a_change_returns_what_the_change_said(tmp_path):
    written, said = records.change(tmp_path / "c.json", lambda r: r.setdefault("n", 5), {})
    assert written == {"n": 5} and said == 5


def test_a_copy_without_git_history_names_the_commit_it_was_sent_as(monkeypatch):
    monkeypatch.setenv("TY_CODE_COMMIT", "a" * 40 + "+changed")
    records.commit.cache_clear()
    try:
        assert records.commit() == ("a" * 40, True)
    finally:
        records.commit.cache_clear()
