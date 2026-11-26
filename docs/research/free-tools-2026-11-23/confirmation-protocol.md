# A confirmation on other people's data, fixed before it is read

Written on 25 November 2026, before any result from these sets was measured. Up to now only their
file types, image sizes and frame counts have been looked at. Every rule below was chosen on our
own data and AstrophotoMarket's; these sets are a test of the rules as they stand, the way a session
fixed in advance tests a search.

## The data

Data sets from about 80 other rigs: colour and mono cameras, DSLRs, smart telescopes, lenses from
55 mm to an 8" SCT at 2032 mm, Bortle 1 to 9. Their sources are not named, and no picture made
from them is published: results are reported as numbers, by kind of rig.

Fields held out of all tuning (IC 405, IC 410, NGC 2174, within 5 degrees) stay held out: a set on
one is used here, as a test, and never for any later change.

## The code

The commit that adds this file. `stacking.py`, `colour.py` and `freetools.py` as they are there;
GraXpert 3.0.2, Seti Astro Suite Pro 1.24.8 (Dark Star, mono AI4 model), Siril 1.4.5. Any change
to the code after that, for any reason, is logged in `deviations.md` beside this file with the reason
and the stages it touched, and stated beside the result.

## What is measured, and the rule for each

Each rule is the one already used on our own data, unchanged.

1. **Hot-pixel and cosmic-ray cleaning** (sets with raw frames: set 76, 697 Ha and OIII frames of
   600 s from a QHY Minicam8M, with its bias and flats; any other raw set is added before its data
   is read). The restack's cleaning against no cleaning, on each filter, by the pass mark of
   24 November: brightest-third star flux within 0.5%, peak within 1%, grain within 1%, fixed defects
   left no worse than the old cleaning, visible cosmic-ray pixels at most the old cleaning's plus 10.
   Reading another camera's frames needs the harness to read its files and calibration; that
   change is logged as a deviation, and nothing in the cleaning is changed.
2. **Star removal** (every set with a finished stack). Dark Star blended, each star decided once for
   all filters, against our old star removal after the same GraXpert denoise: a planted thin faint
   line kept to within 5 points of our code, in every filter.
3. **Stretch** (every set with a finished stack). Ours against Siril's autostretch and autoghs and
   the suite's statistical stretch, each at its default sky level, measured in the faint nebula
   away from stars: a tool replaces ours only with faint lines over grain and bright detail at least
   ours and no more than 0.1 points more burnt white.
4. **The whole chain runs** (every set). `colour.py` on each set's stacks with its defaults, and
   `--background level` where the field is wider than 3 degrees, decided from the plate solve or the
   stated focal length before the run: the run finishes, the picture has no tile, edge or ring
   artefact, and its settings record names each tool, version and model. A failure is counted, not
   fixed first.

Noise reduction and sharpening were judged against an independent half-stack of other frames.
Finished stacks have none, so neither is judged on them; set 76's raw frames can make the halves,
and for that set both are measured as on 23 November.

## What is not a verdict

Comparisons by eye against other processing of the same data are for our own guidance only; no
rule is drawn from them and none is published.

## Reporting

Every set run is reported, passes and failures, in one table per stage, with the code's commit.
A set that cannot be read is listed with why.

## Added 26 November 2026, before any fix is judged (logged in deviations.md)

- **Three roles for data.** Everything run so far is development data. A fix is judged once, after it is
  final, on frozen confirmation data chosen from its listing (camera, scale, subs, calibration) and written
  down before it is opened; and on other cameras' data for cross-camera. Frozen data is never used to tune.
  The frozen sets were chosen on 26 November 2026: six finished stacks fetched on 25 November (only their
  file names and one header card each read), and five raw sessions of the raw archive named by target kind
  before anything inside them was listed. Data run before then, and any set named as an example (the two
  untracked lens sets among them), stays development.
- **A failure stays a failure.** A set that failed a stage stays in that stage's table as a failure with its
  commit, whatever a later fix does; the fix's result is a new row.
- **Star removal has two rules from now on**: the planted faint line kept, as before, and stars removed:
  stars left no more than our own removal's plus 10 points, overall and in the worst tenth, in every stack.
- **What the data's owner said about it is recorded beside a failure** (no flats, untracked, uncropped
  mosaic, drizzled, a mislabelled filter), and does not change the verdict.
