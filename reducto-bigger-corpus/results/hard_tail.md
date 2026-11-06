# #136's documents, run twice

## Real documents, run 1 / run 2

| Document | Docling alone | Gemini, whole PDF | Gemini, page by page | Docling, then Gemini | Reducto Parse | Reducto Extract |
|---|---|---|---|---|---|---|
| census-1951 | 30%, 19 wrong / 30%, 19 wrong | 100%, 0 wrong / 86%, 1 wrong | 100%, 0 wrong / 100%, 0 wrong | 100%, 0 wrong / 100%, 0 wrong | 95%, 4 wrong / 95%, 4 wrong | 84%, 3 wrong / 83%, 4 wrong |
| usgs-of-49-60 | 16%, 34 wrong / 16%, 34 wrong | 100%, 0 wrong / 100%, 0 wrong | 100%, 0 wrong / 100%, 0 wrong | 100%, 0 wrong / 100%, 0 wrong | 100%, 0 wrong / 100%, 0 wrong | 56%, 32 wrong / 54%, 23 wrong |
| naca-824-63-009 | 30%, 22 wrong / 30%, 22 wrong | 100%, 0 wrong / 100%, 0 wrong | 100%, 0 wrong / 100%, 0 wrong | 100%, 0 wrong / 100%, 0 wrong | 100%, 0 wrong / 100%, 0 wrong | 100%, 0 wrong / 95%, 5 wrong |
| naca-824-63-006 | 30%, 20 wrong / 30%, 20 wrong | 100%, 0 wrong / 100%, 0 wrong | 100%, 0 wrong / 100%, 0 wrong | 100%, 0 wrong / 100%, 0 wrong | 100%, 0 wrong / 100%, 0 wrong | 100%, 0 wrong / 100%, 0 wrong |
| usgs-of-61-50 | 33%, 124 wrong / 33%, 124 wrong | 98%, 5 wrong / 96%, 9 wrong | 100%, 1 wrong / 100%, 1 wrong | 100%, 0 wrong / 99%, 0 wrong | 99%, 3 wrong / 99%, 3 wrong | 76%, 3 wrong / 99%, 3 wrong |
| irs-990ez-2017 | failed / failed | 93%, 0 wrong / 93%, 0 wrong | 89%, 0 wrong / 89%, 0 wrong | 96%, 0 wrong / 93%, 0 wrong | failed / failed | 68%, 7 wrong / 64%, 8 wrong |
| state-foia-c09001239 | WER 95.0% / WER 95.0% | WER 0.3% / WER 0.0% | WER 0.0% / WER 0.0% | WER 0.0% / WER 0.0% | WER 4.3% / WER 4.3% | WER 1.0% / WER 1.0% |
| usgs-wsp-1050 | 0%, 0 wrong / 0%, 0 wrong | 92%, 8 wrong / 88%, 14 wrong | 100%, 0 wrong / 100%, 0 wrong | 100%, 0 wrong / 100%, 0 wrong | 0%, 0 wrong / 0%, 0 wrong | 0%, 0 wrong / 0%, 0 wrong |

## Deep Extract and Argon, run 1 / run 2

| Document | Reducto Deep Extract | Argon, page by page | Deep Extract cost per page |
|---|---|---|---|
| census-1951 | 92%, 6 wrong / 97%, 3 wrong | 100%, 0 wrong / 100%, 0 wrong | $0.040 |
| usgs-of-49-60 | 100%, 0 wrong / 100%, 0 wrong | 100%, 0 wrong / 100%, 0 wrong | $0.040 |
| naca-824-63-009 | 100%, 0 wrong / 100%, 0 wrong | 100%, 0 wrong / 100%, 0 wrong | $0.040 |
| naca-824-63-006 | 100%, 0 wrong / 100%, 0 wrong | 100%, 0 wrong / 100%, 0 wrong | $0.040 |
| usgs-of-61-50 | 99%, 3 wrong / 99%, 3 wrong | 100%, 1 wrong / 100%, 0 wrong | $0.040 |
| irs-990ez-2017 | 68%, 7 wrong / 64%, 8 wrong | 100%, 0 wrong / 100%, 0 wrong | $0.040 |
| state-foia-c09001239 | WER 1.0% / WER 1.0% | WER 0.0% / WER 0.3% | $0.040 |
| usgs-wsp-1050 | 92%, 6 wrong / 93%, 5 wrong | 100%, 0 wrong / 100%, 0 wrong | $0.040 |

## Broken tables

| Pipeline | Right, run 1 | Right, run 2 | Wrong | Missing | Cost |
|---|---|---|---|---|---|
| Docling alone | 57.2% | 57.2% | 403 / 403 | 5330 / 5330 | $0.00 |
| Gemini, whole PDF | 98.9% | 97.0% | 81 / 131 | 70 / 268 | $1.08 |
| Gemini, page by page | 94.5% | 93.9% | 61 / 90 | 670 / 726 | $1.43 |
| Docling, then Gemini | 97.5% | 99.0% | 63 / 62 | 278 / 70 | $1.30 |
| Reducto Parse | 92.5% | cached | 277 | 731 | $0.67 |
| Reducto Extract | 97.9% | cached | 250 | 34 | $1.34 |

Share right by failure mode, run 1 / run 2:

| Mode | Docling alone | Gemini, whole PDF | Gemini, page by page | Docling, then Gemini | Reducto Parse | Reducto Extract |
|---|---|---|---|---|---|---|
| m01 | 71% / 71% | 100% / 100% | 100% / 100% | 100% / 100% | 100% | 100% |
| m02 | 65% / 65% | 100% / 100% | 100% / 100% | 100% / 100% | 100% | 100% |
| m03 | 71% / 71% | 100% / 100% | 100% / 100% | 100% / 100% | 100% | 100% |
| m04 | 35% / 35% | 100% / 97% | 52% / 50% | 100% / 100% | 50% | 100% |
| m05 | 28% / 28% | 100% / 100% | 100% / 100% | 100% / 100% | 100% | 100% |
| m06 | 59% / 59% | 100% / 88% | 100% / 97% | 88% / 100% | 91% | 89% |
| m07 | 65% / 65% | 90% / 95% | 90% / 90% | 90% / 90% | 85% | 100% |
| m08 | 70% / 70% | 100% / 100% | 100% / 100% | 100% / 100% | 100% | 100% |
| m09 | 70% / 70% | 100% / 99% | 100% / 100% | 100% / 100% | 94% | 98% |
| m10 | 71% / 71% | 100% / 100% | 100% / 100% | 100% / 100% | 100% | 100% |
| m11 | 4% / 4% | 97% / 96% | 100% / 100% | 99% / 100% | 100% | 100% |
| m12 | 67% / 67% | 98% / 97% | 97% / 97% | 97% / 97% | 96% | 97% |
| m13 | 57% / 57% | 96% / 95% | 96% / 96% | 95% / 96% | 96% | 96% |
