"""Live streaming to YouTube or Twitch: when it starts and stops, where it
goes, what is in the picture, and that the stream key never shows."""
import config
import stream


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
    assert (stream.KEY_FILE.stat().st_mode & 0o777) == 0o600


def test_it_stays_on_air_between_targets_and_holds_the_end_card():
    quiet = {"name": "WASP-12", "age": 400}
    action, since = stream.decide(True, quiet, None, 0, between=True)
    assert action == "carry on"
    assert stream.decide(True, quiet, 0, 10 * stream.STOP_S, between=True)[0] == "carry on"
    assert stream.decide(True, quiet, 0, stream.END_S - 1, ending=True)[0] == "carry on"
    assert stream.decide(True, quiet, 0, stream.END_S, ending=True)[0] == "stop"


def test_the_next_step_due_soon_and_the_night_over_come_from_the_schedule():
    soon = {"schedule": {"steps": [{"label": "a", "status": "done"}, {"label": "b", "status": "queued", "start": 600}]}}
    assert stream.due_soon(soon, 0) and not stream.due_soon(soon, 0, within=60)
    over = {"schedule": {"steps": [{"label": "a", "status": "done"}, {"label": "b", "status": "skipped"}]}}
    assert stream.night_over(over) and not stream.night_over(soon) and not stream.night_over({})


def test_it_goes_down_to_720p_only_when_it_keeps_falling_behind():
    assert stream.speed("frame=1\nspeed=0.98x\nprogress=continue\nspeed=0.79x\n") == 0.79
    assert stream.speed("speed=N/A\n") is None
    slow = [(t, 0.8) for t in range(0, 40, 5)]
    assert stream.falling_behind(slow, 40)
    assert not stream.falling_behind(slow[-2:], 40)                      # not for long enough yet
    assert not stream.falling_behind(slow[:-1] + [(35, 1.0)], 40)       # it caught up
    assert stream.BITRATE[stream.FALLBACK] and "scale=1280:720" in " ".join(stream.encoder(None, stream.FALLBACK))


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
    fine = [(t, 1.0) for t in range(0, 40, 5)]
    assert not stream.falling_behind(fine, 40, drops=[(0, 0), (40, 5)])
    assert stream.falling_behind(fine, 40, drops=[(0, 0), (40, 5 + stream.FPS + 1)])
