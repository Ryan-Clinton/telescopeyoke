+++
title = "Free Astrophotography Software: What Actually Works?"
kind = "build"
summary = "The second round of measured tests of the free processing tools, run by TelescopeYoke's AI: where GraXpert and Dark Star held up, where Dark Star didn't, why my own stretch stayed, and two fixes that failed their final test."
targets = ["NGC2174"]
topics = ["stacking", "telescopeyoke"]

[[images]]
file = "free-tools-star-removal.jpg"
alt = "Three fields, left to right: the original, TelescopeYoke's plain star removal, and Dark Star used only on the stars"
figure = true
+++

I wanted TelescopeYoke to use the best free image-processing tools rather than reinvent them, and I wanted that decided by measurement, not by which picture looks nicer. I don't have the background to judge that myself, so I asked the AI that runs TelescopeYoke (Claude) to do the testing, and had ChatGPT review its work as it went. What follows is what they found, written up from their records. The first round, on my own stacks, is in [the 23 November entry](../2026-11-23-testing-the-free-tools/).

## Why there was a second round

The first round picked GraXpert for noise reduction and Dark Star for star removal, and kept TelescopeYoke's own stretch, background and colour. But it was all measured on one telescope's stacks. The question for the second round was whether those choices still stood up on a much bigger and more varied set of data, with the rules made stricter as it went.

That data was finished stacks from 17 collections and raw frames from two other cameras, shared with the project, plus a few stacks kept completely untouched until the very end. It isn't ours to pass on, so none of it is named or shown here, and the comparisons are described only in numbers.

## How the work was judged

The method is the same as in the first round, and it's the part I'd most want a reader to take away:

- **Planted truth.** Faint artificial lines and glows are added, at known strength, to copies of real stacks. Afterwards you can measure exactly how much of them a tool kept, which you can't tell from looking at a picture.
- **A pass mark set first.** Each test had a written rule before it ran, such as "keep a planted faint line to within 5 points of TelescopeYoke's own code".
- **Data nothing was tuned on.** When a tool's settings or a fix were adjusted, the result was judged again on data that hadn't been used to adjust it. A final set was kept back, opened once, and not adjusted against afterwards.
- **Failures stay in the record**, even if a later version passes.

One honest note on that last point: the rules weren't all fixed at the very start. The second star-removal rule below was added after the first big run showed the original rule wasn't enough. It was fixed before any later checks, but it wasn't part of the original test.

## Noise reduction: GraXpert, and what was and wasn't re-tested

GraXpert's win comes from the first round, where it was the strongest single result. Each tool was compared at the same remaining grain, against an independent stack made from different frames:

| Method | Planted filament kept (at half the grain) | Error against an independent stack (blur = 1.000) |
|---|---|---|
| **GraXpert 3.0.2** | **88.5%** | **0.971** |
| DeepSNR 1.3.2 | 89.1% | 0.974 |
| Cosmic Clarity (AI3.6) | 85.9% | 0.985 |
| TelescopeYoke's own trained model | 84.1% | 0.984 |
| Siril NL-Bayes | 76.0% | 1.017 |
| Seti Astro Suite Pro AI4 | 65.3% | 1.027 |

GraXpert beat the denoiser TelescopeYoke had trained for itself, at every noise level. That model has since been retired. DeepSNR kept a fraction more of the filament, but GraXpert was closer to the independent stack every time, so GraXpert won on both together.

The second round did **not** repeat this comparison: finished stacks have no independent half to judge against. GraXpert was used as the standard noise-reduction step in everything that followed, but that isn't new evidence that it's the best denoiser.

## Star removal: Dark Star, strong on most fields, not on crowded ones

