-- The same reports, recomputed in DuckDB from the archive alone.
-- The trial balance here is built from the journal lines (GL20000 and GL30000),
-- not from GP's summary tables, so it checks the summary against the detail as
-- well as checking the copy.

-- name: trial_balance
WITH lines AS (
  SELECT ACTINDX, OPENYEAR AS YEAR1, PERIODID, DEBITAMT, CRDTAMNT FROM gp.GL20000
  UNION ALL
  SELECT ACTINDX, HSTYEAR AS YEAR1, PERIODID, DEBITAMT, CRDTAMNT FROM gp.GL30000
),
per AS (
  SELECT ACTINDX, YEAR1, PERIODID, SUM(DEBITAMT) AS dr, SUM(CRDTAMNT) AS cr FROM lines GROUP BY ALL
),
periods AS (
  SELECT YEAR1, PERIODID FROM gp.SY40100 WHERE SERIES = 0 AND PERIODDT <= :asof_last
)
SELECT p.YEAR1 AS year, p.PERIODID AS period, a.ACTNUMST AS account,
  CAST(COALESCE(SUM(x.dr - x.cr) FILTER (WHERE x.PERIODID < p.PERIODID), 0) AS DECIMAL(19,2)) AS beginning,
  CAST(COALESCE(SUM(x.dr) FILTER (WHERE x.PERIODID = p.PERIODID), 0) AS DECIMAL(19,2)) AS debit,
  CAST(COALESCE(SUM(x.cr) FILTER (WHERE x.PERIODID = p.PERIODID), 0) AS DECIMAL(19,2)) AS credit,
  CAST(COALESCE(SUM(x.dr - x.cr) FILTER (WHERE x.PERIODID <= p.PERIODID), 0) AS DECIMAL(19,2)) AS ending
FROM periods p CROSS JOIN gp.GL00105 a
LEFT JOIN per x ON x.ACTINDX = a.ACTINDX AND x.YEAR1 = p.YEAR1
GROUP BY p.YEAR1, p.PERIODID, a.ACTNUMST
ORDER BY year, period, account;

-- name: ar_aging
WITH period_ends AS (
  SELECT PERDENDT AS d FROM gp.SY40100 WHERE SERIES = 0 AND PERIODDT <= :asof_last
),
docs AS (
  SELECT CUSTNMBR, DOCNUMBR, RMDTYPAL, DOCDATE, DUEDATE, ORTRXAMT, VOIDSTTS, VOIDDATE FROM gp.RM20101
  UNION ALL
  SELECT CUSTNMBR, DOCNUMBR, RMDTYPAL, DOCDATE, DUEDATE, ORTRXAMT, VOIDSTTS, VOIDDATE FROM gp.RM30101
),
applies AS (
  SELECT APFRDCTY, APFRDCNM, APTODCTY, APTODCNM, APPTOAMT, DATE1 FROM gp.RM20201
  UNION ALL
  SELECT APFRDCTY, APFRDCNM, APTODCTY, APTODCNM, APPTOAMT, DATE1 FROM gp.RM30201
),
applied_to AS (
  SELECT a.d, p.APTODCNM AS doc, p.APTODCTY AS typ, SUM(p.APPTOAMT) AS amt
  FROM period_ends a JOIN applies p ON p.DATE1 <= a.d GROUP BY ALL
),
applied_from AS (
  SELECT a.d, p.APFRDCNM AS doc, p.APFRDCTY AS typ, SUM(p.APPTOAMT) AS amt
  FROM period_ends a JOIN applies p ON p.DATE1 <= a.d GROUP BY ALL
),
open_at AS (
  SELECT a.d, x.CUSTNMBR, x.RMDTYPAL, x.DUEDATE,
    CASE WHEN x.RMDTYPAL < 7 THEN x.ORTRXAMT - COALESCE(t.amt, 0)
         ELSE -(x.ORTRXAMT - COALESCE(f.amt, 0)) END AS remaining
  FROM period_ends a
  JOIN docs x ON x.DOCDATE <= a.d AND NOT (x.VOIDSTTS = 1 AND x.VOIDDATE <= a.d)
  LEFT JOIN applied_to t ON t.d = a.d AND t.doc = x.DOCNUMBR AND t.typ = x.RMDTYPAL
  LEFT JOIN applied_from f ON f.d = a.d AND f.doc = x.DOCNUMBR AND f.typ = x.RMDTYPAL
)
SELECT strftime(d, '%Y-%m-%d') AS as_of, CUSTNMBR AS customer,
  CAST(SUM(CASE WHEN RMDTYPAL < 7 AND date_diff('day', DUEDATE, d) <= 0 THEN remaining ELSE 0 END) AS DECIMAL(19,2)) AS not_due,
  CAST(SUM(CASE WHEN RMDTYPAL < 7 AND date_diff('day', DUEDATE, d) BETWEEN 1 AND 30 THEN remaining ELSE 0 END) AS DECIMAL(19,2)) AS days_1_30,
  CAST(SUM(CASE WHEN RMDTYPAL < 7 AND date_diff('day', DUEDATE, d) BETWEEN 31 AND 60 THEN remaining ELSE 0 END) AS DECIMAL(19,2)) AS days_31_60,
  CAST(SUM(CASE WHEN RMDTYPAL < 7 AND date_diff('day', DUEDATE, d) BETWEEN 61 AND 90 THEN remaining ELSE 0 END) AS DECIMAL(19,2)) AS days_61_90,
  CAST(SUM(CASE WHEN RMDTYPAL < 7 AND date_diff('day', DUEDATE, d) > 90 THEN remaining ELSE 0 END) AS DECIMAL(19,2)) AS days_over_90,
  CAST(SUM(CASE WHEN RMDTYPAL >= 7 THEN remaining ELSE 0 END) AS DECIMAL(19,2)) AS unapplied_credits,
  CAST(SUM(remaining) AS DECIMAL(19,2)) AS balance
