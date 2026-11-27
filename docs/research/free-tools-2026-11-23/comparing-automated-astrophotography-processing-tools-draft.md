# Comparing Automated Astrophotography Image-Processing Tools

**Draft technical report — 27 November 2026 · For review, not publication**

## Summary

I compared freely available astrophotography image-processing tools with the existing processing in TelescopeYoke. The question was not which output looked most dramatic, but which methods preserved faint astronomical structure while controlling noise, unwanted gradients, stars and artefacts. I tested denoising, background extraction, star removal, sharpening, stretching and colour processing, using controlled changes to astronomical images and measurable criteria.

The initial denoising comparison used ten pairs of independently stacked exposures, with artificially planted faint filaments and a common amount of remaining grain. At the 50% grain setting, **GraXpert 3.0.2** had an error of **0.971** against an independent reference, relative to **1.000** for a plain blur. It preserved **88.5%** of the planted filament signal. DeepSNR preserved slightly more of the filament but had slightly higher reference error; the other automatic denoisers did not beat GraXpert on the combined criteria. GraXpert was adopted for *picture production only*, not scientific measurement.

For star removal, **Dark Star** from Seti Astro Suite Pro worked well on most of the tested images when its output was blended selectively with the original. Across **53 individual channel stacks from 17 image collections**, the blend passed the original faint-line preservation criterion on **53/53**. A separate effectiveness check found it met the star-removal comparison on **52/53** overall and **46/53** for the hardest tenth of stars. On one Tarantula Nebula channel, almost no stars were removed. That failure was already present in Dark Star's own output with the settings TelescopeYoke gives it, not introduced by TelescopeYoke's blending.

For stretching, TelescopeYoke's existing method retained a stronger ratio of faint artificial detail to grain under the selected automatic-processing comparison: **10.1**, against **5.4–5.7** for the tested Siril and Seti Astro alternatives. Some alternatives retained more bright detail. The sky brightness targets also differed, so this is **not evidence that one stretch is universally superior**.

The wider evaluation uncovered defects in TelescopeYoke's own stacking and picture handling. Neither a proposed general-purpose hot-pixel cleaner nor a picture-footprint correction passed all required checks. Neither was deployed. The recorded failures are part of the result, not exceptions removed from it.

**Scope:** these are results for the specific software versions, input images, settings, metrics and automated workflows tested. They are not a ranking of what an experienced astrophotographer could achieve with manual adjustment, and they have not been independently peer reviewed.

## The question

Several freely available tools now promise substantial improvements to astronomical images. Some remove noise with AI models; others subtract stars, fit unwanted sky gradients, sharpen structure or stretch faint signals into view. A cleaner or more striking picture is not necessarily a more faithful one. Noise reduction can suppress genuine faint nebula; star removal can erase filaments; sharpening can create structure that another exposure does not support.

I wanted to know **which tools improved the measurable output of an automated pipeline**, and at which processing stages TelescopeYoke should keep its existing methods. This comparison deliberately separates *pictures* from *scientific data*: denoising and star removal operate on copies of retained stacks. They are not fed into TelescopeYoke's photometry or discovery measurements.

## Method

The investigation had two phases. The first used ten held-out half-stack pairs from TelescopeYoke's own observations, principally IC 405 and NGC 2174. Each pair provided a processed image and a second stack made from different exposures of the same target. Faint synthetic filaments or glows were inserted at known strengths. That made it possible to measure how much injected signal survived processing, and whether the processed result moved closer to or farther from the independent stack.

Denoising was compared at matched grain levels, so a method did not win merely by smoothing harder. Background removal was measured on five stacks with known artificial gradients and planted glows. Sharpening was evaluated for added fine detail, grain, ringing and agreement with the independent exposures.

The second phase examined **53 channel stacks associated with 17 image collections**. Some originated as colour images separated into channels for the processing tests; these are *not* 53 independent rigs or 53 independent observations. The larger comparison tested star removal and stretching, along with the ability of the full picture pipeline to handle varied inputs. Finished stacks generally had no independent half-stack, so they **could not independently repeat the original denoiser and sharpening comparisons**.

Acceptance criteria and failures were recorded. Importantly, the original star-removal rule tested preservation of faint filaments; after those results revealed a weakness, an additional criterion required **actual removal of stars**. That additional rule was introduced after the first 53-stack results, and those earlier results were not retroactively presented as having been tested against it in advance. Later correction candidates were evaluated separately on development data, with untouched material reserved for confirmation.

