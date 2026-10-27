| Failure mode | Docling alone | Gemini, whole PDF | Gemini, page by page | Docling, then Gemini | Reducto Parse | Reducto Extract |
|---|---|---|---|---|---|---|
| 1. Page break, no repeated header | 71% (0 wrong, 494 missing, 4 extra) | 100% (1 wrong, 0 missing, 0 extra) | 100% (0 wrong, 0 missing, 0 extra) | 100% (0 wrong, 0 missing, 0 extra) | 100% (0 wrong, 0 missing, 3 extra) | 100% (0 wrong, 0 missing, 0 extra) |
| 2. Row split across the break | 65% (12 wrong, 272 missing, 10 extra) | 100% (0 wrong, 0 missing, 0 extra) | 100% (1 wrong, 0 missing, 2 extra) | 100% (0 wrong, 0 missing, 0 extra) | 100% (1 wrong, 0 missing, 6 extra) | 100% (1 wrong, 0 missing, 0 extra) |
| 3. Continuation on the wrong page | 71% (0 wrong, 282 missing, 6 extra) | 100% (0 wrong, 0 missing, 0 extra) | 100% (0 wrong, 0 missing, 0 extra) | 100% (0 wrong, 0 missing, 0 extra) | 100% (0 wrong, 0 missing, 6 extra) | 100% (0 wrong, 0 missing, 0 extra) |
| 4. Wide table cut in half | 35% (0 wrong, 816 missing, 66 extra) | 100% (1 wrong, 0 missing, 0 extra) | 52% (0 wrong, 600 missing, 60 extra) | 100% (0 wrong, 0 missing, 0 extra) | 50% (0 wrong, 630 missing, 96 extra) | 100% (0 wrong, 0 missing, 0 extra) |
| 5. Misaligned columns, no rules | 28% (16 wrong, 679 missing, 1 extra) | 100% (0 wrong, 0 missing, 0 extra) | 100% (0 wrong, 0 missing, 0 extra) | 100% (0 wrong, 0 missing, 0 extra) | 100% (0 wrong, 0 missing, 3 extra) | 100% (0 wrong, 0 missing, 0 extra) |
| 6. Columns change between pages | 59% (131 wrong, 583 missing, 6 extra) | 100% (2 wrong, 0 missing, 0 extra) | 97% (26 wrong, 26 missing, 0 extra) | 88% (0 wrong, 208 missing, 0 extra) | 91% (130 wrong, 26 missing, 6 extra) | 89% (174 wrong, 26 missing, 0 extra) |
| 7. Merged cells | 65% (0 wrong, 228 missing, 10 extra) | 95% (0 wrong, 31 missing, 0 extra) | 90% (0 wrong, 62 missing, 0 extra) | 90% (0 wrong, 62 missing, 0 extra) | 87% (20 wrong, 66 missing, 16 extra) | 100% (1 wrong, 0 missing, 0 extra) |
| 8. Subtotals, carried forward, repeated header | 70% (0 wrong, 427 missing, 29 extra) | 100% (0 wrong, 0 missing, 0 extra) | 100% (0 wrong, 0 missing, 0 extra) | 100% (0 wrong, 0 missing, 0 extra) | 100% (0 wrong, 0 missing, 31 extra) | 100% (0 wrong, 0 missing, 0 extra) |
| 9. Footnotes, (negatives), dashes, n/a | 70% (36 wrong, 250 missing, 3 extra) | 100% (1 wrong, 0 missing, 0 extra) | 100% (0 wrong, 0 missing, 0 extra) | 100% (0 wrong, 0 missing, 0 extra) | 96% (36 wrong, 0 missing, 3 extra) | 100% (0 wrong, 0 missing, 0 extra) |
| 10. Near-duplicate tables | 71% (1 wrong, 125 missing, 49 extra) | 100% (0 wrong, 0 missing, 0 extra) | 100% (0 wrong, 0 missing, 0 extra) | 100% (0 wrong, 0 missing, 0 extra) | 100% (0 wrong, 0 missing, 60 extra) | 100% (0 wrong, 0 missing, 0 extra) |
| 11. Scan damage | 4% (0 wrong, 691 missing, 32 extra) | 93% (47 wrong, 0 missing, 0 extra) | 100% (3 wrong, 0 missing, 0 extra) | 97% (13 wrong, 8 missing, 1 extra) | 100% (0 wrong, 0 missing, 3 extra) | 100% (0 wrong, 0 missing, 0 extra) |
| 12. Handwritten corrections | 67% (17 wrong, 222 missing, 3 extra) | 97% (21 wrong, 0 missing, 0 extra) | 98% (18 wrong, 0 missing, 0 extra) | 97% (22 wrong, 0 missing, 0 extra) | 96% (29 wrong, 0 missing, 3 extra) | 98% (13 wrong, 0 missing, 0 extra) |
| 13. Everything at once | 57% (190 wrong, 261 missing, 55 extra) | 95% (43 wrong, 8 missing, 0 extra) | 96% (37 wrong, 8 missing, 0 extra) | 96% (38 wrong, 8 missing, 0 extra) | 96% (33 wrong, 8 missing, 15 extra) | 96% (29 wrong, 8 missing, 0 extra) |

| Pipeline | Clean documents | Scanned documents | Cost per page | Seconds per page |
|---|---|---|---|---|
| Docling alone | 83% (196 wrong, 1119 missing, 150 extra) | 22% (207 wrong, 4211 missing, 124 extra) | $0.0000 | 21.9 |
| Gemini, whole PDF | 99% (13 wrong, 31 missing, 0 extra) | 98% (103 wrong, 8 missing, 0 extra) | $0.0085 | 20.7 |
| Gemini, page by page | 94% (39 wrong, 447 missing, 62 extra) | 95% (46 wrong, 249 missing, 0 extra) | $0.0098 | 23.6 |
| Docling, then Gemini | 97% (16 wrong, 239 missing, 0 extra) | 98% (57 wrong, 47 missing, 1 extra) | $0.0098 | 40.3 |
| Reducto Parse | 91% (207 wrong, 481 missing, 154 extra) | 95% (42 wrong, 249 missing, 97 extra) | $0.0100 | 28.6 |
| Reducto Extract | 98% (144 wrong, 26 missing, 0 extra) | 99% (74 wrong, 8 missing, 0 extra) | $0.0200 | 35.4 |

| Pipeline | Handwritten number only | Struck-through number only | Both in one cell | Other or missing |
|---|---|---|---|---|
| Docling alone | 0 | 4 | 4 | 22 |
| Gemini, whole PDF | 4 | 4 | 6 | 16 |
| Gemini, page by page | 5 | 0 | 9 | 16 |
| Docling, then Gemini | 4 | 4 | 8 | 14 |
| Reducto Parse | 4 | 6 | 3 | 17 |
| Reducto Extract | 6 | 7 | 0 | 17 |
