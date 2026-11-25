# Deviations from the confirmation protocol

Each change made after the protocol was fixed, with its reason. Nothing here changes a rule.

- **25 November 2026, step 1, the harness only.** Set 76's camera has no darks in our library, so the
  test calibrates each frame with the set's own master bias (median of its 100 bias frames) and its
  own flat for that filter (median of its 10, bias taken off, normalised), then destripes and bins it
  as the harness always has. The sessions, chosen before any was measured: for each filter the first
  and the last night with at least 20 frames, up to 40 frames each (Ha 9 October and 2 November 2025,
  OIII 9 and 29 October 2025). Script: `clip76.py` on the desktop, beside the other cleaning tests.
