"""Make pipe-fp4/colour.py: colour.py with the covered-area candidate (development data only).
A block of the base stack whose grain is over 1.5 times the stack's usual grain was reached by fewer frames:
it is left out of the sky fit (set to no data, as an empty edge already is) and the finished picture is cropped
to the largest rectangle that is all well covered."""
from pathlib import Path
p = Path("colour.py"); s = p.read_text()
helper = '''

def well_covered(image, block=32, limit=1.5):
    """Where enough of a stack's frames reached: its grain in blocks, against the stack's usual grain. A block
    over `limit` times it is thinly covered (a turned or untracked stack's footprint, an uncropped mosaic)."""
    from scipy import ndimage as N
    d = np.nan_to_num(image.astype(np.float32))
    fine = d - N.median_filter(d, 5)
    h, w = d.shape[0] // block * block, d.shape[1] // block * block
    grain = 1.4826 * np.median(np.abs(fine[:h, :w]).reshape(h // block, block, w // block, block)
                               .transpose(0, 2, 1, 3).reshape(h // block, w // block, -1), axis=2)
    level = np.median(d[:h, :w].reshape(h // block, block, w // block, block).transpose(0, 2, 1, 3)
                      .reshape(h // block, w // block, -1), axis=2)
    # Thin coverage is sky with more grain, reaching the frame's edge: a nebula or galaxy raises the grain too
    # but is brighter than the sky, and sits inside the frame (the first try cut 10 of 17 pictures to nothing).
    thin = (grain > limit * np.median(grain)) & (level <= np.percentile(level, 60))
    thin = N.binary_closing(N.binary_opening(thin, iterations=1), iterations=2, border_value=1)
    labels, n = N.label(thin)
    edge = set(np.unique(np.concatenate([labels[:2].ravel(), labels[-2:].ravel(), labels[:, :2].ravel(), labels[:, -2:].ravel()]))) - {0}
    # The thin part's inner edge, where only a few frames are missing, is under the grain limit: take two blocks more
    # (D28's corner wedges and D57's band showed past the first mask's edge).
    good = ~N.binary_dilation(np.isin(labels, list(edge)), iterations=2)
    full = np.ones(d.shape, bool)
    full[:h, :w] = np.repeat(np.repeat(good, block, axis=0), block, axis=1)
    full[h:, :] = full[h - 1:h, :] if h < d.shape[0] else full[h:, :]
    full[:, w:] = full[:, w - 1:w] if w < d.shape[1] else full[:, w:]
    return full


def inside(valid):
    """The largest rectangle all inside `valid`, as r0, r1, c0, c1 (shrinking the side with most left out)."""
    r0, r1, c0, c1 = 0, valid.shape[0] - 1, 0, valid.shape[1] - 1
    while r1 - r0 > 10 and c1 - c0 > 10:
        box = valid[r0:r1 + 1, c0:c1 + 1]
        if box.mean() >= 0.999:
            break
        sides = [(1 - box[0].mean(), "t"), (1 - box[-1].mean(), "b"), (1 - box[:, 0].mean(), "l"), (1 - box[:, -1].mean(), "r")]
        side = max(sides)[1]
        step = max(1, (r1 - r0) // 200 if side in "tb" else (c1 - c0) // 200)
        if side == "t": r0 += step
        elif side == "b": r1 -= step
        elif side == "l": c0 += step
        else: c1 -= step
    return r0, r1, c0, c1
'''
anchor = "\ndef combine("
assert anchor in s; s = s.replace(anchor, helper + anchor, 1)
old = "    valid = np.all([np.isfinite(i) for i in images.values()], axis=0)\n"
assert old in s
s = s.replace(old, old + "    shared = valid.copy()   # what every filter reached, before the thin parts are left out\n    valid &= well_covered(images[base])   # candidate: thinly covered blocks left out\n", 1)
old2 = """    by_row, by_col = valid.sum(axis=1), valid.sum(axis=0)
    rows = np.where(by_row >= 0.97 * by_row.max())[0] if by_row.max() else np.array([], int)
    cols = np.where(by_col >= 0.97 * by_col.max())[0] if by_col.max() else np.array([], int)
    if rows.size and cols.size:
        r0, r1, c0, c1 = rows[0], rows[-1], cols[0], cols[-1]"""
new2 = """    rows = cols = np.array([0])
    if valid.any():
        r0, r1, c0, c1 = inside(valid)   # candidate: the largest rectangle all well covered"""
assert old2 in s; s = s.replace(old2, new2, 1)
p.write_text(s); print("patched")

# The filters-apart refusal guards against filters that drifted apart (the target cut off); a stack's thinly covered
# edge is not that, so the refusal counts what the filters share, not what is left once the thin parts are out.
s = p.read_text()
old3 = "            if share < min_covered:"
assert old3 in s
s = s.replace(old3, "            if float(shared.sum()) / shared.size < min_covered:", 1)
p.write_text(s); print("patched 3")
