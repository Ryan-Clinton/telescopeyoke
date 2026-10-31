"""Answers in the Twitch chat to a few commands, so a curious viewer can ask
without the picture filling up (docs/stream-look.md, "Chat").

    !what  !target  !next  !focus  !polar  !telescope  !camera  !nova  !transit  !help
    !why  !progress  !result  !moon  !candidate  !vote TOPIC

The answers are the same curated words and measured figures the picture
uses (stream-targets.toml, the status page's status.json): nothing is
generated, and no command moves or changes anything. `!vote` chooses what
the stream explains next (VOTE_TOPICS), or says which of tonight's planned
targets the chat would like next: that is told to the person, who decides
every move; a vote never moves the telescope. It runs inside
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
VOTE_S = 15 * 60          # a vote counts this long
# What `!vote` can choose for the next HOW IT WORKS card: the [stories] pools.
VOTE_TOPICS = {"stacking": "stacking", "focus": "focus", "polar": "polar", "telescope": "telescope",
               "discovery": "discovery", "solving": "plate_solving"}


def answer(command, st, now=None):
    """The reply to `!command`, from what is running now; None for one it does not know."""
    import streamlook
    import streamstory
    now = now or time.time()
    found = streamlook.targets()
    s = streamlook.from_status(st, now) if st.get("name") or st.get("director") else {"kind": None, "target": None}
    entry = found.get("targets", {}).get(s.get("target"), {})
    stories = found.get("stories", {})
    if command == "help":
        return ("Ask: !what !why !progress !result !target !next !moon !candidate !focus !polar !telescope "
                "!camera !nova !transit · !vote " + "|".join(VOTE_TOPICS) + " to choose what is explained next")
    if command in ("why", "progress", "result", "candidate"):
        m = s.get("mission")
        if command == "candidate":
            k = s.get("candidate")
            if not k:
                return "Nothing unusual is being investigated just now."
            label, why = streamlook_confidence(k)
            return f"A possible change is being checked ({label.lower()}): {why} Its position stays private until it is checked."
        if not m:
            return "No mission just now: the telescope is not observing."
        if command == "why":
            return f"Mission: {m['goal']}" + (f" Still open: {m['question']}" if m.get("question") else "")
        if command == "progress":
            done = sum(st == "done" for _, st in m["steps"])
            now_step = next((label for label, st in m["steps"] if st == "now"), None)
            return (f"{m['title'].title()}: " + (f"step {done + 1} of {len(m['steps'])}, {now_step.lower()}." if now_step
                                                   else f"{done} of {len(m['steps'])} steps done." if m["steps"]
                                                   else "under way.")
                    + (f" Next: {m['next'].lower()}." if m.get("next") else ""))
        if m.get("result"):
            label = m.get("confidence")
            return f"Tonight's result: {m['result']}" + (f" Confidence: {label[0].lower()}. {label[1]}" if label else "")
        return "No result yet tonight: the measurement is still going on."
    if command == "moon":
        moon = streamlook.moon_now(now)
        notices = streamstory.moon_notices(found.get("targets", {}).get("Moon", {}), moon)
        line = streamstory.moon_line(moon)
        return " ".join(x for x in [line, notices[0] if notices else None] if x) or None
    if command == "focus":
        return focus_answer(streamlook.focus_stream_state(now), now)
    if command == "polar":
        return polar_answer(streamlook.polar_stream_state(now), now)
    if command == "what":
        f, p = streamlook.focus_stream_state(now), streamlook.polar_stream_state(now)
        if f and f["running"]:
            return "Focusing the telescope with its motor focuser: !focus says how it is going."
        if p and (p["running"] or p["adjusting"]):
            return "Polar aligning the mount, so it follows the stars: !polar says how far it has got."
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
        wanted = tally(now, "target")
        return (f"{nxt[0].title()}: {nxt[1][0]}" if nxt else "Nothing more is planned tonight.") + (
            f" The chat would like {wanted[0][0]} next ({wanted[0][1]} votes); a person decides." if wanted else "")
    if command == "telescope":
        return " ".join(stories.get("telescope", [])[:2]) or None
    if command == "camera":
        return " ".join(stories.get("telescope", [])[1:3]) or None
    if command == "nova":
        return (found.get("programmes", {}).get("patrol", {}).get("explainers") or [None])[0]
    if command == "transit":
        return (found.get("programmes", {}).get("transit", {}).get("explainers") or [None])[0]
    return None


def streamlook_confidence(k):
    import mission
    return mission.confidence(None, candidate=k)


def votes_file():
    import config
    return config.DATA / "cache" / "votes.json"


def vote(user, choice, now=None, targets=()):
    """`user`'s vote for `choice` (a VOTE_TOPICS topic, or one of tonight's
    planned `targets`), replacing any earlier one; the reply, or None for a
    choice that is neither. Never moves anything."""
    import json

    import records
    now = now or time.time()
    choice = (choice or "").strip().lower()
    known = {t.lower(): t for t in targets}
    if choice not in VOTE_TOPICS and choice not in known:
        return None
    try:
        kept = json.loads(votes_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        kept = {}
    kept = {u: v for u, v in kept.items() if now - v.get("at", 0) <= VOTE_S}
    kept[user] = {"choice": known.get(choice, choice), "kind": "target" if choice in known else "topic", "at": now}
    try:
        records.write(votes_file(), kept)
    except OSError:
        pass
    if choice in known:
        return f"Noted: {known[choice]} next. The chat's choice is passed on; a person decides every move."
    return f"Noted: {choice} is explained next if it wins the vote."


def tally(now=None, kind="topic"):
    """[(choice, votes)] most first, of the votes of `kind` still counting."""
    import json
    now = now or time.time()
    try:
        kept = json.loads(votes_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    counts = {}
    for v in kept.values():
        if isinstance(v, dict) and v.get("kind") == kind and now - v.get("at", 0) <= VOTE_S:
            counts[v["choice"]] = counts.get(v["choice"], 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


def user_of(line):
    """The chatter's name from an IRC line ':name!name@... PRIVMSG ...'."""
    return line[1:].split("!", 1)[0].lower() if line.startswith(":") and "!" in line else None


