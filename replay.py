#!/usr/bin/env python3
"""Turn a recorded GoTo-and-centre run into an animated GIF.

    ./mount.py goto M27 --solve --record recordings/m27
    ./replay.py recordings/m27 docs/goto-solve.gif

Each step of the run becomes a frame: the photograph the telescope had just
taken, with the messages so far underneath, as they appeared.
"""
import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

WIDTH, PICTURE, LINES = 720, 480, 6
BACKGROUND, TEXT, DIM = (11, 13, 18), (215, 220, 230), (138, 147, 166)


def build(folder, command=None):
    """List of PIL frames for the recording in `folder`."""
    folder = Path(folder)
    steps = json.loads((folder / "steps.json").read_text())
    if not steps:
        raise SystemExit("The recording is empty.")
    font = ImageFont.load_default(size=19)
    line_height = 27
    height = PICTURE + 16 + line_height * LINES + 12
    shown = [f"$ {command}"] if command else []
    frames = []
    for step in steps:
        shown.append(step["text"])
        frame = Image.new("RGB", (WIDTH, height), BACKGROUND)
        picture = folder / f"frame-{step['frame']:02d}.jpg"
        if step["frame"] and picture.exists():
            photo = Image.open(picture).convert("RGB")
            photo.thumbnail((WIDTH, PICTURE))
            frame.paste(photo, ((WIDTH - photo.width) // 2, (PICTURE - photo.height) // 2))
        else:
            ImageDraw.Draw(frame).text((WIDTH // 2 - 60, PICTURE // 2 - 10), "slewing…",
                                       fill=DIM, font=font)
        draw = ImageDraw.Draw(frame)
        for i, line in enumerate(shown[-LINES:]):
            newest = i == len(shown[-LINES:]) - 1
            draw.text((14, PICTURE + 16 + i * line_height), line[:70],
                      fill=TEXT if newest else DIM, font=font)
        frames.append(frame)
    return frames


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("folder", help="recording made with mount.py --record")
    ap.add_argument("output", help="GIF to write")
    ap.add_argument("--command", help="command line to show as the first line")
    ap.add_argument("--seconds", type=float, default=1.6, help="time on each step")
    args = ap.parse_args()

    frames = build(args.folder, args.command)
    durations = [int(args.seconds * 1000)] * len(frames)
    durations[-1] = 4000   # linger on the result
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(args.output, save_all=True, append_images=frames[1:],
                   duration=durations, loop=0, optimize=True)
    print(f"{len(frames)} steps -> {args.output}")


if __name__ == "__main__":
    main()
