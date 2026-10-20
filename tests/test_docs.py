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


FACTS = ROOT / "docs" / "validation.toml"
MARK = {"proven": "✅", "partly": "⚠️", "simulated": "🧪", "tried": "❌"}


def facts():
    import tomllib
    return tomllib.loads(FACTS.read_text(encoding="utf-8"))["facts"]


def test_each_fact_stands_in_the_validation_record_as_it_does_in_its_index():
    conclusions = text(VALIDATION).split("## Current conclusions")[1].split("\n## ")[0]
    rows = {line.split("|")[1].strip(): line.split("|")[2].strip()
            for line in conclusions.splitlines() if line.startswith("| ") and line.count("|") >= 3}
    for name, fact in facts().items():
        assert fact["row"] in rows, f"{name}: no row '{fact['row']}' in validation.md's Current conclusions"
        assert rows[fact["row"]].startswith(MARK[fact["status"]]), \
            f"{name}: validation.md has '{rows[fact['row']][:20]}', the index says {fact['status']}"


@pytest.mark.parametrize("path", [p for p in PAGES + [ROOT / "docs" / "index.html"] if current(p)],
                         ids=lambda p: str(p.relative_to(ROOT)))
def test_no_page_still_says_what_a_proven_fact_has_overtaken(path):
    body = text(path)
    for name, fact in facts().items():
        for stale in fact.get("contradicted_by", []):
            assert stale not in body, f"{path.relative_to(ROOT)} still says '{stale}' ({name} is {fact['status']})"


UNPROVEN = ("only on a simulated mount", "only on the simulated mount", "simulated only", "not yet proven",
            "Not yet proven", "has not yet run", "not yet been run", "untried")


def sentences(body):
    return re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", body))


@pytest.mark.parametrize("path", [p for p in PAGES + [ROOT / "docs" / "index.html"] if current(p)],
                         ids=lambda p: str(p.relative_to(ROOT)))
def test_no_sentence_calls_a_proven_fact_unproven_whatever_its_wording(path):
    for name, fact in facts().items():
        if fact["status"] != "proven":
            continue
        for sentence in sentences(text(path)):
            if any(m in sentence for m in fact.get("mentions", [])):
                said = [u for u in UNPROVEN if u in sentence]
                assert not said, f"{path.relative_to(ROOT)}: '{sentence[:160]}' calls {name} {said[0]!r}"


def test_the_readme_status_table_agrees_with_the_facts():
    status = text(ROOT / "README.md").split("## Current status")[1].split("\n## ")[0]
    rows = {line.split("|")[1].strip(): line for line in status.splitlines() if line.startswith("| ")}
    for name, fact in facts().items():
        if "readme" not in fact:
            continue
        assert fact["readme"] in rows, f"{name}: no row '{fact['readme']}' in the README's Current status"
        cells = [c.strip() for c in rows[fact["readme"]].split("|")[2:-1]]
        if fact["status"] == "proven":
            assert any(c.startswith("✅") for c in cells[:2]), f"{name} is proven; the README row says {cells}"
        else:
            assert not cells[0].startswith("✅"), f"{name} is {fact['status']}; the README row says {cells}"


def test_the_sentence_check_would_have_caught_the_first_night_page():
    # 20 October 2026: an exact-wording ban missed this variant on docs/first-night.md.
    old = ("Finding and marking the true home (step 7) and the click-and-tone focusing sounds have so far run "
           "only on a simulated mount and made-up stars.")
    mentions = facts()["true_home"]["mentions"]
    assert any(m in old for m in mentions) and any(u in old for u in UNPROVEN)
