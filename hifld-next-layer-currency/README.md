# How current is the infrastructure data the country plans with?

[HIFLD Next](https://hifld.publicenvirodata.org) preserves the federal HIFLD Open layers (hospitals, power
plants, dams, schools, shelters, the flood map) that planners and utilities used until DHS shut HIFLD Open
down on 26 August 2025. This spike measures how old the data in every layer is, and whether the agency
behind it has published something newer since. Issue: #171.

Everything is in one [marimo](https://marimo.io) notebook, [`layer_currency.py`](layer_currency.py), which
reads top to bottom: the catalog, which columns hold dates, reading them, one row per layer, the age shares,
the source checks, the stalest climate-risk layers, and what it can't show.

## Run it

```bash
./run.sh
```

It needs [uv](https://docs.astral.sh/uv/) and internet access, and no key or account. It runs the notebook as
a script (about a minute) and writes:

- `outputs/layer_currency.csv`: one row per layer (330): category, agency, metadata date, the record-date
  column used with its 10th percentile, median and newest value, the best date and how it was found, a flag
  where it couldn't be, and for the 73 checked layers the current source, its date read this run, the gap in
  years and both verdicts;
- `outputs/summary.json`: every number below;
- `outputs/last-run.txt`: the run's printed output.

`uv run marimo edit layer_currency.py` opens it with its tables. `AS_OF=YYYY-MM-DD` changes the date ages are
measured from.

## Where the data comes from

All public, read at run time:

- **HIFLD Next's [STAC API](https://hifld.publicenvirodata.org/stac)**: 526 collections (one per file and
  version), keeping the newest version of each file: 330 layers in 525 files. Each carries the agency, the
  source's `issued`/`modified` dates from the old HIFLD inventory, and its column schema. Categories come from
  `/api/collections/hifld/datasets`. The catalog has 330 layers, not the "400+" the issue expected.
- **The GeoParquet files**: [DuckDB](https://duckdb.org) reads only the date columns over HTTPS: 291 columns,
  111 MB of the catalog's 118.5 GB, in about 40 seconds.
- **Source agencies' current publications**, in [`source_checks.csv`](source_checks.csv): for each checked
  layer, a URL and a regular expression for its date, found starting only from the layer's own metadata
  (agency, office, title, URLs in its description). The notebook re-reads every URL each run; all 59 read in
  our final run. This copies the approach of `rescued-data-currency/`.

We checked the 33 layers that matter most for hazard and climate risk, plus 40 of the other 297 drawn with
seed 171.

## Results

From the run of 2026-10-31 (`./run.sh` from a clean checkout; numbers from `outputs/summary.json`). Cost $0.

**How old the newest data is.** Every layer is over a year old by now, because the copies stopped at the
shutdown. The sharper measure is how old the data already was on the day HIFLD Open went dark:

| | layers | newest data >1 y old at shutdown | >3 y | >5 y today | median age today |
|---|---|---|---|---|---|
| All layers | 330 | 47% | 22% | 15% | 2.1 y |
| Dated from their own records | 171 | 68% | 36% | 25% | 2.7 y |
| Climate-risk layers | 33 | 45% | 18% | 9% | 2.1 y |

The newest record flatters a layer. In **129 of the 171** record-dated layers, the *median* record was more
than five years old at shutdown: transmission lines' typical `SOURCEDATE` is 2016, the flood map's
`BASE_DATE` 2007, power plants' 2019.

By category, the oldest are Energy (41% over 3 years at shutdown), Borders (39%) and the USACE inland charts
under Transportation Water (28%). Natural Hazards (6%) and Boundaries (12%) are the freshest. Full table in
the notebook and `summary.json`.

**Has the source published something newer?** Of the 73 checked layers, 59 still have a current public
source. Of those, the source has published something newer for **41 (69%)** by our vintage call, or 43 (73%)
by date alone. Where it's newer, the **median gap is 1.3 years**. For the climate-risk layers it's 16 of 22
by vintage (73%), median gap 1.4 years.

**14 layers have no current public source: 11 of the 33 climate-risk layers.** No current federal source
publishes the layers ORNL and contractors built for HIFLD: hospitals, trauma levels, nursing homes,
child-care centers, local law enforcement, mobile-home parks, prisons and local EOCs. The same goes for
transmission lines and electric retail service territories. VA facility locations are now only behind a
keyed API. The national map of the grid's lines now exists only as frozen copies.

**The ten stalest climate-risk layers** (newest data, and whether a newer source exists):

| layer | newest data | newer source? |
|---|---|---|
| VHA medical facilities | 2007-10 | only behind a keyed VA API |
| Local emergency operations centers | 2009-11 | none |
| Local law enforcement | 2019-06 | none |
| Nursing homes | 2022-05 | none |
| Colleges and universities | 2022-07 | yes, NCES EDGE 2025-26 |
| Child-care centers | 2022-08 | none |
| ICIS wastewater treatment plants | 2022-11 | no (EPA republished the same data) |
| Landslide regions | 2023-12 | no (USGS v3.0, Feb 2025) |
| Dialysis centers | 2024-01 | yes, Healthcare Ready, 2026-06 |
| Public schools | 2024-03 | yes, NCES 2024-25 |

**No usable record date: 159 layers.** 154 have no date column at all (census geography, most boundary
layers, the flood map's non-panel layers), 4 have one that is empty or holds non-dates (`TIME_ERUPT` holds
codes like `D1`), and one (census block groups) has no metadata date either. These are dated by metadata
only, which is weak (see below).

**Verdict on the argument.** Partly right. A large share of layers was years old before it was frozen, and
seven in ten sources have moved on since, with nothing in HIFLD Next telling a user which. But the
climate-risk layers are *not* older than the rest. The real problem for climate risk is different: a third
of those layers have no current publisher at all.

## What didn't work, and what it doesn't show

- **Two ways to call "newer" disagree on 8 layers.** The date rule compares the source's date with the
  layer's best date. The vintage call is ours, made by hand, comparing what the source publishes with what
  the copy holds. They differ where a date isn't a release date: NCES labels files by school year, a BTS
  layer was re-edited in 2024 but holds 2020 data, and a NOAA item edit isn't new boundaries. We report both.
  The script flags any source whose date moves after we recorded it.
- **Metadata dates are weak.** 380 of 525 files have a `modified` date in 2025, mostly HIFLD's spring 2025
  re-publication. For the 158 layers dated only that way, the age is a floor, not the data's age.
- **Some sources' dates are edit dates.** ArcGIS `lastEditDate` also moves on a full overwrite with
  unchanged data (EPA's ICIS layer is one), and USACE chart dates are per-feature source dates.
- **Year-only source dates count as 1 January**, so gaps are understated, never overstated.
- **Record dates after the shutdown were dropped** from rescued copies: 457 FRS `LAST_REPORTED_DATE`
  values dated after 26 August 2025, for example, are scheduled dates or errors, not records.
- **Layers HIFLD Next doesn't have aren't measured.** Electric substations moved to HIFLD Secure before
  2025 and aren't in the catalog.
- **We looked for an existing tool first.** HIFLD Next's catalog and MCP server expose dates but no currency
  measure. Data.gov's harvest dates are metadata, not data. So the date reading is DuckDB SQL, and the
  source checks are a CSV of URLs and patterns.
