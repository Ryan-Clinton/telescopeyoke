"""Live streaming to YouTube or Twitch: when it starts and stops, where it
goes, what is in the picture, and that the stream key never shows."""
import config
import sys
import stream
import streamlook


def test_it_starts_when_a_run_is_imaging_and_stops_after_quiet():
    live = {"name": "WASP-12", "age": 10}
    assert stream.decide(False, live, None, 0) == ("start", None)
    assert stream.decide(True, live, None, 0) == ("carry on", None)
    quiet = {"name": "WASP-12", "age": 400}
    action, since = stream.decide(True, quiet, None, 1000)
    assert action == "carry on" and since == 1000
    assert stream.decide(True, quiet, since, 1000 + stream.STOP_S)[0] == "stop"
    assert stream.decide(False, quiet, None, 0)[0] == "carry on"          # nothing to stop


def test_each_service_has_its_address_and_the_key_is_hidden_in_anything_shown():
    key = "abcd-efgh-ijkl"
    youtube = stream.destination({"service": "youtube", "url": ""}, key)
    assert youtube.startswith("rtmp://a.rtmp.youtube.com/live2/") and youtube.endswith(key)
    assert stream.destination({"service": "twitch", "url": ""}, key).startswith("rtmp://live.twitch.tv/app/")
    assert key not in stream.hidden(youtube, key) and "<stream key>" in stream.hidden(youtube, key)


def test_a_stream_goes_out_as_flv_and_a_trial_into_a_file(tmp_path):
    assert stream.command("rtmp://x/live/k")[-3:] == ["-f", "flv", "rtmp://x/live/k"]
    assert stream.command(str(tmp_path / "t.mp4"))[-1].endswith("t.mp4")


def test_without_working_video_hardware_it_encodes_on_the_processors():
    assert stream.working_device(devices=["/dev/dri/a", "/dev/dri/b"], test=lambda d: False) is None
    assert stream.working_device(devices=["/dev/dri/a", "/dev/dri/b"], test=lambda d: d.endswith("b")) == "/dev/dri/b"
    assert "libx264" in stream.encoder(None) and "h264_vaapi" in stream.encoder("/dev/dri/b")


def test_the_picture_names_no_place(monkeypatch):
    status = {"name": "WASP-12", "title": "WASP-12 — a star", "accepted": 96, "exposure": 4.0,
              "schedule": {"steps": [{"label": "Next thing", "status": "queued", "start": 0}]}}
    picture = stream.frame(status, now=0)
    assert picture.size == (stream.WIDTH, stream.HEIGHT)
    # The caption is built only from the run and the schedule: the site's name is never read.
    import inspect
    assert "site" not in inspect.getsource(stream.frame)


def test_it_is_off_unless_switched_on(monkeypatch):
    monkeypatch.setattr(config, "hardware", lambda: {})
    said = []
    stream.watch(say=said.append, sleep=lambda s: None, wait=False)
    assert said and "off" in said[0]


def test_the_key_is_kept_readable_only_by_its_owner(tmp_path, monkeypatch):
    monkeypatch.setattr(stream, "KEY_FILE", tmp_path / "ty" / "stream-key")
    assert not stream.keep_key("  \n")
    assert stream.keep_key(" live_123_abc \n")
    assert stream.key() == "live_123_abc"
    assert sys.platform == "win32" or (stream.KEY_FILE.stat().st_mode & 0o777) == 0o600   # Windows has no such modes


def test_one_service_named_as_a_string_works_as_before(tmp_path, monkeypatch):
    monkeypatch.setattr(stream, "KEY_FILE", tmp_path / "stream-key")
    stream.keep_key("live_123_abc")
    for service in ("twitch", "youtube"):
        found, left = stream.destinations({"service": service, "url": ""})
        assert [name for name, _, _ in found] == [service] and not left
        assert found[0][1] == stream.destination({"service": service, "url": ""}, "live_123_abc")
    assert stream.command(found[0][1])[-3:] == ["-f", "flv", found[0][1]]          # no tee for one
    assert stream.services({"service": "twitch"}) == ["twitch"]


def test_several_services_each_have_their_own_key_and_the_old_one_is_twitch_s(tmp_path, monkeypatch):
    monkeypatch.setattr(stream, "KEY_FILE", tmp_path / "stream-key")
    s = {"service": ["youtube", "twitch"], "url": ""}
    assert stream.services(s) == ["youtube", "twitch"] == stream.services({"service": "youtube+twitch"})
    stream.keep_key("old-twitch-key")                       # the key kept before there were two
    stream.keep_key("yt-aaaa-bbbb", "youtube")
    assert sys.platform == "win32" or (stream.key_file("youtube").stat().st_mode & 0o777) == 0o600   # Windows has no such modes
    assert stream.key_file("youtube").name == "stream-key-youtube"
    found, left = stream.destinations(s)
    assert [(n, k) for n, _, k in found] == [("youtube", "yt-aaaa-bbbb"), ("twitch", "old-twitch-key")]
    assert found[0][1].startswith("rtmp://a.rtmp.youtube.com/live2/") and not left
    stream.keep_key("new-twitch-key", "twitch")             # its own file comes first
    assert stream.key("twitch", alone=False) == "new-twitch-key"
    # The plain key is never taken as YouTube's when there are two.
    (tmp_path / "stream-key-youtube").unlink()
    assert stream.key("youtube", alone=False) is None and stream.key("youtube", alone=True) == "old-twitch-key"


