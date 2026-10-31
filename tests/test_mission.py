"""The stream as a mission (mission.py), its voice (narrator.py), its clips
(clips.py), the telescope's decisions shown (director.decide), the chat's
questions and votes, and the 9:16 picture: every word from the measured
state, nothing that moves the telescope."""
import json
import os

import pytest

import config
import director
import mission
import streamlook

NOW = 1792800000.0


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    monkeypatch.setattr(director, "EVENTS_FILE", tmp_path / "cache" / "events.jsonl")
    monkeypatch.setattr(director, "DECISIONS_FILE", tmp_path / "cache" / "decisions.jsonl")
    monkeypatch.setattr(director, "STATE_FILE", tmp_path / "cache" / "broadcast.json")
    (tmp_path / "web").mkdir()
    return tmp_path


def lucky(stage, **more):
    return dict({"stage": stage, "at": NOW - 5}, **more)


# --- the mission ----------------------------------------------------------------

def test_every_programme_has_a_goal_and_its_question_says_only_what_is_known():
    for key in ("lucky", "mineral", "live", "patrol", "transit", "picture", "focus", "polar", "comet"):
        assert mission.missions()[key]["goal"], key
    moon = {"kind": "moon", "target": "Moon", "now": NOW}
    assert mission.of(moon, NOW, lucky("capturing", frames=2000))["question"] == \
        "How many of these 2,000 frames will be sharp enough to keep?"
    assert mission.of(moon, NOW, lucky("capturing"))["question"] == "How sharp will the air let the Moon be tonight?"
    focus = {"kind": "focus", "now": NOW, "focus": {"usual_hfr": 2.28}}
    assert mission.of(focus, NOW, {})["question"] == "Can it reach the usual best of 2.3 HFR?"
    assert mission.of({"kind": "focus", "focus": {}}, NOW, {})["question"] == "How small can the stars get tonight?"
    # Answered: no question left hanging.
    assert mission.of({"kind": "focus", "focus": {"outcome": "complete"}}, NOW, {})["question"] is None
    assert mission.of({"kind": "picture", "target": ""}, NOW, {}) is None        # nothing a viewer can follow


def test_the_milestones_follow_what_has_been_measured():
    moon = {"kind": "moon", "target": "Moon", "now": NOW}
    m = mission.of(moon, NOW, lucky("colour", done=2, videos=3))
    assert m["key"] == "mineral" and m["steps"][1] == ("Capture colour video 2 of 3", "now")
    assert m["steps"][0] == ("Find the Moon", "done") and m["next"] == "Check the colour repeats"
    m = mission.of(moon, NOW, lucky("stacking"))
    assert m["key"] == "lucky" and [st for _, st in m["steps"]] == ["done", "done", "done", "now", "open"]
    patrol = {"kind": "patrol", "target": "M31", "now": NOW,
              "patrol": {"panels": [{"state": "done"}] * 3 + [{"state": "current"}] + [{"state": "open"}] * 4}}
    m = mission.of(patrol, NOW, {})
    assert m["title"] == "NOVA PATROL · M31" and m["steps"][3] == ("Field 4", "now") and len(m["steps"]) == 8
    assert m["question"] == "Is there a new star in this field tonight?"
    patrol["patrol"]["possible"] = 1
    assert mission.of(patrol, NOW, {})["question"] == "Will anything survive the second look?"
    transit = {"kind": "transit", "target": "WASP-12", "now": NOW,
               "transit": {"ingress": NOW + 600, "egress": NOW + 6600, "depth": 0.014}}
    m = mission.of(transit, NOW, {})
    assert m["steps"][0] == ("Measure the star before", "now") and m["question"] == \
        "Will the star dim by the expected 1.4 %?"
    transit["now"] = NOW + 7000
    assert mission.steps("transit", transit)[2] == ("Measure the star after", "now")


SEAS = [{"expected": "Mare Tranquillitatis bluer than Mare Serenitatis", "result": "agrees",
         "bluer_by_percent": 2.04, "videos_agreeing": "3 of 3", "holds_without_any_one_video": True}]


