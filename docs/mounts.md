# Mounts: what works, what is planned, and how to ask for yours

[README](../README.md) · [Hardware](../README.md#hardware) · [Validation](validation.md) · [Research notes](research/mount-protocols-2026-10-20.md)

telescopeyoke has driven one mount so far: the author's Sky-Watcher EQ3
Pro, through its SynScan handset. Nothing in it is meant to stay
Sky-Watcher-only. This page says which mounts can be reached and how, in
the order they are planned, and what a tester would be asked to do. The
facts behind it, with their sources and what is still unconfirmed, are in
the [research notes](research/mount-protocols-2026-10-20.md) (20 October
2026).

**Your mount is not here, or you would test one?** Open a
[Mount support request](https://github.com/Ryan-Clinton/telescopeyoke/issues/new?template=mount-support.yml).
The first thing asked of you only reads: `./doctor.py --report --probe
PORT` asks the port what it is and tells it to do nothing.

## The rule every mount keeps to

The safety checks are above the mount, not inside it: the motion lock, the
Sun, altitude and hour-angle limits, the dry run before a move, the check
that the camera saw the move, the handset's or mount's state before a move.
A new mount is a new way of saying "where are you, go there, stop, turn
this slowly, track"; it never gets a way round the checks. Each one is
proven in steps, with a person beside it: reading only, then one small
move, then a GoTo, then a night.

## Where each family stands

| Family | How it is reached | Status |
|---|---|---|
| Sky-Watcher with a SynScan handset (EQ3/EQ5/HEQ5/EQ6/EQ6-R/AZ-EQ) | the handset's serial protocol, 9600 baud | ✅ EQ3 Pro, firmware 3.35. Same protocol on the rest: wanted, testers |
| Sky-Watcher with no handset: EQDIR lead, the Wi-Fi adapter, the USB socket on the mount (EQ6-R, newer HEQ5), AZ-GTi, Star Adventurer GTi, Wave | the motor board's own protocol (the one EQMOD speaks): serial at 9600, the mount's USB at 115200, Wi-Fi on UDP 11880 | ⚠️ built (`direct.py`); the Wi-Fi adapter read, nothing moved yet. Testers wanted |
| Celestron with a NexStar hand controller (NexStar SE, Evolution through its controller, Advanced VX, CGEM, CGX, CPC, StarSense) | the same hand-controller protocol family as SynScan: 9600 baud, the same commands for position, GoTo, stop and slow moves | 🗓️ planned first: a small variant of the SynScan class |
| Any mount INDI drives (about 100 drivers: iOptron, Celestron Wi-Fi, Losmandy, 10Micron, OnStep, ZWO and more) | an INDI client for mounts, beside the one already used for cameras | 🗓️ planned: the general route on Linux |
| Any mount with an ASCOM or Alpaca driver | ASCOM Alpaca, HTTP and JSON on the network: ASCOM Remote on Windows, INDIGO's Alpaca agent on Linux | 🗓️ planned: the general route on Windows, and the Windows port's way to every mount |
| ZWO AM3, AM5, AM7 | ZWO's published LX200-based protocol, serial at 9600 or Wi-Fi on TCP 4030 | 🗓️ planned: the first native driver of the LX200 family (OnStep would follow) |
| iOptron, Losmandy Gemini, 10Micron, Avalon, Rainbow, Celestron Wi-Fi (AUX) | their own languages | through INDI or Alpaca, not native drivers |

## The plan, in order

**0. Done now (20 October 2026).** A SynScan handset on firmware 4.39.21
or later is refused: from that version, by Sky-Watcher's release note
(seen only quoted, not yet confirmed), the question this program reads the
axis angles with ("z") answers with altitude and azimuth instead, which
would put home and the limits in the wrong place. The handset's firmware is
read at every connection; a tester with a newer handset would settle it.

**1. Sky-Watcher, the whole family.** The motor-board path already speaks
the right protocol; it needs its transports named and tested: the USB socket
on the mount at 115200 (already a setting: `[mount] baud`), and Wi-Fi on
UDP 11880 (already `link = "wifi"`). Testers: an EQ6-R or HEQ5 on its USB
socket, an AZ-GTi or Star Adventurer GTi on Wi-Fi, any mount on an EQDIR
lead. Steps: the doctor's probe; `./mount.py status`; `./mount.py
directions` with the person watching (which way the Dec motor turns); one
`nudge`; a GoTo with centring.

**2. Celestron hand controllers.** A variant of the handset class with
Celestron's differences: the version answer, the model table, the tracking
mode numbers (3 is southern equatorial on a Celestron and PEC on a
SynScan), the reply timeout, and the axis angles, which come from the
passthrough rather than "z". The doctor learns to tell a Celestron from a
SynScan by its model answer first. Testers: an Advanced VX, a CGEM or CGX,
a NexStar SE.

**3. INDI mounts (Linux).** A mount client on the existing INDI code using
about fifteen standard properties: position and GoTo
(`EQUATORIAL_EOD_COORD` with `ON_COORD_SET` set to slew, track or sync),
abort, park, tracking state, timed guide pulses north-south and east-west,
pier side, time and site. The checks stay in front of it. Testers: anyone
already running KStars/Ekos with an iOptron, a ZWO, a Losmandy or an
OnStep mount.

**4. Alpaca (Windows and Linux).** A client for the Alpaca telescope
interface (`/api/v1/telescope/N/…`: slew, sync, park, abort, pulse guide,
tracking, side of pier), finding the server by Alpaca's discovery broadcast
(UDP 32227). It reaches every ASCOM driver through ASCOM Remote, so it is
also how the Windows port drives mounts other than SynScan. Testers: any
Windows user with a working ASCOM driver (EQMOD, GS Server, iOptron
Commander, the ZWO and Celestron drivers).

**5. ZWO AM3/AM5/AM7 natively.** ZWO's own protocol over USB or Wi-Fi, on
a small LX200 core that OnStep would share. Testers: an AM5 owner.

## Asking for testers

Each step above needs one person with that mount, willing to run the
read-only checks first and to stand beside it for one small move.
Nothing moves until they choose it, and the first reports are useful even
if nothing ever moves. The request form asks for the mount, the
controller and its firmware, the link, the computer, and what the doctor
says.

## Not planned

ASCOM's Windows-only COM interface directly (Alpaca reaches the same
drivers across systems), mobile apps as controllers, and mounts with no
computer interface at all.
