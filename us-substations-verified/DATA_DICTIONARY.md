# Data dictionary: US substations, HIFLD-derived and OpenStreetMap

Written by `verify.py` (`./run.sh`). Three files in `dataset/`:

| File | Rows | Licence |
|---|---|---|
| `us_substations.parquet` (GeoParquet, EPSG:4326 points) | every derived substation, plus every OSM substation with no derived substation within 1 km | ODbL 1.0 |
| `us_substations.csv` | the same rows, with `lon` and `lat` instead of a geometry | ODbL 1.0 |
| `us_substations_hifld_only.csv` | derived substations only, with no OSM-derived field | public domain (US government work) |

## Columns

| Column | Type | Meaning |
|---|---|---|
| `id` | text | `hifld-node-<n>` for a substation derived from HIFLD Next line ends (the node number in this run), or `osm-<Overture id>` for an OSM-only substation. Stable only for a given HIFLD and Overture release. |
| `name` | text | The HIFLD `SUB_1`/`SUB_2` name shared by the lines that end there. When that's a placeholder (`UNKNOWN…`, `NOT AVAILABLE`) and an OSM substation is within 1 km, the OSM name. OSM-only rows carry the OSM name. Blank if neither has one. |
| `max_kv` | number | Highest voltage known for the substation, in kV: the higher of `hifld_kv` and `osm_kv`. Blank if neither source records one. |
| `hifld_kv` | number | Highest voltage of the HIFLD Next lines ending there (missing voltages, `-999999`, ignored). Blank for OSM-only rows. |
| `osm_kv` | number | Highest value in the matched OSM substation's `voltage` tag, in kV. Blank if unmatched, or the tag is missing or has no number. |
| `source` | text | `both`: derived, with an OSM substation within 1 km. `derived`: derived, no OSM substation within 1 km. `osm`: in OSM, no derived substation within 1 km. |
| `osm_id` | text | Overture id of the nearest OSM substation, for `both` and `osm` rows. |
| `match_m` | number | For derived rows, metres to the nearest OSM substation (its outline, if mapped as an area). For `osm` rows, metres to the nearest derived substation. |
| `fips` | text | 5-digit county FIPS (Census 2024 cartographic boundaries) the point falls in. |
| `state` | text | Two-letter state code. |
| `county_restricted` | true/false | The county has a county-level wind or solar ordinance in effect in the Sabin Center's restriction data (edition in `outputs/run_log.txt`). State laws and town or township ordinances are not counted. |
| `lon`, `lat` | number | WGS84 coordinates (CSV only). An OSM substation mapped as an area is placed at a point inside it. |

The HIFLD-only file has `id`, `name` (HIFLD name only, no OSM fallback), `hifld_kv`, `fips`, `state`,
`county_restricted`, `lon` and `lat`.

## How to read it

- A `derived` row is not confirmed by OSM. Our hand check of 50 such 230 kV+ points (`hand_check.csv`, README)
  says how many are real substations, taps or errors.
- A row is a point, not a facility record: one real substation can appear as two derived nodes when its
  line ends are more than 100 m apart, and several derived nodes can share one `osm_id`.
- Voltages are floors. 14% of derived substations have no voltage on any line that ends there, and many OSM
  substations have no `voltage` tag.

## Licences and attribution

**OpenStreetMap, via Overture Maps.** The `both` and `osm` rows and the `osm_kv`, `osm_id`, `match_m` and
fallback `name` fields come from OpenStreetMap data in Overture Maps' `base` theme, release 2026-09-23.0.
Overture publishes that theme under the Open Database License. The OSM part is Substantial (tens of thousands
of features), and the `both` rows merge OSM with HIFLD for the same feature type, which the OSMF Licensing
Working Group's Collective Database and Horizontal Layers guidelines say makes the result a Derivative
Database. So `us_substations.parquet` and `us_substations.csv` are released under ODbL 1.0
(<https://opendatacommons.org/licenses/odbl/1-0/>), and the method that made them is `verify.py` in this folder.

> Contains information from OpenStreetMap (© OpenStreetMap contributors) via Overture Maps Foundation, which is
> made available here under the Open Database License (ODbL).

**HIFLD Next.** Derived from the HIFLD Next Transmission Lines layer v1.0.0 (hifld.publicenvirodata.org), a
preserved copy of the HIFLD Open layer produced by Oak Ridge National Laboratory. The upstream metadata lists
access and use constraints as "None (Public Domain Information)". HIFLD Next itself publishes no licence page
(its catalog entry says `"license": "other"`), so we cite it as a source:

> Transmission Lines, Oak Ridge National Laboratory / HIFLD, public domain, via HIFLD Next.

Public-domain HIFLD data can sit inside an ODbL file, so mixing them doesn't block publication. The HIFLD-only
CSV carries no OSM-derived value. In it, OSM is never used to filter, move or rename a point, so it stays
public domain.

**Sabin Center.** `county_restricted` is a yes/no fact per county drawn from the Sabin Center for Climate
Change Law's *Opposition to Renewable Energy Facilities in the United States* restriction data
(oppositionreport.org). The site states no licence for the data. We publish only the flag, with this
citation, and none of Sabin's text. Asking the Sabin Center for written permission before wider promotion is
on the issue as an open question.

**Counties.** US Census Bureau 2024 cartographic boundary files, public domain.

The interactive map (`map/`) shows these rows and credits OpenStreetMap in its corner. Because its GeoJSON
files can be downloaded, they're under ODbL too.
