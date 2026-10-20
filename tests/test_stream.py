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
