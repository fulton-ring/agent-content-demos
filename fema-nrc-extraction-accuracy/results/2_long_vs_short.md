# Long against short, FEMA FIS

Share of keyed values right.

|                                                 |   ('long', 'digital') |   ('long', 'scan') |   ('short', 'digital') |   ('short', 'scan') |
|:------------------------------------------------|----------------------:|-------------------:|-----------------------:|--------------------:|
| ('Claude Haiku 5.5', 'Image, page')             |                 100   |              100   |                    100 |               100   |
| ('Claude Haiku 5.5', 'PDF, whole study')        |                 100   |               33.3 |                    100 |                64.7 |
| ('Claude Haiku 5.5', 'Tesseract, page')         |                  60.5 |               29.7 |                    100 |                29.4 |
| ('Claude Haiku 5.5', 'Text layer, page')        |                 100   |                0   |                    100 |                 0   |
| ('Claude Haiku 5.5', 'Text layer, whole study') |                 100   |              nan   |                    100 |               nan   |
| ('Gemini 3.8 Flash', 'Image, page')             |                 100   |              100   |                    100 |               100   |
| ('Gemini 3.8 Flash', 'PDF, whole study')        |                 100   |               97   |                    100 |               100   |
| ('Gemini 3.8 Flash', 'Tesseract, page')         |                  60.5 |               77.6 |                    100 |                47.1 |
| ('Gemini 3.8 Flash', 'Text layer, page')        |                 100   |                0   |                    100 |                 0   |
| ('Gemini 3.8 Flash', 'Text layer, whole study') |                 100   |              nan   |                    100 |               nan   |

## Right, wrong, missing by group

| model            | pipeline                | length   | kind    |   values |   right |   wrong |   missing |   pct_right |
|:-----------------|:------------------------|:---------|:--------|---------:|--------:|--------:|----------:|------------:|
| Claude Haiku 5.5 | Image, page             | long     | digital |      147 |     147 |       0 |         0 |       100   |
| Claude Haiku 5.5 | Image, page             | long     | scan    |      165 |     165 |       0 |         0 |       100   |
| Claude Haiku 5.5 | Image, page             | short    | digital |       75 |      75 |       0 |         0 |       100   |
| Claude Haiku 5.5 | Image, page             | short    | scan    |       17 |      17 |       0 |         0 |       100   |
| Claude Haiku 5.5 | PDF, whole study        | long     | digital |      147 |     147 |       0 |         0 |       100   |
| Claude Haiku 5.5 | PDF, whole study        | long     | scan    |      165 |      55 |       0 |       110 |        33.3 |
| Claude Haiku 5.5 | PDF, whole study        | short    | digital |       75 |      75 |       0 |         0 |       100   |
| Claude Haiku 5.5 | PDF, whole study        | short    | scan    |       17 |      11 |       0 |         6 |        64.7 |
| Claude Haiku 5.5 | Tesseract, page         | long     | digital |      147 |      89 |       3 |        55 |        60.5 |
| Claude Haiku 5.5 | Tesseract, page         | long     | scan    |      165 |      49 |       6 |       110 |        29.7 |
| Claude Haiku 5.5 | Tesseract, page         | short    | digital |       75 |      75 |       0 |         0 |       100   |
| Claude Haiku 5.5 | Tesseract, page         | short    | scan    |       17 |       5 |       0 |        12 |        29.4 |
| Claude Haiku 5.5 | Text layer, page        | long     | digital |      147 |     147 |       0 |         0 |       100   |
| Claude Haiku 5.5 | Text layer, page        | long     | scan    |      165 |       0 |       0 |       165 |         0   |
| Claude Haiku 5.5 | Text layer, page        | short    | digital |       75 |      75 |       0 |         0 |       100   |
| Claude Haiku 5.5 | Text layer, page        | short    | scan    |       17 |       0 |       0 |        17 |         0   |
| Claude Haiku 5.5 | Text layer, whole study | long     | digital |      147 |     147 |       0 |         0 |       100   |
| Claude Haiku 5.5 | Text layer, whole study | short    | digital |       75 |      75 |       0 |         0 |       100   |
| Gemini 3.8 Flash | Image, page             | long     | digital |      147 |     147 |       0 |         0 |       100   |
| Gemini 3.8 Flash | Image, page             | long     | scan    |      165 |     165 |       0 |         0 |       100   |
| Gemini 3.8 Flash | Image, page             | short    | digital |       75 |      75 |       0 |         0 |       100   |
| Gemini 3.8 Flash | Image, page             | short    | scan    |       17 |      17 |       0 |         0 |       100   |
| Gemini 3.8 Flash | PDF, whole study        | long     | digital |      147 |     147 |       0 |         0 |       100   |
| Gemini 3.8 Flash | PDF, whole study        | long     | scan    |      165 |     160 |       5 |         0 |        97   |
| Gemini 3.8 Flash | PDF, whole study        | short    | digital |       75 |      75 |       0 |         0 |       100   |
| Gemini 3.8 Flash | PDF, whole study        | short    | scan    |       17 |      17 |       0 |         0 |       100   |
| Gemini 3.8 Flash | Tesseract, page         | long     | digital |      147 |      89 |       3 |        55 |        60.5 |
| Gemini 3.8 Flash | Tesseract, page         | long     | scan    |      165 |     128 |      37 |         0 |        77.6 |
| Gemini 3.8 Flash | Tesseract, page         | short    | digital |       75 |      75 |       0 |         0 |       100   |
| Gemini 3.8 Flash | Tesseract, page         | short    | scan    |       17 |       8 |       0 |         9 |        47.1 |
| Gemini 3.8 Flash | Text layer, page        | long     | digital |      147 |     147 |       0 |         0 |       100   |
| Gemini 3.8 Flash | Text layer, page        | long     | scan    |      165 |       0 |       0 |       165 |         0   |
| Gemini 3.8 Flash | Text layer, page        | short    | digital |       75 |      75 |       0 |         0 |       100   |
| Gemini 3.8 Flash | Text layer, page        | short    | scan    |       17 |       0 |       0 |        17 |         0   |
| Gemini 3.8 Flash | Text layer, whole study | long     | digital |      147 |     147 |       0 |         0 |       100   |
| Gemini 3.8 Flash | Text layer, whole study | short    | digital |       75 |      75 |       0 |         0 |       100   |

