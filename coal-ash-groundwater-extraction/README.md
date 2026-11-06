# Coal ash groundwater reports: extraction error, review rate and cost per page

Every US coal plant with an ash pond or landfill must post an annual groundwater monitoring report, a PDF that often runs to hundreds of pages. EIP typed the first year of them (443 reports from 265 plants, last updated 2019-04-30) into a database by hand. Nobody has typed the reports posted since. This spike runs the method from [`scanned-990ez-extraction/`](../scanned-990ez-extraction/) on those reports:

1. Draft the schema from sample pages, then freeze it.
2. Two independent vision models read every page.
3. A field goes to review when the models disagree or the field fails a check.
4. Every value keeps its page and box, and the error rate is measured.

It answers issue #188: can this extract every year of a set like EIP's for cents a page, at an error rate a nonprofit could show a funder?

![The lab printed HLF-1O with a letter O; both models read HLF-10](screenshots/accepted-wrong-well-huntington_ccr-landfill_2018_p0129.png)

*The one kind of error that got through: the lab printed the well `HLF-1O` (letter O), and both models read `HLF-10`.*

## Read it

Three marimo notebooks, each meant to be read top to bottom. Open one with `uv run marimo edit 1_documents.py`, or read it as plain Python.

1. [`1_documents.py`](1_documents.py): the question, the reports, finding lab result pages, and parsing the answer key.
2. [`2_extraction.py`](2_extraction.py): drafting and freezing the schema, and the two models reading every page.
3. [`3_results.py`](3_results.py): the review rule, the scores, cost, the dataset and the size of the whole job.

## Run it

```
./run.sh
```

