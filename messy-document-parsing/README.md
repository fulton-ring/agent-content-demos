# Where open document pipelines break on messy documents

#128 (`reducto-open-pipeline/`) found that Gemini 3.8 Flash reading page images matched what Reducto sells on two clean FEMA flood studies. This spike runs the same pipelines on harder documents to find where they break, and whether that's where a product like Reducto would earn its price:

1. **Seven real public documents**, each with one region keyed by hand: a 1951 Census table, a 1949 USGS well table with its left edge cut off, two of ten tables on a NACA airfoil page, a microfilm sheet with four pages on it, a handwritten 990-EZ under a RECEIVED stamp, a grey 1958 State Department letter, and a sideways USGS table whose second page has no header.
2. **39 synthetic documents with tables broken on purpose**: twelve failure modes, three documents each, plus three with everything at once. The data is made up and seeded, so the answer key is exact.

**Status: stopped partway.** The shared OpenRouter key reached its $50 lifetime limit during notebook 2 (403 "Key limit exceeded"). This spike had spent about $3.50 of it. Notebook 1 is complete. In notebook 2, three of the four pipelines are complete on Gemini 3.8 Flash. For "Docling, then Gemini", 25 of 39 documents ran and 14 failed on the limit. The Gemini 4 Argon re-run on notebook 2's failure cases didn't run. The numbers below come from the answers saved before the limit was hit.

**Read the two notebooks**, each top to bottom (`uv run marimo edit 1_real_documents.py`, or read them as plain Python):

1. [`1_real_documents.py`](1_real_documents.py): the seven documents, the four pipelines, and Gemini 4 Argon on the failures.
2. [`2_broken_tables.py`](2_broken_tables.py): how each broken table is drawn, and the score for each failure mode.

[`pipelines.py`](pipelines.py) holds what both notebooks share: the four pipelines and the scoring. [`model_call.py`](model_call.py) is #128's, with the model as an argument.

## Run it

```
./run.sh
```

