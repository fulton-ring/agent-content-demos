# Rebuilding Reducto's parse and extract with Docling and Gemini

Reducto sells document parsing: *Parse* turns a document into sections, tables and chunks with bounding boxes, *Split* finds the sections of a long file, and *Extract* fills a JSON schema from what Parse saw. Can an open pipeline do the same? Docling or LlamaIndex would handle layout, and a vision language model such as Gemini 3.8 Flash would read the pages. This spike measures that on two tasks with answer keys:

1. **Schema extraction**: the K-1 spike's 30 tax documents and its answer key, read by three pipelines and scored by the K-1 spike's own scoring notebook, so the numbers sit next to its README's.
2. **Section parsing**: five long public reports. Two FEMA Flood Insurance Studies for Henrico County, Virginia, have numbered headings: a scanned typewritten report from 1980 (65 pages) and a born-digital one from 2024 (94 pages). Three have no heading numbers ([#130](https://github.com/fulton-ring/agent-content-demos/issues/130)): a two-column USGS report (78 pages), a scanned 1953 USGS circular (46 pages) and a county budget book (130 pages). A hand-checked key gives their 210 headings, the page each starts on, and nine tables (2,448 cells).

**Read the two notebooks**, each top to bottom. Open one with `uv run marimo edit 1_schema_extraction.py`, or read them as plain Python:

1. [`1_schema_extraction.py`](1_schema_extraction.py): the VLM alone, Docling's text then the model, and Docling routing then the VLM.
2. [`2_section_parsing.py`](2_section_parsing.py): Docling alone, the VLM alone, and Docling then the VLM, on headings, section boundaries and tables.

## Run it

```
./run.sh
```

You need [uv](https://docs.astral.sh/uv/), the `tesseract` binary (`apt install tesseract-ocr` or `brew install tesseract`), `OPENROUTER_API_KEY`, and the K-1 spike's folder next to this one (it's in this repository). `run.sh` first runs the K-1 spike's `1_documents.py`, unchanged and in its own pinned environment, to make the 30 documents. It then runs the two notebooks as scripts, so the numbers come from the code you read. Notebook 1 runs the K-1 spike's `3_results.py`, also unchanged, to score its pipelines. Everything goes to `output/` (set `REDUCTO_OUTPUT_DIR` to write elsewhere). Model answers are saved in `output/answers/` and reused on a re-run; delete that folder to call the model again. A clean run (run 3) took 86 minutes on 4 CPU cores, most of it Docling on the five long reports, and cost $1.99 in model calls ($1.00 for notebook 1, $0.99 for notebook 2).

## Look first: what Reducto documents, and what the open tools cover

- **Reducto** ([docs](https://docs.reducto.ai/overview)). Parse returns chunks of Markdown, each with typed blocks (title, section header, table, figure, key-value) that carry a page, a bounding box and a confidence. Word- and cell-level citations are an option, but they [can't be combined](https://docs.reducto.ai/configs/parse/citations) with joining tables across pages. Split takes plain-language section descriptions and returns page ranges; it "runs Parse … then uses an LLM to classify pages". Extract takes a JSON schema and "can only return what Parse sees". The current parser, r-1, is "one full-page model" that reads "digital text, scans, handwriting". [List prices](https://docs.reducto.ai/reference/credit-usage) per 1,000 pages: Parse $10, Extract $20, Split $20. It publishes no per-page speed, but guarantees 200 to 500+ concurrent pages by tier.
- **Benchmark.** Reducto's [RD-TableBench](https://huggingface.co/datasets/reducto/rd-tablebench) is 1,000 table images with a public answer key. Its licence is CC-BY-NC-ND-4.0, which doesn't fit a commercial blog's demo, and it scores single table images, not long documents or forms, so we built our own keys. Reducto's forms benchmark, RD-FormsBench, was announced but we found no release.
- **Docling** (MIT): layout, reading order, OCR, table structure, section headers, chunking, per-element boxes, and VLM pipelines. **LlamaIndex** (MIT) is the framework and its node parsers; **LlamaParse** is a paid cloud service, so it's out under this repo's rules. **Marker** (code Apache-2.0, weights free only under $5M revenue) and **MinerU** (Apache-2.0 with extra terms) cover the same ground as Docling, with an optional LLM pass. The open **Unstructured** library partitions and chunks by title; its own README puts its table-cell accuracy at 0.43, against 0.87 for its paid API. Each open tool covers layout and tables, none covers schema extraction without a model, and we used Docling because the K-1 spike already does.

## Results

From clean runs of `./run.sh` from a fresh clone: run 2 on 2026-10-26 for the schema and flood-study tables (run 1 earlier that day for comparison), and run 3 on 2026-10-27, which added the three reports without heading numbers, for theirs. All model calls are Gemini 3.8 Flash on OpenRouter at temperature 0.

### Schema extraction, the K-1 spike's 30 documents

| Pipeline | Values right | Accepted without review | Wrong but accepted | Sent to review | Cost per document | Cost per page | Seconds per document (Docling + model) | Failed documents |
|---|---|---|---|---|---|---|---|---|
| *K-1 spike, Gemini 3.8 Flash (from its README, run 2026-10-18, all its review rules)* | *676 of 676* | *652* | *0* | *24* | *$0.0064* | | *8.3 + 11.8* | *0* |
| A. VLM alone, whole PDF | 668 of 676 | 652 | 7 | 24 | $0.0087 | $0.0044 | 0.0 + 15.6 | 0 |
| B. Docling Markdown, then the model (text only) | 393 of 709 | 679 | 296 | 30 | $0.0127 | $0.0064 | 19.2 + 11.2 | 0 |
| C. Docling finds the page, the VLM reads its image and Markdown | 658 of 676 | 652 | 18 | 24 | $0.0091 | $0.0046 | 19.2 + 10.6 | 0 |

"Wrong but accepted" is a wrong value accepted without review, or a box on the key a run never reported. All three pipelines use only the K-1 spike's per-value review rules (confidence, STMT, malformed amounts, unknown or repeated boxes), not its cross-checks or its whole-page check, so the difference between them is the pipeline. The italic row is the K-1 spike's own pipeline with all its rules, from its README.

Run 1 gave the same picture: A 668 of 676 right with 8 wrong but accepted, B 380 of 714 with 313, C 658 of 676 with 18. Run 3: A 669 of 676 with 6, B 389 of 711 with 299, C 658 of 676 with 18. Docling took 19 to 21 seconds a document here, on a busier machine than the K-1 spike's 8.3.

- **Show the model the page.** B, which hands the model Docling's Markdown and no image, let through 296 wrong values (313 in run 1). Nearly all were on scans, where Tesseract's text is all the model gets; on the three born-digital K-1s it got 6 to 9 wrong. A and C, which show the page, got 97 to 99% of values right.
- **Gemini alone on the whole PDF is nearly as good as the K-1 spike's pipeline**, with 7 and 8 wrong values accepted against 0. Every one is on Blackstone's 11-page package and its scans, where it skipped box 7 and coded rows printed as a dash. Docling's job there is to find the page, not to read it.
- **Routing on OCR text fails silently.** C's 18 wrong values are one made-up 1099, in both runs: Docling's OCR missed the form's title on the summary page, C sent the detail page, and every box came back blank. The K-1 spike's whole-page check catches this; C here doesn't have it.

### Section parsing, two flood studies with numbered headings

| Document | Pipeline | Heading recall | Section recall | Level right | Extra headings | Table cells right | Cost per page | Seconds per page (Docling + model) |
|---|---|---|---|---|---|---|---|---|
| fis-henrico-1980 | Docling alone | 23 of 23 | 23 of 23 | 8 of 23 | 13 | 241 of 332 (73%) | $0.0000 | 7.0 + 0.0 |
| fis-henrico-1980 | VLM alone | 23 of 23 | 23 of 23 | 23 of 23 | 0 | 332 of 332 (100%) | $0.0018 | 0.0 + 0.9 |
| fis-henrico-1980 | Docling, then the VLM | 23 of 23 | 23 of 23 | 23 of 23 | 5 | 235 of 332 (71%) | $0.0005 | 7.0 + 0.4 |
| fis-henrico-2024 | Docling alone | 46 of 46 | 46 of 46 | 7 of 46 | 36 | 129 of 255 (51%) | $0.0000 | 7.6 + 0.0 |
| fis-henrico-2024 | VLM alone | 46 of 46 | 46 of 46 | 46 of 46 | 0 | 255 of 255 (100%) | $0.0018 | 0.0 + 0.8 |
| fis-henrico-2024 | Docling, then the VLM | 46 of 46 | 46 of 46 | 46 of 46 | 0 | 255 of 255 (100%) | $0.0009 | 7.6 + 0.4 |

| Document | Table | Docling alone | VLM alone | Docling, then the VLM |
|---|---|---|---|---|
| fis-henrico-1980 | Table 1 - Summary of Discharges | 186 of 192 | 192 of 192 | 192 of 192 |
| fis-henrico-1980 | Table 2 - Manning's "n" Values | 43 of 44 | 44 of 44 | 43 of 44 |
| fis-henrico-1980 | Flood Insurance Zone Data (Table 4 in the contents, printed TABLE 3), James River to North Run | 12 of 96 | 96 of 96 | 0 of 96 |
| fis-henrico-2024 | Table 13: Roughness Coefficients | 99 of 99 | 99 of 99 | 99 of 99 |
| fis-henrico-2024 | Table 22: Summary of Topographic Elevation Data used in Mapping | 30 of 30 | 30 of 30 | 30 of 30 |
| fis-henrico-2024 | Table 23: Floodway Data, Allens Branch | 0 of 126 | 126 of 126 | 126 of 126 |

Run 1 gave the same numbers, cell for cell. A review run on 2026-10-27 differed by one cell: Gemini alone read Deep Run's 0.060 in the scanned Manning's table as -0.060 (331 of 332), and Docling then the VLM read it right (236 of 332). Run 3 repeated the review run (331 and 236 of 332), with 5 extra headings from Gemini alone on the 1980 scan. The speck fools Gemini with or without Docling's text. Docling took 7.0 to 7.6 seconds a page on CPU, with Tesseract on the scan.

- **Every pipeline found every numbered heading on the right page**, on both the scan and the born-digital report. The headings carry their numbers, so this was the easy part; the next section tests reports without them.
- **Docling's outline is flat**: every heading at level 1, plus the cover and contents lines as headings (13 and 36 extras). Giving its Markdown to Gemini fixed every level and most extras, for $0.0005 to $0.0009 a page.
- **Tables are where Docling alone fails.** It merged the 2024 floodway table's 14 rows into one row of whole columns (0 of 126 cells), read the sideways 1980 table as fragments (12 of 96), and glued a footnote marker onto a number (`15,0002` for 15,000 with note 1). Gemini read all 587 cells right from the PDF alone in runs 1 and 2 (586 in the review run and run 3).
- **Docling then the VLM inherits Docling's misses.** Docling's text never names the sideways table, so the pipeline never found its page (0 of 96). On the scanned Manning's table it took Docling's `-0.060` (a speck read as a minus sign) over the page image's 0.060 in runs 1 and 2, though Gemini alone made the same misread in the review run and run 3.

![Docling merges the rows of the 2024 Floodway Data table](screenshots/2024-p55-docling-merges-rows.png)

### Section parsing, three reports without heading numbers

The key's headings are each contents entry, at the level its indentation gives, on the page where the body prints it. "Extra headings" are mostly real sub-headings the contents leaves out, such as "Initiatives" under each budget department.

| Document | Pipeline | Heading recall | Section recall | Level right | Extra headings | Table cells right | Cost per page | Seconds per page (Docling + model) |
|---|---|---|---|---|---|---|---|---|
| usgs-sir-2023-5014 | Docling alone | 48 of 48 | 48 of 48 | 15 of 48 | 26 | 131 of 880 (15%) | $0.0000 | 9.8 + 0.0 |
| usgs-sir-2023-5014 | VLM alone | 48 of 48 | 48 of 48 | 42 of 48 | 11 | 880 of 880 (100%) | $0.0011 | 0.0 + 0.8 |
| usgs-sir-2023-5014 | Docling, then the VLM | 48 of 48 | 48 of 48 | 40 of 48 | 11 | 880 of 880 (100%) | $0.0013 | 9.8 + 0.9 |
| usgs-circ-166-1953 | Docling alone | 27 of 36 | 27 of 36 | 7 of 27 | 10 | 166 of 222 (75%) | $0.0000 | 21.7 + 0.0 |
| usgs-circ-166-1953 | VLM alone | 36 of 36 | 36 of 36 | 36 of 36 | 0 | 222 of 222 (100%) | $0.0010 | 0.0 + 0.8 |
| usgs-circ-166-1953 | Docling, then the VLM | 36 of 36 | 36 of 36 | 36 of 36 | 0 | 146 of 222 (66%) | $0.0019 | 21.7 + 0.4 |
| lewis-county-budget-2026 | Docling alone | 55 of 57 | 55 of 57 | 14 of 55 | 83 | 759 of 759 (100%) | $0.0000 | 12.4 + 0.0 |
| lewis-county-budget-2026 | VLM alone | 57 of 57 | 57 of 57 | 57 of 57 | 62 | 759 of 759 (100%) | $0.0010 | 0.0 + 0.6 |
| lewis-county-budget-2026 | Docling, then the VLM | 56 of 57 | 56 of 57 | 56 of 56 | 67 | 0 of 759 (0%) | $0.0009 | 12.4 + 0.2 |

| Document | Table | Docling alone | VLM alone | Docling, then the VLM |
|---|---|---|---|---|
| usgs-sir-2023-5014 | Table 5 - Regional regression equations and performance metrics (sideways, 4 pages) | 131 of 880 | 880 of 880 | 880 of 880 |
| usgs-circ-166-1953 | Table 6 - Logs of wells, wells 24-47-1db to 25-47-6ba | 166 of 222 | 222 of 222 | 146 of 222 |
| lewis-county-budget-2026 | Department of Social Services accounts (3 pages) | 759 of 759 | 759 of 759 | 0 of 759 |

- **Gemini alone found every heading on the right page** in all three, including the 1953 scan's run-in headings ("Chadron formation.--The ...") and the five budget departments the contents puts a page early. It read all 1,861 keyed cells, including a four-page table printed sideways.
- **Levels are where it slipped, on the two-column report.** It put 6 of 48 headings one level off (5 in a first run), nesting "Rainfall" under "Climate" by meaning although the report sets them in the same type. Docling then the VLM got 8 wrong (11 in the first run); a review run had 9 for Gemini alone and 6 for Docling then the VLM, so neither is reliably better. On the scan's five levels shown only by capitals, centring and underlines, both got all 36 right. In the review run, Docling then the VLM also nested 14 of the budget's 16 top-level headings one level too deep (42 of 56), so level accuracy varies from run to run.
- **Docling alone missed 9 of the scan's 36 headings**, mostly run-in ones, and still put almost every heading at level 1. It read the budget table perfectly from the text layer, but only 131 of 880 cells of the sideways table.
- **Routing on Docling's text missed whole pages of tables.** The budget table's title is split across two of Docling's header cells, so the page finder found no page and the model returned nothing (0 of 759). On the scan, Docling's OCR never found the title on the table's second page, so that page's 37 rows were lost (146 of 222, since best-row matching still credits some of their cells to look-alike rows). Neither failure shows up as an error.

## Failure types, and what would fix each

| Failure | Seen in | Fix |
|---|---|---|
| Text loses the form's grid and OCR misreads digits on scans | Schema B | Show the VLM the page image. Not a layout-tool or fine-tuning problem |
| Routing on OCR text picks the wrong page, and blanks are accepted | Schema C; sections, Docling then VLM, on the sideways table | Let the VLM pick the page, or add the K-1 spike's whole-page check |
| VLM skips rows when given a long package | Schema A, Blackstone | Less context, not more: send the form's page only |
| Rows merged in a table without rules | Sections, Docling alone | VLM on the page image; or fine-tune the table model (below) |
| Sideways pages unreadable | Sections, Docling alone and Docling then VLM | VLM on the page image, which reads it as printed |
| Flat heading levels, cover and contents lines as headings | Sections, Docling alone | Prompting: give Docling's Markdown to an LLM |
| A speck on a scan read as a minus sign (`-0.060`) | Sections, Docling then VLM in runs 1 and 2; VLM alone in the review run | A check that flags signs that don't fit the column, or review on low confidence |
| Footnote marker glued to a number | Sections, Docling alone | VLM, prompted to leave out footnote markers |
| Table title split across Docling's cells, or missed by its OCR, so a page or the whole table is never sent | Sections, Docling then VLM, budget and 1953 scan | Let the VLM find the pages, or check the rows returned against the pages the table spans |
| Headings nested by meaning, not by type | Sections, VLM alone and Docling then VLM, two-column report | Ask for levels from the type, or check them against the contents page |
| Run-in headings ("Chadron formation.--The ...") missed | Sections, Docling alone, 1953 scan | VLM on the page image |

## Where fine-tuning would earn its cost

Nothing we measured needed fine-tuning a frontier VLM. Every error Gemini made was fixed by changing what it was shown (one page instead of 11; the image instead of OCR text) or by a check behind it. Fine-tuning earns its cost in three places:

- **When the model has to be open weights, or run on our own hardware.** The K-1 spike's open models shifted values between boxes (Gemma 4 31B accepted 197 to 278 wrong values a run). That's the error a fine-tune on a few hundred labelled form pages fixes, and a bigger open model only partly fixes (Qwen3-VL 235B: 3 to 29).
- **When pages can't go to a VLM at all**, for cost at volume or privacy. Then Docling's table model is the reader, and its row merging on ruleless numeric tables is a training-data problem: fine-tuning its table model on a few hundred such pages is the fix.
- **At volume, on cost.** Gemini cost $0.0018 a page for section parsing and $0.0044 for schema extraction. A small fine-tuned model could cut that, but only after a pipeline like this one has produced the labels.

## The case against: what Reducto does that this pipeline doesn't

- **Speed.** Docling took 7 seconds a page on 4 CPU cores, and Gemini about 1 second a page. Reducto sells 200 to 500+ concurrent pages; at scale we'd need GPUs and our own queueing and rate-limit handling.
- **Citations we can trust.** Reducto returns word- and cell-level boxes from the page. Gemini's boxes are its own claim, and we didn't check them. Docling's boxes are real, but they belong to Docling's text, not to the VLM's values.
- **Tables across many pages.** Gemini joined tables of up to four pages right, one printed sideways. We didn't test the 2024 study's 9-page and 32-page tables, which Reducto offers to merge.
- **Handwriting and stamps.** None of our documents have them; Reducto says r-1 reads handwriting.
- **Reliability at volume.** Two runs here, each with a run-to-run spread on the K-1 set, rate limits, and a hosted model that changes under us. Reducto adds SLAs, SOC 2, a BAA and zero data retention.
- **Cost doesn't favour Reducto.** At list price, Parse is $0.010 a page and Extract $0.020. Gemini was $0.0018 to $0.0064 a page here, before our own engineering time.

## Verdict

**Yes, for what we measured.** Gemini 3.8 Flash given the whole PDF found all 69 numbered headings on the right page and read 586 to 587 of 587 table cells right, on a 1980 scan as well as a 2024 born-digital report, for $0.0018 a page. On the K-1 set it accepted 7 or 8 wrong values of 676 when given whole packages, and the K-1 spike's routed pipeline accepted none in its README's run (0 to 2 in each of its 11 runs). For public-records extraction an open pipeline is good enough, with two rules. The VLM reads the page image, never OCR text. And whatever routes pages to it is checked. Docling earns its place as a router and a source of real boxes, not as the reader. Section parsing was not the hard part we expected, with or without heading numbers: on three reports without them ([#130](https://github.com/fulton-ring/agent-content-demos/issues/130)) Gemini alone found all 141 headings on the right page and read all 1,861 keyed cells, and its only slips were heading levels (5 to 9 on the two-column report). We found no error that needs fine-tuning a frontier VLM. Fine-tuning earns its cost only when the model must be open weights or run on our own hardware.

## What it doesn't show

- **Two runs aren't an error rate.** The K-1 spike saw Gemini's misreads come and go between runs; these two runs can't pin down any pipeline's rate.
- **Three reports without heading numbers are a small sample**, and the key's headings are the contents' entries, so headings left out of the contents aren't scored. The extra-headings count is not precision.
- **The longest keyed table is four pages.** The scan's Table 6 runs seven pages and is keyed for its first three; the 2024 study's 32-page Table 23 isn't tested. No table changes columns between pages, and there's no handwriting.

## Files

The two notebooks; `model_call.py`, one typed, cost-counted, saved model call that both use; `section_key.json`, the hand-checked key for the five reports; `run.sh`, `pyproject.toml` and `uv.lock`, the one command and its pinned environment; `results/`, the result tables from run 3, copied from `output/`; and `screenshots/`, crops of report pages with Docling's output.
