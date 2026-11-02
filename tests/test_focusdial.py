"""The printable focus-knob dial is drawn at true size."""
import math
import re

import focusdial


def test_the_strip_is_as_long_as_the_knob_is_round_and_has_a_tick_a_degree(tmp_path):
    page = focusdial.svg(40)
    assert 'width="145.7mm"' in page                       # the rim, 125.7 mm, and its margins
    strip = re.search(r'<rect x="10" y="16" width="([\d.]+)"', page)
    assert float(strip.group(1)) == round(math.pi * 40, 3)
    assert page.count("<line") == 1 + 360 + 360               # the 50 mm bar, the strip, the disc
    assert '<line x1="10" y1="11" x2="60" y2="11"' in page   # the check bar is 50 mm
    focusdial.main(["--diameter", "40", "--out", str(tmp_path / "dial.svg")])
    assert (tmp_path / "dial.svg").read_text().startswith("<svg")
