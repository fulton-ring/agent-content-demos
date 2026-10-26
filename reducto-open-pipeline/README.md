# Rebuilding Reducto's parse and extract with Docling and Gemini

Reducto sells document parsing: *Parse* turns a document into sections, tables and chunks with bounding boxes, *Split* finds the sections of a long file, and *Extract* fills a JSON schema from what Parse saw. Can an open pipeline do the same? Docling or LlamaIndex would handle layout, and a vision language model such as Gemini 3.8 Flash would read the pages. This spike measures that on two tasks with answer keys:

1. **Schema extraction**: the K-1 spike's 30 tax documents and its answer key, read by three pipelines and scored by the K-1 spike's own scoring notebook, so the numbers sit next to its README's.
2. **Section parsing**: two long FEMA Flood Insurance Studies for Henrico County, Virginia. One is a scanned typewritten report from 1980 (65 pages), the other a born-digital report from 2024 (94 pages). A hand-checked key gives their 69 numbered headings, the page each starts on, and six tables (587 cells).

**Read the two notebooks**, each top to bottom. Open one with `uv run marimo edit 1_schema_extraction.py`, or read them as plain Python:

1. [`1_schema_extraction.py`](1_schema_extraction.py): the VLM alone, Docling's text then the model, and Docling routing then the VLM.
2. [`2_section_parsing.py`](2_section_parsing.py): Docling alone, the VLM alone, and Docling then the VLM, on headings, section boundaries and tables.

## Run it

```
./run.sh
```

You need [uv](https://docs.astral.sh/uv/), the `tesseract` binary (`apt install tesseract-ocr` or `brew install tesseract`), `OPENROUTER_API_KEY`, and the K-1 spike's folder next to this one (it's in this repository). `run.sh` first runs the K-1 spike's `1_documents.py`, unchanged and in its own pinned environment, to make the 30 documents. It then runs the two notebooks as scripts, so the numbers come from the code you read. Notebook 1 runs the K-1 spike's `3_results.py`, also unchanged, to score its pipelines. Everything goes to `output/` (set `REDUCTO_OUTPUT_DIR` to write elsewhere). Model answers are saved in `output/answers/` and reused on a re-run; delete that folder to call the model again. A clean run took RUNTIME on 4 CPU cores and cost RUNCOST.

## Look first: what Reducto documents, and what the open tools cover

- **Reducto** ([docs](https://docs.reducto.ai/overview)). Parse returns chunks of Markdown, each with typed blocks (title, section header, table, figure, key-value) that carry a page, a bounding box and a confidence. Word- and cell-level citations are an option, but they [can't be combined](https://docs.reducto.ai/configs/parse/citations) with joining tables across pages. Split takes plain-language section descriptions and returns page ranges; it "runs Parse … then uses an LLM to classify pages". Extract takes a JSON schema and "can only return what Parse sees". The current parser, r-1, is "one full-page model" that reads "digital text, scans, handwriting". [List prices](https://docs.reducto.ai/reference/credit-usage) per 1,000 pages: Parse $10, Extract $20, Split $20. It publishes no per-page speed, but guarantees 200 to 500+ concurrent pages by tier.
- **Benchmark.** Reducto's [RD-TableBench](https://huggingface.co/datasets/reducto/rd-tablebench) is 1,000 table images with a public answer key. Its licence is CC-BY-NC-ND-4.0, which doesn't fit a commercial blog's demo, and it scores single table images, not long documents or forms, so we built our own keys. Reducto's forms benchmark, RD-FormsBench, was announced but we found no release.
- **Docling** (MIT): layout, reading order, OCR, table structure, section headers, chunking, per-element boxes, and VLM pipelines. **LlamaIndex** (MIT) is the framework and its node parsers; **LlamaParse** is a paid cloud service, so it's out under this repo's rules. **Marker** (code Apache-2.0, weights free only under $5M revenue) and **MinerU** (Apache-2.0 with extra terms) cover the same ground as Docling, with an optional LLM pass. The open **Unstructured** library partitions and chunks by title; its own README puts its table-cell accuracy at 0.43, against 0.87 for its paid API. Each open tool covers layout and tables, none covers schema extraction without a model, and we used Docling because the K-1 spike already does.

## Results

From a clean run of `./run.sh` from a fresh clone on 2026-10-26 (run 2), with run 1 earlier the same day for comparison. All model calls are Gemini 3.8 Flash on OpenRouter at temperature 0.

### Schema extraction, the K-1 spike's 30 documents

SCHEMA_TABLE

"Wrong but accepted" is a wrong value accepted without review, or a box on the key a run never reported. All three pipelines use only the K-1 spike's per-value review rules (confidence, STMT, malformed amounts, unknown or repeated boxes), not its cross-checks or its whole-page check, so the difference between them is the pipeline. The italic row is the K-1 spike's own pipeline with all its rules, from its README.

SCHEMA_FINDINGS

### Section parsing, two flood studies

SECTION_TABLE

SECTION_FINDINGS

## Failure types, and what would fix each

FAILURES

## Where fine-tuning would earn its cost

FINETUNE

## The case against: what Reducto does that this pipeline doesn't

CASE_AGAINST

## Verdict

VERDICT

## What it doesn't show

- **Two runs aren't an error rate.** The K-1 spike saw Gemini's misreads come and go between runs; these two runs can't pin down any pipeline's rate.
- **Two flood studies with numbered headings are an easy outline.** Every heading carries its number. Reports with unnumbered headings, two columns, or headings set only by font size would test section parsing harder. That's [a follow-up issue](https://github.com/fulton-ring/agent-content-demos/issues/130).
- **No table here is longer than two pages.** The 2024 study's Table 23 runs 32 pages; we keyed one.
- **No handwriting**, and no tables that change columns between pages.
- **The VLM's bounding boxes weren't checked.** Docling's boxes come from the page; Gemini's are its own claim.
- **Docling ran on CPU.** On a GPU it would be several times faster.

## Files

- `1_schema_extraction.py`, `2_section_parsing.py`: the two notebooks
- `model_call.py`: one typed, cost-counted, saved model call, which both notebooks use
- `section_key.json`: the hand-checked key for the two flood studies
- `run.sh`, `pyproject.toml`, `uv.lock`: the one command and its pinned environment
- `results/`: the result tables and failure lists from the run above
