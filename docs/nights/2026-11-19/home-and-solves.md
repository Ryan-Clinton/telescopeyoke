# Home, polar alignment and plate-solve speed: 19 November 2026

Clear sky from about 17:25 UT, the 183M held at -5.0 °C by the camera
keeper throughout (never stopped), the mount through the SynScan Wi-Fi
adapter. First real runs of the changes of 19 November (commits 13bb372 to
f06ea8f).

## Plate solves

| Run | Frame | Preparing | Solving |
|---|---|---|---|
| Before (18 November, full sensor) | 1.5-3.6 s | 1.5-1.6 s | 0.2-0.3 s |
| Binned 2x2 through the keeper (GoTo NGC 7789) | 4.6-4.7 s, 2.8-3.0 s of it switching the binning | 0.2 s | 0.1 s |
| Full sensor, hot pixels done alone (GoTo M52, then every run below) | 1.7-1.9 s | 0.9-1.0 s | 0.2-0.3 s |

Binning costs more than it saves through the keeper, so it is off
(`solve_binning` defaults to 1).

## Settling by the picture

No fixed 10 s wait: each picture 2 s after the slew, taken again while its
stars were trailed. NGC 7789 centred in three solves (64.2'/48.8', 15.2',
1.1'), M52 in two, 7 s apart (12.5'/11.5', 0.3'), with no picture retaken.
In each eight-place findhome one picture was retaken; settling took 16 s
over eight places where it took 80 s.

## Polar alignment

`./polaralign.py --step 12` from M52 (25° would have looked behind the
skyline in the north-east): pictures 13 s apart; the polar axis 0.2° from
the pole (0.3° east, 0.1° high), left. Its home warning: at least 0.2° on
the Dec axis, nothing to say on RA. findhome then found 0.52° and 1.11°:
the warning's lower bound held.

## findhome, truehome, the check

| Step | Home (RA axis, Dec axis) | Places' scatter | Time |
|---|---|---|---|
| findhome, 8 places | +0.52°, +1.11° (±0.07°, ±0.06°) | 0.06° | 161 s of slews, settling and solves |
| truehome by the board's own moves | arrived; home recorded at counts 8381998, 8374524 | | |
| findhome --check, 4 places | -0.03°, +0.00° | 0.04° | 118 s |
| findhome, 8 places, after | -0.11°, -0.04° (±0.03°, ±0.03°) | 0.03° | 183 s |

The check and the full measurement after it differ by 0.08° on the RA axis:
the check holds the tube's squareness and the polar axis at the first
findhome's, and the full one fits them again. Home is now about a tenth of
a degree out (17 October's second findhome: 0.19° and 0.05°). Not moved
again; the joints are not yet marked.

## The second test: home set well out by eye (18:13-18:33 UT)

After the balance, home was set by eye and recorded (`sethome`). The first
findhome solved only two places: every west place looked into the
next-door house, since the tube was 14° below where it was planned, and
through haze several 1 s frames showed too few stars. With the survey
aiming past the error already measured and a 4 s retry:

| Step | Home (RA axis, Dec axis) | Places' scatter |
|---|---|---|
| findhome, 7 of 8 places | +7.79°, +14.00° (±0.05°, ±0.06°) | 0.04° |
| truehome by the board's own moves | arrived; recorded at counts 8283039, 8196543 | |
| findhome --check, 4 places, no fixed wait after the slews | -0.00°, -0.01° | 0.06° |

The board's moves took out 7.8° and 14° and the sky agrees to a hundredth.
No picture taken straight after a slew was trailed.

## Where the time goes, and what changed for it

Each place's slew, settle and solve times are now kept (`slew_s`,
`settle_s`, `solve_s`, `trailed_frames`) and summed at the end of a run.

| Part | Before | 19 November |
|---|---|---|
| Wait after a slew | 10 s fixed (5 s in polar alignment) | none: the picture is retaken only while its stars are trailed (median roundness under 0.5) |
| One plate solve | 3.5-5.5 s | about 3 s: the hot pixels are put back at those pixels alone (1.9 s to 0.09 s, the same picture) |
| A 1 h step between places | | 8.7 s |
| The swing over the pole | | 48 s, once per survey |
| A full findhome, clear sky | 15 minutes planned | 161-183 s |

Tried and not kept: plate-solve frames binned 2x2, which cost 2.8-3.0 s a
picture switching the binning through the keeper (`solve_binning = 2`
turns it back on). Not worth it: shorter exposures or video mode for the
solves, which would save about a second at most while the slews are three
quarters of the time.

Made after these runs and tried only in the demo (578bbf1): a survey
starts on the side of the meridian the tube is on, its GoTos skip the
catch-up move, and every GoTo looks for its end four times a second. The
next findhome's slew times show what they save.

Owed: the joints to be marked at this home; the skyline survey again by
day, since the tube moved up its rings on 17 November.
