# Hand-check notes: the four named communities

Checked 2026-11-06 against FEMA's live NFHL MapServer
(`hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer`) and FEMA's Community
Status Book on OpenFEMA. Each point is a spot inside the community's largest piece in the
Community Layer (HIFLD Next copy, Comprehensive), the same point the notebook uses.

| CID | Community | Claims | Effective map (Status Book) | NFHL polygons under its CID | NFHL polygon at the point | FIRM panel at the point | Flood zone at the point |
|---|---|---|---|---|---|---|---|
| 220204 | Slidell, City of (LA) | 9,935 | 04/21/99 | 0 | "Saint Tammany Parish", CID 225205, from DFIRM `220202` | none | none |
| 220160 | St. Charles Parish (LA) | 7,603 | 06/16/92 | 0 | none | none | none |
| 485457 | Beaumont, City of (TX) | 7,312 | 08/06/02 | 0 | none | none | none |
| 485499 | Port Arthur, City of (TX) | 6,998 | 05/04/92 | 0 | none | `22023C0575H` (Cameron Parish, LA) | none |

## What each one shows

**Slidell.** No polygon under 220204. Its land sits inside a polygon labeled Saint Tammany
Parish, but that polygon belongs to DFIRM `220202`, which is the City of Mandeville's own
single-community map: all 12 polygons in the NFHL for St. Tammany Parish (county FIPS
22103) come from it, and the parish-wide DFIRM `22103C` has no polygons, panels or study
area in the NFHL. The only FIRM panels near Slidell's footprint belong to the neighboring
Orleans (`22071C`) and St. Bernard (`22087C`) parish maps; one Orleans panel touches about
7% of Slidell's Community Layer polygon at the edge of Lake Pontchartrain. So a county
crosswalk would drop Slidell's claims onto a parish polygon that has no flood map under it.
Cause: no digital flood map, with a political polygon drawn from a neighbor's map.

**St. Charles Parish.** County FIPS 22089 has no polygons in layer 22, no panels in layer 3
and no study area in layer 0 (NFHL Availability) under `22089C`. The parish's effective
map is from 1992. Cause: no digital flood map.

**Beaumont.** Jefferson County, Texas (FIPS 48245) has nothing in the NFHL: no polygons,
no panels, no study area under `48245C`, and the county's own CID (480385, 3,797 claims) is
missing too. Panels that overlap Beaumont's bounding box belong to the neighboring Hardin
(`48199C`), Orange (`48361C`) and Jasper (`48241C`) county maps. Cause: no digital flood map.

**Port Arthur.** Also in Jefferson County, so the same absence. The point inside its
largest piece lands on a Cameron Parish, Louisiana panel, because that panel extends over
Sabine Lake, which the Community Layer includes in Port Arthur's boundary. The NFHL
has no flood zone there, so the notebook files Port Arthur as no map. This case is why the
notebook tests for a flood zone (layer 28) and not a FIRM panel (layer 3): panel
rectangles run over county lines and water, and a first version that used panels wrongly
counted 312 communities, Port Arthur among them, as mapped.

## Takeaway

All four are real gaps in the NFHL, not CID bookkeeping: none has a digital flood map of
its own land in the NFHL. Three of the four (St. Charles, Beaumont, Port Arthur) sit in
counties with nothing in the NFHL at all.
