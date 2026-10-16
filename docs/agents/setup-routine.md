# Setting up at the telescope: the agent's routine

For an agent on the laptop beside the telescope while a person is outside
with it. The person's guide is `docs/first-night.md`; this is the same night
from the agent's side: what to run, in what order, and what to ask.

**The agent runs the commands.** The person is outside in the cold with
their hands on the mount. Never hand them a command to type. Tell them only
what needs their hands or their eyes, in a line, and say before anything
moves. A move they ask for is the go (`AGENTS.md`, safety rule 1): dry-run
it, and if it passes, send it at once, with no warnings about cables,
standing clear or the tube swinging; they know. So is telling you what they
can see: "it's clear to the north, can see Polaris" means they are outside,
and the next step that fits that sky starts now, without asking.

**Look before asking.** `lsusb`, `./doctor.py --offline` and `./mount.py
status` (which only reads) say what is plugged in, whether the handset is
past its start-up screens, and where the axes are. Reread what the person
has said: do not ask what it already answers.

**Follow the steps in order, and skip none.** A step may be left out only
when the rig's state shows it is already done tonight: say which, and why.

## 0. Before they go out (indoors)

Dry-run every move planned for the night (`--dry-run`), and run
`./doctor.py --offline`. Anything that can fail should fail now, not with
them standing beside the mount.

## 1. Set the handset

They have put the mount in home by eye (counterweight bar down, tube at the
pole), switched on and pressed ENTER through to the main menu. Check that
with `./doctor.py --offline` ("handset answering and set up"), then

    ./mount.py settime

It moves nothing. It gives the handset this laptop's date, time and site,
and measures its clock. Every later step depends on it.

## 2. Ask where the sky is clear

**Ask the person.** They can see the sky and the forecast cannot: a forecast
of cloud may be wrong either way, and a failed plate solve can be cloud,
focus or too short an exposure. Ask which parts of the sky are clear (the
pole? the south? overhead?) and choose every star and target from their
answer. Never send them out, or keep them waiting, on the forecast's word.

## 3. See that the motors really turn

They stand beside it, clear of the bar.

    ./mount.py nudge

The tube tips 5° and comes back. Ask whether they saw it. If the screen
says it moved and they say it did not, the motors have stalled (6 October
2026): power-cycle and go back to step 1.

## 4. Focus

    ./mount.py goto Deneb      (or any rich star field in clear sky)
    ./focus.py --motor

The motor focuser does it: nobody touches the telescope, so never ask for a
hand on the knob. `--motor` focuses wherever the telescope points, so point
at a rich field first. Run it in the background and report the result (HFR
about 2 to 2.5 is good on the 150P). `./focus.py --field`, the hand-turned
aid with tones, is only for a telescope without the motor. Focus comes before anything that plate-solves: the polar alignment
and every `--solve` work from the stars in a picture, and blurred stars give
no answer. A failed plate solve before this step says nothing about cloud.

## 5. Polar alignment

Only needed when the tripod has been moved or its foot marks are lost;
otherwise the last alignment stands. First a GoTo with plate solving to a
bright star in a part of the sky they said is clear (Vega in autumn
evenings), which also measures the pointing:

    ./mount.py goto Vega --solve
    ./polaralign.py --step 12

Before the first measurement, they centre the two azimuth bolts. After each
measurement, tell them which bolt, which way and how far, in its own words;
once they have turned it, run it again with `--turned`, until under half a
degree. A house or tree in the way of the third picture: a smaller `--step`.

## 6. GoTo and image

From `./tonight.py` and what they said is clear:

    ./mount.py goto TARGET --solve
    ./shoot.py TARGET --frames 0 --recentre 8

Tell them when it is running and they can go in. While they are inside
nobody is watching the mount: make no move they did not ask for.

## 6b. Or a discovery patrol, when they ask for one

    ./patrol.py m31-novae --plan     readiness: lock, field, darkness, reference, focus, expected depth
    ./patrol.py m31-novae            point, image, then depth, subtraction, vetting and the answer

Run `--plan` first and read it out: anything marked NO is said once, and
the focus line comes before going on. The patrol moves the mount only
through `mount.py goto` and `shoot.py`, so it is the same move as step 6
and needs the same go-ahead. When it ends, its last lines are the answer:
say how deep it reached and how many candidates were unexplained, and
show each `patrol-N.png` before calling anything a find. A candidate is
only interesting once `candidates.py` shows it seen on more than one
night (`docs/discovery.md`).

## Not tonight unless asked

Finding the true home (`findhome`, `truehome`, then marking the joints with
paint, nail varnish or a scratch, never crayon or chalk), `pointing`,
`response`: each is a calibration for a spare clear night, not part of
getting a picture.
