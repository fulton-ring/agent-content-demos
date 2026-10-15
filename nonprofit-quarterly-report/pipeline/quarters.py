"""Fiscal quarter ids like FY26-Q2 and the dates that go with them."""

import re
from datetime import date, timedelta

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
QUARTER_RE = re.compile(r"^FY(\d{2})-Q([1-4])$")


def parse(qid, fy_start_month=7):
    m = QUARTER_RE.match(qid)
    if not m:
        raise ValueError(f"not a quarter id: {qid!r} (expected e.g. FY26-Q2)")
    fy, q = 2000 + int(m.group(1)), int(m.group(2))
    month0 = fy_start_month - 1 + (q - 1) * 3          # months since Jan of the year before FY
    year = fy - 1 + month0 // 12 if fy_start_month != 1 else fy + month0 // 12
    start = date(year, month0 % 12 + 1, 1)
    end_month0 = month0 + 3
    end = date(fy - 1 + end_month0 // 12 if fy_start_month != 1 else fy + end_month0 // 12,
               end_month0 % 12 + 1, 1) - timedelta(days=1)
    return start, end


def label(qid, fy_start_month=7):
    start, end = parse(qid, fy_start_month)
    return f"{qid.split('-')[1]} {qid.split('-')[0]} ({MONTHS[start.month - 1]}–{MONTHS[end.month - 1]} {end.year})"


def due_date(qid, days_after, fy_start_month=7):
    return parse(qid, fy_start_month)[1] + timedelta(days=days_after)


def weekdays(qid, fy_start_month=7):
    start, end = parse(qid, fy_start_month)
    d, n = start, 0
    while d <= end:
        n += d.weekday() < 5
        d += timedelta(days=1)
    return n


def previous(qid):
    fy, q = int(qid[2:4]), int(qid[-1])
    return f"FY{fy - 1:02d}-Q4" if q == 1 else f"FY{fy:02d}-Q{q - 1}"


def next_quarter(qid):
    fy, q = int(qid[2:4]), int(qid[-1])
    return f"FY{fy + 1:02d}-Q1" if q == 4 else f"FY{fy:02d}-Q{q + 1}"