![Three fields, left to right: the original, TelescopeYoke's plain star removal, and Dark Star used only on the stars](../img/free-tools-star-removal.jpg)

TelescopeYoke uses Dark Star (in Seti Astro Suite Pro) only where stars are actually found, and keeps the original image elsewhere. Used on its own, Dark Star took faint nebula with it. Each star is decided once for all the filters.

In the second round this ran on every filter of the 17 collections: 53 stacks. Some of those are colour stacks split into their red, green and blue, so they aren't 53 independent cameras. It was judged by two rules:

| Rule | Passed |
|---|---|
| Keep a planted faint line to within 5 points of TelescopeYoke's own code | **53 of 53** (median 100% kept, against 16% for the old code) |
| Remove the stars: no more than 10 points more left than the old code | **52 of 53** overall |
| The same, for the hardest tenth of the stars | **46 of 53** |

So it keeps faint detail extremely well and removes typical stars well: a median 0.2% of the stars left, against 1.1% for the old code. But it isn't reliable on crowded fields with bright nebula behind the stars: the Tarantula, M42 and NGC 7822. On one Tarantula stack it removed almost nothing.

The AI checked whether that was Dark Star or TelescopeYoke's blending, since its own records keep both. In the Tarantula, Dark Star's raw output already leaves the stars, so it's the model. In M101 it's the other way round: Dark Star removes them, and TelescopeYoke's blend puts a share back. That part is TelescopeYoke's to fix. The model's weights aren't open, so for crowded fields the only levers are what it's given (its tiling, its stretch, its mode) or a report to its author.

TelescopeYoke's red, green and blue pictures don't use Dark Star at all yet, so the broadband results test a step that isn't in use for those pictures.

## Stretching: TelescopeYoke's own, by the measure that was chosen

The stretch decides how much faint nebula you can see above the grain. Each stack went in beside a copy with faint lines planted in it, and the measure was how far those lines stand above the grain afterwards. Higher is better:

| Method | Faint lines over the grain (53 stacks) | Bright detail kept |
|---|---|---|
| **TelescopeYoke's own** | **10.1** | 0.0084 |
| Siril autostretch | 5.4 | 0.0130 |
| Siril GHS | 5.7 | 0.0052 |
| Seti Astro statistical stretch | 5.4 | 0.0138 |

TelescopeYoke's stretch scored higher on that measure in all 53 stacks, as it did in the first round. Siril's autostretch and Seti Astro's stretch keep more bright detail, though. The sky levels weren't matched either: TelescopeYoke's puts the sky near black, the others at 0.25. So the fair conclusion is narrower than "better": under the automatic-processing rule chosen, TelescopeYoke's stretch stays.

Sharpening, backgrounds and palette weren't re-tested in the second round. The first round's results for those stand (see 23 November): nothing sharpened real detail, and TelescopeYoke's own background and palette stayed.

## The failures that changed the conclusions

The two most useful lessons came from things that failed.

**A crowded field can beat a star remover that passes everything else.** Dark Star's 53 out of 53 on faint detail hid the fact that it sometimes doesn't remove the stars at all. Only adding the second rule showed it. A tool can score perfectly on keeping detail by doing nothing.

**Faint nebula can look exactly like a stacking fault.** Five of the 17 collections' pictures had edge faults. Three of those were areas only some frames had reached, which are noisier than the rest. The AI built a fix that found those areas by their extra grain, left them out of the sky model and cropped them off. On the pictures it was built on, it fixed two and nearly fixed the third, and spoiled nothing else. Then came the one-time test on six stacks kept back for it. Two of the six couldn't be read at all. Of the four that could, none had the fault, and on two the fix did harm. In Thor's Helmet, faint nebula filling the frame looked just like a thinly covered edge, and the picture lost the helmet's outer wings. So the fix wasn't adopted, and the failure stays recorded. You can't tell the two apart from the picture alone. TelescopeYoke's own stacks avoid the problem, because they record where every frame reached.

## What TelescopeYoke learned about itself

- **Hot-pixel cleaning.** The cleaning that removes cosmic-ray hits passes all 11 of my own sessions. On very sharp data, with stars two or three pixels across, a star's centre looks like a hit and gets partly rubbed out: up to 19% of the brightest stars' light on one camera, far more on the sharpest. The AI tried eight replacements. None met every requirement, so the cleaning wasn't replaced. The closest one checked whether a star is also there in other frames, which kept every star's light, but let a few extra hits through on one of my crowded nights.
- **One-frame sources.** Anything that appears in one frame only, such as an asteroid, a flare or a new star, loses some light to the cleaning: typically 2%, and up to about 24% in the worst frames measured. That matters for discovery work on single frames, and it's a known limit now rather than an unknown one.
- **Two faults fixed.** Colour cameras' frames were stored in a format where a saturated pixel became infinity; they're now capped instead. And two picture options did nothing for red, green and blue pictures while the file name said they'd been used. They're now refused there, not made to work.

## What this does and doesn't show

These are measurements of each tool as released, run automatically at its defaults or as TelescopeYoke drives it. Someone skilled working by hand may well get more out of any of them. What the work shows is which tools, run that way, measurably beat TelescopeYoke's own code at each step. GraXpert did for noise reduction. Dark Star did for star removal on most fields, but not the most crowded. Nothing beat TelescopeYoke's own stretch, by the measure chosen.
