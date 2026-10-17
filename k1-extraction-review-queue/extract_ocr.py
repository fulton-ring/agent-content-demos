"""Read each document with a hosted OCR model on Modal, then fill the form's schema from the OCR text.

    python extract_ocr.py olmocr openrouter:google/gemini-3.8-flash [file filter ...]
    python extract_ocr.py granite-docling openrouter:google/gemini-3.8-flash [file filter ...]

1. The page to read is found with Docling's layout (output/layout/), as in extract_vlm.py.
2. The page is OCR'd on Modal (ocr_modal.py, GPU). olmOCR 2 returns Markdown; granite-docling,
   through Docling's VLM pipeline, returns Markdown plus each text item's box. Results are
   cached in output/ocr/<engine>/, so the GPU step runs once per page.
3. A text model fills the same typed schema as the vision models (extract_vlm.py's Pydantic
   models), through Pydantic AI, from the OCR text alone. It never sees the image.
4. Values go to review on the same rules as extract_vlm.py --model-only. With granite-docling,
   each value is placed on the page at the text item that contains it.

Writes output/<engine>+<text model>/extracted.json, which evaluate.py, report.py and pair.py
read like any other run. Needs Modal credentials, and OPENROUTER_API_KEY for an OpenRouter model.
"""

import asyncio
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import modal

import ocr_modal
from extract_vlm import (FORMS, K1_LABELS, LAYOUT, PARTIAL_EXIT, SAMPLES, Brokerage1099, LPage, Runner, k1_1065_labels, k1_kind,
                         model_fields, near_empty, page_png, slug)

HERE = Path(__file__).parent
ENGINES = {"olmocr": "olmOCR 2 (allenai/olmOCR-2-7B-1025-FP8)",
           "granite-docling": "granite-docling (ibm-granite/granite-docling-258M) in Docling's VLM pipeline"}
# Modal's list price for an L4 GPU, per second. The OCR's cost is its time per page at this rate: for olmOCR the
# batch's GPU time divided by its pages; for granite-docling each page's round trip, which overstates it when the
# server handles several pages at once.
L4_USD_PER_SECOND = 0.000222


def main_page(pages):
    """The page to read, from Docling's text: the K-1 or the 1099 summary. None when Docling couldn't tell."""
    for p in pages:
        if "consolidated form 1099" in p.text.lower():
            return p, "BROKER"
        if k1_kind(p.text):
            return p, k1_kind(p.text)
    return None, None


def form_of(text):
    """The form, from the OCR text: the Part III heading, or the form named in the title."""
    if "consolidated form 1099" in text.lower() or "1099-div" in text.lower():
        return "BROKER"
    if k1_kind(text):
        return k1_kind(text)
    m = re.search(r"Schedule K-1\s*\(Form (1065|1120-?S|1041)\)", text[:600], re.I)
    return m.group(1).upper().replace("-", "") if m else None


def granite_page(url, path, index):
    """One page (0-based) through Docling's VLM pipeline, with granite-docling served on Modal: Markdown, plus every
    text item and table cell with its box in PDF points from the top-left corner."""
    from docling.datamodel import vlm_model_specs
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import VlmPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling.pipeline.vlm_pipeline import VlmPipeline
    from docling_core.types.doc import CoordOrigin

    # Docling's own settings for granite-docling behind a vLLM server, pointed at the Modal one.
    spec = vlm_model_specs.GRANITEDOCLING_VLLM_API.model_copy(deep=True)
    spec.url = f"{url}/v1/chat/completions"
    spec.headers = {"Authorization": f"Bearer {ocr_modal.API_KEY}"}
    spec.timeout = 600
    # Two changes to the preset. granite-docling's DocTags are special tokens: with the preset's skip_special_tokens
    # the server strips them and Docling has nothing to parse. And a dense form runs past the preset's 4,096 tokens,
    # so it gets what the server's 8,192-token context leaves after the page image.
    spec.params["skip_special_tokens"] = False
    spec.params["max_tokens"] = 7000
    opts = VlmPipelineOptions(vlm_options=spec, enable_remote_services=True)
    converter = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_cls=VlmPipeline, pipeline_options=opts)})
    t0 = time.time()
    res = converter.convert(path, page_range=(index + 1, index + 1))
    seconds = round(time.time() - t0, 1)
    doc = res.document
    height = res.pages[0].size.height if res.pages else 792.0

    def box(bb):
        if bb.coord_origin != CoordOrigin.TOPLEFT:
            bb = bb.to_top_left_origin(page_height=height)
        return [round(bb.l, 1), round(bb.t, 1), round(bb.r, 1), round(bb.b, 1)]

    items = [{"text": t.text, "label": str(t.label), "bbox": box(t.prov[0].bbox)} for t in doc.texts if t.prov]
    for table in doc.tables:
        for cell in table.data.table_cells:
            if cell.bbox is not None and cell.text:
                items.append({"text": cell.text, "label": "table_cell", "bbox": box(cell.bbox)})
    return {"markdown": doc.export_to_markdown(), "items": items, "seconds": seconds}


