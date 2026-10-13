# K-1 extraction with a review queue

This demo reads Schedule K-1s and brokerage 1099s and links every extracted value to the box it came from. Anything the software isn't sure of goes to a review queue for a person to check. It answers a sales question for the CPA document extraction play: can a two-minute screen recording show a tax preparer what they'd get, without them sending us any documents?

It compares five current vision-language models on the same documents and answer keys, each on its own and in pairs where two models must agree. Docling reads the page layout and the supplemental statements; Pydantic AI turns each model's answer into typed values with a page, box and confidence.

![A value on a real K-1, highlighted on the page it came from](screenshots/1-value-linked-to-box.png)

## Run it

```
./run.sh               # the model comparison
./run.sh --tesseract   # also the earlier Tesseract pipelines (slow on CPU)
./run.sh --record      # also clicks through the review screen and records it
```

You need Python 3.10+ and `OPENROUTER_API_KEY` in the environment. The script makes a virtualenv (Docling brings a CPU build of PyTorch; the virtualenv comes to about 2 GB), downloads the real sample K-1s, generates the made-up documents, runs Docling, runs the five models in parallel through OpenRouter, pairs them, scores everything and writes:

- `output/comparison.md`: every run side by side
- `output/<model>-alone/index.html`: each model's review screen
- `output/pair-gemini-3.8-flash+qwen3.8-flash/index.html`: the review screen for the recommended pair

