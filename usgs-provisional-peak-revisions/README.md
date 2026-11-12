# How much do USGS river gage peaks change between real time and approval?

When a flood crest goes out from a USGS streamgage, the number is provisional; months later USGS approves the
record, sometimes with a different peak. Polymarket's river-crest markets settle on the provisional number, and
USGS does not archive provisional values, so nobody had measured the gap. This spike measures it for about 100
flood-prone gages, using the Iowa Environmental Mesonet's archive of what gages transmitted in real time.

Issue: [#263](https://github.com/fulton-ring/agent-content-demos/issues/263) (sub-issue of #207).

## Run it

```bash
./run.sh
```

Needs [uv](https://docs.astral.sh/uv/). It runs the marimo notebook `peak_revisions.py` as a script and writes
`outputs/`. To read it alongside its output: `uv run marimo edit peak_revisions.py`.

`cache/` holds the raw pulls from our run (public data, about 15 MB), so a run from a clean checkout takes about
a minute and reproduces our numbers. Delete `cache/` to pull everything fresh: about two hours, because the IEM
archive serves one request at a time per client. Set `USGS_API_KEY` for a higher USGS rate limit (optional).

`snapshot.py` (`uv run snapshot.py`) saves a dated copy of what USGS currently publishes for the gages behind
the live Polymarket markets (St. Louis 07010000, Baton Rouge 07374000, Great Salt Lake 10010000) into
`snapshots/<date>/`. The 2026-11-12 snapshot is committed; #264 takes the end-of-November one.

## Data

- **As transmitted:** [IEM HADS/DCP archive](https://mesonet.agron.iastate.edu/request/dcp/fe.phtml), the SHEF
  messages NOAA's HADS decoded from each gage's satellite transmissions. Gage height (`HG`) from late 2007 in
  some states and November 2010 in most; discharge (`QR`) only from about 2023 at some gages.
- **Approved:** [USGS Water Data OGC API v1](https://api.waterdata.usgs.gov/ogcapi/v1/), `daily` (to find flood
  days) and `continuous` (15-minute values with `approval_status` and qualifiers).
- **Gage list and flood stages:** IEM station tables per state and [NOAA NWPS](https://api.water.noaa.gov/nwps/v1/)
  gauge metadata (USGS id and NWS action, minor, moderate and major flood stages).

## Method, in one paragraph

For 20 states we take NWS forecast-point gages whose IEM archive starts by 2010 and pick five per state with a
fixed seed, plus White River at Indianapolis (03353000) and the two Helene gages at Asheville (03451500,
03451000). For each gage-year we pull three-day windows around the three highest approved days and compare the
highest approved 15-minute value with the highest transmitted value in the same windows. Garbage transmissions
(a 1,213 ft stage at a 20 ft gage) are filtered out first and counted. Only fully approved gage-years with a
transmission within two hours of the approved crest are measured. The notebook explains each step.

## Results

RESULTS_PLACEHOLDER

## What we looked at first

USGS keeps no provisional history: the OGC API and the old WaterServices return only current values, and SIR
2017-5137 says provisional data "have not been archived." The Wayback Machine is blocked from our sandbox. IEM's
HADS archive is the only long record of real-time values we found. We use `httpx`, `polars` and `altair`; no
library wraps either API for this.

## What it doesn't show

- **IEM is a proxy for the USGS website.** It holds what the gage sent. USGS screens and edits values before or
  while it displays them (it does not show the garbage readings we filter), and those edits never reach HADS.
- **Windows can miss a transmitted peak elsewhere in the year.** The notebook's full-year check measures how
  often for a sample.
- **The sample** is NWS forecast points with long IEM archives, not all USGS gages.
- **Discharge** covers only the gages and years where IEM has `QR`, mostly 2023 onward.
- **Market settlement values** (minimum or maximum at a cutoff) are not the annual peak. The snapshot lets a later
  run compare the St. Louis and Baton Rouge November values with the approved record.