You need [uv](https://docs.astral.sh/uv/), `tesseract` (`apt install tesseract-ocr` or `brew install tesseract`) and `OPENROUTER_API_KEY`. The documents (about 95 MB) and a handwriting font (Reenie Beanie, SIL Open Font License) are downloaded and hash-checked at run time. Everything goes to `output/` (set `MESSY_OUTPUT_DIR` to change that), and model answers are saved in `output/answers/` and reused on a re-run.

## The four pipelines

All four are #128's, plus page by page, which the issue asked for:

- **Docling alone**: Docling 2.138 with Tesseract OCR and table structure. It gives tables as rows, with header rows kept, or Markdown for the letter. It can't fill a form's lines without a model.
- **Gemini, whole PDF**: Gemini 3.8 Flash gets the whole file, up to 492 pages and 26 MB in one call.
- **Gemini, page by page**: each page is rendered at 150 dpi and read on its own, then the answers are joined in page order.
- **Docling, then Gemini**: Docling's Markdown of each page, next to the page image.

Every prompt names the table and its columns. On the real documents it also names the PDF page, so this measures reading, not finding the page. #128 already showed that routing on OCR text fails silently. Each cell is scored **right**, **wrong** (a value is there but it isn't the key's, so it looks fine to a reader) or **missing**. **Extra rows** are reported rows that match no key row.

## Results, real documents (notebook 1, complete)

| Document | Docling alone | Gemini, whole PDF | Gemini, page by page | Docling, then Gemini |
|---|---|---|---|---|
| Census 1951, table 33 (88 cells) | 30% right, 19 wrong | 100% | 100% | 100% |
| USGS OF 49-60, clipped well table (90) | 16%, 34 wrong | 100% | 100% | 100% |
| NACA 824, table 63-009 of ten on a page (104) | 30%, 22 wrong | 100% | 100% | 100% |
| NACA 824, table 63-006 (104) | 30%, 20 wrong | 100% | 100% | 100% |
| USGS OF 61-50, microfilm, four pages a sheet (216) | 33%, 124 wrong | 99%, **3 wrong** | 100% | 99%, 2 missing |
| USGS WSP 1050, p248 with no header (115) | 0% | 84%, **14 wrong**, 4 missing | 100% | 100% |
| IRS 990-EZ, handwritten, lines 1-21 (28) | can't | 86%, 1 wrong | 89%, 1 wrong | 93% |
| State FOIA 1958 letter, word error rate | 95% | 0.3% | 0.0% | 0.0% |

The full table, with extra rows, cost and seconds per page, is in [`results/real_documents.md`](results/real_documents.md). Gemini cost $0.0004 to $0.0015 a page given the whole PDF, and $0.0024 to $0.0057 a page read as images.

- **A long PDF fits in one call, but small print suffers.** All 492 pages of Water-Supply Paper 1050 (15 MB) went to Flash in one call for $0.20, and so did NACA 824 (261 pages, 26 MB) for $0.11. On WSP 1050's headerless continuation page, Flash left out one row and gave plausible wrong values for another: 466 for 499, 31 for 51 and 7.4 for 7.2. Read as a 150 dpi image, the same page came back with every cell right.
- **On microfilm, one row took the next row's values.** Given the whole PDF, Flash gave well SE1023 the values of E1023 (50, 115, 10 for 57, 160, 50). Every value is believable. Page by page got all 216 cells right.
- **Handwriting is where Flash fails and Argon doesn't.** On the 990-EZ, Flash read handwritten zeros as blank and 18,656 as 18,658. Gemini 4 Argon got all 28 lines right in every pipeline, for about three times the cost. It also fixed WSP 1050 given the whole PDF (115 of 115).
- **Docling alone fails on every document.** It can't read sideways tables, drops clipped numbers, and merges NACA's ten small tables into fragments, giving 179 extra rows. Its OCR of the 1958 letter is 95% wrong.

## Results, broken tables (notebook 2, partial)

Gemini 3.8 Flash, three documents per failure mode. The first figure is the share of cells right.

| Failure mode | Docling alone | Gemini, whole PDF | Gemini, page by page |
|---|---|---|---|
| 1. Page break, no repeated header | 71% | 100% | 100% |
| 2. Row split across the break | 65% | 100% | 100% |
| 3. Continuation on the wrong page | 71% | 100% | 100% |
| 4. Wide table cut in half | 35% | 100% | **50%** |
| 5. Misaligned columns, no rules | 28% | 100% | 100% |
| 6. Columns change between pages | 59%, 131 wrong | **88%**, 208 missing | 100% |
| 7. Merged cells | 65% | 90% | 90% |
| 8. Subtotals, carried forward, repeated header | 70% | 100% | 100% |
| 9. Footnotes, (negatives), dashes, n/a | 70% | 100% | 100% |
| 10. Near-duplicate tables (FY2023 and FY2024) | 71% | 100% | 100% |
| 11. Scan damage (rotated, skewed, stamped) | 4% | **81%, 125 wrong** | 100%, 2 wrong |
| 12. Handwritten corrections | 67% | 96%, 25 wrong | 97%, 20 wrong |
| 13. Everything at once | 57% | 95%, 40 wrong | 96%, 37 wrong |

Docling, then Gemini, ran on 25 of 39 documents before the limit. It scored 96% on the clean ones that ran and 99% on the scanned ones. The full tables are in [`results/broken_tables.md`](results/broken_tables.md).

- **Most of the deliberate breaks don't break Gemini.** It reads a missing header, a row split across pages, a continuation two pages later or in an appendix, drifting columns without rules, subtotals, carried-forward lines, `(1,234)`, `—`, `n/a` and the right one of two near-identical tables, all at or near 100%.
- **Turning a page sideways breaks the whole-PDF read.** On the page rotated 90 degrees, Flash given the PDF got 113 of 240 cells right, and 114 of the rest were wrong, not blank. The same page rendered as an image was read perfectly.
- **When the columns change on page 2, the whole-PDF read stops at page 1.** Where page 2 drops a column, Flash returned only page 1's rows (208 cells missing). Page by page got every cell.
- **Page by page can't join a table cut down the middle.** Its right half comes back as separate rows (90 extra rows, half the cells missing). Joining the halves needs the whole document, or a step that matches the halves.
- **Handwritten corrections aren't resolved.** Across 30 corrected cells, Flash reported the handwritten number alone in 3 to 7 and the struck-out printed number in 1 to 3. It put both numbers in one cell in 5 to 8, and gave something else in 16 or 17. Telling it which number counts is a prompting fix; reading this font is a model question. The Argon re-run didn't happen.
- **A cell merged down a column isn't filled in.** Where a fund is printed once for a run of rows, Gemini leaves the cells below it blank, as the prompt's "never infer" tells it. Whether to fill them is a prompting decision.

## Failure types, and the fix each needs

| Failure | Seen in | Fix |
|---|---|---|
| Plausible wrong values in small print, from a whole long PDF | WSP 1050, microfilm | Page-by-page images, or a bigger model (Argon fixed WSP 1050) |
| Rotated page misread | Mode 11 | Page-by-page images, or a rotation check before reading |
| Rows after a column change dropped | Mode 6 | Page by page, or a check that the row count matches |
| Table cut down the middle | Mode 4, page by page | Whole-document read, or a join step that matches the halves |
| Handwriting misread | 990-EZ, mode 12 | Bigger model (Argon got the 990-EZ right) |
| Struck-through and handwritten numbers both reported | Mode 12 | Prompting: say which number counts |
| Merged cells left blank | Mode 7 | Prompting: say whether to fill down |
| Everything, read by Docling alone | All | Don't use Docling as the reader; use a VLM |

No failure here needed fine-tuning. Each was fixed by changing what the model was shown or which model read it, or would be fixed by a check behind it.

## What it doesn't show

- **The rest of notebook 2.** The 14 missing Docling-then-Gemini documents and the Argon re-runs need about $1 more in model calls. The numbers above aren't yet from a clean run of `./run.sh`.
- **Reducto itself.** Running Reducto needs an account, which needs a founder's approval. `PIPELINES` in `pipelines.py` takes a fifth pipeline.
- **EPA NEPIS 2000V9TU** isn't keyed. Its 45-by-15 typewritten table across three pages would take an hour by hand. The issue's other optional documents aren't keyed either.
- **The real-document keys were checked by the agent that keyed them, not by a person.** Each key has a note on how it was checked: column sums, airfoil symmetry, or the IRS extract. The 990-EZ's lines 13 and 16 are under the stamp. They're keyed so that lines 13 to 16 add to line 17 as written, and Argon reads them the same way.
- **The synthetic handwriting** is one font at one size. Real corrections vary more.
- **The page-number hint** helps the whole-PDF pipeline find the table. Finding it unaided is #128's routing question.
- **Size.** About 1,350 lines of Python, over the 1,000-line target. Notebook 2 (about 740 lines) draws 13 kinds of broken table. Splitting the drawing code into a module would hide it from the reader, so it stays in the notebook.
