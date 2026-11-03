# One forecast against four, 3 November 2026

At about 23:00 the outlook said the clear spell was one hour, 23:00-00:00,
too short to set up for. ryanclinton.uk's Meanwhile page, which compares
four forecasting centres, said 01:00-06:00.

## Why they disagreed

- **Two different places.** The Meanwhile page was worked out for
  Portstewart (55.2, -6.7: where the visitor's connection appears), about
  15 km from the garden (55.07, -6.50). Its forecasts were fetched at 21:26
  and kept for 3 hours.
- **One model against four.** The planner used Open-Meteo's default
  forecast, and at the garden that is exactly the Met Office's
  (`best_match` and `ukmo_seamless` gave the same figures every hour). The
  Meanwhile page counts an hour clear when at least half of the Met Office,
  ECMWF, DWD ICON and NOAA GFS call it clear.
- **The same rule for an hour.** Both call an hour clear at 30% cloud or
  less, dry and without fog, with the planner's fog rule (Meanwhile imports
  it). The rule was not the difference.
- **The forecast moved.** The 23:38 refresh of the Met Office's forecast
  gave 03:00-05:00 instead of 23:00-00:00.

## The hours, fetched 23:45 for the garden

Cloud %, and C where that centre calls the hour clear:

| hour | default (= Met Office) | ECMWF | ICON | GFS |
|------|------------------------|-------|------|-----|
| 22:00 | 52 | 59 | 75 | 54 |
| 23:00 | 9 C | 44 | 76 | 11 C |
| 00:00 | 83 | 30 C | 1 C | 74 |
| 01:00 | 77 | 19 C | 16 C | 10 C |
| 02:00 | 93 | 9 C | 13 C | 9 C |
| 03:00 | 30 C | 3 C | 56 | 9 C |
| 04:00 | 1 C | 2 C | 42 | 37 |
| 05:00 | 63 | 6 C | 31 | 12 C |
| 06:00 | 61 | 8 C | 50 | 11 C |

No centre forecast fog at the garden (visibility 12-33 km). From 00:00 to
03:00 the Met Office stood alone against three centres calling it clear.

## What changed

The planner now fetches the four centres too (`feeds.weather_centres`)
and takes the clear spell from the hours at least half of them call clear,
as the Meanwhile page does. It says when that differs from the default
forecast ("forecasts disagree: ..."), and a night is GO only when at least
three of four agree in every hour of the spell; a two-two split stays
MARGINAL. With the centres unavailable, the one forecast stands as before.

What the sky really did is still to be recorded in the night's notes.
