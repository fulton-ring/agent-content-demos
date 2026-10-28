# Reducto against open pipelines on SEC 10-K and 10-Q financial statements

Issue #150, split from #141. #136 (`messy-document-parsing/`) found that Reducto made as many believable wrong
values as Gemini did on old federal records, at 2 to 200 times the cost per page. Those records weren't what
Reducto is built for. This spike runs both on documents that are: the balance sheet, income statement and
cash-flow statement in 24 public companies' 10-Ks and 10-Qs. The answer key is the filers' own XBRL.

Everything is in one marimo notebook, [`sec_filings.py`](sec_filings.py). It reads top to bottom: the filings, the
key, finding the statements in print, the pipelines, scoring and results. Every table below comes from
[`results/results.md`](results/results.md), which the notebook writes.

## Run it

```
export OPENROUTER_API_KEY=...   # Gemini, through OpenRouter
export REDUCTO_API_KEY=...      # Reducto Extract and Deep Extract
./run.sh
```

`run.sh` needs [uv](https://docs.astral.sh/uv/). It installs the pinned environment and Playwright's Chromium (if
it isn't already there), then runs the notebook as a script. To read the notebook interactively, run
`uv run marimo edit sec_filings.py`. sec.gov requests send the User-Agent in `SEC_USER_AGENT`, or
`Fulton Ring info@fultonring.com` if that isn't set, and are kept under 10 a second. A full run took 27
minutes and cost $3.23 on OpenRouter and $5.36 on Reducto at list price. Answers are saved under
`output/`, so a second run rescores without paying again.

## Where the data comes from

- **Filings.** A list of 30 filers and 3 reserves, fixed and committed before any full run. It spans tech,
  banks, insurers, a utility, retail, energy, pharma, REITs, industrials and airlines, with filings from 2011 to
  2025. Each filing is downloaded from EDGAR at run time. The main HTML document is printed to PDF with headless
  Chromium, and only the statement pages (3 to 6 a filing) go to the pipelines.
- **The key.** EDGAR's `R` pages render each filing's XBRL one statement at a time. The key is each statement's
  line items and values, matched to the printed page in the form they're printed in (as filed, or in thousands or
  millions). Nothing is typed by hand.
- **Budget cut.** Two runs on 30 filings would have cost $6.72 at Reducto's list price, over the $6 budget. The
  spike uses the first 24 usable filings in list order. Eli Lilly's 2011 10-K has only the older XML viewer
  pages, and Sturm Ruger's printed text layer splits every character onto its own line. Both were replaced by
  the reserves, as the rule written before the run says.

## Results

From the clean-checkout run. Full tables, per filing, are in [`results/results.md`](results/results.md) ([screenshot](screenshots/results.png) of the subset table in the notebook).

**The answer: on clean SEC statements, Reducto doesn't beat the open pipelines. All of them read about 99% of
values right and none of them returned a single wrong number.** Reducto Extract costs 3 to 5 times as much per
page, and Deep Extract 6 to 10 times as much, for no gain in accuracy. Reducto was the most repeatable, and it
was the only reader that never returned an empty statement. The open pipelines' failures were all silent ones on
one hard page.

**Corpus:** 24 filings, 78 statement pages and 5,289 key values. 60 XBRL values (1.1%) weren't printed on the
statement pages and are left out. 446 of the 6,513 numbers printed on those pages (6.8%) match no XBRL value.
Most of these are page and note numbers, dates and figures inside labels.

All 24 filings, two runs each:

| Pipeline | Right, run 1 / run 2 | Wrong | Missing, run 1 / run 2 | Statements that changed between runs | Silent failures | $ per page | Seconds per page |
|---|---|---|---|---|---|---|---|
| Gemini 3.8 Flash, whole PDF | 96.9% / 96.9% | 0 | 3.1% / 3.1% | 1 of 72 | 1 statement, both runs | 0.0042 | 11.3 |
| Gemini, page by page | 98.9% / 99.0% | 0 | 1.1% / 1.0% | 1 of 72 | 0 | 0.0067 | 11.8 |
| Docling, then Gemini | 99.0% / 99.0% | 0 | 1.0% / 1.0% | 2 of 72 | 0 | 0.0057 | 23.9 |
| Reducto Extract | 98.9% / 98.9% | 0 | 1.1% / 1.1% | 0 of 72 | 0 | 0.0200 | 3.2 |

