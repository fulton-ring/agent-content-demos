-- Journal lines posted by one user in a date range.
-- Parameters: $user, $from, $to (dates)
SELECT l.JRNENTRY AS journal_entry, strftime(l.TRXDATE, '%Y-%m-%d') AS date, l.SOURCDOC AS source,
  l.REFRENCE AS reference, a.ACTNUMST AS account, m.ACTDESCR AS description,
  CAST(l.DEBITAMT AS DECIMAL(19,2)) AS debit, CAST(l.CRDTAMNT AS DECIMAL(19,2)) AS credit,
  l.ORMSTRID AS customer_or_vendor, l.ORDOCNUM AS document
FROM (SELECT * EXCLUDE (OPENYEAR) FROM gp.GL20000 UNION ALL BY NAME SELECT * EXCLUDE (HSTYEAR) FROM gp.GL30000) l
JOIN gp.GL00105 a USING (ACTINDX)
JOIN gp.GL00100 m USING (ACTINDX)
WHERE l.USWHPSTD = $user AND l.TRXDATE BETWEEN CAST($from AS DATE) AND CAST($to AS DATE)
ORDER BY l.TRXDATE, l.JRNENTRY, l.SEQNUMBR;
