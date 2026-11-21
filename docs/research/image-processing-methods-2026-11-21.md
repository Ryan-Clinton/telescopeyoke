# Picture-processing methods: what the free sources say

Read 21 November 2026, for `docs/image-processing-spec.md`. These are notes in
our own words. Nothing here is copied code, and nothing has been tried unless
it says so.

## What was and was not read

| Source | Status |
|---|---|
| [GHS process documentation](https://www.ghsastro.co.uk/doc/tools/GeneralizedHyperbolicStretch/GeneralizedHyperbolicStretch.html) | Read: formulas, parameters, cautions |
| [Siril's GHS tutorial](https://siril.org/tutorials/ghs/) | Read, its last quarter through a summary |
| [Siril's SPCC documentation](https://siril.readthedocs.io/en/stable/processing/color-calibration/spcc.html) | Read |
| [Siril source](https://gitlab.com/free-astro/siril), a400664, GPLv3 | Parts read: background, wavelet noise, GHS, SPCC fit, green removal. **The method may be learned; the code may not be pasted** into this project without taking on the GPL |
| [Noise2Noise](https://proceedings.mlr.press/v80/lehtinen18a.html) | Read for the noise conditions and losses |
| [PixInsight's public tutorials](https://pixinsight.com/tutorials/index.html) | Read in a normal browser: gradient correction, noise comparison, median-transform noise reduction and sharpening, dynamic range, narrowband, and the MARS page. The site's terms forbid reproducing its material, so these are short notes in our own words |
| PixInsight's tool reference (`pixinsight.com/doc/`) | **Not available**: the folder answers 403 and the tool pages tried answer 404, in a browser too. It appears to ship with the program |
| PixInsight Class Library | **Not used.** Its licence (2.0.1) forbids use of the source for machine-learning training, datasets, or automated code generation. The copy fetched was deleted after its licence, file list and one header comment had been seen |
| Starck et al. on the starlet transform; Starck, Pantin and Murtagh 2002 on deconvolution | **Not read**: not found at the places tried |

## What each method does, and what it means here

**Stretch (GHS).** A family of curves set by a strength D, a shape b, a symmetry
point SP where contrast is greatest, and limits LP and HP below and above which
the curve is a straight line, protecting shadows and highlights. Tried here in
one form only, an arcsinh centred on the nebula's faint level (b fixed), on NGC
2174. It lifted the nebula's 90th percentile from 57 to 59 of 255 and clipped
more sky to black (15.0% to 17.9%), so it was **not kept**. The full family with
LP and HP has not been tried.

**Star colour (SPCC).** Needs a plate-solved, linear image. Each star's expected
flux in each channel comes from its Gaia DR3 XP spectrum through the sensor's
and filters' response curves. A robust straight-line fit (repeated median) of
catalogue R/G and B/G against measured R/G and B/G gives each channel's factor.
Siril warns that it does not give a Hubble-palette look: an SHO image goes green.
So it suits **LRGB pictures**, not our SHO and HOO, and needs our filter curves.

**Background.** Siril samples the sky at many small boxes, takes each box's
median, and interpolates with a thin-plate radial basis function. That could
replace our bowl plus edge map, since it follows a corner patch without a band
limit. It would need the same planted-glow measurement before it is trusted.

**Noise reduction.** Siril's wavelet denoiser uses BiShrink (soft thresholds that
use the parent scale), with each scale's noise propagated, and can first apply an
Anscombe transform so photon noise becomes even. It also includes NL-Bayes, which
averages similar patches. Our simple threshold kept no more detail than a blur,
so **BiShrink or NL-Bayes is the stronger baseline** for a trained denoiser to beat.

**Green removal (SCNR).** Average-neutral caps green at the mean of red and blue.
Our SHO step is this with 25% of the excess kept.

**Noise2Noise.** With an L2 loss the network learns the mean of its noisy targets,
so the target noise must be zero-mean; L1 learns the median. This supports the
linear L2 loss in the spec. A shared offset between halves is not zero-mean noise.

## What PixInsight's own tutorials add

**Gradients ([Multiscale Gradient Correction](https://pixinsight.com/tutorials/multiscale-gradient-correction/index.html)).**
Its argument is that sampling "empty" sky cannot be trusted, because a deep image
may have none and nothing can be known about the gradient behind the object. It
uses a second, much wider image of the same field, where the gradient across our
small frame is almost nothing. Both are colour calibrated and aligned, their
large scales are isolated, and the difference (with the wide image scaled by a
hand-tuned k) is the gradient model, which is subtracted. **For this rig:** the
guide camera already looks at the same sky through a wider lens, so it might
serve as that second image for broadband work. It has no narrowband filters, its
field and depth have not been checked, and using it would change how a night runs.

**Noise ([comparison](https://pixinsight.com/tutorials/nr-comparison/index.html),
[median transform](https://pixinsight.com/tutorials/mmt-noise-reduction/index.html)).**
On two synthetic images, a 2013 comparison by its author found total generalised
variation (TGV) the best general denoiser; wavelets did well only on smooth
targets and lost sharp edges. That fits our result, where a wavelet threshold was
no better than a blur. Median-based scales isolate strong small structures better
than wavelets. Their usual thresholds are 3 to 4 MAD on the first layer, smaller
above it. **For this rig:** TGV joins BiShrink and NL-Bayes as a baseline to try.

**Local contrast ([sharpening](https://pixinsight.com/tutorials/mmt-sharpening/index.html),
[dynamic range](https://pixinsight.com/tutorials/NGC7023-HDR/index.html)).**
Any linear filter, including our difference of Gaussians, rings at strong edges.
Median filters do not. The dynamic range tutorial protects stars with a mask, then
restores colour saturation, which local methods reduce, and checks for ringing with
a ratio map of the original against the result. It also warns that multiscale
tools can turn artefacts into faint false nebulae. **For this rig:** our local
contrast should move to median scales and get that ringing check.

**Stars and narrowband ([tutorial](https://pixinsight.com/tutorials/narrowband/index.html)).**
Stars are about the same width in broadband and narrowband when linear. What differs
is their brightness against the nebula, which supports balancing nebula and stars
apart, as `colour.py` now does. For Ha into RGB it divides broadband by narrowband
to get a continuum map, denoises it hard, and multiplies the narrowband by it. That
gives a synthetic red with the star colours of R and the low noise of Ha.

## Local contrast, measured on NGC 2174

Built in `colour.py` as a gain from the star-free nebula's structure between 3
and 24 px. To check that this is real sky and not amplified noise, the frames of
one session per filter were split into odd and even halves, and the same scales
compared between the halves (they share calibration masters):

| Filter (frames per half) | 1-3 px | 3-8 px | 8-24 px | 3-24 px |
|---|---:|---:|---:|---:|
| Ha (12) | 0.12 | 0.85 | 0.99 | 0.97 |
| OIII (12) | 0.05 | 0.63 | 0.98 | 0.92 |
| SII (4) | 0.08 | 0.45 | 0.92 | 0.72 |

Below 3 px the halves do not agree: that is noise, and it is left alone. From 3
to 24 px they do, so the structure brought out is mostly real. The weakest band
is 3-8 px in SII, from only 4 frames per half.

## Next, in order

1. Move local contrast to median scales, with a ringing check.
2. Try TGV, then BiShrink with the Anscombe transform, against the plain blur,
   using the planted-signal measurement.
3. Try a thin-plate sky model against the current bowl and edge map.
4. Add photometric colour for LRGB pictures, once the filters' curves are in hand.
5. Look at whether the guide camera can provide a wide reference for gradients.
