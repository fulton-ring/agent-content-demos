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

You need Python 3.10+, `OPENROUTER_API_KEY`, and for the OCR models `MODAL_TOKEN_ID` and `MODAL_TOKEN_SECRET` in the environment. Without the Modal credentials the OCR models are skipped. The script makes a virtualenv (Docling brings a CPU build of PyTorch; the virtualenv comes to about 2 GB), downloads the real sample K-1s, generates the made-up documents, runs Docling, runs the five models in parallel, pairs Gemini with Qwen 3.8 27B, scores everything and writes:

- `output/comparison.md`: every run side by side
- `output/<model>-alone/index.html`: each model's review screen
- `output/pair-gemini-3.8-flash+qwen3.8-27b/index.html`: the review screen for Gemini checked by Qwen 3.8 27B

A clean run took about 30 minutes and cost about $1.24 in all; Gemini 3.8 Flash on its own finishes in a few minutes for about 20 cents.

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
3. **A value goes to review** when the model's confidence is below 0.9, the amount is on an attached statement (`STMT`), it isn't a well-formed amount, a coded row has no code letter, or a cross-check fails (qualified dividends above ordinary dividends, 4a + 4b ≠ 4c, a 1099-B row that doesn't balance).
4. **Pairs** (`pair.py`). Two models' saved answers are combined with no further API calls. A value is accepted only when both models report the same box and code with the same amount and neither has its own reason to send it to review. Anything only one model reported, or that the two read differently, goes to review.
5. **Statements.** For a `STMT` amount, the model reads the statement page and lists that box's lines. The reviewer sees them as a suggestion; the value stays in the queue.
6. **OCR models on Modal** (`ocr_modal.py`, `extract_ocr.py`). olmOCR 2 and granite-docling turn a page into text rather than filling a schema, so each is followed by a text model (Gemini 3.8 Flash, which never sees the image) that fills the same typed schema from the OCR text, with the same review rules.
   - **Weights:** a small CPU container on Modal (`modal run ocr_modal.py::download`) downloads both models from Hugging Face into a Modal Volume. The GPU containers read them from there and only spend GPU time reading pages.
   - **olmOCR 2** (`allenai/olmOCR-2-7B-1025-FP8`) runs on vLLM on an L4 GPU, with olmOCR's own prompt and 1288-pixel page images, and returns Markdown with HTML tables.
   - **granite-docling** (`ibm-granite/granite-docling-258M`) is served by vLLM on an L4 GPU behind an API key made for each run. Docling's VLM pipeline runs locally and calls it, using Docling's own `GRANITEDOCLING_VLLM_API` preset with two changes. The preset asks the server to skip special tokens, but granite-docling's DocTags are special tokens, so the reply came back with no tags and Docling parsed nothing. And a dense form needs more than the preset's 4,096 output tokens.
   - The GPU cost is Modal's L4 list price ($0.000222 a second) for each page's GPU time.

`report.py` builds the review screen for each run. Clicking a value highlights its box on the page. A STMT value opens the statement page. The queue shows each flagged box cropped from the page, with the reason, and lets a person correct or confirm it. The results export to CSV. No extractor reads the answer keys; `evaluate.py` scores the output against them afterwards.

## Results

From one clean run of `./run.sh` from a fresh checkout on 2026-10-13. "Boxes" means every box on the answer key plus every value a run reported, so reading something in an empty box, or reporting a box twice, counts as an error, and the box counts differ between runs. A silent error is a wrong value that was accepted without review: the number that matters for a review queue. The held-out set is 14 documents whose scans and made-up values use a different random seed from the ones used while building the checks.

### All 30 documents

| Pipeline | Values right | Accepted without review | Wrong but accepted | Sent to review | Cost per document | Time per document |
|---|---|---|---|---|---|---|
| **Gemini 3.8 Flash** | **676 of 676** | **652** | **0** | **24, all STMT** | **$0.0065** | **19 s** |
| Qwen3-VL 235B (open weights) | 667 of 681 | 651 | 6 | 30 | $0.0037 | 37 s |
| Qwen 3.8 27B (open weights) | 634 of 697 | 676 | 57 | 21 | $0.0039 | 57 s |
| GLM 5.3 Flash | 564 of 677 | 545 | 4 | 132 | $0.0009 | 17 s |
| Gemma 4 31B (open weights) | 367 of 739 | 639 | 278 | 100 | $0.0050 | 18 s |
| olmOCR 2 on Modal, then Gemini 3.8 Flash on the text | 549 of 702 | 542 | 69 | 160 | $0.0072 | 12 s GPU + 6 s |
| granite-docling on Modal, then Gemini 3.8 Flash on the text | 256 of 678 | 105 | 26 | 573 | $0.0141 | 57 s GPU + 4 s |
| Gemini 3.8 Flash + Qwen 3.8 27B, must agree | 675 of 697 | 619 | 0 | 78 | $0.0105 | 57 s |

"Wrong but accepted" counts both wrong values that were accepted and values on the answer key that a run never reported, since a missed row reads as a blank box.

On the held-out set alone, Gemini 3.8 Flash accepted 299 of 310 boxes, all right, and sent 11 to review, all of them STMT amounts. `output/comparison.md` breaks every run down by kind of document.

The cost is the provider's own figure for each response (OpenRouter reports it), or Pydantic AI's price table when a provider doesn't, and includes reading the supplemental statements. For the OCR pipelines it adds each page's GPU time at Modal's L4 list price: about $0.0027 a document for olmOCR and $0.0126 for granite-docling, whose time is each page's round trip to a server handling several pages at once, so it overstates its share. Docling's layout pass adds about 10 seconds per document on CPU. A pair costs the sum of its two models and takes as long as the slower one.

### What each model got wrong

- **Gemini 3.8 Flash** made no errors in this run, and 675, 676, 676 and 676 of 676 in four earlier full runs. The one error, in one run, was Enviva 2018's `-27,942` read as `-27.942` on an office scan, and that value went to review because it isn't a well-formed amount.
- **Qwen3-VL 235B** let 6 errors through in this run and between 5 and 29 in earlier ones. This time it reported dashes for two boxes that are blank on a made-up 1041 and skipped a few rows.
- **Qwen 3.8 27B** let 57 errors through, mostly rows it skipped in coded boxes on the real K-1s, and on Blackstone and Enviva 2018 it put box 16's rows under box 15.
- **GLM 5.3 Flash** returned a valid but empty answer for 6 of the 30 pages, which sends the whole page to review. Only 4 wrong values went through, but it sent 132 to review.
- **Gemma 4 31B** shifted amounts into neighbouring boxes and misread names ("ENVIRO PARTNERS, LP"). Over 40% of what it accepted was wrong.
- **olmOCR 2** read the characters well: on the Blackstone office scan its text has every Part III amount. But it lays a K-1's two columns of boxes out as one HTML table, pairing labels and amounts loosely, and once the form is text the box an amount belongs to is easy to lose. The text model then put amounts one box off (Blackstone's 6a, 6b and 6c each got the next box's amount), filed coded rows under the wrong box (`20 V` as `13 V`), and missed rows. 69 errors went through.
- **granite-docling** could not read these forms. On 25 of the 30 pages Docling got nothing usable back, and those pages went to review whole. Where it did return text, it read some of the page and often then repeated one token until it ran out of output; it never read a Part III amount on any of the real K-1s. A repetition penalty didn't help. Docling's own Transformers pipeline on a Modal GPU gave the same result at 257 seconds a page, so this is the model, not the serving.

Every vision model that reached the supplemental statements read their lines correctly, checked by `evaluate.py` against the issuers' own text layer. Gemini 3.8 Flash read all 62 lines behind the STMT boxes and missed none.

Two changes made the vision models comparable. In the coded boxes the code letter is now a required field: when it was optional, GLM and Qwen 3.8 27B left it out of every row. And thinking models run at low effort, without which they spent their whole output budget thinking.

### Reading the image, or reading text

The OCR models were the cheapest way to get the characters off the page, and olmOCR got nearly all of them. What they lose is the layout: a K-1 is a grid of numbered boxes, and a text model filling the schema from OCR text has to guess which amount belongs to which box. A vision model reading the image sees the grid. On these documents that difference decided the result: Gemini reading the image was right on all 676 values; Gemini reading olmOCR's text of the same pages was right on 549 of 702.

### Gemini alone, or checked by an open model

Gemini 3.8 Flash on its own was right on every value here, but its own confidence never flagged anything: everything it sent to review was a STMT amount. On a document it does misread, nothing but the cross-checks would catch it. Pairing it with Qwen 3.8 27B, an open-weight model that could run on our own hardware, adds an independent read for about 60% more cost: on these documents the pair let nothing wrong through and sent 54 more values to review than Gemini alone (78 against 24), almost all of them rows Qwen skipped or filed under the wrong box. For a demo, Gemini alone is enough. For client documents, the pair is the safer default.

## Earlier approaches

The first versions of this demo, still in the repository and run with `--tesseract`, read the forms with Tesseract OCR and rules (`extract.py`), and then checked Qwen3-VL 235B against Tesseract box by box (`extract_vlm.py` without `--model-only`). On the held-out set, Tesseract and rules accepted 182 of 321 boxes with 2 silent errors and sent 43% to review. Checking Qwen3-VL against Tesseract accepted 236 with no silent errors and sent 28% to review, much of it because Tesseract couldn't read a box the model had read right. Gemini 3.8 Flash on its own beats both. Docling's own OCR wasn't usable as a check on scans: it picked up 26% of the values on the scanned K-1s.

## What it doesn't show

- **This is not our production extraction.** It is a demo built on public tools and public models. A prospect who sends real documents will see different numbers.
- **The scans are simulated.** Real scans have problems we didn't model: staples, handwriting, stamps, pages scanned at a different scale, and colour backgrounds.
- **The sample is small.** It has three real K-1s, all Form 1065 from publicly traded partnerships. There are no real 1120-S or 1041 K-1s and no real brokerage 1099s; the made-up 1099s use our own layout. A perfect score on 676 values doesn't mean a perfect score in general.
- **Model answers vary from run to run.** Across five full runs GLM 5.3 Flash got between 58% and 84% of values right, Qwen3-VL 235B let between 5 and 29 errors through and Qwen 3.8 27B between 25 and 57; Gemini 3.8 Flash got 675 of 676 once and 676 of 676 four times.

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
