---
name: release
description: Prepare a telescopeyoke release, checking everything agrees and building the zip, and stop before publishing. Only when the person types /release.
disable-model-invocation: true
compatibility: a telescopeyoke checkout with git and the gh command
allowed-tools: Bash(git status) Bash(git log *)
---

# Release

AGENTS.md, "Conventions": the version is in `pyproject.toml` and
`agent.VERSION`; each release has a section in `CHANGELOG.md`; the
download links in the README and on the home page name the release's zip.

1. `git status`: nothing uncommitted, on `main`, pushed.
2. The last CI run on this commit passed (`gh run list --limit 1`). If
   not, stop and say why.
3. The version: ask the person what it is to be, if they have not said.
   Change `pyproject.toml`, `agent.VERSION`, the changelog's "Not yet
   released" to the version and date, and the links.
4. `./release.py`: it builds the zip and the notes and checks that all of
   these agree. Fix what it says disagrees and run it again.
5. Commit and push the version change.
6. Stop. Say: "Ready: `./release.py --publish` tags this commit and
   publishes it on GitHub." **Only a person runs `--publish`**: it is
   public at once and stays.