def ocr_pages(engine, jobs):
    """OCR the (path, page) jobs on Modal that aren't cached yet; returns {(file, page): result}."""
    cache = HERE / "output" / "ocr" / engine
    cache.mkdir(parents=True, exist_ok=True)
    results, todo = {}, []
    for path, index in jobs:
        f = cache / f"{path.stem}-p{index + 1}.json"
        if f.exists():
            results[(path.name, index)] = json.loads(f.read_text())
        else:
            todo.append((path, index))
    if todo:
        print(f"{engine}: reading {len(todo)} pages on Modal")
        with modal.enable_output(), ocr_modal.app.run():
            if engine == "olmocr":
                pngs = [page_png(path, index)[0] for path, index in todo]
                outs = ocr_modal.OlmOCR().ocr.remote(pngs)
            else:
                url = ocr_modal.GraniteServer().serve.get_web_url()
                with ThreadPoolExecutor(8) as pool:
                    outs = list(pool.map(lambda job: granite_page(url, *job), todo))
        for (path, index), out in zip(todo, outs):
            (cache / f"{path.stem}-p{index + 1}.json").write_text(json.dumps(out))
            results[(path.name, index)] = out
    return results


def ocr_text(out):
    """The OCR's Markdown without olmOCR's front matter."""
    return re.sub(r"\A---\n.*?\n---\n", "", out["markdown"], flags=re.S).strip()


def place(f, items, page):
    """Put a value on the page at the granite-docling item whose text contains it (None when no item does)."""
    raw = (f["raw"] or "").strip()
    if not raw or f["key"] == "page":
        return None
    digits = re.sub(r"\D", "", raw)
    for it in items:
        text = it["text"]
        hit = (digits and digits in re.sub(r"\D", "", text) and len(digits) >= 2) or raw in text
        if hit:
            x0, y0, x1, y1 = it["bbox"]
            W, H = page.size[0] / (300 / 72), page.size[1] / (300 / 72)  # page size in points
            return [round(x0 / W, 4), round(y0 / H, 4), round(x1 / W, 4), round(y1 / H, 4)]
    return None


async def structure(runner, path, page, text, engine):
    form = form_of(text)
    doc = path.name
    if form is None:
        return None, None, None
    note = (f"Below is the text of one page of a tax document, as read by an OCR model ({ENGINES[engine]}). "
            "You don't have the image, so set every bbox to [0, 0, 0, 0]. Set confidence below 0.9 where the text "
            "looks garbled or a value is ambiguous.\n\n")
    if form == "BROKER":
        out = await runner.ask(doc, Brokerage1099, note + "Read the summary amounts of this consolidated brokerage 1099.\n\n"
                               + text, [])
        return form, None, out
    names = k1_1065_labels(2025) if form == "1065" else K1_LABELS[form]
    guide = "; ".join(f"{b} {label}" + (" (coded)" if k == "coded" else "") for b, (label, k) in names.items())
    out = await runner.ask(doc, FORMS[form], note + f"Read this Schedule K-1 (Form {form}). Part III boxes on this form "
                           f"include: {guide}. In a coded box, report one row per printed line with its code letter, "
                           "including lines whose amount is a dash and lines coded '*' with STMT.\n\n" + text, [])
    m = re.search(r"calendar\s*year\s*(20\d\d)", text, re.I)
    return form, int(m.group(1)) if m else out.tax_year, out