def test_a_service_without_a_key_is_left_out_and_the_others_still_go(tmp_path, monkeypatch):
    monkeypatch.setattr(stream, "KEY_FILE", tmp_path / "stream-key")
    stream.keep_key("tw-key", "twitch")
    found, left = stream.destinations({"service": ["youtube", "twitch"], "url": ""})
    assert [n for n, _, _ in found] == ["twitch"]
    assert len(left) == 1 and left[0][0] == "youtube" and "stream-key-youtube" in left[0][1]
    monkeypatch.setattr(config, "hardware", lambda: {"stream": {"enabled": True, "service": ["youtube", "twitch"]}})
    said, started = [], []
    monkeypatch.setattr(stream, "status", lambda: {})
    monkeypatch.setattr(stream, "working_device", lambda: None)
    stream.watch(say=said.append, sleep=lambda s: (_ for _ in ()).throw(KeyboardInterrupt), wait=False,
                 run=lambda *a, **k: started.append(a))
    assert sum("YouTube left out" in line for line in said) == 1
    assert not any("tw-key" in line for line in said)


def test_two_services_go_out_from_one_encoding_through_tee_and_no_key_shows():
    keys = ["yt-aaaa-bbbb", "live_123_abc"]
    targets = [stream.INGEST["youtube"].format(key=keys[0]), stream.INGEST["twitch"].format(key=keys[1])]
    cmd = stream.command(targets, "/dev/dri/b")
    assert cmd[-2:] == ["tee", "[f=flv:onfail=ignore]" + targets[0] + "|[f=flv:onfail=ignore]" + targets[1]]
    joined = " ".join(cmd)
    assert "-map 0:v -map 1:a" in joined and "+global_header" in joined and cmd.count("-i") == 2
    shown = stream.hidden(joined, keys)
    assert not any(k in shown for k in keys) and shown.count("<stream key>") == 2
    assert stream.hidden("x", None) == "x"


def test_ffmpeg_s_own_messages_are_passed_on_with_the_keys_taken_out():
    import io
    import time

    class Process:
        stderr = io.BytesIO(b"[tee] Slave '[f=flv:onfail=ignore]rtmp://a.rtmp.youtube.com/live2/yt-aaaa-bbbb': "
                            b"error opening: Connection refused\n\n")
    said = []
    stream.passed_on(Process(), ["yt-aaaa-bbbb", "live_123_abc"], said.append)
    deadline = time.time() + 5
    while not said and time.time() < deadline:
        time.sleep(0.01)
    assert len(said) == 1 and "yt-aaaa-bbbb" not in said[0] and "<stream key>" in said[0]


def test_with_two_services_the_bandwidth_test_goes_to_twitch(tmp_path, monkeypatch):
    monkeypatch.setattr(stream, "PROGRESS", tmp_path / "progress.txt")
    sent = []

    def run(cmd, **kw):
        sent.append(cmd[-1])
        (tmp_path / "stream-bandwidth.txt").write_text("drop_frames=0\nspeed=1.0x\n")
    both = ["rtmp://a.rtmp.youtube.com/live2/y", "rtmp://live.twitch.tv/app/t"]
    assert stream.bandwidth_test(both, run=run) == (stream.WIDTH, stream.HEIGHT)
    assert sent == ["rtmp://live.twitch.tv/app/t?bandwidthtest=true"]
    assert stream.bandwidth_test(both[:1], run=run) == (stream.WIDTH, stream.HEIGHT) and len(sent) == 1


def test_the_settings_form_can_choose_both():
    assert config.checked("stream", "service", "youtube+twitch") == "youtube+twitch"
    assert stream.services({"service": config.checked("stream", "service", "youtube+twitch")}) == ["youtube", "twitch"]


def test_it_stays_on_air_between_targets_and_stops_at_once_when_the_night_is_over():
    """No end-of-night card: its figures came from the last run's status and
    were often another night's (30 October 2026)."""
    quiet = {"name": "WASP-12", "age": 400}
    action, since = stream.decide(True, quiet, None, 0, between=True)
    assert action == "carry on"
    assert stream.decide(True, quiet, 0, 10 * stream.STOP_S, between=True)[0] == "carry on"
    assert stream.decide(True, quiet, None, 0, ending=True)[0] == "stop"
    assert not hasattr(stream, "end_lines") and not hasattr(streamlook, "end_card")


def test_the_next_step_due_soon_and_the_night_over_come_from_the_schedule():
    soon = {"schedule": {"steps": [{"label": "a", "status": "done"}, {"label": "b", "status": "queued", "start": 600}]}}
    assert stream.due_soon(soon, 0) and not stream.due_soon(soon, 0, within=60)
    over = {"schedule": {"steps": [{"label": "a", "status": "done"}, {"label": "b", "status": "skipped"}]}}
    assert stream.night_over(over) and not stream.night_over(soon) and not stream.night_over({})


