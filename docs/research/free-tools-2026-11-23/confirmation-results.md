# Confirmation results

Against the protocol fixed in `confirmation-protocol.md`; every deviation is in `deviations.md`.

## Step 1: hot-pixel and cosmic-ray cleaning, set 76 (QHY Minicam8M, 2.9 um, 348 mm, 600 s)

The protocol's run, stacked as `restack.py` stacks (binned 2x2, as `processing_scale = 2`):

| Session | Brightest-third flux, new / old cleaning | Peak, new | Grain, new | Visible cosmic pixels, new / old | Verdict |
|---|---|---|---|---|---|
| Ha, 10 October 2025 | 0.574 / 0.301 | 0.304 | 0.995 | 10 / 1 | **fail** (flux, peak) |
| Ha, 2 November 2025 | 0.911 | 0.875 | 0.987 | 120 / 179 | **fail** (flux, peak, grain) |
| OIII, 10 October 2025 | 0.171 | 0.168 | 0.996 | 2 / 2 | **fail** (flux, peak) |
| OIII, 29 October 2025 | 0.936 | 0.867 | 0.969 | 56 / 51 | **fail** (flux, peak, grain) |

**All four fail.** The old cleaning cut the stars further on every session where both were measured.

A diagnosis afterwards, not a verdict: the same first-night sessions at full resolution (no 2x2
binning). Binned, this camera's 1.72"/px becomes 3.44"/px and its stars' median width 1.8 px, so a
core is one pixel and both cleanings take it for a defect. Unbinned (median width 3.6 to 6.3 px):

| Session | Brightest-third flux, new / old | Peak, new / old | Verdict by the same mark |
|---|---|---|---|
| Ha, 10 October 2025 | 0.984 / 0.650 | 0.941 / 0.426 | would fail (flux, peak) |
| OIII, 10 October 2025 | 1.000 / 1.000 | 1.000 / 1.000 | would pass |

So most of the loss is the binning: the cleaning was made on this project's 183M at 750 mm, whose
binned stars are 2 to 3 px wide. On a rig whose binned stars are near 2 px, `processing_scale = 2`
undersamples them and the cleaning cuts their cores; even unbinned, the new cleaning took 1.6% of
the Ha stars' light, outside the 0.5% the mark allows. Nothing in the code is changed for this
here: a rig with fine pixels and short focus is the case to fix next, and the fix is checked on data
not yet read.

## Step 4: field widths, decided before any picture is made (25 November 2026)

From each stack's own header (plate solve, or focal length and pixel size), or the owner's stated
focal length where the header has neither. Wider than 3 degrees gets `--background level`.

