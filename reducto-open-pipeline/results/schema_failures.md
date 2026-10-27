| Pipeline | Kind of document | Boxes | Wrong but accepted |
|---|---|---|---|
| A. VLM alone, whole PDF | tuning / real / office scan | 97 | 2 |
| A. VLM alone, whole PDF | tuning / real / born-digital | 97 | 3 |
| A. VLM alone, whole PDF | held out / real / bad scan | 67 | 2 |
| B. Docling Markdown, then the model (text only) | tuning / real / office scan | 104 | 68 |
| B. Docling Markdown, then the model (text only) | tuning / real / born-digital | 99 | 9 |
| B. Docling Markdown, then the model (text only) | tuning / real / bad scan | 37 | 20 |
| B. Docling Markdown, then the model (text only) | tuning / made-up / office scan | 47 | 12 |
| B. Docling Markdown, then the model (text only) | tuning / made-up / clean scan | 51 | 13 |
| B. Docling Markdown, then the model (text only) | tuning / made-up / bad scan | 49 | 20 |
| B. Docling Markdown, then the model (text only) | held out / real / office scan | 102 | 64 |
| B. Docling Markdown, then the model (text only) | held out / real / bad scan | 69 | 50 |
| B. Docling Markdown, then the model (text only) | held out / made-up / office scan | 47 | 15 |
| B. Docling Markdown, then the model (text only) | held out / made-up / clean scan | 51 | 6 |
| B. Docling Markdown, then the model (text only) | held out / made-up / bad scan | 53 | 19 |
| C. Docling finds the page, the VLM reads its image and Markdown | tuning / made-up / bad scan | 48 | 18 |
