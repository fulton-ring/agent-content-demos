`python query.py journal_entries_by_user user=GL.ACCT from=2026-05-01 to=2026-05-31`

| journal_entry | date | source | reference | account | description | debit | credit | customer_or_vendor | document |
|---:|---|---|---|---|---|---:|---:|---|---|
| 13039 | 2026-05-01 | GJ | Reverse utilities accrual | 000-2200-00 | Accrued Liabilities | 7,170.05 | 0.00 |  |  |
| 13039 | 2026-05-01 | GJ | Reverse utilities accrual | 000-6200-00 | Utilities Expense | 0.00 | 7,170.05 |  |  |
| 13179 | 2026-05-14 | GJ | Office furniture reclass | 000-1500-00 | Furniture and Equipment | 12,345.67 | 0.00 |  |  |
| 13179 | 2026-05-14 | GJ | Office furniture reclass | 000-6300-00 | Office Supplies | 0.00 | 12,345.67 |  |  |
