# Why the 28BYJ-48 will not turn the 150P's focuser (research, 20 October 2026)

The problem: the 28BYJ-48 (5 V, ULN2003, Arduino Nano) on the AstroCosas
bracket ([thing 5468202](https://www.thingiverse.com/thing:5468202)) turns freely on the
bench, but on the Explorer 150P's focuser it does not turn the focuser at all,
even with the camera off and the focuser's lock/tension screw loosened.

How sure each point is:

- **[source]**: a page read in full, or a snippet quoted from one.
- **[snippet]**: seen only in a search engine's excerpt. Stargazers Lounge,
  Cloudy Nights, IceInSpace and Agena all returned HTTP 403 to the fetcher,
  so their threads could not be read in full.
- **[inference]**: worked out here from the figures, and unconfirmed.

## 1. The stock focuser: what it is and how it is adjusted

**What type.** No Sky-Watcher spec sheet was found that names the type for the
plain 150P. Retailers describe the PDS's focuser as a "2" dual-speed 10:1
Crayford" and sell it as a retrofit "for black Explorer-150/200/250/300
telescope models supplied with a 2" single-speed focuser", all with the same
85 × 78 mm hole spacing
([Robtics, SW_20241](https://www.robtics.nl/en/focusers/sky-watcher-2-dual-speed-crayford-focuser-for-explorer-models),
[deep-space-astronomy.ch, 150PDS EQ3 Pro](https://deep-space-astronomy.ch/en/product/sky-watcher-explorer-150pds-eq3-pro/)) [source].
So the 150P and the 200P have **the same 2" single-speed focuser** [source for the
shared mounting; inference that the mechanism is identical]. AstroCosas's own
description of the bracket calls the focuser's screw "the crayford adjustment
screw" [source, Thingiverse page metadata]. A Stargazers Lounge owner of a 200P
"realised the focus mech on the 200p body doesn't appear to be a rack type"
([SGL 246045](https://stargazerslounge.com/topic/246045-standard-focuser-mechanism-on-sky-watcher-200p)) [snippet].
An older IceInSpace post says an older 200P had rack and pinion [snippet].
**Best reading: the UK black 150P of c. 2015–2025 has a 2" single-speed,
Crayford-style friction focuser. A smooth shaft (here 4 mm) presses on a flat on
the drawtube, and pads or bearings opposite take the load. It has no rack and
no teeth** [inference, unconfirmed; to confirm, look under the focuser: a smooth
shaft means Crayford, a toothed rack means rack and pinion].

What follows from that: in a Crayford the shaft drives the drawtube only by
friction, and that friction comes from the same pressure that makes the
focuser stiff. Loosening the tension too far makes the shaft slip on the flat,
so the knob (or motor) turns and the tube does not move. Tightening it makes the
shaft hard to turn.

**Adjustments people describe** (mostly on related Synta focusers):

- The lock/tension screw sets the shaft's pressure on the drawtube. On a
  motorised Sky-Watcher focuser one owner found "a very fine balance on the
  tension adjustment screw ... too much and the motor can't turn it and too
  slack and the tube flops about" [snippet,
  [SGL 206987, Flextube 250PX auto focuser](https://stargazerslounge.com/topic/206987-skywatcher-auto-focuser-flextube-250px)].
- "On the basic SW focusers there are 2 tiny grub screws either side of the
  much larger locking knob", reached with a tiny Allen key by trial and error
  [snippet, [SGL 329202](https://stargazerslounge.com/topic/329202-adjusting-a-skywatcher-focuser)].
  The same thread names "the small hex screws on top of the focuser, either
  side of the large tension screw, and the four screws that hold the pinion
  onto the rack underneath" [snippet].
- A Cloudy Nights thread on these focusers: "It is common for these focusers to
  have some slop while being stiff. The first step is to adjust the 2 tiny
  setscrews on either side of the lock screw on top ... Disassembling the
  focuser, cleaning off the thick heavy grease and adjusting it during
  reassembly will improve it further. You can replace the pads with Teflon"
  [snippet, [CN 868318](https://cloudynights.com/topic/868318-focuser-upgrades)].
  Another found "overly tight pads ... focuser motion was very stiff"
  [snippet, same search].
- IceInSpace: check "that the teflon slides are flat & not twisted or doubled
  up ... The teflon & tube must be clean & dry. Do not lubricate with anything"
  [snippet, [IIS t-63438](https://www.iceinspace.com.au/forum/archive/index.php/t-63438.html)].
- On Sky-Watcher Crayfords the drawtube's flat can be slightly concave, so the
  shaft rides only on its edges; some owners flatten it with a fine stone
  [snippet, SGL search on 200P focusers].
- Astro-Baby's tune-up of the 1.25" Sky-Watcher focuser (the same principle):
  a felt or tension pad that has slipped, curled or gone missing jams the
  drawtube. Clean off the old grease with washing-up liquid, not solvents.
  Grease the rack and spindle lightly with lithium grease, and "DO NOT
  OVERTIGHTEN" the two plate screws
  ([astro-baby.com](https://astro-baby.com/Skywatcher%20Focuser%20Tune%20up/Skywatcher%20Focuser%20Tune-up.htm)) [source].
  On a Crayford, grease goes nowhere near the shaft or the flat it drives,
  because grease there makes it slip [inference, consistent with the
  IceInSpace "clean & dry"].

**Turning torque of a stock focuser.** No measured figure was found for any
Sky-Watcher focuser. This is the gap the spring-scale test below fills.

## 2. The 28BYJ-48's real torque

| Figure | Value | Where from |
|---|---|---|
| Pull-in torque (datasheet) | 300 gf·cm (about 29 mN·m) | KiaTronics-style sheet reproduced by resellers, e.g. [piekarz.pl](https://www.piekarz.pl/pdf.php?id=33958) [source] |
| Self-positioning torque | > 34.3 mN·m (about 350 gf·cm), at 120 Hz | same sheet [source] |
| Friction torque (gearbox's own drag) | 600–1200 gf·cm | same sheet [source] |
| DC resistance, 5 V version | 50 Ω ± 7 % per phase (sheet); 27 Ω measured on one sample, 71 Ω on a 12 V one | sheet; [splitflap wiki](https://github.com/scottbez1/splitflap/wiki/Motor-info) [source] |
| Measured, stock ULN2003 board | **300 gf·cm half-stepping, 380 gf·cm full-stepping (two coils on)** | [jpralves.net 2019](https://jpralves.net/post/2019/07/18/change-unipolar-28byj-48-to-bipolar-stepper-motor.html) [source] |
| Unpowered detent torque at output | about 630–650 gf·cm | [Arduino forum 575338](https://forum.arduino.cc/t/28byj-48-5v-stepper-100-rpm/575338) [source] |
| Speed limit at 5 V | about 12–15 RPM; under 3 ms per coil change it misses steps; about 120 steps/s for maximum torque | [Arduino forum 98946](https://forum.arduino.cc/t/28byj-48-stepper/98946), [Espruino](https://forum.espruino.com/conversations/291438), [advpistepper](https://advpistepper.readthedocs.io/en/latest/_modules/advpistepper/driver_unipolar_28byj48.html) [snippets/source] |
| Current | about 160–240 mA per phase quoted; an external 5 V supply recommended | [zbotic](https://zbotic.in/28byj-48-stepper-motor-with-uln2003-driver-complete-tutorial/), [circuit.rocks](https://docs.circuit.rocks/motors/28byj-48/) [snippet] |

- **12 V version.** It looks the same and carries a different label. At 5 V
  it gets roughly 40 % of its current (71 Ω against 27 Ω), so a 12 V motor
  fed 5 V is far weaker. Builders who changed "to a 12V version which seems to
  have better torque" ran it at 12 V (splitflap wiki) [source; the 40 % is
  inference].
- **Bipolar mod.** Cut the red common's trace, drive the four ends from an
  A4988 or DRV8825 at a higher voltage. It is widely said to give "more
  torque" ([Hackaday](https://hackaday.com/tag/cycloid/),
  [SGL 276410](https://stargazerslounge.com/topic/276410-converting-28byj-48-stepper-to-bipolar-for-microstepping/),
  [OpenFlexure](https://openflexure.discourse.group/t/stepper-motor-driver-boards-base/351/7)),
  but **no measured before-and-after figure was found**, one forum poster
  argues the gain at the same power is nil, and the A4988's current setting is
  too coarse for these small windings
  ([Arduino 978085](https://forum.arduino.cc/t/driving-28byj-48-with-a4988/978085)) [snippet].
  Unconfirmed as a fix.
- **Half-step against full-step.** Two-coil full-stepping gives about 25 %
  more torque than half-stepping (380 against 300 gf·cm, jpralves) [source].
  This project's firmware half-steps (`firmware/focuser/focuser.ino`,
  `HALF[8]`), at 20 ms a half-step. That is already slow enough. Speed is not
  the limit, but a full-step mode would add torque [inference].

**What the figures say about a focuser** [inference]. 300 gf·cm on a 4 mm shaft
(2 mm radius) is about 1.5 kgf of push at the drawtube if nothing slips. That
is enough to lift a 0.5 kg camera with room to spare. So when it does not turn
at all, the cause is the tension and friction, or the mechanics or the supply,
and not the camera's weight. As a test at the knob: at a 15 mm knob radius,
300 gf·cm is only about **200 g of force at the knob's rim**. A focuser that
takes more than that by hand is beyond this motor.

## 3. Others with the AstroCosas bracket or similar builds

- **AstroCosas himself** (200/1000): it "worked perfectly ... if the camera is
  not a heavy one". To fit it, "unscrew one of the wheels of the focuser,
  unscrew the holder screw and place this thing. Secure it with the holder
  screw." The newer version adds "another hole ... so the crayford adjustment
  screw can be accessible without need of removing this thing". He used
  MyFocuserPro2 (thing page metadata) [source]. In the video's description
  ([YouTube IO5pJn0p9ok](https://youtu.be/IO5pJn0p9ok?t=227)): "Al enfocador le
  cuesta un poco si tiene mucho peso, creo que voy a tener que ponerle una
  reducción o cambiar el tipo de motor por uno con más potencia" (the focuser
  struggles with much weight; I think I'll need a reduction or a more powerful
  motor) [source].
- **Two things to check from that** [inference]:
  - the bracket is clamped by a focuser screw. If that screw (or the one it
    replaces) is the shaft's tension screw, tightening it to hold the bracket
    firm also tightens the focuser;
  - the bracket only replaces one knob, so the motor and the focuser shaft
    have to line up. A rigid printed coupler on misaligned shafts binds.
    `docs/focuser.md` already records that "the printed coupler bound" once.
- **A user with a similar setup** on element14: the motor was too weak to turn
  the focus, and even a smaller (reducing) gear only "barely" turned it
  ([element14 29092](https://community.element14.com/products/arduino/f/arduino-forum/29092/wich-stepper-motor-is-the-right-for-my-project)) [snippet].
- **Sky-Watcher's own focus motor** is said on SGL to be meant for Crayfords and
  not their rack-and-pinion Newtonian focusers; one retailer says it is "not
  suitable for Newtonian" [snippet]. No reports of it on the black single-speed
  Explorer focuser were found.
- **Couplers on small shafts.** Grub screws dig in and flare the shaft
  ([ZWO forum](https://bbs.zwoastro.com/d/15242/4)). A coupler should engage the
  flat ([Arduino 918116](https://forum.arduino.cc/t/shaft-coupler-question/918116)).
  A printed 5 mm-shaft focuser coupler gave "a lot of slipping" when not
  tight ([Printables 1473565](https://www.printables.com/model/1473565-dual-speed-focuser-for-5-mm-shaft-51))
  [snippets]. A printed coupler with one grub screw of two, on a round 4 mm
  shaft, is a likely slip point [inference].
- **Stronger drives people use.** A belt or gear reduction on the
  28BYJ-48 (element14 and AstroCosas, above). Commercial kits with a NEMA-type
  stepper and gearbox: Pegasus Motor Focus Kit v2 at 60 N·cm pull-in, about
  20 × the 28BYJ-48
  ([Agena](https://agenaastro.com/pegasus-astro-motor-focus-kit-v2-with-universal-l-bracket-requires-controller.html)),
  and ZWO EAF (1:128 reduction, 5 kg payload,
  [EAF manual](https://i.zwoastro.com/zwo-website/manuals/EAF_Manual_EN_V2.4.pdf)) [source].
  myFocuserPro2 supports NEMA 17 with gearboxes on DRV8825 boards
  ([sourceforge](https://sourceforge.net/projects/arduinoascomfocuserpro2diy/));
  the specific 5:1 and 27:1 gearbox recommendations were not confirmed in
  this search.

## 4. Diagnosing a motor that will not turn the focuser at all

In order, cheapest first:

1. **Which joint does not move.** Draw marks across the motor shaft, the
   coupler and the focuser shaft (as `docs/focuser.md` already says). If the
   motor shaft turns and the coupler does not, the coupler is slipping. If the
   coupler turns and the focuser shaft does not, the grub screw is slipping. If
   all three turn and the tube does not move, the Crayford shaft is slipping
   on the drawtube flat (too little tension, or grease on the flat). If nothing
   turns and the motor hums or buzzes, it has stalled. If it is silent and
   cold, it is not getting power.
2. **Measure the focuser's torque by hand, motor off.** Take the motor off and
   tie or tape a thread round the bare knob (or the shaft, through a known
   radius) and pull with a luggage or spring scale, or hang a bottle and add
   water until it turns. Torque = force × radius. Do it with the camera off and
   on, tension as set. Compare with the motor's 300 gf·cm half-stepping
   (about 200 g at a 15 mm knob rim, or 1.5 kg on the 2 mm-radius bare shaft).
   If the focuser needs more, no wiring fix will do; reduce the friction or
   gear the motor down [method: inference from the datasheet figures].
3. **Is the bracket tightening the focuser?** Fit the bracket and screw, motor
   uncoupled, and turn the other knob by hand. If it is stiffer than without
   the bracket, the bracket's clamping screw is loading the shaft
   [inference].
4. **Alignment.** Loosen the coupler's grub screws and see whether the two
   shafts sit on one line without force. If the coupler has to bend to fit,
   it binds. A flexible (spring or jaw) coupler fixes that [inference].
5. **Supply.** The Nano's 5 V pin on USB is about 4.5–4.6 V after its Schottky
   diode (0.3–0.4 V drop;
   [Arduino 688477](https://forum.arduino.cc/t/arduino-nano-5v-pin-doesnt-give-me-5v/688477)),
   and the ULN2003's Darlingtons drop about 1 V more (datasheet up to 1.5 V)
   [source/snippet]. That leaves the coils about 3.5–3.7 V, or roughly 70–75 %
   of the current and torque the 5 V rating assumes [inference]. USB 2.0 gives
   500 mA. Two coils at about 200 mA fit, but only just. Measure the voltage
   at the ULN2003's + pin while the motor holds; feed it from a separate 5 V
   supply of at least 1 A, with grounds joined.
6. **Is it the 12 V motor?** Read the label. A 12 V 28BYJ-48 on 5 V is very weak
   (section 2).
7. **Step rate.** At 20 ms per half-step this firmware is about 0.7 RPM, far
   below the 12–15 RPM limit, so speed is ruled out. Full-stepping with two
   coils on would add about 25 % torque [source jpralves; applying it here is
   inference].

## Likely causes, most likely first [all inference from the above]

1. **Too much friction in the focuser** for a 300 gf·cm motor: tension, the two
   small grub screws beside the lock screw, old heavy grease, a pad that has
   slipped or doubled. The bracket's clamping screw may add to it. Fix: set
   the screws so the drawtube just holds the camera, clean the old grease out,
   check the pads, and keep the shaft and flat dry. Then measure it (step 2).
2. **The coupler slipping or binding.** One grub screw of two on a round
   4 mm shaft, or the two shafts out of line. Fix: both grub screws, a flat
   filed on the focuser shaft (or a D-profile coupler), or a flexible metal
   5 × 4 mm coupler.
3. **Weak supply.** Nano 5 V pin on USB, then the ULN2003 drop. Fix: a
   separate 5 V supply of 1 A or more to the ULN2003.
4. **The motor is simply too small** once the focuser is set to hold a camera.
   Its own designer says it struggles with weight. Fix: a 3:1 to 5:1 printed
   gear or GT2 belt reduction, the 12 V version at 12 V, or a NEMA 14/17 with
   a gearbox on a DRV8825 or TMC driver. The bipolar mod's gain is unproven.
