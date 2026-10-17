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

You need Python 3.10+, the `tesseract` binary (`apt install tesseract-ocr` or `brew install tesseract`; Docling uses it to read the scanned pages, so every run needs it, not only `--tesseract`), `OPENROUTER_API_KEY`, and for the OCR models `MODAL_TOKEN_ID` and `MODAL_TOKEN_SECRET` in the environment. `run.sh` checks for Tesseract and the OpenRouter key before it builds anything. Without the Modal credentials the OCR models are skipped. The script makes a virtualenv (Docling brings a CPU build of PyTorch; the virtualenv comes to about 2 GB), downloads the blank IRS forms and the real sample K-1s, generates the made-up documents, runs Docling, runs the five models in parallel, pairs Gemini with Qwen 3.8 27B, scores everything and writes:

- `output/comparison.md`: every run side by side
- `output/<model>-alone/index.html`: each model's review screen
- `output/pair-gemini-3.8-flash+qwen3.8-27b/index.html`: the review screen for Gemini checked by Qwen 3.8 27B

A run from scratch takes 36 to 55 minutes, 2 to 14 of them building the virtualenv, and costs $1.20 to $1.45 in all; Gemini 3.8 Flash on its own finishes in a few minutes for about 20 cents.

**When a model fails.** Each model gets six attempts at a document, and Pydantic AI retries malformed output twice within each. A comparison model that still fails on some documents doesn't stop the run: it is scored on the documents it finished, and the ones it failed are listed in its `extracted.json` and `metrics.json` (`failed_documents`) and in the "Failed documents" column of `output/comparison.md`. A model that finishes no documents at all is left out of the comparison. The run stops with an error only when Gemini 3.8 Flash or Qwen 3.8 27B produce nothing, since the pair and the screenshots need them. The pair is scored on the documents both of its models finished. The OCR pipelines work the same way.

## The documents

**Real K-1s (Form 1065).** Publicly traded partnerships publish sample K-1 tax packages for their unitholders. Each is the issuer's real K-1 from their tax software, along with its supplemental statements, made out to a placeholder investor. We use three:

| File | Issuer | Tax year | Pages | Source |
|---|---|---|---|---|
| `01-enviva-2018-k1.pdf` | Enviva Partners, LP | 2018 | 8 | [envivabiomass.com](https://www.envivabiomass.com/wp-content/uploads/2019/09/Enviva_Sample_Tax_Package_10000_units.pdf) |
| `02-enviva-2021-k1.pdf` | Enviva Partners, LP | 2021 | 7 | [Enviva investor site](https://s28.q4cdn.com/898203682/files/doc_downloads/schedule_k-1s/2022/03/EVA-2021-Sample-K-1-1-000-Units.pdf) |
| `03-blackstone-2019-k1.pdf` | The Blackstone Group L.P. | 2019 | 11 | [Blackstone investor site](https://s23.q4cdn.com/714267708/files/doc_downloads/2020/03/SAMPLESCHEDULE_K1_2019.pdf) |

These files are not in the repo. `fetch_real.py` downloads them from the issuers' sites and checks their SHA-256 hashes, so the hand-keyed answer key (`real_answer_key.json`) is guaranteed to match. The three cover three different K-1 layouts, since the form changed in 2019 and again in 2021. Between them they include losses printed as `-27,942` and `(18)`, dashes for zero, coded boxes such as `20 AH*`, country codes (`16 A VARIOUS`), and boxes whose amount is only on an attached statement (`* STMT`).

**Scanned copies of the real K-1s.** These are born-digital PDFs, and real client documents often arrive as scans. So `fetch_real.py` also prints each K-1 page and "scans" it: it rotates, blurs and downsamples the image, adds noise and saves it as a JPEG. An office scan is mild. A bad scan imitates a fax or a phone photo.

**Made-up K-1s and 1099s.** Real 1120-S and 1041 K-1s and real brokerage 1099s aren't published anywhere we can use. `generate.py` fills the blank 2025 IRS forms with invented names and amounts, and draws a made-up broker's consolidated 1099 with DIV, INT and 1099-B summary and detail pages. Their EINs start with `00-`, a prefix the IRS doesn't assign. Every made-up document is image-only, either a clean scan, an office scan or a bad scan.

**Blank IRS forms.** `fetch_forms.py` downloads the blank Schedule K-1 forms from the IRS's prior-year archive (`irs.gov/pub/irs-prior/`): Form 1065 for 2018, 2019, 2021 and 2025, and Forms 1120-S and 1041 for 2025. It checks their SHA-256 hashes, as `fetch_real.py` does for the issuers' files. `generate.py` fills the 1120-S and 1041 forms, and the extractors line scanned K-1s up with all six for their box labels. They are not in the repo.

## How it works

1. **Docling reads every page once** (`layout.py`, on CPU). It finds the K-1 page and the supplemental statements, and turns each statement into a Box / Description / Amount table.
2. **Each model reads the form** (`extract_vlm.py --model-only`). The K-1 page (or the 1099 summary page) goes to the model as an image at 200 dpi. Each model is named by a Pydantic AI model string, such as `openrouter:google/gemini-3.8-flash`. All five here go through OpenRouter, which Pydantic AI treats as one provider among others, so a model from another provider is a different string and no code change. Pydantic AI asks for a typed result: one Pydantic model per form (1065, 1120-S, 1041 and the brokerage 1099), where every value carries what was printed, its bounding box and the model's own confidence. Thinking models run at low effort through Pydantic AI's provider-neutral `thinking` setting; reading a form doesn't need long reasoning, and at the default they spent their whole output budget thinking.
3. **A value goes to review** when the model's confidence is below 0.9, the amount is on an attached statement (`STMT`), it isn't a well-formed amount, a coded row has no code letter, or a cross-check fails (qualified dividends above ordinary dividends, 4a + 4b ≠ 4c, a 1099-B row that doesn't balance). **The whole page goes to review** when the model read nothing on it, read too few values for the amounts Docling sees printed on the page (when there are at least 8), or wasn't sure of any value it read. "Too few" depends on the form. A K-1 prints many amounts the schema doesn't ask for, such as the capital account, so a K-1 answer is near-empty only below a quarter of the printed amounts. A brokerage summary page prints only the 18 amounts the schema asks for, so there the line is three quarters: Docling sees 15 to 17 amounts on each made-up 1099 summary page, a full answer has 16 to 18 values, and GLM's sparse answers had 4 to 8. An answer that skips only the DIV or only the INT section still has 12 or 14 values and isn't caught; one that skips the 1099-B rows, or DIV and INT together, is. Otherwise every box the model left out would count as an accepted blank.
4. **Pairs** (`pair.py`). Two models' saved answers are combined with no further API calls. A value is accepted only when both models report the same box and code with the same amount and neither has its own reason to send it to review. Anything only one model reported, or that the two read differently, goes to review.
5. **Statements.** For a `STMT` amount, the model reads the statement page and lists that box's lines. The reviewer sees them as a suggestion; the value stays in the queue.
6. **OCR models on Modal** (`ocr_modal.py`, `extract_ocr.py`). olmOCR 2 and granite-docling turn a page into text rather than filling a schema, so each is followed by a text model (Gemini 3.8 Flash, which never sees the image) that fills the same typed schema from the OCR text, with the same review rules.
   - **Weights:** a small CPU container on Modal (`modal run ocr_modal.py::download`) downloads both models from Hugging Face into a Modal Volume. The GPU containers read them from there and only spend GPU time reading pages.
   - **olmOCR 2** (`allenai/olmOCR-2-7B-1025-FP8`) runs on vLLM on an L4 GPU, with olmOCR's own prompt and 1288-pixel page images, and returns Markdown with HTML tables.
   - **granite-docling** (`ibm-granite/granite-docling-258M`) is served by vLLM on an L4 GPU behind an API key made for each run. Docling's VLM pipeline runs locally and calls it, using Docling's own `GRANITEDOCLING_VLLM_API` preset with two changes. The preset asks the server to skip special tokens, but granite-docling's DocTags are special tokens, so the reply came back with no tags and Docling parsed nothing. And a dense form needs more than the preset's 4,096 output tokens.
   - The GPU cost is Modal's L4 list price ($0.000222 a second) for each page's GPU time.

`report.py` builds the review screen for each run. Clicking a value highlights its box on the page. A STMT value opens the statement page. The queue shows each flagged box cropped from the page, with the reason, and lets a person correct or confirm it. The results export to CSV. No extractor reads the answer keys; `evaluate.py` scores the output against them afterwards.

## Results

From one clean run of `./run.sh --screenshots` from a fresh clone on 2026-10-16. "Boxes" means every box on the answer key plus every value a run reported, so reading something in an empty box, or reporting a box twice, counts as an error, and the box counts differ between runs. A silent error is a wrong value that was accepted without review: the number that matters for a review queue. The held-out set is 14 documents whose scans and made-up values use a different random seed from the ones used while building the checks.

Five earlier full runs are in [How much the results vary between runs](#how-much-the-results-vary-between-runs). In this run, as in the manager's second run, Gemini 3.8 Flash let 2 wrong values through from one misread on the same bad scan; see [What each model got wrong](#what-each-model-got-wrong).

The Tesseract baseline isn't in this table. The default run doesn't produce it; its numbers under [Earlier approaches](#earlier-approaches) come from earlier held-out runs with `--tesseract`.

### All 30 documents

| Pipeline | Values right | Accepted without review | Wrong but accepted | Sent to review | Cost per document | Model time per document |
|---|---|---|---|---|---|---|
| **Gemini 3.8 Flash** | **671 of 676** | **649** | **2** | **27 (24 STMT)** | **$0.0065** | **17 s** |
| Qwen3-VL 235B (open weights) | 668 of 682 | 651 | 6 | 31 | $0.0038 | 39 s |
| Qwen 3.8 27B (open weights) | 631 of 699 | 674 | 56 | 25 | $0.0034 | 58 s |
| GLM 5.3 Flash, 25 documents (failed on 5) | 572 of 587 | 562 | 13 | 25 | $0.0019 | 18 s |
| Gemma 4 31B (open weights) | 446 of 720 | 662 | 220 | 58 | $0.0028 | 125 s, mostly retries |
| olmOCR 2 on Modal, then Gemini 3.8 Flash on the text | 543 of 715 | 574 | 86 | 141 | $0.0073 | 12 s GPU + 5 s |
| granite-docling on Modal, then Gemini 3.8 Flash on the text | 266 of 679 | 78 | 2 | 601 | $0.0151 | 60 s GPU + 4 s |
| **Gemini 3.8 Flash + Qwen 3.8 27B, must agree** | **672 of 699** | **613** | **0** | **86** | **$0.0099** | **58 s** |

"Wrong but accepted" counts both wrong values that were accepted and values on the answer key that a run never reported, since a missed row reads as a blank box. Docling's layout pass adds 8 to 14 seconds per document on CPU to every vision-model row. GLM 5.3 Flash failed every retry on 5 of the 6 made-up brokerage 1099s, so its row covers the other 25 documents and isn't comparable box for box with the rest.

On the held-out set alone, Gemini 3.8 Flash accepted 297 of 310 boxes and got 295 right, and sent 13 to review: 11 STMT amounts and 2 amounts printed with a period for a comma. The manager's second run gave the same 297 right of 299 accepted. In the three runs before that it accepted 299, all right. The pair accepted 278 held-out boxes, all right. `output/comparison.md` breaks every run down by kind of document.

**Cost.** The cost is the provider's own figure for each response (OpenRouter reports it), or Pydantic AI's price table when a provider doesn't, and includes reading the supplemental statements. Every attempt is counted, including retries that failed after the model answered: Gemma 4 31B needed 6 retries in this run (output cut off at the token limit), and they are in its cost. GLM's attempts on the documents it failed were paid for but aren't in its cost, since those documents have no results; its cost per document is a little low. When a response has no known cost, its document is left out of the average and listed in `metrics.json` (`cost_unknown_documents`) and in `output/comparison.md`. That happened to one Qwen 3.8 27B response on the Blackstone office scan in the two runs on 2026-10-15, and to none in this run. For the OCR pipelines the cost adds each page's GPU time at Modal's L4 list price: about $0.0027 a document for olmOCR and $0.0124 to $0.0134 for granite-docling, whose time is each page's round trip to a server handling several pages at once, so it overstates its share. A pair costs the sum of its two models and takes as long as the slower one. This run cost about $1.21 in all, the run on 2026-10-15 about $1.25 and the manager's second run about $1.42, so expect $1.20 to $1.45.

**Time.** A run from scratch takes 36 to 55 minutes. This one took 36 minutes, 2 of them building the virtualenv. The run on 2026-10-15 took 42.5 minutes, 3 of them building the virtualenv. The Spike manager's two runs on another machine took 55 minutes each, 14 of them building the virtualenv in the first. Gemini 3.8 Flash took between 19 and 33 seconds per document across runs, model time and Docling together: in this one, 17 seconds waiting on the model plus 8 seconds of Docling; in the manager's second run, 18.6 seconds plus 14.3. Gemini on its own finishes in a few minutes for about 20 cents.

### How much the results vary between runs

The open models' answers change from run to run at temperature 0, by a lot. These are the six full runs with the current set of models, in order: two on 2026-10-13, the Spike manager's first run on 2026-10-15, a worker's run the same day, the manager's second run later that day, and this one on 2026-10-16. The OCR pipelines were added for the second run. The manager's third run, on 2026-10-16, stopped when GLM failed on three documents and isn't in the table; that is what the failure handling above fixes.

| Pipeline | Wrong but accepted, by run | Sent to review, by run | Cost per document, range |
|---|---|---|---|
| Gemini 3.8 Flash | 0, 0, 0, 0, 2, 2 | 24, 24, 24, 24, 24, 27 (24 STMT each time) | $0.0065 to $0.0066 |
| Qwen3-VL 235B | 29, 6, 13, 22, 3, 6 | 37, 30, 40, 32, 28, 31 | $0.0037 to $0.0040 |
| Qwen 3.8 27B | 25, 57, 91, 32, 61, 56 | 24, 21, 22, 26, 18, 25 | $0.0034 to $0.0063 |
| GLM 5.3 Flash | 14, 4, 88\*, 4, 13, 13† | 116, 132, 92, 59, 206, 25† | $0.0009 to $0.0020 |
| Gemma 4 31B | 211, 278, 222, 239, 235, 220 | 105, 100, 72, 80, 90, 58 | $0.0015 to $0.0050 |
| olmOCR 2 + Gemini | –, 69, 84, 87, 76, 86 | –, 160, 140, 154, 137, 141 | $0.0072 to $0.0074 |
| granite-docling + Gemini | –, 26, 14, 12, 20, 2 | –, 573, 601, 603, 574, 601 | $0.0140 to $0.0219 |
| Gemini + Qwen 3.8 27B pair | 0, 0, 0, 0, 0, 0 | 49, 78, 113, 58, 81, 86 | $0.0099 to $0.0127 |

† 25 documents: GLM failed on 5 of the 6 brokerage 1099s in this run.

\* In the manager's run GLM returned only box 1a, at confidence 0, for five brokerage 1099s. The page wasn't empty, so it wasn't sent to review whole, and every box it left out counted as an accepted blank: 85 of the 88. The page check now sends a near-empty answer to review (see [How it works](#how-it-works)); on those five pages it would have sent the whole page to review, so those 85 would now be review items, not silent errors. In the fourth run GLM didn't do that, and it had its best run.

The first three runs counted only the attempt that succeeded, so their costs leave out failed retries; the last three include them. Before these six runs, with an earlier prompt and a slightly different model set, Gemini 3.8 Flash got 675, 676, 676 and 676 of 676 right; the one error was Enviva 2018's `-27,942` read as `-27.942` on an office scan, and it went to review because it isn't a well-formed amount.

### What each model got wrong

- **Gemini 3.8 Flash** made no errors in four of the six runs. In the last two it made the same misread, which cost two boxes each time: on the bad scan of Enviva 2018 (`01-enviva-2018-k1-scan2b.pdf`, held out), it read the dash in box 5 as `0` and put it in box 4, at confidence 95. That is a box shift on a bad scan, accepted at high confidence, so nothing in Gemini's own answer sent it to review: box 4 became a wrong accepted 0, and box 5 went unreported and counted as an accepted blank. The pair with Qwen 3.8 27B caught it both times; see [below](#gemini-alone-or-checked-by-an-open-model). In this run it also read `-27,942` as `-27.942` twice and `216,999` as `216.999` once on the Enviva scans; those went to review because they aren't well-formed amounts.
- **Qwen3-VL 235B** let 6 errors through in this run: rows of boxes 13, 16 and 20 on the Blackstone K-1 and its office scan, and boxes 8 and 10 on a made-up 1041. In the run on 2026-10-15 it let 22 through, all on the Blackstone K-1 and its scans.
- **Qwen 3.8 27B** let 56 errors through, almost all on the real K-1s and their scans (43 on Blackstone), mostly coded rows (boxes 11, 15 and 16) that it skipped or filed under the wrong box. In earlier runs it put Blackstone's and Enviva 2018's box 16 rows under box 15.
- **GLM 5.3 Flash** can fail outright on the made-up brokerage 1099s. In this run it failed all six attempts on 5 of the 6 (`16`, `17`, `18`, `26` and `27`), each time with Pydantic AI's `Exceeded maximum output retries (2)`: its answer never fit the 1099 schema. The manager's third run failed the same way on 3 of them (`17`, `18`, `27`) and stopped there. On the sixth, `28`, it read only the 1099-B rows, all right, and skipped the DIV and INT sections: 10 boxes counted as accepted blanks. That page shows more amounts than GLM read, but not four times as many, so the near-empty check didn't send it to review. Its other 3 errors were single boxes on the real K-1s. It also varies the most between runs: in the manager's second run it sent 206 values to review and still let 13 through.
- **Gemma 4 31B** shifted amounts into neighbouring boxes, misread names ("ENVIRO PARTNERS, LP") and skipped coded rows. Between a third and 43% of what it accepted was wrong, depending on the run. It regularly runs out of its 8,000 output tokens before answering: 6 times in this run (three on the Blackstone bad scan, and once each on made-up documents `22`, `25` and `28`), 6 in the manager's second run and 8 in the run before. Each is retried, so it finished every document, but that's why it is the slowest model at about two minutes a document.
- **olmOCR 2** read the characters well: on the Blackstone office scan its text has every Part III amount. But it lays a K-1's two columns of boxes out as one HTML table, pairing labels and amounts loosely, and once the form is text the box an amount belongs to is easy to lose. The text model then put amounts one box off (in one run Blackstone's 6a, 6b and 6c each got the next box's amount), filed coded rows under the wrong box (`20 V` as `13 V`), and missed rows. 86 errors went through in this run.
- **granite-docling** could not read these forms. On 26 of the 30 pages Docling got nothing usable back, and those pages went to review whole. Where it did return text, it read some of the page and often then repeated one token until it ran out of output; it never read a Part III amount on any of the real K-1s. A repetition penalty didn't help. Docling's own Transformers pipeline on a Modal GPU gave the same result at 257 seconds a page, so this is the model, not the serving.

**Supplemental statements.** `evaluate.py` checks every statement line a model reads against the issuer's own text layer. Gemini 3.8 Flash read all 62 lines behind the STMT boxes correctly and missed none, in this run and in the earlier ones. In this run every other vision model that reached the statements also read its lines correctly: Qwen3-VL 235B and GLM all 62, Qwen 3.8 27B 19 and Gemma 15. That doesn't always hold: in the manager's first run Gemma 4 31B read 29 of 36 lines right and missed 10; for example it read Blackstone's 20AG as 3,213 where the statement says 3,513. In the manager's second run Gemma read 14 of 17 right and missed 30. The statement lines are only ever a suggestion beside a value that stays in the queue.

Two changes made the vision models comparable. In the coded boxes the code letter is now a required field: when it was optional, GLM and Qwen 3.8 27B left it out of every row. And thinking models run at low effort, without which they spent their whole output budget thinking.

### Reading the image, or reading text

The OCR models were the cheapest way to get the characters off the page, and olmOCR got nearly all of them. What they lose is the layout: a K-1 is a grid of numbered boxes, and a text model filling the schema from OCR text has to guess which amount belongs to which box. A vision model reading the image sees the grid. On these documents that difference decided the result: in this run Gemini reading the image was right on 671 of 676 values, and 674 to 676 in earlier runs; Gemini reading olmOCR's text of the same pages was right on 543 of 715.

### Gemini alone, or checked by an open model

Gemini 3.8 Flash on its own let 0 to 2 wrong values through across six runs, but its own confidence never flagged anything: everything it sent to review was a STMT amount or a malformed one. So when it does misread a document, nothing but the cross-checks will catch it, and in the last two runs nothing did: it put a box 5 dash into box 4 as `0` on a bad scan, at confidence 95, and both boxes were accepted wrong. That is the case a second, independent read is for. Pairing Gemini with Qwen 3.8 27B, an open-weight model that could run on our own hardware, costs 50 to 90% more ($0.0099 to $0.0127 a document against $0.0065). The pair let nothing wrong through in any of the six runs, that misread included, and sent between 25 and 89 more values to review than Gemini alone (49 to 113 against 24 to 27), almost all of them rows Qwen skipped or filed under the wrong box. Gemini alone is cheaper and is right on nearly every value, but it can accept a misread on a bad scan without flagging it. The pair is the safer default for client documents, and the one to show a CPA firm when the point is that wrong values don't get through.

## Earlier approaches

These numbers are from earlier runs and the default `./run.sh` doesn't reproduce them; `./run.sh --tesseract` does. The first versions of this demo, still in the repository and run with `--tesseract`, read the forms with Tesseract OCR and rules (`extract.py`), and then checked Qwen3-VL 235B against Tesseract box by box (`extract_vlm.py` without `--model-only`). On the held-out set, Tesseract and rules accepted 182 of 321 boxes with 2 silent errors and sent 43% to review. Checking Qwen3-VL against Tesseract accepted 236 with no silent errors and sent 28% to review, much of it because Tesseract couldn't read a box the model had read right. Gemini 3.8 Flash on its own beats both. Docling's own OCR wasn't usable as a check on scans: it picked up 26% of the values on the scanned K-1s.

## What it doesn't show

- **This is not our production extraction.** It is a demo built on public tools and public models. A prospect who sends real documents will see different numbers.
- **The scans are simulated.** Real scans have problems we didn't model: staples, handwriting, stamps, pages scanned at a different scale, and colour backgrounds.
- **The sample is small.** It has three real K-1s, all Form 1065 from publicly traded partnerships. There are no real 1120-S or 1041 K-1s and no real brokerage 1099s; the made-up 1099s use our own layout. Gemini's best runs were perfect on 676 values; that doesn't mean a perfect score in general, and two of six runs weren't.
- **Model answers vary from run to run.** Across six runs with the current models, Qwen3-VL 235B let between 3 and 29 errors through, Qwen 3.8 27B between 25 and 91 and GLM 5.3 Flash between 4 and 88 (85 of those from near-empty answers that now go to review). Gemini 3.8 Flash let 0 to 2 through. Six runs are not enough to pin down any model's error rate.
- **A model that skips a whole section can get through.** The page check catches an empty or near-empty answer, but not one like GLM's on document `28`, which read the 1099-B rows and skipped the DIV and INT sections. A check per section of the 1099 would catch it; this demo doesn't have one.
- **A failed document isn't in the review queue.** A document a model couldn't read on any retry is listed as failed and left out of its scores and review screen. In production it would go to a person whole.

## Files

- `run.sh`: the one command
- `fetch_forms.py`: downloads the blank IRS K-1 forms into `forms/`
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

The committed screenshots are Gemini 3.8 Flash's review screen from the clean run reported above.
