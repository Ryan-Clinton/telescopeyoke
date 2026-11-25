# Deviations from the confirmation protocol

Each change made after the protocol was fixed, with its reason. Nothing here changes a rule.

- **25 November 2026, step 1, the harness only.** Set 76's camera has no darks in our library, so the
  test calibrates each frame with the set's own master bias (median of its 100 bias frames) and its
  own flat for that filter (median of its 10, bias taken off, normalised), then destripes and bins it
  as the harness always has. Only the 600 s frames, as the protocol states (some nights mix in 300 s). The sessions, chosen before any was measured: for each filter the first
  and the last night with at least 20 frames of 600 s, up to 40 frames each (Ha 10 October and 2 November 2025,
  OIII 10 and 29 October 2025). A first start failed before measuring anything, on a list index, with the 300 s frames mixed in. The harness reads the frames from the file's primary HDU, where this camera keeps them (ours keep theirs in the second). Script: `clip76.py` on the desktop, beside the other cleaning tests.
