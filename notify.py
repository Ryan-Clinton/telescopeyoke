#!/usr/bin/env python3
"""Tell the person at once: a message, with pictures, to their phone by a
Telegram bot.

    ./notify.py --test               a test message, to see the bot is set up
    ./notify.py "the text"           any message
    ./notify.py "the text" --file F  with F attached at full size

The bot is the person's own: made with Telegram's @BotFather, which gives
its token, and the chat is theirs (the number @userinfobot gives, or the
chat id in the bot's getUpdates once they have written to it). Both go in
config.toml, which git ignores:

    [telegram]
    token = "123456:ABC..."
    chat = "123456789"

or in TY_TELEGRAM_TOKEN and TY_TELEGRAM_CHAT. Without them nothing is sent
and the callers carry on: an alert is a help, never a step anything waits
on. Nothing is sent from the tests or the demo.

What is sent: the patrol's unexplained candidates once vetted (with the
night, the reference and the difference side by side, and the report
packet), and the comet hunt's tracks heading in towards the Sun (with
the movie). Sending a report anywhere else stays a person's decision.
"""
import argparse
import os
import sys
import time
from pathlib import Path

import requests

import config
import interface

API = "https://api.telegram.org/bot{token}/{method}"
LONGEST = 4000          # characters in one message (Telegram's limit is 4096)
TIMEOUT = 30
BUSY_WAIT = 60          # seconds at most waited when Telegram says too many were sent at once (429)
BUSY_TRIES = 3          # times a message is tried while Telegram says that


def settings():
    """(token, chat), or (None, None) when the bot is not set up."""
    token, chat = os.environ.get("TY_TELEGRAM_TOKEN"), os.environ.get("TY_TELEGRAM_CHAT")
    if not (token and chat) and config.FILE.exists():
        t = config._read(config.FILE).get("telegram", {})
        token, chat = token or t.get("token"), chat or t.get("chat")
    return (str(token), str(chat)) if token and chat else (None, None)


def quiet():
    """Whether sending is off here: the demo, or a test."""
    return config.DEMO or "PYTEST_CURRENT_TEST" in os.environ


def patiently(attempt, sleep=time.sleep):
    """The reply to `attempt()`, tried again after the wait Telegram asks
    for while it says too many were sent at once: on 26 October 2026 a hunt
    sent eleven movies in a row and the checked answer after them was cut off."""
    for _ in range(BUSY_TRIES - 1):
        reply = attempt()
        if getattr(reply, "status_code", 200) != 429:
            return reply
        try:
            wait = float(reply.json()["parameters"]["retry_after"])
        except (ValueError, KeyError, TypeError):
            wait = 5.0
        sleep(min(wait + 1, BUSY_WAIT))
    return attempt()


def send(text, pictures=(), animations=(), post=requests.post, say=print, sleep=time.sleep, documents=()):
    """Send the text, then each picture, animation and document (path,
    caption). A picture is shrunk by Telegram (2560 pixels at most); a
    document arrives as the file itself, full size (50 MB at most).
    Returns how many went; never raises, as no caller waits on it."""
    token, chat = settings()
    if not token or quiet():
        return 0
    sent = 0
    try:
        for part in [text[i:i + LONGEST] for i in range(0, len(text), LONGEST)] or [""]:
            reply = patiently(lambda: post(API.format(token=token, method="sendMessage"), timeout=TIMEOUT,
                                           data={"chat_id": chat, "text": part, "disable_web_page_preview": "true"}),
                              sleep)
            reply.raise_for_status()
            sent += 1
        for method, field, items in (("sendPhoto", "photo", pictures), ("sendAnimation", "animation", animations),
                                     ("sendDocument", "document", documents)):
            for path, caption in items:
                if not Path(path).exists():
                    continue

                def attempt():
                    with open(path, "rb") as f:
                        return post(API.format(token=token, method=method), timeout=TIMEOUT * 2,
                                    data={"chat_id": chat, "caption": caption[:1000]}, files={field: f})
                reply = patiently(attempt, sleep)
                reply.raise_for_status()
                sent += 1
    except requests.RequestException as error:
        say(f"  the alert was not sent ({error.__class__.__name__}); carrying on")
    keep(text, list(pictures) + list(documents), animations, sent)
    return sent


