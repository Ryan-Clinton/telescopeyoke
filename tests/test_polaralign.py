import polaralign


def test_two_sides_that_agree_give_the_axis_between_them():
    agree, gap, az, alt = polaralign.cross_check((2.4, 2.8), (2.0, 2.6), 55)
    assert agree and gap < 0.4 and (az, alt) == (2.2, 2.7)


def test_two_sides_that_disagree_are_caught():
    # 13 October 2026, before the Dec axis's movement was allowed for.
    agree, gap, _, _ = polaralign.cross_check((-1.2, -0.5), (4.8, 0.2), 55)
    assert not agree and gap > 3


class FakeMount:
    dec_axis = 40.0

    def axes(self):
        return 0.0, self.dec_axis

    def save_clock(self, site):
        pass

    def drift_model(self, site):
        return type("Model", (), {"set_polar": lambda self, az, alt: None})()


def measure_twice(monkeypatch, tmp_path, first, second):
    import argparse
    import config
    monkeypatch.setattr(polaralign, "SIDES_FILE", tmp_path / "sides.json")
    monkeypatch.setattr(polaralign, "POLAR_FILE", tmp_path / "polar.json")
    monkeypatch.setattr(polaralign.mount, "CLOCK_FILE", tmp_path / "clock.json")
    monkeypatch.setattr(polaralign.config, "load", config.example)
    scope = FakeMount()
    monkeypatch.setattr(polaralign.mount, "Mount", lambda: scope)
    args = argparse.Namespace(dry_run=False, cross_check=True, step=25.0, repeat=1, turned=None)
    answers = []
    for dec_axis, found in ((40.0, first), (140.0, second)):
        scope.dec_axis = dec_axis
        monkeypatch.setattr(polaralign, "measure", lambda *a, found=found: found)
        answers.append(polaralign.run(args))
    return answers


def test_a_cross_check_that_disagrees_gives_no_advice(monkeypatch, tmp_path):
    first, second = measure_twice(monkeypatch, tmp_path, (-1.2, -0.5), (4.8, 0.2))
    assert "cross_check" not in first
    assert second["advice"] is None and not second["cross_check"]["agree"]


def test_a_cross_check_that_agrees_advises_on_the_middle(monkeypatch, tmp_path):
    _, second = measure_twice(monkeypatch, tmp_path, (2.4, 2.8), (2.0, 2.6))
    assert second["cross_check"]["agree"] and second["altitude_deg"] == 2.7
