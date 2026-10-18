# K-1 extraction with a review queue

This demo reads Schedule K-1s and brokerage 1099s and links every extracted value to the box it came from. Anything the software isn't sure of goes to a review queue for a person to check. It answers a sales question for the CPA document extraction play: can we show a tax preparer what they'd get, with screenshots of real sample documents, without them sending us any documents?

It compares five current vision-language models, three of them open-weight, and two OCR models run on Modal's GPUs. They all read the same documents and are scored against the same answer keys. Each model runs on its own, and Gemini 3.8 Flash and Qwen 3.8 27B also run as a pair that must agree. Docling reads the page layout and the supplemental statements. Pydantic AI turns each model's answer into typed values, each with a page, a box and a confidence.

**Read [`notebook.py`](notebook.py)** for the whole story, top to bottom: the documents, each step and why, the review rules, the results, and what didn't work. Open it with `uv run marimo edit notebook.py`, or read it as plain Python.

![A value on a real K-1, highlighted on the page it came from](screenshots/1-value-linked-to-box.png)

## Run it

```
./run.sh               # the whole comparison
./run.sh --screenshots # also retakes screenshots/ from Gemini 3.8 Flash's review screen
```

You need:

- [uv](https://docs.astral.sh/uv/);
- the `tesseract` binary (`apt install tesseract-ocr` or `brew install tesseract`), which Docling uses for scanned pages;
- `OPENROUTER_API_KEY`;
- for the OCR models, `MODAL_TOKEN_ID` and `MODAL_TOKEN_SECRET`. Without them the OCR models are skipped.

For the screenshots, Playwright installs Chromium, or set `CHROMIUM_PATH` to one you have.

`run.sh` runs the notebook as a script (`uv run notebook.py`), so the numbers come from the code you read. uv builds the environment on the first run; Docling brings a CPU build of PyTorch. The notebook downloads the real sample K-1s and the blank IRS forms and checks their hashes. It makes the scanned copies and the made-up documents, runs Docling, runs the five models side by side, pairs two of them, runs the OCR models, and scores everything. It writes:

- `output/comparison.md`: every run, broken down by kind of document;
- `output/<run>/index.html`: each run's review screen;
- `output/<run>/metrics.json`: each run's scores, failed documents and cost.

The model answers are saved under `output/answers/`, and re-running reuses them. Delete that folder to call the models again. Set `K1_OUTPUT_DIR` to write somewhere other than `output/`.

## The documents

- **Three real K-1s (Form 1065)**, the sample packages that Enviva Partners (2018, 2021) and The Blackstone Group (2019) publish for their unitholders. They are downloaded from the issuers' sites at run time, not committed. `real_answer_key.json` is keyed by hand from them.
- **Nine scanned copies** of those K-1 pages, made at run time: office scans and bad scans.
- **Eighteen made-up documents**: 1120-S and 1041 K-1s filled in on the blank IRS forms, and brokerage consolidated 1099s. Every name and amount is invented, and every one is image-only. The generator writes their answer key.

The held-out set is 14 documents whose scans and values come from seeds that weren't used while building the review rules.
