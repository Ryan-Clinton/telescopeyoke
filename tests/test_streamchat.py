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
