"""Settings read at the moment of use, changeable while a run is going."""
import pytest

import live


def test_the_usual_until_set_and_a_change_applies_at_the_next_read():
    assert live.get("patrol.second_look_minutes") == 10.0
    live.set_("patrol.second_look_minutes", live.parse("patrol.second_look_minutes", "6"))
    assert live.get("patrol.second_look_minutes") == 6.0
    live.clear("patrol.second_look_minutes")
    assert live.get("patrol.second_look_minutes", 10) == 10


def test_yes_and_no_and_unknown_names():
    assert live.parse("patrol.second_looks", "no") is False and live.parse("patrol.second_looks", "on") is True
    with pytest.raises(ValueError):
        live.parse("patrol.second_looks", "maybe")
    with pytest.raises(ValueError):
        live.parse("patrol.nonsense", "1")


def test_the_patrol_and_the_imaging_run_read_them_when_they_need_them():
    """Each is read where it is used, not kept from the start."""
    from pathlib import Path
    root = Path(live.__file__).parent
    patrol, shoot = (root / "patrol.py").read_text(), (root / "shoot.py").read_text()
    assert 'live.get("patrol.second_look_minutes"' in patrol and 'live.get("patrol.second_looks")' in patrol
    assert 'live.get("shoot.cloud_stop"' in shoot and 'live.get("shoot.assist_every"' in shoot
