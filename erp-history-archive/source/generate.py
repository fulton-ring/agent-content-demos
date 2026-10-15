"""Build a synthetic Dynamics GP company database in SQL Server.

The company runs calendar fiscal years. 2023, 2024 and 2025 are closed (their
journal lines sit in GL30000 and their period summaries in GL10111); 2026 is
open through September (GL20000 and GL10110). Every receivables and payables
document posts to the general ledger the way GP's posting would, so the
subledgers tie to the AR and AP control accounts.

The data is random but seeded, so every run produces the same database.

One problem is planted on purpose: a single 2026 journal entry is written to
the detail table but not to the GP summary table, the way an interrupted
posting leaves it. GP's trial balance reads the summary table, so the
reconciliation has a real difference to find and explain.
"""

import datetime as dt
import os
import random
import sys
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

import pymssql

HERE = os.path.dirname(os.path.abspath(__file__))
SEED = 20261013
FIRST_YEAR, OPEN_YEAR = 2023, 2026
LAST_DATE = dt.date(2026, 9, 30)
NODATE = dt.date(1900, 1, 1)
CENT = Decimal("0.01")

# Planted problem: this journal entry's summary update is "lost".
PLANTED_JE_REF = "Office furniture reclass"

ACCOUNTS = [
    # number, description, posting type (0 balance sheet, 1 P&L), category, typical balance
    ("1100", "Cash - Operating", 0, 1, 0),
    ("1200", "Accounts Receivable", 0, 3, 0),
    ("1300", "Inventory", 0, 5, 0),
    ("1500", "Furniture and Equipment", 0, 9, 0),
    ("1550", "Accumulated Depreciation", 0, 10, 1),
    ("2100", "Accounts Payable", 0, 13, 1),
    ("2200", "Accrued Liabilities", 0, 14, 1),
    ("2500", "Long-Term Debt", 0, 18, 1),
    ("3000", "Common Stock", 0, 22, 1),
    ("3900", "Retained Earnings", 0, 24, 1),
    ("4000", "Sales - Products", 1, 31, 1),
    ("4100", "Sales - Services", 1, 31, 1),
    ("4900", "Sales Returns and Allowances", 1, 32, 0),
    ("5000", "Cost of Goods Sold", 1, 34, 0),
    ("6000", "Salaries and Wages", 1, 36, 0),
    ("6100", "Rent Expense", 1, 36, 0),
    ("6200", "Utilities Expense", 1, 36, 0),
    ("6300", "Office Supplies", 1, 36, 0),
    ("6400", "Depreciation Expense", 1, 36, 0),
    ("6500", "Travel and Entertainment", 1, 36, 0),
    ("6600", "Professional Fees", 1, 36, 0),
    ("7000", "Interest Expense", 1, 38, 0),
]
ACT = {num: i + 1 for i, (num, *_rest) in enumerate(ACCOUNTS)}
PL = {i + 1: a[2] for i, a in enumerate(ACCOUNTS)}
CATEGORY = {i + 1: a[3] for i, a in enumerate(ACCOUNTS)}
RETAINED_EARNINGS = ACT["3900"]

WORDS_A = ["Alder", "Birch", "Cedar", "Dogwood", "Elm", "Fir", "Ginkgo", "Hawthorn", "Ironwood",
           "Juniper", "Larch", "Maple", "Oak", "Pine", "Quince", "Redwood", "Spruce", "Tupelo",
           "Walnut", "Yew", "Aspen", "Beech", "Chestnut", "Hickory", "Linden", "Magnolia", "Poplar",
           "Sycamore", "Willow", "Cypress"]
WORDS_B = ["Street", "Ridge", "Harbor", "Valley", "Point", "Crossing", "Hollow", "Landing",
           "Mill", "Park", "Bend", "Falls"]
WORDS_C = ["Supply", "Builders", "Outfitters", "Hardware", "Clinic", "Partners", "Foods",
           "Logistics", "Studio", "Works", "Manufacturing", "Services"]
CITIES = [("Fargo", "ND", "58102"), ("Bismarck", "ND", "58501"), ("Sioux Falls", "SD", "57104"),
          ("Duluth", "MN", "55802"), ("Des Moines", "IA", "50309"), ("Omaha", "NE", "68102"),
          ("Madison", "WI", "53703"), ("Rochester", "MN", "55902")]

VENDOR_KINDS = [
    # class, expense account, monthly invoices (approx), amount range
    ("SUPPLIER", "1300", 30.0, (2500, 18000)),
    ("RENT", "6100", 1.0, (14000, 14000)),
    ("UTILITY", "6200", 2.0, (900, 4200)),
    ("OFFICE", "6300", 6.0, (80, 2400)),
    ("TRAVEL", "6500", 8.0, (200, 6500)),
    ("PROFSVC", "6600", 3.0, (2500, 18000)),
]