## Results

### 1. Noise reduction

The following results are for the initial ten held-out pairs, at a setting leaving half the original grain. The error column is relative to a plain blur evaluated at the same noise level; **lower error is better**, while **higher filament preservation is better**.

| Method | Planted filament preserved | Error against independent stack |
|---|---:|---:|
| Plain blur | 96.4% | 1.000 |
| **GraXpert 3.0.2** | **88.5%** | **0.971** |
| DeepSNR 1.3.2 | 89.1% | 0.974 |
| Cosmic Clarity AI3.6 | 85.9% | 0.985 |
| TelescopeYoke's previous trained model | 84.1% | 0.984 |
| Siril 1.4.5 NL-Bayes, defaults | 76.0% | 1.017 |
| Seti Astro Suite Pro 1.24.8 AI4 denoise | 65.3% | 1.027 |

GraXpert performed best on the selected combination of fidelity and noise reduction, although DeepSNR kept slightly more of the artificial filament. The plain blur retained more of the planted line than either AI method, illustrating the trade-off: preserving a particular narrow feature and reducing overall error are not identical goals.

The faintest 5% of measured stars in the worst GraXpert test stack lost about **21% of their measured flux**, despite the median star preserving approximately 99.9%. This is one reason the denoiser is used only for a final picture. No result from this stage justifies using AI-denoised pixels for photometry.

**Decision:** use GraXpert for optional automated picture denoising; retire the home-trained denoiser. The 53-stack study did not independently retest this decision.

### 2. Removing background gradients

An unwanted background may come from light pollution, uneven illumination, a sensor artefact or a genuine difference in sky coverage. The danger is that a background-removal algorithm can also subtract real diffuse nebulosity. I tested automatic approaches on five stacks with planted gradients and faint glows.

| Method | Tilt remaining | Bowl remaining | Corner glow remaining | Realistic faint glow retained |
|---|---:|---:|---:|---:|
| **TelescopeYoke sky model** | 0.11 | 0.17 | 0.19 | **88%** |
| GraXpert AI, smoothing 0.5 | 0.13 | 0.18 | **0.10** | 86% |
| Siril polynomial, degree 2 | **0.09** | 0.30 | 0.62 | 90% |
| Siril RBF, defaults | 0.30 | 0.41 | 0.44 | 57% |
| Seti Astro Suite Pro ABE, defaults | 0.26 | 0.27 | 0.30 | 86% |
| Seti Astro Suite Pro ABE, polynomial 2 only | 0.10 | 0.31 | 0.38 | **95%** |

Lower values in the first three columns are better; the glow-retention figure should be near 100%. GraXpert AI handled the artificial corner glow particularly well but removed too much of one faint test glow: on the worst input it retained only **56%**, versus **85%** for TelescopeYoke's sky model. Seti Astro's ABE with a polynomial alone kept more of the faint glow than TelescopeYoke's model (95% against 88%), but left about twice as much of a bowl or a corner glow, so it did not replace it. The methods were not perfectly symmetric: TelescopeYoke can use its Ha filter to locate nebula, while the other tools were generally run with automatic sampling.

**Decision:** keep TelescopeYoke's sky model for this automated workflow. That does not establish that it is the best possible manual background correction, or that it handles every type of field.

### 3. Star removal

Star removal is particularly easy to judge badly. A method can preserve every artificial filament simply by leaving the image unchanged, including all of its stars. I therefore distinguish **preserving astronomical detail** from **actually removing the stellar signal**.

The tested workflow passed each stack through GraXpert and then Dark Star (Seti Astro Suite Pro 1.24.8, mono AI4 model). In the first phase the blend passed the same faint-line rule on two rounds of five stacks not used to develop it; StarNet2, blended the same way, scored about the same and was not adopted. TelescopeYoke blends Dark Star's result only around detections judged to be stars, because unblended Dark Star had removed substantial genuine faint signal in earlier tests. The old TelescopeYoke star-removal method was the comparison baseline.

| Test on 53 channel stacks | Result |
|---|---:|
| Planted faint line kept within five percentage points of the old method | **53/53 passed** |
| Residual stellar signal no more than 10 points worse than old method, overall | **52/53 passed** |
| Same threshold for the hardest tenth of stars | **46/53 passed** |

