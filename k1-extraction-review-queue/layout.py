"""Read every sample with Docling: the words on each page with their boxes, and each page as Markdown.

Docling does the layout work in the model pipeline. Born-digital pages come from
the PDF's text layer; scanned pages go through Docling's OCR stage (Tesseract,
since it's already needed for the baseline). Its output is used three ways:

- to find each printed box label, so we know where every box is on the page;
- as a second, independent read of each value the vision model reports;
- to find the supplemental statement pages and give their text, in reading
  order with tables, to the model.

Writes output/layout/<file>.json. Each file is only converted once; delete the
folder to redo it.
"""

import json
import logging
import sys
import time
from pathlib import Path

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions, TesseractCliOcrOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.types.doc import CoordOrigin

HERE = Path(__file__).parent
SAMPLES = HERE / "samples"
OUT = HERE / "output" / "layout"


def converter():
    opts = PdfPipelineOptions(do_ocr=True, ocr_options=TesseractCliOcrOptions(lang=["eng"]),
                              do_table_structure=True, generate_parsed_pages=True)
    return DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)})


def words_of(page):
    """Word boxes in PDF points from the top-left corner, with a 0 to 100 confidence (100 for a text layer)."""
    pp = page.parsed_page
    cells = pp.word_cells or pp.textline_cells
    h = page.size.height
    words = []
    for c in cells:
        bb = c.rect.to_bounding_box()
        if bb.coord_origin != CoordOrigin.TOPLEFT:
            bb = bb.to_top_left_origin(page_height=h)
        parts = c.text.split()
        if not parts:
            continue
        # A text-line cell holds several words: split it, sharing its width by characters.
        n = sum(len(p) + 1 for p in parts) - 1
        x, step = bb.l, (bb.r - bb.l) / max(1, n)
        for p in parts:
            words.append({"text": p, "conf": round(100 * c.confidence) if c.from_ocr else 100,
                          "x0": x, "y0": bb.t, "x1": x + len(p) * step, "y1": bb.b, "ocr": c.from_ocr})
            x += (len(p) + 1) * step
    return words


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    logging.getLogger("docling").setLevel(logging.ERROR)
    files = sorted(SAMPLES.glob("*.pdf"))
    if len(sys.argv) > 1:
        files = [f for f in files if any(a in f.name for a in sys.argv[1:])]
    conv = None
    for path in files:
        out = OUT / (path.stem + ".json")
        if out.exists():
            continue
        conv = conv or converter()
        t0 = time.time()
        res = conv.convert(path)
        pages = []
        for page in res.pages:
            md = res.document.export_to_markdown(page_no=page.page_no)  # Docling numbers pages from 1
            words = words_of(page)
            pages.append({"index": page.page_no - 1, "width": page.size.width, "height": page.size.height,
                          "ocr": any(w["ocr"] for w in words), "words": words, "markdown": md})
        seconds = round(time.time() - t0, 1)
        out.write_text(json.dumps({"file": path.name, "seconds": seconds, "pages": pages}))
        print(f"{path.name:38s} {len(pages):2d} pages {seconds:6.1f}s")


if __name__ == "__main__":
    main()