USERS_AR = ["AR.CLERK", "KMORALES"]
USERS_AP = ["AP.CLERK", "DPATEL"]
USERS_GL = ["CONTROLLER", "GL.ACCT"]


def money(x):
    return Decimal(str(x)).quantize(CENT, ROUND_HALF_UP)


def month_iter():
    y, m = FIRST_YEAR, 1
    while dt.date(y, m, 1) <= LAST_DATE:
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def month_end(y, m):
    nxt = dt.date(y + 1, 1, 1) if m == 12 else dt.date(y, m + 1, 1)
    return nxt - dt.timedelta(days=1)


def weekday_on_or_after(d):
    while d.weekday() >= 5:
        d += dt.timedelta(days=1)
    return d


def weekday_on_or_before(d):
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return d


def rand_day(rng, y, m):
    d = dt.date(y, m, rng.randint(1, month_end(y, m).day))
    return weekday_on_or_after(d) if weekday_on_or_after(d).month == m else d


class Ledger:
    """Collects journal lines the way GP posting writes them."""

    def __init__(self):
        self.lines = []
        self.next_je = 1000
        self.seq = defaultdict(int)

    def post(self, date, source_doc, ref, trx_source, user, series, lines,
             master_id="", master_name="", doc_num="", period=None):
        je = self.next_je
        self.next_je += 1
        total_dr = sum(dr for _, dr, _ in lines)
        total_cr = sum(cr for _, _, cr in lines)
        assert total_dr == total_cr, (ref, total_dr, total_cr)
        for i, (act, dr, cr) in enumerate(lines):
            self.lines.append(dict(
                year=date.year, JRNENTRY=je, SOURCDOC=source_doc, REFRENCE=ref[:30],
                DSCRIPTN=ref[:30], TRXDATE=date, TRXSORCE=trx_source, ACTINDX=act,
                POLLDTRX=0, LASTUSER=user, LSTDTEDT=date, USWHPSTD=user, SERIES=series,
                ORTRXTYP=0, ORCTRNUM=doc_num, ORMSTRID=master_id, ORMSTRNM=master_name,
                ORDOCNUM=doc_num, ORPSTDDT=date, ORTRXSRC=trx_source, SEQNUMBR=(i + 1) * 16384,
                DEBITAMT=dr, CRDTAMNT=cr, CURNCYID="", PERIODID=date.month if period is None else period,
                VOIDED=0))
        return je


