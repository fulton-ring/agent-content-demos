# HIFLD Next layers as single PMTiles files

Can the most-used HIFLD Next layers sit on plain object storage as one PMTiles file each, with a
public map reading them directly and no tile server? And since a PMTiles file is read-only, what
happens to people using the map when a layer changes and its file is rewritten?

**Short answer: HIFLD Next already does this.** 514 of its 525 files carry a `.pmtiles` asset,
built with tippecanoe and served from a public Google Cloud Storage bucket with range requests and
CORS, under a new URL for every version. A static MapLibre page reads them with no server of ours.
The open question was updates, and the answer depends on how the file is replaced: **publish each
version under a new URL** (as HIFLD Next does), because overwriting a file in place under a CDN
either serves the old data for the cache lifetime or, with a CDN that caches by byte range,
breaks the layer outright.

![Eight HIFLD Next layers drawn straight from their PMTiles files](outputs/map_first_view.png)

## Run it

```bash
sudo apt install tippecanoe nginx-light   # or: brew install tippecanoe nginx
./run.sh                                  # needs uv; about 12 minutes; downloads ~125 MB into data/
```

`run.sh` runs the marimo notebook `pmtiles_spike.py` as a script, so every number in `outputs/`
comes from the code a reader sees. To read it as a notebook: `uv run marimo edit pmtiles_spike.py`.
Set `CHROMIUM_PATH` to use an installed Chromium instead of downloading one, and
`PMTILES_GDAL_ALL=1` to build all eight layers with GDAL too (adds about 30 minutes).

What's in the folder:

- `pmtiles_spike.py`: the notebook, top to bottom: what HIFLD Next serves, which layers, builds,
  the map, the update test, costs.
- `map/index.html`: the whole map. MapLibre plus the `pmtiles` protocol, given a list of URLs.
- `nginx.conf`: the local "bucket" and two CDN stand-ins used for the update test.
- `outputs/`: CSVs and `results.json` from the last run, and the map screenshot.

## Data

All public, downloaded at run time: the HIFLD Next catalog API and its GeoParquet files
(`hifld.publicenvirodata.org`), HIFLD Next's published `.pmtiles` files, and the ArcGIS Online
search API for view counts. Nothing downloaded is committed.

## Results

RESULTS_PLACEHOLDER

## What we looked at first

tippecanoe (what HIFLD Next uses, same version 2.49) and GDAL's PMTiles driver for building;
the `pmtiles` Python package for reading headers; MapLibre with Protomaps' `pmtiles` JS protocol
for the map; nginx's `proxy_cache` and `slice` modules for the CDN stand-ins. We wrote no tile
code of our own. We read pmtiles.js's `FetchSource` to understand how it handles ETags: it doesn't
send `If-Match` (to avoid CORS preflights), and on an ETag change it drops its cached header,
retries once with `cache: "reload"`, and gives up with an error if the ETag still disagrees.

## What this doesn't show

- **Traffic to HIFLD Next.** It publishes no usage counts, so "most used" means most-viewed on
  ArcGIS Online, which is demand for the old HIFLD Open layers and their copies.
- **A real bucket or CDN.** We had no bucket we could write to and used no paid service. The
  update test runs nginx on one machine as the bucket and as two kinds of CDN. It shows the
  caching mechanics; it doesn't measure a real purge or upload. The upload time is an estimate.
- **Load time from home.** First-view timings are from a cloud machine to Google Cloud Storage.
- **HIFLD Next's real bill.** The costs are estimates at an assumed traffic level from public
  price pages.
- **Chrome only.** The browser tests use headless Chromium.
