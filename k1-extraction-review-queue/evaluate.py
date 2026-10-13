"""Score output/extracted.json against the answer keys.

The real K-1s are scored against real_answer_key.json (keyed by hand), the
made-up documents against answer_key.json (written by generate.py). A scanned
copy of a real K-1 is scored against its original's key.

The numbers that matter for a review queue:
- accuracy of the values that were accepted without review;
- how many wrong values were caught by the queue;
- silent errors: wrong values that were accepted. These are the ones a
  preparer would never see.
Writes output/metrics.json and adds a "correct" flag to each value in
output/extracted.json for the report.
"""

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).parent
# The Tesseract pipeline writes to output/; the model pipeline to output/<model>/, given as the argument.
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "output"


def load_keys():
    keys = {}
    for name in ("real_answer_key.json", "answer_key.json"):
        path = HERE / name
        if path.exists():
            keys.update({k: v for k, v in json.loads(path.read_text()).items() if not k.startswith("_")})
    return keys


def key_for(file, keys):
    if file in keys:
        return keys[file]
    base = re.sub(r"-scan\d[ab]\.pdf$", ".pdf", file)
    return keys.get(base)


def same(a, b):
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) < 0.005
    if isinstance(a, str) and isinstance(b, str):
        # Names and IDs are compared on letters and digits only: "L P" matches "L.P."
        return re.sub(r"[^A-Z0-9]", "", a.upper()) == re.sub(r"[^A-Z0-9]", "", b.upper())
    return a is None and b is None


def scan_level(file, key):
    m = re.search(r"-scan(\d)[ab]\.pdf$", file)
    if m:
        return {"1": "office scan", "2": "bad scan"}[m.group(1)]
    level = key.get("scan_level")
    return {"original": "born-digital", 0: "clean scan", 1: "office scan", 2: "bad scan"}[level]


def statement_check(data):
    """The model pipeline's readings of supplemental statements, against the statement's own text layer.

    The answer keys stop at "STMT", so the statement lines are checked against the
    issuer's PDF: every line on the statement whose code starts with the box number,
    and the amount at the end of that line. Born-digital packages only.
    """
    import pdfplumber
    from extract import parse_value

    lines_total = right = missed = 0
    wrong = []
    for doc in data["documents"]:
        fields = [f for f in doc["fields"] if "statement_lines" in f]
        if not fields:
            continue
        with pdfplumber.open(HERE / "samples" / doc["file"]) as pdf:
            text = [ln for pg in pdf.pages for ln in (pg.extract_text() or "").splitlines()]
        for f in fields:
            box = f["key"].split(" ")[0]
            printed = {ln.split()[0]: ln.split()[-1] for ln in text if re.match(rf"^{box}[A-Z]{{1,2}}\d*\s", ln)}
            read = {ln["code"].replace(" ", "").upper(): ln for ln in f["statement_lines"]}
            missed += len(set(printed) - set(read))
            for code, ln in read.items():
                lines_total += 1
                if code in printed and parse_value(printed[code])[0] == ln["value"]:
                    right += 1
                else:
                    wrong.append(f"{doc['file']} {code} read {ln['printed']}, statement says {printed.get(code)}")
    if not lines_total and not missed:
        return None
    return {"lines_read": lines_total, "right": right, "lines_missed": missed, "wrong": wrong}


