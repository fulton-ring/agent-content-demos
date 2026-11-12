# Sunrise Hospital bed count, answered three ways

### as shipped

Sunrise Hospital and Medical Center (3186 S Maryland Pkwy, Las Vegas, NV 89109) is listed with 834 beds in HIFLD's Hospitals dataset (v1.1.0, updated April 2026). It is classified as a General Acute Care hospital, open, and proprietary. The bed count comes from the BEDS field, and the record's source is the Nevada licensing search, dated 2024-04-19.

### instruction only

Sunrise Hospital and Medical Center (3186 S Maryland Pkwy, Las Vegas, NV 89109) is listed with 834 beds in the HIFLD Hospitals layer. The record is type GENERAL ACUTE CARE, status OPEN, owner PROPRIETARY. The bed count comes from the v1.1.0 release, which states it includes updated hospital bed counts. The bed figure is taken from that record as published; I did not verify it against the hospital or the Nevada licensing source.

Citation: HIFLD Hospitals (dataset slug hospitals-3, file hospitals-3.parquet), version v1.1.0, issued 2026-04-06. Retrieved through HIFLD Next (https://hifld.publicenvirodata.org) on the day of this query; I cannot confirm the exact calendar date from this session, so please record your own retrieval date. Source agency: HIFLD, with the hospital facility data originally drawn from the Nevada Division of Public and Behavioral Health license search (https://nvdpbh.aithent.com/Protected/LIC/LicenseeSearch.aspx, SOURCEDATE 2024-04-19). Producer: Niyam IT. License: CC-PDM-1.0. Reproduce with this SQL against hifld/hospitals-3/hospitals-3/v1.1.0, asset geoparquet-10a626eee8da: SELECT NAME, ADDRESS, CITY, BEDS FROM h WHERE UPPER(NAME) LIKE '%SUNRISE%' AND UPPER(CITY) LIKE '%LAS VEGAS%'

### proxy + instruction

Sunrise Hospital and Medical Center (3186 S Maryland Pkwy, Las Vegas, NV; type: General Acute Care; status: open) is listed with 834 beds in the HIFLD Hospitals dataset (v1.1.0, OBJECTID 12096). That version notes it includes updated hospital bed counts. The record's source date is 2024-04-19, and its validation date is 2013-11-27. Beds are a reported facility attribute, so this may differ from the hospital's current licensed or staffed count.

Citation: Layer: HIFLD Hospitals (hifld/hospitals-3/hospitals-3), version v1.1.0, retrieved 2026-11-12, source agency: Niyam IT (HIFLD Next host), license: CC-PDM-1.0. Data URL: https://hifld.publicenvirodata.org/storage/hifld/hospitals-3/hospitals-3/v1.1.0/geoparquet/hospitals-3.parquet. Query URL: https://hifld.publicenvirodata.org/features/collections/hifld~hospitals-3~hospitals-3~v1.1.0/items?OBJECTID=12096. Reproducing SQL: SELECT NAME, ADDRESS, CITY, STATE, BEDS, TYPE, STATUS, OBJECTID, SOURCEDATE, VAL_DATE FROM read_parquet('https://hifld.publicenvirodata.org/storage/hifld/hospitals-3/hospitals-3/v1.1.0/geoparquet/hospitals-3.parquet') AS h WHERE CITY = 'LAS VEGAS' AND NAME LIKE '%SUNRISE%'
