"""Download the real sample K-1 packages and make scanned copies of their K-1 pages.

Publicly traded partnerships post sample K-1 tax packages for their unitholders:
the issuer's real K-1, printed by their tax software, with supplemental
statements, made out to a placeholder investor ("SAMPLE K-1"). We download them
from the issuers' own sites at run time rather than committing them, and check
each file's hash so the hand-keyed answer key (real_answer_key.json) matches.

Each K-1 page is also printed and "scanned" (rotated, blurred, noisy, JPEG) so
the same real page can be read through OCR as well as from its text layer.
"""

import hashlib
import random
import sys
import urllib.request
from pathlib import Path

import pypdfium2 as pdfium

from generate import degrade, image_pdf

HERE = Path(__file__).parent
SAMPLES = HERE / "samples"
SOURCES = {
    "01-enviva-2018-k1.pdf": (
        "https://www.envivabiomass.com/wp-content/uploads/2019/09/Enviva_Sample_Tax_Package_10000_units.pdf",
        "0dcf2a2eacfa37866b5688d5f28c79c02f40004dc2ae39171816e33d629d2e1a", 2),
    "02-enviva-2021-k1.pdf": (
        "https://s28.q4cdn.com/898203682/files/doc_downloads/schedule_k-1s/2022/03/EVA-2021-Sample-K-1-1-000-Units.pdf",
        "8a99f85cce2208352676a7853be8e5d43c04ee9923694cdcc3ee8d10da6274e1", 2),
    "03-blackstone-2019-k1.pdf": (
        "https://s23.q4cdn.com/714267708/files/doc_downloads/2020/03/SAMPLESCHEDULE_K1_2019.pdf",
        "60a77e0c5d6e8685f18fd34cce2d09fcb2ff1a1d7c4bff9a32ef7e8fd1580414", 3),
}
# (source, scan level, set): level 1 is an ordinary office scan, 2 a bad fax or phone
# photo. The "a" scans were used while tuning the extractor; the "b" scans come from a
# different seed and were held out.
SCANS = [("01-enviva-2018-k1.pdf", 1, "a"), ("02-enviva-2021-k1.pdf", 1, "a"), ("02-enviva-2021-k1.pdf", 2, "a"),
         ("03-blackstone-2019-k1.pdf", 1, "a"),
         ("01-enviva-2018-k1.pdf", 1, "b"), ("01-enviva-2018-k1.pdf", 2, "b"), ("02-enviva-2021-k1.pdf", 1, "b"),
         ("03-blackstone-2019-k1.pdf", 1, "b"), ("03-blackstone-2019-k1.pdf", 2, "b")]


def main():
    SAMPLES.mkdir(exist_ok=True)
    for name, (url, sha, _page) in SOURCES.items():
        path = SAMPLES / name
        if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != sha:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            data = urllib.request.urlopen(req, timeout=60).read()
            got = hashlib.sha256(data).hexdigest()
            if got != sha:
                sys.exit(f"{name}: the issuer's file has changed (sha256 {got}); the answer key no longer applies")
            path.write_bytes(data)
        print(f"{name}: ok")
    rngs = {"a": random.Random(1065), "b": random.Random(1066)}
    for src, level, which in SCANS:
        rng = rngs[which]
        page_no = SOURCES[src][2]
        page = pdfium.PdfDocument(SAMPLES / src)[page_no - 1]
        img = degrade(page.render(scale=200 / 72).to_pil(), rng, level)
        out = SAMPLES / src.replace(".pdf", f"-scan{level}{which}.pdf")
        out.write_bytes(image_pdf([img], 200))
        print(f"{out.name}: scanned copy of page {page_no}")


if __name__ == "__main__":
    main()
