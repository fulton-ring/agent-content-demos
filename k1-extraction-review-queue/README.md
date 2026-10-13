# K-1 extraction with a review queue

This demo reads Schedule K-1s and brokerage 1099s and links every extracted value to the box it came from. Anything the software isn't sure of goes to a review queue for a person to check. It answers a sales question for the CPA document extraction play: can a two-minute screen recording show a tax preparer what they'd get, without them sending us any documents?

It runs two pipelines on the same documents and scores both against the same answer keys:

- **Tesseract and rules** (`extract.py`): OCR, blank-form templates and cross-checks. No model, no paid service.
- **A vision-language model, checked by a second reader** (`layout.py`, `extract_vlm.py`): Qwen3-VL through OpenRouter reads each form into typed Pydantic models, and every value is confirmed against an independent read of the box it names. Two model sizes are compared.

![A value on a real K-1, highlighted on the page it came from](screenshots/1-value-linked-to-box.png)

## Run it

```
./run.sh            # Tesseract pipeline always; the model pipelines too when OPENROUTER_API_KEY is set
./run.sh --record   # also clicks through the review screen and records it
```

You need Python 3.10+ and Tesseract (`apt install tesseract-ocr` or `brew install tesseract`). The script makes a virtualenv (the model pipeline adds Docling and a CPU build of PyTorch; the virtualenv comes to about 2 GB), downloads the real sample K-1s, generates the made-up documents, extracts, scores and writes the review screens:

- `output/index.html`: Tesseract and rules
- `output/qwen3-vl-235b/index.html` and `output/qwen3-vl-30b/index.html`: the model pipelines
- `output/comparison.md`: all three side by side

The model pipelines need `OPENROUTER_API_KEY` in the environment. Both models together cost about 18 cents for all 30 documents. The whole clean run took about an hour, almost all of it waiting on OpenRouter; the 30B model is the slow one. To use a Chromium you already have for the recording, set `CHROMIUM_PATH`.

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

## How the Tesseract pipeline works

1. **Find the page.** In a multi-page tax package, the extractor finds the K-1 page and the supplemental statement pages.
2. **Get the words.**
   - A born-digital page is read from its text layer, so no OCR is needed.
   - A scan is first straightened. It is then matched against the blank IRS forms for 2018, 2019, 2021 and 2025, which picks out both the form and its year: the right one scores 0.83 to 0.95 correlation and the others score below 0.75.
   - The blank form's own printing is then whited out (form dropout), which leaves only what the issuer typed. Specks and leftover rules are removed.
3. **Find each box by its label.** The box label positions come from the page itself, or from the matched blank form when the page is a scan.
4. **Read each box.** For a scan, each box is OCR'd on its own, twice, with two different image treatments.
5. **Send it to review when:**
   - OCR confidence is below 80;
   - the two OCR passes disagree;
   - there are marks in the box that no word accounts for (often a minus sign);
   - the value isn't a well-formed amount;
   - a label can't be found;
   - the amount is on an attached statement;
   - or a cross-check fails: qualified dividends above ordinary dividends, 4a + 4b ≠ 4c, a 1099-B summary row that doesn't balance or doesn't match the detail page.

## How the model pipeline works

1. **Docling reads every page once** (`layout.py`, on CPU). It finds the K-1 page and the supplemental statements, and turns each statement into a Box / Description / Amount table.
2. **The model reads the form.** The K-1 page (or the 1099 summary page) goes to Qwen3-VL as an image at 200 dpi. Pydantic AI asks for a typed result: one Pydantic model per form (1065, 1120-S, 1041 and the brokerage 1099), where every value carries what was printed, its bounding box and the model's own confidence.
3. **A second reader checks every value in the box the model named.** Each box is located by its printed label. On a born-digital page the second read is Docling's words, which come from the PDF's text layer. On a scan it is the Tesseract pipeline's reader: the page is lined up with its blank IRS form and each box is OCR'd on its own.
4. **A value goes to review when:**
   - the model's confidence is below 0.9;
   - the second read of that box says something else, or nothing (the same digits with different punctuation count as agreeing, since OCR often reads a comma as a period);
   - the model gave no code letter for a row in a coded box;
   - the second read finds a box or a row the model didn't report;
   - the value isn't a well-formed amount, or it's on an attached statement;
   - or one of the Tesseract pipeline's cross-checks fails.
