#!/usr/bin/env python3
"""New papers on what the telescope watches and what it hopes to find:
arXiv's newest on each topic, so a paper like July 2026's on a companion
to Tabby's star reaches the night's outlook without anyone looking.

    ./literature.py                   each topic's papers of the last DAYS days
    ./literature.py --days 90 --json

    ./literature.py --unread          what has not been marked read yet, however old
    ./literature.py --read 2610.34806 2607.01234     mark papers read

arXiv (export.arxiv.org, free, no key) is asked once a day per topic; the
answers are kept under cache/ like the other feeds, each paper with its
abstract. `ty night` lists under `papers` those not yet marked read
(cache/literature-read.json), however old, so a paper stays until it has
been read and what it claims said; before anything is marked, the last
NIGHT_DAYS days'. Each topic is a
search of titles and abstracts (TOPICS below). A paper listed is something
to read, not a result: what it claims, and how sure it is, is in the paper.
"""
import argparse
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import requests

import config
import feeds
import interface
import records

ARXIV = "https://export.arxiv.org/api/query"
ATOM = "{http://www.w3.org/2005/Atom}"
DAYS = 30          # papers of the last this many days, by default
NIGHT_DAYS = 14    # ty night lists those of the last this many days
MOST = 20          # papers asked for per topic, newest first
KEEP_HOURS = 24    # each topic asked again after this long

# What each programme watches, and what the person hopes to find (stars
# that behave strangely): arXiv's search, in titles and abstracts.
TOPICS = {
    "Tabby's star": 'abs:"KIC 8462852" OR abs:"Boyajian\'s star" OR abs:"Tabby\'s star" OR ti:"KIC 8462852"',
    "novae in M31 and M33": '(abs:nova OR abs:novae) AND (abs:M31 OR abs:"Andromeda Galaxy" OR abs:M33 '
                            'OR abs:"Triangulum Galaxy")',
    "dipping and dimming stars": 'abs:"dipper star" OR abs:"dipper stars" OR abs:"dipping star" OR abs:"aperiodic dimming" '
                                 'OR abs:exocomet OR abs:exocomets OR abs:"irregular dimming"',
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
                    "submitted": when, "link": link,
                    "abstract": re.sub(r"\s+", " ", e.findtext(f"{ATOM}summary", "")).strip()})
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


def _base(paper_id):
    """A paper's arXiv number without its version: 2610.34806v2 is 2610.34806."""
    return re.sub(r"v\d+$", "", paper_id)


def read_store():
    return config.DATA / "cache" / "literature-read.json"


def already_read():
    """The arXiv numbers marked read, or None before the first marking."""
    path = read_store()
    return set(json.loads(path.read_text(encoding="utf-8"))) if path.exists() else None


def mark_read(ids):
    """Mark papers read (by arXiv number, any version), so they are listed no more."""
    done = (already_read() or set()) | {_base(i) for i in ids}
    path = read_store()
    path.parent.mkdir(parents=True, exist_ok=True)
    records.write(path, sorted(done))
    return done


def unread(now=None, get=requests.get, topics=None, days=NIGHT_DAYS):
    """Each topic's papers not yet marked read, however old (among its MOST
    newest), so a paper is listed until someone has read it rather than
    only in its first NIGHT_DAYS. Before anything is marked read, only the
    last `days` days' count as unread."""
    marked = already_read()
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    out = []
    for name in topics or TOPICS:
        papers = topic(name, get) or []
        if marked is None:
            left = [p for p in papers if datetime.fromisoformat(p["submitted"].replace("Z", "+00:00")) >= since]
        else:
            left = [p for p in papers if _base(p["id"]) not in marked]
        out.append({"topic": name, "papers": left})
    return out


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
    if args.read:
        done = mark_read(args.read)
        say(f"{len(args.read)} marked read ({len(done)} in all)")
        return {"marked_read": sorted(_base(i) for i in args.read), "kind": "inferred"}
    found = unread() if args.unread else recent(args.days)
    for t in found:
        say(f"{t['topic']}: {len(t['papers'])} in the last {args.days:g} days")
        for p in t["papers"]:
            say(f"  {p['submitted'][:10]}  {p['title']}  ({p['authors']})  {p['link']}")
    return {"days": None if args.unread else args.days, "topics": found, "sources": feeds.freshness(), "kind": "inferred"}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--days", type=float, default=DAYS, help=f"papers of the last this many days (default {DAYS})")
    ap.add_argument("--unread", action="store_true", help="the papers not yet marked read, however old")
    ap.add_argument("--read", nargs="+", metavar="ID", help="mark these arXiv papers read (2610.34806)")
    ap.add_argument("--json", action="store_true", help="the answer as JSON")
    args = ap.parse_args()
    interface.main("literature", lambda: run(args), args.json)


if __name__ == "__main__":
    main()
