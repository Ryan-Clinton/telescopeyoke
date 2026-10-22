"""The chat's commands: curated answers, never a flood, nothing that moves anything."""
import streamchat


def test_a_command_is_read_from_the_channel_s_chat_only():
    line = ":viewer!viewer@viewer.tmi.twitch.tv PRIVMSG #facepipe :!what is that"
    assert streamchat.command_of(line, "facepipe") == "what"
    assert streamchat.command_of(line, "other") is None
    assert streamchat.command_of(":v PRIVMSG #facepipe :hello", "facepipe") is None


def test_it_never_floods_the_chat():
    limit = streamchat.Limiter()
    assert limit.allow("what", 100)
    assert not limit.allow("target", 101)                    # too soon after any reply
    assert limit.allow("target", 100 + streamchat.GAP_S)
    assert not limit.allow("what", 100 + streamchat.GAP_S + 1)  # the same command again too soon
    assert limit.allow("what", 100 + streamchat.COOLDOWN_S)


def test_the_answers_come_from_what_is_running_and_the_curated_words(monkeypatch):
    import streamlook
    monkeypatch.setattr(streamlook, "transit_for", lambda name: None)
    status = {"name": "M31-P6", "age": 5, "exposure": 16, "accepted": 10, "captured": 10,
              "discovery": {"mosaics": [{"name": "M31", "columns": 4, "rows": 2,
                                         "panels": [{"panel": n, "state": "done"} for n in range(1, 9)]}],
                            "sessions": []},
              "schedule": {"steps": [{"label": "WASP-12 b transit, 4 s frames", "status": "queued", "start": None}]}}
    assert "nova patrol of M31" in streamchat.answer("what", status)
    assert streamchat.answer("target", status).startswith("M31 (Andromeda Galaxy): The nearest large galaxy")
    assert "WASP-12 b transit" in streamchat.answer("next", status)
    assert streamchat.answer("help", status).startswith("Ask:")
    assert streamchat.answer("slew", status) is None         # unknown commands get nothing
    assert streamchat.answer("what", {}) == "The telescope is not imaging just now."


def test_focus_and_polar_are_answered_from_what_is_being_done(monkeypatch):
    import time

    import streamlook
    now = time.time()
    focusing = {"running": True, "stage": "sweep", "position": 4, "positions": 9, "hfr": 2.6, "best_hfr": 2.41,
                "start_hfr": 5.07, "usual_hfr": 2.28, "started": now - 60, "ended": None}
    monkeypatch.setattr(streamlook, "focus_stream_state", lambda now=None: focusing)
    monkeypatch.setattr(streamlook, "polar_stream_state", lambda now=None: None)
    said = streamchat.answer("focus", {}, now)
    assert said.startswith("Focusing now (sweep, 4 of 9)") and "best so far 2.41" in said and "2.28" in said
    assert "!focus" in streamchat.answer("what", {}, now)
    finished = dict(focusing, running=False, ended=now - 300, outcome="complete", end_hfr=2.19)
    monkeypatch.setattr(streamlook, "focus_stream_state", lambda now=None: finished)
    assert "focus complete, 5.07 → 2.19 HFR" in streamchat.answer("focus", {}, now)
    monkeypatch.setattr(streamlook, "focus_stream_state", lambda now=None: None)
    assert streamchat.answer("focus", {}, now) == "No focus run tonight yet."
    assert streamchat.answer("polar", {}, now) == "No polar alignment tonight yet."
    polar = {"stage": "adjust", "running": False, "adjusting": True, "limit_deg": 1.25,
             "rounds": [{"total_deg": 9.6}, {"total_deg": 2.5}, {"total_deg": 4.2}]}
    monkeypatch.setattr(streamlook, "polar_stream_state", lambda now=None: polar)
    said = streamchat.answer("polar", {}, now)
    assert said.startswith("Waiting for the mount to be adjusted") and "4.2° from the pole after 3 rounds" in said
    assert "began at 9.6°" in said and "under 1.25°" in said
    assert "!polar" in streamchat.answer("what", {}, now)
    measuring = dict(polar, stage="measuring", running=True, adjusting=False, picture=2)
    monkeypatch.setattr(streamlook, "polar_stream_state", lambda now=None: measuring)
    assert streamchat.answer("polar", {}, now).startswith("Measuring the polar axis now: picture 2 of 3.")
    assert "!focus" in streamchat.answer("help", {}) and "!polar" in streamchat.answer("help", {})
