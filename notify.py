#!/usr/bin/env python3
"""Tell the person at once: a message, with pictures, to their phone by a
Telegram bot.

    ./notify.py --test               a test message, to see the bot is set up
    ./notify.py "the text"           any message

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
from pathlib import Path

import requests

import config
import interface

API = "https://api.telegram.org/bot{token}/{method}"
LONGEST = 4000          # characters in one message (Telegram's limit is 4096)
TIMEOUT = 30


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


def send(text, pictures=(), animations=(), post=requests.post, say=print):
    """Send the text, then each picture and animation (path, caption).
    Returns how many went; never raises, as no caller waits on it."""
    token, chat = settings()
    if not token or quiet():
        return 0
    sent = 0
    try:
        for part in [text[i:i + LONGEST] for i in range(0, len(text), LONGEST)] or [""]:
            reply = post(API.format(token=token, method="sendMessage"), timeout=TIMEOUT,
                         data={"chat_id": chat, "text": part, "disable_web_page_preview": "true"})
            reply.raise_for_status()
            sent += 1
        for method, field, items in (("sendPhoto", "photo", pictures), ("sendAnimation", "animation", animations)):
            for path, caption in items:
                if not Path(path).exists():
                    continue
                with open(path, "rb") as f:
                    reply = post(API.format(token=token, method=method), timeout=TIMEOUT * 2,
                                 data={"chat_id": chat, "caption": caption[:1000]}, files={field: f})
                reply.raise_for_status()
                sent += 1
    except requests.RequestException as error:
        say(f"  the alert was not sent ({error.__class__.__name__}); carrying on")
    return sent


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
    sent = send(text, say=say)
    if not sent:
        raise interface.Refusal("INVALID_REQUEST", "Telegram did not take the message: check the token and chat.")
    say("sent")
    return {"sent": sent}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("text", nargs="*", help="the message")
    ap.add_argument("--test", action="store_true", help="a test message")
    ap.add_argument("--json", action="store_true", help="answer in JSON")
    args = ap.parse_args()
    if not args.test and not args.text:
        ap.error("give a message, or --test")
    interface.main("notify", lambda: run(args), args.json)


if __name__ == "__main__":
    sys.exit(main())
