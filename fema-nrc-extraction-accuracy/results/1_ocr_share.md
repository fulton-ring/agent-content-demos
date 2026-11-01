# OCR share, FEMA FIS sample

|                                  |           0 |
|:---------------------------------|------------:|
| pdfs                             |   70        |
| pages                            | 3760        |
| pages_text                       | 1532        |
| pages_scan                       | 1161        |
| pages_drawing                    | 1035        |
| pages_blank                      |   32        |
| share_pages_need_ocr             |    0.584043 |
| share_pdfs_no_ocr                |    0.185714 |
| share_pdfs_no_ocr_drawings_aside |    0.442857 |
| pdfs_all_scanned                 |   34        |

## By effective date

| era       |   pdfs |   pages |   scan |   drawing |   no_ocr_pdfs |   share_pages_need_ocr |
|:----------|-------:|--------:|-------:|----------:|--------------:|-----------------------:|
| 1978-1999 |     26 |     638 |    638 |         0 |             0 |                  1     |
| 2000-2009 |     15 |     883 |    442 |       125 |             3 |                  0.642 |
| 2010-2024 |     29 |    2239 |     81 |       910 |            10 |                  0.443 |

## Classifier against Tesseract, 200 seeded pages

| classifier   |   False |   True |
|:-------------|--------:|-------:|
| False        |      82 |      2 |
| True         |       0 |    116 |
