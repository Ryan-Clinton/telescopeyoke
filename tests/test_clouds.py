"""The satellite cloud picture: a bad answer from the service is said plainly."""
import types

import pytest

import clouds


def test_an_answer_that_is_not_a_picture_is_said_plainly(monkeypatch):
    page = types.SimpleNamespace(content=b"<html>busy</html>", headers={"content-type": "text/html"},
                                 raise_for_status=lambda: None)
    monkeypatch.setattr(clouds.requests, "get", lambda *a, **k: page)
    with pytest.raises(RuntimeError, match="sent no picture .* just now \\(text/html\\)"):
        clouds._layer("mtg_fd:ir105_hrfi", (0, 0, 1, 1))
