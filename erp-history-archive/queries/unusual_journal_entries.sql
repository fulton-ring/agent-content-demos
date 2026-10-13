-- Journal entries an auditor usually asks about: manual entries posted by the
-- system administrator login, on a weekend, or for a round amount of 10,000 or more.
-- Parameters: $from, $to (dates)
WITH lines AS (
  SELECT * EXCLUDE (OPENYEAR) FROM gp.GL20000 UNION ALL BY NAME SELECT * EXCLUDE (HSTYEAR) FROM gp.GL30000
),
je AS (
  SELECT JRNENTRY, min(TRXDATE) AS d, any_value(REFRENCE) AS reference, any_value(USWHPSTD) AS posted_by,
    any_value(SOURCDOC) AS source, SUM(DEBITAMT) AS amount
  FROM lines WHERE SERIES = 2 AND SOURCDOC <> 'BBF' GROUP BY JRNENTRY
)
SELECT JRNENTRY AS journal_entry, strftime(d, '%Y-%m-%d') AS date, dayname(d) AS weekday, reference, posted_by,
  CAST(amount AS DECIMAL(19,2)) AS amount,
  concat_ws('; ',
    CASE WHEN posted_by = 'sa' THEN 'posted by sa' END,
    CASE WHEN dayofweek(d) IN (0, 6) THEN 'weekend' END,
    CASE WHEN amount >= 10000 AND amount % 1000 = 0 THEN 'round amount' END) AS flags
FROM je
WHERE d BETWEEN CAST($from AS DATE) AND CAST($to AS DATE)
  AND (posted_by = 'sa' OR dayofweek(d) IN (0, 6) OR (amount >= 10000 AND amount % 1000 = 0))
ORDER BY d, JRNENTRY;
