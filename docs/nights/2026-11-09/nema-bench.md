# 9 November 2026: the NEMA 17 drive on the bench, not yet turning both ways

Written up the next day for an outside review. The motor was on the bench, not
on the focuser. Short version: the firmware and wiring are proven as far as a
Nano can prove them. The first TMC2209 was ruined by a wrong seating
instruction. The spare turns one way only. The A4988 can't run on this
carrier. Two BigTreeTech TMC2209 V1.3s are on order. The running notes are in
[focuser.md](../../focuser.md) under "9 November 2026, wiring the drive". This
file is the full sequence, with the evidence and the open questions.

## The hardware

- **Motor:** 17HS4401 NEMA 17, 1.7 A rated. A 4-wire lead with a black
  4-pin plug.
- **Carrier:** a black A4988/DRV8825-style screw-terminal carrier.
  - Its socket's pins are labelled for an A4988.
  - It has a green 2-way terminal for the motor supply (VIN, GND).
  - The motor plug goes on 4 header pins, labelled 2B 2A 1A 1B left to right.
  - There are 3 microstep DIP switches, all off.
  - EN, STEP and DIR are on a separate 3-pin header.
  - There is no logic GND or 5 V pin beside them; the board makes its own logic supply.
- **Drivers:**
  - two unbranded TMC2209 StepSticks, bought with the carrier;
  - a red A4988 that came with the motor.
- **Nano:**
  - EN on D8, STEP on D9, DIR on D10;
  - its GND under the green terminal's GND screw, with the 12 V −;
  - USB to the laptop.
- **Supply:** 12 V 2 A plug-in supply, into the green terminal.

## The firmware (commit f898718)

`firmware/focuser/focuser.ino` drives STEP/DIR/EN. The details:

- **Units:** moves stay in the old 28BYJ-48's half-steps, 4096 to a turn.
  That keeps the travel and filter offsets valid. They are converted to 1/8
  microsteps, 1600 a turn, 25 for every 64, with the remainder kept.
- **Each move:**
  1. Set DIR, wait 1 ms.
  2. EN low, wait 200 ms (it was 5 ms at first).
  3. 10 µs STEP pulses at 5.12 ms apart for the default `:S2`.
  4. After the move, wait 50 ms, then EN high, unless `:H1` asked to hold.
- **`:V`:** reads millivolts on A2 against the Nano's 1.1 V bandgap. It
  replaces a meter for reading the driver's Vref. `./focuser.py vref` shows
  it live. A weak pull-up first tells a bare pin (`V -1`) from a real reading.

## What happened, in order

1. **Seating driver 1.** I told the user to seat the TMC2209 with its VM pin
   towards the VIN terminal. That was wrong for this carrier.
   - Seated that way, with 12 V on, the motor didn't hold.
   - Its Vref read 0.92 V, then 0.17 V.
   - Its pot's head was half stripped trying to turn it.

   It went in the right way with the driver's DIR end towards VIN. That
   was only how it looked on this board: the safe rule is to match the
   driver's VM pin to the hole joined to VIN (see the review notes below).
   Turned round, it read a steady 1.11 V (about 0.79 A by the
   BigTreeTech formula A = V × 0.71) and held the motor stiff. **It never
   stepped:** it turned nothing in any direction. Most likely it was damaged
   while it was backwards under 12 V.
2. **Spare driver**, seated the right way, Vref 1.28 V as it came (about 0.91 A).
   - The `+` direction turns every time.
   - The `−` direction only hums and clicks in place.
3. **Changed with no effect:**
   - order of the moves (+ first or − first);
   - step gap (2 or 20 ms a half-step);
   - wake time (5 or 200 ms);
   - holding the driver on between moves (`--hold`);
   - re-making the ground: Nano GND and 12 V − twisted together under one screw.
4. **Isolated:**
   - **Plug turned 180°:** the turning direction reversed. `+` still turned
     and `−` still hummed. So the fault follows DIR's level, not the motor's
     direction.
   - **DIR wire moved from D10 to the Nano's GND:** it hummed. So D10 is not
     the fault.
   - **DIR wire under the carrier's own GND screw:** it hummed. So the Nano
     and the ground link are not the fault.
   - **DIR fed straight onto the driver's own DIR pin**, bypassing the
     carrier's header: low still hummed.
   - **Continuity with the Nano** (A2 against GND, 12 V out, driver pulled):
     socket holes 3–4 are joined through one coil and 5–6 through the other,
     and 4–5 are not joined. So the carrier's motor tracks, the plug and both
     coils are right. Shorting each coil's pair made the shaft stiff, which
     confirms it.
