# NYC climate data: can we download, format and join it?

[Issue #293](https://github.com/fulton-ring/agent-content-demos/issues/293).
An end-to-end feasibility spike for a New York Climate Exchange hackathon, not a dashboard.
Two readable marimo notebooks test real downloads, native-grid Icechunk round trips,
point-observation Parquet, a UTC interval join, storage size and access failures.

## Run from a clean checkout

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then from the repository root:

```sh
bash nyc-climate-icechunk/run.sh
```

No API keys or paid services are needed for the tested core. Internet access is required.
`uv sync --locked` installs the pinned Python environment. The default run downloads six hours
on September 2, 2021, 00:00–06:00 UTC (Hurricane Ida), around 40.6–40.9°N, 74.1–73.7°W.
`config.env` defaults accept environment overrides; runtime files stay in ignored `output/`. Fresh run:

```sh
CLIMATE_OUTPUT="$HOME/.capy/work/climate-proof" bash nyc-climate-icechunk/run.sh
```

The spike caps time to six hours and bounds to one degree per axis. ERA5 response bodies
are capped at 64 MiB; the MRMS/IMERG preflight caps touched decoded chunks to 256 MiB per source.
For repeatable byte measurements, use a **new output directory**: existing Icechunk repositories
retain earlier snapshots. Re-running fetches upstream again; these are not warm-cache timings.
These local repositories are single-writer; do not run two ingest processes into the same output.

Read `gridded.py` top to bottom, then `notebook.py`. For interactive reading, source `config.env`
inside this folder and run `uv run marimo edit gridded.py` (or `notebook.py`).

## What is actually tested

| Source | Acquisition and formatting proof |
|---|---|
| MRMS | Anonymous dynamical.org hourly precipitation → local native-grid Icechunk → identical reopen |
| NASA IMERG Early | Anonymous dynamical.org half-hour precipitation → Icechunk → identical reopen |
| ERA5 | Anonymous WeatherBench hourly precipitation → Icechunk → identical reopen |
| FloodNet | Deployment discovery and processed-depth API → local-only Parquet → identical reopen |
| NOAA CO-OPS | Battery six-minute water levels, metres NAVD88, UTC, with quality flags → Parquet |
| NOAA ASOS via IEM | JFK historical hourly reports, temperatures and trailing-hour rain → Parquet |
| NWS | Latest JFK observation downloaded; explicitly rejected as outside the 2021 event window |

`rainfall-hourly.parquet` contains explicit interval starts/ends and nearest-native-cell coordinates.
`joined-local-only.parquet` joins rain, hourly maximum observed street depth, counts and harbor
elevation by UTC interval start. It does **not** join weather's trailing-hour rain onto clock hours.
`comparison.png`, summary JSONs and `access-audit.json` explain what was measured and what failed.

## Results

Clean-checkout code `38cbb92`: **34.70 seconds**, peak RSS **330 MiB**; all 12 tests,
ruff, ty and strict marimo checks pass. `results/` contains the measured summaries and chart.

| Source | Native array shape (time × lat × lon) | Fresh Icechunk bytes | Six-hour rain at nearest cell |
|---|---|---:|---:|
| MRMS | 6 × 30 × 40 | 14,087 | 132.63 mm |
| IMERG Early | 12 × 3 × 4 | 4,638 | 65.17 mm |
| ERA5 | 6 × 1 × 2 | 3,224 | 38.61 mm |

The join uses 81 depth readings, 60 tide readings and six historical weather reports.
ERA5 transferred 11,273,221 response-body bytes; MRMS/IMERG network bytes are unmeasured.
Not every discussed source works end to end: see the access audit below.

## Issues uncovered before a dashboard exists

1. **A successful join is not agreement.** The three rainfall sources retain different native
   grids and estimates. Nearest cells are not the sensor location. The chart compares them;
   there is no answer key establishing which product is correct at that street.
2. **An unshifted timestamp join is wrong.** MRMS and ERA5 label the end of the previous hour;
   IMERG labels the start of a half-hour. Integrate rates over duration before pairing intervals.
   MRMS/IMERG units are kg m-2 s-1 (equivalent to mm/s); ERA5 precipitation is metres.
3. **JFK hourly reports are not clock-hour rain.** Reports arrive at :51. Their trailing-hour
   precipitation windows do not match 00:00–01:00 intervals; trace precipitation stays flagged,
   not silently converted to a measured zero. Temperature is converted from Fahrenheit.
4. **Historical FloodNet cadence differs from today's one-minute claim.** Measure actual gaps,
   preserve missing values, report counts, and do not claim an hourly maximum is the true peak.
   The API may change; the same deployment was probed with one-, three- and six-hour requests
   and retained roughly the same observed cadence. This does not establish the cause.
5. **A small selected array can require large reads.** The source chunk layout determines
   ingestion traffic. ERA5 reads explicit global hourly chunks; upstream MRMS/IMERG chunks span
   many days. Selected bytes and decoded touched-chunk bytes are not network-byte counts.
6. **Archives don't all overlap.** This ERA5 mirror ends January 10, 2023. It cannot provide the
   September 2023 flood or current weather. GIEO's announced 2025 launch is after this Ida window.
7. **Physical quantities differ.** Local street-water depth is not harbor elevation against
   NAVD88. Do not subtract them, infer citywide flood extent from a point, or claim causal attribution.
8. **Quality and maturity differ.** IMERG Early is not Final; MRMS combines products and can fall
   back to others; ERA5 is reanalysis. Current CO-OPS readings may be preliminary. The chosen
   historical tide quality flags are recorded; source-wide quality validation is not proved.
9. **Publication permission is separate from access.** FloodNet's agreement restricts sharing
   original data, even subsets. Local-only tables are ignored. A public bucket still needs permission.
10. **Snapshot retention costs space.** Unchanged chunks are shared, but retained rewritten
    chunks accumulate. Storage figures from repeated runs are not fresh-release sizes.

## Additional sources: explicit failures and untested scope

`access-audit.json` is generated from live probes, never from a table claiming download success.

- GIEO: the public Helsinki page exposes plots/Grafana, not a verified downloadable data feed.
  We need an operator-provided export/API, schema, QC, coverage and reuse terms.
- MERRA-2 and ECOSTRESS: CMR finds NYC-overlapping granules. Anonymous bounded download probes
  record the returned HTTP status; metadata discovery is not an actual data download.
- ERA5-Land: CDS process metadata is reachable; a credentialed retrieval is not tested.
- NYC stormwater maps: catalog metadata is reachable, but scenario geometries are not downloaded.
- AirNow/AQS and NYC Micronet: not ingested. API accounts and/or reuse permissions remain work.

No fake arrays substitute for these sources. Access follow-ups: [GIEO #294](https://github.com/fulton-ring/agent-content-demos/issues/294)
and [NASA/CDS #295](https://github.com/fulton-ring/agent-content-demos/issues/295); maps remain untested.

## Publishing and cost implications

Use source-specific Icechunk/Zarr datasets and Parquet observation tables, plus a release manifest
pinning each snapshot. Keep native arrays and a clearly derived interval-aligned table.
Don't mirror the global sources; curate NYC chunks and stable event packages instead.
These tiny files are dominated by metadata and storm-specific compression: do not multiply six-hour
compressed sizes into a production annual bill. `gridded-summary.json` separates selected payload,
actual local repository size, measured ERA5 response bytes and unmeasured Rust HTTP bytes.
No cloud writes occur and no paid services are used. Object-store requests, egress, public browser
access, concurrent ingestion, latency SLAs and real cloud billing are **not** validated here.

## Checks

```sh
cd nyc-climate-icechunk
uv run ruff check . && uv run ruff format --check . && uv run ty check
uv run pytest -q
```

Tests cover interval-end shifts, rate integration, incomplete half-hours, wrong units, preserved
native longitude/latitude order and NaNs, exact Icechunk round trips, duplicate sensor times,
missing-versus-dry and repeated local hours during daylight-saving transitions.

## Sources, prior tools and attribution

We used [Xarray/Icechunk](https://icechunk.io/en/latest/guides/xarray/), not a new storage format;
[dynamical MRMS](https://dynamical.org/catalog/noaa-mrms-conus-analysis-hourly/) and
[IMERG](https://dynamical.org/catalog/nasa-imerg-analysis-early/) (CC BY 4.0), rather than GRIB ingest;
[WeatherBench](https://weatherbench2.readthedocs.io/en/latest/data-guide.html) for the ERA5 mirror;
[ECMWF](https://confluence.ecmwf.int/spaces/CKB/pages/76414402/ERA5+data+documentation) for
accumulation semantics; [NOAA CO-OPS](https://api.tidesandcurrents.noaa.gov/api/prod/),
[IEM ASOS](https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?help), and
[FloodNet access documentation](https://github.com/floodnet-nyc/floodnet-data).
The custom code only bounds reads, measures round trips and exposes cross-source incompatibilities.

Credit FloodNet (New York University and The City University of New York), Mydlarz et al. (2024),
doi:10.1029/2023WR036806; NOAA; NASA IMERG via dynamical.org; and Copernicus ERA5 via WeatherBench.
The derived comparison chart is CC BY-NC-SA 4.0 under the linked FloodNet agreement; original
source data are not included. This is exploratory analysis, not emergency or navigation guidance.
