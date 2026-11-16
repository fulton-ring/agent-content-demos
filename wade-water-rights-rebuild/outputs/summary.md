## Per state

|                              | California                                                                                             | Colorado                                                                                                      | Wyoming                                                                                                                     |
|:-----------------------------|:-------------------------------------------------------------------------------------------------------|:--------------------------------------------------------------------------------------------------------------|:----------------------------------------------------------------------------------------------------------------------------|
| WaDE count                   | 41,276                                                                                                 | 162,646                                                                                                       | 45,272                                                                                                                      |
| Rebuilt count                | 44,030                                                                                                 | 163,382                                                                                                       | 66,431                                                                                                                      |
| WaDE IDs matched             | 99.1%                                                                                                  | 99.8%                                                                                                         | 100.0%                                                                                                                      |
| Location within 100 m        | 95.7%                                                                                                  | 99.8%                                                                                                         | 100.0%                                                                                                                      |
| Rights WaDE's checks dropped | 1,949                                                                                                  | 453                                                                                                           | 21,158                                                                                                                      |
| Fields back (≥95%)           | PriorityDate                                                                                           | PriorityDate, LegalStatusCV, TypeCV, Flow_CFS, Volume_AF, BeneficialUseCategory, PrimaryBeneficialUseCategory | Owner, PriorityDate, LegalStatusCV, TypeCV, Flow_CFS, BeneficialUseCategory, PrimaryBeneficialUseCategory, IrrigatedAcreage |
| Fields not back              | Owner, LegalStatusCV, TypeCV, Flow_CFS, Volume_AF, BeneficialUseCategory, PrimaryBeneficialUseCategory | none                                                                                                          | none                                                                                                                        |
| Newest record                | 2026-09-26                                                                                             | 2026-11-13                                                                                                    | 2019-02-15                                                                                                                  |
| Source updated               | 2026-11-16                                                                                             | 2026-11-15                                                                                                    | 2019-03-02                                                                                                                  |
| Update frequency             | Weekly                                                                                                 | Daily                                                                                                         | None (one-off export)                                                                                                       |
| Run time (s)                 | 23.2                                                                                                   | 62.7                                                                                                          | 27.8                                                                                                                        |

## Field agreement on matched rights

|                              | California              | Colorado            | Wyoming             |
|:-----------------------------|:------------------------|:--------------------|:--------------------|
| AllocationOwner              | 0.0% (no source column) | blank in WaDE       | 97.0% (comes back)  |
| AllocationPriorityDate       | 100.0% (comes back)     | 100.0% (comes back) | 100.0% (comes back) |
| AllocationLegalStatusCV      | 35.2% (differs)         | 100.0% (comes back) | 100.0% (comes back) |
| AllocationTypeCV             | 29.0% (differs)         | 100.0% (comes back) | 100.0% (comes back) |
| AllocationFlow_CFS           | 89.6% (partly)          | 99.9% (comes back)  | 100.0% (comes back) |
| AllocationVolume_AF          | 0.0% (differs)          | 100.0% (comes back) | blank in WaDE       |
| BeneficialUseCategory        | 55.9% (partly)          | 99.9% (comes back)  | 99.9% (comes back)  |
| PrimaryBeneficialUseCategory | 77.6% (partly)          | 100.0% (comes back) | 99.9% (comes back)  |
| IrrigatedAcreage             | blank in WaDE           | blank in WaDE       | 100.0% (comes back) |

California crosswalk learned from WaDE's last table: LegalStatusCV: 35 rows restore 93%; TypeCV: 41 rows restore 94%.
