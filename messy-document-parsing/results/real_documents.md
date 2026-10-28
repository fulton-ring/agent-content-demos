| Document | Pipeline | Right | Wrong | Missing | Extra rows | Cost per page | Seconds per page |
|---|---|---|---|---|---|---|---|
| census-1951 | Docling alone | 26 of 88 (30%) | 19 | 43 | 25 | $0.0000 | 43.2 |
| census-1951 | Gemini, whole PDF | 88 of 88 (100%) | 0 | 0 | 0 | $0.0004 | 0.2 |
| census-1951 | Gemini, page by page | 88 of 88 (100%) | 0 | 0 | 0 | $0.0033 | 7.4 |
| census-1951 | Docling, then Gemini | 88 of 88 (100%) | 0 | 0 | 0 | $0.0059 | 49.5 |
| census-1951 | Reducto Parse | 84 of 88 (95%) | 4 | 0 | 33 | $0.0100 | 5.2 |
| census-1951 | Reducto Extract | 84 of 88 (95%) | 4 | 0 | 0 | $0.0200 | 5.2 |
| usgs-of-49-60 | Docling alone | 14 of 90 (16%) | 34 | 42 | 4 | $0.0000 | 13.9 |
| usgs-of-49-60 | Gemini, whole PDF | 90 of 90 (100%) | 0 | 0 | 0 | $0.0005 | 0.5 |
| usgs-of-49-60 | Gemini, page by page | 90 of 90 (100%) | 0 | 0 | 0 | $0.0031 | 16.4 |
| usgs-of-49-60 | Docling, then Gemini | 90 of 90 (100%) | 0 | 0 | 0 | $0.0096 | 43.4 |
| usgs-of-49-60 | Reducto Parse | 90 of 90 (100%) | 0 | 0 | 2 | $0.0100 | 5.9 |
| usgs-of-49-60 | Reducto Extract | 90 of 90 (100%) | 0 | 0 | 0 | $0.0200 | 7.4 |
| naca-824-63-009 | Docling alone | 31 of 104 (30%) | 22 | 51 | 179 | $0.0000 | 109.4 |
| naca-824-63-009 | Gemini, whole PDF | 104 of 104 (100%) | 0 | 0 | 0 | $0.0004 | 0.4 |
| naca-824-63-009 | Gemini, page by page | 104 of 104 (100%) | 0 | 0 | 0 | $0.0036 | 17.8 |
| naca-824-63-009 | Docling, then Gemini | 104 of 104 (100%) | 0 | 0 | 0 | $0.0114 | 116.6 |
| naca-824-63-009 | Reducto Parse | 104 of 104 (100%) | 0 | 0 | 254 | $0.0100 | 15.1 |
| naca-824-63-009 | Reducto Extract | 104 of 104 (100%) | 0 | 0 | 0 | $0.0200 | 19.7 |
| naca-824-63-006 | Docling alone | 31 of 104 (30%) | 20 | 53 | 179 | $0.0000 | 111.0 |
| naca-824-63-006 | Gemini, whole PDF | 104 of 104 (100%) | 0 | 0 | 0 | $0.0004 | 0.2 |
| naca-824-63-006 | Gemini, page by page | 104 of 104 (100%) | 0 | 0 | 0 | $0.0036 | 16.9 |
| naca-824-63-006 | Docling, then Gemini | 104 of 104 (100%) | 0 | 0 | 0 | $0.0114 | 117.7 |
| naca-824-63-006 | Reducto Parse | 104 of 104 (100%) | 0 | 0 | 264 | $0.0100 | 15.9 |
| naca-824-63-006 | Reducto Extract | 104 of 104 (100%) | 0 | 0 | 0 | $0.0200 | 19.5 |
| usgs-of-61-50 | Docling alone | 72 of 216 (33%) | 124 | 20 | 26 | $0.0000 | 67.1 |
| usgs-of-61-50 | Gemini, whole PDF | 211 of 216 (98%) | 4 | 1 | 0 | $0.0011 | 2.2 |
| usgs-of-61-50 | Gemini, page by page | 216 of 216 (100%) | 0 | 0 | 0 | $0.0057 | 10.1 |
| usgs-of-61-50 | Docling, then Gemini | 214 of 216 (99%) | 0 | 2 | 0 | $0.0086 | 91.7 |
| usgs-of-61-50 | Reducto Parse | 213 of 216 (99%) | 3 | 0 | 54 | $0.0100 | 8.2 |
| usgs-of-61-50 | Reducto Extract | 214 of 216 (99%) | 2 | 0 | 0 | $0.0200 | 10.7 |
| irs-990ez-2017 | Docling alone | failed: Docling has no way to map handwriting to form lines without  | | | | $0.0000 | 10.1 |
| irs-990ez-2017 | Gemini, whole PDF | 26 of 28 (93%) | 0 | 2 | 0 | $0.0005 | 0.9 |
| irs-990ez-2017 | Gemini, page by page | 25 of 28 (89%) | 0 | 3 | 0 | $0.0025 | 15.3 |
| irs-990ez-2017 | Docling, then Gemini | 26 of 28 (93%) | 0 | 2 | 0 | $0.0038 | 14.5 |
| irs-990ez-2017 | Reducto Parse | failed: Parse returns blocks, not form lines; Extract fills them | | | | $0.0100 | 8.0 |
| irs-990ez-2017 | Reducto Extract | 18 of 28 (64%) | 8 | 2 | 0 | $0.0200 | 10.8 |
| state-foia-c09001239 | Docling alone | word error rate 95.0% | | | | $0.0000 | 7.9 |
| state-foia-c09001239 | Gemini, whole PDF | word error rate 0.3% | | | | $0.0001 | 0.5 |
| state-foia-c09001239 | Gemini, page by page | word error rate 0.0% | | | | $0.0025 | 5.3 |
| state-foia-c09001239 | Docling, then Gemini | word error rate 0.0% | | | | $0.0030 | 13.4 |
| state-foia-c09001239 | Reducto Parse | word error rate 4.3% | | | | $0.0100 | 13.1 |
| state-foia-c09001239 | Reducto Extract | word error rate 1.0% | | | | $0.0200 | 14.2 |
| usgs-wsp-1050 | Docling alone | 0 of 115 (0%) | 0 | 115 | 0 | $0.0000 | 3.6 |
| usgs-wsp-1050 | Gemini, whole PDF | 98 of 115 (85%) | 15 | 2 | 1 | $0.0005 | 0.3 |
| usgs-wsp-1050 | Gemini, page by page | 105 of 115 (91%) | 10 | 0 | 0 | $0.0023 | 6.2 |
| usgs-wsp-1050 | Docling, then Gemini | 115 of 115 (100%) | 0 | 0 | 0 | $0.0035 | 6.2 |
| usgs-wsp-1050 | Reducto Parse | 0 of 115 (0%) | 0 | 115 | 0 | $0.0100 | 6.5 |
| usgs-wsp-1050 | Reducto Extract | 0 of 115 (0%) | 0 | 115 | 0 | $0.0200 | 8.0 |
