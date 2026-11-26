# Deviations from the confirmation protocol

Each change made after the protocol was fixed, with its reason. Nothing here changes a rule.

- **25 November 2026, step 1, the harness only.** Set 76's camera has no darks in our library, so the
  test calibrates each frame with the set's own master bias (median of its 100 bias frames) and its
  own flat for that filter (median of its 10, bias taken off, normalised), then destripes and bins it
  as the harness always has. Only the 600 s frames, as the protocol states (some nights mix in 300 s). The sessions, chosen before any was measured: for each filter the first
  and the last night with at least 20 frames of 600 s, up to 40 frames each (Ha 10 October and 2 November 2025,
  OIII 10 and 29 October 2025). A first start failed before measuring anything, on a list index, with the 300 s frames mixed in. The harness reads the frames from the file's primary HDU, where this camera keeps them (ours keep theirs in the second). Script: `clip76.py` on the desktop, beside the other cleaning tests.
- **25 November 2026, steps 2 to 4, the input only.** `colour.py` takes one mono stack per filter and
  most of the shared sets are single colour stacks, so each is split into its channels before the
  run: through a dual-band filter (by the owner's stated filter, decided before any stack was read) red
  as Ha and the mean of green and blue as OIII, with palette HOO; otherwise red, green and blue with
  their mean as L, palette LRGB; set 41's two dual-band stacks give SHO. Nothing in `colour.py`
  changes. Script: `ds_sessions.py` on the desktop.
- **25 November 2026, step 1 on a colour camera, the harness only.** Raw 2600MC Pro frames at
  1000 mm from a public Bortle 2 archive: each frame's night's flat (median of its 20, each Bayer site
  normalised on its own) divided out, with no dark or bias (none in the archive), split into colour
  pixels as `camera.colour` does, and the green channel tested, as the restack cleans each channel.
  Sessions fixed before any was measured: for each target the first night with at least 20 lights, up
  to 40 frames (Abell 1656, LBN 552, M81, NGC 7293). Script: `clip533.py` on the desktop.
- **25 November 2026, step 1's measure, before any re-scoring.** Neither set 76 nor the colour
  archive has darks, so the sensor's fixed hot pixels survive the stack wherever the frames were not
  dithered, and the measure took them for stars (149 of 237 "stars" in the first colour session were
  lone spikes; all 171 in set 76's first). Measure 2 leaves out "stars" narrower than 1.5 px in the
  uncleaned stack; nothing else changes. The first verdicts stand as recorded; measure 2 is reported
  beside them, on the same sessions. Scripts: `clip_m2.py`, `clip533m2.py`, `clip76m2.py`, `clip76um2.py`.
- **25 November 2026, step 1's measure again.** Measure 2 left nothing out: to the star finder the
  hot pixels measure wider than 1.5 px, so its first session scored exactly as before, and it was
  stopped. Measure 3 leaves out a star whose centre is a lone spike in the uncleaned stack, by the
  lone-spike test the measure already used to count them. Scripts: `clip_m3.py`, `clip533m3.py`, `clip76m3.py`.
- **25 November 2026, step 1's harness made to match the shipped code.** Looking pixel by pixel at
  a failing colour frame, the new lone-pixel test replaced 9 pixels in its 60 brightest stars (the old
  test 1,182), so the stack's losses came from the defect map. The harness built its map as every
  pixel scoring over 5 in the frames' median, without the guard `stacking.defect_map` has (a pixel
  whose third-brightest neighbour stands out too is a star that did not move, and is left). On
  dithered frames, as all this project's are, stars move and the two agree; on frames not dithered,
  the harness marked star cores as defects and cut them, which `restack.py` does not. The harness's map
  now has that guard; both cameras' sessions are run again with it. Scripts: `clip13g.py`,
  `clip533g.py`, `clip76g.py`.
- **25 November 2026, step 3 on finished stacks.** `stretch.py` measures against an independent
  half-stack, which the shared sets do not have. `ds_stretch.py` keeps its methods, measures and pass
  mark, and takes the regions (sky, faint, bright) from the same stack smoothed; the planted lines go
  into the stack before GraXpert, the pair being the stack denoised without and with them, scaled to
  its 99.995th percentile for the tools. Step 2 on the shared sets takes every filter's stack
  (`ds_real.py`), as the protocol says, where the AstrophotoMarket run took one per set.
- **25 November 2026, the float16 store (beb6b79).** `stacking.register_file` now keeps a colour
  frame's pixel over 65504 at 65504 instead of inf. It touches the restack only (step 1's pipeline
  path, colour cameras); the step 1 harness keeps its own float16 cubes and was not changed by it, and
  steps 2 to 4 read finished stacks. Results before beb6b79 and after it name their commit.
- **26 November 2026, `--background level` on LRGB.** `colour.py` used the choice only in the linear
  narrowband mix; an LRGB picture was made exactly as with `auto`. So step 4's LRGB sets marked "level"
  (40, 44, 49, 56, 57, 72) were in fact made with the automatic background; their verdicts stand as
  verdicts on that. `colour.py` now refuses `--background level` and `--star-removal none` where they
  would do nothing.
- **26 November 2026, the protocol's addition.** Data roles (development, frozen, cross-camera), failures kept
  as failures, a second star-removal rule (stars removed) and the data owner's notes beside failures were
  added to `confirmation-protocol.md`, before any fix is judged. Steps 1 to 4's results so far stand as run.