def test_a_moon_video_keeps_the_stream_on_after_the_schedule_is_over():
    over = {"name": "Moon", "age": 9000, "schedule": {"steps": [{"label": "a", "status": "done"}]}}
    assert stream.night_ending(over, between=False, active=False)
    assert not stream.night_ending(over, between=False, active=True)        # a lucky-imaging video going on
    assert not stream.night_ending(dict(over, age=5), between=False, active=False)


def test_it_goes_down_to_720p_only_when_it_keeps_falling_behind():
    assert stream.speed("frame=1\nspeed=0.98x\nprogress=continue\nspeed=0.79x\n") == 0.79
    assert stream.speed("speed=N/A\n") is None
    span = stream.SLOW_S + 10
    slow = [(t, 0.8) for t in range(0, span, 5)]
    assert stream.falling_behind(slow, span)
    assert not stream.falling_behind(slow[-2:], span)                     # not for long enough yet
    assert not stream.falling_behind(slow[:-1] + [(span - 5, 1.0)], span)  # it caught up
    assert stream.BITRATE[stream.FALLBACK] and "scale=1280:720" in " ".join(stream.encoder(None, stream.FALLBACK))


def test_a_stalled_connection_or_repeated_breaks_count_as_falling_behind_whatever_the_speed():
    span = stream.SLOW_S + 10
    fine = [(t, 1.0) for t in range(0, span, 5)]
    assert stream.falling_behind(fine, span, frames=[(0, 500), (span, 500)])          # no frame went out
    assert not stream.falling_behind(fine, span, frames=[(0, 500), (span, 500 + 30 * span)])
    assert stream.falling_behind([], 1000, breaks=[700, 800, 990])
    assert not stream.falling_behind([], 1000, breaks=[100, 800, 990])               # one too old


def test_the_start_size_comes_from_twitch_s_bandwidth_test(tmp_path, monkeypatch):
    monkeypatch.setattr(stream, "PROGRESS", tmp_path / "progress.txt")
    sent = []

    def run(cmd, **kw):
        sent.append(cmd[-1])
        (tmp_path / "stream-bandwidth.txt").write_text(f"drop_frames=0\nspeed={speed}x\n")
    speed = 1.0
    assert stream.bandwidth_test("rtmp://live.twitch.tv/app/k", run=run) == (stream.WIDTH, stream.HEIGHT)
    assert sent[-1] == "rtmp://live.twitch.tv/app/k?bandwidthtest=true"
    speed = 0.7
    assert stream.bandwidth_test("rtmp://live.twitch.tv/app/k", run=run) == stream.FALLBACK
    assert stream.bandwidth_test("rtmp://a.rtmp.youtube.com/live2/k", run=run) == (stream.WIDTH, stream.HEIGHT)


def test_the_feed_goes_out_at_30_a_second_from_10_pictures_a_second():
    cmd = " ".join(stream.command("rtmp://x/live/k", "/dev/dri/b"))
    assert "-r 10 -i -" in cmd and "fps=30" in cmd and "-progress" in cmd


def test_a_new_picture_fades_in_and_the_feed_never_waits_for_one():
    from PIL import Image
    pictures = iter([Image.new("RGB", (4, 4), (0, 0, 0)), Image.new("RGB", (4, 4), (200, 200, 200))])
    composer = stream.Composer(draw=lambda st, now, mode: next(pictures), every=0.05)
    assert composer.next(b"old") == b"old"                     # nothing drawn yet: the last one again
    composer.view = ({}, "imaging")
    import time
    deadline = time.time() + 5
    while time.time() < deadline and len(composer.ready) < stream.FADE + 1:
        time.sleep(0.02)
    composer.stop()
    steps = [composer.next(None) for _ in range(stream.FADE + 2)]
    assert steps[0] != steps[-1] and steps[-1] == steps[-2] == bytes([200] * 48)


def test_dropped_frames_count_as_falling_behind_too():
    assert stream.reported("drop_frames=3\ndrop_frames=40\n", "drop_frames") == 40
    span = stream.SLOW_S + 10
    fine = [(t, 1.0) for t in range(0, span, 5)]
    assert not stream.falling_behind(fine, span, drops=[(0, 0), (span, 5)])
    assert stream.falling_behind(fine, span, drops=[(0, 0), (span, 5 + stream.FPS + 1)])


def test_the_between_targets_checklist_comes_from_the_named_activities():
    import activity
    assert activity.phase([{"what": "Schedule"}, {"what": "Moving"}]) == "goto"
    assert activity.phase([{"what": "Schedule"}, {"what": "Plate solving"}]) == "solve"
    assert activity.phase([{"what": "Schedule"}]) is None


# --- on air for focusing and polar alignment ------------------------------------