def main():
    data = json.loads((OUT / "extracted.json").read_text())
    keys = load_keys()
    rows = []
    for doc in data["documents"]:
        key = key_for(doc["file"], keys)
        if not key:
            continue
        truth = dict(key["fields"])
        for k in ("payer_ein", "payer_name"):
            if k in key.get("header", {}) and doc["form"] != "BROKER":
                truth[k] = key["header"][k]
        got = {f["key"]: f for f in doc["fields"] if f["key"] != "page"}
        group = "real" if doc["file"][:2] in ("01", "02", "03") else "made-up"
        # Born-digital originals have nothing to tune (no OCR), so they count with the tuning set.
        held_out = doc["file"].startswith("2") or bool(re.search(r"-scan\db\.pdf$", doc["file"]))
        level = scan_level(doc["file"], key)
        for k in sorted(set(truth) | set(got)):
            f = got.get(k)
            expected = truth.get(k)
            value = f["value"] if f else None
            correct = same(value, expected) and (f is not None or expected is None)
            # A value we read that isn't on the key at all (a phantom row) is wrong.
            if f is not None and k not in truth:
                correct = False
            # A missing box reads as blank, unless the whole page was sent to review.
            status = f["status"] if f else ("review" if doc.get("page_review") else "accepted")
            # A coded row we missed still reaches a reviewer when its box has an unreadable row, or a row
            # with the same code letter, in review.
            box = k.split(" ")[0]
            letter = k.split(" ")[1].rstrip("*") if " " in k else None
            if f is None and letter and any(g["status"] == "review" and g["key"].split(" (")[0].rstrip("*") in (f"{box} ?", f"{box} {letter}")
                                            for g in doc["fields"]):
                status = "review"
            if f is not None:
                f["correct"] = correct
                f["expected"] = expected
            rows.append({"file": doc["file"], "group": group, "level": level, "key": k, "held_out": held_out,
                         "blank": expected is None, "correct": correct, "status": status,
                         "statement": expected == "STMT"})

    def summarize(rs):
        acc = [r for r in rs if r["status"] == "accepted"]
        rev = [r for r in rs if r["status"] == "review"]
        wrong = [r for r in rs if not r["correct"]]
        caught = [r for r in wrong if r["status"] == "review"]
        silent = [r for r in wrong if r["status"] == "accepted"]
        filled = [r for r in rs if not r["blank"]]
        return {
            "documents": len({r["file"] for r in rs}),
            "boxes_checked": len(rs),
            "boxes_with_a_value": len(filled),
            "correct": sum(r["correct"] for r in rs),
            "accepted": len(acc),
            "accepted_correct": sum(r["correct"] for r in acc),
            "sent_to_review": len(rev),
            "review_because_statement": sum(r["statement"] for r in rev),
            "review_but_correct": sum(r["correct"] for r in rev),
            "wrong": len(wrong),
            "wrong_caught_by_review": len(caught),
            "silent_errors": len(silent),
            "silent_error_boxes": [f"{r['file']} box {r['key']}" for r in silent],
        }

    by = defaultdict(list)
    for r in rows:
        by[("held out" if r["held_out"] else "tuning", r["group"], r["level"])].append(r)
    metrics = {"all": summarize(rows),
               "tuning_set": summarize([r for r in rows if not r["held_out"]]),
               "held_out_set": summarize([r for r in rows if r["held_out"]]),
               "real_k1s": summarize([r for r in rows if r["group"] == "real"]),
               "made_up": summarize([r for r in rows if r["group"] == "made-up"]),
               "by_source": {f"{st} / {g} / {lv}": summarize(rs) for (st, g, lv), rs in sorted(by.items(), reverse=True)},
               "seconds_per_document": round(sum(d["seconds"] for d in data["documents"]) / max(1, len(data["documents"])), 1),
               "engine": data.get("tesseract") or data.get("model")}
    if any("cost_usd" in d for d in data["documents"]):
        metrics["cost_usd_total"] = round(sum(d["cost_usd"] for d in data["documents"]), 4)
        metrics["cost_usd_per_document"] = round(metrics["cost_usd_total"] / len(data["documents"]), 5)
        metrics["model_seconds_per_document"] = round(sum(d["model_seconds"] for d in data["documents"]) / len(data["documents"]), 1)
        metrics["docling_seconds_per_document"] = round(sum(d["docling_seconds"] for d in data["documents"]) / len(data["documents"]), 1)
    stmt = statement_check(data)
    if stmt:
        metrics["statement_lines"] = stmt
    (OUT / "metrics.json").write_text(json.dumps(metrics, indent=1))
    (OUT / "extracted.json").write_text(json.dumps(data, indent=1))

    print(f"\n{'documents':44s} docs  boxes  correct  accepted (right)  review (STMT)  wrong  caught  silent")
    for name, m in ([("ALL", metrics["all"]), ("tuning set", metrics["tuning_set"]), ("HELD-OUT SET", metrics["held_out_set"])]
                    + list(metrics["by_source"].items())):
        print(f"{name:44s} {m['documents']:4d} {m['boxes_checked']:6d} {m['correct']:8d} "
              f"{m['accepted']:8d} ({m['accepted_correct']:4d}) {m['sent_to_review']:7d} ({m['review_because_statement']:2d}) "
              f"{m['wrong']:6d} {m['wrong_caught_by_review']:7d} {m['silent_errors']:7d}")
    for s in metrics["all"]["silent_error_boxes"]:
        print("  silent error:", s)
    if stmt:
        print(f"statement lines: {stmt['right']} of {stmt['lines_read']} read right, {stmt['lines_missed']} missed")


if __name__ == "__main__":
    main()