def build(rng):
    led = Ledger()
    batch_no = defaultdict(int)

    def trx_source(prefix):
        batch_no[prefix] += 1
        return f"{prefix}{batch_no[prefix]:08d}"

    # Masters
    names = set()
    def company_name():
        while True:
            n = f"{rng.choice(WORDS_A)} {rng.choice(WORDS_B)} {rng.choice(WORDS_C)}"
            if n not in names:
                names.add(n)
                return n

    customers = []
    for i in range(1, 61):
        city, state, zipc = rng.choice(CITIES)
        customers.append(dict(
            CUSTNMBR=f"C{i:05d}", CUSTNAME=company_name(), CUSTCLAS=rng.choice(["WHOLESALE", "RETAIL", "SERVICE"]),
            ADDRESS1=f"{rng.randint(100, 9999)} {rng.choice(WORDS_A)} Ave", CITY=city, STATE=state, ZIP=zipc,
            PYMTRMID="Net 30", CRLMTAMT=money(rng.choice([25000, 50000, 100000])), INACTIVE=0,
            CREATDDT=dt.date(2022, 12, 1), weight=rng.paretovariate(1.3),
            pays_late=rng.random() < 0.15))

    vendors = []
    vid = 0
    for cls, acct, per_month, rng_amt in VENDOR_KINDS:
        count = {"SUPPLIER": 12, "RENT": 1, "UTILITY": 2, "OFFICE": 3, "TRAVEL": 3, "PROFSVC": 3}[cls]
        for _ in range(count):
            vid += 1
            city, state, zipc = rng.choice(CITIES)
            vendors.append(dict(
                VENDORID=f"V{vid:04d}", VENDNAME=company_name(), VNDCLSID=cls,
                ADDRESS1=f"{rng.randint(100, 9999)} {rng.choice(WORDS_A)} St", CITY=city, STATE=state,
                ZIPCODE=zipc, PYMTRMID="Net 30", VENDSTTS=1, CREATDDT=dt.date(2022, 12, 1),
                acct=acct, per_month=per_month / count, amt=rng_amt))

    # Opening balances, brought forward from the system before GP (2023 period 0)
    opening = [(ACT["1100"], money(1500000), 0), (ACT["1300"], money(300000), 0),
               (ACT["1500"], money(800000), 0), (ACT["1550"], 0, money(120000)),
               (ACT["2500"], 0, money(600000)), (ACT["3000"], 0, money(1880000))]
    led.post(dt.date(FIRST_YEAR, 1, 1), "BBF", "Balance Brought Forward", "GLTRX00000001", "sa", 2,
             [(a, money(d), money(c)) for a, d, c in opening], period=0)

    # Receivables
    rm_docs, rm_applies = [], []
    inv_no = pay_no = cm_no = 0
    cust_weights = [c["weight"] for c in customers]
    void_payment_slots = {(2023, 5), (2024, 2), (2024, 11), (2025, 7), (2026, 3)}
    for y, m in month_iter():
        for _ in range(rng.randint(95, 125)):
            c = rng.choices(customers, cust_weights)[0]
            inv_no += 1
            d = rand_day(rng, y, m)
            product = rng.random() < 0.7
            amt = money(rng.lognormvariate(8.4, 0.9))
            amt = max(amt, money(120))
            user = rng.choice(USERS_AR)
            src = trx_source("RMSLS")
            doc = dict(CUSTNMBR=c["CUSTNMBR"], DOCNUMBR=f"INV{inv_no:07d}", RMDTYPAL=1, DOCDATE=d,
                       GLPOSTDT=d, POSTDATE=d, DUEDATE=d + dt.timedelta(days=30), ORTRXAMT=amt,
                       CURTRXAM=amt, BACHNUMB=f"RM{d:%y%m%d}", TRXSORCE=src, CHEKNMBR="", CSHRCTYP=0,
                       VOIDSTTS=0, VOIDDATE=NODATE, PTDUSRID=user, TRXDSCRN="Sales invoice")
            rm_docs.append(doc)
            lines = [(ACT["1200"], amt, money(0)), (ACT["4000" if product else "4100"], money(0), amt)]
            if product:
                cost = money(amt * Decimal("0.58"))
                lines += [(ACT["5000"], cost, money(0)), (ACT["1300"], money(0), cost)]
            led.post(d, "SJ", "Sales Transaction Entry", src, user, 3, lines,
                     c["CUSTNMBR"], c["CUSTNAME"], doc["DOCNUMBR"])

            # Credit memo on a few invoices
            if rng.random() < 0.03:
                cm_no += 1
                cd = d + dt.timedelta(days=rng.randint(3, 20))
                if cd <= LAST_DATE:
                    cm_amt = money(amt * Decimal("0.10"))
                    src = trx_source("RMSLS")
                    cm = dict(doc, DOCNUMBR=f"CM{cm_no:07d}", RMDTYPAL=7, DOCDATE=cd, GLPOSTDT=cd,
                              POSTDATE=cd, DUEDATE=cd, ORTRXAMT=cm_amt, CURTRXAM=money(0), TRXSORCE=src,
                              BACHNUMB=f"RM{cd:%y%m%d}", TRXDSCRN="Pricing allowance")
                    rm_docs.append(cm)
                    led.post(cd, "SJ", "Credit Memo", src, user, 3,
                             [(ACT["4900"], cm_amt, money(0)), (ACT["1200"], money(0), cm_amt)],
                             c["CUSTNMBR"], c["CUSTNAME"], cm["DOCNUMBR"])
                    rm_applies.append(dict(CUSTNMBR=c["CUSTNMBR"], APFRDCTY=7, APFRDCNM=cm["DOCNUMBR"],
                                           APFRDCDT=cd, APTODCTY=1, APTODCNM=doc["DOCNUMBR"], APTODCDT=d,
                                           APPTOAMT=cm_amt, DATE1=cd, GLPOSTDT=cd))
                    doc["CURTRXAM"] -= cm_amt

            # Payment: most invoices are paid in full, a few in two parts, a very few never
            r = rng.random()
            lag = rng.randint(25, 95) if c["pays_late"] else rng.randint(8, 45)
            first = weekday_on_or_after(d + dt.timedelta(days=lag))
            if r < 0.008:
                plan = []
            elif r < 0.04:
                plan = [(first, Decimal("0.5")),
                        (weekday_on_or_after(first + dt.timedelta(days=rng.randint(25, 60))), None)]
            else:
                plan = [(first, None)]
            for pd_, frac in plan:
                if pd_ > LAST_DATE:
                    break  # not paid yet
                pay_amt = doc["CURTRXAM"] if frac is None else money(doc["CURTRXAM"] * frac)
                pay_no += 1
                src = trx_source("RMCSH")
                puser = rng.choice(USERS_AR)
                pay = dict(CUSTNMBR=c["CUSTNMBR"], DOCNUMBR=f"PMT{pay_no:07d}", RMDTYPAL=9, DOCDATE=pd_,
                           GLPOSTDT=pd_, POSTDATE=pd_, DUEDATE=pd_, ORTRXAMT=pay_amt, CURTRXAM=money(0),
                           BACHNUMB=f"CR{pd_:%y%m%d}", TRXSORCE=src, CHEKNMBR=str(rng.randint(1000, 99999)),
                           CSHRCTYP=0, VOIDSTTS=0, VOIDDATE=NODATE, PTDUSRID=puser, TRXDSCRN="Customer payment")
                rm_docs.append(pay)
                led.post(pd_, "CRJ", "Cash Receipts Entry", src, puser, 3,
                         [(ACT["1100"], pay_amt, money(0)), (ACT["1200"], money(0), pay_amt)],
                         c["CUSTNMBR"], c["CUSTNAME"], pay["DOCNUMBR"])
                # A few payments bounce and are voided; the customer pays again later
                if (y, m) in void_payment_slots:
                    void_payment_slots.discard((y, m))
                    vd = pd_ + dt.timedelta(days=9)
                    pay["VOIDSTTS"], pay["VOIDDATE"] = 1, vd
                    src = trx_source("RMCSH")
                    led.post(vd, "CRJ", "Void NSF payment", src, puser, 3,
                             [(ACT["1200"], pay_amt, money(0)), (ACT["1100"], money(0), pay_amt)],
                             c["CUSTNMBR"], c["CUSTNAME"], pay["DOCNUMBR"])
                    pd_ = weekday_on_or_after(vd + dt.timedelta(days=14))
                    if pd_ > LAST_DATE:
                        break
                    pay_no += 1
                    src = trx_source("RMCSH")
                    pay = dict(pay, DOCNUMBR=f"PMT{pay_no:07d}", DOCDATE=pd_, GLPOSTDT=pd_, POSTDATE=pd_,
                               DUEDATE=pd_, TRXSORCE=src, BACHNUMB=f"CR{pd_:%y%m%d}", VOIDSTTS=0,
                               VOIDDATE=NODATE, CHEKNMBR=str(rng.randint(1000, 99999)), TRXDSCRN="Replacement payment")
                    rm_docs.append(pay)
                    led.post(pd_, "CRJ", "Cash Receipts Entry", src, puser, 3,
                             [(ACT["1100"], pay_amt, money(0)), (ACT["1200"], money(0), pay_amt)],
                             c["CUSTNMBR"], c["CUSTNAME"], pay["DOCNUMBR"])
                rm_applies.append(dict(CUSTNMBR=c["CUSTNMBR"], APFRDCTY=9, APFRDCNM=pay["DOCNUMBR"], APFRDCDT=pd_,
                                       APTODCTY=1, APTODCNM=doc["DOCNUMBR"], APTODCDT=d, APPTOAMT=pay_amt,
                                       DATE1=pd_, GLPOSTDT=pd_))
                doc["CURTRXAM"] -= pay_amt

        # A few on-account payments nobody applied
        if rng.random() < 0.25:
            c = rng.choice(customers)
            pd_ = rand_day(rng, y, m)
            amt = money(rng.randint(200, 3000))
            pay_no += 1
            src = trx_source("RMCSH")
            user = rng.choice(USERS_AR)
            rm_docs.append(dict(CUSTNMBR=c["CUSTNMBR"], DOCNUMBR=f"PMT{pay_no:07d}", RMDTYPAL=9, DOCDATE=pd_,
                                GLPOSTDT=pd_, POSTDATE=pd_, DUEDATE=pd_, ORTRXAMT=amt, CURTRXAM=amt,
                                BACHNUMB=f"CR{pd_:%y%m%d}", TRXSORCE=src, CHEKNMBR=str(rng.randint(1000, 99999)),
                                CSHRCTYP=0, VOIDSTTS=0, VOIDDATE=NODATE, PTDUSRID=user,
                                TRXDSCRN="Unapplied payment"))
            led.post(pd_, "CRJ", "Cash Receipts Entry", src, user, 3,
                     [(ACT["1100"], amt, money(0)), (ACT["1200"], money(0), amt)],
                     c["CUSTNMBR"], c["CUSTNAME"], f"PMT{pay_no:07d}")

    # Payables
    pm_docs, pm_applies = [], []
    vch = chk = 0
    void_check_slots = {(2024, 6), (2025, 10)}
    for y, m in month_iter():
        for v in vendors:
            n = int(v["per_month"]) + (1 if rng.random() < v["per_month"] % 1 else 0)
            for _ in range(n):
                vch += 1
                d = rand_day(rng, y, m)
                lo, hi = v["amt"]
                amt = money(lo if lo == hi else rng.uniform(lo, hi))
                user = rng.choice(USERS_AP)
                src = trx_source("PMTRX")
                inv = dict(VCHRNMBR=f"{vch:08d}", VENDORID=v["VENDORID"], DOCTYPE=1, DOCDATE=d,
                           DOCNUMBR=f"{v['VENDORID'][1:]}-{rng.randint(10000, 99999)}", DOCAMNT=amt,
                           CURTRXAM=amt, DUEDATE=d + dt.timedelta(days=30), PSTGDATE=d, POSTEDDT=d,
                           BACHNUMB=f"PM{d:%y%m%d}", TRXSORCE=src, VOIDED=0, VOIDPDATE=NODATE,
                           PTDUSRID=user, TRXDSCRN=f"{v['VNDCLSID'].title()} invoice")
                pm_docs.append(inv)
                led.post(d, "PMTRX", "Payables Transaction Entry", src, user, 4,
                         [(ACT[v["acct"]], amt, money(0)), (ACT["2100"], money(0), amt)],
                         v["VENDORID"], v["VENDNAME"], inv["VCHRNMBR"])
                pd_ = weekday_on_or_after(d + dt.timedelta(days=rng.randint(12, 50)))
                if pd_ > LAST_DATE or rng.random() < 0.015:
                    continue
                chk += 1
                vch += 1
                src = trx_source("PMCHK")
                puser = rng.choice(USERS_AP)
                pay = dict(VCHRNMBR=f"{vch:08d}", VENDORID=v["VENDORID"], DOCTYPE=6, DOCDATE=pd_,
                           DOCNUMBR=f"{20000 + chk}", DOCAMNT=amt, CURTRXAM=money(0), DUEDATE=pd_,
                           PSTGDATE=pd_, POSTEDDT=pd_, BACHNUMB=f"CHK{pd_:%y%m%d}", TRXSORCE=src,
                           VOIDED=0, VOIDPDATE=NODATE, PTDUSRID=puser, TRXDSCRN="Check payment")
                pm_docs.append(pay)
                led.post(pd_, "PMCHK", "Computer Check", src, puser, 4,
                         [(ACT["2100"], amt, money(0)), (ACT["1100"], money(0), amt)],
                         v["VENDORID"], v["VENDNAME"], pay["VCHRNMBR"])
                if (y, m) in void_check_slots and pd_ + dt.timedelta(days=21) <= LAST_DATE:
                    # Check lost in the mail: voided, reissued three weeks later
                    void_check_slots.discard((y, m))
                    vd = pd_ + dt.timedelta(days=7)
                    pay["VOIDED"], pay["VOIDPDATE"] = 1, vd
                    src = trx_source("PMVPY")
                    led.post(vd, "PMVPY", "Void Historical Payment", src, puser, 4,
                             [(ACT["1100"], amt, money(0)), (ACT["2100"], money(0), amt)],
                             v["VENDORID"], v["VENDNAME"], pay["VCHRNMBR"])
                    pd_ = weekday_on_or_after(vd + dt.timedelta(days=14))
                    chk += 1
                    vch += 1
                    src = trx_source("PMCHK")
                    pay = dict(pay, VCHRNMBR=f"{vch:08d}", DOCNUMBR=f"{20000 + chk}", DOCDATE=pd_, PSTGDATE=pd_,
                               POSTEDDT=pd_, DUEDATE=pd_, BACHNUMB=f"CHK{pd_:%y%m%d}", TRXSORCE=src,
                               VOIDED=0, VOIDPDATE=NODATE, TRXDSCRN="Reissued check")
                    pm_docs.append(pay)
                    led.post(pd_, "PMCHK", "Computer Check", src, puser, 4,
                             [(ACT["2100"], amt, money(0)), (ACT["1100"], money(0), amt)],
                             v["VENDORID"], v["VENDNAME"], pay["VCHRNMBR"])
                pm_applies.append(dict(VENDORID=v["VENDORID"], APFRDCNM=pay["VCHRNMBR"], DOCTYPE=6,
                                       APFRDCDT=pd_, APTVCHNM=inv["VCHRNMBR"], APTODCTY=1,
                                       APTODCNM=inv["DOCNUMBR"], APTODCDT=d, APPLDAMT=amt,
                                       DATE1=pd_, GLPOSTDT=pd_))
                inv["CURTRXAM"] = money(0)

    # General journal entries
    for y, m in month_iter():
        me = month_end(y, m)
        user = rng.choice(USERS_GL)
        close = weekday_on_or_before(me)
        for day in (15, me.day):
            d = weekday_on_or_before(dt.date(y, m, day))
            gross = money(rng.uniform(118000, 126000))
            led.post(d, "GJ", "Payroll", trx_source("GLTRX"), user, 2,
                     [(ACT["6000"], gross, money(0)), (ACT["1100"], money(0), gross)])
        led.post(close, "GJ", "Monthly depreciation", trx_source("GLTRX"), user, 2,
                 [(ACT["6400"], money(9500), money(0)), (ACT["1550"], money(0), money(9500))])
        accr = money(rng.uniform(4000, 9000))
        led.post(close, "GJ", "Utilities accrual", trx_source("GLTRX"), user, 2,
                 [(ACT["6200"], accr, money(0)), (ACT["2200"], money(0), accr)])
        nxt = weekday_on_or_after(me + dt.timedelta(days=1))
        if nxt <= LAST_DATE:
            led.post(nxt, "GJ", "Reverse utilities accrual", trx_source("GLTRX"), user, 2,
                     [(ACT["2200"], accr, money(0)), (ACT["6200"], money(0), accr)])
        if m in (3, 6, 9, 12):
            led.post(close, "GJ", "Quarterly loan interest", trx_source("GLTRX"), "CONTROLLER", 2,
                     [(ACT["7000"], money(7500), money(0)), (ACT["1100"], money(0), money(7500))])
    # Equipment purchases and a few one-off entries an auditor would ask about
    led.post(dt.date(2024, 4, 12), "GJ", "Warehouse racking purchase", trx_source("GLTRX"), "CONTROLLER", 2,
             [(ACT["1500"], money(64000), money(0)), (ACT["1100"], money(0), money(64000))])
    led.post(dt.date(2025, 12, 31), "GJ", "Year-end inventory adjustment", trx_source("GLTRX"), "sa", 2,
             [(ACT["5000"], money(18750.40), money(0)), (ACT["1300"], money(0), money(18750.40))])
    led.post(dt.date(2026, 5, 14), "GJ", PLANTED_JE_REF, trx_source("GLTRX"), "GL.ACCT", 2,
             [(ACT["1500"], money(12345.67), money(0)), (ACT["6300"], money(0), money(12345.67))])
    led.post(dt.date(2026, 7, 4), "GJ", "Owner expense reimbursement", trx_source("GLTRX"), "sa", 2,
             [(ACT["6500"], money(4180.00), money(0)), (ACT["1100"], money(0), money(4180.00))])

    # Year-end close: balance sheet accounts brought forward, P&L closed to retained earnings
    led.lines.sort(key=lambda r: (r["TRXDATE"], r["JRNENTRY"], r["SEQNUMBR"]))
    for y in range(FIRST_YEAR, OPEN_YEAR):
        bal = defaultdict(Decimal)
        for r in led.lines:
            if r["year"] == y:
                bal[r["ACTINDX"]] += r["DEBITAMT"] - r["CRDTAMNT"]
        net_income = sum(-b for a, b in bal.items() if PL[a] == 1)
        bbf = defaultdict(Decimal)
        for a, b in bal.items():
            if PL[a] == 0:
                bbf[a] += b
        bbf[RETAINED_EARNINGS] -= net_income
        lines = [(a, b if b > 0 else money(0), -b if b < 0 else money(0))
                 for a, b in sorted(bbf.items()) if b != 0]
        led.post(dt.date(y + 1, 1, 1), "BBF", "Balance Brought Forward", trx_source("GLTRX"), "sa", 2,
                 lines, period=0)

    # GP numbers journal entries as they post, so number them in date order
    order = {}
    for r in sorted(led.lines, key=lambda r: (r["TRXDATE"], r["SOURCDOC"] != "BBF", r["JRNENTRY"])):
        order.setdefault(r["JRNENTRY"], len(order) + 1)
    for r in led.lines:
        r["JRNENTRY"] = order[r["JRNENTRY"]]

    # Move fully applied documents to history. GP's paid transaction removal for
    # receivables was last run at the 2025 year end; payables moves on apply.
    removal_cutoff = dt.date(2025, 12, 31)
    last_apply = defaultdict(lambda: NODATE)
    for a in rm_applies:
        for k in (a["APFRDCNM"], a["APTODCNM"]):
            last_apply[k] = max(last_apply[k], a["DATE1"])
    for d in rm_docs:
        done = d["CURTRXAM"] == 0 and max(last_apply[d["DOCNUMBR"]], d["DOCDATE"]) <= removal_cutoff
        d["hist"] = d["VOIDSTTS"] == 1 or done
    rm_hist = {d["DOCNUMBR"] for d in rm_docs if d["hist"]}
    for a in rm_applies:
        a["hist"] = a["APFRDCNM"] in rm_hist and a["APTODCNM"] in rm_hist
    for d in pm_docs:
        d["hist"] = d["CURTRXAM"] == 0
    pm_hist = {d["VCHRNMBR"] for d in pm_docs if d["hist"]}
    for a in pm_applies:
        a["hist"] = a["APFRDCNM"] in pm_hist and a["APTVCHNM"] in pm_hist

    return dict(customers=customers, vendors=vendors, lines=led.lines, rm_docs=rm_docs,
                rm_applies=rm_applies, pm_docs=pm_docs, pm_applies=pm_applies)


