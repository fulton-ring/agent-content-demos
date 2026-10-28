# Does Reducto beat an open VLM pipeline on the documents it's built for?

#136 (`messy-document-parsing/`) found that Reducto made the same kind of believable wrong values as Gemini 3.8 Flash reading page images, and more of them, on 1940s federal records and synthetic tables. Reducto aims at financial tables, forms and scans, so this spike tests it on three corpora closer to that, each with an answer key nobody typed for us:

1. **FinTabNet**: 102 tables from S&P 500 annual reports, stratified by size and by merged cells, with every cell keyed.
2. **Scanned IRS 990-EZ returns**: 100 paper returns, typed and handwritten, keyed by the IRS Statistics of Income (SOI) extract.
3. **#136's seven real documents and 39 broken tables**, run again unchanged as the hard tail.

The fourth corpus in the issue, SEC filings keyed by XBRL, is split off as #150.

**Read the three notebooks**, each top to bottom (`uv run marimo edit 1_fintabnet.py`, or read them as plain Python):

1. [`1_fintabnet.py`](1_fintabnet.py): the sample, the six pipelines, Deep Extract and Argon, Reducto's cache, and where Reducto loses.
2. [`2_scanned_990s.py`](2_scanned_990s.py): the returns, checking the answer key, and the scores by line.
3. [`3_hard_tail.py`](3_hard_tail.py): #136 run twice, plus fresh Reducto reads, Deep Extract and Argon.

[`pipelines.py`](pipelines.py) is #136's, copied, with the changes listed at its top: Reducto Deep Extract, a per-task table prompt, and `fresh_copies` (see below). [`model_call.py`](model_call.py) is #136's, unchanged.

## Run it

```
./run.sh
```

