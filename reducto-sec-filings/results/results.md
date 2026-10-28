# Results

Written by `sec_filings.py`; see the notebook for how each number is made.

## Corpus

**1 filings, 3 statement pages, 187 key values.** 0 XBRL values (0.0%) weren't printed on the statement pages and are left out. 10 of the 200 numbers printed on those pages (5.0%) match no value on the filing's statement `R` pages.

| Filer | Form | Period | Pages | Key values | XBRL not printed | Printed not in XBRL | Subset |
|---|---|---|---|---|---|---|---|
| Apple | 10-K | 2012-09-29 | 3 | 187 | 0 | 10 of 200 | yes |

## All filings

| Pipeline | Filings | Right, run 1 | Right, run 2 | Wrong (1 / 2) | Missing (1 / 2) | Statements flipped | Silent failures (1 / 2) | Errors (1 / 2) | $ per page | Seconds per page |
|---|---|---|---|---|---|---|---|---|---|---|
| Gemini, whole PDF | 1 | 100.0% | 100.0% | 0.0% / 0.0% | 0.0% / 0.0% | 0 of 3 (0 values) | 0 / 0 of 3 | 0 / 0 | 0.0038 | 9.8 |
| Gemini, page by page | 1 | 100.0% | 100.0% | 0.0% / 0.0% | 0.0% / 0.0% | 0 of 3 (0 values) | 0 / 0 of 3 | 0 / 0 | 0.0055 | 8.9 |
| Docling, then Gemini | 1 | 100.0% | 100.0% | 0.0% / 0.0% | 0.0% / 0.0% | 0 of 3 (0 values) | 0 / 0 of 3 | 0 / 0 | 0.0050 | 24.3 |
| Reducto Extract | 1 | 100.0% | 100.0% | 0.0% / 0.0% | 0.0% / 0.0% | 0 of 3 (0 values) | 0 / 0 of 3 | 0 / 0 | 0.0200 | 9.7 |

## Subset

| Pipeline | Filings | Right, run 1 | Right, run 2 | Wrong (1 / 2) | Missing (1 / 2) | Statements flipped | Silent failures (1 / 2) | Errors (1 / 2) | $ per page | Seconds per page |
|---|---|---|---|---|---|---|---|---|---|---|
| Gemini, whole PDF | 1 | 100.0% | 100.0% | 0.0% / 0.0% | 0.0% / 0.0% | 0 of 3 (0 values) | 0 / 0 of 3 | 0 / 0 | 0.0038 | 9.8 |
| Gemini, page by page | 1 | 100.0% | 100.0% | 0.0% / 0.0% | 0.0% / 0.0% | 0 of 3 (0 values) | 0 / 0 of 3 | 0 / 0 | 0.0055 | 8.9 |
| Docling, then Gemini | 1 | 100.0% | 100.0% | 0.0% / 0.0% | 0.0% / 0.0% | 0 of 3 (0 values) | 0 / 0 of 3 | 0 / 0 | 0.0050 | 24.3 |
| Reducto Extract | 1 | 100.0% | 100.0% | 0.0% / 0.0% | 0.0% / 0.0% | 0 of 3 (0 values) | 0 / 0 of 3 | 0 / 0 | 0.0200 | 9.7 |
| Reducto Deep Extract | 1 | 100.0% | 100.0% | 0.0% / 0.0% | 0.0% / 0.0% | 0 of 3 (0 values) | 0 / 0 of 3 | 0 / 0 | 0.0400 | 16.1 |
| Gemini 4 Argon, whole PDF | 1 | 100.0% | 100.0% | 0.0% / 0.0% | 0.0% / 0.0% | 0 of 3 (0 values) | 0 / 0 of 3 | 0 / 0 | 0.0128 | 11.6 |

## By statement type

All filings:

| Statement | Gemini, whole PDF: right / wrong | Reducto Extract: right / wrong |
|---|---|---|
| balance | 100.0% / 0.0% | 100.0% / 0.0% |
| income | 100.0% / 0.0% | 100.0% / 0.0% |
| cash flow | 100.0% / 0.0% | 100.0% / 0.0% |

Subset:

| Statement | Gemini, whole PDF: right / wrong | Reducto Extract: right / wrong | Gemini 4 Argon, whole PDF: right / wrong | Reducto Deep Extract: right / wrong |
|---|---|---|---|---|
| balance | 100.0% / 0.0% | 100.0% / 0.0% | 100.0% / 0.0% | 100.0% / 0.0% |
| income | 100.0% / 0.0% | 100.0% / 0.0% | 100.0% / 0.0% | 100.0% / 0.0% |
| cash flow | 100.0% / 0.0% | 100.0% / 0.0% | 100.0% / 0.0% | 100.0% / 0.0% |

## Per filing

| Filing | Gemini, whole PDF | Gemini, page by page | Docling, then Gemini | Reducto Extract | Reducto Deep Extract | Gemini 4 Argon, whole PDF |
|---|---|---|---|---|---|---|
| Apple 10-K 2012-09-29 | 100% / 100% | 100% / 100% | 100% / 100% | 100% / 100% | 100% / 100% | 100% / 100% |

## Wrong values

- **Gemini, whole PDF:** 0 wrong. 
- **Gemini, page by page:** 0 wrong. 
- **Docling, then Gemini:** 0 wrong. 
- **Reducto Extract:** 0 wrong. 
- **Reducto Deep Extract:** 0 wrong. 
- **Gemini 4 Argon, whole PDF:** 0 wrong. 