5. **The A4988.** It can't run on this carrier as it stands:
   - the carrier grounds the socket position an A4988 uses for SLEEP (a
     TMC2209's CLK, grounded to use its own clock);
   - it leaves RESET floating;
   - so the A4988 sleeps.

   Its pot was turned to 0.31 V. Bending SLEEP and RESET out of the socket
   and feeding them 5 V from the Nano would work. The user declined that
   rework.
6. **Stopped.** Two BTT TMC2209 V1.3s are ordered from AliExpress, due
   about 15 to 18 November. An ANENG SZ308 meter is coming too, to
   cross-check the Nano's Vref readings.

## What is proven, and what isn't

| Part | State |
|---|---|
| Nano, D8/D9/D10, firmware stepping | Good: turns cleanly in `+` on the spare |
| Wiring and shared ground | Good: DIR tied low at the carrier still fails |
| Carrier motor tracks, plug, coils | Good: continuity and the shorted-coil test |
| Nano as a Vref meter (`:V`) | Steady, plausible readings (1.11, 1.28, 0.31 V); not yet checked against a meter |
| Driver 1 | Dead: holds the motor, never steps |
| Spare driver | Steps only with DIR high: most likely the driver, not proven (no pin voltages measured) |
| A4988 | Fine as far as known, but won't run on this carrier without rework |

## My mistakes

- **The seating instruction ("VM towards VIN") was wrong** and most likely
  killed driver 1. I gave it without checking this carrier's layout against
  the driver's pinout first.
- I left the DIR wire under the GND screw after one test without saying to
  move it back. The user caught it.
- I misread a photo as showing a red jumper cap. There was none.
- Before every move, I should have said what to watch and allowed time to
  hold a wire in place. Several runs were wasted because I didn't.

## Questions for the reviewer

1. **The spare's fault.** It steps with DIR high and only hums with DIR low,
   even with DIR driven directly at the driver's pin. Is that a known failure
   of cheap TMC2209 StepSticks? Or does it point to something the carrier
   does to a pin we haven't considered, such as:
   - the A4988 MS3 or RESET positions, which are the TMC2209's SPREAD and
     PDN/UART in some pinouts;
   - a pull-up or pull-down on DIR?
2. **The seating rule.** For a TMC2209 on an A4988-labelled carrier, is
   "DIR end towards VIN" a safe general rule? Or should the rule be "match
   the driver's GND and VM pins to the carrier's VMOT and GND rows",
   checked on both boards before power?
3. **The current.** Is 1.1 V Vref (about 0.8 A on a BTT V1.3) a sensible
   start for a 1.7 A 17HS4401 lifting a focuser with a camera and filter
   wheel, with the driver off between moves?
4. **The firmware.** Do the 200 ms wake before stepping, the 10 µs pulse
   and the 1 ms DIR setup look right for a standalone TMC2209? It would also
   be useful to know if dropping to EN high 50 ms after a move risks the
   drawtube slipping.
5. **The Nano Vref reader.** Is this sound: a bandgap-referenced ADC, the
   average of 16, with a pull-up test for a bare pin? Should the pot be read
   with the motor unplugged?

## After review, 10 November 2026

**Confirmed, from BTT's schematic and manual for the TMC2209 V1.2:**
- The pins' positions against the carrier's A4988 socket:
  - MS3 is PDN_UART;
  - RESET is PDN, unconnected as BTT ships it;
  - SLEEP is CLK.
- So the carrier's grounded SLEEP and floating RESET are right for a
  standalone TMC2209, and its third switch, off, leaves PDN_UART low.
- SpreadCycle is chosen by a resistor on the driver board, not a pin.
- The sense resistors are 0.11 Ω. I = Vref / √2 holds for BTT's boards only.
- The firmware's arithmetic checks out:
  - 25 microsteps per 64 half-steps, rounding down either way;
  - the gap: `stepMs` × 64/25 ms;
  - the bandgap: 1.1 V × 1023 × 1000 over the average reading.
- The 10 µs pulse and 1 ms DIR setup are well above the TMC2209's minimums.
  No code change.

**Hypotheses, not proven:**
- The spare driver's DIR input or logic is damaged. This fits everything
  seen, but no pin voltage was measured.
- A pin setting on the carrier: none of the fixed pins can explain a fault
  that depends on DIR's level.
- The unbranded drivers may not share BTT's pin order or resistors.
- The "200 ms for StealthChop to tune" in the firmware is a reasonable wait,
  not proof that it tuned.

**Neither TMC2209 is proven dead.**
- Driver 1 held the motor but never stepped.
- The spare steps only with DIR high.

They sat in the same socket, with the same switches and wiring, and behaved
differently. That points at the drivers, not the carrier. It still isn't
proof, because:
- the switch holes (MS1, MS2, MS3) haven't been checked for what they
  connect to with the switches off;
- nobody has asked a driver what it sees on its own pins.

**What would settle it:**
- **The switch holes, checked with the Nano.** 12 V out, driver out, Nano GND
  on the carrier GND, then `./focuser.py vref` with the A2 lead in each hole:
  - about 0 V is a hard ground;
  - an in-between reading is a resistor to ground;
  - "nothing on A2" is nothing there.
- **Ask the chip itself.** A TMC2209 reports the level it sees on each of its
  pins (DIR, STEP, EN, MS1, MS2, PDN_UART, SPREAD) through its own UART line
  (PDN_UART, the MS3 position). Reaching that pin means the driver comes out
  of the socket onto leads, so this waits for a go.

An A4988 working on the same Nano and motor wouldn't prove the TMC2209 at
fault: it bypasses the carrier's switch holes.

**My seating rule in this file was wrong as a rule.** The pins are matched by
continuity, VM to the VIN hole, before power. The commissioning steps are in
[focuser.md](../../focuser.md#the-nema-17-drive-not-yet-commissioned); they
replace the list that stood here.
