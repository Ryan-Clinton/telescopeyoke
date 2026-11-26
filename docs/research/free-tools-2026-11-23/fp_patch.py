"""Make pipe-fp/colour.py: colour.py with the covered-area candidate (development data only).
A block of the base stack whose grain is over 1.5 times the stack's usual grain was reached by fewer frames:
it is left out of the sky fit (set to no data, as an empty edge already is) and the finished picture is cropped
to the largest rectangle that is all well covered."""
from pathlib import Path
p = Path("colour.py"); s = p.read_text()
helper = '''

def covered(image, block=32, limit=1.5):
    """Where enough of a stack's frames reached: its grain in blocks, against the stack's usual grain. A block
    over `limit` times it is thinly covered (a turned or untracked stack's footprint, an uncropped mosaic)."""
    from scipy import ndimage as N
    d = np.nan_to_num(image.astype(np.float32))
    fine = d - N.median_filter(d, 5)
    h, w = d.shape[0] // block * block, d.shape[1] // block * block
    grain = 1.4826 * np.median(np.abs(fine[:h, :w]).reshape(h // block, block, w // block, block)
                               .transpose(0, 2, 1, 3).reshape(h // block, w // block, -1), axis=2)
    good = grain <= limit * np.median(grain)
    good = N.binary_closing(N.binary_opening(good, iterations=1), iterations=2)
    labels, n = N.label(good)
    if n > 1:
        good = labels == (1 + int(np.argmax(N.sum(good, labels, range(1, n + 1)))))
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
s = s.replace(old, old + "    valid &= covered(images[base])   # candidate: thinly covered blocks left out\n", 1)
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
