# Results

Written by `sec_filings.py`; see the notebook for how each number is made.

## Corpus

**24 filings, 78 statement pages, 5,289 key values.** 60 XBRL values (1.1%) weren't printed on the statement pages and are left out. 446 of the 6,513 numbers printed on those pages (6.8%) match no value on the filing's statement `R` pages.

| Filer | Form | Period | Pages | Key values | XBRL not printed | Printed not in XBRL | Subset |
|---|---|---|---|---|---|---|---|
| Apple | 10-K | 2012-09-29 | 3 | 187 | 0 | 10 of 200 | yes |
| Microsoft | 10-Q | 2018-12-31 | 3 | 278 | 0 | 12 of 292 |  |
| Fifth Third | 10-K | 2015-12-31 | 3 | 326 | 0 | 4 of 379 |  |
| Travelers | 10-K | 2014-12-31 | 3 | 235 | 0 | 4 of 263 | yes |
| American Water | 10-K | 2012-12-31 | 3 | 310 | 0 | 3 of 360 |  |
| Walmart | 10-Q | 2017-04-30 | 3 | 195 | 0 | 2 of 193 |  |
| Chevron | 10-Q | 2018-03-31 | 3 | 184 | 2 | 13 of 232 | yes |
| Merck | 10-K | 2018-12-31 | 3 | 219 | 2 | 11 of 251 |  |
| Simon Property | 10-K | 2016-12-31 | 3 | 260 | 22 | 4 of 287 |  |
| Caterpillar | 10-Q | 2012-03-31 | 6 | 200 | 0 | 13 of 390 | yes |
| Coca-Cola | 10-K | 2017-12-31 | 3 | 262 | 0 | 4 of 264 |  |
| Comcast | 10-Q | 2020-03-31 | 3 | 168 | 0 | 4 of 182 |  |
| Cal-Maine Foods | 10-Q | 2012-12-01 | 3 | 175 | 0 | 30 of 204 | yes |
| JPMorgan Chase | 10-Q | 2014-03-31 | 4 | 225 | 14 | 47 of 291 |  |
| UnitedHealth | 10-Q | 2022-03-31 | 3 | 168 | 0 | 4 of 181 |  |
| Intel | 10-K | 2015-12-26 | 4 | 256 | 0 | 16 of 361 | yes |
| Aflac | 10-Q | 2021-03-31 | 3 | 190 | 4 | 4 of 218 |  |
| Costco | 10-K | 2020-08-30 | 3 | 207 | 0 | 12 of 219 |  |
| ConocoPhillips | 10-K | 2021-12-31 | 3 | 249 | 0 | 10 of 264 | yes |
| Johnson & Johnson | 10-Q | 2023-04-02 | 3 | 180 | 0 | 11 of 234 |  |
| Realty Income | 10-Q | 2024-03-31 | 3 | 200 | 1 | 19 of 217 |  |
| Deere | 10-K | 2021-10-31 | 3 | 239 | 6 | 167 of 499 | yes |
| Nike | 10-Q | 2015-11-30 | 3 | 167 | 9 | 25 of 243 |  |
| Netflix | 10-K | 2014-12-31 | 4 | 209 | 0 | 17 of 289 |  |

## All filings

| Pipeline | Filings | Right, run 1 | Right, run 2 | Wrong (1 / 2) | Missing (1 / 2) | Statements flipped | Silent failures (1 / 2) | Errors (1 / 2) | $ per page | Seconds per page |
|---|---|---|---|---|---|---|---|---|---|---|
| Gemini, whole PDF | 24 | 96.9% | 96.9% | 0.0% / 0.0% | 3.1% / 3.1% | 1 of 72 (1 values) | 1 / 1 of 72 | 0 / 0 | 0.0042 | 11.3 |
| Gemini, page by page | 24 | 98.9% | 99.0% | 0.0% / 0.0% | 1.1% / 1.0% | 1 of 72 (4 values) | 0 / 0 of 72 | 0 / 0 | 0.0067 | 11.8 |
| Docling, then Gemini | 24 | 99.0% | 99.0% | 0.0% / 0.0% | 1.0% / 1.0% | 2 of 72 (6 values) | 0 / 0 of 72 | 0 / 0 | 0.0057 | 23.9 |
| Reducto Extract | 24 | 98.9% | 98.9% | 0.0% / 0.0% | 1.1% / 1.1% | 0 of 72 (0 values) | 0 / 0 of 72 | 0 / 0 | 0.0200 | 3.2 |

## Subset

| Pipeline | Filings | Right, run 1 | Right, run 2 | Wrong (1 / 2) | Missing (1 / 2) | Statements flipped | Silent failures (1 / 2) | Errors (1 / 2) | $ per page | Seconds per page |
|---|---|---|---|---|---|---|---|---|---|---|
| Gemini, whole PDF | 8 | 93.4% | 93.4% | 0.0% / 0.0% | 6.6% / 6.6% | 0 of 24 (0 values) | 1 / 1 of 24 | 0 / 0 | 0.0036 | 9.9 |
| Gemini, page by page | 8 | 99.6% | 99.6% | 0.0% / 0.0% | 0.4% / 0.4% | 0 of 24 (0 values) | 0 / 0 of 24 | 0 / 0 | 0.0064 | 11.6 |
| Docling, then Gemini | 8 | 99.6% | 99.6% | 0.0% / 0.0% | 0.4% / 0.4% | 0 of 24 (0 values) | 0 / 0 of 24 | 0 / 0 | 0.0052 | 23.0 |
| Reducto Extract | 8 | 99.4% | 99.4% | 0.0% / 0.0% | 0.6% / 0.6% | 0 of 24 (0 values) | 0 / 0 of 24 | 0 / 0 | 0.0200 | 2.7 |
| Reducto Deep Extract | 8 | 99.6% | 99.6% | 0.0% / 0.0% | 0.4% / 0.4% | 0 of 24 (0 values) | 0 / 0 of 24 | 0 / 0 | 0.0400 | 8.0 |
| Gemini 4 Argon, whole PDF | 8 | 99.5% | 93.4% | 0.0% / 0.0% | 0.5% / 6.6% | 1 of 24 (106 values) | 0 / 1 of 24 | 0 / 0 | 0.0114 | 11.4 |

