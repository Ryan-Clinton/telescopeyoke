[README](../README.md) · [All docs](README.md) · [Validation](validation.md)

# Where TelescopeYoke is listed

Where people looking for astronomy software can find it, what each entry
says, and where it stands. Every entry says only what
[Validation](validation.md) says is proven. Kept up to date as entries are
accepted or turned down.

## Entry pages on the project's site

One page for each kind of reader. Each shows a real output, how to install
it, and how far it is proven:

| Page | For | Proven |
|---|---|---|
| [Home page](https://ryan-clinton.github.io/telescopeyoke/) | anyone | links to the three below near the top |
| [NINA and PHD2 night analysis](https://ryan-clinton.github.io/telescopeyoke/nina-phd2-night-analysis.html) | someone whose nights NINA (or SGP, APT, Ekos) and PHD2 already run | the companion's full report on another observatory's published NINA 3.2 and PHD2 night (read offline); never yet live beside anyone else's observatory |
| [SynScan automation](https://ryan-clinton.github.io/telescopeyoke/synscan-automation.html) | someone with a Sky-Watcher SynScan mount | one EQ3 Pro, through its handset; the Wi-Fi adapter partly, EQDIR untried |
| [ASCOM Alpaca](https://ryan-clinton.github.io/telescopeyoke/ascom-alpaca.html) | someone with ASCOM drivers | ASCOM's own simulator only; no real device |

**All four are published and live** (20 November 2026): each address
above answers, and the home page, the NINA and PHD2 page and the Alpaca
page name the current release. Their sources are in `docs/` (`index.html` and
the three `*.html` pages). Publishing them, and the site's own upkeep (its
sitemap, indexing, Search Console), is done with the rest of the author's
site, not in this repository.

## GitHub

The repository's description names the SynScan observatory and the
read-only companion for NINA and PHD2 nights. Its 20 topics include
`astrophotography`, `synscan`, `skywatcher`, `eq3`, `telescope-mount`,
`plate-solving`, `observatory-automation`, `astronomy-software`, `indi`,
`nina`, `phd2`, `ascom-alpaca`, `autoguiding`, `claude-code` and
`model-context-protocol` (the MCP server is read-only). EQ5, HEQ5 and EQ6
are not topics: nobody has tried them. `python`, `linux` and `windows` are
left out: GitHub shows the language, and the README the systems.

## Directories

| Where | What was sent | Date | State |
|---|---|---|---|
| [Awesome Astrophotography](https://github.com/lunohodov/awesome-astrophotography), a curated list of astrophotography software | The companion, under Software, Other ([pull request 34](https://github.com/lunohodov/awesome-astrophotography/pull/34)) | 20 November 2026 | waiting for the maintainer |
| [INDI's list of clients](https://indilib.org/about/clients.html) | TelescopeYoke as a client of INDI camera drivers (one row; the mount goes through its handset, not INDI) ([pull request 14](https://github.com/indilib/indi-website/pull/14) to indilib/indi-website) | 20 November 2026 | waiting for the maintainers |
| [Astrophysics Source Code Library](https://ascl.net) | Nothing: it lists code used in research that has appeared in, or been submitted to, a peer-reviewed journal, and none from TelescopeYoke has yet | | Possible once a result (a nova, a transit timing, a variable star) is written up and submitted; the code behind that paper could then be listed |

Each entry says the author wrote it, and how far it has been tried.

## Downloads

Release [0.4.2](https://github.com/Ryan-Clinton/telescopeyoke/releases/tag/v0.4.2)
(20 November 2026) is the current download. 0.4.1, the same day, was the
first with the companion, Alpaca and PHD2; 0.4.2 adds the refusal of a
GoTo by name within 40° of the Sun, so every entry above leads to 0.4.2.