A clean run took about 45 minutes and cost about 48 cents for all five models; Gemini 3.8 Flash on its own finishes in a few minutes.

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
2. **Each model reads the form** (`extract_vlm.py --model-only`). The K-1 page (or the 1099 summary page) goes to the model as an image at 200 dpi. Pydantic AI asks for a typed result: one Pydantic model per form (1065, 1120-S, 1041 and the brokerage 1099), where every value carries what was printed, its bounding box and the model's own confidence. Thinking models run at low reasoning effort; reading a form doesn't need long reasoning, and at the default they spent their whole output budget thinking.
3. **A value goes to review** when the model's confidence is below 0.9, the amount is on an attached statement (`STMT`), it isn't a well-formed amount, a coded row has no code letter, or a cross-check fails (qualified dividends above ordinary dividends, 4a + 4b ≠ 4c, a 1099-B row that doesn't balance).
4. **Pairs** (`pair.py`). Two models' saved answers are combined with no further API calls. A value is accepted only when both models report the same box and code with the same amount and neither has its own reason to send it to review. Anything only one model reported, or that the two read differently, goes to review.
5. **Statements.** For a `STMT` amount, the model reads the statement page and lists that box's lines. The reviewer sees them as a suggestion; the value stays in the queue.

`report.py` builds the review screen for each run. Clicking a value highlights its box on the page. A STMT value opens the statement page. The queue shows each flagged box cropped from the page, with the reason, and lets a person correct or confirm it. The results export to CSV. No extractor reads the answer keys; `evaluate.py` scores the output against them afterwards.

## Results

From one clean run of `./run.sh` from a fresh checkout on 2026-10-13. "Boxes" means every box on the answer key plus every value a run reported, so reading something in an empty box, or reporting a box twice, counts as an error, and the box counts differ between runs. A silent error is a wrong value that was accepted without review: the number that matters for a review queue. The held-out set is 14 documents whose scans and made-up values use a different random seed from the ones used while building the checks.

### All 30 documents

| Model | Values right | Accepted without review | Wrong but accepted | Sent to review | Cost per document | Model time per document |
|---|---|---|---|---|---|---|
| **Gemini 3.8 Flash** | **676 of 676** | **652** | **0** | **24, all STMT** | **$0.0066** | **18 s** |
| Qwen 3.8 Flash | 647 of 684 | 649 | 24 | 35 | $0.0036 | 69 s |
| Qwen3-VL 235B | 660 of 705 | 646 | 7 | 59 | $0.0026 | 46 s |
| GLM 5.3 Flash | 533 of 705 | 513 | 3 | 192 | $0.0017 | 27 s |
| Gemma 4 31B | 409 of 764 | 586 | 182 | 178 | $0.0015 | 73 s |
| Gemini 3.8 Flash + Qwen 3.8 Flash, must agree | 669 of 684 | 625 | 0 | 59 | $0.0101 | 69 s |
| Gemini 3.8 Flash + Qwen3-VL 235B, must agree | 676 of 705 | 639 | 0 | 66 | $0.0091 | 46 s |

On the held-out set alone, Gemini 3.8 Flash accepted 299 of 310 boxes, all right, and sent 11 to review, all of them STMT amounts. The Gemini + Qwen 3.8 pair accepted 288 of 312, all right, and sent 24 to review. `output/comparison.md` breaks every run down by kind of document.

The cost is OpenRouter's own figure for each call, or the listed per-token price when a call doesn't report one, and includes reading the supplemental statements. Docling adds about 11 seconds per document on CPU. A pair costs the sum of its two models and takes as long as the slower one, since they run side by side.

### What each model got wrong

- **Gemini 3.8 Flash** made no errors in this run. In an earlier full run of the same code it made one: it read Enviva 2018's `-27,942` as `-27.942` on an office scan, and that value went to review because it isn't a well-formed whole-dollar amount.
- **Qwen 3.8 Flash** read well but let 24 errors through, almost all in coded boxes on the real K-1s, where it attached amounts to the wrong code letters: box 16 (foreign transactions) on Blackstone and Enviva 2018, and the `AH*` rows on Enviva 2018. Its provider refuses the forced tool call Pydantic AI normally uses for typed output when the model is in thinking mode, so it runs with the schema in the prompt instead (`--prompted`).
- **Qwen3-VL 235B** let 7 errors through, all in Blackstone's box 13, where it assigned amounts to the wrong code letters.
- **GLM 5.3 Flash** returned a valid but empty answer for 6 of the 30 pages in this run (12 in an earlier run, including every brokerage 1099). An empty answer used to read as every box blank, so the pipeline now sends such a page to review as a whole. It also often left out the code letter in coded boxes, which sends those rows to review. Only 3 wrong values went through, but it sent 192 to review.
- **Gemma 4 31B** shifted amounts into neighbouring boxes and misread names ("ENVIRO PARTNERS, LP"). About half of what it reported was wrong.

Every model read the supplemental statement lines it reached correctly, checked by `evaluate.py` against the issuers' own text layer. Gemini 3.8 Flash read all 62 lines behind the STMT boxes and missed none.

### Gemini alone, or checked by a second model

Gemini 3.8 Flash on its own was right on every value here, but its own confidence never flagged anything: everything it sent to review was a STMT amount. On a document it does misread, nothing but the cross-checks would catch it. Pairing it with Qwen 3.8 Flash adds an independent read for about 50% more cost and a longer wait: on these documents the pair let nothing wrong through and sent 35 more values to review than Gemini alone (59 against 24 across all 30 documents), almost all of them rows where Qwen attached an amount to the wrong code. For a demo video, Gemini alone is enough. For client documents, the pair is the safer default.

## Earlier approaches

The first versions of this demo, still in the repository and run with `--tesseract`, read the forms with Tesseract OCR and rules (`extract.py`), and then checked Qwen3-VL 235B against Tesseract box by box (`extract_vlm.py` without `--model-only`). On the held-out set, Tesseract and rules accepted 182 of 321 boxes with 2 silent errors and sent 43% to review. Checking Qwen3-VL against Tesseract accepted 236 with no silent errors and sent 28% to review, much of it because Tesseract couldn't read a box the model had read right. Gemini 3.8 Flash on its own beats both. Docling's own OCR wasn't usable as a check on scans: it picked up 26% of the values on the scanned K-1s.

## What it doesn't show

- **This is not our production extraction.** It is a demo built on public tools and public models. A prospect who sends real documents will see different numbers.
- **The scans are simulated.** Real scans have problems we didn't model: staples, handwriting, stamps, pages scanned at a different scale, and colour backgrounds.
- **The sample is small.** It has three real K-1s, all Form 1065 from publicly traded partnerships. There are no real 1120-S or 1041 K-1s and no real brokerage 1099s; the made-up 1099s use our own layout. A perfect score on 676 values doesn't mean a perfect score in general.
- **Model answers vary from run to run.** Across three full runs GLM 5.3 Flash got between 58% and 76% of values right; Gemini 3.8 Flash got 675, 676 and 676 of 676.

## Files

- `run.sh`: the one command
- `fetch_real.py`: downloads the real K-1s and makes scanned copies
- `generate.py`: makes the made-up documents and `answer_key.json`
- `layout.py`: runs Docling over every sample once, writing `output/layout/`
- `extract_vlm.py`: reads every document with one model, `python extract_vlm.py <OpenRouter model id> --model-only`
- `pair.py`: combines two models' runs, `python pair.py output/<a>-alone output/<b>-alone`
- `evaluate.py`: scores a run and writes its `metrics.json`
- `report.py`: builds a run's review screen, `index.html`
- `compare.py`: writes `output/comparison.md`
- `extract.py`: the earlier Tesseract pipeline
- `record.py`: clicks through the review screen and saves `screenshots/` and `recording/walkthrough.mp4`
- `real_answer_key.json`: the real K-1s' Part III boxes and the partnership name and EIN, keyed by hand from the issuers' PDFs
- `forms/`: blank IRS Schedule K-1 forms (1065 for 2018, 2019, 2021 and 2025; 1120-S and 1041 for 2025), from irs.gov
- `SCRIPT.md`: a two-minute voice-over for recording the walkthrough

The committed screenshots, recording and `SCRIPT.md` still show the Tesseract pipeline's review screen; `record.py` needs `--tesseract` until they are redone.
