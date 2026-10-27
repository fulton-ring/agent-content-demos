# How current are the rescued copies of federal climate data?

Our article on federal climate data lists 20 datasets that went offline, stopped updating or
lost their app after January 2025, and for each one the newest record in the copy people can
still use. This folder turns that table into a dataset we maintain: a CSV, plus a notebook that
re-reads the newest record date in every copy, so the table can be refreshed instead of going
stale itself.

## Run it

```bash
./run.sh
```

It needs [uv](https://docs.astral.sh/uv/) and internet access, and no key or account. It runs
`refresh.py` (a [marimo](https://marimo.io) notebook) as a script. The script reads
`data/currency.csv`, fetches every copy, writes the CSV back with today's `date_checked`, and
prints what changed since the last run and which rows a person has to check. The output is
saved to `results/last-run.txt`. `uv run marimo edit refresh.py` opens the notebook with its tables.

## The data

`data/currency.csv` has one row per **copy**. That gives 25 rows for the 20 datasets:
Billion-Dollar Disasters has two copies (Climate Central, and NOAA's frozen archive), EJScreen
has two (PEDP's environmental layers and the EJAM demographics), and the four NCEI satellite
records get one row each. The first row of each dataset is its main copy, and counts by
dataset use that row.

Columns: `dataset`, `agency`, `went_dark` (date: what happened), `copy_name`, `copy_url`,
`newest_record_in_copy` (ISO date at the precision the copy gives), `date_checked`, `status`,
`how_checked`, and the check itself (`check_kind`, `check_url`, `check_pattern`,
`check_value`), plus `article_newest` (the article's value) and `notes`.

`status` uses the article's categories. One was added, "FOIA copy newer than the agency",
for the Greenhouse Gas Reporting Program, which didn't fit the others. `status` is a person's
call, and the script never changes it.

`data/article-2026-10-17.csv` is the starting point: the article's values as checked by hand
on 2026-10-17. The data are CC BY 4.0 (`data/LICENSE.md`).

## How a copy is read

Rather than write one reader per site, each row names a URL and a regular expression. There
are three kinds of row:

- **date** (18 rows): the pattern's named groups make a date, and the newest match wins. The
  sources include a CSV's last row (Sea Ice Index, NCEI's disaster list), a folder listing
  (PSL, Pathfinder, HURSAT, ISCCP-H), a file name (ETC Explorer), an ArcGIS field (FEMA's
  `NRI_VER`, the EJ grants layer's `dataLastEditDate`), an OPeNDAP time axis (CoRTAD), CDC's
  Tracking API (the Heat Tracker), and a dated line on a page (Climate Central's "As of
  September 2026").
- **marker** (7 rows): finished products and rebuilt apps with no date to read (NCA5, the
  Atlas, NEO's decommission notice, EJScreen's "Version 2.3", CEJST's newest release note,
  our Future Risk Index build, USDA Climate Hubs). The script reads a piece of text that would
  change if the copy did. Unchanged, the last date stands. Changed, the row goes to a person.
- **manual**: no row needs this today. Any row whose fetch or match fails falls back to it
  for that run, keeping its last value and listing it for a person.

Before writing this, we looked for an existing tool. Website change monitors
(changedetection.io, Visualping) can tell you that a page changed, but not what the newest
date in a CSV, a folder listing or an OPeNDAP axis is. The Data Rescue Project, PEDP and
dataindex.us don't record how current each copy is (see the article). So the readers here are
a few lines of `re` and `requests`, and everything else is in the CSV.

## Results (run of 2026-10-23)

| | |
|---|---|
| Datasets dated by the script on their own (main copy) | **13 of 20** |
| Datasets watched by a marker, dated by a person when it changes | **7 of 20** |
| Datasets fully manual | **0 of 20** |
| Copies read on the first run | **25 of 25** (the CDC row fails in some runs, see below) |
| Run time | **1.8 seconds** for all 25 copies (2 to 4 s across runs) |
| Values changed from the article's 2026-10-17 check | **4 of 25** copies: 2 earlier, 1 newer, 1 new |
| Stale, frozen at the last federal release | **7 of 20** (same as the article) |
| Current data from the agency or a federal successor | **6 of 20** (same as the article) |

Against the article's 2026-10-17 values, of the 18 dated copies: 14 agree, 1 is newer
because the source kept updating (the Sea Ice Index, 2026-10-16 to 2026-10-17), 2 are
earlier than the article said, and the Heat Tracker has a date where the article had none.

**Where the run disagrees with the article:**

- **HURSAT: 2016, not 2024.** NCEI's HURSAT-B1 v06 archive has storm-year folders from 1978
  to 2016. The newest file is Typhoon Nock-ten, December 2016. The HURSAT-AVHRR and HURSAT-MW
  archives stop in 2009. We found no 2024 data. The four NCEI records stay "stale" either way.
- **EJ grants map: 2025-05-19, not 2025-05-29.** The grants layer behind PEDP's map was last
  edited on 2025-05-19. The 29 May date the article used is likely the web map item's
  `modified` date (2025-05-28 UTC, so the 29th in some time zones), which changes when the
  map is edited, not the data. Either way, nothing has changed in 17 months.
- **CDC Heat and Health Tracker: current, not unconfirmed.** CDC's Tracking API offers weekly
  heat-related ED visit rates (measure 1237, the tracker's own series) through the week ending
  **2026-10-17**. We read that in this session. The page's "Planned Maintenance" text is a
  hidden placeholder, not a banner. So the article's "apparently restored, unconfirmed" can
  become "restored, current", and the count of 4 restored stands. The API lists the weeks it
  offers, not values. One more check of a week's numbers would confirm it fully.
- **More precise, same value:** NCEI's archive's newest event is Hurricane Milton (begins
  2024-10-09). CoRTAD's last week is 2022-12-27. ISCCP-H's newest month is 2017-06.
  Climate.us's newest update is 2026-06-23 (version 1.0 of the site).

**Hard cases from the issue:**

- **NASA NEO**: `neo.gsfc.nasa.gov` now redirects to a NASA page saying "The NEO website was
  decommissioned in September 2026". No copy. The marker row watches that notice.
- **PSL repository**: newest folder is 2024-05-17 in `iccdata1/FACTS` (`iccdata2` stops at
  2023-06-08). This matches the article.
- **ETC Explorer**: no federal version has come back. The court opinion's line that the tool
  "has since been updated with new methodology and data" describes the TC Explorer update of
  January 2025, before the removal. Its builder, D.W. Rowlands, says the tool is no longer
  online, and DOT's ETC page returns 403 to scripts. The copy is the Rowlands data, dated
  2025-01-03.

## Second run

The first run, starting from the article's values, is saved in
`results/first-run-from-article.txt`. Then, from a clean checkout of the branch, we ran
`./run.sh` twice in a row. Both runs reported `Changed since the last run: 0` and nothing for
a person to check (`results/clean-run-1.txt`, `results/clean-run-2.txt`). A row changes only
when a source moves on. The Sea Ice Index usually adds a day each day (not this week: on 2026-10-23 it still
ended at 2026-10-17). To see the 4 changes from the
article again, run with `CURRENCY_CSV` pointed at a copy of `data/article-2026-10-17.csv`;
when CDC rate-limits the Heat Tracker row, a normal run counts it as not re-read and shows 3.

## What didn't work, and what it doesn't show

- **CDC's Tracking API limits requests without a token.** After a few calls it answers
  `"code":429, "Server has serviced too many non-token requests"` with HTTP 200. The limit
  seems to be shared across this sandbox's outbound address. The Heat Tracker row failed in
  4 of our 11 runs, and in all 3 of a reviewer's runs the same day, and fell back to its
  last value, as designed. CDC issues free API tokens.
  Adding one is the fix if this runs on a schedule.
- **Some sites block scripts.** fema.gov, cdc.gov (but not atsdr.cdc.gov), transportation.gov
  and GitHub's API return 403 from this sandbox. We read FEMA through its ArcGIS layer. We
  didn't check the GitHub copy of EJI (`oedp/cdc-ej-index`) or the Esri Future Risk Index
  archive layer.
- **Some dates are proxies.** Climate.us's newest What's New entry, not each dashboard series.
  EPA's "Web update" on the heat-waves page, not all 57 indicators. EIP's reporting year in a
  page title, so a 2025 release on a new page would be missed. The newest Pathfinder year
  folder, not the newest day.
- **A pattern is tied to a page's wording.** A redesign makes the row fail loudly and fall
  back to manual, rather than read a wrong date. That is deliberate, but needs upkeep.
- **Markers never date a copy.** Seven datasets still need a person whenever their marker
  changes.
- **It doesn't run on a schedule.** See below.

## A monthly schedule

The script is fast and fails safely, so a monthly GitHub Actions workflow could run
`./run.sh`, commit `data/currency.csv` when it changes, and open an issue listing the rows for
a person. It would need a CDC Tracking API token as a repository secret, and an owner to work
the list each month. Whether to commit to that is a founder's call, filed as #113. The article shouldn't promise monthly updates until it exists.
