---
name: report-comet
description: Report a comet found by the comet hunt to the Sungrazer Project and send it. Use when the person says to report it, send it or submit it ("send it", "report comet 1", /report-comet N) after the hunt or comet-checker has found an unexplained track.
argument-hint: TRACK-NUMBER
compatibility: Claude Code with Claude in Chrome; without a browser tool it gives the form's fields as a list to paste
allowed-tools: Bash(./ty candidates *)
---

# Report comet $ARGUMENTS

The procedure is `docs/agents/claiming.md`, "report comet N": read it now.
The person saying to send or report it is the go: fill the form and press
send yourself, at once. The first report is the one credited.

1. The track: candidate $ARGUMENTS (1 if only one) in the newest
   `sungrazer/hunt-*.json` (`./ty candidates` lists them as `comets`): its
   camera, the pictures' times, its `sungrazer_xy` in each, and its movie.
2. Check it against the project's reports and the Cambridge list, unless
   that was done in this session already. If it is already found, don't
   send: say which comet and who found it.
3. Open the Sungrazer Project's report form in the browser
   (`https://sungrazer.nrl.navy.mil/report`). The reporter's name and email
   are `[reporter]` in the site settings, read with `python3 -c "import
   tomllib; print(tomllib.load(open('config.toml','rb'))['reporter'])"`
   (the guard refuses reading the whole file). Fill the camera, the pictures' times and the positions
   from the track.
4. Press send. Say what went, with the report's ID if the page gives one,
   and add it to the night's notes.
5. With no browser tool: the fields and values as a list to paste.