5. **Statements.** For a `STMT` amount, the model reads the statement page and lists that box's lines. The reviewer sees them as a suggestion, each marked by whether Docling's table has the same code and amount. The value stays in the queue.

Docling's OCR wasn't usable as the second read on scans. On the scanned K-1s it picked up 26% of the answer-key values: 84% on the clean made-up scans, 21% on office scans and 5% on bad scans. It finds a form's blocks of printed text, but most of the small typed amounts inside the boxes never reach OCR. It did better on the brokerage summaries (93 to 100% of amounts) but dropped lots from the detail pages that the cross-check needs, so the brokerage scans use Tesseract as the second read as well.

LlamaIndex isn't used. A tax package has at most a handful of statement pages, and Docling's tables already say which page has which box's lines, so there is nothing for a retrieval index to do. LibreOffice isn't used either, since every input is a PDF.

## The review screen

`report.py` builds the review screen for each pipeline. Clicking a value highlights its box on the page. A STMT value opens the statement page. The queue shows each flagged box cropped from the page, with the reason, and lets a person correct it or confirm it. The results export to CSV.

Neither extractor reads the answer keys. `evaluate.py` scores the output against them afterwards.

## Results

These are from one clean run of `./run.sh` from a fresh checkout, with Tesseract 5.3.4, Docling 2.138 and Pydantic AI 2.55, on 2026-10-13. "Boxes" means every box on the answer key plus every value a pipeline reported, so reading something in an empty box, or reporting a box twice, counts as an error. That's why the box counts differ between pipelines.

**Tuning and held-out sets.** The Tesseract pipeline's thresholds and rules were tuned on the first set of documents. The model pipeline's checks were tuned the same way, on the same set: no output from the held-out documents was looked at until the scoring logic was final. The only changes after that were to how a statement page is found, retries when OpenRouter rate-limits a call, and the statement check in `evaluate.py`, none of which change what gets accepted. The held-out set uses a different random seed for its scans and made-up documents, so it is the fairer measure.

### Held-out set (14 documents)

| Pipeline | Boxes | Accepted without review | Right when accepted | Sent to review | Misreads | Caught by review | Silent errors |
|---|---|---|---|---|---|---|---|
| Tesseract and rules | 321 | 182 | 180 (98.9%) | 139 (43%) | 68 | 66 | 2 |
| **Qwen3-VL 235B, checked** | **327** | **236** | **236 (100%)** | **91 (28%)** | **17** | **17** | **0** |
| Qwen3-VL 30B, checked | 450 | 124 | 123 (99.2%) | 326 (72%) | 201 | 200 | 1 |

### By kind of document (held-out, except the born-digital K-1s, which have nothing to tune)

Accepted without review, then how many of those were right:

| | Tesseract and rules | Qwen3-VL 235B | Qwen3-VL 30B |
|---|---|---|---|
| Real K-1s, born-digital | 91, all right | 88, all right | 39, all right |
| Real K-1 office scans | 64, 63 right | 85, all right | 32, 31 right |
| Real K-1 bad scans | 26, all right | 45, all right | 12, all right |
| Made-up clean scans | 37, 36 right | 35, all right | 22, all right |
| Made-up office scans | 35, all right | 37, all right | 28, all right |
| Made-up bad scans | 20, all right | 34, all right | 30, all right |

`output/comparison.md` has every row of every table after a run.

### Cost and time per document

| Pipeline | Cost | Time |
|---|---|---|
| Tesseract and rules | nothing | 6 seconds |
| Qwen3-VL 235B | $0.0022 | 95 seconds: 9 for Docling on CPU, 85 waiting on OpenRouter |
| Qwen3-VL 30B | $0.0037 | 299 seconds, almost all waiting on OpenRouter |

The cost is OpenRouter's own figure for each call, summed by `extract_vlm.py`. It includes reading the supplemental statements. The time is mostly queueing at the provider, and some calls were rate-limited and retried; a dedicated endpoint would be far faster.

### Supplemental statements

The 235B model read every statement line behind the six `STMT` boxes in the two packages that have statements (Enviva 2021 and Blackstone 2019): 62 lines, all 62 right and none missed, checked by `evaluate.py` against the issuers' own text layer. On 10 of those lines Docling's table disagreed with the model. Each time the model was right and Docling's table had merged or shifted rows, which is why these readings are shown to the reviewer as suggestions rather than accepted.