def test_a_result_is_labelled_no_surer_than_it_was_measured():
    assert mission.confidence("mineral", lucky("done", kind="mineral", videos=3, seas=SEAS))[0] == "CONSISTENT"
    assert mission.confidence("mineral", lucky("done", kind="mineral", videos=1, seas=SEAS))[0] == "PRELIMINARY"
    against = [dict(SEAS[0], result="disagrees")]
    assert mission.confidence("mineral", lucky("done", kind="mineral", videos=3, seas=against))[0] == "DOES NOT AGREE"
    assert mission.confidence("mineral", lucky("done", kind="mineral", seas=[]))[0] == "NOT SEEN TONIGHT"
    assert mission.confidence("mineral", lucky("mineral")) is None                  # no result yet
    assert mission.confidence(None, candidate={"stage": "detected"})[0] == "PRELIMINARY"
    assert mission.confidence(None, candidate={"stage": "second"})[0] == "NEEDS SECOND LOOK"
    assert mission.confidence(None, candidate={"stage": "result", "result": "a known asteroid"})[0] == "REJECTED"
    assert mission.confidence(None, candidate={"stage": "result", "result": "unexplained"})[0] == "AWAITING REVIEW"
    assert mission.result_words("mineral", lucky("done", kind="mineral", seas=SEAS)) == \
        "Tranquillitatis bluer than Serenitatis: agrees, by 2.0 %, in 3 of 3 videos"


def test_what_why_now_and_next_take_turns_across_the_top():
    s = {"kind": "moon", "target": "Moon", "now": NOW, "activity_words": "capturing"}
    m = mission.of(s, NOW, lucky("capturing", frames=2000))
    seen = {mission.context(m, s, NOW + i * mission.CONTEXT_S)[0] for i in range(4)}
    assert seen == {"WHAT", "WHY", "NOW", "NEXT"}
    assert mission.context(m, s, NOW - NOW % (4 * mission.CONTEXT_S)) == ("WHAT", "THE MOON")
    assert mission.context(None, {"kind": None}, NOW) is None


def test_the_reveal_and_the_recap_use_the_measured_counts(data):
    (data / "web" / "lucky.json").write_text(json.dumps(lucky("done", frames=2000, kept=400)))
    r = mission.reveal({"kind": "moon"}, NOW)
    assert (r["before"], r["after"]) == ("ONE RAW FRAME", "THE SHARPEST 400 OF 2,000 COMBINED")
    assert mission.so_far(NOW) == ["Moon: the sharpest 400 of 2,000 frames combined"]
    assert mission.reveal({"kind": "moon"}, NOW + mission.REVEAL_S + 10) is None     # not tonight's
    (data / "web" / "lucky.json").write_text(json.dumps(lucky("done", kind="mineral", videos=3, seas=SEAS,
                                                              picture=str(data / "m.jpg"))))
    assert mission.reveal({"kind": "moon"}, NOW)["after"] == "MINERAL MOON · 3 COLOUR VIDEOS"
    assert "(consistent)" in mission.so_far(NOW)[1]
    deep = mission.reveal({"kind": "picture", "combined": 40, "exposure": 16, "integration_s": 640}, NOW)
    assert (deep["before"], deep["after"]) == ("ONE 16 S EXPOSURE", "40 STACKED · 11 MIN")


# --- drawn ----------------------------------------------------------------------

def written(canvas):
    return " ".join(w["words"] for w in canvas.written)


