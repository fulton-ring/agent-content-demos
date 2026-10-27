| Failure mode | Docling alone | Gemini, whole PDF | Gemini, page by page | Docling, then Gemini |
|---|---|---|---|---|
| 1. Page break, no repeated header | 71% (0 wrong, 494 missing, 4 extra) | 100% (1 wrong, 0 missing, 0 extra) | 100% (0 wrong, 0 missing, 0 extra) | 100% (0 wrong, 0 missing, 0 extra) |
| 2. Row split across the break | 65% (12 wrong, 272 missing, 10 extra) | 100% (0 wrong, 0 missing, 0 extra) | 100% (1 wrong, 0 missing, 1 extra) | 100% (0 wrong, 0 missing, 0 extra) |
| 3. Continuation on the wrong page | 71% (0 wrong, 282 missing, 6 extra) | 100% (0 wrong, 0 missing, 0 extra) | 100% (0 wrong, 0 missing, 0 extra) | 100% (0 wrong, 0 missing, 0 extra) |
| 4. Wide table cut in half | 35% (0 wrong, 816 missing, 66 extra) | 100% (1 wrong, 0 missing, 0 extra) | 50% (0 wrong, 630 missing, 90 extra) | 100% (0 wrong, 0 missing, 0 extra) |
| 5. Misaligned columns, no rules | 28% (16 wrong, 679 missing, 1 extra) | 100% (0 wrong, 0 missing, 0 extra) | 100% (0 wrong, 0 missing, 0 extra) | 100% (0 wrong, 0 missing, 0 extra) |
| 6. Columns change between pages | 59% (131 wrong, 583 missing, 6 extra) | 88% (0 wrong, 208 missing, 0 extra) | 100% (0 wrong, 0 missing, 0 extra) | 88% (0 wrong, 208 missing, 0 extra) |
| 7. Merged cells | 65% (0 wrong, 228 missing, 10 extra) | 90% (0 wrong, 62 missing, 0 extra) | 90% (0 wrong, 62 missing, 0 extra) | 90% (0 wrong, 62 missing, 0 extra) |
| 8. Subtotals, carried forward, repeated header | 70% (0 wrong, 427 missing, 29 extra) | 100% (0 wrong, 0 missing, 0 extra) | 100% (0 wrong, 0 missing, 0 extra) | 100% (0 wrong, 0 missing, 0 extra) |
| 9. Footnotes, (negatives), dashes, n/a | 70% (36 wrong, 250 missing, 3 extra) | 100% (0 wrong, 0 missing, 0 extra) | 100% (0 wrong, 0 missing, 0 extra) | 100% (0 wrong, 0 missing, 0 extra, 2 documents failed) |
| 10. Near-duplicate tables | 71% (1 wrong, 125 missing, 49 extra) | 100% (0 wrong, 0 missing, 0 extra) | 100% (0 wrong, 0 missing, 0 extra) | not run, 3 documents failed |
| 11. Scan damage | 4% (0 wrong, 691 missing, 32 extra) | 81% (125 wrong, 13 missing, 0 extra) | 100% (2 wrong, 0 missing, 0 extra) | not run, 3 documents failed |
| 12. Handwritten corrections | 67% (17 wrong, 222 missing, 3 extra) | 96% (25 wrong, 2 missing, 0 extra) | 97% (20 wrong, 0 missing, 0 extra) | not run, 3 documents failed |
| 13. Everything at once | 57% (190 wrong, 261 missing, 55 extra) | 95% (40 wrong, 8 missing, 0 extra) | 96% (37 wrong, 8 missing, 0 extra) | not run, 3 documents failed |

| Pipeline | Clean documents | Scanned documents | Cost per page | Seconds per page |
|---|---|---|---|---|
| Docling alone | 83% (196 wrong, 1119 missing, 150 extra) | 22% (207 wrong, 4211 missing, 124 extra) | $0.0000 | 22.3 |
| Gemini, whole PDF | 97% (12 wrong, 239 missing, 0 extra) | 96% (180 wrong, 54 missing, 0 extra) | $0.0085 | 20.2 |
| Gemini, page by page | 94% (15 wrong, 451 missing, 61 extra) | 95% (45 wrong, 249 missing, 30 extra) | $0.0097 | 23.8 |
| Docling, then Gemini | 96% (0 wrong, 239 missing, 0 extra, 5 documents failed) | 99% (0 wrong, 31 missing, 0 extra, 9 documents failed) | $0.0104 | 40.8 |

| Pipeline | Handwritten number only | Struck-through number only | Both in one cell | Other or missing |
|---|---|---|---|---|
| Docling alone | 0 | 4 | 4 | 22 |
| Gemini, whole PDF | 3 | 3 | 8 | 16 |
| Gemini, page by page | 7 | 1 | 5 | 17 |
| Docling, then Gemini | 0 | 0 | 0 | 0 |