def lit(v):
    if v is None:
        return "NULL"
    if isinstance(v, (dt.date, dt.datetime)):
        return f"'{v:%Y-%m-%d}'"
    if isinstance(v, (int, Decimal)):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    return "'" + str(v).replace("'", "''") + "'"


def insert(cur, table, cols, rows):
    rows = list(rows)
    for i in range(0, len(rows), 900):
        chunk = rows[i:i + 900]
        values = ",\n".join("(" + ",".join(lit(r[c]) for c in cols) + ")" for r in chunk)
        cur.execute(f"INSERT INTO {table} ({','.join(cols)}) VALUES {values}")
    return len(rows)


def load(conn, data):
    cur = conn.cursor()
    with open(os.path.join(HERE, "schema.sql")) as f:
        ddl = f.read()
    for stmt in ddl.split(";"):
        if stmt.strip() and not all(l.strip().startswith("--") or not l.strip() for l in stmt.splitlines()):
            cur.execute(stmt)

    years = range(FIRST_YEAR, OPEN_YEAR + 1)
    insert(cur, "SY40101", ["YEAR1", "FSTFSCDY", "LSTFSCDY", "NUMOFPER", "HISTORYR"],
           [dict(YEAR1=y, FSTFSCDY=dt.date(y, 1, 1), LSTFSCDY=dt.date(y, 12, 31), NUMOFPER=12,
                 HISTORYR=int(y < OPEN_YEAR)) for y in years])
    insert(cur, "SY40100", ["YEAR1", "PERIODID", "PERIODDT", "PERDENDT", "PERNAME", "SERIES", "ODESCTN", "CLOSED"],
           [dict(YEAR1=y, PERIODID=p, PERIODDT=dt.date(y, p, 1), PERDENDT=month_end(y, p),
                 PERNAME=dt.date(y, p, 1).strftime("%B"), SERIES=0, ODESCTN="",
                 CLOSED=int(month_end(y, p) <= LAST_DATE and y < OPEN_YEAR))
            for y in years for p in range(1, 13)])

    acct_rows = [dict(ACTINDX=ACT[n], ACTNUMBR_1="000", ACTNUMBR_2=n, ACTNUMBR_3="00", ACTALIAS="",
                      ACTDESCR=desc, ACCTTYPE=1, PSTNGTYP=pt, ACCATNUM=cat, TPCLBLNC=tb, ACTIVE=1,
                      CREATDDT=dt.date(2022, 12, 1), ACTNUMST=f"000-{n}-00")
                 for n, desc, pt, cat, tb in ACCOUNTS]
    insert(cur, "GL00100", ["ACTINDX", "ACTNUMBR_1", "ACTNUMBR_2", "ACTNUMBR_3", "ACTALIAS", "ACTDESCR",
                            "ACCTTYPE", "PSTNGTYP", "ACCATNUM", "TPCLBLNC", "ACTIVE", "CREATDDT"], acct_rows)
    insert(cur, "GL00105", ["ACTINDX", "ACTNUMBR_1", "ACTNUMBR_2", "ACTNUMBR_3", "ACTNUMST"], acct_rows)

    gl_cols = ["JRNENTRY", "SOURCDOC", "REFRENCE", "DSCRIPTN", "TRXDATE", "TRXSORCE", "ACTINDX", "POLLDTRX",
               "LASTUSER", "LSTDTEDT", "USWHPSTD", "SERIES", "ORTRXTYP", "ORCTRNUM", "ORMSTRID", "ORMSTRNM",
               "ORDOCNUM", "ORPSTDDT", "ORTRXSRC", "SEQNUMBR", "DEBITAMT", "CRDTAMNT", "CURNCYID", "PERIODID",
               "VOIDED"]
    lines = data["lines"]
    for r in lines:
        r["OPENYEAR"] = r["HSTYEAR"] = r["year"]
    insert(cur, "GL30000", ["HSTYEAR"] + gl_cols, [r for r in lines if r["year"] < OPEN_YEAR])
    insert(cur, "GL20000", ["OPENYEAR"] + gl_cols, [r for r in lines if r["year"] == OPEN_YEAR])

    # Summary tables, built the way posting updates them, minus the planted lost update
    summ = defaultdict(lambda: [Decimal(0), Decimal(0)])
    for r in lines:
        if r["REFRENCE"] == PLANTED_JE_REF:
            continue
        s = summ[(r["ACTINDX"], r["year"], r["PERIODID"])]
        s[0] += r["DEBITAMT"]
        s[1] += r["CRDTAMNT"]
    srows = [dict(ACTINDX=a, YEAR1=y, PERIODID=p, ACCATNUM=CATEGORY[a], DEBITAMT=d, CRDTAMNT=c,
                  PERDBLNC=d - c) for (a, y, p), (d, c) in sorted(summ.items())]
    insert(cur, "GL10111", ["ACTINDX", "YEAR1", "PERIODID", "ACCATNUM", "DEBITAMT", "CRDTAMNT", "PERDBLNC"],
           [r for r in srows if r["YEAR1"] < OPEN_YEAR])
    insert(cur, "GL10110", ["ACTINDX", "YEAR1", "PERIODID", "ACCATNUM", "DEBITAMT", "CRDTAMNT", "PERDBLNC"],
           [r for r in srows if r["YEAR1"] == OPEN_YEAR])

    insert(cur, "RM00101", ["CUSTNMBR", "CUSTNAME", "CUSTCLAS", "ADDRESS1", "CITY", "STATE", "ZIP", "PYMTRMID",
                            "CRLMTAMT", "INACTIVE", "CREATDDT"], data["customers"])
    rm_cols = ["CUSTNMBR", "DOCNUMBR", "RMDTYPAL", "DOCDATE", "GLPOSTDT", "POSTDATE", "DUEDATE", "ORTRXAMT",
               "CURTRXAM", "BACHNUMB", "TRXSORCE", "CHEKNMBR", "CSHRCTYP", "VOIDSTTS", "VOIDDATE", "PTDUSRID",
               "TRXDSCRN"]
    insert(cur, "RM30101", rm_cols, [d for d in data["rm_docs"] if d["hist"]])
    insert(cur, "RM20101", rm_cols, [d for d in data["rm_docs"] if not d["hist"]])
    ap_cols = ["CUSTNMBR", "APFRDCTY", "APFRDCNM", "APFRDCDT", "APTODCTY", "APTODCNM", "APTODCDT", "APPTOAMT",
               "DATE1", "GLPOSTDT"]
    insert(cur, "RM30201", ap_cols, [a for a in data["rm_applies"] if a["hist"]])
    insert(cur, "RM20201", ap_cols, [a for a in data["rm_applies"] if not a["hist"]])

    insert(cur, "PM00200", ["VENDORID", "VENDNAME", "VNDCLSID", "ADDRESS1", "CITY", "STATE", "ZIPCODE",
                            "PYMTRMID", "VENDSTTS", "CREATDDT"], data["vendors"])
    pm_cols = ["VCHRNMBR", "VENDORID", "DOCTYPE", "DOCDATE", "DOCNUMBR", "DOCAMNT", "CURTRXAM", "DUEDATE",
               "PSTGDATE", "POSTEDDT", "BACHNUMB", "TRXSORCE", "VOIDED", "VOIDPDATE", "PTDUSRID", "TRXDSCRN"]
    insert(cur, "PM30200", pm_cols, [d for d in data["pm_docs"] if d["hist"]])
    insert(cur, "PM20000", pm_cols, [d for d in data["pm_docs"] if not d["hist"]])
    pa_cols = ["VENDORID", "APFRDCNM", "DOCTYPE", "APFRDCDT", "APTVCHNM", "APTODCTY", "APTODCNM", "APTODCDT",
               "APPLDAMT", "DATE1", "GLPOSTDT"]
    insert(cur, "PM30300", pa_cols, [a for a in data["pm_applies"] if a["hist"]])
    insert(cur, "PM10200", pa_cols, [a for a in data["pm_applies"] if not a["hist"]])
    conn.commit()


