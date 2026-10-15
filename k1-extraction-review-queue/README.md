# K-1 extraction with a review queue

This demo reads Schedule K-1s and brokerage 1099s and links every extracted value to the box it came from. Anything the software isn't sure of goes to a review queue for a person to check. It answers a sales question for the CPA document extraction play: can we show a tax preparer what they'd get, with screenshots of real sample documents, without them sending us any documents?

It compares five current vision-language models, three of them open-weight, and two OCR models run on Modal's GPUs, on the same documents and answer keys, each on its own and in pairs where two models must agree. Docling reads the page layout and the supplemental statements; Pydantic AI turns each model's answer into typed values with a page, box and confidence.

![A value on a real K-1, highlighted on the page it came from](screenshots/1-value-linked-to-box.png)

## Run it

```
./run.sh               # the model comparison
./run.sh --tesseract   # also the earlier Tesseract pipelines (slow on CPU)
./run.sh --screenshots # also takes screenshots of Gemini 3.8 Flash's review screen
```

You need Python 3.10+, the `tesseract` binary (`apt install tesseract-ocr` or `brew install tesseract`; Docling uses it to read the scanned pages, so every run needs it, not only `--tesseract`), `OPENROUTER_API_KEY`, and for the OCR models `MODAL_TOKEN_ID` and `MODAL_TOKEN_SECRET` in the environment. `run.sh` checks for Tesseract and the OpenRouter key before it builds anything. Without the Modal credentials the OCR models are skipped. The script makes a virtualenv (Docling brings a CPU build of PyTorch; the virtualenv comes to about 2 GB), downloads the real sample K-1s, generates the made-up documents, runs Docling, runs the five models in parallel, pairs Gemini with Qwen 3.8 27B, scores everything and writes:

- `output/comparison.md`: every run side by side
- `output/<model>-alone/index.html`: each model's review screen
- `output/pair-gemini-3.8-flash+qwen3.8-27b/index.html`: the review screen for Gemini checked by Qwen 3.8 27B

A run from scratch takes 40 to 55 minutes, 3 to 14 of them building the virtualenv, and costs about $1.25 in all; Gemini 3.8 Flash on its own finishes in a few minutes for about 20 cents.

## The documents

**Real K-1s (Form 1065).** Publicly traded partnerships publish sample K-1 tax packages for their unitholders. Each is the issuer's real K-1 from their tax software, along with its supplemental statements, made out to a placeholder investor. We use three:

