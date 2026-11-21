# Can our FEMA and NRC answer keys become an open OCR benchmark for US public records?

Issue [#318](https://github.com/fulton-ring/agent-content-demos/issues/318). We turned the answer keys from
`fema-nrc-extraction-accuracy/` (PR #177) into [olmOCR-Bench](https://github.com/allenai/olmocr/tree/main/olmocr/bench)
unit tests and scored six pipelines with olmOCR's own scorer. We also wrote a review file so a person can check each test against the page.

**In short:**
- **Yes, the keys convert:** they give 676 tests on 18 pages, in a format anyone can score with `olmocr.bench.benchmark`.
- **As a benchmark, it's nearly saturated at the top.** Claude Haiku 5.5 reading the page image passed 99.3% of the tests and Gemini 3.8 Flash 97.3%, on scans and born-digital pages alike.
- **It separates pipeline types sharply.** The PDF text layer passed 31% and Tesseract 31%; Tesseract followed by a model passed 64%; the open 8B vision model passed 77%.
- **The person check hasn't been done yet.**
- **It's small:** 18 pages, against olmOCR-Bench's 1,403.

[`bench.py`](bench.py) is the whole spike, a marimo notebook to read top to bottom (`uv run marimo edit bench.py`). It covers prior art, the conversion, the pipelines, the scores, the review file and what didn't work.

## Run it

```
./run.sh
```

You need [uv](https://docs.astral.sh/uv/) and `tesseract` (`apt install tesseract-ocr` or `brew install tesseract`).
The run downloads the 18 source PDFs (about 150 MB) from FEMA and OSTI and checks their hashes. It cuts the keyed pages into `bench/pdfs/`, which isn't committed, and rebuilds the tests. It then rescores the committed pipeline outputs and writes `results/scores.md`, `output/review.html` and `results/olmocr_benchmark.txt` (olmOCR's own report, with baseline checks and bootstrap confidence intervals).
Every model output is committed in `bench/<pipeline>/`, so a run needs no API key. To call a model again, delete a page's `.md` file and set `OPENROUTER_API_KEY`.
A run from a fresh clone took about 3 minutes on 4 cores, most of it downloading and Tesseract.

**Score your own pipeline:** write one Markdown file per page to `bench/<your_name>/<pdf>_pg1_repeat1.md`, then run
`uv run python -m olmocr.bench.benchmark --dir bench`.

## What's in it

| Group (JSONL) | Pages | Tests | Test types |
|---|---|---|---|
| `fis_born_digital` | 4 FIS *Summary of Discharges* pages | 213 | 201 table, 12 present |
| `fis_scanned` | 4 FIS pages, two of them sideways tables | 192 | 176 table, 16 present |
| `nrc_poor_scan` | 4 NRC pages (Tesseract confidence 63-85) | 166 | present |
| `nrc_fair_scan` | 3 NRC pages (86-89) | 41 | present |
| `nrc_good_scan` | 3 NRC pages (92-94) | 47 | present |
| `headers_footers` | 17 pages with a printed page number | 17 | absent |
| **Total** | **18 pages** | **676** | |

- **FIS table tests:** every keyed number must sit in a table cell, with the row's neighbouring value beside it, and each drainage area must sit next to its location. This checks that values stay in their rows.
- **NRC present tests:** the NRC key is a bag of numbers per page with no positions. So each distinct number of three or more characters must appear somewhere in the output (254 tests from the key's 432 distinct numbers per page).
- **Absent tests:** these are olmOCR's header and footer check. The printed page number must not appear at the start or end of the output.

## Results

Share of tests passed (%), from `results/scores.md`:

| Pipeline | FIS digital | FIS scanned | NRC poor | NRC fair | NRC good | Headers/footers | All |
|---|---|---|---|---|---|---|---|
| PDF text layer | 5.6 | 0 | 60.2 | 92.7 | 100 | 70.6 | 30.9 |
| Tesseract 5 | 5.6 | 2.6 | 66.9 | 61.0 | 100 | 58.8 | 31.1 |
| Tesseract → Claude Haiku 5.5 | 82.2 | 33.9 | 65.7 | 48.8 | 100 | 100 | 64.1 |
| Image → Claude Haiku 5.5 | 100 | 99.5 | 99.4 | 92.7 | 100 | 100 | 99.3 |
| Image → Gemini 3.8 Flash | 100 | 100 | 92.2 | 92.7 | 100 | 88.2 | 97.3 |
| Image → Qwen3-VL-8B (open weights) | 92.5 | 40.6 | 96.4 | 58.5 | 100 | 100 | 77.4 |

olmOCR's own scorer, which averages the per-group scores and adds baseline tests, ranks the pipelines in the same order: Haiku 98.8% ± 1.2, Gemini 96.2 ± 2.4, Qwen 84.0 ± 2.6, Tesseract → Haiku 75.8 ± 2.7, text layer 58.1 ± 4.3, Tesseract 56.4 ± 4.1.

- **The best vision models saturate it.** Haiku missed 5 of 676 tests, and Gemini missed none of the 405 FIS tests. Our hypothesis was that vision models would saturate the born-digital pages and split on the poor scans. They didn't split: Haiku scored 99.4% on the poor scans. Haiku's 5 misses were 3 axis labels on a chart, which every vision model left out; "Tenmile Creek" misread as "Tennile Creek"; and one number on the dot-matrix page. Gemini's 18 misses were the same 3 axis labels, 2 page numbers it left in, and 13 numbers on one page it cut short (see below).
- **Text pipelines fail the table tests by design.** olmOCR's table tests need a Markdown or HTML table. The born-digital text layer holds every FIS number in order but scores 5.6%. On the NRC number tests, the text layer the scans already carry scored 60% on poor scans.
- **The open 8B model is where the split is.** Qwen3-VL-8B looped on one sideways FIS table, repeating a row until it hit the token limit: 4% on that page and 40.6% on scanned FIS. It also scored 9% on an NRC chart page and 56% on a table page. It took 70 s a page against 7 s for Haiku.
- **Gemini stopped mid-table on NRC/CR-1724 page 77.** It returned 76% of that page with no error. This is the same page Gemini refused outright in the source spike.
- **Cost and time:** model calls cost **$0.15** in all, against a $5 budget: Gemini $0.076, Qwen $0.031, Tesseract → Haiku $0.023, Haiku $0.023. One Qwen call hung with no timeout in the first run; we added a 240 s timeout and reran that page.

## Person check: not yet checked

`output/review.html` lists all 676 tests. Each shows what it expects and a crop of the page with the value boxed ([screenshot](review_screenshot.png)). 512 tests have a crop; for the rest, where Tesseract couldn't find the value (poor scans, the ruled table on 39151CV001C), the reviewer uses the whole page shown above each page's tests.
The reviewer marks each test right or wrong and downloads `review_decisions.json` into `bench/`. The next `./run.sh` then writes the verdicts into olmOCR's `checked` field and reports how many tests the check overturned.
olmOCR's own review app also works on the whole page: `uv run python -m olmocr.bench.review_app bench/fis_scanned.jsonl`.
Test IDs are numbered in build order, so freeze the tests before the check starts.

## Prior art and reuse

- **No public OCR benchmark built from US agency records turned up.**
  - [olmOCR-Bench](https://huggingface.co/datasets/allenai/olmOCR-bench) draws on arXiv, the Internet Archive, AI2's crawl and Library of Congress letters (the "old scans" set, 98 PDFs of correspondence).
  - The closest in method is [KDoc-OCRBench-V2](https://huggingface.co/datasets/ONTHEIT/KDoc-OCRBench-V2): olmOCR format, 849 Korean public-sector pages, 56,197 person-reviewed tests.
  - The closest in documents is LlamaIndex's [ExtractBench](https://github.com/run-llama/ExtractBench) (49 US government forms, schema extraction).
  - OmniDocBench, READoc, CC-OCR, FUNSD and DocVQA hold no US agency records.
- **FEMA:** "Most material on FEMA.gov is free of copyright" (FEMA website information page). The Map Service Center states no terms.
- **NRC:** NUREG/CR reports are contractor works, so [17 U.S.C. 105](https://www.law.cornell.edu/uscode/text/17/105) doesn't cover them.
  - [OSTI's copyright page](https://www.osti.gov/copyright) says to treat unmarked items "as if they are protected by copyright".
  - DOE's [STI copyright rules](https://www.osti.gov/stip/submit/submission-basics/sti-copyright) say a contractor report without permission to claim copyright gets "no copyright marking" and "unlimited distribution".
  - None of the ten reports carries a copyright notice, but NUREG/CR-1724's conference papers carry contractor licence notices.
  - So the PDFs are downloaded, not committed. Whether the page PDFs can go into a published dataset is a founder decision.
- **What we looked at first:**
  - olmOCR's `bench` package supplied the test format, the scorer, the prompt (`build_basic_prompt`) and its review app.
  - The pipelines follow the source spike, using typed Pydantic AI calls through OpenRouter. The model output type is a plain `str`, because the output *is* the page's Markdown.
  - olmOCR 2, Chandra and PaddleOCR-VL need a GPU and aren't on OpenRouter, so Qwen3-VL-8B stands in as the open model.

## What this doesn't show

- **18 pages are a seed, not a benchmark.** A useful public-records set needs far more poor scans, and probably permits and handwritten forms, which is where the top models might stop saturating.
- **NRC tests check that a number is printed, not where.**
- **The tests are AI-made** (the source keys, and the page labels read by this worker) until the person check is done.
- **Each pipeline ran once.**
- [`DATASET_CARD.md`](DATASET_CARD.md) is a draft Hugging Face card. Nothing is published.