def test_focusing_or_polar_alignment_puts_the_stream_on_air_and_imaging_is_as_before():
    quiet = {"name": "M31-P6", "age": 900}
    assert stream.decide(False, quiet, None, 0, active=True) == ("start", None)
    assert stream.decide(True, quiet, 50, 10 * stream.STOP_S, active=True) == ("carry on", None)
    # Once it ends, the same quiet rule as after imaging.
    action, since = stream.decide(True, quiet, None, 1000)
    assert action == "carry on" and stream.decide(True, quiet, since, since + stream.STOP_S)[0] == "stop"
    assert stream.decide(False, {"name": "M31-P6", "age": 10}, None, 0) == ("start", None)


def test_what_is_shown_comes_from_the_focus_and_polar_files(monkeypatch):
    import activity
    import streamlook
    monkeypatch.setattr(streamlook, "focus_stream_state", lambda now=None: {"showing": True, "running": True})
    monkeypatch.setattr(streamlook, "polar_stream_state", lambda now=None: {"showing": True})
    assert stream.observatory()[0] == "focus"                    # focus first: polar alignment needs it
    monkeypatch.setattr(streamlook, "focus_stream_state", lambda now=None: {"showing": False})
    assert stream.observatory()[0] == "polar"
    monkeypatch.setattr(streamlook, "polar_stream_state", lambda now=None: None)
    assert stream.observatory() == (None, None)
    monkeypatch.setattr(activity, "phase", lambda: "focus_check")
    assert stream.broadcasting()[2]                               # an activity line alone keeps it on air
    monkeypatch.setattr(activity, "phase", lambda: "goto")
    assert not stream.broadcasting()[2]
    monkeypatch.setattr(streamlook, "polar_stream_state", lambda now=None: 1 / 0)
    assert stream.observatory() == (None, None)                   # a bad file never stops the stream


def test_the_focus_and_polar_segments_draw_from_their_files(monkeypatch):
    import streamlook
    examples = streamlook.examples()
    monkeypatch.setattr(stream, "pictures", lambda st=None: (None, None))
    monkeypatch.setattr(streamlook, "focus_stream_state", lambda now=None: examples["focus"]["focus"])
    monkeypatch.setattr(streamlook, "polar_stream_state", lambda now=None: examples["polar-adjust"]["polar"])
    assert stream.frame({}, 1000.0, "focus").size == (stream.WIDTH, stream.HEIGHT)
    assert stream.frame({}, 1000.0, "polar").size == (stream.WIDTH, stream.HEIGHT)
    monkeypatch.setattr(streamlook, "focus_stream_state", lambda now=None: None)
    assert stream.frame({}, 1000.0, "focus").size == (stream.WIDTH, stream.HEIGHT)   # gone: the usual picture


