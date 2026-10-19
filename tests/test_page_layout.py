"""The status page at :8080: what comes in what order, and the pictures on a
page of their own (20 October 2026)."""
import config
import page
import tonight


def built(tmp_path):
    rep = tonight.build(config.example(), demo=True)
    page.write(rep, 5, tmp_path / "index.html")
    return (tmp_path / "index.html").read_text(), tmp_path / "pictures.html"


def test_imaging_then_the_schedule_then_discovery(tmp_path):
    html, _ = built(tmp_path)
    order = [html.index(f"<h2>{title}</h2>") for title in ("Imaging", "Tonight's schedule", "Tonight's discovery")]
    assert order == sorted(order)


def test_the_pictures_have_a_page_of_their_own_in_the_same_style(tmp_path):
    html, pictures = built(tmp_path)
    assert pictures.exists() and 'href="pictures.html"' in html
    other = pictures.read_text()
    assert html[html.index("<style>"):html.index("</style>")] in other and "status.json" in other


def test_the_page_script_names_each_function_once(tmp_path):
    """A second function of the same name silently replaces the first."""
    import re
    html, _ = built(tmp_path)
    names = re.findall(r"function (\w+)\(", html)
    assert len(names) == len(set(names)), sorted(n for n in names if names.count(n) > 1)


def test_the_page_names_no_place(tmp_path):
    """20 October 2026: the heading said where the telescope stands."""
    html, _ = built(tmp_path)
    assert config.example()["site"]["name"] not in html


def test_the_feeds_blank_the_place_wherever_it_appears():
    import serve
    answer = {"data": {"site": "Back garden, Somewhere", "notes": ["clear at Back garden, Somewhere tonight"],
                       "rows": [{"site": "Back garden, Somewhere"}], "other": 3}}
    out = serve.unplaced(answer, "Back garden, Somewhere")
    assert out["data"]["site"] == "" and "Somewhere" not in str(out) and out["data"]["other"] == 3