The subset of 8 filings (every third), where the stronger readers ran too:

| Pipeline | Right, run 1 / run 2 | Wrong | Silent failures | $ per page | Seconds per page |
|---|---|---|---|---|---|
| Gemini, page by page | 99.6% / 99.6% | 0 | 0 | 0.0064 | 11.6 |
| Reducto Extract | 99.4% / 99.4% | 0 | 0 | 0.0200 | 2.7 |
| Reducto Deep Extract | 99.6% / 99.6% | 0 | 0 | 0.0400 | 8.0 |
| Gemini 4 Argon, whole PDF | 99.5% / 93.4% | 0 | 1 statement in run 2 | 0.0114 | 11.4 |

**By statement type** (both runs pooled, all filings), the best open pipeline (Docling, then Gemini) against
Reducto Extract: balance sheet 98.1% against 98.0%, income statement 98.7% against 98.3%, and cash flow 99.9%
against 99.9%. Reducto doesn't win on any statement type. It loses by a hair on income statements, because it
dropped four Cal-Maine Foods lines in both runs.

**What failed:**
- **Every silent failure came from one page.** For Deere, the cash-flow page that page-finding chose is the
  supplemental consolidating statement: 12 columns for Equipment Operations, Financial Services, Eliminations
  and Consolidated ([screenshot](screenshots/deere-cash-flow-page.png)). Its consolidated columns hold the key's
  values, so the key is right, but it's the hardest page in the corpus. Gemini Flash reading the whole PDF
  returned the cash-flow statement with no rows in both runs, and so did Gemini 4 Argon in its second run. No
  error was raised; the balance sheet and income statement came back fine
  ([sample](results/samples/gemini-whole-pdf-deere-10-k-silent-failure.json)). Every page-at-a-time pipeline,
  and both Reducto modes, read all 12 columns
  ([sample](results/samples/reducto-extract-deere-10-k.json)). That's 1 statement in 72 for Flash, and 1 in 24
  for Argon. A pipeline that checks for an empty statement would catch it.
- **About 0.7% of values are missed by every pipeline alike.** These are lines that print a dash for zero, a
  few lines whose amounts sit inside the label, and the VIE lines at the foot of JPMorgan's balance sheet. They
  are the same for every reader, so they don't change the comparison.
- **The key took three fixes after the first scoring.** The fixes were for
  Simon Property, a combined filing whose `R` page repeats every line; Deere's segment columns, where column
  alignment looked at too few columns; and comprehensive-income and percent-of-sales lines that the prompt had
  told pipelines to skip. The first scoring showed the same ~70 "wrong" values for every pipeline, which pointed
  at the key, not the readers. The fixes change only the key and the scorer, the same for every pipeline. The
  pipelines' answers weren't re-run; the published numbers rescore the same saved answers.

Compared with #136, these statements are easy: a clean text layer, no handwriting, a fixed layout. On them the
readers converge, and the remaining differences are about cost, speed and the rare empty answer.

## What it doesn't show

- **Clean, born-digital statements only.** Every page here is HTML printed to PDF, with a perfect text layer.
  Scans, the filer's own typeset PDFs and the notes tables aren't tested. #141 covers scans and FinTabNet.
- **Sign isn't scored.** XBRL and print often disagree on sign (for example, "Less: cost of sales" is printed
  positive), so values are compared as absolute numbers. A pipeline that drops a minus sign isn't penalised.
- **The key is as good as the match to print.** XBRL values that aren't printed on the statement pages are left
  out (counted in the corpus table). Printed numbers that match no XBRL value are counted but not scored. Most
  of them are page and note numbers, dates and figures inside labels.
- **One prompt, one schema.** Every pipeline gets the same prompt and schema. Reducto might do better with its
  own schema tuning or with Parse, which wasn't run because the budget went to Deep Extract.
- **24 filings, 8 in the subset.** With 8 filings, the Deep Extract and Argon comparison is directional.
- **"Wrong" is a floor.** As in #136, a key line is matched to an extracted row by its values or its label. A row
  whose numbers are all wrong and whose label differs from the XBRL label is scored missing, not wrong. Checking
  by hand, 35 to 39 missing values per pipeline appear somewhere in that pipeline's answer, nearly all of them the
  same lines for every pipeline (zero lines, Simon's and JPMorgan's footers). So at most about 0.7% of values
  could be hidden wrong values, and they wouldn't separate the pipelines.
