# Can we rebuild a national prison boundaries layer from public sources?

Issues [#300](https://github.com/fulton-ring/agent-content-demos/issues/300) and
[#308](https://github.com/fulton-ring/agent-content-demos/issues/308). HIFLD's *Prison Boundaries* layer (Oak Ridge
National Laboratory's polygons of every secure detention facility, federal to county) moved behind DHS's restricted
GII portal, so HIFLD Next can't republish it. This spike rebuilds as much of it as public sources allow and
measures the result against the last public copy.

**Answer: about half of the prisons, and about a fifth of the jails.**
- **Prisons.** The Bureau of Prisons and 46 state corrections lists give 1,092 federal and state facilities.
  We find again 53% of HIFLD's open state and federal records, and 75% of our facilities have an outline (59% from
  OpenStreetMap).
- **Jails.** County and local jails are 65% of the old layer, and no national list of them is public. Twelve
  states publish a jail list. Those lists give 1,000 jails and put one within 1 km of 56% of HIFLD's open county
  and local records in those states. Nationally the jail lists reach 19% of HIFLD's county records, and 22% have
  one of our facilities of any kind within 1 km (`output/jail_coverage.csv`, `output/hifld_coverage.csv`).
- **Open maps.** OSM and Overture alone reach about half of HIFLD's county records, mostly as points rather than
  outlines.

![Facilities by outline source](output/facilities_map.png)

## How to run it

```bash
./run.sh     # needs uv. First run about 24 minutes (state sites and Overture buildings from S3), then seconds
uv run marimo edit rebuild.py   # to read it as a notebook
```

State and jail pages are cached in `data/states/` and `data/jails/`. If a site was down during a run (the log
shows a failed fetch), delete that state's CSV and run again.

Everything is in one marimo notebook, [`rebuild.py`](rebuild.py), which reads top to bottom:
the answer key and state survey; BOP, the state scraper and the jail lists; geocoding, OSM, Overture and matching;
the HIFLD and jail comparisons; the output, the hand check, and what didn't work.

Downloads go to `data/`, results to `output/`. The buildings pass needs about 12 GB of memory. At about 1,300 lines,
the notebook is over the 1,000-line target, because #308 adds the jail lists to the same pipeline rather than
copying it.

## The data (all public, downloaded at run time)

| Source | What | Licence |
|---|---|---|
| HIFLD Prison Boundaries, last public copy via [PASDA](https://mapservices.pasda.psu.edu/server/rest/services/pasda/HIFLD_FEMA/MapServer/131) | answer key only: counted and compared, never copied into our output | ORNL / DHS GMO, HIFLD Open |
| [BOP facility locator](https://www.bop.gov/locations/list.jsp) JSON | 118 federal institutions with coordinates | public domain (US government) |
| State DOC sites and state GIS portals ([`state_sources.csv`](state_sources.csv)) | 974 state facilities | state public records, terms vary |
| State jail lists ([`jail_sources.csv`](jail_sources.csv)): GIS layers (AR, MN, MD, MA, UT, VA), DOC pages (GA, LA), PDFs (PA, TN, KY, CA BSCC) | 1,000 county and local jails | state public records, terms vary |
| [Census geocoder](https://geocoding.geo.census.gov/geocoder/) (batch and one-line) | coordinates for addresses | public domain |
| OpenStreetMap via [QLever](https://qlever.dev) | 3,360 `amenity=prison` features in the US, 2,754 of them polygons | ODbL 1.0 |
| [Overture](https://docs.overturemaps.org/) 2026-10-21.0 places | 4,090 `jail_or_prison` places | CDLA-Permissive-2.0 |
| Overture 2026-10-21.0 buildings | footprints near each facility | ODbL 1.0 |
| Esri World Imagery | hand-check images (not committed) | Esri terms |

The PASDA copy has the same change log ("80 records added, 132 closed, 30 reopened, and 363 removed") as the
Data Rescue Project's copy archived in August 2025. Its latest source date is 2024-08-19.

**Licences per row.** `output/prison_boundaries_rebuilt.parquet` (GeoParquet, not committed) has
`attributes_licence` and `geometry_licence` on every row.
- The 1,451 rows with an OSM or Overture-building outline are ODbL (share-alike).
- The other 641 are points that carry BOP, state or Census terms, or CDLA-Permissive for an Overture name match.
- Publishing ODbL polygons in HIFLD Next is a founder call. `output/facilities.csv` (committed) has no OSM geometry.

## Results (from one `./run.sh`)

**States with a usable corrections list: 46 of 50 plus DC** (`output/scrape_yield.csv`, with a `reason` column).
- **Still unreadable:** NY and RI (Cloudflare) and SD and NH (Akamai) block scripted requests and headless
  Chromium through Playwright; we recorded that and did not work around it. DC describes its two facilities in prose.
- **Added in #308** with three scraper options:
  - AK: 12 of 13 located, from a two-column PDF.
  - CO: 21 rows from Google Maps embed titles; 13 located.
  - HI: 7 of 8 located.
  - KS and WY: rows with only a PO box, placed by an Overture name match.
- One generic scraper, configured by a few columns per state, got at least 80% of the hand count in 38 states.

**Facilities found against HIFLD** (`output/hifld_coverage.csv`; "found" means one of ours within 1 km of the
HIFLD record):

| | HIFLD open records | Ours | HIFLD records found |
|---|---:|---:|---:|
| Federal | 250 | 118 (BOP) | 164 (66%) |
| State | 1,718 | 974 (880 located) | 871 (51%) |
| County | 3,463 | 1,000 from 12 state jail lists (691 located) | 779 (22%) |
| Local | 299 | (same) | 35 (12%) |
| Multi / n/a | 74 | – | 14 |

HIFLD's federal count also includes ICE, US Marshals and contract sites, and its state count includes
juvenile and community-corrections sites. That is why our lists are shorter. Going the other way, 92 to 93% of
our located facilities in each group fall within 1 km of a HIFLD record (`output/rebuilt_on_hifld.csv`).

**State jail lists** (`output/jail_coverage.csv`, `output/jail_yield.csv`):

| State | Jails | Located | With an outline | HIFLD open county + local found |
|---|---:|---:|---:|---:|
| AR, MN, MD, MA, UT, VA (GIS) | 307 | 100% | 99% | 82% |
| GA, LA, PA (addresses) | 301 | 87% | 72% | 65% |
| TN, KY, CA (names only) | 392 | 31% | 29% | 28% |
| All 12 | 1,000 | 69% | 63% | 56% |

- **The GIS layers work.** AR 90%, MD 89%, UT 86%, MN 81%, VA 79%. MA is 73%: its layer has 16 county rows.
- **Name-only lists mostly fail.**
  - Tennessee, Kentucky and California give no addresses. The Overture name match placed 36 of Tennessee's
    110, 52 of Kentucky's 73 and 33 of California's 209 (most of California's are Type I police lockups).
  - The 134 jails the name match did place are right as often as geocoded ones: 95% are within 1 km of a HIFLD
    record.
- **A building fits a jail better than a prison.** Against HIFLD polygons (`output/outline_agreement.csv`,
  median intersection over union), an Overture building scores 0.59 for jails and 0.23 for state prisons. OSM
  scores 0.54 for jails and 0.65 for state prisons.

**Locations.** The sources give coordinates for 649 facilities. The Census geocoder placed 811, an Overture place
name match 229, and 403 stay unlocated (309 of them jails from name-only lists; `output/geocode_summary.csv`).

**Share with an outline** (`output/outline_share.csv`): an OSM `amenity=prison` polygon within 250 m, else an
Overture building within 50 m.

| | OSM polygon | Overture building only | none | not located |
|---|---:|---:|---:|---:|
| BOP (118) | 69% | 3% | 29% | 0% |
| State DOC (974) | 58% | 18% | 15% | 10% |
| State-listed jails (1,000) | 23% | 41% | 6% | 31% |

**Hand check on imagery** (`hand_check.csv`, `output/hand_check_summary.csv`): the same 40 BOP and state
facilities as #300, found by state and name. Reviewers saw only the image and the name. The jails are not
hand-checked.

| Outline | fits | covers part | wrong |
|---|---:|---:|---:|
| OSM prison polygon (20) | 13 | 7 | 0 |
| Overture building (15) | 3 | 6 | 6 |

Only 21 of the 40 points sit on the facility itself. Geocoded points often land on the road outside, which is why
matching allows 250 m.

**What the open maps alone cover** (`output/hifld_coverage.csv`). Of HIFLD's 3,463 open county records, 25% have
an OSM polygon and 45% have an Overture `jail_or_prison` place within 250 m; 53% have either. For the 299 local
records, either one covers 34%.

**Run time and cost.** A run from a clean checkout took 1,433 s (about 24 minutes), and every output file it
wrote matched the committed copies. The Overture buildings pass takes most of that. After that it runs from
`data/` in 11 s. Cost is $0, with no paid services.

## What it doesn't show

- It doesn't show that the rebuilt layer is current. We take each source as published, and HIFLD itself is
  from 2024.
- It doesn't cover juvenile facilities run by separate agencies, ICE or US Marshals detention, private
  contract sites outside the DOC lists, or tribal jails. Jails are covered only in the 12 states with a list.
- Rows aren't all secure facilities. Some are head offices, work camps, release centres or police lockups, as
  each source lists them.
- 40 images is a small hand check, and it covers no jails. The HIFLD comparison is the larger check.
- We looked at the HIFLD Next catalogue and the UCLA COVID Behind Bars facility file (2,296 facilities, with
  coordinates taken from HIFLD) before building. Neither is a public replacement.
