# FinTabNet, 102 tables

| Pipeline | Right, run 1 | Right, run 2 | Wrong | Missing | Empty answers | Errors | Cost per page | Seconds per page |
|---|---|---|---|---|---|---|---|---|
| Docling alone | 11.7% | (once) | 271 | 3022 | 90 | 0 | $0.0000 | 5.2 |
| Gemini, whole PDF | 98.8% | 97.7% | 25 / 35 | 18 / 49 | 0 / 0 | 0 / 0 | $0.0044 | 12.2 |
| Gemini, page by page | 99.0% | 99.0% | 18 / 16 | 18 / 21 | 0 / 0 | 0 / 0 | $0.0031 | 8.5 |
| Docling, then Gemini | 96.1% | 99.2% | 22 / 16 | 123 / 12 | 0 / 0 | 0 / 0 | $0.0046 | 15.2 |
| Reducto Parse | 66.1% | (once) | 425 | 838 | 6 | 0 | $0.0100 | 1.2 |
| Reducto Extract | 81.9% | (once) | 128 | 548 | 3 | 0 | $0.0200 | 6.5 |

## 22-table subset

| Pipeline | Right, run 1 | Right, run 2 | Wrong | Missing | Empty answers | Errors | Cost per page | Seconds per page |
|---|---|---|---|---|---|---|---|---|
| Gemini, page by page | 96.7% | 97.3% | 13 / 11 | 9 / 7 | 0 / 0 | 0 / 0 | $0.0027 | 8.3 |
| Argon, page by page | 97.9% | 97.9% | 10 / 10 | 4 / 4 | 0 / 0 | 0 / 0 | $0.0060 | 9.0 |
| Reducto Extract | 74.3% | 70.3% | 39 / 79 | 130 / 116 | 1 / 1 | 0 / 0 | $0.0200 | 9.8 |
| Reducto Deep Extract | 93.8% | 90.3% | 29 / 30 | 12 / 34 | 0 / 0 | 0 / 0 | $0.0400 | 15.4 |

## By kind of table

| Tables | Best open pipeline | Its cells right | Reducto Extract | Reducto Parse |
|---|---|---|---|---|
| large, merged cells | Gemini, whole PDF | 99.0% | 77.2% | 61.7% |
| large, no merged cells | Gemini, page by page | 98.8% | 81.1% | 50.5% |
| medium, merged cells | Docling, then Gemini | 99.7% | 84.4% | 94.7% |
| medium, no merged cells | Gemini, page by page | 99.7% | 89.1% | 69.1% |
| small, merged cells | Gemini, whole PDF | 99.6% | 72.8% | 81.3% |
| small, no merged cells | Gemini, page by page | 99.6% | 97.5% | 92.5% |

## Shape of each answer, run 1

| Pipeline | right shape | empty | one row | under 80% of the rows | a row of the wrong width |
|---|---|---|---|---|---|
| Gemini, whole PDF | 102 | 0 | 0 | 0 | 0 |
| Gemini, page by page | 102 | 0 | 0 | 0 | 0 |
| Docling, then Gemini | 101 | 0 | 0 | 1 | 0 |
| Reducto Parse | 70 | 6 | 0 | 0 | 26 |
| Reducto Extract | 82 | 3 | 4 | 5 | 8 |

## Reducto's cache

Reducto Extract on the 22 subset tables. Same files again: 22 of 22 answers identical to run 1, 0.4 seconds a table. New bytes: 16 of 22 answers differ. Cells right: 488 in run 1, 488 on the same files, 462 on new bytes.