You need [uv](https://docs.astral.sh/uv/), `tesseract`, `OPENROUTER_API_KEY` and `REDUCTO_API_KEY`. Everything is downloaded at run time: FinTabNet's first test file from Hugging Face (142 MB, pinned and hash-checked), the SOI extract, and the 990 scans through ProPublica and the IRS. Notebook 3 copies `messy-document-parsing/` into `output/` and runs its `run.sh` twice, so #136's own documents, keys and scorer are used without changing that folder. Answers are saved in `output/` (set `BIGGER_OUTPUT_DIR` to change that) and reused on a re-run.

From nothing, a run takes about 3 to 4 hours on 4 cores, mostly Docling and #136's two runs. All of this spike's calls cost **$11.41 on OpenRouter** and **$20.39 on Reducto at list price**. $5.61 of the Reducto figure is answers served from Reducto's cache, which may not be billed. Reducto is costed at its list price, $10 (Parse), $20 (Extract) and $40 (Deep Extract) per 1,000 pages, since its API reports pages, not dollars.

## Pipelines

#136's six: Docling alone; Gemini 3.8 Flash given the PDF; Gemini given each page image; Docling's Markdown next to the image; Reducto Parse (r-1); and Reducto Extract, with the same schema and prompt as Gemini. Added on a 50-document subset drawn with a seed before any run (22 FinTabNet tables, 20 returns and #136's 8 real-document tasks): **Reducto Deep Extract**, Extract in an agentic loop that checks its own answer, and **Gemini 4 Argon** given the page image. Everything runs twice, except Docling, which is deterministic. Cells and fields are **right**, **wrong** (a value that isn't the key's, so it looks fine to a reader) or **missing**, with #136's scorer. An **empty answer** is one with no values and no error: the silent failure.

## Reducto answers a file it has seen from a cache

Our first second run of Reducto came back identical on all 102 FinTabNet tables, under new job IDs, in about 0.2 seconds a table. Sending the 22 subset tables again with one comment line added after the end of each PDF (the same pages, a different file hash) changed 16 of the 22 answers, and the cells right went from 488 to 462. Reducto's docs don't mention this. In #136's two runs here, 57 of 94 Reducto answers in run 2 were cache hits. So every second Reducto read in this spike is on such a copy. Reducto run twice on the same file measures its cache, not its reading. #136's own run-to-run Reducto comparison was partly this.

## Results

**FinTabNet, 102 tables, 3,838 keyed cells** ([`results/fintabnet.md`](results/fintabnet.md)):

| Pipeline | Cells right, run 1 / run 2 | Wrong | Empty answers | Cost per page | Seconds per page |
|---|---|---|---|---|---|
| Gemini, page by page | 99.0% / 99.0% | 18 / 16 | 0 | $0.0031 | 8.5 |
| Gemini, whole PDF | 98.8% / 97.7% | 25 / 35 | 0 | $0.0044 | 12.2 |
| Docling, then Gemini | 96.1% / 99.2% | 22 / 16 | 0 | $0.0046 | 15.2 |
| Reducto Extract | 81.9% (once) | 128 | 3 | $0.0200 | 6.5 |
| Reducto Parse | 66.1% (once) | 425 | 6 | $0.0100 | 1.2 |
| Docling alone | 11.7% | 271 | 90 | $0 | 5.2 |

On the 22-table subset, with Reducto's second read on new bytes:

| Pipeline | Cells right, run 1 / run 2 | Wrong | Cost per page |
|---|---|---|---|
| Gemini 4 Argon, page by page | 97.9% / 97.9% | 10 / 10 | $0.0060 |
| Gemini Flash, page by page | 96.7% / 97.3% | 13 / 11 | $0.0027 |
| Reducto Deep Extract | 93.8% / 90.3% | 29 / 30 | $0.0400 |
| Reducto Extract | 74.3% / 70.3% | 39 / 79 | $0.0200 |

- **Gemini reading the image wins in every group**: 98.8% to 99.7% of cells in each size and merged-cell group, against 72.8% to 97.5% for Reducto Extract. Reducto comes closest on small tables without merged cells (97.5%).
- **Reducto Extract's losses are mostly the table's shape, not its digits.** Of 102 answers, 82 had the right shape. 3 were empty, 4 put the whole table in one row (one 43-row income statement came back as a single row of 175 cells), 5 lost over a fifth of the rows, and 8 had rows of the wrong width. Gemini returned the right shape all 102 times in both modes. Our schema is a plain list of rows; Reducto might do better with a schema of named fields, but it was given what Gemini was given.
- **Deep Extract fixes most of that, at twice Extract's price**, but still trails Flash, at 13 times Flash's cost a page.

**Scanned 990-EZ, 100 returns, 2,000 fields** ([`results/scanned_990s.md`](results/scanned_990s.md)):

| Pipeline | Fields right, run 1 / run 2 | Wrong | Missing | Cost per page |
|---|---|---|---|---|
| Gemini, page by page | 99.8% / 99.9% | 5 / 3 | 0 / 0 | $0.0021 |
| Docling, then Gemini | 98.8% / 99.9% | 18 / 2 | 6 / 0 | $0.0039 |
| Gemini, whole PDF | 99.0% / 99.0% | 18 / 19 | 2 / 2 | $0.0017 |
| Reducto Extract | 99.0% / 98.4% | 20 / 29 | 0 / 4 | $0.0200 |

On the 20-return subset, Deep Extract got 100% and 99.8%, as did Argon. Extract got 99.8% and 95.8%, the drop coming from 13 wrong values in its second read. The key is #58's: SOI, with the fields where SOI differs from the scan checked on the scan (`adjudications.json`). This run turned up 20 more fields where two or more reads agreed against the key. All were checked on the scan. In every one the key was right: the reads had taken a struck-through number, swapped lines 1 and 9, misread a handwritten 5, or put a "not including $" amount on line 6b. One more file turned out to be Schedule A, not the 990-EZ, and was replaced by the next return. All of these decisions were made by the agent that built this, not by a person.

**#136's documents** ([`results/hard_tail.md`](results/hard_tail.md)), run 1 / run 2:

- **WSP 1050 still fails silently in Reducto.** Parse and Extract read 0% of the page in both runs, the fresh second read included. **Deep Extract read 92% and 93%**, the one place in this spike where it beat Extract by a long way. Gemini page by page read 100% in both.
- **Reducto Extract varies on the real documents.** The USGS well table came out at 56% and 54% (100% in #136), the census at 84% and 83%, and the microfilm at 76% and 99%. The handwritten 990-EZ was 68% and 64%, with lines put one off, as #136 found. Deep Extract repeated the 990-EZ result: 68% and 64%. Argon got the 990-EZ 100% both times.
- **On the 39 broken tables Reducto Extract got 97.9%** (run 1 only; run 2 was its cache), against 97.0% to 99.0% for Gemini given the PDF or Docling's Markdown. Gemini page by page got 93.9% to 94.5%, dragged down by the wide table cut in half, as in #136.

## Where Reducto wins and loses

- **Loses:** financial tables (FinTabNet), where it's 17 points behind on all 102 tables and returns tables of the wrong shape a fifth of the time. Typed and handwritten forms, where it gives 4 to 10 times as many wrong values as Gemini page by page. #136's real documents.
- **Wins or ties:** #136's synthetic broken tables (97.9% against 97.0% to 99.0%). Deep Extract on the subsets ties Gemini on 990s and recovers WSP 1050, which plain Reducto calls blank.
- **Silent failures:** Reducto Extract returned an empty table for 3 of 102 FinTabNet tables, and Parse for 6. Both read WSP 1050 as blank in every run. Gemini had no empty answers on FinTabNet or the 990s.

The issue expected Reducto to be close on clean financial tables, with any edge in Deep Extract at several times the cost. It wasn't close. The edge from Deep Extract is real but only brings it up to about Gemini Flash, at 13 to 19 times Flash's cost a page. Gemini Argon, at about twice Flash's cost, was as good as or better than Deep Extract on all three subsets.

## What it doesn't show

- **SEC filings** are #150.
- **FinTabNet ships table crops, not pages**, at low resolution (the screenshot is the full image). So this tests reading a table, not finding one, and low resolution may hurt Reducto more than Gemini.
- **One schema for every pipeline.** Reducto Extract got Gemini's schema (rows as lists of cells) and prompt. A schema written for Reducto, or its agentic table mode in Parse, wasn't tried.
- **Reducto's second read on all 102 FinTabNet tables** wasn't bought: the first attempt was its cache, and the budget didn't cover another. The 22-table subset has it. The same holds for Reducto on #136's 39 broken tables.
- **Run-to-run for Reducto rests on two reads**, so treat its spread as a lower bound.
- **Keys were checked by the agent, not a person**, as in #58 and #136.
- **Size.** About 1,540 lines of Python, over the 1,000-line target: about 1,020 in the three notebooks, and 520 in `pipelines.py` and `model_call.py`, copied from #136 rather than imported so that folder stays unchanged.

## Files

- `1_fintabnet.py`, `2_scanned_990s.py`, `3_hard_tail.py`: the notebooks. `run.sh` runs them in order.
- `pipelines.py`, `model_call.py`: shared with all three, copied from #136.
- `adjudications.json`: #58's checks of the 990 key, plus this spike's, marked `#141`.
- `results/`: each notebook's tables, written by the run.
- `screenshots/`: the FinTabNet table Reducto Extract returned as one row, and the struck-through 733 on a 990-EZ that Reducto Extract read as line 6d in both runs, and every Gemini pipeline left blank.

Before building this we looked for Reducto's own benchmark figures on FinTabNet and 990s, and found none. The pipelines are #136's, so the comparison changes only the documents.