def test_a_focus_reading_is_heard_as_a_tone_higher_the_sharper():
    import numpy as np

    import focus
    tones = stream.Tones(fd=None)
    run = {"running": True, "started": 1.0, "count": 1, "last_hfr": 5.0, "usual_hfr": 2.0}
    tones.hear(run)                                               # a run first seen: nothing until its next reading
    assert len(tones.queue) == 0
    tones.hear(dict(run, count=2, last_hfr=4.0))
    soft = np.copy(tones.queue)
    assert len(soft) == len(focus.waveform("tone", 300))
    tones.queue = tones.queue[:0]
    tones.hear(dict(run, count=2, last_hfr=2.0))                  # the same reading again: no sound
    assert len(tones.queue) == 0
    tones.hear(dict(run, count=3, last_hfr=2.0))
    sharp = np.copy(tones.queue)

    def hertz(samples):
        spectrum = np.abs(np.fft.rfft(samples[len(samples) // 2:].astype(float)))
        return np.argmax(spectrum) * focus.RATE / len(samples[len(samples) // 2:])
    assert hertz(sharp) > hertz(soft)
    tones.queue = tones.queue[:0]
    tones.hear(dict(run, count=4, last_hfr=None))                 # no stars: two clicks
    assert len(tones.queue) == len(focus.waveform("double"))
    tones.queue = tones.queue[:0]
    n = 100
    assert len(tones.chunk(n)) == 2 * n and tones.chunk(10 ** 6).count(b"\0") == 2 * 10 ** 6
    tones.hear({"running": False})


def test_the_sound_comes_from_a_pipe_when_there_are_tones_and_is_silent_otherwise():
    plain = " ".join(stream.command("rtmp://x/live/k"))
    assert "anullsrc" in plain and "pipe:" not in plain
    args = stream.command("rtmp://x/live/k", audio_fd=7)
    piped = " ".join(args)
    assert f"-f s16le -ar {stream.TONE_RATE} -ac 1 -i pipe:7" in piped and "anullsrc" not in piped
    # Counted as arguments: the scratch folder's random name can hold "-i".
    assert "-ar 44100 -ac 2" in piped and args.count("-i") == 2
    both = stream.command(["rtmp://a/live/k", "rtmp://live.twitch.tv/app/k"], audio_fd=7)
    assert "-map 1:a" in " ".join(both)


def test_the_tones_reach_the_stream_s_sound_through_ffmpeg(tmp_path):
    """The whole path for real, into a file: pictures on ffmpeg's input,
    the tones on a pipe, and the file has sound that is not silence."""
    import os
    import shutil
    import subprocess

    import pytest
    if not shutil.which("ffmpeg"):
        pytest.skip("no ffmpeg here")
    out = tmp_path / "tones.mp4"
    stream.PROGRESS.parent.mkdir(parents=True, exist_ok=True)
    listen = os.pipe()
    process = subprocess.Popen(stream.command(str(out), None, (1280, 720), audio_fd=listen[0]),
                               stdin=subprocess.PIPE, stderr=subprocess.PIPE, pass_fds=(listen[0],))
    os.close(listen[0])
    tones = stream.Tones(listen[1]).start()
    picture = bytes(stream.WIDTH * stream.HEIGHT * 3)
    run = {"running": True, "started": 1.0, "count": 0, "last_hfr": 3.0, "usual_hfr": 2.0}
    tones.hear(run)
    import time
    for i in range(20):                                         # two seconds of pictures
        if i % 5 == 0:
            run = dict(run, count=run["count"] + 1)
            tones.hear(run)
        try:
            process.stdin.write(picture)
        except BrokenPipeError:
            pytest.fail(process.stderr.read().decode())
        time.sleep(1 / stream.INPUT_FPS)
    process.stdin.close()
    tones.stop()
    process.wait(timeout=60)
    assert out.exists() and out.stat().st_size > 0, process.stderr.read().decode()
    probe = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(out), "-af", "volumedetect", "-f", "null", "-"],
                           capture_output=True, text=True, timeout=60).stderr
    loudest = float(probe.split("max_volume:")[1].split("dB")[0])
    assert loudest > -30, probe


# --- the night opens, and the night's result ------------------------------------

def brief():
    import datetime
    bst = datetime.timezone(datetime.timedelta(hours=1))
    at = lambda h, m, day=21: datetime.datetime(2026, 10, day, h, m, tzinfo=bst)
    return {"site": "My back garden", "verdict": "GO", "mean_cloud_percent": 20, "clear_hours": 6,
            "clear_window": [at(22, 0), at(4, 0, 22)],
            "darkness": {"level": "astronomical", "start": at(19, 50).isoformat(), "end": at(5, 40, 22).isoformat()},
            "moon": {"illumination": 34, "waxing": True, "rise": None, "set": at(0, 10, 22)},
            "discovery": [{"programme": "m31-novae", "field": "M31", "mosaic": False, "window": [1, 2], "in_clear": True},
                          {"programme": "m31-panels", "field": "M31", "mosaic": True, "window": [1, 2], "in_clear": True},
                          {"programme": "tabby", "field": "Tabby", "mosaic": False, "window": None, "in_clear": None}]}


def test_the_night_opens_with_tonight_s_plan_in_utc_and_never_the_site():
    lines = dict(stream.open_lines(brief(), {}))
    assert lines["THE SKY"] == "forecast GO, 20% cloud on average"
    assert lines["CLEAR SPELL"] == "21:00 to 03:00 UTC, about 6 h"
    assert lines["DARK"] == "astronomical darkness from 18:50 to 04:40 UTC"
    assert lines["THE MOON"] == "34% lit, waxing, sets 23:10 UTC"
    assert lines["TONIGHT WILL TRY"] == "M31 nova patrol, M31 mosaic fields"      # what is in the clear
    assert not any("garden" in words for words in lines.values())
    # Tonight's schedule, where there is one, says what will be tried.
    st = {"schedule": {"steps": [{"label": "goto M31", "status": "queued"},
                                 {"label": "WASP-12 b transit, 4 s frames", "status": "queued"},
                                 {"label": "M31 panels", "status": "done"}]}}
    assert dict(stream.open_lines(brief(), st))["TONIGHT WILL TRY"] == "WASP-12 b transit"
    # Only what is known: no forecast, no times without their zone.
    bare = stream.open_lines({"verdict": None, "darkness": {"start": "2026-10-21T19:50:00"}, "moon": {}}, {})
    assert bare == []
    assert stream.utc_clock("2026-10-21T19:50:00") is None and stream.utc_clock(None) is None


def test_the_night_opens_once_a_night_and_never_waits_for_the_plan(tmp_path):
    import time
    path = tmp_path / "night.json"
    assert stream.opening_due(1e9, path) and not stream.opening_due(1e9 + 3600, path)
    assert stream.opening_due(1e9 + stream.NIGHT_S + 1, path)
    opening = stream.Opening(time.time(), get=brief)
    deadline = time.time() + 5
    while opening.brief is None and time.time() < deadline:
        time.sleep(0.01)
    assert opening.showing(time.time()) and not opening.showing(time.time() + stream.OPEN_S + 1)
    failed = stream.Opening(time.time(), get=lambda: 1 / 0)
    time.sleep(0.05)
    assert not failed.showing(time.time())                        # no plan: no card


def test_the_night_opens_card_draws(monkeypatch):
    monkeypatch.setattr(stream, "pictures", lambda st=None: (None, None))
    picture = stream.frame({"night_brief": brief()}, 1000.0, "open")
    assert picture.size == (stream.WIDTH, stream.HEIGHT)


def test_a_moon_step_on_the_plan_opens_with_the_moon():
    st = {"schedule": {"steps": [{"label": "Moon, 0.02 s frames", "status": "queued"}]}}
    lines = dict(stream.open_lines(brief(), st))
    assert lines["TONIGHT: THE MOON"] == ("34% lit, waxing · coming up: close-up imaging → frame selection → "
                                          "final stack")
    assert "TONIGHT: THE MOON" not in dict(stream.open_lines(brief(), {}))


def test_a_fresh_picture_keeps_the_stream_on_air_and_no_stack_never_costs_it(tmp_path, monkeypatch):
    """30 October 2026: "what the scope sees is broadcast", whatever takes the picture."""
    import os
    from PIL import Image
    monkeypatch.setattr(stream, "WEB", tmp_path)
    Image.new("RGB", (40, 30), (200, 200, 200)).save(tmp_path / "latest.jpg")
    now = (tmp_path / "latest.jpg").stat().st_mtime + 3
    assert stream.seeing(now) and not stream.seeing(now + stream.START_S)
    stack, single = stream.pictures({})
    assert stack is None and single is not None                  # no stack.jpg: the newest frame still comes
    over = {"name": "M31", "age": 90000, "schedule": {"steps": [{"label": "M31", "status": "done"}]}}
    assert not stream.night_ending(over, between=False, active=stream.seeing(now))
    os.utime(tmp_path / "latest.jpg", (now - 3600, now - 3600))
    assert stream.night_ending(over, between=False, active=stream.seeing(now))


def test_another_night_s_finished_schedule_does_not_end_tonight_s_stream():
    """1 November 2026: a schedule from 20 October, all done, made every
    pause between focusing and imaging look like the end of the night, and
    the stream stopped and started ten times in an hour."""
    import time as _time
    now = _time.time()
    old = {"schedule": {"steps": [{"status": "done", "start": now - 12 * 86400}]}}
    tonight = {"schedule": {"steps": [{"status": "done", "start": now - 3600}]}}
    assert not stream.night_over(old, now) and stream.night_over(tonight, now)


def test_a_lost_destination_is_seen_and_brought_back_a_few_times_an_hour():
    """1 November 2026: with onfail=ignore a service that dropped off stayed off
    while the other went on; the stream starts again to bring it back, but not
    without limit, so one down for good does not keep breaking the other."""
    import stream
    assert stream.lost_destination("[tee @ 0x55] Slave muxer #1 failed: Broken pipe, continuing with 1/2 slaves.")
    assert not stream.lost_destination("frame=  100 fps= 30")

    class P:
        lost_at = 1000.0
    assert not stream.rejoin_due(P(), 1000 + stream.REJOIN_S - 1, [])
    assert stream.rejoin_due(P(), 1000 + stream.REJOIN_S, [])
    assert not stream.rejoin_due(P(), 5000, [4000 + i for i in range(stream.REJOINS_PER_HOUR)])
    assert not stream.rejoin_due(object(), 5000, [])


def test_an_ffmpeg_that_broke_off_is_reaped_not_left_behind():
    import stream
    calls = []

    class Gone:
        stdin = type("In", (), {"close": lambda self: calls.append("close")})()
        def kill(self): calls.append("kill")
        def wait(self, timeout=None):
            calls.append("wait")
            return -9
    said = []
    assert stream.ended(Gone(), said.append) == -9
    assert calls == ["close", "kill", "wait"] and "exit -9" in said[0]


def test_the_cloud_card_says_what_tonight_hopes_for_without_the_telescope_picture():
    """4 November 2026: waiting for a gap, the stream showed the cloud; asked
    for "a card saying what we hope to achieve if the cloud clears"."""
    import time as clock
    import stream
    import streamlook
    names = {"M31": "Andromeda Galaxy", "M33": "Triangulum Galaxy"}
    assert stream.hope_words({"what": "M31-P4", "why": "a second look at M31-P4-x (seen on 2 nights)"},
                             names).startswith("Look again at a faint spot in the Andromeda Galaxy seen on 2")
    assert "novae" in stream.hope_words({"what": "m33-novae", "why": "last run 02 Nov"}, names)
    assert "Triangulum" in stream.hope_words({"what": "m33-novae", "why": "last run 02 Nov"}, names)
    assert "edge to edge" in stream.hope_words({"what": "m31-panels", "why": ""}, names)
    brief = {"clear_window": ["2026-11-04T00:00:00+00:00", "2026-11-04T07:00:00+00:00"],
             "recommendation": {"steps": [{"what": "m31-novae", "why": "last run 02 Nov",
                                           "start": "2026-11-04T02:20:00+00:00"}]}}
    lines = stream.cloud_lines(brief)
    assert lines["hopes"][0][0] == "02:20" and "00:00 to 07:00 UTC" in lines["sky"]
    canvas = streamlook.compose({"kind": "cloud", "target": "", "now": clock.time(), "cloud": dict(lines, waiting=True)})
    words = " ".join(w["words"] for w in canvas.written)
    assert "WAITING FOR THE CLOUD TO CLEAR" in words and "IF IT CLEARS" in words
    assert stream.cloud_lines(None) == {"hopes": [], "sky": None}
    streamlook.vertical({"kind": "cloud", "now": clock.time(), "cloud": lines})


def test_the_setup_card_crosses_off_each_step_from_what_the_steps_keep(tmp_path, monkeypatch):
    """4 November 2026: "show the steps and cross them out when complete ...
    switch to the scope when that is done ... come back if the cloud
    monitor is activated again later"."""
    import json
    import time as clock
    import config
    import director
    import stream
    monkeypatch.setattr(config, "DATA", tmp_path)
    (tmp_path / "cache").mkdir()
    now = clock.time()
    began = stream.night_began(now)
    assert now - 86400 < began <= now
    steps = stream.setup_steps(now)
    assert [s[1] for s in steps] == ["now", "open", "open", "open"]
    assert not stream.setup_card_due({"programme": None, "run_current": False}, None, now)  # not begun
    (tmp_path / "cache" / "handset_clock.json").write_text(json.dumps({"saved": now - 60}))
    (tmp_path / "cache" / "focus_runs.jsonl").write_text(json.dumps({"saved": began - 3600}) + "\n"
                                                        + json.dumps({"saved": now - 30, "checked_hfr": 2.25}) + "\n")
    (tmp_path / "cache" / "polar.json").write_text(json.dumps({"measured": began - 60, "total_deg": 1.5}))
    steps = stream.setup_steps(now)
    assert [s[1] for s in steps] == ["done", "done", "now", "open"]
    assert steps[1][2] == "in focus: star size 2.25" and steps[2][2] is None   # yesterday's polar is not tonight's
    idle = {"programme": None, "run_current": False}
    assert stream.setup_card_due(idle, None, now)                      # polar still to do: the card
    assert not stream.setup_card_due(idle, None, now + stream.SETUP_S + 60)   # left: not on air for ever
    assert not stream.setup_card_due(idle, "focus", now)               # focusing has its own look
    assert not stream.setup_card_due(dict(idle, run_current=True), None, now)
    (tmp_path / "cache" / "polar.json").write_text(json.dumps({"measured": now - 10, "total_deg": 0.2}))
    assert not stream.setup_card_due(idle, None, now)                  # set up: the telescope's picture
    assert stream.setup_card_due(dict(idle, programme=director.CLOUD, run_current=True), None, now)  # cloud again


def test_the_polar_adjust_look_gives_way_once_the_telescope_goes_to_a_target(monkeypatch):
    """4 November 2026: the M31 patrol went out under the polar look, its
    "waiting for the mount to be adjusted" held 15 minutes after the check."""
    import stream
    import streamlook
    monkeypatch.setattr(streamlook, "focus_stream_state", lambda now: None)
    monkeypatch.setattr(streamlook, "polar_stream_state", lambda now: {"stage": "adjust", "showing": True})
    monkeypatch.setattr(stream, "phase", lambda: None)
    assert stream.observatory(1.0)[0] == "polar"               # the person may be turning the bolts
    for doing in ("goto", "solve", "imaging"):
        monkeypatch.setattr(stream, "phase", lambda d=doing: d)
        assert stream.observatory(1.0) == (None, None)
    monkeypatch.setattr(streamlook, "polar_stream_state", lambda now: {"stage": "measuring", "showing": True})
    assert stream.observatory(1.0)[0] == "polar"               # its own measuring moves are its own


def test_a_smaller_stream_size_sends_full_pictures_and_lets_ffmpeg_scale():
    """4 November 2026: the bandwidth test chose 1280x720, the pictures were
    shrunk before ffmpeg, which read them as 1920x1080: garbage on air."""
    import inspect
    import stream
    cmd = stream.command("rtmp://x", None, (1280, 720))
    assert cmd[cmd.index("-s") + 1] == f"{stream.WIDTH}x{stream.HEIGHT}"
    assert "scale=1280:720" in " ".join(cmd)
    assert ".resize(size)" not in inspect.getsource(stream.main if hasattr(stream, "main") else stream)


def test_the_bandwidth_test_sends_what_every_stream_needs_together(tmp_path, monkeypatch):
    """A test of one 5 Mbit/s stream passing said nothing about two sharing
    the upload: it is sent at their bitrates added up."""
    monkeypatch.setattr(stream, "PROGRESS", tmp_path / "progress.txt")
    rates = []

    def run(cmd, **kw):
        rates.append(cmd[cmd.index("-b:v") + 1])
        (tmp_path / "stream-bandwidth.txt").write_text("drop_frames=0\nspeed=1.0x\n")
    one = int(stream.BITRATE[(stream.WIDTH, stream.HEIGHT)][:-1])
    both = ["rtmp://a.rtmp.youtube.com/live2/y", "rtmp://live.twitch.tv/app/t"]
    stream.bandwidth_test(both[1:], run=run)
    stream.bandwidth_test(both, run=run)
    stream.bandwidth_test(both, run=run, vertical=True)
    upright = int(stream.BITRATE[stream.VERTICAL][:-1])
    assert rates == [f"{one}k", f"{2 * one}k", f"{2 * one + upright}k"]


def test_a_new_target_does_not_inherit_the_last_one_s_display_sky():
    import numpy as np
    streamlook._STEADY.clear()
    dark, bright = np.full(3, 0.05), np.full(3, 0.5)
    noise = np.full(3, 0.01)
    streamlook.steady("stack", dark, noise, scene="M31")
    same, _ = streamlook.steady("stack", bright, noise, scene="M31")
    assert same[0] < 0.2                                      # smoothed: no pumping on one target
    fresh, _ = streamlook.steady("stack", bright, noise, scene="M45")
    assert fresh[0] == 0.5                                    # another target starts from its own sky


def test_youtube_not_live_is_told_once_after_ten_minutes_on_air():
    """1 November 2026: YouTube called the stream healthy while its
    broadcast sat at Preparing, and viewers saw nothing."""
    import time
    stuck = {"streams": [{"status": "active", "health": "good"}], "broadcasts": [{"life": "ready"}]}
    live = dict(stuck, broadcasts=[{"life": "live"}])
    assert stream.youtube_trouble(live) is None and stream.youtube_trouble(None) is None
    assert "active/good" in stream.youtube_trouble(stuck) and "ready" in stream.youtube_trouble(stuck)
    told, said = [], []
    check = stream.YouTubeCheck(state=lambda: stuck, tell=told.append, say=said.append)
    check.started(1000)
    check.look(1000 + stream.YT_LIVE_S - 1)
    assert not check.busy and not told                        # too soon to judge
    for later in (stream.YT_LIVE_S, stream.YT_LIVE_S + stream.YT_LOOK_S, stream.YT_LIVE_S + 3 * stream.YT_LOOK_S):
        check.look(1000 + later)
        deadline = time.time() + 5
        while check.busy and time.time() < deadline:
            time.sleep(0.01)
    assert len(told) == 1 and said == told and "see nothing" in told[0]
    fine = stream.YouTubeCheck(state=lambda: live, tell=told.append, say=said.append)
    fine.started(0)
    fine.look(stream.YT_LIVE_S)
    while fine.busy:
        time.sleep(0.01)
    assert len(told) == 1


def test_the_vertical_feed_passes_its_errors_on_without_its_key():
    import io
    import time

    class Process:
        stdin = io.BytesIO()
        stderr = io.BytesIO(b"rtmp://a.rtmp.youtube.com/live2/vert-key-123: Broken pipe\n")

        def wait(self, timeout=None):
            return 0
    said = []
    feed = stream.VerticalFeed("rtmp://a.rtmp.youtube.com/live2/vert-key-123", run=lambda *a, **k: Process(),
                               say=said.append)
    deadline = time.time() + 5
    while not said and time.time() < deadline:
        time.sleep(0.01)
    feed.stop()
    assert said and said[0].startswith("9:16 feed:") and "vert-key-123" not in said[0]


def test_what_goes_on_air_decodes_to_the_picture_sent_at_1080p_and_720p(tmp_path):
    """4 November 2026: 720p went on air as garbage while the test of
    ffmpeg's arguments passed. A known picture is encoded through the very
    command the stream runs, decoded again, and compared."""
    import shutil
    import subprocess

    import numpy as np
    import pytest
    from PIL import Image
    if not shutil.which("ffmpeg"):
        pytest.skip("no ffmpeg here")
    stream.PROGRESS.parent.mkdir(parents=True, exist_ok=True)
    w, h = stream.WIDTH, stream.HEIGHT
    picture = np.zeros((h, w, 3), dtype=np.uint8)            # four coloured quarters and a white bar
    picture[: h // 2, : w // 2] = (200, 30, 30)
    picture[: h // 2, w // 2:] = (30, 200, 30)
    picture[h // 2:, : w // 2] = (30, 30, 200)
    picture[h // 2:, w // 2:] = (220, 220, 40)
    picture[h // 2 - 40: h // 2 + 40, w // 4: 3 * w // 4] = 255
    for size in ((w, h), stream.FALLBACK):
        out = tmp_path / f"{size[0]}.mp4"
        p = subprocess.run(stream.command(str(out), None, size), input=picture.tobytes() * 20,
                           capture_output=True, timeout=120)
        assert p.returncode == 0, p.stderr.decode()
        frame = tmp_path / f"{size[0]}.png"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(out), "-vf", "select=eq(n\\,15)",
                        "-frames:v", "1", str(frame)], check=True, timeout=60)
        with Image.open(frame) as im:
            assert im.size == size
            got = np.asarray(im.convert("RGB").resize((w, h)), dtype=np.float32)
        error = np.abs(got - picture.astype(np.float32)).mean()
        assert error < 8, f"{size}: mean error {error:.1f} levels"


def test_youtube_end_ends_broadcasts_left_live_but_never_during_a_run():
    calls, said = [], []
    assert stream.youtube_end(say=said.append, st={"name": "M31", "age": 10}, end=lambda say: calls.append(1)) == 1
    assert not calls and "imaging" in said[0]
    assert stream.youtube_end(say=said.append, st={"name": "M31", "age": 9000}, end=lambda say: 1) == 0
