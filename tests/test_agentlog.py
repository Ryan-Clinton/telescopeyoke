"""agentlog.py: the decision record writes what ran and who asked, and never a secret."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

import agentlog
import config

ROOT = Path(__file__).resolve().parent.parent
TOKEN = "8926225145:AAGGEQTH5r1K0TWi-qQNEknCN7hA6ZDQD4z"   # the shape of one, not a real one


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    return tmp_path


@pytest.mark.parametrize("text, kept, gone", [
    (f"curl https://api.telegram.org/bot{TOKEN}/sendMessage", "api.telegram.org/bot***", TOKEN),
    (f"echo {TOKEN}", "echo ***", TOKEN),
    ("./notify.py --token abc123 hi", "--token ***", "abc123"),
    ("./x.py --password=hunter2", "--password=***", "hunter2"),
    ("TY_TELEGRAM_TOKEN=s3cret ./notify.py --test", "TY_TELEGRAM_TOKEN=***", "s3cret"),
    ("printf 'token = \"abc\"'", "token = ***", "abc"),
    ("curl 'https://example.org/api?key=k1&chat=99'", "https://example.org/api?***", "k1"),
    ("chat = 1234567890", "chat = ***", "1234567890"),
])
def test_secrets_are_redacted_before_anything_is_written(text, kept, gone):
    out = agentlog.redact(text)
    assert kept in out and gone not in out


def test_ordinary_commands_are_kept_as_they_are():
    for text in ("./ty mount goto Vega --dry-run", "git log -3", "./patrol.py m31-panels --plan"):
        assert agentlog.redact(text) == text


def transcript(tmp_path, said, when="2026-10-17T21:11:00Z"):
    t = tmp_path / "t.jsonl"
    rows = [{"type": "user", "message": {"content": "earlier"}, "timestamp": "2026-10-17T20:00:00Z"},
            {"type": "assistant", "message": {"content": "ok"}},
            {"type": "user", "message": {"content": [{"type": "text", "text": said}]}, "timestamp": when},
            {"type": "user", "message": {"content": [{"type": "tool_result", "content": "x"}]}}]
    t.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    return t


def payload(command, t=None, agent=None, session="s1"):
    p = {"tool_name": "Bash", "tool_input": {"command": command}, "session_id": session}
    if t:
        p["transcript_path"] = str(t)
    if agent:
        p["agent_type"] = agent
    return p


def test_a_move_is_recorded_with_its_authorisation_as_data(data, tmp_path):
    row = agentlog.event(payload("./ty mount goto Vega --solve", transcript(tmp_path, "swing to Vega")))
    assert row["cls"] == "hardware"
    assert row["authorisation"] == {"present": True, "scope": "mount.goto", "target": "Vega",
                                    "words": "swing to Vega"}


def test_a_second_move_without_the_person_speaking_again_is_not_authorised(data, tmp_path):
    t = transcript(tmp_path, "swing to Vega")
    agentlog.write(agentlog.event(payload("./ty mount goto Vega", t)))
    again = agentlog.event(payload("./ty mount goto Deneb", t))
    assert again["authorisation"]["present"] is False
    later = agentlog.event(payload("./ty mount goto Deneb", transcript(tmp_path, "now Deneb", "2026-10-17T21:20Z")))
    assert later["authorisation"]["present"] is True


def test_nothing_an_agent_runs_is_authorised(data, tmp_path):
    row = agentlog.event(payload("./mount.py nudge", transcript(tmp_path, "nudge it"), agent="night-analyst"))
    assert row["authorisation"]["present"] is False


def test_a_skill_loaded_is_carried_on_what_follows(data):
    agentlog.write(agentlog.event({"tool_name": "Skill", "tool_input": {"skill": "nightly-setup"},
                                   "session_id": "s1"}))
    assert agentlog.event(payload("./doctor.py --offline"))["skill"] == "nightly-setup"
    assert agentlog.event(payload("./doctor.py --offline", session="s2"))["skill"] is None


def test_the_report_counts_skills_agents_refusals_and_unasked_moves(data, tmp_path):
    t = transcript(tmp_path, "swing to Vega")
    agentlog.write(agentlog.event({"tool_name": "Skill", "tool_input": {"skill": "focus"}, "session_id": "s1"}))
    agentlog.write(agentlog.event(payload("./ty focus --motor", t)))
    agentlog.write(agentlog.event(payload("./ty mount goto Vega", t)))
    agentlog.write(agentlog.refusal("no-motion", payload("./shoot.py M31", agent="candidate-vetter"), "no"))
    answer = agentlog.report(agentlog.read())
    assert answer["hardware_commands"] == 2 and answer["hardware_without_the_person_speaking_first"] == 1
    assert {k: answer["skills"]["focus"][k] for k in ("loaded", "ran", "refused")} == {"loaded": 1, "ran": 2, "refused": 0}
    assert answer["agents"]["candidate-vetter"]["refused"] == 1 and answer["refused"] == {"no-motion": 1}


def test_the_logging_hook_never_stops_the_work(tmp_path):
    for text in ("not json", "", json.dumps({"tool_name": "Bash", "tool_input": None})):
        done = subprocess.run([sys.executable, str(ROOT / ".claude" / "hooks" / "log.py")], input=text,
                              capture_output=True, text=True, timeout=60,
                              env={"TY_DATA": str(tmp_path), "PATH": "", "SYSTEMROOT": ""})
        assert done.returncode == 0


def chat(tmp_path, *turns):
    t = tmp_path / "chat.jsonl"
    rows = []
    for who, text in turns:
        kind = "assistant" if who == "claude" else "user"
        rows.append({"type": kind, "message": {"content": [{"type": "text", "text": text}]}})
    t.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    return str(t)


@pytest.mark.parametrize("said, corrected", [
    ("no, not that one", True), ("stop", True), ("don't move it", True), ("why did you slew?", True),
    ("I said Vega", True), ("wait", True), ("swing to Vega", False), ("now Deneb", False),
    ("nothing wrong, carry on", False),
])
def test_a_message_that_corrects_or_stops_is_noted_without_its_words(data, tmp_path, said, corrected):
    row = agentlog.person({"session_id": "s1", "prompt": said, "transcript_path": chat(tmp_path)})
    assert row["correction"] is corrected and said not in json.dumps(row)


def test_an_interruption_before_the_message_is_noted(data, tmp_path):
    t = chat(tmp_path, ("claude", "Focusing now."), ("person", "[Request interrupted by user]"))
    assert agentlog.person({"session_id": "s1", "prompt": "stop", "transcript_path": t})["interrupted"]
    t = chat(tmp_path, ("claude", "Focusing now."))
    assert not agentlog.person({"session_id": "s1", "prompt": "ok", "transcript_path": t})["interrupted"]


@pytest.mark.parametrize("reply, question", [
    ("Focus now?", True), ("Which part of the sky is clear?\nThen I'll pick a star.", True),
    ("Focused: HFR 2.3.", False), ("It printed `ready?` and stopped.", False),
    ('The handset says "continue?" on its screen.', False),
])
def test_a_turn_ending_on_a_question_is_noted(data, tmp_path, reply, question):
    t = chat(tmp_path, ("person", "focus"), ("claude", reply))
    assert agentlog.turn_end({"session_id": "s1", "transcript_path": t})["asked"] is question


def test_an_interruption_is_not_taken_as_the_persons_words_for_a_move(tmp_path):
    t = chat(tmp_path, ("person", "swing to Vega"), ("claude", "Going."), ("person", "[Request interrupted by user]"))
    assert agentlog.last_words(t)[0] == "swing to Vega"


def test_the_report_says_per_skill_how_often_it_asked_was_corrected_or_stopped(data, tmp_path):
    agentlog.write(agentlog.event({"tool_name": "Skill", "tool_input": {"skill": "focus"}, "session_id": "s1"}))
    agentlog.write(agentlog.turn_end({"session_id": "s1", "transcript_path": chat(tmp_path, ("claude", "Now?"))}))
    agentlog.write(agentlog.turn_end({"session_id": "s1", "transcript_path": chat(tmp_path, ("claude", "Done."))}))
    agentlog.write(agentlog.person({"session_id": "s1", "prompt": "no, stop",
                                    "transcript_path": chat(tmp_path, ("person", "[Request interrupted by user]"))}))
    s = agentlog.report(agentlog.read())["skills"]["focus"]
    assert (s["turns"], s["questions"], s["corrected"], s["interrupted"]) == (2, 1, 1, 1)
