# Public-records OCR bench: scores

Written by `bench.py`.

## Tests

| group            |   absent |   present |   table |   total |
|:-----------------|---------:|----------:|--------:|--------:|
| fis_born_digital |        0 |        12 |     201 |     213 |
| fis_scanned      |        0 |        16 |     176 |     192 |
| headers_footers  |       17 |         0 |       0 |      17 |
| nrc_fair_scan    |        0 |        41 |       0 |      41 |
| nrc_good_scan    |        0 |        47 |       0 |      47 |
| nrc_poor_scan    |        0 |       166 |       0 |     166 |
| total            |       17 |       282 |     377 |     676 |

## Share of tests passed, by group (%)

| pipeline        |   fis_born_digital |   fis_scanned |   headers_footers |   nrc_fair_scan |   nrc_good_scan |   nrc_poor_scan |   all tests |
|:----------------|-------------------:|--------------:|------------------:|----------------:|----------------:|----------------:|------------:|
| text_layer      |                5.6 |           0   |              70.6 |            92.7 |             100 |            60.2 |        30.9 |
| tesseract       |                5.6 |           2.6 |              58.8 |            61   |             100 |            66.9 |        31.1 |
| tesseract_haiku |               82.2 |          33.9 |             100   |            48.8 |             100 |            65.7 |        64.1 |
| image_haiku     |              100   |          99.5 |             100   |            92.7 |             100 |            99.4 |        99.3 |
| image_gemini    |              100   |         100   |              88.2 |            92.7 |             100 |            92.2 |        97.3 |
| image_qwen3vl8b |               92.5 |          40.6 |             100   |            58.5 |             100 |            96.4 |        77.4 |

## By test type (%)

| pipeline        |   absent |   present |   table |
|:----------------|---------:|----------:|--------:|
| text_layer      |     70.6 |      69.9 |     0   |
| tesseract       |     58.8 |      70.9 |     0   |
| tesseract_haiku |    100   |      68.4 |    59.2 |
| image_haiku     |    100   |      98.2 |   100   |
| image_gemini    |     88.2 |      94.3 |   100   |
| image_qwen3vl8b |    100   |      89.4 |    67.4 |

## By page (%)

| pdf                 |   image_gemini |   image_haiku |   image_qwen3vl8b |   tesseract |   tesseract_haiku |   text_layer |
|:--------------------|---------------:|--------------:|------------------:|------------:|------------------:|-------------:|
| 060724V000_p11.pdf  |            100 |           100 |               100 |          10 |                10 |           10 |
| 080290V000_p15.pdf  |            100 |            99 |                 4 |           0 |                 1 |            1 |
| 10125120_p493.pdf   |            100 |           100 |               100 |          79 |                88 |           67 |
| 1083928_p73.pdf     |            100 |            99 |                91 |          61 |                72 |           14 |
| 1083948_p21.pdf     |             95 |           100 |               100 |         100 |               100 |          100 |
| 35049CV000A_p12.pdf |            100 |           100 |                81 |           6 |               100 |            6 |
| 35053CV000A_p11.pdf |            100 |           100 |               100 |          12 |               100 |           12 |
| 39151CV001C_p49.pdf |            100 |           100 |               100 |           2 |                19 |            4 |
| 45061CV000A_p10.pdf |            100 |           100 |               100 |           9 |               100 |            9 |
| 5063304_p51.pdf     |             73 |            73 |                 9 |         100 |                64 |           91 |
| 51005CV000A_p16.pdf |            100 |           100 |               100 |           7 |               100 |            2 |
| 510218V000_p8.pdf   |            100 |           100 |               100 |          29 |               100 |           14 |
| 5239714_p10.pdf     |            100 |           100 |               100 |         100 |               100 |          100 |
| 5507271_p114.pdf    |            100 |           100 |                56 |           6 |                 6 |          100 |
| 5533698_p72.pdf     |            100 |           100 |               100 |          94 |                88 |           81 |
| 5777799_p77.pdf     |             76 |           100 |               100 |          55 |                40 |           97 |
| 6613275_p204.pdf    |            100 |           100 |               100 |         100 |               100 |          100 |
| 6623512_p42.pdf     |            100 |           100 |               100 |          95 |               100 |           95 |

## Model calls

| pipeline        |    usd |   seconds_per_page |   failed_pages |
|:----------------|-------:|-------------------:|---------------:|
| image_gemini    | 0.0761 |             6.9235 |              0 |
| image_haiku     | 0.0225 |             7.429  |              0 |
| image_qwen3vl8b | 0.0305 |            69.746  |              0 |
| tesseract_haiku | 0.0233 |            12.6403 |              0 |

Person check: not yet checked.
