"""The stream's presenter: a chapter, a line or an explainer within a minute of
arriving, never the same card twice running, and never anything made up."""
import streamlook
import streamstory

TARGETS = streamlook.targets()
PATROL = {"kind": "patrol", "target": "M31", "last_age": 3, "combined": 225, "exposure": 16, "fwhm_arcsec": 5.8,
          "patrol": {"awaiting": 0}}
LIVE = {"accepted": 203, "rejected": 8, "reasons": {"star brightness down (cloud)": 8}, "depth_mag": 16.68,
        "discovery": {"sessions": [{"field": "M31-P5", "session": "1", "kept": 19}],
                      "mosaics": [{"name": "M31", "panels": [{"state": "done"}] * 5 + [{"state": "planned"}] * 3}]},
        "schedule": {"steps": [{"label": "M31 panels", "status": "running"},
                               {"label": "WASP-12 b transit, 4 s frames, to 06:20", "status": "queued",
                                "start": 1000 + 12 * 60}]}}


def timeline(state, live, seconds, step=5):
    story = streamstory.Story()
    return [(t, streamstory.plan(state, live, 1000 + t, story, TARGETS)) for t in range(0, seconds, step)]


def test_someone_arriving_sees_something_explained_within_a_minute():
    events = timeline(PATROL, LIVE, 3 * streamstory.CYCLE)
    told = [t for t, p in events if p["chapter"] != "NOW" or p["line"] or p["explainer"]]
    gaps = [b - a for a, b in zip(told, told[1:])]
    assert told[0] <= 60 and max(gaps) <= 60


def test_the_chapters_come_round_and_each_card_is_new_until_its_pool_is_used():
    events = timeline(PATROL, LIVE, 4 * streamstory.CYCLE)
    chapters = {p["chapter"] for _, p in events}
    assert {"NOW", "SCIENCE", "HOW IT WORKS", "TONIGHT", "COMING UP"} <= chapters
    science = []
    for _, p in events:
        if p["chapter"] == "SCIENCE" and (not science or science[-1] != p["card"][1][0]):
            science.append(p["card"][1][0])
    assert len(science) >= 3 and len(set(science[:3])) == 3


def test_the_measured_cards_say_only_what_was_measured():
    made = dict(streamstory.made(PATROL, LIVE))
    assert "225 exposures of 16 s" in made["made-stack"] and "60 minutes" in made["made-stack"]
    assert "8 frames set aside" in made["made-rejected"] and "cloud" in made["made-rejected"]
    assert "magnitude 16.7" in made["made-depth"]
    bare = dict(streamstory.made({"kind": "patrol", "target": "M31"}, {}))
    assert bare == {}                                     # nothing measured, nothing said


def test_coming_up_says_what_and_when_in_plain_words():
    title, words = streamstory.coming_up(LIVE["schedule"]["steps"], 1000, TARGETS)
    assert title == "COMING UP IN ~12 MIN" and words[0] == "WASP-12 b transit"
    assert "giant planet" in words[1]
    assert streamstory.coming_up([], 1000, TARGETS) is None


def test_a_follow_up_or_a_warning_has_the_screen_to_itself():
    for state in (dict(PATROL, candidate={"stage": "second"}), dict(PATROL, last_age=600)):
        for _, p in timeline(state, LIVE, streamstory.CYCLE):
            assert p == {"chapter": "NOW", "card": None, "line": None, "explainer": None, "crawl": None}


def test_tonight_says_finding_nothing_is_a_result_and_the_crawl_names_what_is_next():
    lines = streamstory.tonight_lines(PATROL, LIVE)
    assert "5 of 8 M31 fields searched" in lines and any("still a result" in line for line in lines)
    assert "next: WASP-12 b transit" in streamstory.crawl_text(PATROL, LIVE, 1000, TARGETS)


def test_every_curated_line_fits_and_none_names_the_place():
    import config
    place = config.example()["site"]["name"]
    pools = []
    for entry in TARGETS["targets"].values():
        pools += entry.get("facts", []) + entry.get("why", []) + entry.get("notice", [])
    for prog in TARGETS["programmes"].values():
        pools += prog.get("explainers", []) + prog.get("method", [])
    for items in TARGETS["stories"].values():
        pools += items
    assert pools and all(len(t) <= 170 and place not in t for t in pools)