def stack_ready(what, picture, say=print, post=requests.post, full=None):
    """A finished stack's picture to the person's phone (30 October 2026:
    "whenever the stacks finish send me the pics on Telegram"), to look at,
    then the same file as an attachment at full resolution ("full res image
    as an attachment please"), as Telegram shrinks a picture: `full`, the
    picture at the stack's own size, when `picture` is a smaller copy.
    Returns how many messages went; never raises."""
    return send(f"Stack finished: {what}", pictures=[(picture, what)], documents=[(full or picture, f"{what} (full size)")],
                post=post, say=say)


SENT_LOG = config.DATA / "cache" / "sent.jsonl"


def keep(text, pictures, animations, sent):
    """A copy of every message for the phone, sent or not, kept on the laptop:
    an agent watching the night reads the alerts as they go (20 October
    2026: candidate alerts reached the phone with nothing on the laptop
    saying so). Never raises."""
    import json
    import time
    try:
        SENT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(SENT_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"time": time.time(), "sent": sent, "text": text,
                                "pictures": [str(path) for path, _ in pictures],
                                "animations": [str(path) for path, _ in animations]}) + "\n")
    except Exception:
        pass


def candidate_alert(name, session, vetted, followed, pictures, reports):
    """The text for the patrol's unexplained candidates, one paragraph each."""
    lines = [f"{name}: {len(vetted)} unexplained candidate{'s' if len(vetted) != 1 else ''} in {Path(session).name}"]
    for n, c in enumerate(vetted, 1):
        book = next((f for f in followed if abs(f["ra"] - c["ra"]) < 1e-3 and abs(f["dec"] - c["dec"]) < 1e-3), None)
        lines.append(f"\n{n}. {book['id'] if book else ''} RA {c['ra']:.5f} Dec {c['dec']:+.5f}, "
                     f"G {c.get('mag') or 0:.2f}, {c['score']:.1f} sigma, halves {c.get('halves')}")
        if book:
            lines.append(f"   seen on {book['seen_on']} of {book['of']} nights")
        for clue in c.get("clues", []):
            lines.append(f"   clue: {clue}")
    if reports:
        lines.append("\nReport packets: " + ", ".join(reports))
    lines.append("\nLook at the pictures. To claim one, tell Claude \"claim ID\": it fills the TNS form and you "
                 "press send.")
    return "\n".join(lines)


def run(args, say=print):
    token, _ = settings()
    if not token:
        raise interface.Refusal("INVALID_REQUEST", "No Telegram bot set up: put [telegram] token and chat in "
                                                   "config.toml (see ./notify.py --help).")
    text = "telescopeyoke: the alerts reach you." if args.test else " ".join(args.text)
    pictures = [(path, " ".join(args.text)[:200]) for path in getattr(args, "picture", None) or []]
    documents = [(path, " ".join(args.text)[:200]) for path in getattr(args, "file", None) or []]
    sent = send(text, pictures=pictures, documents=documents, say=say)
    if not sent:
        raise interface.Refusal("INVALID_REQUEST", "Telegram did not take the message: check the token and chat.")
    say("sent")
    return {"sent": sent}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("text", nargs="*", help="the message")
    ap.add_argument("--test", action="store_true", help="a test message")
    ap.add_argument("--picture", action="append", metavar="FILE", help="a picture to send after the message")
    ap.add_argument("--file", action="append", metavar="FILE",
                    help="a file to send as an attachment, untouched (a picture at full size)")
    ap.add_argument("--json", action="store_true", help="answer in JSON")
    args = ap.parse_args()
    if not args.test and not args.text:
        ap.error("give a message, or --test")
    interface.main("notify", lambda: run(args), args.json)


if __name__ == "__main__":
    sys.exit(main())
