-- A subset of the Dynamics GP company database schema: the general ledger,
-- receivables and payables tables a controller or auditor asks about.
-- Table and column names follow GP. Columns GP has that this demo never fills
-- (multicurrency, analytical accounting, tax detail) are left out.
-- GP stores text as fixed-width char and uses 1900-01-01 for "no date".

-- Fiscal calendar
CREATE TABLE SY40101 (            -- Period header: one row per fiscal year
  YEAR1     smallint NOT NULL PRIMARY KEY,
  FSTFSCDY  datetime NOT NULL,    -- first day of the fiscal year
  LSTFSCDY  datetime NOT NULL,    -- last day of the fiscal year
  NUMOFPER  smallint NOT NULL,
  HISTORYR  tinyint  NOT NULL     -- 1 once the year is closed
);
CREATE TABLE SY40100 (            -- Period setup: one row per fiscal period
  YEAR1     smallint NOT NULL,
  PERIODID  smallint NOT NULL,
  PERIODDT  datetime NOT NULL,    -- period start
  PERDENDT  datetime NOT NULL,    -- period end
  PERNAME   char(21) NOT NULL,
  SERIES    smallint NOT NULL,
  ODESCTN   char(51) NOT NULL,
  CLOSED    tinyint  NOT NULL,
  PRIMARY KEY (YEAR1, PERIODID, SERIES, ODESCTN)
);