| File | Issuer | Tax year | Pages | Source |
|---|---|---|---|---|
| `01-enviva-2018-k1.pdf` | Enviva Partners, LP | 2018 | 8 | [envivabiomass.com](https://www.envivabiomass.com/wp-content/uploads/2019/09/Enviva_Sample_Tax_Package_10000_units.pdf) |
| `02-enviva-2021-k1.pdf` | Enviva Partners, LP | 2021 | 7 | [Enviva investor site](https://s28.q4cdn.com/898203682/files/doc_downloads/schedule_k-1s/2022/03/EVA-2021-Sample-K-1-1-000-Units.pdf) |
| `03-blackstone-2019-k1.pdf` | The Blackstone Group L.P. | 2019 | 11 | [Blackstone investor site](https://s23.q4cdn.com/714267708/files/doc_downloads/2020/03/SAMPLESCHEDULE_K1_2019.pdf) |

These files are not in the repo. `fetch_real.py` downloads them from the issuers' sites and checks their SHA-256 hashes, so the hand-keyed answer key (`real_answer_key.json`) is guaranteed to match. The three cover three different K-1 layouts, since the form changed in 2019 and again in 2021. Between them they include losses printed as `-27,942` and `(18)`, dashes for zero, coded boxes such as `20 AH*`, country codes (`16 A VARIOUS`), and boxes whose amount is only on an attached statement (`* STMT`).

**Scanned copies of the real K-1s.** These are born-digital PDFs, and real client documents often arrive as scans. So `fetch_real.py` also prints each K-1 page and "scans" it: it rotates, blurs and downsamples the image, adds noise and saves it as a JPEG. An office scan is mild. A bad scan imitates a fax or a phone photo.

**Made-up K-1s and 1099s.** Real 1120-S and 1041 K-1s and real brokerage 1099s aren't published anywhere we can use. `generate.py` fills the blank 2025 IRS forms (in `forms/`) with invented names and amounts, and draws a made-up broker's consolidated 1099 with DIV, INT and 1099-B summary and detail pages. Their EINs start with `00-`, a prefix the IRS doesn't assign. Every made-up document is image-only, either a clean scan, an office scan or a bad scan.

## How it works

1. **Docling reads every page once** (`layout.py`, on CPU). It finds the K-1 page and the supplemental statements, and turns each statement into a Box / Description / Amount table.
2. **Each model reads the form** (`extract_vlm.py --model-only`). The K-1 page (or the 1099 summary page) goes to the model as an image at 200 dpi. Each model is named by a Pydantic AI model string, such as `openrouter:google/gemini-3.8-flash`. All five here go through OpenRouter, which Pydantic AI treats as one provider among others, so a model from another provider is a different string and no code change. Pydantic AI asks for a typed result: one Pydantic model per form (1065, 1120-S, 1041 and the brokerage 1099), where every value carries what was printed, its bounding box and the model's own confidence. Thinking models run at low effort through Pydantic AI's provider-neutral `thinking` setting; reading a form doesn't need long reasoning, and at the default they spent their whole output budget thinking.
3. **A value goes to review** when the model's confidence is below 0.9, the amount is on an attached statement (`STMT`), it isn't a well-formed amount, a coded row has no code letter, or a cross-check fails (qualified dividends above ordinary dividends, 4a + 4b ≠ 4c, a 1099-B row that doesn't balance). **The whole page goes to review** when the model read nothing on it, read fewer than a quarter as many values as Docling sees amounts printed on the page (at least 8 of them), or wasn't sure of any value it read. Otherwise every box the model left out would count as an accepted blank.
4. **Pairs** (`pair.py`). Two models' saved answers are combined with no further API calls. A value is accepted only when both models report the same box and code with the same amount and neither has its own reason to send it to review. Anything only one model reported, or that the two read differently, goes to review.
5. **Statements.** For a `STMT` amount, the model reads the statement page and lists that box's lines. The reviewer sees them as a suggestion; the value stays in the queue.
6. **OCR models on Modal** (`ocr_modal.py`, `extract_ocr.py`). olmOCR 2 and granite-docling turn a page into text rather than filling a schema, so each is followed by a text model (Gemini 3.8 Flash, which never sees the image) that fills the same typed schema from the OCR text, with the same review rules.
   - **Weights:** a small CPU container on Modal (`modal run ocr_modal.py::download`) downloads both models from Hugging Face into a Modal Volume. The GPU containers read them from there and only spend GPU time reading pages.
   - **olmOCR 2** (`allenai/olmOCR-2-7B-1025-FP8`) runs on vLLM on an L4 GPU, with olmOCR's own prompt and 1288-pixel page images, and returns Markdown with HTML tables.
   - **granite-docling** (`ibm-granite/granite-docling-258M`) is served by vLLM on an L4 GPU behind an API key made for each run. Docling's VLM pipeline runs locally and calls it, using Docling's own `GRANITEDOCLING_VLLM_API` preset with two changes. The preset asks the server to skip special tokens, but granite-docling's DocTags are special tokens, so the reply came back with no tags and Docling parsed nothing. And a dense form needs more than the preset's 4,096 output tokens.
   - The GPU cost is Modal's L4 list price ($0.000222 a second) for each page's GPU time.

`report.py` builds the review screen for each run. Clicking a value highlights its box on the page. A STMT value opens the statement page. The queue shows each flagged box cropped from the page, with the reason, and lets a person correct or confirm it. The results export to CSV. No extractor reads the answer keys; `evaluate.py` scores the output against them afterwards.

## Results

From one clean run of `./run.sh --screenshots` from a fresh clone on 2026-10-15, after the fixes below. "Boxes" means every box on the answer key plus every value a run reported, so reading something in an empty box, or reporting a box twice, counts as an error, and the box counts differ between runs. A silent error is a wrong value that was accepted without review: the number that matters for a review queue. The held-out set is 14 documents whose scans and made-up values use a different random seed from the ones used while building the checks.

The Tesseract baseline isn't in this table. The default run doesn't produce it; its numbers under [Earlier approaches](#earlier-approaches) come from earlier held-out runs with `--tesseract`.

### All 30 documents

| Pipeline | Values right | Accepted without review | Wrong but accepted | Sent to review | Cost per document | Model time per document |
|---|---|---|---|---|---|---|
| **Gemini 3.8 Flash** | **676 of 676** | **652** | **0** | **24, all STMT** | **$0.0066** | **21 s** |
| Qwen3-VL 235B (open weights) | 653 of 687 | 655 | 22 | 32 | $0.0039 | 70 s |
| Qwen 3.8 27B (open weights) | 656 of 693 | 667 | 32 | 26 | $0.0053 (29 documents; see below) | 33 s |
| GLM 5.3 Flash | 656 of 678 | 619 | 4 | 59 | $0.0015 | 16 s |
| Gemma 4 31B (open weights) | 416 of 726 | 646 | 239 | 80 | $0.0030 | 162 s, mostly retries |
| olmOCR 2 on Modal, then Gemini 3.8 Flash on the text | 533 of 711 | 557 | 87 | 154 | $0.0074 | 12 s GPU + 6 s |
| granite-docling on Modal, then Gemini 3.8 Flash on the text | 253 of 678 | 75 | 12 | 603 | $0.0140 | 56 s GPU + 4 s |
| Gemini 3.8 Flash + Qwen 3.8 27B, must agree | 676 of 693 | 635 | 0 | 58 | $0.0119 (29 documents) | 33 s |

"Wrong but accepted" counts both wrong values that were accepted and values on the answer key that a run never reported, since a missed row reads as a blank box. Docling's layout pass adds about 11 seconds per document on CPU to every vision-model row.

On the held-out set alone, Gemini 3.8 Flash accepted 299 of 310 boxes, all right, and sent 11 to review, all of them STMT amounts. `output/comparison.md` breaks every run down by kind of document.

**Cost.** The cost is the provider's own figure for each response (OpenRouter reports it), or Pydantic AI's price table when a provider doesn't, and includes reading the supplemental statements. Every attempt is counted, including retries that failed after the model answered: Gemma 4 31B needed 8 retries in this run (output cut off at the token limit), and they are in its cost. When a response has no known cost, its document is left out of the average and listed in `metrics.json` (`cost_unknown_documents`) and in `output/comparison.md`: here one Qwen 3.8 27B response on the Blackstone office scan, so Qwen's and the pair's averages are over 29 documents. For the OCR pipelines the cost adds each page's GPU time at Modal's L4 list price: about $0.0027 a document for olmOCR and $0.0124 for granite-docling, whose time is each page's round trip to a server handling several pages at once, so it overstates its share. A pair costs the sum of its two models and takes as long as the slower one. The whole run cost about $1.25.

**Time.** A run from scratch takes 40 to 55 minutes. This one took 42.5 minutes, 3 of them building the virtualenv; the Spike manager's run on another machine took 55 minutes, 14 of them building the virtualenv. Gemini 3.8 Flash took between 19 and 32 seconds per document across runs (in this one, 21 seconds waiting on the model plus 11 seconds of Docling). Gemini on its own finishes in a few minutes for about 20 cents.

### How much the results vary between runs

The open models' answers change from run to run at temperature 0, by a lot. These are the four full runs with the current set of models: two on 2026-10-13 (the second was the README's earlier results), the Spike manager's run on 2026-10-15, and this one. The OCR pipelines were added for the second run.

| Pipeline | Wrong but accepted, by run | Sent to review, by run | Cost per document, range |
|---|---|---|---|
| Gemini 3.8 Flash | 0, 0, 0, 0 | 24, 24, 24, 24 (all STMT) | $0.0065 to $0.0066 |
| Qwen3-VL 235B | 29, 6, 13, 22 | 37, 30, 40, 32 | $0.0037 to $0.0040 |
| Qwen 3.8 27B | 25, 57, 91, 32 | 24, 21, 22, 26 | $0.0036 to $0.0063 |
| GLM 5.3 Flash | 14, 4, 88\*, 4 | 116, 132, 92, 59 | $0.0009 to $0.0017 |
| Gemma 4 31B | 211, 278, 222, 239 | 105, 100, 72, 80 | $0.0015 to $0.0050 |
| olmOCR 2 + Gemini | –, 69, 84, 87 | –, 160, 140, 154 | $0.0072 to $0.0074 |
| granite-docling + Gemini | –, 26, 14, 12 | –, 573, 601, 603 | $0.0140 to $0.0172 |
| Gemini + Qwen 3.8 27B pair | 0, 0, 0, 0 | 49, 78, 113, 58 | $0.0102 to $0.0127 |

\* In the manager's run GLM returned only box 1a, at confidence 0, for five brokerage 1099s. The page wasn't empty, so it wasn't sent to review whole, and every box it left out counted as an accepted blank: 85 of the 88. The page check now sends a near-empty answer to review (see [How it works](#how-it-works)); on those five pages it would have sent the whole page to review, so those 85 would now be review items, not silent errors. In this run GLM didn't do that, and it had its best run yet.

The first three runs counted only the attempt that succeeded, so their costs leave out failed retries; this run's costs include them. Before these four runs, with an earlier prompt and a slightly different model set, Gemini 3.8 Flash got 675, 676, 676 and 676 of 676 right; the one error was Enviva 2018's `-27,942` read as `-27.942` on an office scan, and it went to review because it isn't a well-formed amount.

### What each model got wrong

- **Gemini 3.8 Flash** made no errors in any of the four runs.
- **Qwen3-VL 235B** let 22 errors through in this run, all on the Blackstone K-1 and its three scans: mostly Part III amounts it misread or skipped (boxes 3, 4a to 4c, 6c, 9b and 12 on one office scan) and rows of box 13.
- **Qwen 3.8 27B** let 32 errors through, all on scans of the real K-1s, mostly coded rows (boxes 11, 15 and 16) that it skipped or filed under the wrong box. In earlier runs it put Blackstone's and Enviva 2018's box 16 rows under box 15.
- **GLM 5.3 Flash** let 4 errors through, all on Enviva 2018, and returned an empty answer for one page, which went to review whole. It varies the most: see the table above.
- **Gemma 4 31B** shifted amounts into neighbouring boxes, misread names ("ENVIRO PARTNERS, LP") and skipped coded rows. Between a third and 43% of what it accepted was wrong, depending on the run.
- **olmOCR 2** read the characters well: on the Blackstone office scan its text has every Part III amount. But it lays a K-1's two columns of boxes out as one HTML table, pairing labels and amounts loosely, and once the form is text the box an amount belongs to is easy to lose. The text model then put amounts one box off (in one run Blackstone's 6a, 6b and 6c each got the next box's amount), filed coded rows under the wrong box (`20 V` as `13 V`), and missed rows. 87 errors went through in this run.
- **granite-docling** could not read these forms. On 26 of the 30 pages Docling got nothing usable back, and those pages went to review whole. Where it did return text, it read some of the page and often then repeated one token until it ran out of output; it never read a Part III amount on any of the real K-1s. A repetition penalty didn't help. Docling's own Transformers pipeline on a Modal GPU gave the same result at 257 seconds a page, so this is the model, not the serving.

**Supplemental statements.** `evaluate.py` checks every statement line a model reads against the issuer's own text layer. Gemini 3.8 Flash read all 62 lines behind the STMT boxes correctly and missed none, in this run and in the manager's. In this run every other vision model that reached the statements also read its lines correctly (Gemma reached only 15 lines). That doesn't always hold: in the manager's run Gemma 4 31B read 29 of 36 lines right and missed 10; for example it read Blackstone's 20AG as 3,213 where the statement says 3,513. The statement lines are only ever a suggestion beside a value that stays in the queue.

Two changes made the vision models comparable. In the coded boxes the code letter is now a required field: when it was optional, GLM and Qwen 3.8 27B left it out of every row. And thinking models run at low effort, without which they spent their whole output budget thinking.

### Reading the image, or reading text

The OCR models were the cheapest way to get the characters off the page, and olmOCR got nearly all of them. What they lose is the layout: a K-1 is a grid of numbered boxes, and a text model filling the schema from OCR text has to guess which amount belongs to which box. A vision model reading the image sees the grid. On these documents that difference decided the result: Gemini reading the image was right on all 676 values; Gemini reading olmOCR's text of the same pages was right on 533 of 711.

### Gemini alone, or checked by an open model

Gemini 3.8 Flash on its own was right on every value here, but its own confidence never flagged anything: everything it sent to review was a STMT amount. On a document it does misread, nothing but the cross-checks would catch it. Pairing it with Qwen 3.8 27B, an open-weight model that could run on our own hardware, adds an independent read for about 80% more cost: the pair let nothing wrong through in any run and sent between 25 and 89 more values to review than Gemini alone (49 to 113 against 24), almost all of them rows Qwen skipped or filed under the wrong box. For a demo, Gemini alone is enough. For client documents, the pair is the safer default.

## Earlier approaches

These numbers are from earlier runs and the default `./run.sh` doesn't reproduce them; `./run.sh --tesseract` does. The first versions of this demo, still in the repository and run with `--tesseract`, read the forms with Tesseract OCR and rules (`extract.py`), and then checked Qwen3-VL 235B against Tesseract box by box (`extract_vlm.py` without `--model-only`). On the held-out set, Tesseract and rules accepted 182 of 321 boxes with 2 silent errors and sent 43% to review. Checking Qwen3-VL against Tesseract accepted 236 with no silent errors and sent 28% to review, much of it because Tesseract couldn't read a box the model had read right. Gemini 3.8 Flash on its own beats both. Docling's own OCR wasn't usable as a check on scans: it picked up 26% of the values on the scanned K-1s.

## What it doesn't show

- **This is not our production extraction.** It is a demo built on public tools and public models. A prospect who sends real documents will see different numbers.
- **The scans are simulated.** Real scans have problems we didn't model: staples, handwriting, stamps, pages scanned at a different scale, and colour backgrounds.
- **The sample is small.** It has three real K-1s, all Form 1065 from publicly traded partnerships. There are no real 1120-S or 1041 K-1s and no real brokerage 1099s; the made-up 1099s use our own layout. A perfect score on 676 values doesn't mean a perfect score in general.
- **Model answers vary from run to run.** Across four runs with the current models, Qwen3-VL 235B let between 6 and 29 errors through, Qwen 3.8 27B between 25 and 91 and GLM 5.3 Flash between 4 and 88 (85 of those from near-empty answers that now go to review). Gemini 3.8 Flash made no errors in any of them. Four runs are not enough to pin down an open model's error rate.

## Files

- `run.sh`: the one command
- `fetch_real.py`: downloads the real K-1s and makes scanned copies
- `generate.py`: makes the made-up documents and `answer_key.json`
- `layout.py`: runs Docling over every sample once, writing `output/layout/`
- `extract_vlm.py`: reads every document with one model, `python extract_vlm.py openrouter:<model> --model-only`, or any other Pydantic AI model string
- `pair.py`: combines two models' runs, `python pair.py output/<a>-alone output/<b>-alone`
- `ocr_modal.py`: the Modal app: the CPU weight download, olmOCR 2 on vLLM, and the granite-docling vLLM server
- `extract_ocr.py`: OCR on Modal, then a text model fills the schema, `python extract_ocr.py olmocr|granite-docling openrouter:<model>`
- `evaluate.py`: scores a run and writes its `metrics.json`
- `report.py`: builds a run's review screen, `index.html`
- `compare.py`: writes `output/comparison.md`
- `extract.py`: the earlier Tesseract pipeline
- `screenshots.py`: saves `screenshots/` from a run's review screen (Gemini 3.8 Flash by default)
- `real_answer_key.json`: the real K-1s' Part III boxes and the partnership name and EIN, keyed by hand from the issuers' PDFs
- `forms/`: blank IRS Schedule K-1 forms (1065 for 2018, 2019, 2021 and 2025; 1120-S and 1041 for 2025), from irs.gov

The committed screenshots are Gemini 3.8 Flash's review screen from the clean run reported above.
