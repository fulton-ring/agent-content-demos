-- Every receivables document open on a past date, with what was still owed that day.
-- Parameters: $as_of (a date)
WITH docs AS (
  SELECT * FROM gp.RM20101 UNION ALL BY NAME SELECT * FROM gp.RM30101
),
applies AS (
  SELECT * FROM gp.RM20201 UNION ALL BY NAME SELECT * FROM gp.RM30201
),
owed AS (
  SELECT x.CUSTNMBR, x.DOCNUMBR, x.RMDTYPAL, x.DOCDATE, x.DUEDATE, x.ORTRXAMT,
    CASE WHEN x.RMDTYPAL < 7
      THEN x.ORTRXAMT - COALESCE((SELECT SUM(APPTOAMT) FROM applies p WHERE p.APTODCNM = x.DOCNUMBR AND p.APTODCTY = x.RMDTYPAL AND p.DATE1 <= CAST($as_of AS DATE)), 0)
      ELSE -(x.ORTRXAMT - COALESCE((SELECT SUM(APPTOAMT) FROM applies p WHERE p.APFRDCNM = x.DOCNUMBR AND p.APFRDCTY = x.RMDTYPAL AND p.DATE1 <= CAST($as_of AS DATE)), 0))
    END AS remaining
  FROM docs x
  WHERE x.DOCDATE <= CAST($as_of AS DATE) AND NOT (x.VOIDSTTS = 1 AND x.VOIDDATE <= CAST($as_of AS DATE))
)
SELECT o.CUSTNMBR AS customer, c.CUSTNAME AS name, o.DOCNUMBR AS document,
  CASE o.RMDTYPAL WHEN 1 THEN 'Invoice' WHEN 7 THEN 'Credit memo' WHEN 9 THEN 'Payment' ELSE 'Other' END AS type,
  strftime(o.DOCDATE, '%Y-%m-%d') AS doc_date, strftime(o.DUEDATE, '%Y-%m-%d') AS due_date,
  CAST(o.ORTRXAMT AS DECIMAL(19,2)) AS original, CAST(o.remaining AS DECIMAL(19,2)) AS owed_on_date,
  CASE WHEN o.RMDTYPAL < 7 THEN greatest(date_diff('day', o.DUEDATE, CAST($as_of AS DATE)), 0) END AS days_past_due
FROM owed o JOIN gp.RM00101 c USING (CUSTNMBR)
WHERE o.remaining <> 0
ORDER BY customer, o.DOCDATE, document;
