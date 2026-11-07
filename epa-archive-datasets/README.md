# What data is inside EPA's legacy web archive?

EPA says it retires `archive.epa.gov` on December 31, 2026. Anything But Binary crawled it into the
Internet Archive item [`epa-archive-harvest-2026`](https://archive.org/details/epa-archive-harvest-2026).
This spike reads that crawl's CDX index to work out how much of the archive is data, checks the
crawl's own numbers, looks for live copies of a sample of the data files somewhere else, and pulls
seven datasets out of the WARCs into Parquet. Each one gets a catalog entry with its provenance.

Issue: [#217](https://github.com/fulton-ring/agent-content-demos/issues/217).

## Run it

```bash
./run.sh
```

You need [uv](https://docs.astral.sh/uv/) and network access. Nothing else. It downloads about 9 MB
of index files plus the seven WARC records it extracts (about 23 MB in total), all by HTTP range
request. It never downloads whole WARCs. A run takes 1 to 2 minutes and writes everything to
`outputs/`. To read the walkthrough with its tables, run
`uv run marimo edit epa_archive_datasets.py`.

Settings come from environment variables: `EPA_SAMPLE_SIZE` (default 100), `EPA_SEED` (217),
`EPA_CACHE_DIR` and `EPA_OUT_DIR`.

## Where the data comes from

All of it is public and read at run time. None of it is committed.

- `epa-archive-harvest-2026.cdx.gz`: the item's merged CDX (142,008 captures).
- `baseline-2026-10-23.zip`: the crawlers' list of the 79,352 URLs in EPA's sitemaps.
- The item's metadata, which lists every WARC file.
- www.epa.gov, EPA's three snapshot sites (`19january2017snapshot`, `…2021…`, `…2025…`), and the
  data.gov catalog search (`catalog.data.gov/search?q=`) for the live-copy check.

## Results (run of 2026-11-07)

All numbers come from `outputs/last-run.txt` and the CSVs next to it.

**How much is data.** The crawl captured 127,194 distinct addresses with HTTP 200. Of those,
**1,759 (1.4%) are data files**: 1,690 spreadsheets and CSVs, 65 SAS transport files and 4 Access
databases. Counting the 572 zip and tar.gz archives, which often hold data, the figure is 1.8%. The
data files take 0.52 GB of the 77.5 GB of WARC records. PDFs take 70% of the bytes. There are no GIS
files (shp, kml), and the XML and JSON turned out to be RSS feeds and page labels, not data. The full
list, with the WARC and offset of every record, is in `outputs/data_files.csv`.

| kind | addresses | share |
|---|---:|---:|
| pdf | 52,585 | 41.3% |
| web page | 43,011 | 33.8% |
| image | 25,848 | 20.3% |
| data (spreadsheet, CSV, SAS, Access) | 1,759 | 1.4% |
| zip / tar.gz | 572 | 0.4% |
| everything else | 3,419 | 2.7% |

**The crawl's numbers.** Its sitemap claim holds: 79,351 of 79,352 sitemap URLs were captured with
200. The "nearly 24,000" extra addresses are 47,843 in the CDX, but 26,920 of those are images, CSS
and JS. The other 20,923 are close to the claim. The merged CDX indexes 77.5 GB of WARCs, against the
81.3 GB claimed. The item has since grown to 147.1 GB: 129 later WARC files (69.5 GB) aren't in the
merged index yet, so this spike doesn't describe them.

**Damaged and missing.** 6,879 addresses never returned 200: 6,007 ended in 404 and 872 in 403. That
is about twice the "3,400+" the crawlers reported, which they called a figure "so far". All but one
are links from archive pages, not sitemap entries, so these are links that were already dead on
EPA's server. By kind: 5,261 web pages, 737 images, 506 PDFs, 203 media files and 17 data files.
The 17 data files are 14 NAEMS animal-feeding-operation spreadsheets, two PM emissions files and
a climate calculator. See `outputs/failed_by_kind.csv` and `failed_addresses.csv`.

**Live copies elsewhere.** We drew a seeded sample of 100 of the 1,759 data files. 38 have a live
copy, and the split by origin is stark:

| origin of the file | sampled | live copy found | where |
|---|---:|---:|---|
| moved from www.epa.gov (`/epa/sites/production/files/…`) | 39 | 38 | www.epa.gov (38), 2017 snapshot (34) |
| legacy program sites (EMAP, NAEMS, air toxics, regions…) | 61 | **0** | nowhere |

data.gov matched none of the 100 by file name. Across the whole inventory, 1,009 of the 1,759 data
files come from the legacy program sites. The check matches file names, so it misses a dataset that
was republished under a new name. That makes "0 of 61" an upper bound on how much is archive-only. A
manual spot-check by web search found one partial case: EPA's AP-42 FTP site has
[NAEMS daily summary CSVs](https://gaftp.epa.gov/ap42/ch09/s04/Related_Information/) (2024), though
not the raw half-hourly files. Meanwhile EPA's live
[NAEMS page](https://www.epa.gov/afos-air/national-air-emissions-monitoring-study) still sends readers
to archive.epa.gov for "the final reports for data". The EMAP coastal survey data and the West Lake
Landfill groundwater database turned up only on archive.epa.gov.

**Extraction.** All 7 picked datasets came out of the WARCs by byte range. Every payload's SHA-1
matched the digest the crawler recorded.

| dataset | format | tables | rows | Parquet MB | seconds |
|---|---|---:|---:|---:|---:|
| EMAP NCA Northeast benthic abundance | CSV | 1 | 34,756 | 0.2 | 1.7 |
| the same, SAS transport copy | XPT | 1 | 34,756 | 0.2 | 2.6 |
| NAEMS IN4A ammonia, fall 2007 | XLS | 1 | 4,369 | 5.0 | 10.3 |
| KCBX petcoke PM10, Jan 2016 | XLSX | 11 | 1,702 | 0.1 | 2.5 |
| West Lake Landfill groundwater, Apr 2013 | ACCDB | 2 | 26,674 | 0.5 | 11.2 |
| NATA 1999 NEI HAP potential errors | MDB | 4 | 14,329 | 0.5 | 3.4 |
| NATA 1996 tract-level file (zip) | XLS in ZIP | 2 | 62,239 | 5.0 | 19.3 |

That's 178,825 rows in total, with a median of 3.4 s per dataset. The EMAP CSV's header declares
34,756 records; the CSV and the XPT copy both give exactly that. Catalog entries (original URL,
capture time, WARC file and offset, SHA-256, tables) are in `outputs/catalog.json`. The Parquet
(11.4 MB) is regenerated by `run.sh` and not committed.

**Run time.** 66 to 97 s for the whole notebook. The live-copy check is most of it.

## What it doesn't show

- It covers the 77.5 GB the merged CDX indexes, not the 69.5 GB added after it.
- Byte figures are compressed WARC record sizes. The originals are larger.
- "Damaged" here means "never returned 200". A file that returned 200 but is truncated would need
  every record opened.
- The live-copy check matches file names only, and the sample is 100 files. The manual spot-check
  covers three datasets.
- Zip and tar.gz contents weren't inventoried. Only one zip was opened.
- The XLS extraction keeps every sheet, but the cells come out as text. Turning them into typed,
  documented tables is the next step for a real republication.

## What we looked at first

[warcio](https://github.com/webrecorder/warcio) reads the WARC records. The Internet Archive's own
merged CDX means no index has to be built. We went with
[access-parser](https://github.com/claroty/access_parser) for Access files because mdbtools needs a
system install, and with [python-calamine](https://github.com/dimastbk/python-calamine) for Excel
because pandas has deprecated xlrd. The data.gov CKAN API (`/api/3/action`) returns 404 now, so the
check uses the catalog's `/search` endpoint.

## Files

- `epa_archive_datasets.py`: the marimo notebook (question, inventory, crawl check, failures,
  live-copy check, extraction, result).
- `run.sh`: runs the notebook as a script and saves the output to `outputs/last-run.txt`.
- `outputs/`: `inventory_by_kind.csv`, `inventory_data_by_extension.csv`, `data_files.csv`,
  `crawl_check.csv`, `failed_by_kind.csv`, `failed_addresses.csv`, `live_copy_sample.csv`,
  `extraction.csv` and `catalog.json`.
