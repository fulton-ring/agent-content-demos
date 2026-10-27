# Pipelines compared

Same documents and answer keys. A silent error is a wrong value accepted without review. Written by 3_results.py.

## held out set

| Pipeline | Boxes | Accepted (right) | Sent to review | Silent errors |
|---|---|---|---|---|
| A. VLM alone, whole PDF | 310 | 298 (296) | 12 | 2 |
| B. Docling Markdown, then the model (text only) | 329 | 314 (154) | 15 | 160 |
| C. Docling finds the page, the VLM reads its image and Markdown | 310 | 299 (299) | 11 | 0 |

## tuning / real / office scan

| Pipeline | Boxes | Accepted (right) | Sent to review | Silent errors |
|---|---|---|---|---|
| A. VLM alone, whole PDF | 97 | 91 (90) | 6 | 1 |
| B. Docling Markdown, then the model (text only) | 104 | 100 (32) | 4 | 68 |
| C. Docling finds the page, the VLM reads its image and Markdown | 97 | 91 (91) | 6 | 0 |

## tuning / real / born-digital

| Pipeline | Boxes | Accepted (right) | Sent to review | Silent errors |
|---|---|---|---|---|
| A. VLM alone, whole PDF | 97 | 91 (88) | 6 | 3 |
| B. Docling Markdown, then the model (text only) | 100 | 92 (83) | 8 | 9 |
| C. Docling finds the page, the VLM reads its image and Markdown | 97 | 91 (91) | 6 | 0 |

## tuning / real / bad scan

| Pipeline | Boxes | Accepted (right) | Sent to review | Silent errors |
|---|---|---|---|---|
| A. VLM alone, whole PDF | 30 | 29 (29) | 1 | 0 |
| B. Docling Markdown, then the model (text only) | 33 | 32 (16) | 1 | 16 |
| C. Docling finds the page, the VLM reads its image and Markdown | 30 | 29 (29) | 1 | 0 |

## tuning / made-up / office scan

| Pipeline | Boxes | Accepted (right) | Sent to review | Silent errors |
|---|---|---|---|---|
| A. VLM alone, whole PDF | 46 | 46 (46) | 0 | 0 |
| B. Docling Markdown, then the model (text only) | 47 | 47 (31) | 0 | 16 |
| C. Docling finds the page, the VLM reads its image and Markdown | 46 | 46 (46) | 0 | 0 |

## tuning / made-up / clean scan

| Pipeline | Boxes | Accepted (right) | Sent to review | Silent errors |
|---|---|---|---|---|
| A. VLM alone, whole PDF | 48 | 48 (48) | 0 | 0 |
| B. Docling Markdown, then the model (text only) | 50 | 50 (38) | 0 | 12 |
| C. Docling finds the page, the VLM reads its image and Markdown | 48 | 48 (48) | 0 | 0 |

## tuning / made-up / bad scan

| Pipeline | Boxes | Accepted (right) | Sent to review | Silent errors |
|---|---|---|---|---|
| A. VLM alone, whole PDF | 48 | 48 (48) | 0 | 0 |
| B. Docling Markdown, then the model (text only) | 48 | 44 (26) | 4 | 18 |
| C. Docling finds the page, the VLM reads its image and Markdown | 48 | 48 (30) | 0 | 18 |

## held out / real / office scan

| Pipeline | Boxes | Accepted (right) | Sent to review | Silent errors |
|---|---|---|---|---|
| A. VLM alone, whole PDF | 97 | 91 (90) | 6 | 1 |
| B. Docling Markdown, then the model (text only) | 101 | 100 (35) | 1 | 65 |
| C. Docling finds the page, the VLM reads its image and Markdown | 97 | 91 (91) | 6 | 0 |

## held out / real / bad scan

| Pipeline | Boxes | Accepted (right) | Sent to review | Silent errors |
|---|---|---|---|---|
| A. VLM alone, whole PDF | 67 | 61 (60) | 6 | 1 |
| B. Docling Markdown, then the model (text only) | 74 | 71 (19) | 3 | 52 |
| C. Docling finds the page, the VLM reads its image and Markdown | 67 | 62 (62) | 5 | 0 |

## held out / made-up / office scan

| Pipeline | Boxes | Accepted (right) | Sent to review | Silent errors |
|---|---|---|---|---|
| A. VLM alone, whole PDF | 47 | 47 (47) | 0 | 0 |
| B. Docling Markdown, then the model (text only) | 48 | 46 (29) | 2 | 17 |
| C. Docling finds the page, the VLM reads its image and Markdown | 47 | 47 (47) | 0 | 0 |

