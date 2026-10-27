# Where open document pipelines break on messy documents

#128 (`reducto-open-pipeline/`) found that Gemini 3.8 Flash reading page images matched what Reducto sells on two clean FEMA flood studies. This spike runs the same pipelines on harder documents to find where they break, and whether that's where a product like Reducto would earn its price:

1. **Seven real public documents**, each with one region keyed by hand: a 1951 Census table, a 1949 USGS well table with its left edge cut off, two of ten tables on a NACA airfoil page, a microfilm sheet with four pages on it, a handwritten 990-EZ under a RECEIVED stamp, a grey 1958 State Department letter, and a sideways USGS table whose second page has no header.
2. **39 synthetic documents with tables broken on purpose**: twelve failure modes, three documents each, plus three with everything at once. The data is made up and seeded, so the answer key is exact.

**Read the two notebooks**, each top to bottom (`uv run marimo edit 1_real_documents.py`, or read them as plain Python):

1. [`1_real_documents.py`](1_real_documents.py): the seven documents, the four pipelines, and Gemini 4 Argon on the failures.
2. [`2_broken_tables.py`](2_broken_tables.py): how each broken table is drawn, and the score for each failure mode.

[`pipelines.py`](pipelines.py) holds what both notebooks share: the four pipelines and the scoring. [`model_call.py`](model_call.py) is #128's, with the model as an argument.

## Run it

```
./run.sh
```