def argument_of(line, channel):
    """The word after the command in a chat line, or None."""
    marker = f" PRIVMSG #{channel} :!"
    words = line.split(marker, 1)[1].split() if marker in line else []
    return words[1] if len(words) > 1 else None


TONIGHT_S = 12 * 3600      # a run further back than this is not tonight's


def clock_words(t):
    return time.strftime("%H:%M UTC", time.gmtime(t))


def focus_answer(f, now):
    """!focus: what the focus run is doing now, or how the last one tonight
    ended, from focus.py's own file (streamlook.focus_stream_state)."""
    if not f or now - (f.get("ended") or f.get("started") or 0) > TONIGHT_S:
        return "No focus run tonight yet."
    usual = f" The usual best is {f['usual_hfr']:.2f}." if f.get("usual_hfr") else ""
    if f.get("running"):
        where = f" ({f['stage']}" + (f", {f['position']} of {f['positions']}" if f.get("positions") else "") + ")"
        figures = (f" Star size (HFR) now {f['hfr']:.2f}, best so far {f['best_hfr']:.2f}, "
                   f"{f['start_hfr']:.2f} at the start." if f.get("hfr") and f.get("best_hfr") and f.get("start_hfr")
                   else " The first reading is being taken.")
        return f"Focusing now{where}.{figures}{usual}"
    if f.get("ended"):
        import streamlook
        title, line, _ = streamlook.focus_card(f)
        return f"The last focus run ended at {clock_words(f['ended'])}: {title.lower()}, {line}".rstrip(", ")
    return "No focus run is going just now." + usual


def polar_answer(p, now):
    """!polar: where tonight's polar alignment has got, from polaralign.py's
    own file (streamlook.polar_stream_state)."""
    rounds = (p or {}).get("rounds") or []
    if not p or (not rounds and p.get("stage") != "measuring"):
        return "No polar alignment tonight yet."
    if p["stage"] == "measuring" and p.get("running"):
        doing = f"Measuring the polar axis now: picture {p.get('picture') or 1} of 3."
    elif p["stage"] == "adjust":
        doing = "Waiting for the mount to be adjusted, then it measures again."
    elif p["stage"] == "complete":
        doing = "Polar alignment is done for tonight."
    elif p["stage"] == "failed":
        doing = f"The last measurement failed: {p.get('words') or 'nothing was measured'}"
    else:
        doing = "Not measuring just now."
    if not rounds:
        return doing
    last = rounds[-1]["total_deg"]
    told = f" The axis is {last:.1f}° from the pole"
    if len(rounds) > 1:
        told += f" after {len(rounds)} rounds (it began at {rounds[0]['total_deg']:.1f}°)"
    told += "."
    if p.get("limit_deg"):
        told += f" Target: under {p['limit_deg']:.2f}° on each axis, where the drift stays under a star's own size."
    return doing + told


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
                    if word == "vote":
                        planned = [x.get("label", "").split(",")[0] for x in
                                   ((status().get("schedule") or {}).get("steps") or []) if x.get("status") == "queued"]
                        reply = vote(user_of(line) or "?", argument_of(line, channel), clock(), planned)
                        if reply and limiter.allow(f"vote-{user_of(line)}", clock()):
                            conn.sendall(f"PRIVMSG #{channel} :{reply[:450]}\r\n".encode())
                    elif word and limiter.allow(word, clock()):
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
