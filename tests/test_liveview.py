"""The live view's Moon hold: the disc found in each look and the mount moved
back once it has drifted, by the picture's measured directions."""
import json

import numpy as np

import liveview


class Scope:
    def __init__(self):
        self.moves = []

    def goto_target(self, name, site, aim_off=(0.0, 0.0)):
        self.moves.append((name, aim_off))


def moon_at(cy, cx, r=60, shape=(400, 600)):
    rows, cols = np.indices(shape)
    mosaic = np.full(shape, 30, np.uint16)
    mosaic[(rows - cy) ** 2 + (cols - cx) ** 2 <= r * r] = 3000
    return mosaic


# A move of 1' east takes the picture 8 px right; 1' north, 8 px up.
MATRIX = [[0.0, 8.0], [-8.0, 0.0]]


def test_a_drifted_moon_is_moved_back_to_the_middle_and_a_centred_one_is_left():
    scope = Scope()
    aim = liveview.hold_moon(scope, {}, [-67.0, 31.0], MATRIX, moon_at(200, 340), say=lambda m: None)
    assert len(scope.moves) == 1 and scope.moves[0][0] == "Moon"
    assert tuple(aim) == scope.moves[0][1]
    # The move takes the picture back by the disc's 40 px to the right of the middle.
    down, right = np.asarray(MATRIX) @ np.subtract(aim, [-67.0, 31.0])
    assert abs(down) < 2 and abs(right + 40) < 2
    still = liveview.hold_moon(scope, {}, aim, MATRIX, moon_at(199.5, 300.5), say=lambda m: None)
    assert still == aim and len(scope.moves) == 1


def test_no_moon_in_the_look_moves_nothing():
    scope = Scope()
    dark = np.full((400, 600), 30, np.uint16)
    assert liveview.hold_moon(scope, {}, [1.0, 2.0], MATRIX, dark, say=lambda m: None) == [1.0, 2.0]
    assert not scope.moves


def test_the_hold_starts_from_where_the_newest_moon_video_was_centred(tmp_path, monkeypatch):
    import lucky
    monkeypatch.setattr(lucky, "OUT", tmp_path)
    assert liveview.last_moon_aim() == [0.0, 0.0]
    (tmp_path / "Moon-20261030-021112.json").write_text(json.dumps({"aim": [-67.3, 26.9]}))
    (tmp_path / "Moon-20261030-021837.json").write_text(json.dumps({"aim": [-67.3, 30.5]}))
    assert liveview.last_moon_aim() == [-67.3, 30.5]
