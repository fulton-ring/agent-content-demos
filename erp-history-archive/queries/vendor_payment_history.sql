-- Every invoice and payment for one vendor, with what each payment paid and any voids.
-- Parameters: $vendor
WITH docs AS (
  SELECT *, 'open' AS kept_in FROM gp.PM20000
  UNION ALL BY NAME
  SELECT *, 'history' AS kept_in FROM gp.PM30200
),
applies AS (
  SELECT * FROM gp.PM10200 UNION ALL BY NAME SELECT * FROM gp.PM30300
)
SELECT strftime(d.DOCDATE, '%Y-%m-%d') AS date,
  CASE d.DOCTYPE WHEN 1 THEN 'Invoice' WHEN 5 THEN 'Credit memo' WHEN 6 THEN 'Payment' ELSE 'Other' END AS type,
  d.VCHRNMBR AS voucher, d.DOCNUMBR AS document, CAST(d.DOCAMNT AS DECIMAL(19,2)) AS amount,
  CAST(d.CURTRXAM AS DECIMAL(19,2)) AS unapplied_today,
  string_agg(DISTINCT CASE WHEN d.DOCTYPE = 6 THEN p.APTODCNM ELSE p.APFRDCNM END, ', ') AS applied_with,
  CASE WHEN d.VOIDED = 1 THEN 'voided ' || strftime(d.VOIDPDATE, '%Y-%m-%d') ELSE '' END AS void,
  d.PTDUSRID AS entered_by, d.kept_in
FROM docs d
LEFT JOIN applies p ON (d.DOCTYPE = 6 AND p.APFRDCNM = d.VCHRNMBR) OR (d.DOCTYPE = 1 AND p.APTVCHNM = d.VCHRNMBR)
WHERE d.VENDORID = $vendor
GROUP BY ALL
ORDER BY date, voucher;