def test_the_panel_shows_the_mission_the_header_its_context_and_a_decision_takes_the_panel(data, monkeypatch):
    monkeypatch.setattr(streamlook, "moon_now", lambda now: {"illumination": 80, "waxing": True, "age_days": 10,
                                                             "distance_km": 371000.0, "size_deg": 0.54,
                                                             "altitude": 31})
    s = {"kind": "moon", "target": "Moon", "now": NOW, "moon": streamlook.moon_now(NOW), "last_age": 1,
         "lucky": True, "lucky_stage": ("CAPTURING THE MOON'S COLOUR", "colour video 2 of 3"), "story": {}}
    s = streamlook.with_mission(s, NOW, lucky("colour", done=2, videos=3))
    words = written(streamlook.compose(s))
    for told in ("MISSION", "Reveal colour differences", "Capture colour video 2 of 3",
                 "Will the colour repeat as the Moon moves across the camera?"):
        assert told in words, told
    assert s["context"][0] in ("WHAT", "WHY", "NOW", "NEXT") and s["context"][1] in words
    assert "80%" in words                                        # the figures are kept, not stripped
    director.decide("The Moon has drifted 73 pixels in the picture", "Re-centring it before the next burst",
                    "The same part of the Moon has to stay inside the camera's fast region.", now=NOW - 5)
    s = streamlook.with_mission(s, NOW, lucky("colour", done=2, videos=3))
    words = written(streamlook.compose(s))
    assert "TELESCOPEYOKE DECISION" in words and "Re-centring it before the next burst" in words
    assert director.decision(NOW + director.DECISION_S + 1) is None                # gone after its seconds


def test_the_reveal_shows_one_raw_frame_and_what_was_made_of_it(data):
    from PIL import Image
    Image.new("RGB", (400, 300), (90, 90, 90)).save(data / "web" / "latest.jpg")
    Image.new("RGB", (400, 300), (200, 200, 200)).save(data / "web" / "stack.jpg")
    s = {"kind": "picture", "target": "M31", "now": NOW, "combined": 40, "exposure": 16, "last_age": 5,
         "story": {"chapter": "RESULT", "card": ("RAW → RESULT", [])}}
    s = streamlook.with_mission(s, NOW, {})
    c = streamlook.compose(s)
    assert "RAW → RESULT" in written(c) and "40 STACKED" in written(c) and "ONE 16 S EXPOSURE" in written(c)


def test_the_phones_picture_has_the_target_the_mission_and_the_question(data):
    from PIL import Image
    s = streamlook.with_mission({"kind": "moon", "target": "Moon", "now": NOW, "last_age": 1, "lucky": True},
                                NOW, lucky("colour", done=2, videos=3))
    c = streamlook.vertical(s, Image.new("RGB", (800, 600), (180, 180, 180)))
    assert c.image.size == (1080, 1920)
    words = written(c)
    assert "THE MOON" in words and "MINERAL MOON" in words and "Will the colour repeat" in words
    assert "ILLUMINATED" not in words                             # no figures on the phones' picture
    assert sum(c.image.getpixel((540, 320 + 500))) > 300          # the Moon shown as it is, not stretched black


# --- the director's moments and decisions ---------------------------------------

def test_moments_and_decisions_are_kept_and_the_opening_is_a_line_over_the_picture(data):
    director.decide("Something unexplained turned up in this field", "Taking 10 minutes more of it",
                    "A real new star will be there again.", now=NOW)
    assert director.decision(NOW + 1)["action"] == "Taking 10 minutes more of it"
    assert director.events(NOW - 1)[0]["words"] == "DECISION: Taking 10 minutes more of it"
    director.update({}, NOW + 5, procedure=None)                     # a first answer to put the line on
    director.opening("TELESCOPEYOKE LIVE · TONIGHT: MINERAL MOON", NOW + 6)
    assert director.last()["headline"]["words"].startswith("TELESCOPEYOKE LIVE")
    assert director.last()["headline"]["until"] == NOW + 6 + director.OPENING_S


def test_a_new_headline_is_a_moment_of_the_night(data, monkeypatch):
    calls = iter([{"scene": "slew", "target": "M33", "headline": {"words": "MOVING TO M33", "until": NOW + 4}},
                  {"scene": "slew", "target": "M33", "headline": {"words": "MOVING TO M33", "until": NOW + 4}}])
    monkeypatch.setattr(director, "gather", lambda *a, **k: {})
    monkeypatch.setattr(director, "direct", lambda given, before: dict(next(calls), updated=NOW))
    director.update({}, NOW)
    director.update({}, NOW + 2)
    assert [e["words"] for e in director.events(NOW - 1)] == ["MOVING TO M33"]       # once, not every look


