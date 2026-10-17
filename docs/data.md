# What is kept, and what a find needs

[README](../README.md) · Guides: [First night](first-night.md) · [Setup](setup.md) · [Imaging](imaging.md) · [Calibration](calibration.md) · [Focus](focus.md) · Science: [Discovery](discovery.md) · [Validation](validation.md) · [Data](data.md) · Developers: [Contributing](../CONTRIBUTING.md) · [Agents](agents/README.md)

Everything a script keeps is under one folder: the checkout itself for a
real telescope, `rigs/NAME/` for a named rig, `demo/` in the demo. None of
it goes into git. This page says what each part is and which parts have
to be kept for a find to be checked again later, by you or by someone
asked to believe it.

## The folders

| Folder | What is in it |
|---|---|
| `frames/NAME/SESSION/` | One night of one target. `light-*.fits` are the raw frames, every one kept. `session.json` and `frames.json` say how they were taken and how each was judged; `restack.json` (or `discovery.json` for the search's own stack) which went into the stack; `final.fits` the stack; `depth.json` how faint it reaches; `candidates.json` and `difference.fits` what the subtraction found; `vetted.json` the evidence for each candidate; `patrol.json` the patrol's answer; `transit-*.json` and `variables-*.json` brightness measured through the night |
| `reference/NAME/` | Each field's references: `vN.fits` the stack and `vN.json` where it came from. A version is never replaced; a better one is the next number |
| `candidates/NAME.json` | Every candidate a field has had, followed as one object from night to night, with each night's measurement or limit and any dismissal and its reason |
| `reports/ID/` | A candidate's report packet: `report.json`, `report.txt`, `finding.png` |
| `sungrazer/` | The coronagraph pictures fetched (deleted after 3 days), each look's tracks and movies, and `hunt-CAMERA.json`, the newest hunt's finds |
| `calibration/` | Dark and flat frames, by exposure and gain |
| `cache/` | Things fetched or worked out that can be fetched or worked out again (`realbogus.json`, the real-or-bogus model, is made again with `./realbogus.py train`; `agent-log.jsonl`, the decision record of what Claude ran, is not: keep it if it matters): catalogue stars, ZTF images, public alerts, the skyline, the mount's remembered measurements |
| `mosaics/`, `landmarks/`, `web/` | Mosaic panels, remembered landmarks, the status page |

## Which code made it

Every scientific record carries `provenance`: the telescopeyoke version,
the git commit, whether there were changes not committed (if so, the commit
alone does not say what ran), the schema version, the Python and the
numpy, scipy and astropy versions, when it was made, and a fingerprint of
the settings with the site and the Telegram bot left out
(`schemas/provenance.schema.json`). Each night in a candidate's history
says the same in short, as `code`: `0.2.1+6bb014d`.

So to know what found a candidate, read the `provenance` of the session's
`candidates.json` and `vetted.json`, and `git checkout` that commit to run
the same code again.

## To reproduce a find, keep

1. The session's whole folder under `frames/`: the raw frames above all.
   Every stack, measurement and candidate can be made again from them; none
   of them can make the frames.
2. The reference version it was found against (`reference/NAME/vN.*`):
   the candidate's record names it.
3. The field's candidate book (`candidates/NAME.json`) and the report
   packet (`reports/ID/`).
4. The calibration frames that night used, if any.
5. Earlier sessions of the same field: they hold the last night it was not
   there, which a report needs.

`cache/` need not be kept: it is fetched again. A record is only ever
replaced whole (`records.py`): a crash leaves the old one, and one that
does not match its schema is set aside as `NAME.rejected.json` instead of
written.