## Cost and time

|                                                 |   calls |       usd |   pages |   seconds |   usd_per_page |   seconds_per_page |
|:------------------------------------------------|--------:|----------:|--------:|----------:|---------------:|-------------------:|
| ('Claude Haiku 5.5', 'Image, page')             |       8 | 0.0064813 |       8 |   37.1977 |        0.00081 |               4.65 |
| ('Claude Haiku 5.5', 'PDF, whole study')        |       8 | 0.369896  |     510 |  140.139  |        0.00073 |               0.27 |
| ('Claude Haiku 5.5', 'Tesseract, page')         |       8 | 0.00449   |       8 |   40.029  |        0.00056 |               5    |
| ('Claude Haiku 5.5', 'Text layer, page')        |       4 | 0.0038606 |       4 |   25.8661 |        0.00097 |               6.47 |
| ('Claude Haiku 5.5', 'Text layer, whole study') |       4 | 0.102564  |     274 |  102.007  |        0.00037 |               0.37 |
| ('Gemini 3.8 Flash', 'Image, page')             |       8 | 0.0349703 |       8 |   84.1522 |        0.00437 |              10.52 |
| ('Gemini 3.8 Flash', 'PDF, whole study')        |       8 | 0.285627  |     510 |  189.479  |        0.00056 |               0.37 |
| ('Gemini 3.8 Flash', 'Tesseract, page')         |       8 | 0.0770992 |       8 |  158.546  |        0.00964 |              19.82 |
| ('Gemini 3.8 Flash', 'Text layer, page')        |       4 | 0.0171045 |       4 |   25.331  |        0.00428 |               6.33 |
| ('Gemini 3.8 Flash', 'Text layer, whole study') |       4 | 0.157793  |     274 |  147.32   |        0.00058 |               0.54 |