# --- the voice ------------------------------------------------------------------

def test_the_narrator_says_what_happened_in_the_first_person(data):
    import narrator
    assert narrator.sentence({"words": "NOW OBSERVING: THE MOON", "target": "Moon"}) == "I've reached the Moon."
    assert narrator.sentence({"words": "MOVING TO M33", "target": "M33"}) == "I'm moving the telescope to M33."
    assert narrator.sentence({"words": "STACKING THE BEST FRAMES"}).startswith("I'm lining up")
    said = narrator.sentence({"words": "DECISION: Re-centring it before the next burst",
                              "situation": "The Moon has drifted 73 pixels in the picture",
                              "why": "The same part of the Moon has to stay inside the camera's fast region."})
    assert said.startswith("The Moon has drifted 73 pixels in the picture, so I'm re-centring it")
    assert narrator.sentence({"words": "SOMETHING ELSE"}) is None
    m = {"goal": "Find a star that wasn't there before.", "question": "Will anything survive the second look?"}
    assert narrator.status_line(m) == ("Still working: the aim tonight is to find a star that wasn't there before. "
                                       "The open question: Will anything survive the second look?")


def test_the_narrator_speaks_seldom_and_never_waits_on_speech(data):
    import narrator
    heard, clock = [], [NOW]
    voice = narrator.Narrator(heard.append, speak=lambda words: [len(words)], clock=lambda: clock[0],
                              background=False)
    director.event("NOW OBSERVING: THE MOON", NOW + 1, target="Moon")
    clock[0] = NOW + 2
    assert voice.tick(None, clock[0]) == "I've reached the Moon." and heard == [[22]]
    director.event("STACKING THE BEST FRAMES", NOW + 3)
    clock[0] = NOW + 4
    assert voice.tick(None, clock[0]) is None                    # too soon after the last
    m = {"goal": "Freeze the air.", "question": None}
    clock[0] = NOW + narrator.STATUS_S + 5
    assert voice.tick(m, clock[0]).startswith("Still working")
    silent = narrator.Narrator(heard.append, speak=lambda words: None, clock=lambda: clock[0], background=False)
    silent.say("anything")                                       # no speech made: nothing sent, no error
    assert len(heard) == 2


# --- the clips ------------------------------------------------------------------

def test_clips_are_cut_round_each_moment_once_it_has_played_out(tmp_path):
    import clips
    events = [{"at": NOW, "words": "NOW OBSERVING: THE MOON"}, {"at": NOW + 30, "words": "LUCKY IMAGING STARTED"},
              {"at": NOW + 200, "words": "RESULT READY"}]
    assert clips.due(events, NOW + 30) == []                                       # still playing out
    assert [e["words"] for e in clips.due(events, NOW + clips.AFTER_S + clips.SEGMENT_S)] == \
        ["NOW OBSERVING: THE MOON"]                                                 # the second shares its clip
    assert clips.due(events, NOW + clips.AFTER_S + clips.SEGMENT_S, done={str(NOW)}) == []
    buffer = tmp_path / "buffer"
    buffer.mkdir()
    for i, ended in enumerate([NOW - 60, NOW - 15, NOW + 5, NOW + 55, NOW + 68, NOW + 200]):
        p = buffer / f"seg{i:03d}.ts"
        p.write_bytes(b"x")
        os.utime(p, (ended, ended))
    assert [p.name for p in clips.pieces(NOW, buffer)] == ["seg001.ts", "seg002.ts", "seg003.ts", "seg004.ts"]
    ran = []

    def run(cmd, **kw):
        ran.append(cmd)
        open(cmd[-1], "wb").close()
        return type("Done", (), {"returncode": 0})()
    clip = clips.cut(events[0], run, buffer, tmp_path / "clips")
    assert clip.name.endswith("-now-observing-the-moon.mp4") and "-c" in ran[0] and "copy" in ran[0]
    assert not list((tmp_path / "clips").glob("*.txt"))
    for n in range(3):
        (tmp_path / "clips" / f"old{n}.mp4").write_bytes(b"x")
    clips.tidy(tmp_path / "clips", keep=2)
    assert len(list((tmp_path / "clips").glob("*.mp4"))) == 2