def hunt_file(tmp_path, state, when="2026-10-20 05:05"):
    import json
    (tmp_path / "sungrazer").mkdir(exist_ok=True)
    every = [f"2026-10-19 {h:02d}:{m:02d}" for h in range(16, 24) for m in (0, 15, 30, 45)]
    times = every[3:17] + every[19:]                    # 16:45-20:00 and 20:45-23:45, as on 19 October
    (tmp_path / "sungrazer" / "hunt-ccor1.json").write_text(json.dumps({
        "when": when, "pictures": 74, "towards_sun": [
            {"times": times, "movie": str(tmp_path / "candidate-1.gif"),
             "public": {"state": state, "report": "report_ms_20261019125628", "who": "Michael Stark",
                        "type": "Known Comet Now Entering", "group": "Kreutz"}}]}))


def test_a_known_comet_the_hunt_found_is_told_and_an_unreported_track_never_is(tmp_path, monkeypatch):
    import datetime
    import config
    monkeypatch.setattr(config, "DATA", tmp_path)
    evening = datetime.datetime(2026, 10, 20, 19, 0, tzinfo=datetime.timezone.utc).timestamp()
    hunt_file(tmp_path, "known comet")
    hunt = streamstory.comet_hunt(evening)
    assert hunt["seen"] == 27 and hunt["pictures"] == 74 and hunt["day"] == "19 October"
    words = streamstory.comet_words(hunt)
    assert "74 pictures" in words and "known Kreutz sungrazing comet" in words and "27 of them, over 7 hours" in words
    story = streamstory.Story()
    seen = [streamstory.plan(PATROL, LIVE, evening + t, story, TARGETS) for t in range(0, 6 * 300, 5)]
    assert any(p["explainer"] == "comet" and p["comet"]["seen"] == 27 for p in seen)
    assert streamstory.comet_hunt(evening + 2 * 86400) is None                     # old news
    for state in ("no matching public report found", "possible public match", "public reports not checked"):
        hunt_file(tmp_path, state)
        assert streamstory.comet_hunt(evening) is None


def test_while_focusing_or_polar_aligning_the_cards_come_from_their_own_pools():
    for kind, title in (("focus", "HOW FOCUSING WORKS"), ("polar", "HOW POLAR ALIGNMENT WORKS")):
        story = streamstory.Story()
        pool = TARGETS["stories"][kind]
        assert len(pool) >= 8
        cards = [streamstory.plan({"kind": kind}, {}, 1000 + t, story, TARGETS)["card"]
                 for t in range(0, streamstory.SEGMENT_S * len(pool), streamstory.SEGMENT_S)]
        assert all(card[0] == title for card in cards)
        assert sorted(card[1][0] for card in cards) == sorted(pool)        # each one once before any again
    words = " ".join(TARGETS["stories"]["focus"] + TARGETS["stories"]["polar"])
    for idea in ("half-flux radius", "shimmer", "slack", "doughnut", "second mirror", "cools", "curve",
                 "celestial pole", "Polaris is not exactly at the pole", "circle", "declination", "bolts",
                 "level tripod is not essential"):
        assert idea in words, idea


MOON = {"kind": "moon", "target": "Moon", "combined": 40, "exposure": 0.02, "fwhm_arcsec": 9.3,
        "moon": {"illumination": 97, "waxing": True, "age_days": 12.9, "distance_km": 371200.0,
                 "size_deg": 0.54, "altitude": 31}}


def test_the_moon_s_story_has_no_star_size_or_depth_and_its_notices_follow_the_phase():
    made = dict(streamstory.made(MOON, {"depth_mag": 16.0}))
    assert "made-stars" not in made and "made-depth" not in made and "freeze" in made["made-stack"]
    entry = streamlook.targets()["targets"]["Moon"]
    full = streamstory.moon_notices(entry, MOON["moon"])
    crescent = streamstory.moon_notices(entry, dict(MOON["moon"], illumination=30))
    assert any("rays" in t.lower() for t in full) and not any("terminator" in t.lower() for t in full)
    assert any("terminator" in t.lower() for t in crescent)
    assert streamstory.moon_line(MOON["moon"]) == "THE MOON · 97% illuminated · altitude 31° · 371,200 km away"
    assert streamstory.crawl_text(MOON, {}, 0, {}).startswith("TONIGHT   ·   THE MOON · 97% illuminated")