## held out / made-up / clean scan

| Pipeline | Boxes | Accepted (right) | Sent to review | Silent errors |
|---|---|---|---|---|
| A. VLM alone, whole PDF | 50 | 50 (50) | 0 | 0 |
| B. Docling Markdown, then the model (text only) | 53 | 48 (42) | 5 | 6 |
| C. Docling finds the page, the VLM reads its image and Markdown | 50 | 50 (50) | 0 | 0 |

## held out / made-up / bad scan

| Pipeline | Boxes | Accepted (right) | Sent to review | Silent errors |
|---|---|---|---|---|
| A. VLM alone, whole PDF | 49 | 49 (49) | 0 | 0 |
| B. Docling Markdown, then the model (text only) | 53 | 49 (29) | 4 | 20 |
| C. Docling finds the page, the VLM reads its image and Markdown | 49 | 49 (49) | 0 | 0 |

**A. VLM alone, whole PDF**: $0.26 in all, 0 failed attempts. Failed documents: none. Unknown cost: none. Silent errors: 03-blackstone-2019-k1-scan1a.pdf box 7; 03-blackstone-2019-k1-scan1b.pdf box 16 E; 03-blackstone-2019-k1-scan2b.pdf box 7; 03-blackstone-2019-k1.pdf box 13 E; 03-blackstone-2019-k1.pdf box 17 B; 03-blackstone-2019-k1.pdf box 7.

