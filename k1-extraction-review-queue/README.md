# K-1 extraction with a review queue

This demo reads Schedule K-1s and brokerage 1099s and links every extracted value to the box it came from. Anything the software isn't sure of goes to a review queue for a person to check. It answers a sales question for the CPA document extraction play: can a two-minute screen recording show a tax preparer what they'd get, without them sending us any documents?

![A value on a real K-1, highlighted on the page it came from](screenshots/1-value-linked-to-box.png)

## Run it

```
./run.sh            # a few minutes on a laptop CPU
./run.sh --record   # also clicks through the review screen and records it
```

You need Python 3.10+ and Tesseract (`apt install tesseract-ocr` or `brew install tesseract`). The script makes a virtualenv, downloads the real sample K-1s, generates the made-up documents, extracts, scores and writes `output/index.html`. Open that file in a browser. To use a Chromium you already have for the recording, set `CHROMIUM_PATH`.

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
6. **Show it.** `report.py` builds the review screen. Clicking a value highlights its box on the page. A STMT value opens the statement page. The queue shows each flagged box cropped from the page, with the reason, and lets a person correct it or confirm it. The results export to CSV.

The extractor never reads the answer keys. `evaluate.py` scores its output against them afterwards.

## Results

These are from a clean run of `./run.sh` with Tesseract 5.3.4. "Boxes" means every box on the answer key plus every value the extractor reported. Blank boxes count, so reading something in an empty box is an error.

I tuned the thresholds and rules while looking at the first set of documents. The held-out set uses a different random seed for its scans and made-up documents. I ran it once, after the code was final, and changed nothing afterwards, so it is the fairer measure.

| | Boxes | Accepted without review | Right when accepted | Sent to review | Misreads | Caught by review | Silent errors |
|---|---|---|---|---|---|---|---|
| Real K-1s, born-digital | 97 | 91 | 91 (100%) | 6 (all STMT) | 0 | 0 | 0 |
| Tuning set, all | 371 | 253 | 253 (100%) | 118 | 55 | 55 | 0 |
| **Held-out set, all** | **321** | **182** | **180 (98.9%)** | **139** | **68** | **66** | **2** |
| Held-out, real K-1 office scans | 99 | 64 | 63 | 35 | 16 | 15 | 1 |
| Held-out, real K-1 bad scans | 74 | 26 | 26 | 48 | 31 | 31 | 0 |
| Held-out, made-up clean scans | 50 | 37 | 36 | 13 | 3 | 2 | 1 |
| Held-out, made-up office scans | 47 | 35 | 35 | 12 | 4 | 4 | 0 |
| Held-out, made-up bad scans | 51 | 20 | 20 | 31 | 14 | 14 | 0 |

The two silent errors on the held-out set are:

- **Blackstone office scan, box 13 E.** The issuer printed a dash for zero, and OCR missed both the dash and its row. Other rows in the same box were in review, so a reviewer looking at box 13 would see it on the page, but it isn't flagged on its own.
- **Made-up 1041, the trust's name.** OCR skipped the name line and read the address line under it with high confidence. A name isn't an amount, so no cross-check can catch it.

Speed: 2 to 3 seconds for a whole born-digital tax package, and 4 to 12 seconds for a scanned page, on one CPU core.

## What this shows

- Born-digital K-1s, which is how most PTP and fund K-1s arrive, extract exactly, with every value tied to its box. The only things left for a person are the amounts the issuer moved to a statement.
- On scans, the review queue is what makes the output usable. On the held-out set it caught 66 of 68 misreads, and 98.9% of the values it let through were right.
- Showing the box next to each value is what makes review fast. A preparer looks at a cropped box and types a number. They don't hunt through the page.

## What it doesn't show

- **This is not our production extraction.** It uses Tesseract OCR, form templates and rules, with no language model and no paid service. A model would likely read more of the scanned boxes (fewer reviews) and could read the statement pages. Nothing here measures that.
- **The scans are simulated.** Real scans have problems we didn't model: staples, handwriting, stamps, pages scanned at a different scale, and colour backgrounds.
- **The sample is small.** It has three real K-1s, all Form 1065 from publicly traded partnerships. There are no real 1120-S or 1041 K-1s, and no real brokerage 1099s. The made-up documents use our own layout for the 1099s.
- **It doesn't read supplemental statements.** STMT amounts go to review with a link to the statement page.
- **Header fields are weak on scans.** These are the partnership's name and EIN. On scans they often go to review or come out wrong. Box values are the focus.
- **The review queue is large on bad scans** (up to two-thirds of the boxes). On those pages the demo shows a person doing the work, with the software pointing at the boxes.

## Files

- `run.sh`: the one command
- `fetch_real.py`: downloads the real K-1s and makes scanned copies
- `generate.py`: makes the made-up documents and `answer_key.json`
- `extract.py`: the extractor
- `evaluate.py`: scores the extraction and writes `output/metrics.json`
- `report.py`: builds the review screen, `output/index.html`
- `record.py`: clicks through the review screen and saves `screenshots/` and `recording/walkthrough.mp4`
- `real_answer_key.json`: the real K-1s' Part III boxes and the partnership name and EIN, keyed by hand from the issuers' PDFs
- `forms/`: blank IRS Schedule K-1 forms (1065 for 2018, 2019, 2021 and 2025; 1120-S and 1041 for 2025), from irs.gov
- `SCRIPT.md`: a two-minute voice-over for recording the walkthrough
