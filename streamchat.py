"""Answers in the Twitch chat to a few commands, so a curious viewer can ask
without the picture filling up (docs/stream-look.md, "Chat").

    !what  !target  !next  !telescope  !camera  !nova  !transit  !help

The answers are the same curated words and measured figures the picture
uses (stream-targets.toml, the status page's status.json): nothing is
generated, and no command moves or changes anything. It runs inside
`stream.py watch` while the stream is on air, and only once the laptop has
been signed in with the chat permissions (`./stream.py twitch-login`, which
asks for chat:read and chat:edit as well). It answers at most once every
GAP_S, and each command at most once every COOLDOWN_S, so it never floods
the chat. A failure is said once and it tries again later; it never stops
the stream.
"""
import socket
import ssl
import time

HOST, PORT = "irc.chat.twitch.tv", 6697
GAP_S, COOLDOWN_S = 3, 30
CHAT_SCOPES = {"chat:read", "chat:edit"}


def answer(command, st, now=None):
    """The reply to `!command`, from what is running now; None for one it does not know."""
    import streamlook
    import streamstory
    now = now or time.time()
    found = streamlook.targets()
    s = streamlook.from_status(st, now) if st.get("name") else {"kind": None, "target": None}
    entry = found.get("targets", {}).get(s.get("target"), {})
    stories = found.get("stories", {})
    if command == "help":
        return "Ask: !what !target !next !telescope !camera !nova !transit"
    if command == "what":
        if not s.get("kind"):
            return "The telescope is not imaging just now."
        if s["kind"] == "transit":
            return (f"Timing a transit of the exoplanet {s['transit']['planet']}: the star dims by about "
                    f"{100 * s['transit']['depth']:.1f}% as the planet crosses it.")
        if s["kind"] == "patrol":
            return f"A nova patrol of {s['target']}: tonight's picture is compared with an earlier one to find new stars."
        return f"Imaging {s['target']}: every exposure is added to the stack shown."
    if command == "target":
        if not s.get("target"):
            return "No target just now."
        parts = [s["target"] + (f" ({entry['common']})" if entry.get("common") else ""), entry.get("words"),
                 entry.get("distance")]
        return ": ".join(p for p in parts[:2] if p) + (f" About {parts[2].lstrip('~')} away." if parts[2] else "")
    if command == "next":
        nxt = streamstory.coming_up((st.get("schedule") or {}).get("steps") or [], now, found)
        return f"{nxt[0].title()}: {nxt[1][0]}" if nxt else "Nothing more is planned tonight."
    if command == "telescope":
        return " ".join(stories.get("telescope", [])[:2]) or None
    if command == "camera":
        return " ".join(stories.get("telescope", [])[1:3]) or None
    if command == "nova":
        return (found.get("programmes", {}).get("patrol", {}).get("explainers") or [None])[0]
    if command == "transit":
        return (found.get("programmes", {}).get("transit", {}).get("explainers") or [None])[0]
    return None


class Limiter:
    """At most one reply each GAP_S, and each command at most once each COOLDOWN_S."""

    def __init__(self):
        self.last, self.each = 0.0, {}

    def allow(self, command, now):
        if now - self.last < GAP_S or now - self.each.get(command, -1e9) < COOLDOWN_S:
            return False
        self.last, self.each[command] = now, now
        return True


def command_of(line, channel):
    """'what' from a chat line `... PRIVMSG #channel :!what`, else None."""
    marker = f" PRIVMSG #{channel} :!"
    if marker not in line:
        return None
    word = line.split(marker, 1)[1].strip().split(" ")[0].lower()
    return word if word.isalpha() and len(word) <= 12 else None


def run(status, tokens, say=print, stop=None, connect=None, clock=time.time):
    """Stay in the channel's chat and answer, until `stop` is set; reconnect
    after a failure, waiting longer each time (at most 5 minutes)."""
    import twitch
    wait = 10
    while stop is None or not stop.is_set():
        try:
            conn = connect() if connect else ssl.create_default_context().wrap_socket(
                socket.create_connection((HOST, PORT), timeout=30), server_hostname=HOST)
            channel = tokens["login"]
            conn.sendall(f"PASS oauth:{tokens['access_token']}\r\nNICK {channel}\r\nJOIN #{channel}\r\n".encode())
            limiter, buffer = Limiter(), ""
            conn.settimeout(60)
            while stop is None or not stop.is_set():
                try:
                    data = conn.recv(4096).decode(errors="replace")
                except socket.timeout:
                    conn.sendall(b"PING :tmi.twitch.tv\r\n")
                    continue
                if not data:
                    break
                buffer += data
                *lines, buffer = buffer.split("\r\n")
                for line in lines:
                    if line.startswith("PING"):
                        conn.sendall(line.replace("PING", "PONG", 1).encode() + b"\r\n")
                    elif "Login authentication failed" in line:
                        raise PermissionError("the chat sign-in was refused")
                    word = command_of(line, channel)
                    if word and limiter.allow(word, clock()):
                        reply = answer(word, status())
                        if reply:
                            conn.sendall(f"PRIVMSG #{channel} :{reply[:450]}\r\n".encode())
                wait = 10
            conn.close()
        except PermissionError:
            fresh = twitch.refreshed()
            if fresh is None:
                say("The chat's sign-in has lapsed: ./stream.py twitch-login")
                return
            tokens = fresh
        except (OSError, ssl.SSLError) as error:
            say(f"The chat dropped ({twitch.redacted(error, tokens)}); trying again in {wait} s")
        if stop is not None and stop.wait(wait):
            return
        if stop is None:
            time.sleep(wait)
        wait = min(wait * 2, 300)
