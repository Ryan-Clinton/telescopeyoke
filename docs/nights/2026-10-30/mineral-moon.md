# The first mineral Moon, 30 October 2026

Three colour videos of the 80 %-lit waning Moon, 57° up, from the night of
29 to 30 October: 01:55 (1018 frames, overexposed), 02:11 (1000) and 02:18
(495), 8-bit, gain 100, about 7 ms, no flat. Made with
`./ty lucky mineral frames/lucky/Moon-20261030-015546.ser ...-021112.ser ...-021837.ser`
at the standard strength (15 times).

| | |
|---|---|
| Colour as measured | strongest 1 % at 2.5 %, spread 0.85 % (blue against orange) |
| Clipped | 54 % of the 01:55 video's disc, 0.2 % of each other |
| Agreement, two by two | 0.34 and 0.29 with the overexposed video; 0.80 between the other two |
| Orientation found | up 213° east of north, not mirrored (south up, as a Newtonian gives); uplands 1.4 times the seas' brightness |
| Under us / under the Sun | 5.0° S 2.0° E / 1.4° S 51.5° W |
| Tranquillitatis bluer than Serenitatis | agrees, by 2.0 %, 11.3 standard errors |
| Tranquillitatis bluer than the uplands | agrees, by 2.3 %, 3.3 standard errors |
| Confident (green) | 46 % of the usable disc |

The first tries that morning showed why each step is there:

- **No colour balance.** The stacks came out green (red 116, green 147,
  blue 93 on the disc).
- **The overexposed video.** It turned the bright side magenta.
- **A slope across the disc.** Red against green rose 2.3 % from the
  terminator to the limb in every video, five times the minerals' 0.5 %.
- **The camera's green-magenta axis.** Turned up, it painted the uplands
  magenta and the seas green.

Caveats:

- These were 8-bit videos. The 0.5 % colours are about one step of 8 bits,
  and `./ty moon --mineral` now takes 16-bit ones.
- There was no flat.
- The overexposed video agrees poorly with the other two.

The check passing on this data says the blue and brown are where the
spacecraft put them. It does not say the strength of the colour is right.
