#!/usr/bin/env python3
"""Make a release: the zip people download, its notes, and the tag.

    ./release.py             build TelescopeYoke-vX.Y.Z.zip and the notes, and check everything agrees
    ./release.py --publish   the same, then tag this commit and publish the release on GitHub

The version is agent.VERSION. The zip is this commit exactly as git has it,
in a folder named after the version, so a report from someone who downloaded
it says which code they ran. Nothing is published without --publish, and
that refuses unless the work is committed and pushed.
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

import agent

ROOT = Path(__file__).parent
REPO = "https://github.com/Ryan-Clinton/telescopeyoke"
OUT = ROOT / "dist"


def names(version=agent.VERSION):
    """(tag, zip file name, the address the zip is downloaded from)."""
    tag = f"v{version}"
    return tag, f"TelescopeYoke-{tag}.zip", f"{REPO}/releases/download/{tag}/TelescopeYoke-{tag}.zip"


def changes(version=agent.VERSION):
    """(title, text) of this version's section in CHANGELOG.md."""
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    found = re.search(rf"^## {re.escape(version)}: (.+?)\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    if not found:
        raise SystemExit(f"CHANGELOG.md has no section for {version}")
    return found.group(1).strip(), found.group(2).strip()


def disagreements(version=agent.VERSION):
    """What does not match this version: the package's version, and any
    download link in the README or the home page that names another one."""
    wrong = []
    if f'version = "{version}"' not in (ROOT / "pyproject.toml").read_text(encoding="utf-8"):
        wrong.append(f"pyproject.toml does not say version {version}")
    address = names(version)[2]
    for page in ("README.md", "docs/index.html"):
        links = re.findall(rf"{re.escape(REPO)}/releases/download/[^\s\")]+", (ROOT / page).read_text(encoding="utf-8"))
        if not links:
            wrong.append(f"{page} has no download link to a release")
        wrong += [f"{page} links {link}, not {address}" for link in sorted(set(links)) if link != address]
    return wrong


def notes(version=agent.VERSION):
    tag, name, address = names(version)
    _, text = changes(version)
    return f"""![The demo: tonight's report, a GoTo centred by plate solving, focusing, and an imaging run]({REPO}/raw/{tag}/docs/tour.gif)

**To try it, with no telescope:** download [{name}]({address}) and unpack it.
On Ubuntu run `./install.sh --demo` in the folder. On Windows, with Python 3.11
or newer installed, double-click `try-demo.cmd`. A pretend mount, camera and
sky open in a window; nothing real is connected or moved.

**Have an EQ3, EQ5, HEQ5 or EQ6 with a SynScan handset?** Run
`./doctor.py --report` and paste what it writes into a
[hardware report]({REPO}/issues/new?template=hardware-report.md). It only
looks at what is connected; you do not have to let it move the mount.

{text}
"""


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def build(version=agent.VERSION):
    tag, name, _ = names(version)
    OUT.mkdir(exist_ok=True)
    git("archive", "--format=zip", f"--prefix={name[:-4]}/", "-o", str(OUT / name), "HEAD")
    (OUT / "notes.md").write_text(notes(version), encoding="utf-8")
    return OUT / name, OUT / "notes.md"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--publish", action="store_true", help="tag this commit and publish the release on GitHub")
    args = ap.parse_args()

    tag, name, address = names()
    title, _ = changes()
    wrong = disagreements()
    if wrong:
        sys.exit("Not ready:\n  " + "\n  ".join(wrong))
    archive, words = build()
    print(f"{archive}  ({archive.stat().st_size / 1e6:.1f} MB)\n{words}\n{tag}: {title}")
    if not args.publish:
        print("Checked and built; nothing published. To publish:  ./release.py --publish")
        return
    # Files git does not know about are not in the zip, so they do not matter here.
    if git("status", "--porcelain", "--untracked-files=no"):
        sys.exit("There is uncommitted work: the zip would not match what is on GitHub.")
    git("fetch", "origin", "main")
    if git("rev-parse", "HEAD") != git("rev-parse", "origin/main"):
        sys.exit("This commit is not what is on GitHub's main branch. Push first.")
    if git("tag", "--list", tag):
        sys.exit(f"{tag} already exists.")
    subprocess.run(["gh", "release", "create", tag, str(archive), "--target", git("rev-parse", "HEAD"),
                    "--title", f"{tag}: {title}", "--notes-file", str(words)], cwd=ROOT, check=True)
    print(f"Published. The zip is at {address}")


if __name__ == "__main__":
    main()