FROM open_at
WHERE remaining <> 0
GROUP BY d, CUSTNMBR
ORDER BY as_of, customer;

-- name: ap_aging
WITH period_ends AS (
  SELECT PERDENDT AS d FROM gp.SY40100 WHERE SERIES = 0 AND PERIODDT <= :asof_last
),
docs AS (
  SELECT VENDORID, VCHRNMBR, DOCTYPE, DOCDATE, DUEDATE, DOCAMNT, VOIDED, VOIDPDATE FROM gp.PM20000
  UNION ALL
  SELECT VENDORID, VCHRNMBR, DOCTYPE, DOCDATE, DUEDATE, DOCAMNT, VOIDED, VOIDPDATE FROM gp.PM30200
),
applies AS (
  SELECT APFRDCNM, DOCTYPE, APTVCHNM, APTODCTY, APPLDAMT, DATE1 FROM gp.PM10200
  UNION ALL
  SELECT APFRDCNM, DOCTYPE, APTVCHNM, APTODCTY, APPLDAMT, DATE1 FROM gp.PM30300
),
applied_to AS (
  SELECT a.d, p.APTVCHNM AS doc, p.APTODCTY AS typ, SUM(p.APPLDAMT) AS amt
  FROM period_ends a JOIN applies p ON p.DATE1 <= a.d GROUP BY ALL
),
applied_from AS (
  SELECT a.d, p.APFRDCNM AS doc, p.DOCTYPE AS typ, SUM(p.APPLDAMT) AS amt
  FROM period_ends a JOIN applies p ON p.DATE1 <= a.d GROUP BY ALL
),
open_at AS (
  SELECT a.d, x.VENDORID, x.DOCTYPE, x.DUEDATE,
    CASE WHEN x.DOCTYPE < 4 THEN x.DOCAMNT - COALESCE(t.amt, 0)
         ELSE -(x.DOCAMNT - COALESCE(f.amt, 0)) END AS remaining
  FROM period_ends a
  JOIN docs x ON x.DOCDATE <= a.d AND NOT (x.VOIDED = 1 AND x.VOIDPDATE <= a.d)
  LEFT JOIN applied_to t ON t.d = a.d AND t.doc = x.VCHRNMBR AND t.typ = x.DOCTYPE
  LEFT JOIN applied_from f ON f.d = a.d AND f.doc = x.VCHRNMBR AND f.typ = x.DOCTYPE
)
SELECT strftime(d, '%Y-%m-%d') AS as_of, VENDORID AS vendor,
  CAST(SUM(CASE WHEN DOCTYPE < 4 AND date_diff('day', DUEDATE, d) <= 0 THEN remaining ELSE 0 END) AS DECIMAL(19,2)) AS not_due,
  CAST(SUM(CASE WHEN DOCTYPE < 4 AND date_diff('day', DUEDATE, d) BETWEEN 1 AND 30 THEN remaining ELSE 0 END) AS DECIMAL(19,2)) AS days_1_30,
  CAST(SUM(CASE WHEN DOCTYPE < 4 AND date_diff('day', DUEDATE, d) BETWEEN 31 AND 60 THEN remaining ELSE 0 END) AS DECIMAL(19,2)) AS days_31_60,
  CAST(SUM(CASE WHEN DOCTYPE < 4 AND date_diff('day', DUEDATE, d) BETWEEN 61 AND 90 THEN remaining ELSE 0 END) AS DECIMAL(19,2)) AS days_61_90,
  CAST(SUM(CASE WHEN DOCTYPE < 4 AND date_diff('day', DUEDATE, d) > 90 THEN remaining ELSE 0 END) AS DECIMAL(19,2)) AS days_over_90,
  CAST(SUM(CASE WHEN DOCTYPE >= 4 THEN remaining ELSE 0 END) AS DECIMAL(19,2)) AS unapplied_credits,
  CAST(SUM(remaining) AS DECIMAL(19,2)) AS balance
