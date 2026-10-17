"""Each field's reference: the deepest measured stack is kept as a numbered
version with where it came from, the newest is what new nights are compared
with, and a night is never compared with itself."""
import json

import pytest

import config
import interface
import reference


def measured(tmp_path, session, half, fwhm=6.0):
    folder = tmp_path / "frames" / "M31" / session
    folder.mkdir(parents=True)
    (folder / "final.fits").write_bytes(b"stack " + session.encode())
    (folder / "depth.json").write_text(json.dumps({
        "stack": str(folder / "final.fits"), "zeropoint": 23.1, "fwhm_arcsec": fwhm, "sky_mag_per_arcsec2": 19.0,
        "exposure_s": 3000.0, "frames": 200, "completeness": {"all": {"mag_50": half}}}))
    return folder


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    return tmp_path


def test_the_deepest_measured_stack_is_kept_with_where_it_came_from(data):
    measured(data, "20261013-232632", 17.6)
    deep = measured(data, "20261020-220000", 17.9, fwhm=4.6)
    made = reference.make("M31")
    assert made["version"] == 1 and made["source"] == str(deep / "final.fits") and made["mag_50"] == 17.9
    assert reference.newest("M31").read_bytes() == b"stack 20261020-220000"
    # Its depth goes with it, for the zero point.
    assert json.loads((data / "reference" / "M31" / "v1-depth.json").read_text())["zeropoint"] == 23.1


def test_a_new_version_never_replaces_an_old_one(data):
    first = measured(data, "20261013-232632", 17.6)
    reference.make("M31")
    later = measured(data, "20261020-220000", 17.9)
    reference.make("M31")
    versions = reference.kept("M31")
    assert [v["version"] for v in versions] == [1, 2]
    assert (data / "reference" / "M31" / "v1.fits").read_bytes() == b"stack 20261013-232632"
    assert reference.sessions_used("M31") == {first.resolve(), later.resolve()}


def test_a_stack_without_a_measurement_is_not_made_a_reference(data):
    with pytest.raises(interface.Refusal) as refused:
        reference.make("M31")
    assert refused.value.code_name == "NO_SESSION"


def test_a_panel_without_its_own_reference_uses_the_whole_objects(data):
    measured(data, "20261013-232632", 17.6)
    reference.make("M31")
    path, owner = reference.for_field("M31-P3")
    assert owner == "M31" and path == reference.newest("M31")
    assert reference.for_field("M33") == (None, None)


def test_a_stack_that_could_hold_an_open_candidate_is_not_made_a_reference(data, monkeypatch):
    import candidates
    import mount
    monkeypatch.setattr(mount, "find_target", lambda name: {"id": name, "ra": 10.68, "dec": 41.27})
    measured(data, "20261020-221500", 17.9)
    book = candidates.load("M31")
    candidates.add_night(book, "20261018-220000", [{"ra": 10.80, "dec": 41.40, "score": 6.0, "mag": 17.5,
                                                    "verdict": "unexplained: worth a person's eyes"}])
    candidates.save(book)
    with pytest.raises(interface.Refusal) as refused:
        reference.make("M31")
    assert "M31-20261018-220000-001" in refused.value.message
    made = reference.make("M31", force=True)
    assert made["held_back"] == ["M31-20261018-220000-001"]


def test_a_stack_from_before_the_candidate_is_clean(data, monkeypatch):
    import candidates
    import mount
    monkeypatch.setattr(mount, "find_target", lambda name: {"id": name, "ra": 10.68, "dec": 41.27})
    measured(data, "20261013-232632", 17.6)
    book = candidates.load("M31")
    candidates.add_night(book, "20261018-220000", [{"ra": 10.80, "dec": 41.40, "score": 6.0, "mag": 17.5,
                                                    "verdict": "unexplained: worth a person's eyes"}])
    candidates.save(book)
    assert reference.make("M31")["held_back"] == []
