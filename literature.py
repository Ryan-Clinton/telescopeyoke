#!/usr/bin/env python3
"""New papers on what the telescope watches and what it hopes to find:
arXiv's newest on each topic, so a paper like July 2026's on a companion
to Tabby's star reaches the night's outlook without anyone looking.

    ./literature.py                   each topic's papers of the last DAYS days
    ./literature.py --days 90 --json

arXiv (export.arxiv.org, free, no key) is asked once a day per topic; the
answers are kept under cache/ like the other feeds, and `ty night` lists
the papers of the last NIGHT_DAYS days under `papers`. Each topic is a
search of titles and abstracts (TOPICS below). A paper listed is something
to read, not a result: what it claims, and how sure it is, is in the paper.
"""
import argparse
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import requests

import feeds
import interface

ARXIV = "https://export.arxiv.org/api/query"
ATOM = "{http://www.w3.org/2005/Atom}"
DAYS = 30          # papers of the last this many days, by default
NIGHT_DAYS = 14    # ty night lists those of the last this many days
MOST = 20          # papers asked for per topic, newest first
KEEP_HOURS = 24    # each topic asked again after this long

# What each programme watches, and what the person hopes to find (SETI and
# stars that behave strangely): arXiv's search, in titles and abstracts.
TOPICS = {
    "Tabby's star": 'abs:"KIC 8462852" OR abs:"Boyajian\'s star" OR abs:"Tabby\'s star" OR ti:"KIC 8462852"',
    "novae in M31 and M33": '(abs:nova OR abs:novae) AND (abs:M31 OR abs:"Andromeda Galaxy" OR abs:M33 '
                            'OR abs:"Triangulum Galaxy")',
    "dipping and dimming stars": 'abs:"dipper star" OR abs:"dipper stars" OR abs:"dipping star" OR abs:"aperiodic dimming" '
                                 'OR abs:exocomet OR abs:exocomets OR abs:"irregular dimming"',
    "technosignatures and SETI": 'abs:technosignature OR abs:technosignatures OR abs:SETI OR abs:"Breakthrough Listen"',
    "exoplanet transit timing": '(abs:"transit timing" OR abs:ExoClock) AND cat:astro-ph.EP',
}


def read(text):
    """The papers in an arXiv Atom answer: id, title, first authors, when
    submitted (UTC), link."""
    out = []
    for e in ET.fromstring(text).iter(f"{ATOM}entry"):
        link = (e.findtext(f"{ATOM}id") or "").strip()
        when = (e.findtext(f"{ATOM}published") or "").strip()
        if not link or not when:
            continue
        authors = [a.findtext(f"{ATOM}name", "").strip() for a in e.iter(f"{ATOM}author")]
        out.append({"id": link.rsplit("/", 1)[-1], "title": re.sub(r"\s+", " ", e.findtext(f"{ATOM}title", "")).strip(),
                    "authors": ", ".join(authors[:3]) + (" et al." if len(authors) > 3 else ""),
                    "submitted": when, "link": link})
    return out


def topic(name, get=requests.get):
    """A topic's newest papers, kept for KEEP_HOURS (feeds' cache, so its
    freshness is said with the other feeds); None when arXiv cannot be had."""
    def fetch():
        r = get(ARXIV, params={"search_query": TOPICS[name], "sortBy": "submittedDate", "sortOrder": "descending",
                               "max_results": MOST}, timeout=feeds.TIMEOUT, headers=feeds.HEADERS)
        r.raise_for_status()
        return read(r.text)
    key = "arxiv_" + re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return feeds._cached(key, KEEP_HOURS, fetch)


def recent(days=DAYS, now=None, get=requests.get, topics=None):
    """Each topic's papers submitted in the last `days` days, newest first."""
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    out = []
    for name in topics or TOPICS:
        papers = topic(name, get) or []
        fresh = [p for p in papers if datetime.fromisoformat(p["submitted"].replace("Z", "+00:00")) >= since]
        out.append({"topic": name, "papers": fresh})
    return out


def run(args, say=print):
    found = recent(args.days)
    for t in found:
        say(f"{t['topic']}: {len(t['papers'])} in the last {args.days:g} days")
        for p in t["papers"]:
            say(f"  {p['submitted'][:10]}  {p['title']}  ({p['authors']})  {p['link']}")
    return {"days": args.days, "topics": found, "sources": feeds.freshness(), "kind": "inferred"}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--days", type=float, default=DAYS, help=f"papers of the last this many days (default {DAYS})")
    ap.add_argument("--json", action="store_true", help="the answer as JSON")
    args = ap.parse_args()
    interface.main("literature", lambda: run(args), args.json)


if __name__ == "__main__":
    main()