FROM open_at
WHERE remaining <> 0
GROUP BY d, VENDORID
ORDER BY as_of, vendor;

-- name: customer_history
WITH docs AS (
  SELECT CUSTNMBR, RMDTYPAL, DOCDATE, ORTRXAMT, VOIDSTTS FROM gp.RM20101
  UNION ALL
  SELECT CUSTNMBR, RMDTYPAL, DOCDATE, ORTRXAMT, VOIDSTTS FROM gp.RM30101
)
SELECT CUSTNMBR AS customer, year(DOCDATE) AS year,
  count(*) FILTER (WHERE RMDTYPAL = 1) AS invoices,
  CAST(COALESCE(SUM(ORTRXAMT) FILTER (WHERE RMDTYPAL = 1), 0) AS DECIMAL(19,2)) AS invoiced,
  CAST(COALESCE(SUM(ORTRXAMT) FILTER (WHERE RMDTYPAL = 7), 0) AS DECIMAL(19,2)) AS credit_memos,
  count(*) FILTER (WHERE RMDTYPAL = 9 AND VOIDSTTS = 0) AS payments,
  CAST(COALESCE(SUM(ORTRXAMT) FILTER (WHERE RMDTYPAL = 9 AND VOIDSTTS = 0), 0) AS DECIMAL(19,2)) AS paid,
  count(*) FILTER (WHERE VOIDSTTS = 1) AS voided
FROM docs
GROUP BY ALL
ORDER BY customer, year;

-- name: vendor_history
WITH docs AS (
  SELECT VENDORID, DOCTYPE, DOCDATE, DOCAMNT, VOIDED FROM gp.PM20000
  UNION ALL
  SELECT VENDORID, DOCTYPE, DOCDATE, DOCAMNT, VOIDED FROM gp.PM30200
)
SELECT VENDORID AS vendor, year(DOCDATE) AS year,
  count(*) FILTER (WHERE DOCTYPE = 1) AS invoices,
  CAST(COALESCE(SUM(DOCAMNT) FILTER (WHERE DOCTYPE = 1), 0) AS DECIMAL(19,2)) AS invoiced,
  count(*) FILTER (WHERE DOCTYPE = 6 AND VOIDED = 0) AS payments,
  CAST(COALESCE(SUM(DOCAMNT) FILTER (WHERE DOCTYPE = 6 AND VOIDED = 0), 0) AS DECIMAL(19,2)) AS paid,
  count(*) FILTER (WHERE VOIDED = 1) AS voided
FROM docs
GROUP BY ALL
ORDER BY vendor, year;

-- name: control_accounts
-- Subledger against general ledger: AR and AP aging totals at each period end
-- against the 1200 and 2100 account balances built from journal lines.
WITH lines AS (
  SELECT ACTINDX, TRXDATE, PERIODID, DEBITAMT, CRDTAMNT FROM gp.GL20000
  UNION ALL
  SELECT ACTINDX, TRXDATE, PERIODID, DEBITAMT, CRDTAMNT FROM gp.GL30000
),
period_ends AS (
  SELECT PERDENDT AS d FROM gp.SY40100 WHERE SERIES = 0 AND PERIODDT <= :asof_last
),
-- Balance sheet balances are cumulative across years. Brought-forward lines
-- (period 0) restate the prior year, so count them only for the company's first year.
gl AS (
  SELECT a.d, acct.ACTNUMST AS account, SUM(l.DEBITAMT - l.CRDTAMNT) AS bal
  FROM period_ends a
  CROSS JOIN (SELECT ACTINDX, ACTNUMST FROM gp.GL00105 WHERE ACTNUMST IN ('000-1200-00', '000-2100-00')) acct
  JOIN lines l ON l.ACTINDX = acct.ACTINDX AND l.TRXDATE <= a.d
    AND (l.PERIODID > 0 OR year(l.TRXDATE) = (SELECT min(YEAR1) FROM gp.SY40101))
  GROUP BY ALL
)
SELECT strftime(d, '%Y-%m-%d') AS as_of, account, CAST(bal AS DECIMAL(19,2)) AS gl_balance
FROM gl ORDER BY as_of, account;
