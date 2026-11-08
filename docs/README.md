# The documentation

[README](../README.md) · Guides: [First night](first-night.md) · [Setup](setup.md) · [Imaging](imaging.md) · [Calibration](calibration.md) · [Focus](focus.md) · Science: [Discovery](discovery.md) · [Results](results.md) · [Validation](validation.md) · Developers: [Contributing](../CONTRIBUTING.md) · [Agents](agents/README.md)

Every page, by what you came for. Four kinds of page are kept apart: a
**guide** walks you through something, a **reference** lists what there is,
a **record** says what happened on a dated night or test, and a
**specification** says what was designed and why (some of it ahead of what
is built). What is proven is decided in one place,
[Validation](validation.md).

## I have a SynScan mount and want to try it

| Page | Kind | What is in it |
|---|---|---|
| [From box to first galaxy](first-night.md) | guide | A first night for someone who knows none of the words. Says which steps are proven on a real mount. |
| [Setup](setup.md) | guide | Installing, the camera driver, the plate solver, what the computer needs; Windows. |
| [Hardware](hardware.md) | reference | What it has run on, what to expect of yours, how to send a report, EQMOD and ASCOM, more than one telescope. |
| [Mounts](mounts.md) | reference | Which mounts can be reached and how, in the order planned. |
| [Calibrating a mount, in order](calibration.md) | guide | Level, polar-align, find the true home and mark it, measure the pointing each side. |
| [Focusing by ear](focus.md) | guide | Turn the knob and the laptop talks you onto focus. |
| [The motor focuser](focuser.md) | record | The project's own focuser motor and what it can lift. |
| [How a picture is made](imaging.md) | guide | Calibration, frame checks, lining up, stacking, the quality pass. |
| [Imaging the Moon](lucky-imaging.md) | guide | Short frames, no stars to solve on. |
| [The mount is wonky; measure how wonky](tracking.md) | guide | Drift from a rough polar alignment, and how it is cancelled. |
| [Collimation](collimation.md) | guide | Lining the 150P's mirrors up. |
| [Commands](commands.md) | reference | Every script, what it does, how they fit together, and a night by hand. |
| [What makes it different](features.md) | reference | Each way it measures and works round modest equipment, with how far each is proven. |

## I want to see what it has found

| Page | Kind | What is in it |
|---|---|---|
| [Results so far](results.md) | record | Each real result as question, method, result and limits: the self-centring GoTo, the mount measured, WASP-12 b, the nova patrol, Kepler, SETI, the 183M's first M33. |
| [Validation](validation.md) | record | Exactly what has and has not been proven, night by night. |
| [Looking for something new](discovery.md) | guide and specification | The discovery station: novae in M31 and M33, transits, public alerts, and its phases. |
| [Discovery results](discovery/results.md) | record | What each phase measured. |
| [Searching the Kepler archive](archive.md) | guide and record | Tabby-like dips in Kepler's and TESS's light curves. |
| [The leads](research/README.md) | record | Each lead from the archive searches, and what explains it. |
| [Radio SETI](seti.md) | guide and record | Breakthrough Listen's open data, searched slice by slice. |
| [What is kept, and what a find needs](data.md) | reference | The files behind a claim. |
| [Naming the satellite in a frame](satellites.md) | guide | Trails identified from their orbits. |
| [Nights](nights/) | record | The dated night files the other pages link to. |

## I want to watch it, or run a broadcast

| Page | Kind | What is in it |
|---|---|---|
| [The live stream](streaming.md) | guide | Running the YouTube and Twitch broadcast: what viewers see, the presenter, the chat's commands. |
| [The public live page](live-page.md) | reference | What is public while the telescope works, and what it reads. |
| [The stream's design record](stream-look.md) | specification | Why the broadcast looks as it does. |
| [Alerts](alerts.md) | guide | The house's lights and speaker, the phone, and calling the person. |

## I build with AI agents

| Page | Kind | What is in it |
|---|---|---|
| [For programs and AI agents](agents/README.md) | guide | `--json`, `--dry-run`, the `ty` command, the web API and the MCP server. |
| [Commands for agents](agents/commands.md) | reference | Every `ty` command, classed by what it may do. |
| [Safety](agents/safety.md) | specification | Why the language model never decides what may move. |
| [Architecture](agents/architecture.md) | reference | How the scripts fit together, on one page. |
| [Skills, agents and hooks](skills-and-agents.md) | specification | The Claude skills and specialist agents that hold the routines. |
| [The setup routine](agents/setup-routine.md) | guide | The order an agent follows at the telescope. |

## The equipment's own records

| Page | Kind | What is in it |
|---|---|---|
| [Adding the 183M, filter wheel and corrector](mono-upgrade.md) | specification | The cooled mono train: what changed and why. |
| [Autoguiding](autoguiding.md) | specification | Guiding through the guide camera's ST4 lead, with dithering. The ST4 lead works; star, calibration and loop are built but have not guided, and the camera does not yet deliver 2 s frames on its hub. |
| [The guide camera's dropped frames](guide-camera-fault.md) | record | Why the guide camera does not stream: what was measured, what is ruled out, what others found, what is left to try. |
| [The main camera's lost-frame fault](camera-fault.md) | record | The 183C's fault from the first sign to the latest test. |
| [The camera's row stripes](banding.md) | record | What others found, and what was measured here. |
| [The USB hub](usb-hub.md) | record | The powered hub at the telescope. |
| [The cloud sensor](cloudsensor.md) | specification | A plan for a box on the wall that says whether the sky is clear. Not built. |

## Plans and designs

| Page | Kind | What is in it |
|---|---|---|
| [The application](gui.md) | specification | The window and its companion page. |
| [Running on Windows](windows-port.md) | specification | The Windows port. |
| [Planning a night by what it gets](observing-plan-spec.md) | specification | The outcome-led planner, phase by phase. |
| [Flexible plans](flexible-plans.md) | specification | Changing a night's plan when it goes wrong. |
| [Changelog](../CHANGELOG.md) | record | What each release added. |
