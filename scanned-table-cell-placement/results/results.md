# Results

## Keyed tables

| page        | table                                        |   rows |   printed totals |   numbers keyed |   not in source key |
|:------------|:---------------------------------------------|-------:|-----------------:|----------------:|--------------------:|
| 5507271     | Table 4-2 Fragility descriptions (continued) |      5 |                0 |              31 |                   0 |
| 5777799     | Table I Analytical conditions                |      4 |                0 |              38 |                   0 |
| 5777799     | Table II Summary of results                  |     10 |                5 |              51 |                   0 |
| 5533698     | Table C.2 Properties of absorbents           |     19 |                0 |              32 |                   0 |
| 1083928     | Table A.4 Pellet data for rod 4              |     15 |                2 |             150 |                   0 |
| 510218V000  | FIS Summary of Discharges                    |      1 |                0 |               0 |                   0 |
| 060724V000  | FIS Summary of Discharges                    |      6 |                0 |               0 |                   0 |
| 45061CV000A | FIS Summary of Discharges                    |      6 |                0 |               0 |                   0 |
| 35053CV000A | FIS Summary of Discharges                    |      9 |                0 |               0 |                   0 |
| 39151CV001C | FIS Summary of Discharges                    |     16 |                0 |               0 |                   0 |
| 35049CV000A | FIS Summary of Discharges                    |     17 |                0 |               0 |                   0 |
| 51005CV000A | FIS Summary of Discharges                    |     11 |                0 |               0 |                   0 |
| 080290V000  | FIS Summary of Discharges                    |     22 |                0 |               0 |                   0 |

## NRC tables: found vs right row vs right cell (Wilson 95% interval)

| scan   | model            | pipeline               |   cells | found %         | right row %     | right cell %    |   gap (cells) |
|:-------|:-----------------|:-----------------------|--------:|:----------------|:----------------|:----------------|--------------:|
| all    | Claude Haiku 5.5 | Page image             |     286 | 100.0% (99-100) | 100.0% (99-100) | 100.0% (99-100) |             0 |
| all    | Claude Haiku 5.5 | Tesseract, then model  |     286 | 45.1% (39-51)   | 40.6% (35-46)   | 34.3% (29-40)   |            31 |
| all    | Claude Haiku 5.5 | Text layer, then model |     286 | 43.0% (37-49)   | 37.1% (32-43)   | 34.6% (29-40)   |            24 |
| all    | Gemini 3.8 Flash | Page image             |     286 | 72.4% (67-77)   | 72.4% (67-77)   | 72.4% (67-77)   |             0 |
| all    | Gemini 3.8 Flash | Tesseract, then model  |     286 | 78.0% (73-82)   | 73.4% (68-78)   | 64.7% (59-70)   |            38 |
| all    | Gemini 3.8 Flash | Text layer, then model |     286 | 77.3% (72-82)   | 68.5% (63-74)   | 48.6% (43-54)   |            82 |
| fair   | Claude Haiku 5.5 | Page image             |      57 | 100.0% (94-100) | 100.0% (94-100) | 100.0% (94-100) |             0 |
| fair   | Claude Haiku 5.5 | Tesseract, then model  |      57 | 56.1% (43-68)   | 47.4% (35-60)   | 45.6% (33-58)   |             6 |
| fair   | Claude Haiku 5.5 | Text layer, then model |      57 | 100.0% (94-100) | 84.2% (73-91)   | 73.7% (61-83)   |            15 |
| fair   | Gemini 3.8 Flash | Page image             |      57 | 100.0% (94-100) | 100.0% (94-100) | 100.0% (94-100) |             0 |
| fair   | Gemini 3.8 Flash | Tesseract, then model  |      57 | 59.6% (47-71)   | 52.6% (40-65)   | 47.4% (35-60)   |             7 |
| fair   | Gemini 3.8 Flash | Text layer, then model |      57 | 100.0% (94-100) | 100.0% (94-100) | 98.2% (91-100)  |             1 |
| poor   | Claude Haiku 5.5 | Page image             |     229 | 100.0% (98-100) | 100.0% (98-100) | 100.0% (98-100) |             0 |
| poor   | Claude Haiku 5.5 | Tesseract, then model  |     229 | 42.4% (36-49)   | 38.9% (33-45)   | 31.4% (26-38)   |            25 |
| poor   | Claude Haiku 5.5 | Text layer, then model |     229 | 28.8% (23-35)   | 25.3% (20-31)   | 24.9% (20-31)   |             9 |
| poor   | Gemini 3.8 Flash | Page image             |     229 | 65.5% (59-71)   | 65.5% (59-71)   | 65.5% (59-71)   |             0 |
| poor   | Gemini 3.8 Flash | Tesseract, then model  |     229 | 82.5% (77-87)   | 78.6% (73-83)   | 69.0% (63-75)   |            31 |
| poor   | Gemini 3.8 Flash | Text layer, then model |     229 | 71.6% (65-77)   | 60.7% (54-67)   | 36.2% (30-43)   |            81 |

