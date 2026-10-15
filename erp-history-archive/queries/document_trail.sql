-- Everything the archive holds about one receivables or payables document:
-- the document, what was applied to or from it, and the journal lines it posted.
-- Parameters: $document (a GP document or voucher number)
SELECT 'document' AS part, strftime(DOCDATE, '%Y-%m-%d') AS date, CUSTNMBR AS party,
  'RM type ' || RMDTYPAL || CASE WHEN VOIDSTTS = 1 THEN ', voided ' || strftime(VOIDDATE, '%Y-%m-%d') ELSE '' END AS detail,
  CAST(ORTRXAMT AS DECIMAL(19,2)) AS amount, '' AS account
FROM (SELECT * FROM gp.RM20101 UNION ALL BY NAME SELECT * FROM gp.RM30101) WHERE DOCNUMBR = $document
UNION ALL
SELECT 'document', strftime(DOCDATE, '%Y-%m-%d'), VENDORID,
  'PM type ' || DOCTYPE || ', vendor document ' || DOCNUMBR || CASE WHEN VOIDED = 1 THEN ', voided ' || strftime(VOIDPDATE, '%Y-%m-%d') ELSE '' END,
  CAST(DOCAMNT AS DECIMAL(19,2)), ''
FROM (SELECT * FROM gp.PM20000 UNION ALL BY NAME SELECT * FROM gp.PM30200) WHERE VCHRNMBR = $document
UNION ALL
SELECT 'applied', strftime(DATE1, '%Y-%m-%d'), CUSTNMBR, APFRDCNM || ' -> ' || APTODCNM, CAST(APPTOAMT AS DECIMAL(19,2)), ''
FROM (SELECT * FROM gp.RM20201 UNION ALL BY NAME SELECT * FROM gp.RM30201) WHERE $document IN (APFRDCNM, APTODCNM)
UNION ALL
SELECT 'applied', strftime(DATE1, '%Y-%m-%d'), VENDORID, APFRDCNM || ' -> ' || APTVCHNM, CAST(APPLDAMT AS DECIMAL(19,2)), ''
FROM (SELECT * FROM gp.PM10200 UNION ALL BY NAME SELECT * FROM gp.PM30300) WHERE $document IN (APFRDCNM, APTVCHNM)
UNION ALL
SELECT 'journal entry ' || JRNENTRY, strftime(TRXDATE, '%Y-%m-%d'), USWHPSTD, REFRENCE,
  CAST(DEBITAMT - CRDTAMNT AS DECIMAL(19,2)), a.ACTNUMST
FROM (SELECT * EXCLUDE (OPENYEAR) FROM gp.GL20000 UNION ALL BY NAME SELECT * EXCLUDE (HSTYEAR) FROM gp.GL30000) l
JOIN gp.GL00105 a USING (ACTINDX)
WHERE ORDOCNUM = $document
ORDER BY date, part;
