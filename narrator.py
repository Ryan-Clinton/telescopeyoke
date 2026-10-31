"""TelescopeYoke's voice on the stream: a sentence now and then, said over
the stream's sound, never a running commentary.

It speaks when something happens (the night's events, cache/events.jsonl,
written by director.py: a target reached, a stage begun, a result, a
decision), and otherwise at most every STATUS_S, a line on the mission and
what is still unknown. Never more than one sentence every GAP_S.

Every sentence is a curated template ([voice] in stream-targets.toml) filled
with the measured state: calm, curious, first person, and plain about what
is not known. Nothing is generated. The speech is made by gTTS (as the
house alerts are, alert.py), off the stream's own thread: if it cannot be
made, nothing is said and the pictures never wait.

On by default; [stream] narration = false in config.toml turns it off.
"""
import subprocess
import threading
import time

import numpy as np

STATUS_S = 6 * 60          # a line on the mission at most this often when nothing happens
GAP_S = 20                 # never two sentences closer than this
SPEECH_S = 30              # making one sentence's speech may take this long; after twice it, it is given up
RATE = 22050               # the stream's sound (stream.TONE_RATE)


def templates():
    import streamlook
    return streamlook.targets().get("voice", {})


def _target_words(event):
    import director
    return director.target_words(event.get("target"), "moon" if event.get("target") == "Moon" else None) \
        .replace("THE MOON", "the Moon")


def sentence(event, voice=None):
    """What to say about one event (director.event), or None."""
    voice = templates() if voice is None else voice
    words = event.get("words") or ""
    target = _target_words(event) if event.get("target") else "the target"
    if words.startswith("DECISION: "):
        line = voice.get("decision")
        return line.format(situation=event.get("situation", ""), action=words[10:].lower(),
                           why=event.get("why", "")) if line else None
    for prefix, key in (("MOVING TO ", "moving"), ("CENTRING ", "centring"), ("NOW OBSERVING: ", "observing"),
                        ("TELESCOPEYOKE LIVE", "opening")):
        if words.startswith(prefix):
            line = voice.get(key)
            return line.format(target=target) if line else None
    import director
    phase = next((p for p, w in director.HEADLINES.items() if w == words), None)
    line = voice.get(phase) if phase else None
    return line.format(target=target) if line else None


def status_line(m, voice=None):
    """The quiet-time line on the mission: its goal and its open question."""
    voice = templates() if voice is None else voice
    if not m or not voice.get("status"):
        return None
    line = voice["status"].format(goal=m["goal"][0].lower() + m["goal"][1:].rstrip("."))
    if m.get("question") and voice.get("question"):
        line += " " + voice["question"].format(question=m["question"])
    return line


def speech(words):
    """`words` spoken, as 16-bit samples at RATE, or None if they could not be made."""
    try:
        from io import BytesIO

        from gtts import gTTS
        mp3 = BytesIO()
        try:
            speaker = gTTS(text=words, lang="en", tld="co.uk", timeout=SPEECH_S)
        except TypeError:          # an older gTTS without a timeout: Narrator.say's own limit stands
            speaker = gTTS(text=words, lang="en", tld="co.uk")
        speaker.write_to_fp(mp3)
        pcm = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", "pipe:0", "-f", "s16le", "-ac", "1",
                              "-ar", str(RATE), "pipe:1"], input=mp3.getvalue(), capture_output=True,
                             timeout=60).stdout
    except Exception:              # no network, no gTTS, no ffmpeg: silence
        return None
    return np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32767 if pcm else None


class Narrator:
    """Decides when to speak and hands the sound to `sink` (stream.Tones.add)."""

    def __init__(self, sink, speak=speech, clock=time.time, background=True):
        self.sink, self.speak, self.clock, self.background = sink, speak, clock, background
        now = clock()
        self.seen, self.spoke, self.said_status = now, 0.0, now
        self.busy, self.began = threading.Lock(), 0.0
        self.said = []             # (at, words), for the tests and the log

    def tick(self, mission=None, now=None):
        """Look at what has happened since last time and perhaps say one thing."""
        import director
        now = now or self.clock()
        fresh = director.events(self.seen)
        self.seen = now + 1e-6
        if now - self.spoke < GAP_S:
            return None
        words = next((w for w in (sentence(e) for e in reversed(fresh)) if w), None)
        if words is None and now - self.said_status >= STATUS_S:
            words = status_line(mission)
            if words:
                self.said_status = now
        if words:
            self.say(words, now)
        return words

    def say(self, words, now=None):
        if not self.busy.acquire(blocking=False):
            if (now or self.clock()) - self.began < 2 * SPEECH_S:
                return             # still making the last one: this one is dropped, not queued
            self.busy = threading.Lock()       # the last one stalled: given up, its thread left to end
            self.busy.acquire()
        self.spoke = self.began = now or self.clock()
        busy = self.busy
        self.said.append((self.spoke, words))

        def run():
            try:
                samples = self.speak(words)
                if samples is not None:
                    self.sink(samples)
            finally:
                busy.release()
        if self.background:
            threading.Thread(target=run, daemon=True).start()
        else:
            run()
