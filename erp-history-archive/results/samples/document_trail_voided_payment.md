`python query.py document_trail document=PMT0001500`

| part | date | party | detail | amount | account |
|---|---|---|---|---:|---|
| document | 2024-02-13 | C00013 | RM type 9, voided 2024-02-22 | 4,301.42 |  |
| journal entry 4287 | 2024-02-13 | AR.CLERK | Cash Receipts Entry | 4,301.42 | 000-1100-00 |
| journal entry 4287 | 2024-02-13 | AR.CLERK | Cash Receipts Entry | -4,301.42 | 000-1200-00 |
| journal entry 4395 | 2024-02-22 | AR.CLERK | Void NSF payment | 4,301.42 | 000-1200-00 |
| journal entry 4395 | 2024-02-22 | AR.CLERK | Void NSF payment | -4,301.42 | 000-1100-00 |
