"""Alerts to the house: when the sky is said to have turned, and what a light is told."""
import alert


def test_dimming_stars_are_cloud_and_faint_ones_clouded_out_and_too_few_frames_say_nothing():
    steady = [240] * 20
    assert alert.sky_from_frames(steady) == "clear"
    assert alert.sky_from_frames(steady + [120] * 5) == "cloud"
    assert alert.sky_from_frames(steady + [20] * 5) == "clouded"
    assert alert.sky_from_frames(steady + [180] * 5) is None          # between the two: no change is claimed
    assert alert.sky_from_frames([240] * 8) is None
    assert alert.sky_from_frames(steady + [240, 240, None, 240, 240]) == "clear"   # one lost frame decides nothing
    assert alert.sky_from_frames(steady + [None] * 5) == "clouded"                 # no stars at all is cloud


def test_each_change_is_told_once_and_a_clear_start_is_not_news():
    events, state = alert.decide({}, "clear", False, False)
    assert events == [] and state["sky"] == "clear"
    events, state = alert.decide(state, "cloud", False, False)
    assert events == ["cloud"]
    assert alert.decide(state, "cloud", False, False)[0] == []
    events, state = alert.decide(state, "clouded", True, False)
    assert events == ["rain", "clouded"]
    assert alert.decide(state, "clouded", True, False)[0] == []
    for _ in range(alert.SETTLED - 1):                                   # broken cloud: not yet "cleared"
        events, state = alert.decide(state, "clear", False, False)
        assert events == [] and state["sky"] == "clouded"
    events, state = alert.decide(state, "clear", False, False)
    assert events == ["clear"] and state["sky"] == "clear" and state["rain"] is False


def test_a_gap_in_broken_cloud_is_not_called_clear_and_the_cloud_after_it_is_not_told_again():
    state = {"sky": "cloud"}
    events, state = alert.decide(state, "clear", False, False)
    assert events == []
    events, state = alert.decide(state, "cloud", False, False)
    assert events == [] and state["clear_looks"] == 0
    events, state = alert.decide(state, "clouded", False, False)
    assert events == ["clouded"]
    assert alert.decide(state, "cloud", False, False)[0] == []           # thinning a little is not news


def test_with_no_run_going_the_forecast_can_say_cloud_but_never_clear():
    events, state = alert.decide({"sky": "clear"}, None, False, True)
    assert events == ["cloud"]
    assert alert.decide(state, None, False, False) == ([], state)


def test_the_forecast_is_read_for_this_hour_and_the_next():
    hour = 3600
    weather = {"time": [0, hour, 2 * hour, 3 * hour], "cloud_cover": [10, 20, 90, 100],
               "precipitation_probability": [0, 0, 10, 80], "precipitation": [0, 0, 0, 0.4]}
    assert alert.forecast(weather, now=hour + 60) == (False, True)       # clear now, cloud next hour
    assert alert.forecast(weather, now=2 * hour + 60) == (True, False)   # rain next hour; already cloudy
    assert alert.forecast(weather, now=10 * hour) == (False, False)      # off the end: nothing claimed


class Bridge:
    def __init__(self, light):
        self.now, self.puts = light, []

    def light(self, light_id):
        return self.now

    def put(self, light_id, body):
        self.puts.append(body)
        self.now = {**self.now, **{k: v for k, v in body.items() if k != "alert"}}


def lamp(colour=True):
    light = {"id": "a1", "metadata": {"name": "Lamp"}, "on": {"on": False}, "dimming": {"brightness": 40.0}}
    if colour:
        light["color"] = {"xy": {"x": 0.3, "y": 0.3}}
    return light


def test_a_light_is_coloured_and_then_put_back_as_it_was():
    bridge = Bridge(lamp())
    said = alert.colour_light(bridge, bridge.now, "Orange", seconds=0, sleep=lambda s: None)
    assert bridge.puts[0]["color"]["xy"] == {"x": 0.55, "y": 0.41} and bridge.puts[0]["on"] == {"on": True}
    assert bridge.puts[1] == {"on": {"on": False}, "dimming": {"brightness": 40.0}, "color": {"xy": {"x": 0.3, "y": 0.3}}}
    assert "put back" in said


def test_a_light_someone_changed_meanwhile_is_left_alone():
    bridge = Bridge(lamp())

    def switched_off(seconds):
        bridge.now = {**bridge.now, "on": {"on": False}}
    said = alert.colour_light(bridge, bridge.now, "Blue", seconds=0, sleep=switched_off)
    assert len(bridge.puts) == 1 and "left alone" in said


def test_a_white_only_light_is_sent_no_colour():
    bridge = Bridge(lamp(colour=False))
    alert.colour_light(bridge, bridge.now, "Red", seconds=0, sleep=lambda s: None)
    assert "color" not in bridge.puts[0]


def test_a_dry_run_says_what_it_would_do_and_does_nothing(monkeypatch):
    monkeypatch.setattr(alert, "settings", lambda: {**alert.DEFAULTS, "light": "Lamp", "speaker": "Kitchen"})
    said = []
    alert.tell("rain", dry_run=True, say_it=said.append)
    assert said == ['Would turn Lamp blue and say "Rain is on the way. Cover the telescope." on Kitchen.']


def test_a_call_pulses_every_light_speaks_and_sends(monkeypatch):
    """19 October 2026: alone in the house, the person asked for every light
    and the speaker as well as Telegram when the telescope needs them."""
    monkeypatch.setattr(alert, "settings", lambda: {**alert.DEFAULTS, "speaker": "Kitchen", "seconds": 0})

    class Lights:
        def __init__(self):
            self.state = {"a1": lamp(), "b2": {**lamp(colour=False), "id": "b2"}}
            self.puts = []

        def lights(self):
            return list(self.state.values())

        def light(self, light_id):
            return self.state[light_id]

        def put(self, light_id, body):
            self.puts.append((light_id, body))
            self.state[light_id] = {**self.state[light_id], **{k: v for k, v in body.items() if k != "alert"}}

    bridge, spoken, sent, said = Lights(), [], [], []
    alert.call("Come out to the telescope.", bridge=bridge, speak=lambda words, *a: spoken.append(words) or "spoke",
               send=sent.append, say_it=said.append)
    assert {light for light, _ in bridge.puts} == {"a1", "b2"}           # every light, each put back after
    assert spoken == sent == ["Come out to the telescope."] and "sent by Telegram" in said


def test_a_call_whose_telegram_fails_still_lights_and_speaks(monkeypatch):
    monkeypatch.setattr(alert, "settings", lambda: {**alert.DEFAULTS, "speaker": "Kitchen", "seconds": 0})
    spoken, said = [], []

    def broken(words):
        raise OSError("no network")
    alert.call("Hello.", bridge=type("B", (), {"lights": lambda self: []})(), speak=lambda w, *a: spoken.append(w) or "ok",
               send=broken, say_it=said.append)
    assert spoken == ["Hello."] and any("Telegram: no network" in line for line in said)
