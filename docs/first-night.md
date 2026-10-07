# From box to first galaxy

[Back to the README](../README.md)

*A first night with a motorised telescope, for someone who does not know
what any of this means yet.*

You have a Sky-Watcher telescope on a motorised mount with a SynScan
handset, a camera, and a laptop. You want a picture of a galaxy. You do not
need to know what RA, Dec, polar alignment, plate solving or HFR mean
tonight. Each step below says what to do, what you should see, and, folded
away, what it was for. [What telescopeyoke just did for you](how-it-all-works.md)
explains all of it afterwards, when you have a picture to show for it.

**How much of this has been done for real.** This project is young and says
so. On the author's EQ3, 150 mm Newtonian and Hypercam, under real stars:
the polar alignment (step 5), focusing by the star measurement (step 7), the
GoTo that corrects itself (step 9) and the picture (step 10) have all
worked. Finding and marking the true home (step 6) and the click-and-tone
focusing sounds have so far run only on a simulated mount and made-up
stars. Each step says which it is. [The full account](validation.md) is kept
up to date.

It is written for Ubuntu, where the project is developed. On Windows the
commands are `python doctor.py` in place of `./doctor.py`, and so on; see
[Setup](setup.md#windows) for what has and has not been tried there.

## An afternoon indoors, before any night

Do this in daylight, in the warm. Nothing here needs the sky.

1. **Install it and try the demo.** Follow the [Quick start](../README.md#quick-start).
   The demo is the whole application on a pretend telescope: press every
   button you like, nothing real can move.
2. **Tell it where you are.** Copy `config.example.toml` to `config.toml` and
   put in your latitude and longitude. This file stays on your computer.
3. **Plug everything in and ask the doctor.** Mount lead and camera into the
   laptop, mount switched on, then:

       ./doctor.py

   It lists what it can see: the handset, the camera, the plate solver and
   its star database. Fix anything with a cross beside it using
   [Setup](setup.md) before going on. If you get stuck, `./doctor.py --report`
   writes the whole thing out to post in
   [Discussions](https://github.com/Ryan-Clinton/telescopeyoke/discussions).
4. **Ask what tonight is like.**

       ./tonight.py

   It says whether the night is worth it (GO, MARGINAL or NO-GO), when it is
   dark, and what is worth pointing at.

## 1. Put the telescope together safely

- Tripod on firm ground, legs spread fully, roughly level. Mark where the
  feet stand: next time they go back on the same marks.
- Mount head on the tripod. **Counterweights on before the telescope**, and
  off after it, always: a tube with no weight opposite it swings down hard.
- Telescope on, camera in the focuser. Loosen each clutch in turn and slide
  the weights and the tube until neither axis swings by itself.
- Leave slack in every cable. The tube will swing right over the top of the
  mount during the night, and a lead that pulls tight stops the night.

<details>
<summary>Why "roughly" level is enough</summary>

The mount only needs its main axis to point at one particular spot in the
sky. Later tonight the stars will tell telescopeyoke exactly where that axis
points, however the tripod leans. A level tripod just makes the adjusting
bolts behave more simply.
</details>

## 2. Point the mount roughly north

Turn the whole mount so that its main axis, the one the counterweight bar
turns about, points north and up at the sky, towards the Pole Star if you
can find it. A phone compass is good enough. Do not fuss: step 5 measures
how far out it is and tells you which bolt to turn.

## 3. Switch on, at the home position

Turn the telescope by hand (clutches loose, then locked) so that the
**counterweight bar hangs straight down** and the **tube sits on top,
pointing along the mount's main axis**, at the pole. That is the home
position. Then switch the mount on, and press ENTER on the handset through
every start-up screen until it shows its main menu. You do not need to type
the date: once it is at the main menu, run

    ./mount.py settime

Now see that the computer really moves the telescope. Stand beside it, clear
of the bar, and run

    ./mount.py nudge

The tube tips a little way and comes back. If the screen says it moved and
the tube did not, switch the mount off and on and start this step again.

<details>
<summary>What "home" is</summary>

The mount has no way of knowing which way it is facing when it wakes up. It
simply assumes it is in the home position, and counts every later turn of
its motors from there. So how well you set home decides how close its first
aim lands. By eye it is usually a few degrees out. Step 6 measures and
fixes that; step 9 copes with it meanwhile.
</details>

*Proven on the real mount: `nudge` and `settime` each ran once, on 7 October 2026.*

## 4. See what the rig knows about itself

    ./ty characterise

In the application this is the **Rig knowledge** screen. It lists what has
been measured about this telescope and what has not, with the command for
each. On a first night nearly every line reads "not measured". That is the
point: each step from here turns one of them into a number, and you can
watch the count go up. None of it has to be finished tonight.

## 5. Get the mount pointing at the pole

Wait until it is dark enough to see stars. Send the telescope to a bright
star well away from the pole, and let it correct its own aim (step 9
explains what it is doing). Vega is high on autumn evenings; `./tonight.py`
lists what is up at other times:

    ./mount.py goto Vega --solve

Then:

    ./polaralign.py --step 12

Before the first measurement, **centre the two azimuth bolts** (the pair
that swings the mount head left and right): the same length of thread
showing on each, so there is room to go either way.

It takes three pictures of the sky, turning a little between them, and
answers in plain words: "it points 3.1° too far east of north; swing the
mount's north end 3.1° to the west", and the same for up and down. Turn the
two pairs of bolts on the mount's base by about that much, and run it again,
until it is under half a degree, which is plenty for tonight. If it is more
than a couple of degrees out to one side, it tells you to turn the whole
tripod instead, and by how much. Tell it what you turned each time
(`--turned 0.5 0`, or the two boxes on the application's Polar alignment
screen, which also draws each bolt) and it learns what a turn does on your
mount, and from then on says "left bolt in, about half a turn".

A first answer of five degrees is not a failure. It is the software telling
you exactly what to change.

<details>
<summary>What polar alignment is</summary>

The sky seems to turn about one point, close to the Pole Star, because the
Earth is turning. If the mount's main axis points at that same point, one
slow motor can follow any star all night. If it points somewhere else, the
stars slide slowly out of the picture. The three pictures show where the
axis really points, because the middle of each picture travels on a circle
about it.
</details>

*Proven on the real mount: five rounds took the author's from 5.2° to 0.2°.
If a house or a tree is in the way of the third picture it says so; a
smaller `--step` usually clears it.*

## 6. Find the true home, and mark it

Home was set by eye in step 3. Now that the mount points at the pole, the
stars can say where home really is:

    ./mount.py findhome

It visits eight places, four on each side of the sky, photographs each, and
works out how far the home you set is from the real one. The tube swings
over the top of the mount once: stand clear. Then

    ./mount.py truehome --dry-run
    ./mount.py truehome

The first line shows where it would go; the second goes there and holds.
**Mark both joints of the mount now**, a paint dot or a scratch across each
gap. Switch the mount off and on with the marks lined up, press ENTER
through the handset's screens, run `./mount.py settime`, and run
`./mount.py findhome` once more to see what is left.

From then on, setting home is lining up two marks, and step 3 takes a
minute.

**You can skip this on a first night.** Step 9 corrects the aim anyway. Do
it on the second or third night, when the rest is familiar.

*Not yet proven: this has run only on a simulated mount. The first real run
is still to come. If its answer looks wrong, it says so and moves nothing.*

## 7. Focus by ear

Start the focusing aid. With `--field` it first moves the telescope to a
bright star with plenty of others round it, so keep clear as it starts:

    ./focus.py --field

Put a hand on the focuser and turn it slowly. You do not need to look at
the laptop.

- Every **click** means a picture has just been measured: your last turn
  has been seen.
- The **tone** after it is higher the sharper the stars. Turn the way that
  makes it rise.
- It will say "Level two", then "Level three. Fine focus" as you get
  closer. Turn less each time.
- Keep going until it says **"Minimum passed. Reverse slightly."** You have
  gone through the sharpest point. Come back gently.
- Stop at **"Focus good. Hold."**

<details>
<summary>What it is measuring</summary>

How wide the stars are in the picture. A star in focus is a tiny dot; out
of focus it is a blob, and far out, a ring. The number it works with is the
half-flux radius, HFR: the radius that holds half of a star's light.
Smaller is sharper. It measures many stars at once so that the air's
shimmer, which makes any one star dance, averages out.
</details>

*Partly proven: the star measurement brought the real telescope to focus on
6 October 2026, with the readings spoken as numbers (`--numbers` still does
that). The clicks, tones and levels have so far run only on made-up stars.*

## 8. Ask what you can see tonight

    ./tonight.py --top 10

Or the **Tonight** and **Targets** screens. Each line is something worth
pointing at, best first, with when it is highest, how high, which way, and
the hours it is in view. It already allows for the Moon, your sky's
brightness and, if you have [taught it your skyline](../README.md#what-makes-it-different),
your house and trees.

For a first galaxy from the northern hemisphere, the Andromeda Galaxy,
**M31**, is the one: big, bright, and high in the autumn and winter evening
sky. In spring try M81. In summer the Dumbbell Nebula, M27, is not a galaxy,
but it is the first thing this project photographed.

## 9. Press GoTo, and let it fix its own mistake

    ./mount.py goto M31 --solve

The mount slews. It will not land exactly on the galaxy: no inexpensive
mount does, least of all one whose home was set by eye. So the camera takes
a picture, telescopeyoke works out from the stars in it where the telescope
really ended up, and nudges it across. You will see something like this,
from the author's first night:

    off by -107.0' in hour angle, +94.4' in Dec
    off by -6.2' in hour angle, -11.4' in Dec
    off by +1.0' in hour angle, -1.8' in Dec
    centred

Nearly two degrees out, then a tenth, then centred. Before every move it
tells you if the tube will swing over the top of the mount. Keep clear of it.

<details>
<summary>How it knows where it is pointing</summary>

Plate solving. The pattern of stars in any picture of the sky is unique,
like a fingerprint. A program called ASTAP compares the pattern in the
camera's picture with a catalogue of every star and says exactly which
patch of sky it shows. The difference between that and where the galaxy is
tells the mount how far to move.
</details>

*Proven under real stars.*

## 10. Take the picture

    ./shoot.py M31 --frames 100 --exposure 2 --recentre 8

One long exposure would smear, because the mount is not perfect. So it
takes a hundred short ones. Each is checked as it arrives, the poor ones are
set aside, and the good ones are lined up on their stars and added together.
Open the status page (`./serve.py`, then `http://localhost:8080`, or from
another computer in the house) and watch two pictures side by side: **Now**,
the newest single exposure, which looks like almost nothing, and **Live
stack**, which grows clearer as the frames add up, until the galaxy's glow
stands out of the grain. That light left it two and a half million years
ago, and it is on your screen.

Every raw frame is kept. When the run ends, a slower, more careful pass
goes back over them and makes the finished picture, and any better method
later can remake it from the same frames.

*Proven under real stars: runs of 48 and 207 frames. One caution from those
nights: this camera exposes for about two thirds of the time it is asked,
so "2 seconds" is nearer 1.3.*

## Putting it away

`./mount.py home`, switch off, counterweights off **last**. Leave the tripod
feet's marks where they are.

## When something goes wrong

| What you see | What to do |
|---|---|
| A command refuses and says why | Read the sentence: every refusal says what to do next. |
| The screen says the mount moved and it did not | Switch the mount off and on, press ENTER through the handset's screens, set the tube to home by hand, start from step 3. |
| "Could not plate-solve" | Cloud, or badly out of focus, or something in the way. Look at the newest picture on the status page before anything else. |
| The tone never rises | You may be far from focus. Turn steadily one way for several clicks; if the buzz of "no star" does not stop, turn the other way. |
| Rain | `./mount.py stop`, then bring it in. Nothing needs to finish. |
| Anything looks about to hit anything | `./mount.py stop`, or the mount's own power switch. Create a file called `MOTION_LOCKED` in the folder and nothing will move until you delete it. |

## What you just did

Tonight you polar-aligned an equatorial mount, measured its home position,
focused by half-flux radius, planned by altitude and moonlight, plate-solved
a GoTo and stacked calibrated sub-exposures. You did not need any of those
words to do it. When you want them:
[What telescopeyoke just did for you](how-it-all-works.md).
