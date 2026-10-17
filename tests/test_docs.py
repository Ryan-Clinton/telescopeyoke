"""The documentation keeps to docs/validation.md, and its links lead somewhere.

docs/validation.md is the one record of what has been proven; the other
pages follow it. These catch the ways they have drifted from it before.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PAGES = sorted([ROOT / "README.md", ROOT / "AGENTS.md", ROOT / "CLAUDE.md", ROOT / "CONTRIBUTING.md",
                *ROOT.glob("docs/**/*.md")])
VALIDATION = ROOT / "docs" / "validation.md"


def text(path):
    return path.read_text(encoding="utf-8")


def current(path):
    """The pages that state the present: not the validation record, which
    keeps old figures as history, and not the changelog, which is history."""
    return path != VALIDATION and path.name != "CHANGELOG.md"


@pytest.mark.parametrize("path", [p for p in PAGES + [ROOT / "docs" / "index.html"] if current(p)],
                         ids=lambda p: str(p.relative_to(ROOT)))
def test_no_page_states_a_figure_the_validation_record_found_wrong(path):
    # 6 October's polar figures were wrong by degrees (validation.md, 13 October).
    assert not re.search(r"5\.2° to 0\.2°", text(path))


def test_the_polar_result_in_the_readme_is_the_validation_records():
    figure = "3.3° to 0.1°"
    assert figure in text(VALIDATION).split("## Current conclusions")[1].split("\n## ")[0]
    assert figure in text(ROOT / "README.md")


def test_the_pages_do_not_say_things_that_stopped_being_true():
    assert "Not built." not in text(ROOT / "docs" / "discovery.md")[:1000]
    assert "dozen short scripts" not in text(ROOT / "README.md")
    assert "does not use it yet" not in text(ROOT / "AGENTS.md")
    for path in (ROOT / "README.md", ROOT / "docs" / "setup.md"):
        assert "Polaris shows in a short exposure by day" not in text(path)


def test_the_validation_record_has_its_conclusions_first():
    body = text(VALIDATION)
    assert body.index("## Current conclusions") < body.index("## Why frames are slow")


@pytest.mark.parametrize("path", PAGES, ids=lambda p: str(p.relative_to(ROOT)))
def test_every_relative_link_leads_to_a_file(path):
    for target in re.findall(r"\]\(([^)\s]+)\)", text(path)):
        if re.match(r"[a-z]+:", target) or target.startswith("#"):
            continue
        file = target.split("#")[0]
        assert (path.parent / file).exists(), f"{path.relative_to(ROOT)} links to {target}"