You need [uv](https://docs.astral.sh/uv/). The model answers are committed under `answers/`, so a re-run rescores without calling a model and needs no key. Reading a page that isn't saved needs `OPENROUTER_API_KEY`, and spending stops at $4.50.

`run.sh` runs the three notebooks in order. They download the seven reports (about 120 MB) to `output/`, which is not committed (set `CCR_OUTPUT_DIR` to put it elsewhere), and write the dataset to `results/`. With the saved answers, a run from a clean clone took about 5 minutes. The first run, which called the models, took 22 minutes for the reading and cost **$2.06**. A ten-page Qwen trial added $0.05.

## The data

All of it is public, and none of it is committed.

- **Reports.** PacifiCorp lists every annual groundwater report for its five coal plants (Dave Johnston, Hunter, Huntington, Jim Bridger, Naughton) on one page per plant: 136 reports. 40 CFR 257.107 requires them to be posted. The sample is seven reports, chosen to cover scanned lab pages (Hunter and Huntington, 2018 and 2019) and born-digital ones (Dave Johnston 2022, Jim Bridger 2021, Naughton 2022). Each file's sha256 is logged.
- **Pages.** A page counts as *scanned* if one picture covers most of it. Some scans carry an OCR text layer full of misreads, so a text layer alone doesn't make a page born-digital. The demo reads every scanned candidate page (378) and a seeded 15 born-digital candidates per report (75). Both models agreed that 232 of the 453 are lab result pages; the rest are custody forms, QC summaries and cover letters.
- **Answer key.** Each report also has the consultant's results table: every well, date and constituent, typed from the same lab reports into a born-digital table. `pdfplumber` parses it exactly, giving 26,127 values in 1,556 samples. Blocks where a replaced well (`DJ-37` and `DJ-37R`) makes the well name ambiguous are dropped rather than guessed.
- **EIP's database isn't used.** It covers only the first year, its download needs a release form, and its terms bar commercial use.
- **Models.** Gemini 3.8 Flash (Google) and Mistral Small 2603 (Mistral, open weights) through OpenRouter, typed with Pydantic AI.
- **`adjudications.json`** (committed): the 17 fields where the answer key was in doubt, each checked on the page image, with the value seen there and a note.

## Results

From the run of `./run.sh` on 2026-11-06. Of the 232 lab pages, 188 matched a sample in the results table; the 44 that didn't are field duplicates and blanks, or wells dropped from the key. On those 188 pages, **1,541 constituent values** were scored.

| | Gemini alone | Mistral alone | The pair, review on disagreement |
|---|---|---|---|
| Wrong or missing values | 1 (0.06%) | 2 (0.13%) | **0 of 1,538 accepted** (95% interval 0% to 0.25%) |
| Scanned pages (1,025 values) | 1 missing | 1 wrong | 0 accepted wrong (0% to 0.37%) |
| Born-digital pages (516 values) | 0 | 1 wrong | 0 accepted wrong (0% to 0.74%) |
| Well names wrong (188 pages) | 4 | 5 | **3 accepted wrong** |

**Review rate.** 8 of 2,644 fields on lab pages went to review (0.3%). Counting the 2 pages that only one model called a lab page, 8 of 234 pages (3.4%) have something in review. Review caught the one value error that mattered: Mistral read calcium `496` as `4.96`. Gemini's own confidence, given the same review budget, caught none. It put 0.95 or higher on every value.

**What got through: well names.** On 3 of 188 pages, both models read the well `HLF-1O` (letter O) as `HLF-10` (zero), so every result on those pages sits under the wrong well. Disagreement can't catch an error both models make. A check against the report's own list of wells would, and it isn't built (see below).

**The answer key was wrong more often than the models.** Of the 17 fields checked on the page, 9 are values the results table rounds (the lab printed `0.341`, the table `0.34`). Two are fluoride results where the report carries two versions of the same sample's lab report (`2.77` on one page, `< 0.400` on another) and the table follows the other version. Three are the `HLF-10` lab pages, where the lab itself printed a zero; the other three are the misreads above.

**Boxes.** 18 values (0.8%) on 10 pages have a box taller than it is wide. On those pages Gemini returned `[y, x, y, x]`. The values are right; their boxes are flagged in `bbox_suspect`.

**Cost and time.** Model calls cost **$0.0045 per page read**, or **$0.0088 per lab result page** once the non-result pages are counted in. Gemini took 6.3 seconds a page and Mistral 13.2. Review time is an assumption, not a measurement: at 30 seconds a reviewed field and $40 an hour, review adds $0.069 per lab page, for **$0.078 all-in per lab page**.

**The whole job (an estimate).** The sample reports average 312 pages and 64 lab result pages each. Nationally, report years 2018 to 2025 come to about 3,500 reports (EIP's 443 a year) to 6,100 (EPA's 768 units). That is 1.1 to 1.9 million pages, of which 230,000 to 395,000 are lab result pages. At the measured cost, reading and reviewing all of them would cost **$18,000 to $31,000**, mostly in assumed review time.

## What didn't work, and what it doesn't show

- **Disagreement misses shared misreads.** The well-name error got through because both models made it. A check of each page's well against the wells named in the report, or the results table, is the obvious next rule.
- **A page check matters more than a field check.** Matching to the key needed a 3-day window, because the table sometimes gives the event date and the lab the day of sampling. It also had to treat O and 0 alike.
- **We switched off Qwen on one page's evidence.** A one-page test with an earlier schema returned no results from Qwen, so Mistral took its place. Read again with the frozen schema, Qwen got all ten trial pages right. It wasn't measured on the full set.
- **Mostly one lab and one consultant.** Most lab pages come from two labs (American West, Energy Laboratories), and every table from one consultant (WET), all at one utility. Other utilities' reports, older scans and handwritten pages will do worse. The table parser also needs work per consultant.
- **Most later lab pages aren't scans.** From 2020 on, PacifiCorp's lab pages are born-digital; what is scanned is mostly custody forms. A text-layer parser could read those pages for free if someone writes one per lab layout.
- **The checking was done by the agent that built this, not a person.** Each decision is in `adjudications.json` for anyone to re-check. Where one model matched the table, the table is taken as right.
- **Small sample.** Zero accepted errors in 1,538 values still allows up to 0.25% at 95% confidence. The national estimate scales seven reports' averages, and counting born-digital candidates slightly overstates the lab pages (61 of the 75 read were lab pages).
- **Reviewers are assumed perfect and their time is assumed.**

## Files

- `1_documents.py`, `2_extraction.py`, `3_results.py`: the demo, as three marimo notebooks
- `answers/`: every model answer, with its cost and time, so the scores can be rerun for free
- `adjudications.json`: every field checked on the page image
- `results/`: `groundwater_results.csv` and `.parquet` (2,180 rows), `review_queue.csv`, `accuracy.csv`, `results.json` and [`DATA_DICTIONARY.md`](results/DATA_DICTIONARY.md)
- `screenshots/`: every wrong value accepted without review
- `run.sh`, `pyproject.toml`, `uv.lock`: the one command and its pinned environment

What we looked at first: vendor tools ship the same steps (Reducto, Extend, Azure Document Intelligence, Textract with A2I; see the reading research in #58), but none publishes its error rate on public records. The pipeline is the 990-EZ spike's, with `pdfplumber` added for the answer-key tables.
