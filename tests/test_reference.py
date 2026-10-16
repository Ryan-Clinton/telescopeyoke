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
