# The USB hub

The camera, the focuser's Nano and sometimes the handset lead go through one
powered hub at the telescope. This page is the record of that hub: what it
is, every way it has failed, what other owners report, and what replaces it.
The camera's own fault (short exposures, jams) is a separate matter, in
[`camera-fault.md`](camera-fault.md).

## The hub

- **RSHTECH RSH-ST04**, 4-port powered USB 3.0 hub, aluminium, with a 1 m
  USB-B to USB-A/USB-C lead and a 5 V / 2 A mains adapter. Bought 22 October
  2026, £22.98. It arrived on 26 October and came into use on 30 October.
- **Inside it is two hubs.** Linux sees a USB 3 half, Realtek `0bda:0411`,
  and a USB 2 half, Realtek RTS5411 `0bda:5411`. The camera runs on the
  USB 3 half. The Nano (CH340) and the handset's FTDI lead run on the USB 2
  half.
- **Each port has a power button.** The hub also switches each port's power
  on command, so `usbpower.py` (through uhubctl) can cut the camera's power
  from the laptop when the camera jams. That came in on 1 November 2026.

## How it failed

The figures come from the laptop's kernel log (`journalctl -k`).

| When | Set-up | What happened |
|---|---|---|
| 30 Oct, 16:43 to 17:27 | The 3 m lead from the laptop to the hub, the new 1 m lead to the camera. Two laptop sockets and two hub ports tried | The camera dropped off USB within two minutes each time, even at readout speed 0. The kernel timed out reading it (`error -110`), the camera's fan stopped and the hub's light flashed. Pressing the port button twice brought it back |
| 30 Oct, 17:28 onwards | The two 1 m leads, either way round | Speed 0 kept 50 of 50 and speed 2 kept 720 of 720. **But** the hub itself dropped off the laptop 19 times around 21:10, unnoticed at the time |
| 30 Oct, about 22:20 | The Nano on the hub, then on a laptop socket | It lifted the drawtube on the hub but stalled on the laptop's socket. The hub's power is what let the focuser lift |
| 31 Oct 23:43 to 1 Nov 02:30, outside | The hub's own 1 m lead from the laptop to the hub, the old 1 m lead to the camera. Two laptop sockets | **The hub dropped off the laptop 142 times**, 101 of them between 00:00 and 01:00, with 57 `error -71` (a garbled signal on the wire). Mostly the USB 2 half went, taking the Nano and the handset lead with it; sometimes the USB 3 half went too. Pressing a port button does not bring the USB 2 half back; replugging the hub's lead at the laptop does |
| 1 Nov, 20:15 to 20:34 | The hub moved to the laptop's working USB-C socket | **The USB 3 half dropped 35 times.** From 20:22 the camera came back only at USB 2 speed, where it sends no frames, so the walk-in could not run. The camera then went straight into the laptop |

**What that rules out:**

- **The leads:** it dropped on both 1 m leads, its own and the old one.
- **The laptop's sockets:** it dropped on two USB-A sockets and on USB-C.
- **The Nano as the cause:** it dropped on 30 October with the old motor
  driver, and on 1 November with the TMC2209.
- **The camera:** the camera's own fault happens without the hub, and the
  hub drops devices that are not the camera.

What is left is **the hub's own link to the laptop.** Each failure was on
the hub's upstream side: the 3 m lead into it, its USB 2 half, then its
USB 3 half. Noise from the mount's motors is not ruled out, but the worst
burst came while the tripod was being turned by hand, with the mount only
tracking.

## What other owners say

From the hub's Amazon pages, read on 1 November 2026:

- **Amazon UK:** 4.3 out of 5 from 99 ratings, 13 % of them 1 or 2 stars.
  A review of 21 August 2026 says that even with the 5 V supply it cannot
  power the devices on it, "no more than an ordinary usb A socket". A video
  review is titled "Great while it lasted, now intermittent connectivity".
- **Amazon US:** 4.5 out of 5 from 234 ratings. Amazon's summary of the
  reviews says "some customers report no failures, others mention issues
  with USB ports failing intermittently", and reliability is the
  most-mentioned topic (32 reviews).
- **uhubctl's maintainer** says very few Rosonway hubs (the maker behind
  RSHTECH) truly cut a port's power; most only cut the data lines. This one
  does cut it: the camera's fan stops.

