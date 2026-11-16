# HIFLD Next against OpenStreetMap, Overture and the official registries

Two marimo notebooks on five [HIFLD Next](https://hifld.publicenvirodata.org) point layers (hospitals, fire/EMS,
law enforcement, public schools, power plants; 201,013 records in the 50 states and DC):

- [`crosswalk.py`](crosswalk.py), issue [#91](https://github.com/fulton-ring/agent-content-demos/issues/91): can each
  record be matched to OSM and Overture, so it gets a GERS ID? (Yes for 75%; details below.)
- [`registries.py`](registries.py), issue [#100](https://github.com/fulton-ring/agent-content-demos/issues/100):
  which records should be **added, removed, retyped or moved**, judged against the official registries (CMS, NCES,
  EIA), with every disagreement sent to a person in a review queue instead of decided automatically.

`shared.py` holds what both use (downloads, HIFLD loading, OSM via QLever, Overture via DuckDB, name matching).

## How to run it

```bash
./run.sh               # needs uv; both notebooks. First run ~45 min (Overture buildings and places from S3), then ~3 min
./run.sh --registries  # registries.py only (~7 min first run, 90 s after)
./run.sh --chips       # also draws the aerial-imagery chips behind both hand checks (data/, not committed)
```

Read either as a notebook with `uv run marimo edit registries.py`. Downloads go to `data/`, results to `output/`.
`crosswalk.py` needs about 12 GB of free memory; `registries.py` about 3 GB. Run them one at a time.

## The data (all public, fetched at run time)

| Source | What | Version | Licence |
|---|---|---|---|
| HIFLD Next | the five layers, via its STAC API | release `1704edb3` | public domain (US government) |
| [CMS Provider of Services](https://data.cms.gov/provider-characteristics/hospitals-and-other-facilities/provider-of-services-file-hospital-non-hospital-facilities) | hospitals (13,598, 7,033 active) and the iQIES file of other providers | 2026 Q3 | public domain (US government) |
| [NCES CCD](https://nces.ed.gov/ccd/files.asp) + [EDGE](https://nces.ed.gov/programs/edge/Geographic/SchoolLocations) | school directory and status; school coordinates | 2025-26 preliminary; EDGE 2024-25 | public domain (US government) |
| [EIA-860](https://www.eia.gov/electricity/data/eia860/) | plants with coordinates; generator status | 2025 (Sept 2026) | public domain (US government) |
| [USFA fire department registry](https://apps.usfa.fema.gov/registry/download) | station list (coverage count only) | live | US government |
| [Census batch geocoder](https://geocoding.geo.census.gov/geocoder/) | coordinates for CMS hospital addresses | Public_AR_Current | free public service |
| OpenStreetMap via [QLever](https://qlever.dev) | same-kind features, plus `disused:`/`abandoned:` ones | planet 2026-09-21 | ODbL 1.0 |
| [Overture Maps](https://docs.overturemaps.org/) | places (all categories), infrastructure, buildings | 2026-09-23.0 | places CDLA-Permissive 2.0; buildings ODbL |
| [NAIP](https://planetarycomputer.microsoft.com/dataset/naip) via Planetary Computer | dated aerial imagery for the hand check | 2014–2025 | public domain (USDA) |

**Fire/EMS and police have no official registry with locations.** The USFA registry is voluntary and lists 8,092
stations from 2,891 departments, with addresses and no coordinates (HIFLD has 51,930 stations). BJS's 2018 law
enforcement census is agency-level and sits behind an ICPSR sign-in. For those two layers OSM and Overture are
the reference, as in #91.

## registries.py: method

- **Link** each record to its registry entry: by ID for schools (`NCESID`) and plants (`PLANT_CODE`); by name and
  street address for hospitals (no CMS ID in HIFLD), preferring an active CCN over a terminated one.
- **Propose** from the registry: no entry or closed/terminated/retired/cancelled → *remove*; another provider
  type (iQIES nursing home, surgery centre, clinic; a vet by name; another NCES school type) → *retype*; active but
  more than 250 m away → *move*; else *keep*. Active registry facilities with no HIFLD record → *add*.
- **Agree or review.** The open maps vote: a same-name OSM or Overture feature within 250 m (same kind or, as the
  issue asks, an Overture place of any category), or a same-kind one within 50 m. A proposal the maps agree with is
  final; every disagreement goes to `output/review_queue_<layer>.csv` with a reason code, what each source says,
  distances, links (OSM, registry, NAIP and Esri Wayback) and empty `reviewer_decision`/`reviewer_note` columns.
  Filled copies placed in `review/` are read back on the next run and leave the queue.
- **Hand check**: a seeded sample of 50 removals, 50 adds, 25 keeps and 25 moves per layer, drawn on the latest
  and earliest NAIP images (dates stamped on each chip), labelled by subagents who saw only the chip, the name and
  the kind, not the proposal: present / looks disused / absent / unclear (`hand_check_registry.csv`).

## registries.py: results (from one `./run.sh --registries`)

**Proposals** (`output/registry_summary.csv`): agreed by the sources / sent to review.

| Layer | Keep | Remove | Retype | Move | Add | In the review queue |
|---|---|---|---|---|---|---:|
| Hospitals (8,254) | 4,664 / 548 | 172 / 1,580 | 62 / 141 | 0 / 1,087 | 333 / 806 | 4,162 |
| Fire and EMS (51,930) | 44,441 / 0 | 0 / 7,489 | – | – | 1,478 / 0 | 7,489 |
| Law enforcement (23,299) | 21,102 / 0 | 0 / 2,197 | – | – | 1,033 / 0 | 2,197 |
| Public schools (101,279) | 86,137 / 1,777 | 499 / 4,082 | 139 / 16 | 1,355 / 7,274 | 2,250 / 681 | 13,830 |
| Power plants (16,251) | 8,368 / 2,107 | 1,761 / 1,033 | – | 75 / 2,907 | 480 / 806 | 6,853 |

About 34,500 records would need a person; `output/review_reasons.csv` counts them by reason. The biggest piles:
schools whose NCES point is more than 250 m from HIFLD's (6,841 in review; median 1.3 km), fire stations on neither map
(7,339), plants whose EIA point differs (2,840, mostly solar and wind farms, coded separately), and records the
registry calls closed that the maps still show (1,328 schools, 675 hospitals, 199 plants). 605 hospital records
share a CCN with another record within 250 m: HIFLD v1.1 lists psychiatric and rehab units as separate hospitals.
Hospital addresses go through the live Census geocoder, so hospital counts can move by a few records between runs
(a review rerun got 331 agreed adds against 333).

**Ready to approve** (`output/proposed_changes_<layer>.csv`, agreed adds and removals with registry ID, reason and
source): hospitals 333 adds and 172 removals, schools 2,250 and 499, plants 480 and 1,761, fire/EMS 1,478 adds
and police 1,033 adds (on both OSM and Overture, no HIFLD record within 250 m).

**Hand check** (`output/registry_hand_check.csv`; by reason in `registry_hand_check_by_reason.csv`), all layers:

| List | Checked | Confirmed | Contradicted | Unclear |
|---|---:|---:|---:|---:|
| keep | 124 | 80 (65%) | 6 | 38 |
| move, at the registry point | 74 | 37 (50%) | 20 | 17 |
| add | 213 | 91 (43%) | 38 | 84 |
| remove | 244 | 26 (11%) | 118 | 100 |

Keeps hold up: hospitals 23/25 and schools 22/24 confirmed, none contradicted. School moves are right: 24/25
NCES points sit on the school. Adds: schools 28/47 confirmed, police 24/50 and fire 17/50 (no contradiction,
the rest unclear), power plants only 17/50 (28 show nothing at EIA's point). **Removals mostly can't be confirmed
from above**: 38 of 50 hospital and 37 of 50 school removals show the building standing, and
`registry_closed_but_on_maps` is contradicted 36 times in 44. A closed hospital or school keeps its building, so
imagery tests whether a site exists, not whether it is open. Agreed plant removals (EIA retired or cancelled, on
neither map) are confirmed 9 of 24, contradicted 7.

**How stale** (`output/data_dates.csv`): median HIFLD source date against the registry: schools 1.7 years
(CCD 2022-23 vs 2025-26), hospitals 2.2, plants 5.6, fire/EMS 6.0 (against OSM), law enforcement 18.2 (CSLLEA 2008).

## crosswalk.py (#91) in brief

Match rates within 250 m on either side: hospitals 95%, schools 97%, fire/EMS 76%, police 72%, power plants 66%.
151,339 records (75%) get a high-confidence match and 96–99% of the building layers an Overture building GERS ID.
A hand check of 250 unmatched records estimates about 2,600 stale or misplaced power plant records and about 6,900
fire/EMS stations missing from both maps. Outputs: `match_rates.csv`, `stale_estimate.csv`, `hand_check.csv`,
`crosswalk_hospitals.csv` and the rest of `output/`; method notes are in the notebook.

## What didn't work, and what this doesn't show

- **QLever cuts responses at about 5 MB**, so OSM is now read in pages of 20,000 rows; downloads retry four times.
  A rerun of `crosswalk.py` after moving its helpers to `shared.py` reproduced every committed output byte for byte.
- **16 million Overture places** near our points ran out of memory as one GeoDataFrame. The any-category check
  now pairs points and places in DuckDB on a shared name word and grid cell before scoring names.
- **Census geocoder**: a hand-built multipart upload hung; `requests` with batches of 1,000 works. 677 active CMS
  hospitals didn't geocode and can only be reviewed, so the hospital add sample has 16 records, not 50.
- **Name scoring**: `token_set_ratio` scores 100 when one name is a subset of the other ("Longview" vs "Longview
  Regional Medical Center"), which linked rehab hospitals to their neighbours. Hospital links now average it with
  `token_sort_ratio`.
- **Imagery can't see closure**, and many police and fire checks are unclear (an office in a larger building).
  The labels are AI subagents' calls, blind to the proposal but not spot-checked by a person yet.
- **QLever is live**: a rerun after it moves past the 2026-09-21 planet will drift; the pinned registry URLs won't.
- **Budget**: `registries.py` is about 1,400 lines, over the ~1,000-line target; most is the proposal rules and the
  queue's 45 columns.
- **We propose, we don't upload.** Nothing here edits HIFLD Next or OSM; OSM's
  [import guidelines](https://wiki.openstreetmap.org/wiki/Import/Guidelines) apply to any of it.

## Licences of the outputs

Registry and HIFLD fields are public domain. The review queues, `proposed_changes_*.csv` and the committed
`crosswalk_hospitals.csv` contain OSM IDs, names and distances, so they are Derivative Databases under ODbL 1.0:
© OpenStreetMap contributors, © Overture Maps Foundation, and anything built from them stays ODbL. A file with only
HIFLD ID → registry ID → Overture place GERS ID could go out under CDLA-Permissive 2.0 with attribution.

## What we looked at first

DuckDB httpfs/spatial for Overture, Overpass then QLever for OSM, GeoPandas `dwithin`, rapidfuzz, the Census
geocoder, the Planetary Computer STAC and data API for NAIP (no raster library needed), marimo. Google Maps is out:
its terms bar extracting content, and OSM forbids deriving from it.
