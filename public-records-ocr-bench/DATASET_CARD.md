---
license: other
license_name: mixed-us-government-works
language:
- en
task_categories:
- image-to-text
tags:
- ocr
- olmocr-bench
- government-documents
- tables
pretty_name: US Public Records OCR Bench (seed)
size_categories:
- n<1K
---

# US Public Records OCR Bench (seed, draft card, not published)

This is a draft card. Publishing is a founder decision (issue #318). The tests below are AI-made and haven't been person-checked yet.

676 [olmOCR-Bench](https://huggingface.co/datasets/allenai/olmOCR-bench)-format unit tests on 18 single pages of US federal records:

- 8 *Summary of Discharges* pages from FEMA Flood Insurance Studies: 4 born digital, 4 scanned, 2 of them sideways tables.
- 10 pages of 1975-1984 NRC reports (NUREG and NUREG/CR) as scanned by OSTI, split into thirds by scan quality.

## Files

- `fis_born_digital.jsonl`, `fis_scanned.jsonl`: `table` tests. Each keyed number must be in a table cell next to its row neighbour. There are also `present` tests for flooding source names.
- `nrc_poor_scan.jsonl`, `nrc_fair_scan.jsonl`, `nrc_good_scan.jsonl`: `present` tests. Each is a number of three or more characters printed on the page.
- `headers_footers.jsonl`: `absent` tests. The printed page number must not appear at the start or end of the output.
- `pdfs/`: the 18 single-page PDFs, if publishing them is cleared (see Licensing). Otherwise use the download script in the source repo.

Score a pipeline with `python -m olmocr.bench.benchmark --dir <this folder>` after writing `<pipeline>/<pdf>_pg1_repeat1.md` for each page.

## Baseline scores (one run each, olmOCR scorer, average of per-file scores)

| Pipeline | Score |
|---|---|
| Image → Claude Haiku 5.5 | 98.8% ± 1.2 |
| Image → Gemini 3.8 Flash | 96.2% ± 2.4 |
| Image → Qwen3-VL-8B-Instruct | 84.0% ± 2.6 |
| Tesseract 5 → Claude Haiku 5.5 | 75.8% ± 2.7 |
| PDF text layer | 58.1% ± 4.3 |
| Tesseract 5 | 56.4% ± 4.1 |

## How it was made

Answer keys were made by an AI worker for a previous study. FEMA pages were keyed from the page image and checked against the text layer or Tesseract. NRC pages were keyed by comparing three reads (the PDF's OCR layer, Tesseract and a separate vision model), checking disagreements on the image. The keys were converted to tests by `bench.py` in [fulton-ring/agent-content-demos](https://github.com/fulton-ring/agent-content-demos/tree/main/public-records-ocr-bench). Person check: not yet done.

## Limitations

- **It's small:** 18 pages. Frontier vision models nearly saturate it.
- **NRC tests check that a number appears, not where it appears.**
- **Text-only pipelines can't pass table tests,** because olmOCR requires Markdown or HTML tables.

## Licensing

- **FEMA Flood Insurance Studies** are federal publications. FEMA states that most of its material is free of copyright.
- **NUREG/CR reports were written by government contractors** and carry no copyright notice. OSTI advises treating unmarked items as copyrighted, while DOE policy gives such reports unlimited distribution. NUREG/CR-1724 contains conference papers with contractor licence notices.
- **To settle before publishing:** whether to include the page PDFs, or to ship only the tests and a download script.
