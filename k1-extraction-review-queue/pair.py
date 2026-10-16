"""Check one model with another: accept a value only when two models read the same thing.

Takes two model-alone runs (extract_vlm.py --model-only) and writes a combined
run that evaluate.py and report.py read like any other:

    python pair.py output/gemini-3.8-flash-alone output/glm-5.3-flash-alone

A value is accepted when both models report the same box (and code) with the same
value, and neither model has its own reason to send it to review (low confidence,
STMT, a failed cross-check). Anything only one model reported, or that the two
read differently, goes to review. The first model's reading is the one shown.
No API calls: it only reads the two runs' extracted.json.
"""

import json
import sys
from pathlib import Path

from extract_vlm import agrees, same_text

HERE = Path(__file__).parent


def name_of(d):
    return d.name.removesuffix("-alone")


def same(fa, fb):
    if fa["key"].startswith("payer"):
        return same_text(fa["value"], fb["value"])
    return agrees(fa["raw"], fb["raw"])


def missing_cost(d):
    """Responses with no known cost; runs from before this was counted mark them with a NaN cost."""
    return d.get("cost_missing_responses", 0) + (0 if d["cost_usd"] == d["cost_usd"] else 1)


def combine(da, db, na, nb, dir_a):
    fb = {f["key"]: f for f in db["fields"]}
    fields = []
    for fa in da["fields"]:
        f = dict(fa, reasons=list(fa["reasons"]))
        other = fb.pop(fa["key"], None)
        if other is None:
            f["reasons"].append(f"only {na} reported it")
        else:
            f["reasons"] += [r for r in other["reasons"] if r not in f["reasons"]]
            if not same(fa, other):
                f["reasons"].append(f"{nb} read '{other['raw']}'")
            f["confidence"] = min(fa["confidence"], other["confidence"])
        fields.append(f)
    for other in fb.values():  # what only the second model reported
        fields.append(dict(other, reasons=list(other["reasons"]) + [f"only {nb} reported it"], page=other["page"]))
    for f in fields:
        f["status"] = "review" if f["reasons"] else "accepted"
    pages = {k: f"../{dir_a.name}/{v}" for k, v in da["pages"].items()}
    return dict(da, pages=pages, fields=fields, second_read=nb, page_review=da.get("page_review") or db.get("page_review"),
                cost_usd=round(sum(d["cost_usd"] for d in (da, db) if d["cost_usd"] == d["cost_usd"]), 6),
                cost_missing_responses=missing_cost(da) + missing_cost(db),
                failed_attempts=da.get("failed_attempts", 0) + db.get("failed_attempts", 0),
                input_tokens=da["input_tokens"] + db["input_tokens"],
                output_tokens=da["output_tokens"] + db["output_tokens"],
                model_calls=da["model_calls"] + db["model_calls"],
                # The two models run side by side, so the wait is the slower of the two.
                model_seconds=max(da["model_seconds"], db["model_seconds"]),
                seconds=round(da["docling_seconds"] + max(da["model_seconds"], db["model_seconds"]), 1))


def main():
    dir_a, dir_b = Path(sys.argv[1]), Path(sys.argv[2])
    a = json.loads((dir_a / "extracted.json").read_text())
    b = json.loads((dir_b / "extracted.json").read_text())
    na, nb = name_of(dir_a), name_of(dir_b)
    docs_b = {d["file"]: d for d in b["documents"]}
    # A document either model failed on can't be checked by both, so it counts as failed for the pair too.
    docs = [combine(d, docs_b[d["file"]], na, nb, dir_a) for d in a["documents"] if d["file"] in docs_b]
    if not docs:
        sys.exit("the two runs have no documents in common")
    done = {d["file"] for d in docs}
    failed = {f["file"]: f["error"] for run in (a, b) for f in run.get("failed_documents", [])}
    failed.update({d["file"]: "only one model read it" for run in (a, b) for d in run["documents"]
                   if d["file"] not in done and d["file"] not in failed})
    out = HERE / "output" / f"pair-{na}+{nb}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "extracted.json").write_text(json.dumps({
        "pipeline": "two vision-language models that must agree", "model": f"{a['model']} checked by {b['model']}",
        "models": [a["model"], b["model"]], "documents": docs,
        "failed_documents": [{"file": f, "error": e} for f, e in sorted(failed.items())]}, indent=1))
    n = sum(len(d["fields"]) for d in docs)
    r = sum(f["status"] == "review" for d in docs for f in d["fields"])
    known = [d["cost_usd"] for d in docs if not d["cost_missing_responses"]]
    cost = f"${sum(known) / len(known):.4f} per document" if known else "no known cost"
    unknown = len(docs) - len(known)
    print(f"{out.name}: {len(docs)} documents, {n} values, {r} to review, {cost}"
          + (f" ({unknown} documents with an unknown cost left out)" if unknown else "")
          + (f"; {len(failed)} documents failed: {', '.join(sorted(failed))}" if failed else ""))


if __name__ == "__main__":
    main()
