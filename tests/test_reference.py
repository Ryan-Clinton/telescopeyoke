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


FRAME = {"ra": 10.68, "dec": 41.27, "cd": [[-0.000378, 0.0], [0.0, 0.000378]], "width_px": 2700, "height_px": 1800}


def test_only_a_candidate_inside_the_stacks_own_frame_holds_it_back(data, monkeypatch):
    """4 November 2026: a circle round the field's centre held back M31-P8's
    clean stack for a candidate outside that stack's frame. The stack's own
    plate solve decides; a candidate inside it still holds it back."""
    import candidates
    import mount
    monkeypatch.setattr(mount, "find_target", lambda name: {"id": name, "ra": 10.68, "dec": 41.27})
    folder = measured(data, "20261020-221500", 17.9)
    record = json.loads((folder / "depth.json").read_text())
    (folder / "depth.json").write_text(json.dumps(dict(record, footprint=FRAME)))
    book = candidates.load("M31")
    # 0.45 degrees north: inside the old 0.6 degree circle, outside a 0.68 degree tall frame.
    candidates.add_night(book, "20261018-220000", [{"ra": 10.68, "dec": 41.72, "score": 6.0, "mag": 17.5,
                                                    "verdict": "unexplained: worth a person's eyes"}])
    candidates.save(book)
    assert reference.make("M31")["held_back"] == []
    # One inside the frame still stops it, as before.
    candidates.add_night(book, "20261019-220000", [{"ra": 10.80, "dec": 41.40, "score": 6.0, "mag": 17.5,
                                                    "verdict": "unexplained: worth a person's eyes"}])
    candidates.save(book)
    with pytest.raises(interface.Refusal) as refused:
        reference.make("M31")
    assert "M31-20261019-220000-002" in refused.value.message
    assert "M31-20261018-220000-001" not in refused.value.message


def test_a_stack_that_cannot_be_placed_keeps_the_cautious_circle(data, monkeypatch):
    import candidates
    import mount
    monkeypatch.setattr(mount, "find_target", lambda name: {"id": name, "ra": 10.68, "dec": 41.27})
    measured(data, "20261020-221500", 17.9)       # no kept solve, and the solve below fails
    book = candidates.load("M31")
    candidates.add_night(book, "20261018-220000", [{"ra": 10.68, "dec": 41.72, "score": 6.0, "mag": 17.5,
                                                    "verdict": "unexplained: worth a person's eyes"}])
    candidates.save(book)

    def no_solve(lum, name):
        raise interface.Refusal("PLATE_SOLVE_FAILED", "no")
    with pytest.raises(interface.Refusal):
        reference.make("M31", solver=no_solve)


def test_a_candidate_inside_the_frame_but_outside_the_circle_still_holds_it_back(data, monkeypatch):
    """A frame sits off the catalogue's centre and its corners reach past
    0.6 degrees: the frame is the authority whenever it is known, so a
    candidate in it is never missed for being outside the circle."""
    import candidates
    import mount
    monkeypatch.setattr(mount, "find_target", lambda name: {"id": name, "ra": 10.68, "dec": 41.27})
    folder = measured(data, "20261020-221500", 17.9)
    record = json.loads((folder / "depth.json").read_text())
    (folder / "depth.json").write_text(json.dumps(dict(record, footprint=dict(FRAME, dec=41.57))))
    book = candidates.load("M31")
    # 0.62 degrees from the catalogue's centre, 0.32 from the frame's (half its height is 0.34).
    candidates.add_night(book, "20261018-220000", [{"ra": 10.68, "dec": 41.89, "score": 6.0, "mag": 17.5,
                                                    "verdict": "unexplained: worth a person's eyes"}])
    candidates.save(book)
    with pytest.raises(interface.Refusal) as refused:
        reference.make("M31")
    assert "M31-20261018-220000-001" in refused.value.message


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


def test_locate_keeps_the_references_solve_for_its_footprint(data, monkeypatch):
    """A reference made before depth.py kept its solve gets one: the solve
    is kept in its depth record, and footprint.py then places the frame by
    it, turned as solved, instead of at the catalogue's centre."""
    import numpy as np
    from astropy.io import fits
    from astropy.wcs import WCS

    import depth
    import footprint
    measured(data, "20261013-232632", 17.6)
    reference.make("M31")
    path = reference.newest("M31")
    fits.writeto(path, np.zeros((40, 60), dtype=np.float32), overwrite=True)
    scale = 0.66 / 3600

    def solver(lum, name):
        w = WCS(naxis=2)
        w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
        w.wcs.crval = [10.70, 41.30]
        w.wcs.crpix = [(lum.shape[1] + 1) / 2, (lum.shape[0] + 1) / 2]
        w.wcs.cd = np.array([[0, -scale], [scale, 0]])         # turned a quarter
        return w
    kept = reference.locate("M31", solver=solver)
    assert kept["width_px"] == 60 and kept["height_px"] == 40
    record = json.loads(depth.record_path(path).read_text())
    assert record["footprint"]["ra"] == 10.7 and record["zeropoint"] == 23.1    # the measurement kept with it
    fp = footprint.of_reference("M31")
    assert fp["source"].startswith("plate solve") and fp["across"] == [0.0, 1.0]
    assert footprint.of_field("M31") == [fp]


def test_locate_without_a_reference_is_refused(data):
    with pytest.raises(interface.Refusal):
        reference.locate("M33")