| Set | Scale ("/px) | Field (deg) | Background |
|---|---|---|---|
| 07, 18 (2600MC at 363 mm, drizzled) | 1.01, 2.01 | 3.5 | level |
| 40 (D5500, 70 mm) | 11.6 | 15.6 | level |
| 44 (Bortle 8) | 3.67 | 3.9 | level |
| 72 (R50, Askar 80ED with 0.7x, stated) | about 1.8 | about 3.1 | level |
| 29, 31, 37, 74 (533MC, 400 to 750 mm) | 0.55 to 1.1 | 0.9 to 1.7 | auto |
| 28 (8" Dobson, 1200 mm, stated) | about 0.6 | about 0.5 | auto |

The rest, from their XISF headers or the owners' stated rigs (their TIFFs are not read by Pillow):

| Set | Scale ("/px) | Field (deg) | Background |
|---|---|---|---|
| 43 (533MC, RedCat 51, 2x drizzle, 10350 px) | about 1.55 | about 4.5 | level |
| 49 (2600MC at 370 mm) | 2.1 | 3.6 | level |
| 56 (D750 at 360 mm, stated) | about 3.4 | about 5.7 | level |
| 57 (D5300 at 300 mm, stated) | about 2.7 | about 4.5 | level |
| 65 (D7000 on a Z73 at 440 mm, 2x drizzle, stated) | about 1.1 | about 3.1 | level |
| 41 (2600MC on a 90 mm at 540 mm, stated) | about 1.4 | about 2.5 | auto |
| 78 (533MC at 249 mm) | 3.1 | 2.6 | auto |

## Step 1 on a colour camera (raw 2600MC Pro at 1000 mm, Bortle 2, no darks)

| Session | Brightest-third flux, new / old cleaning | Peak, new / old | Stack star width (px) | Verdict |
|---|---|---|---|---|
| Abell 1656 | 0.943 / 0.573 | 0.819 / 0.361 | 3.47 | **fail** (flux, peak) |
| LBN 552 | 0.970 / 0.498 | 0.926 / 0.364 | 3.12 | **fail** (flux, peak, cosmic) |
| M81 | 0.997 / 0.673 | 0.978 / 0.470 | 3.65 | **fail** (peak) |
| NGC 7293 | 1.000 / 0.738 | 1.000 / 0.542 | 3.71 | **pass** |

Three of four fail. The losses are real: leaving out every measured star whose centre is a lone
spike in the uncleaned stack (deviations 5 and 6) left out none, so the measured stars are stars, not
the sensor's hot pixels. **The cause is not found.** Undersampled single frames were the first guess, and they do not fit:
measured in single frames (median width of the stars found, px at the stacking scale), this
project's sessions run 2.5 to 4.9 and all pass, M33's R at 2.5 among them; set 76's run 2.7 to 3.6
and all fail, its OIII of 10 October at 3.6 losing 83%; the colour camera's run 3.2 to 4.1, M81 at
4.1 failing. So frame width does not separate passes from fails. What both other cameras' data has
and this project's does not is no dark frame; whether that, the flats, or something in the frames
themselves is the cause is the next thing measured, pixel by pixel in single frames.
This project's 183M at 750 mm (1.3"/px binned) passed all 11 of its sessions.

## Step 4: artefacts in the 17 pictures (colour.py's defaults, read by eye on 25 November 2026)

Every run ended with exit 0. Each picture was looked at whole for tiles, edges, rings and gradients.

| Set | Verdict | What is wrong |
|---|---|---|
| 07, 18, 29, 37, 40, 43, 49, 56, 74 | **pass** | nothing seen |
| 78 | **pass** (no artefact) | M42's core burnt out: needs HDR, a known gap |
| 31, 44 | pass, just | a thin red line down the left edge; 44 also a lighter band along the top |
| 28 | **fail** | the stack's footprint left in: dark wedges at the four corners, a green gradient along the bottom |
| 41 | **fail** | a purple gradient in the bottom-right corner, and an arc along the bottom edge (the Foraxx stretch of the same stacks has neither) |
| 57 | **fail** | a diagonal band down the left third, and an orange glow in the bottom-right corner |
| 65 | **fail** | a strip along the top with another background level from the rest |
| 72 | **fail** | dark round holes in the sky (two plainly, more faintly), and the Rosette hardly shows |

Five of 17 fail, all at the edges or in the sky model: the background step (28, 41, 57, 65, and 72's holes
round what may be dust motes) rather than the colour or the stars. Next: the sky model's edge handling and
what it does with a stack whose frames did not all cover the field.

### The stack's rejection is not the cause (clipmean, 25 November 2026)

Diagnostic, not a verdict: Abell 1656's 40 frames with each layer a plain mean (no rejection). The new
cleaning against none: brightest-third flux 0.945, peak 0.819, the same as through the clipped stack
(0.943, 0.819). So the light is lost before stacking, in each frame's cleaning as the harness applies it,
although the shipped rule alone touches only 9 pixels in a frame's 60 brightest stars. Next: one frame cleaned
and not, star by star, through the harness's own per-frame path (`clip3.frame`).

Found on the way: the harness keeps colour frames as float16, as `stacking.store_dtype` does, and 1,100
pixels per plane passed float16's 65504 and became inf (saturated stars over their flat). The plain mean
spread them until the stars could not be measured. The shipped store had the same hole; `register_file` now
keeps such a pixel at 65504. Not yet seen in a real restack.