### The errors

- **Tesseract and rules, 2 silent errors.** On the Blackstone office scan, box 13 E, the issuer printed a dash for zero and OCR missed both the dash and its row. On a made-up 1041, OCR skipped the trust's name and read the address line under it with high confidence.
- **Qwen3-VL 235B, no silent errors** in this run, or in an earlier full run of the same code (238 accepted, all right). Its 17 held-out misreads were all caught. Nine are rows Tesseract read on a scan that didn't line up with the model's, mostly because Tesseract misread a code letter (`L*` as `L°`, `B` as `8`) or read specks as a row. Two are rows the model skipped and Tesseract found. Six are code letters the model repeated or left out in the made-up 1041s. Each one disagreed with the second read, so each went to review.
- **Qwen3-VL 30B, 1 silent error**, the same Blackstone 13 E dash that Tesseract missed, since Tesseract was its second reader there. With the same prompt and schema, the 30B model listed empty boxes, put box numbers where the code letters go, and moved amounts between boxes (on the Enviva 2021 K-1 it put box 19's 32,336 under box 9b), so most of what it read went to review. It also wrote about three times as many output tokens, which is why it cost more than the larger model.

## What this shows

- Born-digital K-1s, which is how most PTP and fund K-1s arrive, extract exactly with either pipeline, with every value tied to its box. The only things left for a person are the amounts the issuer moved to a statement, and the model pipeline also reads those statements correctly as a suggestion.
- On scans, Qwen3-VL 235B with a second reader lets about 30% more values through without review than Tesseract does (236 against 182 on the held-out set), and every one it let through was right. The share sent to review fell from 43% to 28%.
- The check is what makes the model safe to use. Its first answers had values in the wrong box and skipped rows; none of those got through, because each one disagreed with the second read of the box it named.
- The smaller model isn't a cheaper option: it cost more per document and sent nearly three-quarters of the boxes to review.

## What it doesn't show

- **This is not our production extraction.** It is a demo built on public tools and a public model. A prospect who sends real documents will see different numbers.
- **The scans are simulated.** Real scans have problems we didn't model: staples, handwriting, stamps, pages scanned at a different scale, and colour backgrounds.
- **The sample is small.** It has three real K-1s, all Form 1065 from publicly traded partnerships. There are no real 1120-S or 1041 K-1s and no real brokerage 1099s; the made-up 1099s use our own layout. The statement check covers two packages.
- **Model answers vary from run to run.** Two full runs of the 235B pipeline gave 238 and 236 accepted values on the held-out set, both with no silent errors. The rate of silent errors is zero on these documents, which is not the same as zero in general.
- **On a scan the second reader is Tesseract**, so a box Tesseract can't read goes to review even when the model read it right. That is most of the review load on bad scans.
- **Header fields are weaker than box values on scans.** The partnership's name and EIN often go to review, because Tesseract reads the address line or misreads a digit.
- **The review queue is still large on bad scans:** a third to a half of the boxes with the 235B model, depending on the set.

## Files

- `run.sh`: the one command
- `fetch_real.py`: downloads the real K-1s and makes scanned copies
- `generate.py`: makes the made-up documents and `answer_key.json`
- `extract.py`: the Tesseract pipeline
- `layout.py`: runs Docling over every sample once, writing `output/layout/`
- `extract_vlm.py`: the model pipeline, `python extract_vlm.py <OpenRouter model id>`
- `evaluate.py`: scores a pipeline's output and writes its `metrics.json`
- `report.py`: builds a pipeline's review screen, `index.html`
- `compare.py`: writes `output/comparison.md`
- `record.py`: clicks through the review screen and saves `screenshots/` and `recording/walkthrough.mp4`
- `real_answer_key.json`: the real K-1s' Part III boxes and the partnership name and EIN, keyed by hand from the issuers' PDFs
- `forms/`: blank IRS Schedule K-1 forms (1065 for 2018, 2019, 2021 and 2025; 1120-S and 1041 for 2025), from irs.gov
- `SCRIPT.md`: a two-minute voice-over for recording the walkthrough

The committed screenshots and recording still show the Tesseract pipeline's review screen.
