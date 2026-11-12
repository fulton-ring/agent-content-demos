# Which public data endpoints went dark in the PHP2Shell shutdowns, and did they come back?

On October 21, 2026, governments in the Netherlands, Finland, France, Belgium, Germany, Denmark, Canada and the UK
took websites offline as a precaution against the PHP2Shell flaws (CVE-2026-109618, CVE-2026-109619), and CISA
told US organizations to take PHP systems they couldn't patch offline. Nobody published a list of what went
down. This spike rebuilds one for public data from the outside: from the Wayback Machine's capture record and
from a live check of each endpoint today.

Taking a vulnerable system offline was sound advice. The question here is only what the public couldn't reach
in the meantime, and whether all of it came back.

## Run it

```bash
./run.sh
```

It needs [uv](https://docs.astral.sh/uv/). `run.sh` runs the marimo notebook `outages.py` as a script. To read
it with its outputs: `uv run marimo edit outages.py`.

The notebook reads the saved archive answers in `cdx/` and today's live check in `live/` first, and only goes
to the network for what's missing. A rerun on the same day and network gives the same numbers. A run on a new
day adds a new live check. To query the archive from scratch, empty `cdx/`. The fetch is one query at a time,
two seconds apart; from a GitHub Actions runner the archive took about 33 seconds per endpoint, so a
full fetch takes over two hours.

Settings, all optional, from environment variables: `CDX_URL`, `REPLAY_URL`, `CDX_DIR`, `LIVE_DIR`,
`OUTPUT_DIR`, `NETWORK` (labels the live check, default `local`) and `CHECK_DATE`.

## Data

- `endpoints.csv` (255 endpoints, committed). Where each one came from is in its `found_from` column:
  - 50 HIFLD Next source URLs, the `check_url`s from `hifld-next-layer-currency/source_checks.csv`.
  - 98 US federal data pages from `federal-portals-ai-crawlers/hosts.csv`.
  - 25 US state open-data portals, picked by hand.
  - 82 national statistics offices, open-data portals, dataset downloads and government portals in the
    countries that announced shutdowns, plus Eurostat and data.europa.eu, picked by hand. Ten endpoints, such as
    Statistics Canada and Overheid.nl, were named as offline in coverage (BBC, Reuters, CBC, The Register).
    They are the method's check.
- `cdx/NNN.json`: the raw Wayback Machine CDX answer for each endpoint, October 14 to November 1, 2026, plus
  its last good capture before October 21. `cdx/replays.json`: the archived captures we opened to look for
  maintenance pages. These are committed so the numbers can be rebuilt after the archive changes.
- `live/<date>-<network>.csv`: one live request per endpoint.

The Wayback Machine doesn't answer from the Claude worker's sandbox, so the archive fetch ran from a GitHub
Actions runner (`archive-fetch.yml`, copied to `.github/workflows/` only while the branch needed it). It took
five runs: the archive answered CDX queries in about 33 seconds each, and it throttles replays to about 15 a
minute.

## Results

From the run of 2026-11-12: archive answers for all 255 endpoints, the 93 suspect captures opened, and a live
check from a GitHub Actions runner the same day.

| | |
|---|---|
| Endpoints checked | 255: US 173 (50 HIFLD Next sources, 98 federal, 25 state), CA 17, UK 15, NL 11, FI 8, FR 8, DE 8, BE 7, DK 6, EU 2 |
| No capture at all, Oct 14 to Nov 1 | 81 |
| No capture during the shutdown days (too few to tell) | 173 (68%) |
| Outages starting in the shutdown days | 4 (CA 1, NL 1, DE 1, US 1) |
| Median outage length, bounds | 0 to 34.8 hours |
| Still bad at the end of the window (Nov 1) | 0 |
| Outages starting in the week before (background) | 1 |
| Outages that had an outside copy | 4 of 4 (238 of 255 endpoints have one) |
| Live on 2026-11-12 | 233 up, 18 blocked our client, 2 down, 2 gone |
| Up without downloads | 0 of the 14 pages where we found data-file links |

**The method sees real takedowns when the archive was looking.** Ten endpoints were named offline in coverage.
Five had a capture during the shutdown days, and two of those show the outage. Statistics Canada's home page
returned a 503 at 16:56 UTC on October 21 and was back by 04:53 UTC on October 23, which matches CBC. The Dutch
cyber-security agency's home page served "Onze website is tijdelijk niet beschikbaar" (our website is
temporarily unavailable) at 10:53 UTC on October 21 and was back by 20:15 UTC. The other three (OBR data, the
Finnish Government, Canada's Cyber Centre) had captures only before their takedown or after it.

**The other two outages look like noise:** a single 404 on the retired HIFLD Open hub, and a single 404 on the
German Federal Employment Agency's statistics site, each good again within hours. The same statistics site
served a maintenance page on October 26, after the shutdown days.

**Everything seen going down came back within the window.** None of the 4 was still bad on November 1. Today two
are up, one is the retired HIFLD Open hub (gone before the shutdowns too), and one blocks our client. Of the
four, two run Drupal and two show no PHP. We found no data page that came back without its downloads, but only
14 pages had download links we could test.

**The capture record is the main limit.** The archive made about 4,500 captures a day of these endpoints from
October 14 to 16, then 100 to 175 a day from October 18 on, shutdown days included. 68% of endpoints have no capture during October 21 to 23, and
49 of the 50 HIFLD Next sources have none. Among the national portals in the shutdown countries, 57 of 82 can't
be told. So the answer to "did they all come back" is yes for every outage we could see, but "nobody published
a list" holds for the archive too: most of what might have gone dark wasn't watched.

Full numbers: `outputs/summary.json`. Per endpoint: `outputs/endpoint_results.csv`. Each outage with its
bounds: `outputs/outages.csv`. The run's printout: `outputs/last-run.txt`. The live check from the worker's
sandbox on 2026-11-11 is kept in `live/` (235 up, 15 blocked, 3 down, 2 gone).

To reproduce these numbers exactly from the saved files, run
`NETWORK=github-actions CHECK_DATE=2026-11-12 ./run.sh`. Without those settings it makes a new live check today.

## How it decides

- **Bad capture:** a server error (5xx), a 404 or 410, or a maintenance page. To find maintenance pages behind
  a 200 status or a redirect, it opens archived captures from October 21 on that are redirects or much smaller
  than the endpoint's usual page, and whose content is new. It then looks for maintenance wording in the
  redirect target, title or first heading, in six languages.
- **Outage:** a run of bad captures after a good one. It's counted as part of the shutdowns if it starts
  between October 21 and 24 UTC. Its length is given as two bounds: at least first bad to last bad, at most
  good before to good after.
- **Too few captures to tell:** no capture between October 21 and 24.
- **Outside copy:** a good archive capture before October 21, at any date, or the endpoint is a HIFLD Next
  source, so HIFLD Next holds a copy of its layer.
- **Today:** up, down, gone (404/410), blocked (the site refused our client), or up without downloads (every
  data-file link on the page failed).

We report software platforms only as counts, never per endpoint.

## What we looked at first

The Wayback Machine CDX API is the standard way to list captures. We tried its availability API
(`archive.org/wayback/available`), which the sandbox can reach, but it returns only one nearby capture, often a
stale one, so it can't show an outage. The Common Crawl index was also unreachable from the sandbox, and it
crawls about once a month, too rarely for a three-day event.

## What it doesn't show

- **Pages the archive didn't visit.** An endpoint with no capture during the shutdown days could have been down
  the whole time. That share is the method's blind spot, reported above.
- **Why a page failed.** A 503 on October 22 fits a precautionary takedown, but it could be an ordinary failure.
  The week before is the background rate.
- **Exact outage lengths.** Captures are snapshots, hours or days apart.
- **Every public dataset.** It's a sample weighted to US federal data and to the main national portals.