async def run(engine, model_name, files):
    layouts = {p: [LPage(x) for x in json.loads((LAYOUT / (p.stem + ".json")).read_text())["pages"]] for p in files}
    jobs = []
    for path, pages in layouts.items():
        main, _form = main_page(pages)
        jobs.append((path, (main or pages[0]).index))
    t0 = time.time()
    ocr = await asyncio.to_thread(ocr_pages, engine, jobs)
    print(f"OCR ready in {time.time() - t0:.0f}s")
    runner = Runner(model_name)
    out_dir = HERE / "output" / f"{engine}+{slug(model_name)}"
    (out_dir / "pages").mkdir(parents=True, exist_ok=True)

    failures = {}

    async def one(path, index):
        page = next(p for p in layouts[path] if p.index == index)
        o = ocr[(path.name, index)]
        text = ocr_text(o)
        try:
            form, year, out = await structure(runner, path, page, text, engine)
        except Exception as e:
            failures[path.name] = f"{type(e).__name__}: {str(e)[:200]}"
            print(f"{path.name}: failed: {failures[path.name]}")
            return None
        if form is None:
            fields = [{"key": "page", "label": "The whole page", "value": None, "raw": "", "page": index, "bbox": None,
                       "confidence": 0, "reasons": ["couldn't tell from the OCR text which form this is"]}]
        elif form == "BROKER":
            fields = model_fields(page, form, out, {})
        else:
            fields = model_fields(page, form, out, k1_1065_labels(year) if form == "1065" else K1_LABELS[form])
        page_review = near_empty(page, fields, form)
        if page_review:
            if not any(f["key"] == "page" for f in fields):
                fields.append({"key": "page", "label": "The whole page", "value": None, "raw": "", "page": index,
                               "bbox": None, "confidence": 0, "reasons": [page_review]})
        for f in fields:
            f["bbox"] = place(f, o.get("items", []), page) if engine == "granite-docling" else None
            f["status"] = "review" if f["reasons"] else "accepted"
        name = f"{path.stem}-p{index + 1}.jpg"
        img = page_png(path, index)[1]
        img.resize((page.size[0] // 2, page.size[1] // 2)).convert("L").save(out_dir / "pages" / name, quality=72)
        c = runner.cost.get(path.name, {})
        gpu_seconds = o.get("seconds", 0)
        return {"file": path.name, "form": form, "year": year, "source": f"{engine} OCR", "pages": {str(index): f"pages/{name}"},
                "ocr_text": text, "page_review": page_review, "second_read": "none",
                "seconds": round(gpu_seconds + c.get("seconds", 0), 1), "docling_seconds": 0.0, "ocr_seconds": gpu_seconds,
                "model_seconds": round(c.get("seconds", 0), 1),
                "cost_usd": round(c.get("usd", 0) + gpu_seconds * L4_USD_PER_SECOND, 6),
                "ocr_cost_usd": round(gpu_seconds * L4_USD_PER_SECOND, 6), "cost_missing_responses": c.get("cost_missing", 0),
                "input_tokens": c.get("input_tokens", 0), "output_tokens": c.get("output_tokens", 0),
                "model_calls": c.get("calls", 0), "failed_attempts": c.get("failed_attempts", 0), "fields": fields}

    results = await asyncio.gather(*(one(path, index) for path, index in jobs))
    docs = sorted((d for d in results if d), key=lambda d: d["file"])
    failed = [{"file": path.name, "error": failures.get(path.name, "no result")}
              for (path, _i), d in zip(jobs, results) if not d]
    (out_dir / "extracted.json").write_text(json.dumps({
        "pipeline": "OCR, then a text model alone", "label": f"{engine} OCR + {slug(model_name)} on the text",
        "model": model_name, "ocr": ENGINES[engine], "documents": docs,
        "failed_documents": failed}, indent=1))
    for d in docs:
        n = sum(f["status"] == "review" for f in d["fields"])
        print(f"{d['file']:38s} {str(d['form']):6s} {len(d['fields']):3d} values, {n:2d} to review, ${d['cost_usd']:.4f}")
    print(f"{out_dir.name}: {len(docs)} documents")
    if not docs:
        sys.exit(f"{out_dir.name}: every document failed, so there are no results")
    if failed:
        # Scored on the documents that finished, with the failed ones listed, as in extract_vlm.py.
        print(f"{out_dir.name}: {len(failed)} documents failed every retry: {', '.join(f['file'] for f in failed)}")
        sys.exit(PARTIAL_EXIT)


def main():
    engine, model_name = sys.argv[1], sys.argv[2]
    if engine not in ENGINES:
        sys.exit(f"engine is one of {', '.join(ENGINES)}")
    files = sorted(SAMPLES.glob("*.pdf"))
    if len(sys.argv) > 3:
        files = [f for f in files if any(a in f.name for a in sys.argv[3:])]
    asyncio.run(run(engine, model_name, files))


if __name__ == "__main__":
    os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")
    main()
