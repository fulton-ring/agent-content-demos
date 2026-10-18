"""Reading a printed amount. Shared by 2_extraction.py (the review rules) and 3_results.py (the statement check)."""

import re
from typing import Any

AMOUNT = re.compile(r"^(\(|-)?\$?\d{1,3}(,\d{3})*(\.\d{2})?\)?$")


def parse_value(text: str) -> tuple[Any, str]:
    """(value, kind), where kind is amount, statement, text, blank or unreadable."""
    t = text.replace("$", "").replace(" ", "")
    if not t:
        return None, "blank"
    if t in ("-", "—", "–"):
        return 0, "amount"
    if t.upper() == "STMT":
        return "STMT", "statement"
    if AMOUNT.match(t):
        v = float(t.strip("()-").replace(",", ""))
        v = v if "." in t else int(v)
        return (-v if t[0] in "(-" else v), "amount"
    if re.fullmatch(r"[A-Z]{2,}", t):
        return t, "text"  # a country code in the foreign transactions box
    return None, "unreadable"