## By statement type

All filings:

| Statement | Docling, then Gemini: right / wrong | Reducto Extract: right / wrong |
|---|---|---|
| balance | 98.1% / 0.0% | 98.0% / 0.0% |
| income | 98.7% / 0.0% | 98.3% / 0.0% |
| cash flow | 99.9% / 0.0% | 99.9% / 0.0% |

Subset:

| Statement | Docling, then Gemini: right / wrong | Reducto Extract: right / wrong | Gemini 4 Argon, whole PDF: right / wrong | Reducto Deep Extract: right / wrong |
|---|---|---|---|---|
| balance | 98.9% / 0.0% | 98.9% / 0.0% | 98.9% / 0.0% | 98.9% / 0.0% |
| income | 99.8% / 0.0% | 98.9% / 0.0% | 99.8% / 0.0% | 99.8% / 0.0% |
| cash flow | 100.0% / 0.0% | 100.0% / 0.0% | 92.5% / 0.0% | 100.0% / 0.0% |

## Per filing

| Filing | Gemini, whole PDF | Gemini, page by page | Docling, then Gemini | Reducto Extract | Reducto Deep Extract | Gemini 4 Argon, whole PDF |
|---|---|---|---|---|---|---|
| Apple 10-K 2012-09-29 | 100% / 100% | 100% / 100% | 100% / 100% | 100% / 100% | 100% / 100% | 100% / 100% |
| Microsoft 10-Q 2018-12-31 | 100% / 100% | 100% / 100% | 100% / 100% | 100% / 100% |  |  |
| Fifth Third 10-K 2015-12-31 | 100% / 100% | 100% / 100% | 100% / 100% | 100% / 100% |  |  |
| Travelers 10-K 2014-12-31 | 100% / 100% | 100% / 100% | 100% / 100% | 100% / 100% | 100% / 100% | 100% / 100% |
| American Water 10-K 2012-12-31 | 100% / 100% | 100% / 100% | 100% / 100% | 100% / 100% |  |  |
| Walmart 10-Q 2017-04-30 | 98% / 98% | 98% / 98% | 98% / 98% | 98% / 98% |  |  |
| Chevron 10-Q 2018-03-31 | 99% / 99% | 99% / 99% | 99% / 99% | 99% / 99% | 99% / 99% | 99% / 99% |
| Merck 10-K 2018-12-31 | 99% / 99% | 99% / 99% | 99% / 99% | 99% / 99% |  |  |
| Simon Property 10-K 2016-12-31 | 95% / 95% | 95% / 95% | 95% / 95% | 95% / 95% |  |  |
| Caterpillar 10-Q 2012-03-31 | 100% / 100% | 100% / 100% | 100% / 100% | 100% / 100% | 100% / 100% | 100% / 100% |
| Coca-Cola 10-K 2017-12-31 | 100% / 100% | 100% / 100% | 100% / 100% | 100% / 100% |  |  |
| Comcast 10-Q 2020-03-31 | 98% / 98% | 98% / 98% | 98% / 98% | 98% / 98% |  |  |
| Cal-Maine Foods 10-Q 2012-12-01 | 98% / 98% | 98% / 98% | 98% / 98% | 95% / 95% | 98% / 98% | 98% / 98% |
| JPMorgan Chase 10-Q 2014-03-31 | 95% / 95% | 95% / 95% | 95% / 95% | 95% / 95% |  |  |
| UnitedHealth 10-Q 2022-03-31 | 100% / 100% | 100% / 100% | 100% / 100% | 100% / 100% |  |  |
| Intel 10-K 2015-12-26 | 100% / 100% | 100% / 100% | 100% / 100% | 100% / 100% | 100% / 100% | 100% / 100% |
| Aflac 10-Q 2021-03-31 | 98% / 98% | 98% / 98% | 98% / 98% | 98% / 98% |  |  |
| Costco 10-K 2020-08-30 | 100% / 100% | 100% / 100% | 100% / 100% | 100% / 100% |  |  |
| ConocoPhillips 10-K 2021-12-31 | 100% / 100% | 100% / 100% | 100% / 100% | 100% / 100% | 100% / 100% | 100% / 100% |
| Johnson & Johnson 10-Q 2023-04-02 | 97% / 97% | 97% / 99% | 97% / 99% | 97% / 97% |  |  |
| Realty Income 10-Q 2024-03-31 | 99% / 99% | 99% / 99% | 99% / 99% | 99% / 99% |  |  |
| Deere 10-K 2021-10-31 | 55% / 55% | 100% / 100% | 100% / 100% | 100% / 100% | 100% / 100% | 100% / 55% |
| Nike 10-Q 2015-11-30 | 98% / 98% | 98% / 98% | 99% / 98% | 98% / 98% |  |  |
| Netflix 10-K 2014-12-31 | 100% / 100% | 100% / 100% | 100% / 100% | 100% / 100% |  |  |

## Wrong values

- **Gemini, whole PDF:** 0 wrong. 
- **Gemini, page by page:** 0 wrong. 
- **Docling, then Gemini:** 0 wrong. 
- **Reducto Extract:** 0 wrong. 
- **Reducto Deep Extract:** 0 wrong. 
- **Gemini 4 Argon, whole PDF:** 0 wrong. 