**B. Docling Markdown, then the model (text only)**: $0.48 in all, 0 failed attempts. Failed documents: none. Unknown cost: none. Silent errors: 01-enviva-2018-k1-scan1a.pdf box 10; 01-enviva-2018-k1-scan1a.pdf box 13 K; 01-enviva-2018-k1-scan1a.pdf box 16 A; 01-enviva-2018-k1-scan1a.pdf box 16 B; 01-enviva-2018-k1-scan1a.pdf box 16 L*; 01-enviva-2018-k1-scan1a.pdf box 17 A; 01-enviva-2018-k1-scan1a.pdf box 17 B; 01-enviva-2018-k1-scan1a.pdf box 18 C; 01-enviva-2018-k1-scan1a.pdf box 19 A; 01-enviva-2018-k1-scan1a.pdf box 20 A; 01-enviva-2018-k1-scan1a.pdf box 20 AD; 01-enviva-2018-k1-scan1a.pdf box 20 AH*; 01-enviva-2018-k1-scan1a.pdf box 20 V; 01-enviva-2018-k1-scan1a.pdf box 5; 01-enviva-2018-k1-scan1a.pdf box 9a; 01-enviva-2018-k1-scan1a.pdf box payer_ein; 01-enviva-2018-k1-scan1b.pdf box 1; 01-enviva-2018-k1-scan1b.pdf box 10; 01-enviva-2018-k1-scan1b.pdf box 13 K; 01-enviva-2018-k1-scan1b.pdf box 16 A; 01-enviva-2018-k1-scan1b.pdf box 16 B; 01-enviva-2018-k1-scan1b.pdf box 16 L*; 01-enviva-2018-k1-scan1b.pdf box 17 A; 01-enviva-2018-k1-scan1b.pdf box 17 B; 01-enviva-2018-k1-scan1b.pdf box 18 C; 01-enviva-2018-k1-scan1b.pdf box 19 A; 01-enviva-2018-k1-scan1b.pdf box 20 A; 01-enviva-2018-k1-scan1b.pdf box 20 AD; 01-enviva-2018-k1-scan1b.pdf box 20 AH*; 01-enviva-2018-k1-scan1b.pdf box 20 V; 01-enviva-2018-k1-scan1b.pdf box 5; 01-enviva-2018-k1-scan1b.pdf box 9a; 01-enviva-2018-k1-scan1b.pdf box payer_ein; 01-enviva-2018-k1-scan2b.pdf box 1; 01-enviva-2018-k1-scan2b.pdf box 10; 01-enviva-2018-k1-scan2b.pdf box 13 K; 01-enviva-2018-k1-scan2b.pdf box 13 L; 01-enviva-2018-k1-scan2b.pdf box 13 W; 01-enviva-2018-k1-scan2b.pdf box 16 A; 01-enviva-2018-k1-scan2b.pdf box 16 B; 01-enviva-2018-k1-scan2b.pdf box 16 L*; 01-enviva-2018-k1-scan2b.pdf box 17 A; 01-enviva-2018-k1-scan2b.pdf box 17 B; 01-enviva-2018-k1-scan2b.pdf box 18 A; 01-enviva-2018-k1-scan2b.pdf box 18 C; 01-enviva-2018-k1-scan2b.pdf box 19 A; 01-enviva-2018-k1-scan2b.pdf box 20 AD; 01-enviva-2018-k1-scan2b.pdf box 20 AH*; 01-enviva-2018-k1-scan2b.pdf box 20 B; 01-enviva-2018-k1-scan2b.pdf box 20 V; 01-enviva-2018-k1-scan2b.pdf box 5; 01-enviva-2018-k1-scan2b.pdf box 9a; 01-enviva-2018-k1-scan2b.pdf box payer_ein; 01-enviva-2018-k1-scan2b.pdf box payer_name; 01-enviva-2018-k1.pdf box 17 B; 01-enviva-2018-k1.pdf box 20 B; 01-enviva-2018-k1.pdf box 20 L*; 01-enviva-2018-k1.pdf box 5; 01-enviva-2018-k1.pdf box 9a; 02-enviva-2021-k1-scan1a.pdf box 1; 02-enviva-2021-k1-scan1a.pdf box 10; 02-enviva-2021-k1-scan1a.pdf box 13 K; 02-enviva-2021-k1-scan1a.pdf box 17 A; 02-enviva-2021-k1-scan1a.pdf box 17 B; 02-enviva-2021-k1-scan1a.pdf box 18 C; 02-enviva-2021-k1-scan1a.pdf box 19 A; 02-enviva-2021-k1-scan1a.pdf box 19 C*; 02-enviva-2021-k1-scan1a.pdf box 20 *; 02-enviva-2021-k1-scan1a.pdf box 20 A; 02-enviva-2021-k1-scan1a.pdf box 20 N; 02-enviva-2021-k1-scan1a.pdf box 20 V; 02-enviva-2021-k1-scan1a.pdf box 5; 02-enviva-2021-k1-scan1a.pdf box 9a; 02-enviva-2021-k1-scan1a.pdf box payer_ein; 02-enviva-2021-k1-scan1b.pdf box 1; 02-enviva-2021-k1-scan1b.pdf box 10; 02-enviva-2021-k1-scan1b.pdf box 13 K; 02-enviva-2021-k1-scan1b.pdf box 14 A; 02-enviva-2021-k1-scan1b.pdf box 17 A; 02-enviva-2021-k1-scan1b.pdf box 17 B; 02-enviva-2021-k1-scan1b.pdf box 18 B; 02-enviva-2021-k1-scan1b.pdf box 18 C; 02-enviva-2021-k1-scan1b.pdf box 19 A; 02-enviva-2021-k1-scan1b.pdf box 19 C*; 02-enviva-2021-k1-scan1b.pdf box 20 *; 02-enviva-2021-k1-scan1b.pdf box 20 A; 02-enviva-2021-k1-scan1b.pdf box 20 B; 02-enviva-2021-k1-scan1b.pdf box 20 N; 02-enviva-2021-k1-scan1b.pdf box 20 V; 02-enviva-2021-k1-scan1b.pdf box 9a; 02-enviva-2021-k1-scan1b.pdf box payer_ein; 02-enviva-2021-k1-scan2a.pdf box 1; 02-enviva-2021-k1-scan2a.pdf box 10; 02-enviva-2021-k1-scan2a.pdf box 13 K; 02-enviva-2021-k1-scan2a.pdf box 17 A; 02-enviva-2021-k1-scan2a.pdf box 17 B; 02-enviva-2021-k1-scan2a.pdf box 18 B; 02-enviva-2021-k1-scan2a.pdf box 18 C; 02-enviva-2021-k1-scan2a.pdf box 19 A; 02-enviva-2021-k1-scan2a.pdf box 19 C*; 02-enviva-2021-k1-scan2a.pdf box 20 *; 02-enviva-2021-k1-scan2a.pdf box 20 A; 02-enviva-2021-k1-scan2a.pdf box 20 B; 02-enviva-2021-k1-scan2a.pdf box 20 N; 02-enviva-2021-k1-scan2a.pdf box 20 V; 02-enviva-2021-k1-scan2a.pdf box 5; 02-enviva-2021-k1-scan2a.pdf box 9a; 02-enviva-2021-k1.pdf box 10; 02-enviva-2021-k1.pdf box 21; 02-enviva-2021-k1.pdf box 5; 02-enviva-2021-k1.pdf box 9a; 03-blackstone-2019-k1-scan1a.pdf box 1; 03-blackstone-2019-k1-scan1a.pdf box 10; 03-blackstone-2019-k1-scan1a.pdf box 13 E; 03-blackstone-2019-k1-scan1a.pdf box 13 H; 03-blackstone-2019-k1-scan1a.pdf box 13 J; 03-blackstone-2019-k1-scan1a.pdf box 13 L; 03-blackstone-2019-k1-scan1a.pdf box 13 M; 03-blackstone-2019-k1-scan1a.pdf box 13 V; 03-blackstone-2019-k1-scan1a.pdf box 13 W; 03-blackstone-2019-k1-scan1a.pdf box 16 *; 03-blackstone-2019-k1-scan1a.pdf box 16 A; 03-blackstone-2019-k1-scan1a.pdf box 16 B; 03-blackstone-2019-k1-scan1a.pdf box 16 C; 03-blackstone-2019-k1-scan1a.pdf box 16 E; 03-blackstone-2019-k1-scan1a.pdf box 16 F; 03-blackstone-2019-k1-scan1a.pdf box 16 G; 03-blackstone-2019-k1-scan1a.pdf box 17 *; 03-blackstone-2019-k1-scan1a.pdf box 17 A; 03-blackstone-2019-k1-scan1a.pdf box 17 B; 03-blackstone-2019-k1-scan1a.pdf box 18 A; 03-blackstone-2019-k1-scan1a.pdf box 18 B; 03-blackstone-2019-k1-scan1a.pdf box 18 C; 03-blackstone-2019-k1-scan1a.pdf box 19 A; 03-blackstone-2019-k1-scan1a.pdf box 20 A; 03-blackstone-2019-k1-scan1a.pdf box 20 B; 03-blackstone-2019-k1-scan1a.pdf box 3; 03-blackstone-2019-k1-scan1a.pdf box 4a; 03-blackstone-2019-k1-scan1a.pdf box 5; 03-blackstone-2019-k1-scan1a.pdf box 6a; 03-blackstone-2019-k1-scan1a.pdf box 6b; 03-blackstone-2019-k1-scan1a.pdf box 6c; 03-blackstone-2019-k1-scan1a.pdf box 7; 03-blackstone-2019-k1-scan1a.pdf box 8; 03-blackstone-2019-k1-scan1a.pdf box 9a; 03-blackstone-2019-k1-scan1a.pdf box 9b; 03-blackstone-2019-k1-scan1a.pdf box 9c; 03-blackstone-2019-k1-scan1a.pdf box payer_ein; 03-blackstone-2019-k1-scan1b.pdf box 1; 03-blackstone-2019-k1-scan1b.pdf box 10; 03-blackstone-2019-k1-scan1b.pdf box 11 *; 03-blackstone-2019-k1-scan1b.pdf box 13 *; 03-blackstone-2019-k1-scan1b.pdf box 13 E; 03-blackstone-2019-k1-scan1b.pdf box 13 H; 03-blackstone-2019-k1-scan1b.pdf box 16 *; 03-blackstone-2019-k1-scan1b.pdf box 16 A; 03-blackstone-2019-k1-scan1b.pdf box 16 B; 03-blackstone-2019-k1-scan1b.pdf box 16 C; 03-blackstone-2019-k1-scan1b.pdf box 16 E; 03-blackstone-2019-k1-scan1b.pdf box 16 F; 03-blackstone-2019-k1-scan1b.pdf box 16 G; 03-blackstone-2019-k1-scan1b.pdf box 17 *; 03-blackstone-2019-k1-scan1b.pdf box 17 A; 03-blackstone-2019-k1-scan1b.pdf box 17 B; 03-blackstone-2019-k1-scan1b.pdf box 18 C; 03-blackstone-2019-k1-scan1b.pdf box 19 A; 03-blackstone-2019-k1-scan1b.pdf box 2; 03-blackstone-2019-k1-scan1b.pdf box 20 *; 03-blackstone-2019-k1-scan1b.pdf box 20 A; 03-blackstone-2019-k1-scan1b.pdf box 20 B; 03-blackstone-2019-k1-scan1b.pdf box 5; 03-blackstone-2019-k1-scan1b.pdf box 6a; 03-blackstone-2019-k1-scan1b.pdf box 6b; 03-blackstone-2019-k1-scan1b.pdf box 7; 03-blackstone-2019-k1-scan1b.pdf box 8; 03-blackstone-2019-k1-scan1b.pdf box 9a; 03-blackstone-2019-k1-scan1b.pdf box 9c; 03-blackstone-2019-k1-scan1b.pdf box payer_ein; 03-blackstone-2019-k1-scan1b.pdf box payer_name; 03-blackstone-2019-k1-scan2b.pdf box 1; 03-blackstone-2019-k1-scan2b.pdf box 10; 03-blackstone-2019-k1-scan2b.pdf box 11 *; 03-blackstone-2019-k1-scan2b.pdf box 13 *; 03-blackstone-2019-k1-scan2b.pdf box 13 E; 03-blackstone-2019-k1-scan2b.pdf box 13 H; 03-blackstone-2019-k1-scan2b.pdf box 16 *; 03-blackstone-2019-k1-scan2b.pdf box 16 A; 03-blackstone-2019-k1-scan2b.pdf box 16 B; 03-blackstone-2019-k1-scan2b.pdf box 16 C; 03-blackstone-2019-k1-scan2b.pdf box 16 E; 03-blackstone-2019-k1-scan2b.pdf box 16 F; 03-blackstone-2019-k1-scan2b.pdf box 16 G; 03-blackstone-2019-k1-scan2b.pdf box 17 *; 03-blackstone-2019-k1-scan2b.pdf box 17 A; 03-blackstone-2019-k1-scan2b.pdf box 17 B; 03-blackstone-2019-k1-scan2b.pdf box 18 C; 03-blackstone-2019-k1-scan2b.pdf box 19 A; 03-blackstone-2019-k1-scan2b.pdf box 2; 03-blackstone-2019-k1-scan2b.pdf box 20 *; 03-blackstone-2019-k1-scan2b.pdf box 20 A; 03-blackstone-2019-k1-scan2b.pdf box 20 B; 03-blackstone-2019-k1-scan2b.pdf box 5; 03-blackstone-2019-k1-scan2b.pdf box 6a; 03-blackstone-2019-k1-scan2b.pdf box 6b; 03-blackstone-2019-k1-scan2b.pdf box 7; 03-blackstone-2019-k1-scan2b.pdf box 8; 03-blackstone-2019-k1-scan2b.pdf box 9a; 03-blackstone-2019-k1-scan2b.pdf box 9c; 03-blackstone-2019-k1-scan2b.pdf box payer_ein; 03-blackstone-2019-k1-scan2b.pdf box payer_name; 10-madeup-k1-1120s.pdf box 11; 10-madeup-k1-1120s.pdf box 12 B; 10-madeup-k1-1120s.pdf box 16 D; 10-madeup-k1-1120s.pdf box 16 E; 10-madeup-k1-1120s.pdf box 2; 10-madeup-k1-1120s.pdf box 4; 10-madeup-k1-1120s.pdf box 9; 11-madeup-k1-1120s.pdf box 1; 11-madeup-k1-1120s.pdf box 11; 11-madeup-k1-1120s.pdf box 13 A; 11-madeup-k1-1120s.pdf box 16 D; 11-madeup-k1-1120s.pdf box 17 V; 11-madeup-k1-1120s.pdf box 4; 11-madeup-k1-1120s.pdf box 5a; 11-madeup-k1-1120s.pdf box 5b; 11-madeup-k1-1120s.pdf box 7; 11-madeup-k1-1120s.pdf box 8a; 11-madeup-k1-1120s.pdf box payer_ein; 12-madeup-k1-1120s.pdf box 1; 12-madeup-k1-1120s.pdf box 12 B; 12-madeup-k1-1120s.pdf box 16 D; 12-madeup-k1-1120s.pdf box 17 V; 12-madeup-k1-1120s.pdf box 4; 12-madeup-k1-1120s.pdf box 5a; 12-madeup-k1-1120s.pdf box 5b; 12-madeup-k1-1120s.pdf box 8a; 13-madeup-k1-1041.pdf box 1; 13-madeup-k1-1041.pdf box 11 C; 13-madeup-k1-1041.pdf box 14 I; 13-madeup-k1-1041.pdf box 2a; 13-madeup-k1-1041.pdf box 2b; 14-madeup-k1-1041.pdf box 14 A; 14-madeup-k1-1041.pdf box 4a; 14-madeup-k1-1041.pdf box 5; 14-madeup-k1-1041.pdf box 7; 14-madeup-k1-1041.pdf box payer_name; 15-madeup-k1-1041.pdf box 1; 15-madeup-k1-1041.pdf box 14 A; 15-madeup-k1-1041.pdf box 2a; 15-madeup-k1-1041.pdf box 2b; 15-madeup-k1-1041.pdf box 3; 15-madeup-k1-1041.pdf box 4a; 15-madeup-k1-1041.pdf box 6; 15-madeup-k1-1041.pdf box 7; 15-madeup-k1-1041.pdf box 9 B; 18-madeup-brokerage-1099.pdf box DIV 1b; 20-madeup-k1-1120s.pdf box 12 B; 20-madeup-k1-1120s.pdf box 4; 20-madeup-k1-1120s.pdf box 5a; 20-madeup-k1-1120s.pdf box 5b; 20-madeup-k1-1120s.pdf box 6; 20-madeup-k1-1120s.pdf box 7; 21-madeup-k1-1120s.pdf box 16 D; 21-madeup-k1-1120s.pdf box 17 V; 21-madeup-k1-1120s.pdf box 2; 21-madeup-k1-1120s.pdf box 4; 21-madeup-k1-1120s.pdf box 5a; 21-madeup-k1-1120s.pdf box 5b; 21-madeup-k1-1120s.pdf box 8a; 21-madeup-k1-1120s.pdf box 9; 21-madeup-k1-1120s.pdf box payer_name; 22-madeup-k1-1120s.pdf box 1; 22-madeup-k1-1120s.pdf box 12 B; 22-madeup-k1-1120s.pdf box 16 B; 22-madeup-k1-1120s.pdf box 16 C; 22-madeup-k1-1120s.pdf box 16 D; 22-madeup-k1-1120s.pdf box 4; 22-madeup-k1-1120s.pdf box 5a; 22-madeup-k1-1120s.pdf box 5b; 22-madeup-k1-1120s.pdf box 7; 22-madeup-k1-1120s.pdf box 8a; 24-madeup-k1-1041.pdf box 1; 24-madeup-k1-1041.pdf box 11 D; 24-madeup-k1-1041.pdf box 14 I; 24-madeup-k1-1041.pdf box 2a; 24-madeup-k1-1041.pdf box 2b; 24-madeup-k1-1041.pdf box 4a; 24-madeup-k1-1041.pdf box 5; 24-madeup-k1-1041.pdf box 7; 25-madeup-k1-1041.pdf box 1; 25-madeup-k1-1041.pdf box 11 D; 25-madeup-k1-1041.pdf box 14 I; 25-madeup-k1-1041.pdf box 2a; 25-madeup-k1-1041.pdf box 2b; 25-madeup-k1-1041.pdf box 3; 25-madeup-k1-1041.pdf box 4a; 25-madeup-k1-1041.pdf box 6; 25-madeup-k1-1041.pdf box payer_ein; 25-madeup-k1-1041.pdf box payer_name.

