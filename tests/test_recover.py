"""Recovering a known transient from archive images: the search answer is
read and the sharpest clean image picked, the cut-outs are kept, and a
transient that appeared between two made-up ZTF images is found at its
place. A stand-in for IRSA answers; nothing touches the network."""
import io

import numpy as np
import pytest
from astropy.io import fits

import config
import interface
import recover
from test_depth import render, star_field

SEARCH_ANSWER = """in_row_id,in_ra,in_dec,field,ccdid,qid,filtercode,obsjd,filefracday,seeing,maglimit,infobits
1,10.3,40.9,695,11,3,zr,2460451.97,20240521471250,2.08,20.17,0
1,10.3,40.9,695,11,3,zr,2460447.97,20240517472766,1.90,20.33,33554432
1,10.3,40.9,695,11,3,zr,2460449.97,20240519471111,2.50,20.0,0
"""


class Reply:
    def __init__(self, text="", content=b""):
        self.text, self.content = text, content

    def raise_for_status(self):
        pass


def test_the_sharpest_clean_image_is_chosen():
    rows = recover.images_near(10.3, 40.9, "2024-05-20", "zr", get=lambda *a, **k: Reply(SEARCH_ANSWER))
    # The sharpest is flagged (infobits); the sharpest clean one comes first.
    assert [r["filefracday"] for r in rows] == ["20240521471250", "20240519471111"]
    assert recover.url(rows[0], 10.3, 40.9).endswith("ztf_20240521471250_000695_zr_c11_o_q3_sciimg.fits"
                                                     "?center=10.30000,40.90000&size=600arcsec&gzip=false")


def fits_bytes(image, wcs, zp=26.3):
    header = wcs.to_header()
    header["MAGZP"] = zp
    buffer = io.BytesIO()
    fits.PrimaryHDU(image.astype(np.float32), header).writeto(buffer)
    return buffer.getvalue()


def test_a_transient_between_two_images_is_recovered_at_its_place(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    before, wcs, _ = star_field(shape=(600, 800), count=300, seed=6)
    spot = (412.3, 287.6)
    ra, dec = (float(v) for v in wcs.pixel_to_world_values(*spot))
    after = before + render(before.shape, np.array([spot]), np.array([900.0])) \
        + np.random.default_rng(7).normal(0, 4, before.shape).astype(np.float32)
    images = {"20240521471250": fits_bytes(before, wcs), "20240627360232": fits_bytes(after, wcs)}

    def get(url, params=None, timeout=None):
        if params:      # a search: one image a date
            jd = float(params["WHERE"].split()[2])      # obsjd BETWEEN <from> AND <to> ...
            ff = "20240521471250" if jd < 2460460 else "20240627360232"
            return Reply(SEARCH_ANSWER.splitlines()[0] + f"\n1,{ra},{dec},695,11,3,zr,{jd},{ff},2.0,20.2,0\n")
        return Reply(content=images[next(k for k in images if k in url)])
    answer = recover.recover("TEST", ra, dec, "2024-05-21", "2024-06-27", "zr", say=lambda *_: None, get=get)
    assert answer["recovered"] and answer["arcsec_off"] < 1.5 and answer["rank"] == 1
    assert len(list((tmp_path / "cache" / "ztf").glob("*.fits"))) == 2     # kept for next time


def test_a_page_that_is_not_an_image_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    row = {"filefracday": "20240521471250", "field": "695", "ccdid": "11", "qid": "3", "filtercode": "zr"}
    with pytest.raises(interface.Refusal):
        recover.cutout(row, 10.3, 40.9, get=lambda *a, **k: Reply(content=b"<html>503</html>"))
