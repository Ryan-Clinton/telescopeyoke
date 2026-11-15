---
name: release
description: Prepare a telescopeyoke release, checking everything agrees and building the zip, and publish it when the person says to. Only when the person types /release.
disable-model-invocation: true
compatibility: a telescopeyoke checkout with git and the gh command
allowed-tools: Bash(git status) Bash(git log *)
---

# Release

AGENTS.md, "Conventions": the version is in `pyproject.toml` and
`agent.VERSION`; each release has a section in `CHANGELOG.md`; the
download links in the README and on the home page name the release's zip.

1. `git status`: nothing uncommitted, on `main`, pushed.
2. The version: ask the person what it is to be, if they have not said.
   Change `pyproject.toml`, `agent.VERSION`, the changelog's "Not yet
   released" to the version and date, and the links.
3. `./release.py`: it builds the zip and the notes and checks that all of
   these agree. Fix what it says disagrees and run it again.
4. Commit and push the version change.
5. If the person has said to publish: `./release.py --publish`, which tags
   this commit and publishes it on GitHub. Otherwise say it is ready.