-- General ledger
CREATE TABLE GL00100 (            -- Account master
  ACTINDX     int      NOT NULL PRIMARY KEY,
  ACTNUMBR_1  char(9)  NOT NULL,
  ACTNUMBR_2  char(9)  NOT NULL,
  ACTNUMBR_3  char(9)  NOT NULL,
  ACTALIAS    char(21) NOT NULL,
  ACTDESCR    char(51) NOT NULL,
  ACCTTYPE    smallint NOT NULL,  -- 1 posting account
  PSTNGTYP    smallint NOT NULL,  -- 0 balance sheet, 1 profit and loss
  ACCATNUM    smallint NOT NULL,  -- account category
  TPCLBLNC    smallint NOT NULL,  -- typical balance: 0 debit, 1 credit
  ACTIVE      tinyint  NOT NULL,
  CREATDDT    datetime NOT NULL,
  DEX_ROW_ID  int IDENTITY(1,1) NOT NULL
);
CREATE TABLE GL00105 (            -- Account index master (formatted account string)
  ACTINDX     int       NOT NULL PRIMARY KEY,
  ACTNUMBR_1  char(9)   NOT NULL,
  ACTNUMBR_2  char(9)   NOT NULL,
  ACTNUMBR_3  char(9)   NOT NULL,
  ACTNUMST    char(129) NOT NULL,
  DEX_ROW_ID  int IDENTITY(1,1) NOT NULL
);
CREATE TABLE GL10110 (            -- Account summary, open years (what GP's trial balance reads)
  ACTINDX   int           NOT NULL,
  YEAR1     smallint      NOT NULL,
  PERIODID  smallint      NOT NULL,
  ACCATNUM  smallint      NOT NULL,
  CRDTAMNT  numeric(19,5) NOT NULL,
  DEBITAMT  numeric(19,5) NOT NULL,
  PERDBLNC  numeric(19,5) NOT NULL,  -- net change for the period
  DEX_ROW_ID int IDENTITY(1,1) NOT NULL,
  PRIMARY KEY (ACTINDX, YEAR1, PERIODID)
);
CREATE TABLE GL10111 (            -- Account summary, history years
  ACTINDX   int           NOT NULL,
  YEAR1     smallint      NOT NULL,
  PERIODID  smallint      NOT NULL,
  ACCATNUM  smallint      NOT NULL,
  CRDTAMNT  numeric(19,5) NOT NULL,
  DEBITAMT  numeric(19,5) NOT NULL,
  PERDBLNC  numeric(19,5) NOT NULL,
  DEX_ROW_ID int IDENTITY(1,1) NOT NULL,
  PRIMARY KEY (ACTINDX, YEAR1, PERIODID)
);
CREATE TABLE GL20000 (            -- Year-to-date transaction open (journal lines, open year)
  OPENYEAR  smallint      NOT NULL,
  JRNENTRY  int           NOT NULL,
  SOURCDOC  char(11)      NOT NULL,
  REFRENCE  char(31)      NOT NULL,
  DSCRIPTN  char(31)      NOT NULL,
  TRXDATE   datetime      NOT NULL,
  TRXSORCE  char(13)      NOT NULL,
  ACTINDX   int           NOT NULL,
  POLLDTRX  tinyint       NOT NULL,
  LASTUSER  char(15)      NOT NULL,
  LSTDTEDT  datetime      NOT NULL,
  USWHPSTD  char(15)      NOT NULL,  -- user who posted
  SERIES    smallint      NOT NULL,  -- 2 financial, 3 sales, 4 purchasing
  ORTRXTYP  smallint      NOT NULL,
  ORCTRNUM  char(21)      NOT NULL,
  ORMSTRID  char(31)      NOT NULL,  -- originating customer or vendor ID
  ORMSTRNM  char(65)      NOT NULL,
  ORDOCNUM  char(21)      NOT NULL,  -- originating document number
  ORPSTDDT  datetime      NOT NULL,
  ORTRXSRC  char(13)      NOT NULL,
  SEQNUMBR  int           NOT NULL,
  DEBITAMT  numeric(19,5) NOT NULL,
  CRDTAMNT  numeric(19,5) NOT NULL,
  CURNCYID  char(15)      NOT NULL,
  PERIODID  smallint      NOT NULL,
  VOIDED    tinyint       NOT NULL,
  DEX_ROW_ID int IDENTITY(1,1) NOT NULL PRIMARY KEY
);
CREATE TABLE GL30000 (            -- Account transaction history (journal lines, closed years)
  HSTYEAR   smallint      NOT NULL,
  JRNENTRY  int           NOT NULL,
  SOURCDOC  char(11)      NOT NULL,
  REFRENCE  char(31)      NOT NULL,
  DSCRIPTN  char(31)      NOT NULL,
  TRXDATE   datetime      NOT NULL,
  TRXSORCE  char(13)      NOT NULL,
  ACTINDX   int           NOT NULL,
  POLLDTRX  tinyint       NOT NULL,
  LASTUSER  char(15)      NOT NULL,
  LSTDTEDT  datetime      NOT NULL,
  USWHPSTD  char(15)      NOT NULL,
  SERIES    smallint      NOT NULL,
  ORTRXTYP  smallint      NOT NULL,
  ORCTRNUM  char(21)      NOT NULL,
  ORMSTRID  char(31)      NOT NULL,
  ORMSTRNM  char(65)      NOT NULL,
  ORDOCNUM  char(21)      NOT NULL,
  ORPSTDDT  datetime      NOT NULL,
  ORTRXSRC  char(13)      NOT NULL,
  SEQNUMBR  int           NOT NULL,
  DEBITAMT  numeric(19,5) NOT NULL,
  CRDTAMNT  numeric(19,5) NOT NULL,
  CURNCYID  char(15)      NOT NULL,
  PERIODID  smallint      NOT NULL,
  VOIDED    tinyint       NOT NULL,
  DEX_ROW_ID int IDENTITY(1,1) NOT NULL PRIMARY KEY
);

-- Receivables
CREATE TABLE RM00101 (            -- Customer master
  CUSTNMBR  char(15)      NOT NULL PRIMARY KEY,
  CUSTNAME  char(65)      NOT NULL,
  CUSTCLAS  char(15)      NOT NULL,
  ADDRESS1  char(61)      NOT NULL,
  CITY      char(35)      NOT NULL,
  STATE     char(29)      NOT NULL,
  ZIP       char(11)      NOT NULL,
  PYMTRMID  char(21)      NOT NULL,
  CRLMTAMT  numeric(19,5) NOT NULL,
  INACTIVE  tinyint       NOT NULL,
  CREATDDT  datetime      NOT NULL,
  DEX_ROW_ID int IDENTITY(1,1) NOT NULL
);
-- RMDTYPAL: 1 invoice, 3 debit memo, 7 credit memo, 9 payment
CREATE TABLE RM20101 (            -- Open documents
  CUSTNMBR  char(15)      NOT NULL,
  DOCNUMBR  char(21)      NOT NULL,
  RMDTYPAL  smallint      NOT NULL,
  DOCDATE   datetime      NOT NULL,
  GLPOSTDT  datetime      NOT NULL,
  POSTDATE  datetime      NOT NULL,
  DUEDATE   datetime      NOT NULL,
  ORTRXAMT  numeric(19,5) NOT NULL,  -- original amount
  CURTRXAM  numeric(19,5) NOT NULL,  -- amount still unapplied today
  BACHNUMB  char(15)      NOT NULL,
  TRXSORCE  char(13)      NOT NULL,
  CHEKNMBR  char(21)      NOT NULL,
  CSHRCTYP  smallint      NOT NULL,
  VOIDSTTS  smallint      NOT NULL,
  VOIDDATE  datetime      NOT NULL,
  PTDUSRID  char(15)      NOT NULL,
  TRXDSCRN  char(31)      NOT NULL,
  DEX_ROW_ID int IDENTITY(1,1) NOT NULL,
  PRIMARY KEY (RMDTYPAL, DOCNUMBR)
);
CREATE TABLE RM30101 (            -- History documents (fully applied, or voided)
  CUSTNMBR  char(15)      NOT NULL,
  DOCNUMBR  char(21)      NOT NULL,
  RMDTYPAL  smallint      NOT NULL,
  DOCDATE   datetime      NOT NULL,
  GLPOSTDT  datetime      NOT NULL,
  POSTDATE  datetime      NOT NULL,
  DUEDATE   datetime      NOT NULL,
  ORTRXAMT  numeric(19,5) NOT NULL,
  CURTRXAM  numeric(19,5) NOT NULL,
  BACHNUMB  char(15)      NOT NULL,
  TRXSORCE  char(13)      NOT NULL,
  CHEKNMBR  char(21)      NOT NULL,
  CSHRCTYP  smallint      NOT NULL,
  VOIDSTTS  smallint      NOT NULL,
  VOIDDATE  datetime      NOT NULL,
  PTDUSRID  char(15)      NOT NULL,
  TRXDSCRN  char(31)      NOT NULL,
  DEX_ROW_ID int IDENTITY(1,1) NOT NULL,
  PRIMARY KEY (RMDTYPAL, DOCNUMBR)
);
CREATE TABLE RM20201 (            -- Apply open (payments and credits applied to invoices)
  CUSTNMBR  char(15)      NOT NULL,
  APFRDCTY  smallint      NOT NULL,
  APFRDCNM  char(21)      NOT NULL,
  APFRDCDT  datetime      NOT NULL,
  APTODCTY  smallint      NOT NULL,
  APTODCNM  char(21)      NOT NULL,
  APTODCDT  datetime      NOT NULL,
  APPTOAMT  numeric(19,5) NOT NULL,
  DATE1     datetime      NOT NULL,  -- apply date
  GLPOSTDT  datetime      NOT NULL,
  DEX_ROW_ID int IDENTITY(1,1) NOT NULL PRIMARY KEY
);
CREATE TABLE RM30201 (            -- Apply history
  CUSTNMBR  char(15)      NOT NULL,
  APFRDCTY  smallint      NOT NULL,
  APFRDCNM  char(21)      NOT NULL,
  APFRDCDT  datetime      NOT NULL,
  APTODCTY  smallint      NOT NULL,
  APTODCNM  char(21)      NOT NULL,
  APTODCDT  datetime      NOT NULL,
  APPTOAMT  numeric(19,5) NOT NULL,
  DATE1     datetime      NOT NULL,
  GLPOSTDT  datetime      NOT NULL,
  DEX_ROW_ID int IDENTITY(1,1) NOT NULL PRIMARY KEY
);

-- Payables
CREATE TABLE PM00200 (            -- Vendor master
  VENDORID  char(15)      NOT NULL PRIMARY KEY,
  VENDNAME  char(65)      NOT NULL,
  VNDCLSID  char(11)      NOT NULL,
  ADDRESS1  char(61)      NOT NULL,
  CITY      char(35)      NOT NULL,
  STATE     char(29)      NOT NULL,
  ZIPCODE   char(11)      NOT NULL,
  PYMTRMID  char(21)      NOT NULL,
  VENDSTTS  smallint      NOT NULL,
  CREATDDT  datetime      NOT NULL,
  DEX_ROW_ID int IDENTITY(1,1) NOT NULL
);
-- DOCTYPE: 1 invoice, 5 credit memo, 6 payment
CREATE TABLE PM20000 (            -- Open transactions
  VCHRNMBR  char(21)      NOT NULL,
  VENDORID  char(15)      NOT NULL,
  DOCTYPE   smallint      NOT NULL,
  DOCDATE   datetime      NOT NULL,
  DOCNUMBR  char(21)      NOT NULL,
  DOCAMNT   numeric(19,5) NOT NULL,
  CURTRXAM  numeric(19,5) NOT NULL,
  DUEDATE   datetime      NOT NULL,
  PSTGDATE  datetime      NOT NULL,
  POSTEDDT  datetime      NOT NULL,
  BACHNUMB  char(15)      NOT NULL,
  TRXSORCE  char(13)      NOT NULL,
  VOIDED    tinyint       NOT NULL,
  VOIDPDATE datetime      NOT NULL,
  PTDUSRID  char(15)      NOT NULL,
  TRXDSCRN  char(31)      NOT NULL,
  DEX_ROW_ID int IDENTITY(1,1) NOT NULL,
  PRIMARY KEY (VCHRNMBR, DOCTYPE)
);
CREATE TABLE PM30200 (            -- Paid transaction history
  VCHRNMBR  char(21)      NOT NULL,
  VENDORID  char(15)      NOT NULL,
  DOCTYPE   smallint      NOT NULL,
  DOCDATE   datetime      NOT NULL,
  DOCNUMBR  char(21)      NOT NULL,
  DOCAMNT   numeric(19,5) NOT NULL,
  CURTRXAM  numeric(19,5) NOT NULL,
  DUEDATE   datetime      NOT NULL,
  PSTGDATE  datetime      NOT NULL,
  POSTEDDT  datetime      NOT NULL,
  BACHNUMB  char(15)      NOT NULL,
  TRXSORCE  char(13)      NOT NULL,
  VOIDED    tinyint       NOT NULL,
  VOIDPDATE datetime      NOT NULL,
  PTDUSRID  char(15)      NOT NULL,
  TRXDSCRN  char(31)      NOT NULL,
  DEX_ROW_ID int IDENTITY(1,1) NOT NULL,
  PRIMARY KEY (VCHRNMBR, DOCTYPE)
);
CREATE TABLE PM10200 (            -- Apply to open (applications involving an open document)
  VENDORID  char(15)      NOT NULL,
  APFRDCNM  char(21)      NOT NULL,  -- payment or credit voucher
  DOCTYPE   smallint      NOT NULL,  -- type of the apply-from document
  APFRDCDT  datetime      NOT NULL,
  APTVCHNM  char(21)      NOT NULL,  -- invoice voucher applied to
  APTODCTY  smallint      NOT NULL,
  APTODCNM  char(21)      NOT NULL,
  APTODCDT  datetime      NOT NULL,
  APPLDAMT  numeric(19,5) NOT NULL,
  DATE1     datetime      NOT NULL,  -- apply date
  GLPOSTDT  datetime      NOT NULL,
  DEX_ROW_ID int IDENTITY(1,1) NOT NULL PRIMARY KEY
);
CREATE TABLE PM30300 (            -- Apply to history
  VENDORID  char(15)      NOT NULL,
  APFRDCNM  char(21)      NOT NULL,
  DOCTYPE   smallint      NOT NULL,
  APFRDCDT  datetime      NOT NULL,
  APTVCHNM  char(21)      NOT NULL,
  APTODCTY  smallint      NOT NULL,
  APTODCNM  char(21)      NOT NULL,
  APTODCDT  datetime      NOT NULL,
  APPLDAMT  numeric(19,5) NOT NULL,
  DATE1     datetime      NOT NULL,
  GLPOSTDT  datetime      NOT NULL,
  DEX_ROW_ID int IDENTITY(1,1) NOT NULL PRIMARY KEY
);
