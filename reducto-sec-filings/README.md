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
`Fulton Ring info@fultonring.com` if that isn't set, and are kept under 10 a second. A full run takes about
RUNTIME minutes and costs about $COST on OpenRouter and $5.36 on Reducto at list price. Answers are saved under
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

RESULTS

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
