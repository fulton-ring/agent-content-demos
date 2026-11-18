# Can we rebuild a national child care facilities layer?

Issue [#301](https://github.com/fulton-ring/agent-content-demos/issues/301). HIFLD's Child Care Centers layer is
frozen (HIFLD Next carries only New York and Washington, from a 2015 ORNL copy), and no federal agency lists
licensed facilities. This spike asks whether **state licensing rosters** give an official base and whether
**OpenStreetMap** and **Overture Places** can fill the gaps.

**Answer: open maps can't, rosters can for about half the states.** 26 of 51 states (with DC) publish a roster a
script can download. In the 13 we compared, Overture finds 36% of licensed centres, OSM 8.5%, both together
40%, and a hand check judged only 80% of those matches to be the same facility. The centres the maps miss are
real. By the issue's own test ("open maps find well under the roster counts"), the idea is wrong: the piece is
about what open maps miss.

Everything is in one marimo notebook, [`child_care.py`](child_care.py). It reads top to bottom: the question,
the roster survey, the open-map counts, the 13-state comparison, the hand check, the combined layer and its
licence, then the answer. [`output/child_care.html`](output/child_care.html) is a static copy with every output.

## How to run it

```bash
./run.sh                          # needs uv; first run ~6 min (Overture scan from S3), later runs ~25 s
uv run marimo edit child_care.py  # to read it as a notebook
```

Downloads go to `data/` and results to `output/` (override with `CHILDCARE_DATA_DIR` / `CHILDCARE_OUTPUT_DIR`).
No keys, no paid services: cost $0. It needs about 3 GB of memory.

## The data (all public, fetched at run time)

| Source | What | Version | Licence |
|---|---|---|---|
| 13 state rosters (CA, DC, DE, MA, MD, MI, NJ, NY + NYC, PA, TN, VT, WA, WI) | licensed centres and homes with coordinates | live, Feb–Nov 2026 | public domain or state open data; VT ODbL, DC CC BY 4.0 (see `rosters.csv`) |
| [Overture Places](https://docs.overturemaps.org/) | `child_care_and_day_care`, `day_care_preschool`, `preschool`, `kindergarten` | 2026-10-21.0 | CDLA-Permissive 2.0 |
| OpenStreetMap via [QLever](https://qlever.dev) | `amenity=childcare`, `amenity=kindergarten` | live planet | ODbL 1.0 |
| [ACF Head Start locator](https://headstart.gov/center-locator) API | open Head Start centres | live | US government |
| Census cartographic boundaries | states, to place every point | 2024, 1:500k | public domain |

[`rosters.csv`](rosters.csv) is the hand survey of all 51 rosters (done 2026-11-18 by three research
subagents, each URL checked with curl): agency, format, download URL, coordinates, update date, terms.

## Results (from one `./run.sh`, 2026-11-18)

**Rosters** (`output/survey_summary.csv`): 26 states publish a machine-readable statewide roster; 18 have
coordinates; 24 were updated in the last year (AZ and MN are stale). 25 are search forms, PDFs or exports
behind a form post or an emailed code. Eight have addresses but no coordinates (CO, CT, FL, ID, IN, MO, SD, TX).

**Counts** (`output/counts_by_state.csv`): nationally Overture has 88,416 child care places (after dropping
2,061 marked closed), OSM 13,691 features, 95,492 together after deduplication, and Head Start 17,137 open
centres. In the 13 roster states the maps hold 38,116 features against 47,669 licensed centres and 29,560
licensed family homes.

**Do the maps find the licensed centres?** (`output/match_rates.csv`, `found_on_either_map.csv`; a match is
within 250 m with names agreeing, or within 50 m, as in `hifld-overture-crosswalk/`):

| | Overture | OSM | Either |
|---|---:|---:|---:|
| Roster centres found | 35.8% | 8.5% | 39.5% (19% VT to 55% DC) |
| Map features that agree with a roster facility | 49.7% | 67.0% | |
| … with a roster facility within 250 m but another name | 22.0% of near ones | 15.8% | |
| … with no roster facility within 250 m | 36.2% | 20.5% | |

**Head Start as a check on the rosters** (`output/head_start_in_roster.csv`): 70% of Head Start centres are in
their state roster; PA (38%) and WA (47%) list fewer, since school-run or federal sites sit outside them.

**Hand check** (`hand_check.csv`, `output/hand_check_summary.csv`; seeded sample of 100, labelled from web
sources by AI subagents who didn't see which group a record came from):

| Group (25 each) | licensed | exempt | closed | unclear |
|---|---:|---:|---:|---:|
| Roster centres on neither map | 24 | 0 | 0 | 1 |
| Agreeing matches (roster record) | 25 | 0 | 0 | 0 |
| Overture-only features | 10 | 1 | 3 | 11 |
| OSM-only features | 10 | 3 | 4 | 8 |

Of the 25 agreeing matches, 20 are the same facility, 4 are a different business at the same address (an old
occupant or a sister programme) and 1 is unclear. The licensed open-map-only finds are mostly family homes,
which California's layer and several others omit.

**Combined layer** (`output/child_care_layer.parquet`, GeoParquet, 163,743 rows, source and licence per row; not
committed): 77,229 roster rows, then 12,826 Head Start centres no roster matches, 68,320 Overture places that
match neither, and 5,368 OSM features that match none. `child_care_layer_no_osm.parquet` leaves OSM out.

## Licence consequences

The rosters and Head Start are public domain or open data, and Overture Places needs only attribution, so a
roster + Head Start + Overture layer can be published under permissive terms (credit Overture, DC and Maryland;
Vermont's roster is ODbL). Adding OSM makes the whole layer an ODbL Derivative Database with share-alike, for
5,368 extra rows (3%). HIFLD Next allows OSM and Overture only after a recorded rights decision: that's a
founder call, and this spike doesn't make it.

## What didn't work, and what this doesn't show

- **Matching overcounts.** The 50 m rule pairs a centre with whatever shares its building, so 4 of 25 checked
  matches were wrong. The real found rate is nearer 30% than 36%.
- **Overture's state is sometimes wrong** (a West Virginia home tagged MD). Every point is placed by the Census
  boundaries instead.
- **Roster type columns differ by state.** *Centre* and *home* are our mapping, in the roster cell. California's
  geocoded layer has no family homes, and NJ and WA publish centres only.
- **State search pages refused scripted access** (403s, CAPTCHAs, Salesforce portals), so the hand check rests on
  third-party directories that copy state data. The labels are AI calls and no person has checked them.
- **catalog.data.gov's CKAN API returned 404**, so the survey used the Socrata discovery API, ArcGIS Online
  and state portals instead. Some rosters may exist that we missed.
- **13 of 26 roster states compared.** The address-only, form and PDF states are sub-issue
  [#310](https://github.com/fulton-ring/agent-content-demos/issues/310).
- **Budget:** the notebook is about 1,100 lines (over the ~1,000 target); half of it is the 13 roster readers.

## What we looked at first

DuckDB httpfs for Overture (as in `hifld-overture-crosswalk/`), QLever for OSM, Socrata and ArcGIS REST for the
rosters, GeoPandas `dwithin`, rapidfuzz, the Head Start locator API (found via its developer guide), and marimo.
Child Care Aware's supply layers and other third-party mirrors were left out because they aren't state sources.
