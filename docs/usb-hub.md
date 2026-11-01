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

What the telescope needs from a hub:

1. A USB 2 side that stays up, for the Nano and the handset lead.
2. Enough power for the camera's fan and the focuser's motor together.
3. **Per-port power switching the laptop can command**, so the camera's jam
   is still cleared without anyone going outside.
4. Happy in the cold and damp outside.

Budget: up to about £70 (the £20 refund plus £30 to £50). The laptop's own
USB sockets cannot cut a port's power (checked with uhubctl on 1 November
2026), so the hub has to.

| Hub | Price | Power | Laptop can cut a port | Notes |
|---|---|---|---|---|
| **Amazon Basics 7-port USB 3.0, HU3770V1** (ASIN B00E6GX4BG) | £29.99 used on eBay, free post, 30-day returns | 12 V / 3 A adapter | Yes, on uhubctl's list | VIA VL812 chips (`2109:2811`), not Realtek. Seven ports, so the camera, the Nano, the handset and the guide camera all fit. uhubctl's only warning is about Raspberry Pis, not laptops. Check the label says HU3770V1: the later Amazon Basics U3-7HUB switches only one port |
| StarTech HB31C2A2CB | £56.90 new (Amazon UK) | Adapter included | Partly | Two USB-A and two USB-C ports. Owners say a USB 3 device's power only goes off when every port is off, so a camera power cut would cut the Nano too |
| RSHTECH RSH-ST10C-6 | £44.99 (Amazon UK) | 12 V / 5 A adapter | Yes, with catches | Same maker and the same Realtek USB 2 chip. Owners say switching works only from the USB 3 side, ports must first be on at the touch buttons, and one USB-C port ignores commands |
| The same RSH-ST04 again | about £19.49 | 5 V / 2 A | Yes, as now | The reviews report the same faults |
| Pegasus Astro USB Control Hub | £169 | 12–14 V, 8 A | Yes, through INDI | Built for telescopes, but out of budget. None used on eBay UK or Facebook Marketplace on 1 November 2026 |

Not suitable: the StarTech HB30A4AIB (£32) takes all its power from the
laptop, and Atolla and Sabrent hubs are not known to switch port power.

**Recommended: the Amazon Basics HU3770V1.** It is the cheapest hub with a
different chip, a 12 V supply and power switching uhubctl is known to
handle. `usbpower.py` finds a hub by its ports, not its maker, so it should
work unchanged; the first night it goes on, cut the camera's power with
`./camera_test.py --power-cycle` and check the fan stops.

**With no hub,** the camera goes straight into a laptop USB-A socket. Plugged
in that way it has never dropped off USB, including three 720-frame runs on
the 3 m lead. The cost: nothing can cut its power there, so a jam means
pulling its lead. The Nano on a laptop socket can turn the focuser inward but
cannot lift the drawtube outward.