So we are not the only ones: intermittent ports and a weak supply are both
reported. Nothing published mentions the Realtek chips themselves dropping
in a loop. That points at this unit or this design, not the chips.

## The return

A return to Amazon was started on 1 November 2026 (returnable until 31
January 2027) as "Item is defective or does not work", with the comment:

> Hub keeps disconnecting: USB 2 ports dropped about 150 times in one night,
> on two different cables and two laptop ports. USB 3 side also drops out.
> Connected devices cut off mid-use.

## What replaces it

Budget: up to about £70 (the £20 refund plus £30 to £50). Facts checked on
1 November 2026.

### Four separate requirements

1. **A link that stays up:** the hub's own connection to the laptop, on both
   its USB 2 and USB 3 sides.
2. **Power:** enough for the camera's fan and the focuser's motor together.
   A bigger adapter on the box does not prove better regulation inside;
   what is known here is only that this 5 V / 2 A hub let the motor lift
   where a laptop socket did not.
3. **Remote power cut for the camera:** the laptop switching the camera
   port's 5 V off and on (`usbpower.py`, through uhubctl), which cleared
   every jam on 1 November. A port button pressed by hand is not this. Nor
   is a hub that only cuts the data lines: uhubctl testers have found many
   that leave the 5 V on. The laptop's own sockets cannot do it (checked
   with uhubctl).
4. **Outdoors:** cold, damp, leads moving.

The jobs need not share one box. **The camera can be on its own**, straight
into the laptop or on a hub of its own, **with the Nano and the handset on a
separate powered USB 2 hub.** Then a hub dropping its USB 2 side cannot take
the camera with it, and a camera power cut cannot take the focuser.

### Candidates under about £70

| Hub | Price | 1. Chip | 2. Power | 3. Remote power cut | 4. Outdoors |
|---|---|---|---|---|---|
| **Lindy 43374**, 4-port USB 3.0 metal hub | £59.59 + £4.35 post (Comms Express; out of stock at Lindy) | VIA VL817 (seller's listing), not Realtek | External adapter included | **Unknown**: VL817 hubs can switch, but only if the maker wired the switches. Testable on arrival with uhubctl, within 30 days | Industrial: all-metal case, EMC protection, mounting brackets, short-circuit protection per port |
| Amazon Basics HU3770V1, 7-port (ASIN B00E6GX4BG) | £29.99 used, eBay, 30-day returns | VIA VL812 | 12 V / 3 A | **On uhubctl's list** | Plastic. A 2013 design, bought used: its condition is unknown |
| TP-Link UH720, 7-port | not checked | **Realtek RTS5411**, the same USB 2 chip that dropped 142 times | 12 V | **No.** uhubctl testers found it cuts only the data lines; the 5 V stays on | Plastic |
| StarTech HB31C2A2CB | £56.90 (Amazon UK) | StarTech's own | Adapter included | Partly: a USB 3 device's power only goes off when every port is off | Plastic |
| RSHTECH RSH-ST10C-6 | £44.99 | Realtek, the same USB 2 chip | 12 V / 5 A | Yes, with catches | Aluminium |

Over budget or unsuitable:

- **Pegasus Astro USB Control Hub:** £169. No used one on eBay UK or
  Facebook Marketplace.
- **Yepkit YKUSH3**, a USB 3 power switcher: €124.99, out of stock. Its
  USB 2 sibling, the YKUSH at €59, cannot carry the camera.
- **StarTech HB30A4AIB:** takes all its power from the laptop.

### The choice

- **If the remote power cut matters:** the Amazon Basics, the only one in
  budget known to do it. Check its label says HU3770V1, and test it on
  arrival. Or the Lindy, if it turns out to switch on arrival; return it
  within 30 days if it does not.
- **If not:** the Lindy, for the build and the different chip. The camera
  goes straight into the laptop, and a jam means pulling its lead at the
  scope.

Whichever is bought, test it on arrival indoors, before any night that
depends on it. Run `./camera_test.py --power-cycle` and see whether the
camera's fan stops. Then run a long frame run with the Nano on the same hub.

**With no hub,** the camera goes straight into a laptop USB-A socket. Plugged
in that way it has never dropped off USB, including three 720-frame runs on
the 3 m lead. The cost: nothing can cut its power there, so a jam means
pulling its lead. The Nano on a laptop socket can turn the focuser inward but
cannot lift the drawtube outward.
