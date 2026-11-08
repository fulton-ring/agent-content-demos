# Which live EPA pages still send readers to the archive EPA retires on December 31?

EPA says it retires `archive.epa.gov` on December 31, 2026. Our earlier spike
([`epa-archive-datasets/`](https://github.com/fulton-ring/agent-content-demos/pull/229), issue
#217) looked inside the archive. This one looks at it from EPA's current site. We crawled every
page in www.epa.gov's sitemap, collected every link into the archive, followed page links one
step to the data files they list, and checked each file for a live copy elsewhere.

Issue: [#233](https://github.com/fulton-ring/agent-content-demos/issues/233).

## Run it

```bash
./run.sh
```

You need [uv](https://docs.astral.sh/uv/) and network access. The first run crawls all 73,974
sitemap pages politely: 6 requests at a time, a 0.5 s pause per worker after each request, robots.txt
respected, at most 3 tries per page. It took 2 h 28 min (18:14 to 20:42 UTC, 2026-11-08) and
downloaded 4.6 GB, none of it kept. Pages are recorded in `cache/pages.jsonl`, so a stopped run
resumes, and reruns take under a minute. To try it quickly on a seeded sample, run
`EPA_PAGE_CAP=2000 ./run.sh` (about 3 minutes; small samples may find no data files). Counts then cover the sample, not the site.
To read the walkthrough with its tables, run `uv run marimo edit epa_live_archive_links.py`.

Settings come from environment variables: `EPA_PAGE_CAP` (default 80000, above the sitemap's size),
`EPA_WORKERS` (6, at most 8), `EPA_DELAY` (0.5 s, at least 0.2), `EPA_SEED` (233),
`EPA_HAND_CHECK_SIZE` (30), `EPA_CACHE_DIR`, `EPA_OUT_DIR` and `EPA_PARENT_OUTPUTS_URL` (where
#217's `data_files.csv` and `catalog.json` are read from).

## Where the data comes from

Everything is fetched at run time from public sites: www.epa.gov's sitemap and pages,
archive.epa.gov, EPA's three `19january20XXsnapshot` sites, the data.gov catalog search, and
#217's published outputs. The only things committed are the result tables in `outputs/` and the
hand-check sheet `hand_check.csv`.

## Results (run of 2026-11-08)

The numbers come from `outputs/last-run.txt` and the CSVs next to it.

**Crawl.** 73,974 sitemap pages, all allowed by robots.txt. 73,746 returned 200. The 228 that
didn't are EPA's staff-only sections (`webcmstraining`, `webguide`, `web-analytics`, returning 403
or 401) and two pages that returned 503 (`outputs/pages_not_reached.csv`).

**Links into the archive.** 804 live pages (1.1%) link into the archive, with 1,896 links to 1,488
distinct addresses. Every link sits in the page's own content, none in site navigation.

| kind | links | distinct targets | live pages |
|---|---:|---:|---:|
| archived page | 1,436 | 1,185 | 619 |
| PDF | 290 | 286 | 39 |
| archive home page ("Search EPA Archive") | 155 | 2 | 153 |
| other (images, one video) | 15 | 15 | 9 |
| **data file** | **0** | **0** | **0** |

**No live page links straight to a data file in the archive.** The page links go mostly to old
news releases, enforcement cases and EPA history (`history` 403 links, `enforcement` 330,
`agriculture` 131). One page, the Enbridge Michigan oil spill page, accounts for 211 of the
290 PDF links. The 153 archive-home links are the NAEMS pattern: the live page tells readers to
search the archive for the material, which can't be followed to particular files.

**One step in.** Of the 1,185 archived pages that live pages link to, 16 list data files: **65
distinct files, reached from 20 live pages**. All 65 still download today.

| check | files |
|---|---:|
| same path on www.epa.gov | 2 (both moved there from www.epa.gov) |
| EPA snapshot sites | 0 |
| data.gov, by file name | 0 |
| **archive-only by file name** | **63** |

**Hand check.** 30 of the 63 archive-only files, drawn by seed, were searched by hand: the dataset
title and file name on the web, the program's current www.epa.gov pages, gaftp.epa.gov listings,
data.gov and regulations.gov (`hand_check.csv`). **23 of 30 (77%) are confirmed archive-only.** All
7 copies found are in the Clean Air Interstate Rule's regulations.gov docket (EPA-HQ-OAR-2003-0053),
and for 6 of the 7 the docket lists a file the same size in bytes as the archive's spreadsheet
(four of them as Lotus `.wk4`). None was on EPA's own site. The rate puts the archive-only files at about 48 of 63.

**Pages whose data runs through the archive.** 19 live pages in 13 programs reach at least one
file with no live copy found, and 16 of them reach a file the hand check confirmed. Eight of the 19
reach their files through one archived page, CAIR's. #217's crawl captured 43 of the 65 files and
extracted none of them to Parquet. The 22 it didn't index include the 1998 NOx SIP Call budget
files, the Strecker Forest dioxin workbooks and the 2005 HHRAP database.

| live page | archive-only files | in #217 crawl | in #217 Parquet |
|---|---:|---:|---:|
| [NOx Budget Trading Program](https://www.epa.gov/power-sector/nox-budget-trading-program) | 23 | 21 of 30 | 0 |
| [Cross-State Air Pollution](https://www.epa.gov/Cross-State-Air-Pollution/cross-state-air-pollution) | 14 | 21 of 21 | 0 |
| [Historical Regulations Impacting Cross-State Air Pollution](https://www.epa.gov/Cross-State-Air-Pollution/historical-regulations-impacting-cross-state-air-pollution) | 14 | 21 of 21 | 0 |
| [Emission Trading Results](https://www.epa.gov/emissions-trading/emission-trading-results) | 14 | 21 of 21 | 0 |
| [Emissions Trading Programs](https://www.epa.gov/emissions-trading/emissions-trading-programs) | 14 | 21 of 21 | 0 |
| [IPM Analysis for CAIR](https://www.epa.gov/power-sector-modeling/ipm-analysis-clean-air-interstate-rule-cair) | 14 | 21 of 21 | 0 |
| [Power Sector Programs](https://www.epa.gov/power-sector/power-sector-programs) | 14 | 21 of 21 | 0 |
| [Programs & Progress](https://www.epa.gov/power-sector/programs-progress) | 14 | 21 of 21 | 0 |
| [FIFRA SAP Historical Meetings](https://www.epa.gov/sap/fifra-scientific-advisory-panel-historical-meetings) | 8 | 8 of 8 | 0 |
| [Strecker Forest Environmental Review](https://www.epa.gov/mo/strecker-forest-environmental-review-wildwood-missouri) | 5 | 0 of 5 | 0 |

**Verdict.** The argument fails for data. EPA has almost cut the dependency: no live page links a
data file in the archive, and about 19 pages reach roughly 48 archive-only files one step in,
most of them from the 2005 CAIR rulemaking. The wider breakage on January 1 is in reading: 804
live pages link to archived news releases, case documents, history and PDFs, and 153 tell readers
to search an archive that will be gone.

## What it doesn't show

- Pages outside the sitemap, links inside PDFs, links built by JavaScript, and other EPA hosts
  (cfpub, ofmpub, regional subdomains) weren't crawled.
- We follow archived pages one step only. A data file two clicks into the archive isn't counted.
- Sorting by extension counts every zip as data, but some SAP and ozone zips hold Word or WordPerfect files.
- The Wayback Machine's APIs returned HTTP 429 from this environment, so we couldn't check which of
  the 22 files outside #217's indexed crawl the Internet Archive holds.
- gaftp.epa.gov can't be searched by file name, so it's covered only by the hand check. The hand
  check samples 30 files, 12 of them from CAIR.
- What EPA does with archive links on January 1 (redirect, banner or 404) is unknown. Re-run close
  to publication.

## What we looked at first

#217's notebook supplied the address spelling, the live-copy matching (www.epa.gov, snapshots,
data.gov `/search`) and the inventory to join against. We read the sitemap instead of crawling
by following links, because it is EPA's own bounded list of current pages. Python's
`urllib.robotparser` reads robots.txt, and [selectolax](https://github.com/rushter/selectolax)'s
lexbor parser pulls out the links. Wayback's CDX API would have answered what the Internet
Archive holds, but it was rate-limited here.

## Files

- `epa_live_archive_links.py`: the marimo notebook (question, sitemap, crawl, link kinds, one-step
  follow, status today, live-copy check, hand check, result, coverage).
- `run.sh`: runs the notebook as a script and saves its output to `outputs/last-run.txt`.
- `hand_check.csv`: the hand-check verdicts, with where each copy was found.
- `outputs/`: `archive_links.csv` (every link found), `links_by_kind.csv`, `data_links.csv`,
  `data_file_copies.csv`, `pages_with_data_links.csv`, `dependent_pages_by_program.csv`,
  `top_ten_pages.csv`, `hand_check_sample.csv`, `pages_not_reached.csv`.