## FIS tables: found vs right cell (Wilson 95% interval)

| scan    | model            | pipeline               |   cells | found %         | right cell %    |   gap (cells) |
|:--------|:-----------------|:-----------------------|--------:|:----------------|:----------------|--------------:|
| digital | Claude Haiku 5.5 | Image page             |     222 | 100.0% (98-100) | 100.0% (98-100) |             0 |
| digital | Claude Haiku 5.5 | PDF whole study        |     222 | 100.0% (98-100) | 100.0% (98-100) |             0 |
| digital | Claude Haiku 5.5 | Tesseract page         |     222 | 74.3% (68-80)   | 73.9% (68-79)   |             1 |
| digital | Claude Haiku 5.5 | Text layer page        |     222 | 100.0% (98-100) | 100.0% (98-100) |             0 |
| digital | Claude Haiku 5.5 | Text layer whole study |     222 | 100.0% (98-100) | 100.0% (98-100) |             0 |
| digital | Gemini 3.8 Flash | Image page             |     222 | 100.0% (98-100) | 100.0% (98-100) |             0 |
| digital | Gemini 3.8 Flash | PDF whole study        |     222 | 100.0% (98-100) | 100.0% (98-100) |             0 |
| digital | Gemini 3.8 Flash | Tesseract page         |     222 | 74.3% (68-80)   | 73.9% (68-79)   |             1 |
| digital | Gemini 3.8 Flash | Text layer page        |     222 | 100.0% (98-100) | 100.0% (98-100) |             0 |
| digital | Gemini 3.8 Flash | Text layer whole study |     222 | 100.0% (98-100) | 100.0% (98-100) |             0 |
| scan    | Claude Haiku 5.5 | Image page             |     182 | 100.0% (98-100) | 100.0% (98-100) |             0 |
| scan    | Claude Haiku 5.5 | PDF whole study        |     182 | 39.6% (33-47)   | 36.3% (30-43)   |             6 |
| scan    | Claude Haiku 5.5 | Tesseract page         |     182 | 29.7% (24-37)   | 29.7% (24-37)   |             0 |
| scan    | Gemini 3.8 Flash | Image page             |     182 | 100.0% (98-100) | 100.0% (98-100) |             0 |
| scan    | Gemini 3.8 Flash | PDF whole study        |     182 | 97.3% (94-99)   | 97.3% (94-99)   |             0 |
| scan    | Gemini 3.8 Flash | Tesseract page         |     182 | 80.2% (74-85)   | 74.7% (68-80)   |            10 |

## Totals check

|                                     | count   |
|:------------------------------------|:--------|
| columns checked                     | 42      |
| columns with an error               | 33      |
| flagged by the check (caught)       | 33      |
| passed the check (missed)           | 0       |
| columns with every value right      | 9       |
| flagged anyway (false alarm)        | 0       |
| wrong cell errors: caught / missed  | 162 / 0 |
| wrong digit errors: caught / missed | 205 / 0 |
| missing errors: caught / missed     | 207 / 0 |

