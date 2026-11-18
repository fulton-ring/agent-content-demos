# Who would notice if a public data endpoint went dark for a week?

During the PHP2Shell shutdowns of October 21 to 23, 2026, the Wayback Machine had no capture of 68% of 255
public data endpoints ([php2shell-data-outages](../php2shell-data-outages/README.md)). This spike asks whether
anyone else would have noticed, whether that blind spot was special to the shutdown week, and what the
smallest monitor that fills it looks like.

**Status: partial.** The Wayback CDX API resets the connection from the worker's sandbox, so this run makes no
new archive queries. The four weeks either side of the shutdowns and a control set of popular government pages
are not measured yet; see "Not done" below.

## Run it

```bash
./run.sh
```

It needs [uv](https://docs.astral.sh/uv/). `run.sh` runs `monitor.py` once (checks HIFLD Next's 50 source
endpoints and appends to `log/checks.csv`), then runs the marimo notebook `notice.py` as a script. To read the
notebook with its outputs: `uv run marimo edit notice.py`.

Settings, all optional, from environment variables: `SOURCES`, `MONITOR_LOG`, `NETWORK` (labels the monitor
run, default `local`), `PHP2SHELL_DIR` and `OUTPUT_DIR`.

## Data

- The PHP2Shell spike's saved Wayback CDX answers (`../php2shell-data-outages/cdx/`), October 14 to
  November 1, 2026, for 255 endpoints in 9 countries plus the EU. They're read, not copied or changed.
- `sources.csv`: HIFLD Next's 50 source URLs, copied from that spike's `endpoints.csv`.
- `log/checks.csv`: one row per endpoint per monitor run.

## Results

From the run of 2026-11-18. Full numbers in `outputs/summary.json`, per endpoint in `outputs/endpoint_gaps.csv`,
per day in `outputs/captures_per_day.csv`, printout in `outputs/last-run.txt`.

| | |
|---|---|
| Captures per day, Oct 14–16 vs Oct 18–Nov 1 | 4,566 vs 134 (mean) |
| Share of the Oct 14–16 captures made by the top 10 endpoints | 93% (gov.uk and ons.gov.uk alone about 1,400 a day each) |
| When the fall happened | one hour: 163 captures at 14:00 UTC Oct 17, 108 at 15:00, 14 at 16:00 |
| Captures of the 50 HIFLD Next sources, any day | 0 to 3 in total |
| Median captures per endpoint per week | 1 (Oct 14–20), 0 (Oct 25–31) |
| Endpoints with a gap over 7 days with no capture, Oct 14–Nov 1 | 193 of 255 (HIFLD Next 49 of 50, US federal 58 of 98, US state 24 of 25, national 62 of 82) |
| Endpoints with no capture in either week | 89 |
| Endpoints captured at least daily in both weeks | 30 |
| Other public monitors covering these endpoints day by day | none found (8 checked, below) |
| Monitor run (worker sandbox, 2026-11-18) | 50 up, 0 down, 5.0 s |
| Cost | $0 |

**The fall in captures was not about data endpoints or the shutdowns.** It was a step on October 17 at about
15:00 to 16:00 UTC, four days before the first takedowns, and nearly all of it was a few popular national home
pages losing a very frequent crawl. HIFLD Next's sources were never captured more than three times a day in
total, before or after. The card's line that "captures of HIFLD Next's sources fell from about 4,500 a day"
misreads the PHP2Shell numbers: 4,500 a day was all 255 endpoints.

**So the shutdown week was ordinary for data endpoints, and ordinary is blind.** Across October 14 to
November 1, three in four endpoints went more than 7 days without any capture, and 49 of the 50 HIFLD Next
sources did. A week-long outage at almost any of them would leave no trace in the archive.

**Nobody else keeps the record.** The data.gov harvester logs failures only for agency catalog files (data.json),
not ArcGIS services. The Data Rescue Project and dataindex.us track removals by hand or quarterly, and
dataindex.us "does not count temporary takedowns". ArcGIS Online's status page covers Esri's own platform only.
data.europa.eu re-checks each link every few weeks and keeps no outage history. EDGI tracks content changes on
environmental pages, built on Wayback captures. The PHPocalypse Tracker followed sites people reported dark
until about October 30. Small uptime pages watch a handful of big .gov sites. Sources and quotes are in the
notebook's Step 3.

**The monitor is 73 lines and takes about 5 seconds.** `monitor.py` would have caught any of the 50 sources going
dark on the first daily run. On October 21 to 23 the archive captured one of the 50; the PHP2Shell spike's
own live checks on November 11 and 12 found all 50 up. Scheduling it daily (for example a GitHub Actions cron
that commits `log/checks.csv`) is a founder decision and isn't set up.

## Not done

- **Four weeks either side, and a control set.** The issue asks for captures per day for September 23 to
  November 20 for the 255 endpoints and for popular government pages outside them. That needs new CDX queries.
  The CDX API resets the connection from this sandbox (3 of 3 tries); the PHP2Shell spike got its data from a
  GitHub Actions runner. The national home pages in the 255 (gov.uk, ons.gov.uk, cbs.nl) act as a partial
  control here: they fell by the same step.
- **Why the archive's crawl changed on October 17.** Not known; only its timing and shape are measured.

## What it doesn't show

- Whether the archive's pattern in these 19 days is typical of the rest of the year.
- Whether the data behind an endpoint that answers is complete or current. The monitor checks the endpoint
  answers.
- Endpoints outside the PHP2Shell spike's sample, which is weighted to US federal data and national portals.

## What we looked at first

Existing public monitors (above) before writing one. `monitor.py` uses `requests` and the standard library;
a hosted uptime checker would do the same job but adds a paid or third-party service and keeps the log out of
the repo. The archive's availability API (`archive.org/wayback/available`) answers from the sandbox but returns
only one nearby capture, so it can't count captures.
