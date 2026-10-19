# What do the HIFLD power plant, substation and transmission line layers leave out?

People treat the public HIFLD electric layers, now preserved in [HIFLD Next](https://hifld.publicenvirodata.org), as
the map of the US grid. This spike makes one pass over them against three outside references: EIA-860 for battery
storage, OpenStreetMap substations for line connectivity, and USGS's once-per-century geoelectric hazard for
substations. Issue [#50](https://github.com/fulton-ring/agent-content-demos/issues/50).

Everything is in one marimo notebook, [`grid_gaps.py`](grid_gaps.py), in three sections with a table and a map each.

## How to run it

```bash
./run.sh            # needs uv; downloads ~100 MB into data/ on the first run, then writes output/
./run.sh --chips    # also redraws the aerial-imagery chips behind hand_check.csv (data/chips/)
```

To read it as a notebook: `uv run marimo edit grid_gaps.py`. The first run takes about 5 minutes, most of it the
Overture query; later runs reuse `data/` and take about 20 seconds.

## The data

All of it is public and downloaded at run time; nothing downloaded is committed. `output/provenance.csv` records the
URL and download time of every file.

| Source | What we use | Version |
|---|---|---|
| [HIFLD Next](https://hifld.publicenvirodata.org) | Power Plants, Generating Units, Transmission Lines (GeoParquet/GeoPackage) | layer v1.0.0 (release `1704edb3`; the URL is not hash-pinned), downloaded 2026-10-18 |
| [EIA-860](https://www.eia.gov/electricity/data/eia860/) | Plant and Energy Storage schedules | 2025 annual (final), released September 2026 |
| [Overture Maps](https://docs.overturemaps.org/) | `base/infrastructure`, `class = substation` (OpenStreetMap data, ODbL) | release 2026-09-23.0 |
| USGS, [Lucas et al. 2020](https://doi.org/10.1029/2019SW002329) | 100-year geoelectric field at 1,079 magnetotelluric sites | the paper's CSV at [commit `856374c`](https://github.com/greglucas/GeoelectricHazardPaper2019/blob/856374c4aa0a96f149915712d5b7cc3e017d1507/code/geoelectric_100year.csv) |
| US Census | state boundaries 1:20m | 2024 cartographic boundary file |

**HIFLD Next has no Electric Substations layer.** DHS withdrew HIFLD's substation layer from public access in 2022
([data.gov](https://catalog.data.gov/dataset/electric-substations-c633a) lists it as "restricted public"), so it was not
on HIFLD Open when HIFLD Next preserved it. We use OpenStreetMap's substations, via Overture, in its place.

The HIFLD layers are old. Every Generating Units record is dated 2023-09-01; the newest Power Plants record 2024-06-12;
the newest Transmission Lines record is older still. Nothing has refreshed them since HIFLD Open shut down in 2025.

## Results (run of 2026-10-18)

**Storage.** EIA-860 2025 lists 1,003 operable battery generators, 43,643 MW. Generating Units lists 685 of them
(26,798 MW, 61%). Matching in order:

| Match | Generators | MW | Share of MW |
|---|---:|---:|---:|
| Unit in Generating Units | 685 | 26,798 | 61% |
| Plant code in Power Plants, unit not listed | 126 | 6,708 | 15% |
| A HIFLD plant within 1 km | 54 | 1,955 | 4% |
| Missing from the map | 138 | 8,181 | 19% |

Most of the gap is age: 454 generators (30,854 MW) started after August 2023, the layer's source date; 190 of those
are in Generating Units, but as planned units (one as cancelled), not operating ones. Of the battery generators operating by August 2023, 54 (548 MW) are
not in Generating Units. Texas has the most unlisted battery capacity (7,056 MW), then Arizona and California
(`output/storage_by_state.csv`). EIA's threshold is 1 MW of combined nameplate per plant, so home and most commercial
batteries are in neither source by design; we don't count them.

**Connectivity.** 93,962 lower-48 lines have 187,924 ends.

| Distance | Ends farther than this from any OSM substation | ...and from any HIFLD plant, touching no other line |
|---|---:|---:|
| 50 m | 50,011 (27%) | 1,734 (0.9%) |
| 250 m | 36,691 (20%) | 1,479 (0.8%) |
| 1 km | 22,638 (12%) | 1,008 (0.5%) |

We hand-checked 50 random ends from the 22,638 that are more than 1 km from a substation, on aerial imagery
([`hand_check.csv`](hand_check.csv)): **43 taps or interconnections** (39 branch off another line, 4 are breaks where
the line continues as another segment), **2 ends at a plant**, **1 data error**, **4 unclear**. HIFLD's lines are
segments that break at every branch, not a network that runs substation to substation, and 86% of the far ends carry a
placeholder substation name (`TAP...`, `UNKNOWN...` or `NOT AVAILABLE`) in `SUB_1`/`SUB_2`.

**Geomagnetic hazard.** OpenStreetMap has 72,249 substations in the lower 48, about 5,300 more than the 66,935 in
Microsoft Research's space-weather model; HIFLD Next has none. 54,720 of them are within 100 km of a USGS survey site;
**6,272 (11%)** of those sit where the once-per-century geoelectric field is 3 V/km or more, 919 of them at 10 V/km or
more. New Jersey (897), North Carolina (886), New York (642), Minnesota (513) and Pennsylvania (448) have the most.
17,529 substations, mostly in the Southeast, Texas and the southern Plains, have no survey site nearby and are unrated.

## What the spike shows

The argument holds, but not in the shape we expected. The biggest gap is the substation layer that isn't there at
all. The storage gap is real (19% of battery MW is nowhere on the map, 39% isn't listed as a unit) but is mostly the
layers' age, not a blind spot in how they were built. The connectivity gap is mostly not a gap: line ends that meet no
substation are almost all taps, so a raw count of floating ends would mostly be counting taps.

## What didn't work, and what this doesn't show

- **Overpass failed.** Pulling OSM substations from the Overpass API reset or timed out on three servers. Overture's
  GeoParquet on S3 worked and is versioned, so it's the reproducible choice.
- **EIA-860 is fetched from an unversioned URL** (`eia8602025.zip`). EIA revises annual files in place, so a later
  run may shift the storage numbers slightly; `output/provenance.csv` records the download date.
- **Connectivity is tested against OSM, not HIFLD.** A line end at a substation OSM hasn't mapped counts as floating.
  The 4 unclear ends include one at a named HIFLD substation with no clear yard on imagery.
- **The hazard rating is by nearest survey site within 100 km**, not the paper's mapped cells, and the unsurveyed
  third of the lower 48 is unrated. We didn't compute line voltages, which is what the paper's hazard map shows.
- **We couldn't compare substation lists with Microsoft's**; its list isn't published with the blog post, only the
  count.
- **We hand-checked the general pool of far ends**, not the 1,008 dead ends. Those are where data errors would
  concentrate; a second sample of them would size the error rate.
- Generating Units has no coordinates, so its location match goes through Power Plants or EIA's coordinates.
- Out of scope: storage below EIA's threshold, on-site generation at data centers, satellite detection, and anything
  about utilities' own GIS.

## What we looked at first

GeoPandas for the spatial joins, DuckDB's spatial and httpfs extensions for Overture, and marimo for the notebook. We
wrote no matching logic beyond joins on EIA's own IDs and nearest-neighbour distances.