**C. Docling finds the page, the VLM reads its image and Markdown**: $0.27 in all, 0 failed attempts. Failed documents: none. Unknown cost: none. Silent errors: 18-madeup-brokerage-1099.pdf box B A cost; 18-madeup-brokerage-1099.pdf box B A gain; 18-madeup-brokerage-1099.pdf box B A proceeds; 18-madeup-brokerage-1099.pdf box B A wash; 18-madeup-brokerage-1099.pdf box B D cost; 18-madeup-brokerage-1099.pdf box B D gain; 18-madeup-brokerage-1099.pdf box B D proceeds; 18-madeup-brokerage-1099.pdf box B D wash; 18-madeup-brokerage-1099.pdf box DIV 1a; 18-madeup-brokerage-1099.pdf box DIV 1b; 18-madeup-brokerage-1099.pdf box DIV 2a; 18-madeup-brokerage-1099.pdf box DIV 3; 18-madeup-brokerage-1099.pdf box DIV 5; 18-madeup-brokerage-1099.pdf box DIV 7; 18-madeup-brokerage-1099.pdf box INT 1; 18-madeup-brokerage-1099.pdf box INT 3; 18-madeup-brokerage-1099.pdf box INT 4; 18-madeup-brokerage-1099.pdf box INT 8.
