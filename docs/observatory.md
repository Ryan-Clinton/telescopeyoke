# The TelescopeYoke observatory

[README](../README.md) · [Validation](validation.md) · [Discovery](discovery.md) · [Streaming](streaming.md) · [Alerts](alerts.md) · [Agents](agents/README.md)

What TelescopeYoke is as a whole, on one page. The README's sections and
the other pages go into each part; [validation.md](validation.md) says how
far each is proven, and its figures win over anything here.

It began on 3 October 2026 as scripts to point a Sky-Watcher 150P on an EQ3
Pro. It is now a small observatory: it plans and runs nights, measures and
corrects its own hardware's faults, searches its pictures and public data
for new objects, tells its person what matters and how urgently, and
explains itself live. An AI agent (Claude) operates it beside a person,
inside deterministic limits.

```
                              THE PERSON
                     at the telescope, indoors, or asleep
                                  │
       console and status page · phone (Telegram) · house lights and speaker
                                  │
                                  ▼
                   AI AGENT (Claude), with specialist agents
          reads state, plans, investigates, proposes; asks before each move
                                  │
                ┌─────────────────┴─────────────────┐
                ▼                                   ▼
       OBSERVATORY CONTROL                       SCIENCE
  schedule · GoTo and centring           subtraction · candidates · vetting
  focus · tracking · hold · park         comets · transits · variables
  motion lock · limits · checks          depth · provenance · reports
                │                                   │
                └─────────────────┬─────────────────┘
                                  ▼
                            MEASUREMENTS
       pointing · polar error · drift · focus · shutter · depth · noise
                                  │
          ┌───────────────────────┼────────────────────────┐
          ▼                       ▼                        ▼
     status page            Telegram, lights,         live broadcast
     and console             speaker (alerts)      Twitch: presenter, chat
```

## Six things it does

**Observe.** `schedule.py` runs a night's agreed steps in order, with times
not to start before, waits for steps already running, fills gaps with more
of the last field, stops and fetches the person when a step fails, and at
the end parks the mount and says so. `mount.py` drives the SynScan handset,
centres every GoTo by plate solving, and keeps inside the mount's limits;
`shoot.py` images, checks each frame, re-centres, and for transits holds
the target on the same pixels (`--hold`).

**Measure.** The hardware is not assumed right: the pointing error on each
side of the meridian, the polar error, where home really is, the drift and
the motor's answer to it, focus and the focuser's slack, the camera's real
shutter time, its stripes, how deep each picture goes (planted fake stars),
and how precise its photometry is (`precision.py`). `./ty characterise`
lists what has been measured and what has not.

**Discover.** The nova patrol of M31 and M33 subtracts a reference, vets
every candidate against catalogues, asteroids and a classifier trained on
the rig's own pictures, takes a second look, and follows candidates from
night to night. The comet hunt searches GOES-19 CCOR-1 pictures every six
hours. Public survey alerts are searched for what this rig could confirm
first; old pictures are searched again as methods improve; variable stars,
Tabby's star and exoplanet transits are measured. [discovery.md](discovery.md)
has each programme and how far it is proven.

**Operate.** Cloud, rain and a stopped run are noticed from the frames and
the forecast. What needs the person goes to them by the right channel: the
status page for ordinary state; Telegram with the evidence for a candidate,
a comet and its verdict, or the end of the night; and for hands now, every
light in the house, a spoken sentence and a phone message
([alerts.md](alerts.md)). Every message to the phone is also kept for the
agent to read.

**Reason.** Every command answers in a fixed JSON envelope with a schema;
`ty` is one front door, and a read-only web API and MCP server give the same
facts to other programs. Fourteen skills hold the routines (setup, focus,
polar alignment, a discovery night, a claim, a comet report) and eight
specialist agents do focused jobs: vetting a candidate, researching a place
in catalogues, checking a comet track, reviewing a change that moves the
mount, analysing a night. Every action an agent takes is logged.

**Share.** The status page and a public live page with the place left out;
a 1080p live broadcast on Twitch with a presenter that explains what the
telescope is doing and why, and chat commands that let viewers ask but not
operate ([streaming.md](streaming.md)); a night-by-night diary.

## The rule it is built on

**AI proposes; deterministic code decides what is safe; a person authorises
movement.** The agent can read everything, investigate and plan. What may
move is decided by code that does not depend on the agent behaving: the Sun
limit, altitude and hour-angle limits, the motion lock (a file whose
presence stops every move), the handset's state checked before each move,
moves checked against what the camera saw, dry runs that move nothing, and
hooks that refuse an agent's attempt to work round any of them. The MCP
server and the web API are read-only. A person asks for each move. Two
kinds of move happen without a fresh ask, both inside the same limits: the
park at the end of the night, which the person asked for standing, and the
transit hold's small corrections during a run they started.

## It learns from real nights

A night that fails is measured, and the next is changed by what was found:

- **19 October, the comet hunt:** one known comet split into two tracks by
  a gap in the pictures, and a false alarm at the occulter's edge. By noon
  the hunt joined tracks, set rim tracks aside, checked finds against the
  planets and public reports, and sent its verdict as a second message.
- **20 October, WASP-12 b:** a transit seen but not measurable. The same
  frames were measured 288 ways to find why; the hold, the calibration
  warnings, the exposure headroom and a recipe followed the same day.
- **20 October, the morning:** the night ended in cloud, outside the
  schedule, and the mount tracked on unparked; the night's end now parks and
  tells the person.

## What it is not, yet

It has no dome or roof and no weather station of its own; it has run on one
person's telescope, and long unattended operation over many nights is not
yet proven. It has made no discovery of its own. [validation.md](validation.md)
keeps the full account.