| model            | pipeline               |    osti | column                                  |   cells |   parts add to |   total read | flagged   |   errors |   wrong cell |   wrong digit |   missing |
|:-----------------|:-----------------------|--------:|:----------------------------------------|--------:|---------------:|-------------:|:----------|---------:|-------------:|--------------:|----------:|
| Claude Haiku 5.5 | Text layer, then model | 5777799 | Leakage, Case 1                         |       3 |       nan      |     197      | True      |        2 |            2 |             0 |         0 |
| Claude Haiku 5.5 | Text layer, then model | 5777799 | Leakage, Case 3                         |       2 |       nan      |     163.2    | True      |        1 |            1 |             0 |         0 |
| Claude Haiku 5.5 | Text layer, then model | 5777799 | Leakage, Case 4                         |       3 |       nan      |     247.8    | True      |        2 |            2 |             0 |         0 |
| Claude Haiku 5.5 | Text layer, then model | 5777799 | Leakage, Case 5                         |       3 |       nan      |     291.8    | True      |        2 |            2 |             0 |         0 |
| Claude Haiku 5.5 | Text layer, then model | 5777799 | Leakage, Case 6                         |       3 |       nan      |     291.1    | True      |        2 |            2 |             0 |         0 |
| Claude Haiku 5.5 | Text layer, then model | 1083928 | Total UO2 weight                        |      61 |       nan      |     nan      | True      |       61 |            0 |             0 |        61 |
| Claude Haiku 5.5 | Text layer, then model | 1083928 | Total fuel length (mean of L-1 and L-2) |     121 |       nan      |     nan      | True      |      121 |            0 |             0 |       121 |
| Claude Haiku 5.5 | Tesseract, then model  | 5777799 | Leakage, Case 1                         |       3 |       nan      |     nan      | True      |        3 |            2 |             0 |         1 |
| Claude Haiku 5.5 | Tesseract, then model  | 5777799 | Leakage, Case 3                         |       2 |       nan      |     nan      | True      |        2 |            1 |             0 |         1 |
| Claude Haiku 5.5 | Tesseract, then model  | 5777799 | Leakage, Case 4                         |       3 |       nan      |     nan      | True      |        3 |            3 |             0 |         0 |
| Claude Haiku 5.5 | Tesseract, then model  | 5777799 | Leakage, Case 5                         |       3 |       nan      |     nan      | True      |        3 |            2 |             0 |         1 |
| Claude Haiku 5.5 | Tesseract, then model  | 5777799 | Leakage, Case 6                         |       3 |       nan      |     nan      | True      |        3 |            0 |             0 |         3 |
| Claude Haiku 5.5 | Tesseract, then model  | 1083928 | Total UO2 weight                        |      61 |       702.865  |     704.091  | True      |       16 |            1 |            15 |         0 |
| Claude Haiku 5.5 | Tesseract, then model  | 1083928 | Total fuel length (mean of L-1 and L-2) |     121 |        15.0035 |      30.0833 | True      |      121 |            0 |           121 |         0 |
| Claude Haiku 5.5 | Page image             | 5777799 | Leakage, Case 1                         |       3 |       197      |     197      | False     |        0 |            0 |             0 |         0 |
| Claude Haiku 5.5 | Page image             | 5777799 | Leakage, Case 3                         |       2 |       163.2    |     163.2    | False     |        0 |            0 |             0 |         0 |
| Claude Haiku 5.5 | Page image             | 5777799 | Leakage, Case 4                         |       3 |       247.8    |     247.8    | False     |        0 |            0 |             0 |         0 |
| Claude Haiku 5.5 | Page image             | 5777799 | Leakage, Case 5                         |       3 |       291.8    |     291.8    | False     |        0 |            0 |             0 |         0 |
| Claude Haiku 5.5 | Page image             | 5777799 | Leakage, Case 6                         |       3 |       291.1    |     291.1    | False     |        0 |            0 |             0 |         0 |
| Claude Haiku 5.5 | Page image             | 1083928 | Total UO2 weight                        |      61 |       704.091  |     704.091  | False     |        0 |            0 |             0 |         0 |
| Claude Haiku 5.5 | Page image             | 1083928 | Total fuel length (mean of L-1 and L-2) |     121 |        30.0435 |      30.0435 | False     |        0 |            0 |             0 |         0 |
| Gemini 3.8 Flash | Text layer, then model | 5777799 | Leakage, Case 1                         |       3 |       nan      |     197      | True      |        2 |            2 |             0 |         0 |
| Gemini 3.8 Flash | Text layer, then model | 5777799 | Leakage, Case 3                         |       2 |       nan      |     163.2    | True      |        1 |            1 |             0 |         0 |
| Gemini 3.8 Flash | Text layer, then model | 5777799 | Leakage, Case 4                         |       3 |       nan      |     247.8    | True      |        2 |            2 |             0 |         0 |
| Gemini 3.8 Flash | Text layer, then model | 5777799 | Leakage, Case 5                         |       3 |       nan      |     291.8    | True      |        2 |            2 |             0 |         0 |
| Gemini 3.8 Flash | Text layer, then model | 5777799 | Leakage, Case 6                         |       3 |       nan      |     291.1    | True      |        2 |            2 |             0 |         0 |
| Gemini 3.8 Flash | Text layer, then model | 1083928 | Total UO2 weight                        |      61 |        30.018  |     704.087  | True      |       61 |           15 |            46 |         0 |
| Gemini 3.8 Flash | Text layer, then model | 1083928 | Total fuel length (mean of L-1 and L-2) |     121 |        25.2427 |      30.045  | True      |      121 |          110 |            11 |         0 |
| Gemini 3.8 Flash | Tesseract, then model  | 5777799 | Leakage, Case 1                         |       3 |       nan      |     nan      | True      |        3 |            2 |             0 |         1 |
| Gemini 3.8 Flash | Tesseract, then model  | 5777799 | Leakage, Case 3                         |       2 |       nan      |     nan      | True      |        2 |            2 |             0 |         0 |
| Gemini 3.8 Flash | Tesseract, then model  | 5777799 | Leakage, Case 4                         |       3 |       nan      |     nan      | True      |        3 |            3 |             0 |         0 |
| Gemini 3.8 Flash | Tesseract, then model  | 5777799 | Leakage, Case 5                         |       3 |       nan      |     nan      | True      |        3 |            2 |             0 |         1 |
| Gemini 3.8 Flash | Tesseract, then model  | 5777799 | Leakage, Case 6                         |       3 |       nan      |     nan      | True      |        3 |            0 |             0 |         3 |
| Gemini 3.8 Flash | Tesseract, then model  | 1083928 | Total UO2 weight                        |      61 |       704.333  |     704.091  | True      |        8 |            0 |             8 |         0 |
| Gemini 3.8 Flash | Tesseract, then model  | 1083928 | Total fuel length (mean of L-1 and L-2) |     121 |        30.039  |      30.0833 | True      |        5 |            1 |             4 |         0 |
| Gemini 3.8 Flash | Page image             | 5777799 | Leakage, Case 1                         |       3 |       nan      |     nan      | True      |        3 |            0 |             0 |         3 |
| Gemini 3.8 Flash | Page image             | 5777799 | Leakage, Case 3                         |       2 |       nan      |     nan      | True      |        2 |            0 |             0 |         2 |
| Gemini 3.8 Flash | Page image             | 5777799 | Leakage, Case 4                         |       3 |       nan      |     nan      | True      |        3 |            0 |             0 |         3 |
| Gemini 3.8 Flash | Page image             | 5777799 | Leakage, Case 5                         |       3 |       nan      |     nan      | True      |        3 |            0 |             0 |         3 |
| Gemini 3.8 Flash | Page image             | 5777799 | Leakage, Case 6                         |       3 |       nan      |     nan      | True      |        3 |            0 |             0 |         3 |
| Gemini 3.8 Flash | Page image             | 1083928 | Total UO2 weight                        |      61 |       704.091  |     704.091  | False     |        0 |            0 |             0 |         0 |
| Gemini 3.8 Flash | Page image             | 1083928 | Total fuel length (mean of L-1 and L-2) |     121 |        30.0435 |      30.0435 | False     |        0 |            0 |             0 |         0 |

This run: 0.6 s, $0 (no model calls). The saved answers it rescores cost $1.15 when the source spike made them (NRC $0.09, FIS $1.06).
