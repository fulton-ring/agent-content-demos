# Can we rebuild the layers of Regrid and Mireye from public sources?

[Regrid](https://regrid.com) sells US parcel data with add-ons for buildings, addresses, zoning and ownership.
[Mireye](https://www.mireye.com) is a Y Combinator (Summer 2026) start-up selling "physical world context for AI
agents": one API and MCP server answering questions about a place with cited fields. This spike lists every layer
both vendors advertise, rates each one **public and easy**, **public but scattered** (public record, but only county
by county) or **proprietary**, and tests the parcel layers in three counties. Issue
[#129](https://github.com/fulton-ring/agent-content-demos/issues/129).

Everything is in one marimo notebook, [`layers.py`](layers.py). The ratings, with a quote and link for each, are in
[`inventory/`](inventory/).

## How to run it

```bash
./run.sh     # needs uv; ~5 min the first time (Overture buildings from S3), ~2 min after
```

To read it as a notebook: `uv run marimo edit layers.py`. Downloads go to `data/` (not committed); results to
`output/`.

## The data

All public, read at run time. We used no logins, vendor accounts or paid services, and record no owner names (owner
fields are only counted).

| Source | What we use |
|---|---|
| Regrid docs ([support.regrid.com](https://support.regrid.com/llms.txt)) | the 40 layers in `inventory/regrid_layers.csv`, each with a quote |
| Regrid [coverage report](https://docs.google.com/spreadsheets/d/1rvRYv6_ppZlwbmyi2kbzemot6FOEm2EEPdHPyENTQPE/htmlview) | per-county parcel counts, refresh dates and fill rates for every field; building, address and zoning tabs |
| Mireye [`/v1/meta/fields`](https://api.mireye.com/v1/meta/fields), [`/v1/enrich/fields`](https://api.mireye.com/v1/enrich/fields) | its whole field catalog with each field's source, public without a key |
| County and state ArcGIS services | parcels, zoning, address points in three counties (`inventory/county_sources.csv`) |
| FEMA NFHL, Census TIGERweb 2020 | flood zones and FIRM panel dates; county outlines and 2020 housing units |
| [Overture Maps](https://docs.overturemaps.org/) 2026-10-21.0 | buildings (OSM, Microsoft, Esri) and addresses (NAD) inside each county |

The three counties are **Wake NC** (urban; county and state publish parcels), **Fergus MT** (rural; Montana's free
statewide cadastral) and **Gordon GA** (no open parcels: a view-only qPublic site whose terms forbid scraping, and a
GIS file sold at $300 a layer).

## Results (from one clean `./run.sh`)

**The catalogs** (`output/regrid_layers_rated.csv`, `output/mireye_sources_rated.csv`, chart in `output/ratings.png`):

| | Public and easy | Public but scattered | Proprietary |
|---|---:|---:|---:|
| Regrid, 40 layers | 12 | 17 | 11 |
| Mireye, 538 fields | 358 | 15 | 165 |

- **Regrid.** The 17 scattered layers are the county record itself: boundaries, owners, values, sales, land use,
  building attributes. The 11 proprietary ones are bought from partners (ATTOM deeds, Zoneomics zoning, EarthDefine
  buildings, Ageon unit addresses, USPS validation, Esri demographics, NatureServe) or are Regrid's own IDs and its
  land-use crosswalk. The 12 easy ones (FEMA flood, NRI, Census, PLSS, elevation, transmission distance, cropland,
  PAD-US) are free federal layers joined to parcels.
- **Mireye.** 358 fields come from 94 public national datasets (USGS, FEMA, EPA, EIA, NREL, Overture and others),
  each linked in its catalog. 15 clip public layers to a parcel. The 165 proprietary fields are its parcel records,
  labelled only `PARCEL_VENDOR`. **161 of the 165 have the same names as Regrid's columns**: Mireye's parcel layer is
  Regrid's, resold. Its terms forbid reconstructing it.

**Regrid's freshness against its claims** (`output/summary.csv`), from its own report of 3,229 counties:

- 87.6% of counties and 92.3% of parcels were refreshed in the last 365 days. Regrid targets "over 3,000 counties
  (92%)" and says "on average 94% of our parcels". The median county is 95 days old; 121 counties are over two
  years old, the oldest from 2021-09-28.
- Advertised fields can be nearly empty (`output/regrid_thin_fields.csv`): tax amount is 14% filled nationwide and
  0% in 2,697 counties; land use code is 0% in 1,373; FEMA flood zone, a free layer, is 0% in 758.
- 4 small counties have fewer than half as many parcels as homes, so are partial (LA St. Helena: 55 parcels for
  5,243 homes).
- Product pages disagree with the report and with each other (`output/regrid_claims.csv`): addresses are "more than
  73 million" on one page and "more than 180 million" on another (the report has 180.1 million).

**The three counties** (`output/county_side_by_side.csv`, `output/county_field_fill.csv`):

| | Wake NC public / Regrid | Fergus MT public / Regrid | Gordon GA public / Regrid |
|---|---|---|---|
| Parcels | 439,398 / 435,472 | 20,862 / 20,831 | none official / 28,899 |
| Buildings (Overture) | 418,892 / 474,941 | 17,602 / 24,297 | 33,517 / 43,195 |
| Addresses | 674,404 / 582,793 | 9,614 / 9,215 | 0 / 31,415 |
| Zoning | 15 town and county layers / 434,361 parcels | none found / 2,937 parcels | city only / 28,874 parcels |
| Latest FIRM panel | 2022-07-19 | 2010-07-22 | 2008-09-26 |

- **Wake:** the county and state layers carry every field Regrid fills (owner, address, value, sale, use, year
  built, all within a few points of Regrid's fill). The county's layer has sales to 2026-10-21; Regrid's copy is from
  2026-06-24.
- **Fergus:** parcels and addresses are public through Montana. Montana's property type is 99% filled where
  Regrid's land use code is 0%. Regrid has sale dates on 78% of parcels in a state that doesn't disclose sales.
  We found no machine-readable zoning, yet Regrid reports 2,937 parcels in a standardized zone.
- **Gordon:** no open parcels or addresses. Regrid's 28,899 parcels with owners and values are bought from a county
  that sells them. A City of Calhoun utility server exposes county-wide parcel shapes with no attributes or licence;
  we count it as a finding, not a source.
- **Open buildings** reach 72–88% of Regrid's licensed building counts.

## What the spike shows

**Of Regrid's layers, 30% are free and national, 42% are public but scattered and 27% are proprietary. Two thirds
of Mireye's fields are free and national, and nearly all the rest is Regrid's parcel layer.** An open rebuild
covers Mireye's whole catalog except the parcels.
For Regrid, the scattered county record is the real product. Where a state publishes it (North Carolina, Montana),
an open rebuild matches Regrid's counts and fields, and can be fresher. Where a county sells it (Gordon), it can't.
The genuinely proprietary layers are the partner add-ons: unit addresses, USPS vacancy, daily deeds, standardized
zoning, and lidar buildings and heights. Regrid's own report shows the advertised layers are thinner and older than
its marketing in places. Its freshness misses its stated targets, several fields are near-empty in most counties,
and its zoning claims include a county where we found no machine-readable zoning.

## What this doesn't show

- **Ratings are judgement**, one line of reason each. A statewide program makes a scattered layer easy for that
  state only.
- **Three counties are examples, not a sample.** The national numbers are Regrid's own report.
- **Counts aren't quality.** We didn't compare boundaries or values record by record.
- **Freshness is a proxy:** the newest date in a layer's date field. Montana's cadastral has none.
- **Mireye's values weren't tested.** Calling its Fetch API needs a key from a sign-up, so we rated its catalog only.
- **What failed:** `field <> ''` matches nothing on servers that store empty strings as NULL, so the first run
  showed Wake's own layer with 0% owners (`CHAR_LENGTH(field) > 0` works). `api.census.gov` now needs a key, so we
  took housing units from TIGERweb. The National Address Database times out on attribute filters, so we query it by
  bounding box, which counts neighbours too.

## What we looked at first

Each vendor's public docs and catalog endpoints, Regrid's published coverage report rather than its paid API, ArcGIS
REST `returnCountOnly` and `outStatistics` for counts and dates, and DuckDB's httpfs and spatial extensions over
Overture's GeoParquet (as in `hifld-overture-crosswalk/`). We wrote no code beyond the notebook.
