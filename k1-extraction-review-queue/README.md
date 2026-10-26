# K-1 extraction with a review queue

This demo reads Schedule K-1s and brokerage 1099s and links every extracted value to the box it came from. Anything the software isn't sure of goes to a review queue for a person to check. It answers a sales question for the CPA document extraction play: can we show a tax preparer what they'd get, with screenshots of real sample documents, without them sending us any documents?

It compares five current vision-language models, three of them open-weight, and two OCR models run on Modal's GPUs. They all read the same documents and are scored against the same answer keys. Each model runs on its own, and Gemini 3.8 Flash and Qwen 3.8 27B also run as a pair that must agree. Docling reads the page layout and the supplemental statements. Pydantic AI turns each model's answer into typed values, each with a page, a box and a confidence.

**Read the three notebooks in order** for the whole story, each top to bottom. Open one with `uv run marimo edit 1_documents.py`, or read them as plain Python:

1. [`1_documents.py`](1_documents.py): the question, and the 30 documents and their answer keys.
2. [`2_extraction.py`](2_extraction.py): Docling, what each model is asked for, the review rules, every model, the pair and the OCR models.
3. [`3_results.py`](3_results.py): scoring, the results, the review screens, and what didn't work.

![A value on a real K-1, highlighted on the page it came from](screenshots/1-value-linked-to-box.png)

## Run it

```
./run.sh               # the whole comparison, including the three Gemma re-runs below
./run.sh --screenshots # also retakes screenshots/ from Gemini 3.8 Flash's review screen
./run.sh --gemma-google # only Gemma 4 31B with Google's recommended settings, three times (about $0.13)
```

You need:

- [uv](https://docs.astral.sh/uv/);
- the `tesseract` binary (`apt install tesseract-ocr` or `brew install tesseract`), which Docling uses for scanned pages;
- `OPENROUTER_API_KEY`;
- for the OCR models, `MODAL_TOKEN_ID` and `MODAL_TOKEN_SECRET`. Without them the OCR models are skipped.

For the screenshots, Playwright installs Chromium, or set `CHROMIUM_PATH` to one you have.

`run.sh` runs the three notebooks as scripts, in order, so the numbers come from the code you read. They hand their results on through files in `output/`. uv builds the environment on the first run; Docling brings a CPU build of PyTorch. The notebook downloads the real sample K-1s and the blank IRS forms and checks their hashes. It makes the scanned copies and the made-up documents, runs Docling, runs the five models side by side, pairs two of them, runs the OCR models, and scores everything. It writes:

- `output/comparison.md`: every run, broken down by kind of document;
- `output/<run>/index.html`: each run's review screen;
- `output/<run>/metrics.json`: each run's scores, failed documents and cost.

The model answers are saved under `output/answers/`, and re-running reuses them. Delete that folder to call the models again. Set `K1_OUTPUT_DIR` to write somewhere other than `output/`.

## The documents

- **Three real K-1s (Form 1065)**, the sample packages that Enviva Partners (2018, 2021) and The Blackstone Group (2019) publish for their unitholders. They are downloaded from the issuers' sites at run time, not committed. `real_answer_key.json` is keyed by hand from them.
- **Nine scanned copies** of those K-1 pages, made at run time: office scans and bad scans.
- **Eighteen made-up documents**: 1120-S and 1041 K-1s filled in on the blank IRS forms, and brokerage consolidated 1099s. Every name and amount is invented, and every one is image-only. The generator writes their answer key.

The held-out set is 14 documents whose scans and values come from seeds that weren't used while building the review rules.

## Results

From a clean run of `./run.sh --screenshots` from a fresh clone on 2026-10-18. It took 26 minutes on 4 cores, with uv's package cache already warm. Docling took 8.3 seconds a document, and the whole run cost $1.36. Earlier runs took 36 to 81 minutes and cost $1.20 to $1.45, depending mostly on the CPU and the environment build.

"Boxes" means every box on the answer key plus every value a run reported, so reading something in an empty box counts as an error. "Wrong but accepted" is a wrong value accepted without review, or a box on the key the run never reported, since a missed row reads as a blank box. It is the number that matters for a review queue.

| Pipeline | Values right | Accepted without review | Wrong but accepted | Sent to review (STMT) | Cost per document | Model time per document |
|---|---|---|---|---|---|---|
| **Gemini 3.8 Flash** | **676 of 676** | **652** | **0** | **24 (24)** | **$0.0064** | **11.8 s** |
| Qwen3-VL 235B (open weights) | 667 of 680 | 651 | 6 | 29 (22) | $0.0037 | 31.8 s |
| Qwen 3.8 27B (open weights) | 636 of 708 | 685 | 64 | 23 (14) | $0.0054 | 61.7 s |
| GLM 5.3 Flash | 520 of 734 | 611 | 115 | 123 (21) | $0.0013 | 9.3 s |
| Gemma 4 31B (open weights) | 380 of 740 | 575 | 205 | 165 (2) | $0.0068 | 20.1 s |
| olmOCR 2 on Modal, then Gemini 3.8 Flash on the text | 550 of 703 | 557 | 73 | 146 (11) | $0.0071 | 12.0 s GPU + 5.6 s |
| granite-docling on Modal, then Gemini 3.8 Flash on the text | 252 of 678 | 74 | 8 | 604 (24) | $0.0147 | 59.5 s GPU + 1.8 s |
| **Gemini 3.8 Flash + Qwen 3.8 27B, must agree** | **676 of 708** | **621** | **0** | **87 (24)** | **$0.0118** | **61.7 s** |

Every pipeline finished all 30 documents in this run. On the held-out set, Gemini 3.8 Flash accepted 299 boxes, all right, and sent 11 to review. The pair accepted 289, all right. Gemini read all 62 supplemental statement lines behind the STMT boxes correctly, as in every earlier run. Docling's layout pass adds its own seconds per document on CPU to every vision-model row. `output/comparison.md` breaks every run down by kind of document.

**Gemini alone, or checked by an open model.** Gemini 3.8 Flash's own confidence never flags anything: everything it sends to review is a STMT amount or a malformed one. In four of the eight earlier runs it accepted a misread on a bad scan at confidence 95, a box shift on Enviva 2018 or a wrong code letter on Enviva 2021, each costing 2 boxes. It made no such misread in this run or in either of the other two runs on 2026-10-18. The pair with Qwen 3.8 27B caught every one of those misreads and has let nothing wrong through in any run. It costs 50 to 100% more and sends 25 to 89 more values to review, almost all of them rows Qwen skipped or filed under the wrong box. The pair is the safer default for client documents, and the one to show a CPA firm when the point is that wrong values don't get through.

**Reading the image, or reading text.** olmOCR got nearly all the characters off the page, but once a K-1 is text, the box an amount belongs to is easy to lose. Gemini reading the image was right on 676 of 676 values. Gemini reading olmOCR's text of the same pages was right on 550 of 703.

### How much the results vary between runs

The open models' answers change from run to run at temperature 0, by a lot. Wrong but accepted, run by run. Runs 1 to 8 are from 2026-10-13 to 2026-10-17, from the code before it became notebooks. Run 9 is that code on 2026-10-18 without the OCR models. Runs 10 and 11 are the notebook version on 2026-10-18, run 11 being the one above; it was then one notebook, since split into these three with the same code:

| Pipeline | Wrong but accepted, runs 1 to 11 | Cost per document, range |
|---|---|---|
| Gemini 3.8 Flash | 0, 0, 0, 0, 2, 2, 2, 2, 0, 0, 0 | $0.0064 to $0.0066 |
| Qwen3-VL 235B | 29, 6, 13, 22, 3, 6, 4, 16, 7, 6, 6 | $0.0037 to $0.0040 |
| Qwen 3.8 27B | 25, 57, 91, 32, 61, 56, 31, 38, 54, 58, 64 | $0.0034 to $0.0063 |
| GLM 5.3 Flash | 14, 4, 88\*, 4, 13, 13†, 70\*, 2†, 67‡, 70‡, 115‡ | $0.0009 to $0.0020 |
| Gemma 4 31B | 211, 278, 222, 239, 235, 220, 241, 232, 229, 197, 205 | $0.0015 to $0.0076 |
| olmOCR 2 + Gemini | –, 69, 84, 87, 76, 86, 70, 70, –, 68, 73 | $0.0071 to $0.0074 |
| granite-docling + Gemini | –, 26, 14, 12, 20, 2, 19, 8, –, 7, 8 | $0.0124 to $0.0219 |
| Gemini + Qwen 3.8 27B pair | 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0 | $0.0099 to $0.0127 |

\* Near-empty answers on the brokerage 1099s, before the three-quarter page check (see `2_extraction.py`, section 3). In runs 9 to 11 that check sent all six of GLM's 4-value 1099 answers to review.
† GLM failed every retry on 5 (run 6) and 4 (run 8) of the 6 brokerage 1099s; those runs score the other documents.
‡ Mostly the wrong form. When Docling can't tell which form a scan is, the model is asked. In each of runs 9 to 11, GLM named the same 7 made-up 1120-S and 1041 scans as the wrong form, almost always "Form 1065", and read them with that form's boxes. That gave 66, 66 and 70 wrong accepted values. In run 11 it also named the Blackstone office scan "Form 1041", which added 44. The other vision models named every form right.

Run 1 to 3 costs leave out failed retries; later runs count every attempt. Gemma 4 31B runs out of its 8,000 output tokens on some documents every run (5 times in run 11) and finishes after retries.

### Gemma 4 31B with Google's recommended settings

Is Gemma's F down to the model or to how we called it ([#106](https://github.com/fulton-ring/agent-content-demos/issues/106))? We called it at temperature 0, with the default image budget, on whichever OpenRouter host was picked. `./run.sh --gemma-google` re-runs only Gemma 4 31B, three times, with [Google's recommended](https://ai.google.dev/gemma/docs/core/model_card_4) temperature 1.0, top_p 0.95 and top_k 64. The calls are pinned to one host at full precision, Crusoe (bf16); most of OpenRouter's hosts serve it at fp4 or fp8. The prompt, schema, review rules and scoring are unchanged (`2_extraction.py`, section 5b). From a run on 2026-10-25, which took 31 minutes (69 in a review re-run, because of rate limits) and cost $0.13 for all three runs:

| Gemma 4 31B | Values right | Accepted without review | Wrong but accepted | Sent to review (STMT) | Cost per document |
|---|---|---|---|---|---|
| As we ran it (run 11 above) | 380 of 740 | 575 | 205 | 165 (2) | $0.0068 |
| Google's settings, Crusoe bf16, run 1 | 427 of 751 | 646 | 227 | 105 (4) | $0.0014 |
| Google's settings, Crusoe bf16, run 2 | 417 of 753 | 648 | 236 | 105 (3) | $0.0013 |
| Google's settings, Crusoe bf16, run 3 | 420 of 736 | 653 | 238 | 83 (4) | $0.0015 |

**It stays an F.** Wrong but accepted is 227 to 238, inside the 197 to 278 of runs 1 to 11. It gets more values right (417 to 427, against 380) but sends fewer to review, so just as many wrong values get through. On the made-up forms it is nearly right: 0 to 6 wrong accepted values in each group. The errors are on the three real K-1s and their scans. There it reads the digits correctly and puts them in the wrong box. Box 20's rows land in boxes 13 and 14, box 16's in 4 and 5, and box 10's in 11. Of the 64 to 71 wrong values it accepted in boxes on the key in each run, all but 3 to 6 are a number that is on the key, in another box; its other wrong accepted values are in boxes that are blank on the key. Another 147 to 153 are boxes on the key it never reported, which read as blank, and in 128 to 135 of those it had put the number in another box. These box-shift counts were tallied by hand from `output/*/extracted.json`, not by a notebook cell; a review re-run on 2026-10-26 found the same pattern (60 to 72 wrong values in key boxes, all but 3 to 5 shifted from another box).

**The image budget couldn't be raised.** Gemma 4 turns an image into 70, 140, 280 (the default), 560 or 1120 tokens, and Google says to use a higher budget for reading small text. vLLM takes the budget as `mm_processor_kwargs.max_soft_tokens`, and OpenRouter has no parameter of its own for it. We sent a 1700 × 2200 page with budgets of 70 and 1120 to seven hosts: Crusoe, Novita, Parasail, DeepInfra, CoreWeave, SiliconFlow and Chutes. Every host reported the same prompt size whichever budget we sent, so each one ignored it. Every Gemma run here and above therefore saw a K-1 page at about 700 × 900 pixels. A higher budget might help it keep the box grid apart, but it's not available through OpenRouter. Testing it needs a host we run ourselves.

Crusoe was rate-limited upstream on 69 calls, which were refused without charge and retried. On a busier day 5 to 9 documents per run can fail after six attempts; run `./run.sh --gemma-google` again and it retries only those, reusing the answers saved in `output/answers/`, until the Failed documents column is 0. The rate limits also mean model time per document (36 to 50 s) isn't comparable with the table above. Gemma ran out of its 8,000 output tokens 3 times and finished after retries. `gemma-google-settings.md` has the breakdown by kind of document from this run.

## What it doesn't show

- **This is not our production extraction.** A prospect who sends real documents will see different numbers.
- **The scans are simulated**, and the sample is small: three real K-1s, all Form 1065, and no real 1120-S, 1041 or brokerage 1099s. Gemini's perfect runs don't mean a perfect score in general.
- **Eleven runs don't pin down any model's error rate**, the open models' least of all.
- **Some errors get through any page-level check**: a 1099 answer that skips only the DIV or only the INT section, values put in the wrong box, or a whole page read as the wrong form.
- **A failed document isn't in the review queue.** In production it would go to a person whole.

The last section of `3_results.py` covers what didn't work, including the first Tesseract pipelines.

## Files

- `1_documents.py`, `2_extraction.py`, `3_results.py`: the demo, as three marimo notebooks
- `amounts.py`: reading a printed amount, which `2_extraction.py` and `3_results.py` both need
- `ocr_modal.py`: the Modal app for the OCR models (a module, because Modal imports it inside its containers)
- `review_screen.html`: the review screen's page, which `3_results.py` fills with each run's results
- `real_answer_key.json`: the real K-1s' Part III boxes and the partnership's name and EIN, keyed by hand from the issuers' PDFs
- `screenshots/`: Gemini 3.8 Flash's review screen from the run above
- `gemma-google-settings.md`: `output/comparison.md` from the `--gemma-google` run on 2026-10-25
- `run.sh`, `pyproject.toml`, `uv.lock`: the one command and its pinned environment