The blended method left a median **0.2% of measured stellar brightness** under the test's residual-signal metric, versus **1.1%** for the old method. These figures are not percentages of the number of stars remaining; they measure how much stellar signal is left around the measured stars.

The worst cases matter. On the Tarantula Nebula's Ha image, Dark Star's **own output, with the settings used, still retained approximately 94%** of measured stellar signal; TelescopeYoke's blend retained approximately 100%. In several other crowded or strongly nebulous fields, the hardest stars remained almost intact. On an M101 image the fault was different: Dark Star removed more of the stars, but TelescopeYoke's blend restored some of them. This distinction prevents blaming the AI model for a failure created by the integration code. Whether the crowded-field failures come from the model or from what it is given (its tiling, stretch and mode) has not been tested.

**Decision:** Dark Star remains useful for the narrowband picture pipeline, but its performance is not reliable across every crowded field. No change to Dark Star's proprietary model weights was attempted, and the remaining failures have not been solved. Broadband comparisons were research tests; the current LRGB picture path does not invoke Dark Star.

### 4. Stretching faint detail

A stretch maps the faint linear signal of a stacked exposure into visible brightness. More apparent contrast can expose more grain or burn bright structure. The same 53 stacks were measured with planted faint lines, comparing visibility relative to grain and the retention of bright detail.

| Method | Faint-line signal relative to grain | Bright-detail measure |
|---|---:|---:|
| **TelescopeYoke** | **10.1** | 0.0084 |
| Siril autostretch | 5.4 | 0.0130 |
| Siril autoghs | 5.7 | 0.0052 |
| Seti Astro statistical stretch | 5.4 | **0.0138** |

TelescopeYoke scored better on the **specific faint-line-to-grain metric** used for the automatic workflow. Siril autostretch and Seti Astro's statistical stretch retained more measured bright detail. The methods did **not** use the same displayed sky brightness: TelescopeYoke put the sky near black, while the external tools targeted 0.25. These results therefore do not prove that the TelescopeYoke stretch looks better under every viewing condition or with every setting.

**Decision:** retain the existing automated stretch under the selected criteria; no tested replacement met all of the requirements.

### 5. Sharpening, palette and colour calibration

The initial tests found no sharpening method that increased agreement with a second, independent stack. Seti Astro's non-stellar sharpening increased measured fine detail by **45%**, but grain by **41%**; Siril's default Richardson–Lucy deconvolution added much less apparent detail. TelescopeYoke's own sharpening also worsened independent-stack agreement and remains off by default. These measurements did not establish that sharpening creates *no* real detail in general—only that no tested configuration demonstrated a qualifying improvement.

The existing narrowband colour-palette combination was retained after a visual comparison on one stack (NGC 2174) with a simple automated Siril/Seti Astro workflow, which left a purple gradient across the sky; neither tool offers an automatic palette combination. For broadband colour calibration, Siril's spectrophotometric calibration crashed in the tested installation, so it could not be fairly evaluated against TelescopeYoke's star-based balancing. That balance was checked alone against 135 Gaia stars in an M33 field: Sun-like stars came out 0.07 magnitudes from white, against 0.20 with no balance. The crash is a limitation of this test, not a claim that Siril's calibration is generally unusable.

## What the broader tests uncovered

### A science-stacking limitation

TelescopeYoke removes isolated bright pixels before stacking because cosmic-ray hits and hot pixels are not astronomical sources. The difficulty is that a very sharp star can have a similarly compact core. The shipped cleaning passed the defined criteria across **11 sessions on the original rig**, but failed on **three of four additional colour-camera sessions** and **four of four sessions from a second camera**. One second-camera session also contained mismatched fields, complicating interpretation, but it was not silently excluded from the reported failures.

Eight correction candidates were tried. The best candidates recovered stellar brightness more successfully but also protected unwanted cosmic-ray hits. **None passed all criteria**, and the shipped cleaner was left unchanged. Tests with artificial one-frame, star-like signals in the original rig's 11 sessions also found a median **1.8% loss of flux**, with a worst case around **23.5%**, the same with the shipped cleaner and the best candidate. Those results concern planted sources, not measured losses from real discoveries. They matter because the scientific uses of the pipeline require more caution than producing an attractive final picture.

### A false correction for image footprints

The complete picture pipeline initially showed visible defects in **five of 17 image collections**. Some defects were areas with less exposure coverage, while others involved the background model or missing calibration. A candidate correction estimated poorly covered areas from unusually high grain and excluded or cropped them in the *picture only*, leaving the retained stacks untouched.

