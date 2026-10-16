import pytest

import config
import interface
import remote


def test_a_session_keeps_its_place_under_the_data_folder_on_the_other_computer():
    session = config.DATA / "frames" / "M31" / "20261013-232632"
    assert remote.there(session) == "telescopeyoke-remote/data/frames/M31/20261013-232632"


def test_a_folder_outside_the_data_is_refused_before_anything_is_sent(tmp_path, monkeypatch):
    monkeypatch.setattr(remote, "ssh", lambda *a, **k: pytest.fail("nothing should be sent"))
    with pytest.raises(interface.Refusal):
        remote.restack("desktop", [tmp_path / "elsewhere"], [])
