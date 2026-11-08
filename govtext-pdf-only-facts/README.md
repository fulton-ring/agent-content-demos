# Which infrastructure and hazard facts exist only in the federal PDFs archived in 2020?

[GovText](https://source.coop/govscape/eota-ocr) is the public-domain (CC0) text of 9.02 million PDFs from the
2020 End of Term crawl of government websites. Each PDF is read twice: once from the text embedded in the file
(pypdfium2) and once by an OCR model (olmOCR). This spike matches dams, hospitals and power plants from
[HIFLD Next](https://hifld.publicenvirodata.org) to GovText pages. It then counts the facts those pages give about
each facility that the layer doesn't hold, and how many of those facts only the OCR text recovered. Issue: #212.

Everything is in one [marimo](https://marimo.io) notebook, [`pdf_only_facts.py`](pdf_only_facts.py). It reads top
to bottom: the layers, the GovText query, matching, the page sample, the model's fact lists, the comparison with
the layer, the check against page images, and what didn't work.

## Run it

```bash
./run.sh
```

It needs [uv](https://docs.astral.sh/uv/) and internet access. It needs no key, because the model's answers for
the sample are saved in `outputs/model_answers.jsonl`. A run downloads about 0.7 GB of GovText text for 5,000 PDFs
and 60 PDFs for the check (cached in `data/`, which isn't committed). From a clean checkout it takes five to
seven minutes depending on bandwidth (4 min 43 s and 6 min 40 s in two clean runs, with no key set); a rerun with the cache takes under two minutes. It writes:

- `outputs/facts.csv`: one row per fact (896), with the facility's layer and row, the fact type, the quote, the
  model's verdict against the layer record, and whether each text contains the quote;
- `outputs/summary.json`: every number below;
- `outputs/last-run.txt`: the run's printed output;
- `data/hand_check/`: the 60 page images and a checking sheet for the hand check.

`uv run marimo edit pdf_only_facts.py` opens the notebook with its tables. If you change the sample (`DOCS_TO_READ`,
the seed, the matching rule), new pages go to the model and `OPENROUTER_API_KEY` is needed. `MODEL` picks the model
(default `anthropic/claude-haiku-5.5`).

## Where the data comes from

All public, read at run time:

- **HIFLD Next GeoParquet**, read with DuckDB over HTTPS: National Inventory of Dams (92,366 rows), Hospitals
  (8,340) and Power Plants (16,317).
- **GovText on Source Cooperative** (`s3://us-west-2.opendata.source.coop/govscape/eota-ocr`, read over HTTPS).
  GovText has no full-text index. So DuckDB filters the 2020 rows of `cdx/complete_cdx.parquet` (12.96 million
  URLs) to PDFs whose URL mentions dams, levees, spillways, reservoirs, hospitals, power plants, generating
  stations, hydroelectric projects, hazard mitigation plans, emergency action plans or flood insurance studies.
  That gives 16,420 candidate PDFs. We read 5,000 of them, at most 25 per host and drawn with seed 212:
  `ocr_metadata/<id>/metadata.json` for the OCR text and `extracted_text/<id>.tar.gz` for the embedded text.
- **Matching:** each facility's name (at least two words, including a word like dam, hospital or plant) must
  appear on the page together with its state. If several facilities share the name, the page must also name the
  facility's city or county. A National Inventory of Dams ID (such as `WY02950`) is a match on its own.

What we looked at first: the [GovScape](https://govscape.net) search site runs over the same PDFs but has no
documented API, so we query the published files directly. Matching uses
[pyahocorasick](https://pypi.org/project/pyahocorasick/), fact listing uses [Pydantic AI](https://ai.pydantic.dev)
with typed output, quote checks use [RapidFuzz](https://github.com/rapidfuzz/RapidFuzz), and pages are rendered
with [PyMuPDF](https://pymupdf.readthedocs.io).

## Results

From `./run.sh` on a clean checkout, 2026-11-07. Numbers are from `outputs/summary.json`.

**Matches.** 5,000 PDFs and 156,861 pages:

| layer | facilities matched | page matches | PDFs | pages sampled | sampled pages really about the facility |
|---|---|---|---|---|---|
| Dams | 4,830 | 9,648 | 397 | 100 | 85% |
| Hospitals | 2,649 | 16,029 | 900 | 100 | 84% |
| Power plants | 57 | 497 | 47 | 53 | 79% |

**Facts.** The model listed 896 facts about the matched facilities on the 253 sampled pages:

| layer | facts | not in layer | different value in layer | same in layer | OCR-only share of "not in layer" |
|---|---|---|---|---|---|
| Dams | 438 | 165 (38%) | 69 | 204 | 17.6% |
| Hospitals | 287 | 227 (79%) | 13 | 47 | 15.4% |
| Power plants | 171 | 126 (74%) | 16 | 29 | 12.7% |
| All | 896 | 518 (58%) | 98 | 280 | 15.4% |

That is 2.05 facts per sampled page that the layer lacks. By type: operations or services 23%, plans and
projects 14%, finance 13%, identity or contacts 12%, other 11%, events 8%, size or capacity 8%, condition or
inspection 7%, hazard or risk 6%. Most hospital facts are quality and finance figures from state reports. Dam facts
include safety classes, faults under embankments, rehabilitation and breach-scenario results.

**Which text recovered them.** 15.4% of the facts the layer lacks are in the OCR text but not in the embedded text.
Only 6.9% come from pages with no embedded text at all. The rest come from pages whose embedded text is garbled,
or missing the words. That is close to GovText's corpus-wide 12.45% of pages readable only with OCR.

**Hand check against page images** (60 facts the layer lacks: 30 OCR-only, 30 in both texts):

- 90% of the facts are on the page as stated, 98% are about the matched facility, and 78% are substantive (not a
  bare mention, map label or contract boilerplate). 68% pass all three. That puts genuinely new, correct facts at
  about 1.4 per matched page.
- The OCR text was wrong for 4 of the 60 quotes, all of them in OCR-only facts and 3 of the 4 in one scanned
  inventory list. Each one made the model's fact wrong (a wrong street address, a mixed-up table row).
- The embedded text was wrong for 4 of the 30 facts found in both texts: misread characters (`!he`, `14,506,72L`,
  `MAY "66`), or numbers out of reading order in tables.
- Of the 30 OCR-only facts, the embedded text was absent for 24 and wrong for 3. For the other 3 it was actually
  right, so about 1 in 10 "OCR-only" calls is a false alarm.

**Cost and time.** The model calls for the final sample cost $0.24 (253 pages, claude-haiku-5.5 at OpenRouter's
price on the day). Development, including two discarded samples, spent $0.88 in total. The clean run took 4 min 43 s.

## What it shows and doesn't

**Shows:** archived federal PDFs do hold facility facts that the HIFLD layers lack, about 1.4 checked facts per
matched page. About one in seven of them needed OCR. So a next public infrastructure dataset is partly an
extraction job. But mostly it is a job of reading documents with embedded text, and the OCR share is about 15%,
not most of it.

**Doesn't show:** what share of the whole corpus covers these facilities (the pool comes from URL words, not a
text search). It doesn't show whether the facts exist in other datasets (EIA, CMS, the full NID). The answer to
"not in the layer" is a model's comparison against one record. Power plants are thin (57 matched). The hand
check was done by Claude reading page images, not by a person; the labels are in
[`hand_check_labels.csv`](hand_check_labels.csv) with notes, and every page image is rebuilt by a run. Section 9 of
the notebook lists what didn't work.
