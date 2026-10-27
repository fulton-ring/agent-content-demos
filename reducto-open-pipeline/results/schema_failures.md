| Pipeline | Kind of document | Boxes | Wrong but accepted |
|---|---|---|---|
| A. VLM alone, whole PDF | tuning / real / office scan | 97 | 1 |
| A. VLM alone, whole PDF | tuning / real / born-digital | 97 | 3 |
| A. VLM alone, whole PDF | held out / real / office scan | 97 | 1 |
| A. VLM alone, whole PDF | held out / real / bad scan | 67 | 1 |
| B. Docling Markdown, then the model (text only) | tuning / real / office scan | 104 | 68 |
| B. Docling Markdown, then the model (text only) | tuning / real / born-digital | 100 | 9 |
| B. Docling Markdown, then the model (text only) | tuning / real / bad scan | 33 | 16 |
| B. Docling Markdown, then the model (text only) | tuning / made-up / office scan | 47 | 16 |
| B. Docling Markdown, then the model (text only) | tuning / made-up / clean scan | 50 | 12 |
| B. Docling Markdown, then the model (text only) | tuning / made-up / bad scan | 48 | 18 |
| B. Docling Markdown, then the model (text only) | held out / real / office scan | 101 | 65 |
| B. Docling Markdown, then the model (text only) | held out / real / bad scan | 74 | 52 |
| B. Docling Markdown, then the model (text only) | held out / made-up / office scan | 48 | 17 |
| B. Docling Markdown, then the model (text only) | held out / made-up / clean scan | 53 | 6 |
| B. Docling Markdown, then the model (text only) | held out / made-up / bad scan | 53 | 20 |
| C. Docling finds the page, the VLM reads its image and Markdown | tuning / made-up / bad scan | 48 | 18 |