You need [uv](https://docs.astral.sh/uv/), `tesseract` (`apt install tesseract-ocr` or `brew install tesseract`) and `OPENROUTER_API_KEY`. The documents (about 95 MB) and a handwriting font (Reenie Beanie, SIL Open Font License) are downloaded and hash-checked at run time. Everything goes to `output/` (set `MESSY_OUTPUT_DIR` to change that), and model answers are saved in `output/answers/` and reused on a re-run. A run from a fresh clone took 37 minutes on 4 CPU cores and cost $3.69 ($1.24 for notebook 1, $2.45 for notebook 2). All of the spike's runs together cost about $7.20.

## The four pipelines

All four are #128's, plus page by page, which the issue asked for:

- **Docling alone**: Docling 2.138 with Tesseract OCR and table structure. It gives tables as rows, with header rows kept, or Markdown for the letter. It can't fill a form's lines without a model.
- **Gemini, whole PDF**: Gemini 3.8 Flash gets the whole file, up to 492 pages and 26 MB in one call.
- **Gemini, page by page**: each page is rendered at 150 dpi and read on its own, then the answers are joined in page order.
- **Docling, then Gemini**: Docling's Markdown of each page, next to the page image.

Every prompt names the table and its columns. On the real documents it also names the PDF page, so this measures reading, not finding the page. #128 already showed that routing on OCR text fails silently. Each cell is scored **right**, **wrong** (a value is there but it isn't the key's, so it looks fine to a reader) or **missing**. **Extra rows** are reported rows that match no key row. Where a Gemini pipeline got under 95% right, the same pipeline was run again on **Gemini 4 Argon**, the strongest Gemini on OpenRouter.

## Results, real documents

From the clean run. The first figure is the share of cells right, with Flash.

| Document | Docling alone | Gemini, whole PDF | Gemini, page by page | Docling, then Gemini |
|---|---|---|---|---|
| Census 1951, table 33 (88 cells) | 30%, 19 wrong | 100% | 100% | 100% |
| USGS OF 49-60, clipped well table (90) | 16%, 34 wrong | 100% | 100% | 100% |
| NACA 824, table 63-009 of ten on a page (104) | 30%, 22 wrong | 100% | 100% | 100% |
| NACA 824, table 63-006 (104) | 30%, 20 wrong | 100% | 100% | 100% |
| USGS OF 61-50, microfilm, four pages a sheet (216) | 33%, 124 wrong | 98%, **4 wrong** | 100% | 99%, 2 missing |
| USGS WSP 1050, p248 with no header (115) | 0% | 85%, **15 wrong** | 91%, **10 wrong** | 100% |
| IRS 990-EZ, handwritten, lines 1-21 (28) | can't | 93%, 2 missing | 89%, 3 missing | 93%, 2 missing |
| State FOIA 1958 letter, word error rate | 95% | 0.3% | 0.0% | 0.0% |

On the failure cases, **Argon got 100%**: the 990-EZ in all three pipelines, and WSP 1050 both given the whole PDF and page by page. It cost about three times Flash's price. Flash cost $0.0001 to $0.0011 a page given the whole PDF, and $0.0023 to $0.0057 a page read as images. The full tables are in [`results/real_documents.md`](results/real_documents.md) and [`results/real_documents_bigger_model.md`](results/real_documents_bigger_model.md).

- **The worst errors look right.** Every Gemini error on the tables was a believable wrong value or a dropped cell, never garbage:
  - **Page by page, WSP 1050.** Read without the page carrying its header, Flash swapped the bicarbonate and sulfate columns in all five rows, giving 10 believable wrong values. Docling then Gemini, which saw both pages, got all 115 cells right.
  - **Whole PDF, WSP 1050.** Given all 492 pages, Flash gave values such as 114 for 67 and 56 for 43, and mislabelled the July 22 row.
  - **Whole PDF, microfilm.** Flash gave one well the next well's values.
- **It changes from run to run.** An earlier run on the same code got WSP 1050 page by page 100% right, and the whole PDF 84% right. One read is not a measurement; a second read or a check (an ion balance would catch the swapped columns) is the safeguard.
- **A long PDF fits in one call.** All 492 pages of Water-Supply Paper 1050 (15 MB) went to Flash in one call, as did NACA 824 (261 pages, 26 MB) at $0.11. That one is near the limit: base64 makes it a 34 MB request, and in a review run one OpenRouter provider rejected it with a 413 before the retry went through another. Small print suffers there, though: page images did better.
- **Handwriting needs the bigger model.** Flash read handwritten zeros as blank, and in an earlier run 18,656 as 18,658. Argon got all 28 lines in every pipeline.
- **Docling alone fails on every document.** It can't read sideways tables, drops clipped numbers, and splits NACA's ten small tables into fragments, giving 179 extra rows. Its OCR of the 1958 letter is 95% wrong.

## Results, broken tables

From the clean run, with Flash, three documents per failure mode. The first figure is the share of cells right.

| Failure mode | Docling alone | Gemini, whole PDF | Gemini, page by page | Docling, then Gemini |
|---|---|---|---|---|
| 1. Page break, no repeated header | 71% | 100% | 100% | 100% |
| 2. Row split across the break | 65% | 100% | 100% | 100% |
| 3. Continuation on the wrong page | 71% | 100% | 100% | 100% |
| 4. Wide table cut in half | 35% | 100% | **52%** | 100% |
| 5. Misaligned columns, no rules | 28% | 100% | 100% | 100% |
| 6. Columns change between pages | 59% | 100% | 97%, 26 wrong | **88%**, 208 missing |
| 7. Merged cells | 65% | 95% | 90% | 90% |
| 8. Subtotals, carried forward, repeated header | 70% | 100% | 100% | 100% |
| 9. Footnotes, (negatives), dashes, n/a | 70% | 100% | 100% | 100% |
| 10. Near-duplicate tables (FY2023 and FY2024) | 71% | 100% | 100% | 100% |
| 11. Scan damage (rotated, skewed, stamped) | 4% | 93%, **47 wrong** | 100%, 3 wrong | 97%, 13 wrong |
| 12. Handwritten corrections | 67% | 97%, 21 wrong | 98%, 18 wrong | 97%, 22 wrong |
| 13. Everything at once | 57% | 95%, 43 wrong | 96%, 37 wrong | 96%, 38 wrong |

Clean documents scored 99% given the whole PDF, and scanned ones 98%. Full tables, the Argon re-runs, cost and seconds are in [`results/broken_tables.md`](results/broken_tables.md) and [`results/broken_tables_bigger_model.md`](results/broken_tables_bigger_model.md).

- **Most of the deliberate breaks don't break Gemini.** At or near 100% in every Gemini pipeline:
  - a missing header, a row split across pages, and a continuation two pages later or in an appendix;
  - columns drifting with no rules;
  - subtotals and carried-forward lines;
  - `(1,234)`, `—` and `n/a`;
  - the right one of two near-identical tables.
- **A page turned sideways breaks the whole-PDF read.** On the page rotated 90 degrees, Flash given the PDF got 200 of 240 cells right, and all 40 of the rest were wrong, not blank. The earlier run got 113 right. Argon got 231 right. The same page rendered as an image was read right by Flash.
- **A column dropped on page 2 loses or shifts page 2.** Each pipeline failed this a different way, and it varied by run:
  - Docling then Gemini returned only page 1's rows (208 cells missing); Argon fixed that.
  - Page by page, Flash slid page 2's values one column left, so 26 values were believable but wrong. Argon, page by page, dropped page 2.
  - Given the whole PDF, Flash got it right in this run, and dropped page 2 in the earlier one.
- **Page by page can't join a table cut down the middle.** Its right half comes back as separate rows, and Argon doesn't help. Joining the halves needs the whole document, or a step that matches the halves.
- **Handwritten corrections aren't resolved.** Across 30 corrected cells, Gemini reported the handwritten number alone in 4 or 5. It put both numbers in one cell in 6 to 9, and gave the struck-out printed number or something else in the rest. Telling it which number counts is a prompting fix; reading this font is a model question.
- **A cell merged down a column isn't filled in**, by either model. Where a fund is printed once for a run of rows, Gemini leaves the cells below it blank, as the prompt's "never infer" tells it. Whether to fill them is a prompting decision.
- **Everything at once** costs 4 to 5 points, and Argon recovers only a few of them.

## Failure types, and the fix each needs

| Failure | Seen in | Fix |
|---|---|---|
| Believable wrong values in small print from a whole long PDF | WSP 1050, microfilm, mode 11 | Page-by-page images, or a bigger model (Argon fixed WSP 1050) |
| Columns swapped on a page with no header | WSP 1050, page by page | Show the header page alongside, as Docling then Gemini did, plus a check (ion balance, sums) |
| Rows after a column change dropped or shifted | Mode 6 | A check that row counts and columns match; Argon fixed one pipeline, not another |
| Table cut down the middle | Mode 4, page by page | Whole-document read, or a join step that matches the halves |
| Handwriting misread | 990-EZ, mode 12 | Bigger model (Argon got the 990-EZ right) |
| Struck-through and handwritten numbers both reported | Mode 12 | Prompting: say which number counts |
| Merged cells left blank | Mode 7 | Prompting: say whether to fill down |
| Answers differ between runs | WSP 1050, modes 6 and 11 | Read twice and compare, or check |
| Everything, read by Docling alone | All | Don't use Docling as the reader; use a VLM |

No failure here needed fine-tuning. Each was fixed, or would be, by:

- changing what the model was shown;
- a bigger model;
- a prompt;
- a check behind the read.

The biggest risk is not a blank cell but a believable wrong one, and these failures vary by run. Where a product like Reducto could earn its price is in doing the checks and re-reads, not in reading the page.

## What it doesn't show

- **Reducto itself.** Running Reducto needs an account, which needs a founder's approval. `PIPELINES` in `pipelines.py` takes a fifth pipeline.
- **EPA NEPIS 2000V9TU** isn't keyed. Its 45-by-15 typewritten table across three pages would take about an hour by hand. The issue's other optional documents aren't keyed either.
- **The real-document keys were checked by the agent that keyed them, not by a person.** Each key has a note on how it was checked: column sums, airfoil symmetry, or the IRS extract. On the 990-EZ, lines 13 to 16 sit under the stamp. They're keyed so they add to line 17 as written, and Argon reads them the same way.
- **The synthetic handwriting** is one font at one size. Real corrections vary more.
- **The page-number hint** helps the whole-PDF pipeline find the table. Finding it unaided is #128's routing question.
- **Run-to-run spread.** Each figure is one run. The earlier, partial run is described above where it differed.
- **Size.** About 1,350 lines of Python, over the 1,000-line target. Notebook 2 (about 740 lines) draws 13 kinds of broken table. Splitting the drawing code into a module would hide it from the reader, so it stays in the notebook.
