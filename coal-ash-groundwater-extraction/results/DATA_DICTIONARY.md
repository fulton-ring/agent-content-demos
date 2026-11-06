# `groundwater_results` data dictionary

One row per constituent per lab result page, as the pair of models read it. Same columns in the CSV and the Parquet file. `3_results.py` writes both.

| Column | Meaning |
|---|---|
| `plant` | PacifiCorp plant: `dave-johnston`, `hunter`, `huntington`, `jim-bridger` or `naughton` |
| `ccr_unit` | The CCR unit the report covers, as in PacifiCorp's URL (for example `ccr-landfill`, `ash-pond`) |
| `report_year` | The year the report covers (posted the following January) |
| `page_url` | The report PDF on PacifiCorp's site, opened at the page (`#page=N`) |
| `page` | Page number in the PDF, from 1 |
| `page_kind` | `scanned` (one picture covers most of the page) or `born-digital` |
| `well` | Client sample ID as Gemini read it: usually the monitoring well, sometimes a duplicate (`DUP`) or field blank (`FB`) |
| `collection_date` | Collection date as Gemini read it, `YYYY-MM-DD` |
| `analyte` | One of the 20 Appendix III and IV constituents the results tables hold (`boron`, `tds`, `ph`, …). Other rows on the page are not kept |
| `result_printed` | The result exactly as printed, such as `< 0.00200`, `ND` or `1.86` |
| `nondetect` | True if the result is below the reporting limit (`<` or `ND`) |
| `value` | The number: the measured value, or the detection limit for a non-detect. mg/L, or standard units for pH |
| `units` | Units as printed |
| `reporting_limit` | The lab's reporting limit as printed, if any |
| `lab_qualifier` | The lab's flag beside the result, if any (for example `H`, received outside holding time) |
| `bbox` | `[x0, y0, x1, y1]` of the result on the page, in 0–1000 page coordinates, from Gemini |
| `bbox_suspect` | True if the box is taller than it is wide. Gemini sometimes returns `[y0, x0, y1, x1]`, so the box, not the value, is in doubt |
| `gemini_read`, `mistral_read` | What each model read, as printed |
| `in_review` | True if the field, or the page's well or date, went to review: the models disagree, only one read it, or it failed a check |
| `review_reason` | Why, in words |
| `checked` | True if this value was looked up on the page image (listed in `adjudications.json`). The checking was done by the agent that built the demo, not a person |
| `in_results_table` | True if the page matched a sample in the consultant's results table, which is the answer key |

`review_queue.csv` holds the rows with `in_review` True, plus one row for each page where only one model called it a lab result page.

The `well` column is what the models read. On three pages both models read the well `HLF-1O` (letter O) as `HLF-10`; `adjudications.json` lists them. Those rows still say `HLF-10`.
