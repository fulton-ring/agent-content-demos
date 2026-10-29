# Scanned 990-EZ, 100 returns

| Pipeline | Right, run 1 | Right, run 2 | Wrong | Missing | Empty answers | Errors | Cost per page | Seconds per page |
|---|---|---|---|---|---|---|---|---|
| Gemini, whole PDF | 99.0% | 99.0% | 18 / 19 | 2 / 2 | 0 / 0 | 0 / 0 | $0.0017 | 9.8 |
| Gemini, page by page | 99.8% | 99.9% | 5 / 3 | 0 / 0 | 0 / 0 | 0 / 0 | $0.0021 | 8.6 |
| Docling, then Gemini | 98.8% | 99.9% | 18 / 2 | 6 / 0 | 0 / 0 | 0 / 0 | $0.0039 | 26.4 |
| Reducto Extract | 99.0% | 98.4% | 20 / 29 | 0 / 4 | 0 / 0 | 0 / 0 | $0.0200 | 7.8 |

## 20-return subset

| Pipeline | Right, run 1 | Right, run 2 | Wrong | Missing | Empty answers | Errors | Cost per page | Seconds per page |
|---|---|---|---|---|---|---|---|---|
| Gemini, page by page | 99.5% | 99.8% | 2 / 1 | 0 / 0 | 0 / 0 | 0 / 0 | $0.0021 | 7.4 |
| Argon, page by page | 100.0% | 99.8% | 0 / 1 | 0 / 0 | 0 / 0 | 0 / 0 | $0.0059 | 10.0 |
| Reducto Extract | 99.8% | 95.8% | 1 / 13 | 0 / 4 | 0 / 0 | 0 / 0 | $0.0200 | 6.1 |
| Reducto Deep Extract | 100.0% | 99.8% | 0 / 1 | 0 / 0 | 0 / 0 | 0 / 0 | $0.0400 | 16.7 |

## Wrong values by line, both runs

| Line | Gemini, whole PDF | Gemini, page by page | Docling, then Gemini | Reducto Extract |
|---|---|---|---|---|
| 1 | 4 | 2 | 1 | 3 |
| 2 | 2 | 1 | 1 | 5 |
| 3 | 2 | 0 | 1 | 3 |
| 4 | 2 | 0 | 1 | 2 |
| 5a | 2 | 0 | 1 | 2 |
| 5b | 2 | 0 | 1 | 2 |
| 5c | 2 | 0 | 1 | 1 |
| 6a | 2 | 0 | 1 | 1 |
| 6b | 2 | 0 | 1 | 3 |
| 6c | 0 | 0 | 1 | 1 |
| 6d | 2 | 0 | 1 | 3 |
| 7a | 0 | 0 | 0 | 1 |
| 7b | 2 | 1 | 2 | 2 |
| 7c | 2 | 1 | 1 | 4 |
| 8 | 2 | 0 | 0 | 0 |
| 9 | 3 | 2 | 3 | 5 |
| 17 | 2 | 0 | 1 | 2 |
| 18 | 3 | 1 | 1 | 4 |
| 20 | 0 | 0 | 0 | 1 |
| 21 | 1 | 0 | 1 | 4 |
