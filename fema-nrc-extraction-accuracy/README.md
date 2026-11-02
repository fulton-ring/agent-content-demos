# How accurate is AI extraction on long FEMA flood studies and old NRC scans?

Issue [#175](https://github.com/fulton-ring/agent-content-demos/issues/175). The argument was that on real agency documents the model matters less than three things decided before it runs: whether each page needed OCR, how long the document is, and how good the scan is. A second claim was that counting questions fail under retrieval and succeed once the facts are in a table. We measured each on public FEMA Flood Insurance Studies (FIS) and scanned NRC reports, with hand-checked answer keys, two models (Gemini 3.8 Flash and Claude Haiku 5.5) and up to five pipelines.

**In short:** routing decides the result and the model barely matters, as long as the model sees the page image. Length made no difference on born-digital studies. Scan quality hurt the pipelines that read OCR text, not the ones that read the image. Retrieval answered 2 of 10 counting questions; the extracted table answered all 10.

Read the four notebooks, each top to bottom (`uv run marimo edit 1_ocr_share.py`, or read them as plain Python):

1. [`1_ocr_share.py`](1_ocr_share.py): how many FIS pages need OCR, against Firecrawl's ~54% figure.
2. [`2_long_vs_short.py`](2_long_vs_short.py): field accuracy on short against long studies, scanned against born digital.
3. [`3_old_nrc_scans.py`](3_old_nrc_scans.py): what still comes out of 1975-1984 NRC scans, by scan quality.
4. [`4_counting.py`](4_counting.py): counting questions by retrieval against an extracted table.

[`common.py`](common.py) holds what they share: the document lists with hashes, page text, Tesseract, one typed model call, and value comparison (`norm` and `same`, adapted from `messy-document-parsing/pipelines.py`).

## Run it

```
./run.sh
```

You need [uv](https://docs.astral.sh/uv/) and `tesseract` (`apt install tesseract-ocr` or `brew install tesseract`). Every model answer is committed in `answers/`, so a run rescores without calling a model and needs no key. Delete a file in `answers/` and set `OPENROUTER_API_KEY` to call the model again. The documents (about 400 MB) are downloaded from FEMA and OSTI and hash-checked at run time, into `output/` (set `FEMA_NRC_OUTPUT_DIR` to change that). Results go to `results/`. A run from a fresh clone with no API key took 13-22 minutes on 4 CPU cores, most of it downloading (one file at a time) and Tesseract, and reproduced every file in `results/`.

**Data.** 70 FIS PDFs: every FIS report FEMA's Map Service Center listed on 2026-11-01 for 12 counties drawn with `random.Random(175)` from the Census county list. 10 NRC reports: drawn with the same seed from the 68 NUREG reports dated 1975-1984 that OSTI lists as NRC-sponsored with full text. **We couldn't reach ADAMS** from the machine this ran on (`adams.nrc.gov` was refused by the network, `www.nrc.gov/docs/` answered 403), so the NRC scans are OSTI's copies of the same NUREG reports.

**Answer keys.** [`fis_key.json`](fis_key.json): 404 values from one *Summary of Discharges* page per study (location, drainage area, four peak discharges), the page drawn by seed. Keyed by eye from the page image; on the four born-digital pages all 222 values were then found in order in the text layer, and on the four scans Tesseract agreed on 177 of 182 and the other five were rechecked on the image. [`nrc_key.json`](nrc_key.json): 717 numbers from one seeded page per report, keyed in three ways. On six pages it is Gemini 4 Argon's transcription (Argon isn't one of the tested models), checked on the image wherever it disagreed with both the PDF's OCR layer and Tesseract. On three pages it is the majority of those three reads. On one dot-matrix page, rows 1-15 were keyed by eye. The file records how each page was keyed. Both keys were made by the AI worker, not checked by a person. One blank FIS row (39151CV001C, "Just US from confluence of Plum Creek") was added to the key after the first model answers listed it. It is on page 49, all `*`, and holds no scored values, but it brings the location count to 88. Without it, counting Q1 and Q4 would have been 87 and 12, and the table arm would have scored 8/10.

## Results

From the run on 2026-11-01. Model calls cost $1.56 in all (answers in `answers/`), plus about $1.80 for a first run that we discarded: it left Gemini's thinking at its default and some calls spent all 16,000 tokens thinking before answering, so we set thinking to low, as the K-1 spike does, and ran everything again.

### 1. Share of FIS pages that need OCR

| | Pages | Share |
|---|---|---|
| Text layer of 50+ characters | 1,532 | 41% |
| Scan with no text layer | 1,161 | 31% |
| Vector drawing, no text (flood profiles) | 1,035 | 28% |
| Blank | 32 | 1% |
| **Need OCR (scan or drawing)** | **2,196 of 3,760** | **58%** |

**Only 13 of the 70 PDFs (19%) need no OCR at all, against Firecrawl's ~54%**, or 44% if the flood profiles are set aside. 34 PDFs are scans from cover to cover. Every page of the 26 studies effective before 2000 needs OCR; 64% of pages in 2000-2009 studies; 44% since 2010, nearly all of them flood profile drawings. The cheap classifier (text characters, image coverage, vector paths) agreed with Tesseract's verdict on 198 of 200 seeded pages.

### 2. Long against short: share of keyed values right

Two studies per group: short is 19-26 pages, long is 81-127.

| Pipeline | Model | Short digital | Long digital | Short scan | Long scan |
|---|---|---|---|---|---|
| Text layer of the page | either | 100% | 100% | 0% | 0% |
| Tesseract text of the page | Flash | 100% | 61% | 47% | 78% |
| | Haiku | 100% | 61% | 29% | 30% |
| Page image | either | 100% | 100% | 100% | 100% |
| Whole study as text, no page given | either | 100% | 100% | n/a | n/a |
| Whole study as PDF, no page given | Flash | 100% | 100% | 100% | 97% |
| | Haiku | 100% | 100% | 65% | 33% |

- **Routing decides the result.** The page image read all 404 values right with both models. Trusting the text layer gives nothing on a scan. Tesseract then a model failed on a table printed sideways (060724V000: Haiku 0 of 12, Flash 3 of 12) and on a ruled table whose cells Tesseract read column by column (39151CV001C: 8 of 65 for both models).
- **Length made no difference on born-digital studies.** Handed the whole 100- or 127-page study with no page number, both models found the table and got every value right, as text or as PDF. We didn't see ExtractBench's long-document drop here.
- **Long scans broke one model.** Haiku's API rejected the whole 112-page, 25 MB scan (HTTP 400, four attempts) and found only half a 24-page scan's values. Flash read the whole 112-page scan at 95% (105 of 110 values), with 5 wrong.
- **The errors look right.** Tesseract then Flash gave 31 wrong values on 080290V000, and both models 6 on 51005CV000A: believable discharges, not garbage.
- **Cost per page:** reading a page image cost $0.0008 with Haiku (4.7 s) and $0.0044 with Flash (10.5 s). A whole study as one PDF cost $0.0006-0.0007 a page.

### 3. Old NRC scans: share of keyed numbers found

Scan quality is Tesseract's mean word confidence on the keyed page, split into thirds (poor 63-85, fair 86-89, good 92-94).

| Pipeline | Model | Poor | Fair | Good | All 717 | Extra numbers |
|---|---|---|---|---|---|---|
| Text layer the PDF carries | none | 57% | 91% | 91% | 72% | 78 |
| Tesseract | none | 62% | 66% | 87% | 69% | 30 |
| Text layer, then model | Haiku / Flash | 50% / 79% | 83% / 94% | 91% / 91% | 67% / 85% | 27 / 10 |
| Tesseract, then model | Haiku / Flash | 60% / 83% | 69% / 74% | 87% / 97% | 68% / 85% | 26 / 18 |
| Page image | Haiku / Flash | 99.5% / 72% | 98.5% / 96% | 99.5% / 99.5% | 99.3% / 84% | 5 / 1 |

- **Scan quality decides what OCR text gives you, not what the image gives you.** On the poor third, the OCR layer the PDF already carries held 57% of the numbers; Haiku reading the image found 99.5%. On a 1981 dot-matrix printout the OCR layer held 36 of 177 numbers and both models reading the image got all 177.
- **Gemini refused a page.** Flash's 72% on the poor third is one page it wouldn't read: a 1980 table of fuel particle leakage from a reactor vessel (NUREG/CR-1724), blocked four times by Gemini (HTTP 502, "blocked the response: OTHER", no reason given). Without it Flash found 599 of 608 (98.5%).
- A model reading OCR text can't recover what the OCR lost: on the dot-matrix page Haiku gave up and returned only the title.

### 4. Counting questions

Ten counting, totalling and ranking questions over the eight keyed FIS pages (88 locations), written before any answers came back.

| Approach | Right of 10 |
|---|---|
| Retrieval: BM25 picks 8 chunks of ~600 characters, Flash answers | 2 |
| Whole text of all eight pages to Flash | 10 |
| Notebook 2's extracted table, queried with pandas | 10 |

Retrieval answered "2" to "how many locations are listed" (right: 88) and 0 to the Jackson River total (right: 167,000 cfs): the chunks it picked held part of the data, and the model counted what it saw. The founders' draft "Beating the financebench RAG dataset" turned out to be notes on parsers and BM25-first retrieval with no counting test, so it doesn't already make this argument.

## What didn't work, and what this doesn't show

- **Small keys.** 404 FIS values on 8 pages and 717 NRC numbers on 10 pages. The short scans carry only 17 FIS values, so their percentages move with one error. Each pipeline ran once; answers vary from run to run (see `messy-document-parsing/`).
- **"Long" here is 81-127 pages.** None of the 70 sampled studies is longer than 167 pages. The 300-plus-page documents some benchmarks use may still show a drop.
- **Length and scanning go together.** Old FEMA studies are scans and new ones are digital. We separated them by drawing two studies in each of the four groups, not by finding long scans in general.
- **The NRC metric counts numbers, not fields.** A number found in the wrong place still counts as found. On the partly keyed dot-matrix page (177 key numbers, only 91 distinct; "4206" appears 17 times), a transcript of the whole page of about 700 numbers can match the key without rows 1-15 being read right. So its 177/177, and the poor third's 99.5%, are upper bounds.
- **Whole text fits only because the set is small.** Eight pages fit in one prompt. A real archive doesn't, which is where the table pays off.
- **Not ADAMS.** The NRC scans are OSTI's copies; ADAMS may hold different scans of the same reports.
- **What we looked at first.** Firecrawl's `pdf-inspector` decides from content streams whether a page has text and images, but publishes no thresholds; ours follows the same idea in a few lines of `pypdfium2`. The pipelines reuse the repo's earlier pattern (typed Pydantic AI calls through OpenRouter, answers saved and reused) and its value comparison. We left out Docling, because the issue asked for a text-layer read, an open OCR model and a vision model, and `messy-document-parsing/` already measured Docling on harder pages.