def test_the_stream_also_records_into_the_clips_buffer_when_asked():
    import stream
    plain = stream.command("rtmp://x/live/k")
    assert plain[-3:] == ["-f", "flv", "rtmp://x/live/k"]
    recording = stream.command("rtmp://x/live/k", record=True)
    assert recording[-2] == "tee" and "[f=flv:onfail=ignore]rtmp://x/live/k|[f=segment:" in recording[-1]
    upright = stream.command("rtmp://y/live/v", size=stream.VERTICAL, picture=stream.VERTICAL)
    assert "1080x1920" in upright and "scale=" not in " ".join(upright)


# --- the chat -------------------------------------------------------------------

def test_the_chat_can_ask_why_how_far_and_what_came_of_it(data, monkeypatch):
    import streamchat
    m = {"key": "mineral", "title": "MINERAL MOON", "goal": "Reveal the Moon's colour.",
         "question": "Will the colour repeat?", "next": "Check the colour repeats", "result": None,
         "confidence": None, "steps": [("Find the Moon", "done"), ("Capture colour video 2 of 3", "now"),
                                       ("Check the colour repeats", "open")]}
    monkeypatch.setattr(streamlook, "from_status", lambda st, now=None, session=None:
                        {"kind": "moon", "target": "Moon", "mission": m, "candidate": None})
    st = {"name": "Moon"}
    assert streamchat.answer("why", st) == "Mission: Reveal the Moon's colour. Still open: Will the colour repeat?"
    assert streamchat.answer("progress", st) == ("Mineral Moon: step 2 of 3, capture colour video 2 of 3. "
                                                 "Next: check the colour repeats.")
    assert streamchat.answer("result", st).startswith("No result yet tonight")
    m.update(result="Tranquillitatis bluer than Serenitatis: agrees", confidence=("CONSISTENT", "In every video."))
    assert "Confidence: consistent" in streamchat.answer("result", st)
    assert streamchat.answer("candidate", st) == "Nothing unusual is being investigated just now."


def test_a_vote_chooses_what_is_explained_and_only_tells_the_person_a_target(data):
    import streamchat
    assert streamchat.vote("ann", "focus", NOW) == "Noted: focus is explained next if it wins the vote."
    assert streamchat.vote("bob", "focus", NOW) and streamchat.vote("cat", "stacking", NOW)
    assert streamchat.tally(NOW) == [("focus", 2), ("stacking", 1)]
    assert streamchat.vote("ann", "stacking", NOW + 1) and streamchat.tally(NOW + 1)[0] == ("stacking", 2)   # changed
    assert streamchat.tally(NOW + streamchat.VOTE_S + 5) == []                   # old votes lapse
    assert streamchat.vote("dan", "slew", NOW) is None                            # not a choice
    said = streamchat.vote("dan", "m33", NOW, targets=["M33"])
    assert "a person decides every move" in said and streamchat.tally(NOW, "target") == [("M33", 1)]
    line = ":dan!dan@dan.tmi.twitch.tv PRIVMSG #facepipe :!vote focus please"
    assert streamchat.user_of(line) == "dan" and streamchat.argument_of(line, "facepipe") == "focus"


def test_the_channel_title_asks_the_missions_question():
    import twitch
    title, _ = twitch.describe({"kind": "moon", "target": "Moon",
                                "mission": {"stream_title": "LIVE: can an amateur telescope reveal the Moon's hidden colour?"}},
                               {"targets": {}})
    assert title.startswith("LIVE: can an amateur telescope reveal the Moon's hidden colour?")
