| Pipeline | Values right | Accepted without review | Wrong but accepted | Sent to review | Cost per document | Cost per page | Seconds per document (Docling + model) | Failed documents |
|---|---|---|---|---|---|---|---|---|
| *K-1 spike, Gemini 3.8 Flash (from its README, run 2026-10-18, all its review rules)* | *676 of 676* | *652* | *0* | *24* | *$0.0064* | | *8.3 + 11.8* | *0* |
| A. VLM alone, whole PDF | 669 of 676 | 651 | 6 | 25 | $0.0086 | $0.0044 | 0.0 + 16.6 | 0 |
| B. Docling Markdown, then the model (text only) | 389 of 711 | 679 | 299 | 32 | $0.0159 | $0.0081 | 14.3 + 21.2 | 0 |
| C. Docling finds the page, the VLM reads its image and Markdown | 658 of 676 | 652 | 18 | 24 | $0.0089 | $0.0045 | 14.3 + 11.3 | 0 |
