# Rebuilding Virginia's data-center generator dataset from the air permits

**Status: in progress, blocked on getting the permit PDFs (see issue #189).** Only the first notebook exists.

The question: can a vision model read Virginia DEQ's air permits for data centers as accurately as the
[Better Data Center Project](https://github.com/jsbangsund/data-center-generator-permits) did by hand, and then
extend their dataset with the permits DEQ issued in 2026?

## Run it

```
./run.sh
```

You need [uv](https://docs.astral.sh/uv/). Outputs go to `output/` (or `VA_OUTPUT_DIR`).

## The data

- **Answer key:** `data/air_permits_VA.csv` from the Better Data Center Project, by John Bangsund and Catherine
  Casomar, CC-BY-4.0, pinned to commit `9a494e2` (2026-03-04). Downloaded at run time, not committed.
- **Permits:** DEQ's [Issued Air Permits for Data Centers](https://www.deq.virginia.gov/news-info/shortcuts/permits/air/issued-air-permits-for-data-centers)
  page and the permit PDFs it links. Not yet downloaded: www.deq.virginia.gov answers 403 to every request from the
  cloud environment our workers run in.

## What we have so far

From `1_answer_key.py`: 821 equipment rows across 173 permit registrations. The fields we score are filled on
647 (operating hours) to 821 (unit count, kWe) rows. 51 rows across 21 permits carry `possible_issues` notes.
524 of the 821 rows come from permit documents dated 2023 to 2025.

Tier is out of scope: the authors describe it as a best guess, not a printed value.
