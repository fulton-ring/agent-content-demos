# HIFLD Next's map tiles vs its GeoParquet: same answers?

HIFLD Next publishes every layer twice: GeoParquet for analysis, PMTiles for maps. Tile readers
such as Query Farm's [vgi-mvt](https://github.com/Query-farm/vgi-mvt) now make a PMTiles file
queryable as a table, so analysts and agents will reach for the tiles. Do they get the same
answer? We asked 21 plain questions of 7 layers, answered each with the same SQL over both files,
and measured the error, bytes read and time.

**Short answer: it depends almost entirely on how the tiles are read.** Read naively, one row per
stored piece, which is what GDAL's `ST_Read` does, **no total was right**: counts and lengths came
out 6% to 641% too high. Read at the top zoom with pieces glued back together by feature id,
which is vgi-mvt's default, **20 of 21 answers were within 1%**. The one miss was an area where
the GeoParquet's own geometry is invalid. A zoom or two below the top, point layers lose 80% to
98% of their features and totals collapse. Proximity questions were right at the top zoom whichever
way the tiles were read, and read 43 times fewer bytes than the GeoParquet. But for counts filtered
on an attribute, the GeoParquet read **30 times fewer** bytes than the tiles, because Parquet
reads only the columns a query needs.

## Run it

```bash
./run.sh    # needs uv; about 12 minutes; downloads ~250 MB into data/
```

`run.sh` runs the marimo notebook `tiles_vs_geoparquet.py` as a script, so every number in
`outputs/` comes from the code a reader sees. To read it as a notebook:
`uv run marimo edit tiles_vs_geoparquet.py`. Set `DATA_DIR` to reuse downloaded files.

- `tiles_vs_geoparquet.py`: the notebook, top to bottom: layers, feature ids, the tile reader,
  the 21 questions, the answer key, tile answers, results, which file to use.
- `outputs/`: `results.csv` (every question × zoom × reading mode), the summary tables
  below as CSVs, `summary.json` and `geometry_notes.json`.

## Data

All public, downloaded at run time through the HIFLD Next catalog API
(`hifld.publicenvirodata.org`): the GeoParquet and PMTiles files of hospitals, fire and EMS
stations, power plants, transmission lines, electric retail service territories, counties and
states. Nothing downloaded is committed.

## How it works

- **Answer key:** DuckDB 2.0 with the spatial extension over the GeoParquet, each layer
  reprojected from its declared CRS (two are stored in Web Mercator). Lengths, areas and
  distances in CONUS Albers metres (EPSG:5070) on both sides.
- **Tiles:** read with `pmtiles` (directory) and `mapbox-vector-tile` (decoding) at each layer's
  top zoom and two and four zooms below, three ways: **raw** (every stored piece, buffer copies
  included), **clip** (each piece cut to its tile; needs no ids) and **merge** (clip, then union
  the pieces that share a feature id). The decoded pieces go into DuckDB tables with the same
  column names, and the same SQL runs.
- **Bytes:** for tiles, the header, directories and tiles a range-request reader would fetch. For
  GeoParquet, what DuckDB actually fetched from HIFLD Next's bucket (its HTTP log, file cache off).
- **Error:** relative for numbers; for names, right or wrong; for lists, 1 − Jaccard.

## Results

From the clean-checkout run (`outputs/`). Questions within 1% of the GeoParquet answer:

| Type (questions) | Top zoom, merged | Top zoom, raw | 2 zooms down, merged | 4 zooms down, merged |
|---|---:|---:|---:|---:|
| Count (7) | 7 | 0 | 1 | 1 |
| Length (3) | 3 | 0 | 3 | 0 |
| Area (4) | 3 | 0 | 3 | 3 |
| Proximity (7) | 7 | 7 | 3 | 2 |
| **All (21)** | **20** | **7** | **10** | **6** |

Error on the 13 numeric totals: top zoom raw **−99.9% to +640.6%** (median +7.8%); top zoom merged
**−8.5% to 0.0%** (median 0.0%); 4 zooms down merged −97.6% to 0.0% (median −51.9%).

