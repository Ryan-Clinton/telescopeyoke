---
name: report-comet
description: Prepare a report of a comet found by the comet hunt to the Sungrazer Project, filling their form for the person to send. Only when the person types /report-comet N.
disable-model-invocation: true
argument-hint: TRACK-NUMBER
compatibility: Claude Code with Claude in Chrome; without a browser tool it gives the form's fields as a list to paste
allowed-tools: Bash(./ty candidates *)
---

# Report comet $ARGUMENTS

The procedure is `docs/agents/claiming.md`, "report comet N": read it now.
**You never press send.** The person does.

1. The track: candidate $ARGUMENTS in the newest `sungrazer/hunt-*.json`
   (`./ty candidates` lists them as `comets`): its camera, the pictures'
   times, its x and y in each, and its movie.
2. `comet-checker` with that track in its prompt. If it says "already
   found", stop and say which comet and who found it.
3. Open the Sungrazer Project's report form in the browser
   (sungrazer.nrl.navy.mil). **Ask the person in this session before
   typing their name or email**: it is their personal data. Fill the
   camera, the pictures' times and the positions from the track.
4. Stop before the send button and ask them to press it.
5. With no browser tool: the fields and values as a list to paste.
