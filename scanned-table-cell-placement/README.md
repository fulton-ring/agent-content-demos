# When AI reads an old scanned table, does each number land in the right cell, and can the printed totals check it?

Issue [#328](https://github.com/fulton-ring/agent-content-demos/issues/328). The `fema-nrc-extraction-accuracy` spike (PR #177) found 99.5% of the keyed numbers on the poorest NRC scans when a model read the page image. "Found" there meant the number showed up anywhere in the transcript. This spike asks whether those numbers sit in the right row and column. It also asks whether adding up a column and comparing it with the total printed on the page catches the ones that don't, without an answer key.

**In short:**

- **Reading the page image, found and right cell are the same.** Of 286 NRC table values, Haiku put all 286 in the right cell, and Gemini put every value it returned in the right cell (it refused one page). On the scanned FIS tables, both models put all 182 values in the right cell. On the image pipeline, the worry that "found" hides values in the wrong cell doesn't hold.
- **Reading OCR text, "found" overstates by 8 to 29 points.** The model pipelines that read the PDF's text layer or Tesseract's text found 43-78% of the NRC table values but put only 34-65% in the right cell. OCR text loses the table's layout, so values end up in the next column or interleaved with a neighbouring row.
- **The totals check caught every column with an error, with no false alarms, but only 7 columns could be checked.** Only 2 of 13 keyed tables print a total. Across 42 column checks (7 columns × 6 pipelines), 33 had a wrong value and all 33 failed the check. All 9 correct columns passed. The check caught two subtle cases: through Tesseract, Haiku misread 15 of 60 pellet weights by a digit (11.595 for 11.505) and Flash misread 8. Each value looked plausible on its own, but the columns added up to 702.865 g and 704.333 g against the printed 704.091.

So the argument splits. Reading digits and placing them are separate problems only when the model reads OCR text, not when it reads the image. The totals check works where totals exist, but most of these tables don't print any.

Read the notebook top to bottom: [`cell_placement.py`](cell_placement.py) (`uv run marimo edit cell_placement.py`, or read it as plain Python). The tables it prints are in [`results/results.md`](results/results.md).

## Run it

```
./run.sh
```

You need [uv](https://docs.astral.sh/uv/) and a checkout of the whole repo. The notebook reads the saved model answers and keys in `../fema-nrc-extraction-accuracy/` (set `SOURCE_SPIKE_DIR` to point somewhere else) and doesn't change them. It calls no model and downloads nothing. A run took under 1 second after `uv` installed the environment, and wrote `results/` (set `CELL_PLACEMENT_RESULTS_DIR` to change that).

**Cost:** $0 for this run. The saved answers it rescores cost $1.15 when the source spike made them.

## Data

- **Model answers:** the source spike's saved answers in `fema-nrc-extraction-accuracy/answers/`. For NRC: Claude Haiku 5.5 and Gemini 3.8 Flash, each reading the page image, the PDF's text layer or Tesseract's text. For FIS: the same two models across its five pipelines. The two no-model NRC pipelines (text layer alone, Tesseract alone) aren't saved and would need Tesseract and the PDFs, so they're left out.
- **FIS key:** `fis_key.json` from the source spike, which is already rows and columns: 404 values, 8 *Summary of Discharges* tables (4 scanned, 4 born digital).
- **NRC cell key:** [`nrc_cell_key.json`](nrc_cell_key.json), new here. Of the 10 NRC pages the source spike keyed, only 4 are tables. The others are reference lists, a contents page, prose and figures. For those 4 pages (5 tables), we keyed each row's label and its values left to right, by eye from the page images. The notebook checks that every value keyed is among the source key's numbers for that page. On the 1981 dot-matrix pellet table, the source key covers rows 1-15, which are scored. Rows 16-60 are needed only for the totals. They come from the two image reads, which agree on all 600 values, and whose weight and length columns add up exactly to the printed totals. They aren't scored, because scoring the image pipelines against their own reading would be circular.

**How a transcript becomes cells.** NRC answers are transcripts, not tables. For each table the notebook cuts the transcript from the table's title to its note, finds each row's label, and reads the values from there to the next label, left to right. A value is *in the right cell* if it's the n-th value in its row, as printed. It's *in the right row* if it's anywhere in that stretch, and *found* if it's anywhere in the transcript. Printed placeholders (`-`, `---`, `NA`, `*`) hold a column but aren't scored. FIS answers are typed rows, so the cell score is the source spike's own method.

## Results

### Found vs right cell, NRC tables (286 values per pipeline; Wilson 95% interval)

| Pipeline | Model | Found | Right row | Right cell |
|---|---|---|---|---|
| Page image | Haiku | 100.0% (99-100) | 100.0% | 100.0% (99-100) |
| | Flash | 72.4% (67-77) | 72.4% | 72.4% (67-77) |
| Text layer, then model | Haiku | 43.0% (37-49) | 37.1% | 34.6% (29-40) |
| | Flash | 77.3% (72-82) | 68.5% | 48.6% (43-54) |
| Tesseract, then model | Haiku | 45.1% (39-51) | 40.6% | 34.3% (29-40) |
| | Flash | 78.0% (73-82) | 73.4% | 64.7% (59-70) |

By scan quality (the source spike's thirds: 2 pages each in poor and fair, none in good), the image pipeline has no gap in either. The largest gap is Flash on the text layer of the poor scans: 71.6% found, 36.2% right cell. Flash's 72.4% on the image is one page Gemini refused four times in the source spike (HTTP 502, "blocked the response: OTHER"). Its 79 values there count as missing, and every value it did return is in its cell.

### Found vs right cell, scanned FIS tables (182 values per pipeline)

| Pipeline | Haiku found / cell | Flash found / cell |
|---|---|---|
| Page image | 100.0% / 100.0% | 100.0% / 100.0% |
| Tesseract page | 29.7% / 29.7% | 80.2% / 74.7% |
| PDF, whole study | 39.6% / 36.3% | 97.3% / 97.3% |

The FIS gap is smaller (0-10 values) because the model types each row into named fields, which keeps a value with its column. On born-digital FIS tables the gap is 0-1 values.

### Totals check

| | Count |
|---|---|
| Tables that print a total | 2 of 13 keyed (5777799 Table II; 1083928 pellet table) |
| Columns with a printed total | 7 (5 leakage cases; total weight; total length) |
| Column checks (7 × 6 pipelines) | 42 |
| With an error: caught / missed | 33 / 0 |
| Correct: wrongly flagged | 0 of 9 |
| Errors in caught columns: wrong cell / wrong digit / missing | 162 / 205 / 207 |
| Errors in missed columns | 0 |

A column fails if its values don't add up to its total, to the last printed decimal, or if a value is missing so it can't be added up. Most caught columns were broken in ways a reviewer would see anyway (rows missing, every `.4204` read as `.24204`). The two weight columns read through Tesseract are the cases where a reviewer wouldn't notice.

## What this doesn't show

- **Few totals, few pages.** The catch rate rests on 7 columns from 2 tables. That's 42 checks, but far fewer independent cases. The accuracy scores rest on 4 NRC pages and 8 FIS pages. The intervals treat cells as independent, and they aren't.
- **What the check can't catch.** Swaps within a column, errors that cancel out, and any table without a printed total: none of the 8 FIS tables, the fragility table or the absorbent table print one. It also says a column is wrong, not which cell.
- **An AI-built key.** The source NRC key and the row/column key here were both made by an AI worker, not checked by a person.
- **The OCR-text pipelines weren't asked for a table.** They were asked for "a clean transcription". Their cell scores measure whether the output can be used as a table, not whether they followed a table instruction. The row finder only sees a row if its label survived OCR.
- **One run per pipeline.** These are the source spike's single saved answers. A re-run would vary.
- **What we looked at first.** Table-structure metrics such as TEDS (PubTabNet) and GriTS score whole predicted tables as HTML or grids. Our answers are free-text transcripts, so we score cells against a row/column key directly, with a few lines of regex. The scoring reuses the source spike's FIS row pairing and its rule for what counts as a number.
