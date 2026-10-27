| Pipeline | Values right | Accepted without review | Wrong but accepted | Sent to review | Cost per document | Cost per page | Seconds per document (Docling + model) | Failed documents |
|---|---|---|---|---|---|---|---|---|
| *K-1 spike, Gemini 3.8 Flash (from its README, run 2026-10-18, all its review rules)* | *676 of 676* | *652* | *0* | *24* | *$0.0064* | | *8.3 + 11.8* | *0* |
| A. VLM alone, whole PDF | 668 of 676 | 652 | 7 | 24 | $0.0087 | $0.0044 | 0.0 + 15.6 | 0 |
| B. Docling Markdown, then the model (text only) | 393 of 709 | 679 | 296 | 30 | $0.0127 | $0.0064 | 19.2 + 11.2 | 0 |
| C. Docling finds the page, the VLM reads its image and Markdown | 658 of 676 | 652 | 18 | 24 | $0.0091 | $0.0046 | 19.2 + 10.6 | 0 |