def main():
    host = os.environ.get("GP_HOST", "localhost:14330")
    pw = os.environ["MSSQL_SA_PASSWORD"]
    db = os.environ.get("GP_DB", "TWOSYN")
    admin = pymssql.connect(host, "sa", pw, autocommit=True)
    c = admin.cursor()
    c.execute(f"IF DB_ID('{db}') IS NOT NULL BEGIN ALTER DATABASE {db} SET SINGLE_USER WITH ROLLBACK IMMEDIATE; DROP DATABASE {db}; END")
    c.execute(f"CREATE DATABASE {db}")
    admin.close()

    data = build(random.Random(SEED))
    conn = pymssql.connect(host, "sa", pw, db)
    load(conn, data)
    conn.close()

    # The archive gets its own login with read access only, as a DBA would grant it
    reader, reader_pw = os.environ.get("GP_READER", "gp_archive_reader"), os.environ["GP_READER_PASSWORD"]
    admin = pymssql.connect(host, "sa", pw, db, autocommit=True)
    c = admin.cursor()
    c.execute(f"IF SUSER_ID('{reader}') IS NULL CREATE LOGIN {reader} WITH PASSWORD = '{reader_pw}', CHECK_POLICY = OFF")
    c.execute(f"CREATE USER {reader} FOR LOGIN {reader}")
    c.execute(f"ALTER ROLE db_datareader ADD MEMBER {reader}")
    admin.close()
    print(f"built {db}: {len(data['lines'])} journal lines, {len(data['rm_docs'])} receivables documents, "
          f"{len(data['pm_docs'])} payables documents", file=sys.stderr)


if __name__ == "__main__":
    main()