- **Raw tiles overcount.** Points near a tile edge are stored again in the neighbour's buffer
  (+7% on hospitals). A line or polygon is one row per tile it touches: Texas's 254 counties came
  back as 1,881 rows, and 345 kV lines were overcounted by 44%.
- **Merging fixes it, and needs ids.** Merged counts were exact except 345 kV lines (2,598 vs
  2,600): 803 lines, all 2 to 71 m long, are missing from the tiles even at the top zoom because
  tippecanoe drops lines too small to draw. Lengths were within 0.1%.
- **Lower zooms drop features.** The tiles were built with `--drop-densest-as-needed`, so point
  counts two zooms down are short by 80% to 95%, and proximity lists lose most of their members.
  Polygon layers keep every feature at lower zooms, so county and territory answers held.
- **The answer key has flaws too.** The largest service territory (WAPA) is 1,829,047 km² by
  `ST_Area` in the GeoParquet but 1,516,903 km² after `ST_MakeValid`; 254 of 2,931 territory
  polygons are invalid. The merged tiles say 1,672,977 km² (−8.5%), between the two.
- **Proximity was right at the top zoom** even though points sit on a grid of about 150 m at
  zoom 6. None of our seven questions had a feature close enough to its cut-off to move.

Bytes and time (medians, top zoom, merged):

| Question kind | Tile MB | GeoParquet MB | Tile s | GeoParquet s |
|---|---:|---:|---:|---:|
| Proximity (7) | 0.05 | 2.15 | 0.33 | 0.19 |
| Totals (14) | 6.93 | 28.42 | 38.7 | 0.31 |

Attribute counts (hospitals in Texas, solar plants) read 0.04 to 0.09 MB of GeoParquet against
1.2 to 9.0 MB of tiles. Tile times are our pure-Python decoder and merge, which is slow on
whole layers (about a minute to glue 67,000 territory pieces); a compiled reader would be
faster, but it can't avoid fetching every tile.

**Which file for which question** (`outputs/guide.csv`): proximity → PMTiles at the top zoom;
length totals → PMTiles at the top zoom merged by id (fewer bytes, slower); counts and areas →
GeoParquet. Never answer a total from a tile reader that doesn't merge by id, or below the top zoom.

**Feature ids.** Every tile feature has an id, which is enough to glue pieces inside one tileset.
But on all 7 layers the id matches neither `OBJECTID` nor the row order of the GeoParquet: it's a
number from the build, so it can't be joined back and may change with the next version.
tippecanoe's `--use-attribute-for-id=OBJECTID` (with `-aI` for numeric strings) would make it
stable; MVT ids must be unsigned integers, so layers keyed by a string (`GLOBALID`) or with no key
(power plants) need an integer key added first. The two files of one version also disagree on
columns: the hospital tiles call the source key `ID`, the GeoParquet `source_ID`.

## What we looked at first

vgi-mvt was the reader the issue named. Its worker installs from GitHub, which this machine's
policy blocked, so we used the two libraries vgi-mvt's own conformance tests check against
(`mapbox-vector-tile`, `pmtiles`) and copied its three `tile_edges` modes. GDAL's `ST_Read`
behaves like our raw mode. We wrote the directory walk and the merge ourselves (about 150 lines).

## What this doesn't show

- **vgi-mvt itself.** We reproduced its modes, not its code. Its merge also joins pieces without
  ids when they meet at a tile edge, which we didn't implement.
- **Other tilesets.** HIFLD Next's tiles use `-zg`, which picked low top zooms (5 to 10). Tiles
  built to zoom 14 would round less and drop fewer small lines, and be much bigger.
- **An agent choosing the file.** We skipped the optional agent step.
- **Edge cases for proximity.** Seven questions, none near a cut-off. Rounding of up to ~150 m
  (zoom 6) to ~300 m (zoom 5) will flip answers for features near the distance.
- **Real-world timings.** Times are on local files on one cloud machine; bytes are what a remote
  reader would fetch.