That approach improved several development images. But the final check used six reserved image sets. Two could not be read; two of the four successfully processed pictures were damaged by the candidate. In the Thor's Helmet field, genuine faint extended nebula looked like a poorly covered image edge and was partly lost. **The candidate failed and was not adopted.** Actual coverage-weight maps provide stronger information than a guess based on image grain.

Two narrower production fixes did go in: saturation values are no longer allowed to overflow the half-precision storage used for some colour frames, and options that do not operate in the LRGB path are now explicitly refused rather than quietly accepted.

## Limits of the evidence

1. **Automatic operation only.** This study measured the specified releases and presets or commands used in the automated pipeline. Manual tuning could yield different results.
2. **Not every test used independent exposures.** The ten original half-stack pairs allowed independent-stack comparisons for denoising and sharpening. The later 53-stack comparisons did not provide that independent reference.
3. **Not 53 independent cameras.** The 53 star-removal and stretch inputs were channel stacks from 17 image collections, with some colour sources separated into channels.
4. **The rules evolved transparently.** The effectiveness requirement for star removal was added after the initial faint-detail scores. It was not a criterion fixed before those initial scores were seen.
5. **The held-out check did not always succeed.** Some confirmation files could not be read, and the footprint correction failed on readable confirmation inputs. No failed result was converted into a pass by changing the threshold.
6. **Not all test material is redistributable.** Contributor-provided data and links are omitted. The numerical evidence and code do not, by themselves, permit an independent reader to regenerate every result without access to the original inputs.
7. **Not peer reviewed.** These figures are taken from the project's recorded experiments. They have not been independently reproduced for this publication.

## Conclusion

The measurements support a **selective** use of free astrophotography processing tools, rather than replacing every part of the pipeline with a free application or an AI model. GraXpert improved the measured denoising result on the original independent half-stack tests. Dark Star improved typical star removal while protecting faint injected lines, but it was unreliable in certain crowded fields. The tested automatic stretches, sharpening methods and background extraction methods did not satisfy all of the criteria required to replace TelescopeYoke's existing methods.

The most useful outcome was not simply the set of tools chosen. The measurements revealed circumstances in which a technically plausible image correction can remove real astronomical signal. That is why failed candidates remain in the research record and why no cleaner or footprint correction was deployed merely because it improved a few familiar pictures.

## Source records and methods

- [Free-tools research plan and first-round measurements](https://github.com/Ryan-Clinton/telescopeyoke/blob/main/docs/free-tools-plan.md)
- [Independent-data confirmation protocol](https://github.com/Ryan-Clinton/telescopeyoke/blob/main/docs/research/free-tools-2026-11-23/confirmation-protocol.md)
- [Confirmation results, including failures](https://github.com/Ryan-Clinton/telescopeyoke/blob/main/docs/research/free-tools-2026-11-23/confirmation-results.md)
- [Recorded deviations from the protocol](https://github.com/Ryan-Clinton/telescopeyoke/blob/main/docs/research/free-tools-2026-11-23/deviations.md)
- [Research scripts and index](https://github.com/Ryan-Clinton/telescopeyoke/tree/main/docs/research/free-tools-2026-11-23)
- [The earlier 23 November diary entry](https://ryanclinton.uk/astrophotography/2026-11-23-testing-the-free-tools/)

## Data and code availability

The code is at https://github.com/Ryan-Clinton/telescopeyoke, and every number here is in the records linked above, with the scripts that made it. The first phase's stacks are the project's own. The second phase's stacks and raw frames, and the reserved confirmation sets, are not the project's to redistribute, so they are neither named nor linked, and those results cannot be reproduced from public data alone. The tests were designed, run and recorded by TelescopeYoke's AI assistant (Claude), and the method was reviewed with ChatGPT.

## References

- GraXpert 3.0.2, S. Hirsch et al., https://github.com/Steffenhir/GraXpert
- Seti Astro Suite Pro 1.24.8 (Dark Star, Cosmic Clarity, statistical stretch, ABE), F. Ramos, https://github.com/setiastro/setiastrosuitepro
- Siril 1.4.5, https://siril.org
- DeepSNR 1.3.2; StarNet2
- Gaia Collaboration, Vallenari, A. et al. 2023, A&A 674, A1: Gaia Data Release 3.

## Revisions

Version 1.0, 27 November 2026. First version.

*Draft for review. Not published.*