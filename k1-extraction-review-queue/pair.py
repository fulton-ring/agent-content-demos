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
    return dict(da, pages=pages, fields=fields, second_read=nb,
                cost_usd=round(da["cost_usd"] + db["cost_usd"], 6),
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
    missing = [d["file"] for d in a["documents"] if d["file"] not in docs_b]
    if missing or len(a["documents"]) != len(b["documents"]):
        sys.exit(f"the two runs don't cover the same documents: {missing or 'different counts'}")
    docs = [combine(d, docs_b[d["file"]], na, nb, dir_a) for d in a["documents"]]
    out = HERE / "output" / f"pair-{na}+{nb}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "extracted.json").write_text(json.dumps({
        "pipeline": "two vision-language models that must agree", "model": f"{a['model']} checked by {b['model']}",
        "models": [a["model"], b["model"]], "documents": docs}, indent=1))
    n = sum(len(d["fields"]) for d in docs)
    r = sum(f["status"] == "review" for d in docs for f in d["fields"])
    print(f"{out.name}: {len(docs)} documents, {n} values, {r} to review, "
          f"${sum(d['cost_usd'] for d in docs) / len(docs):.4f} per document")


if __name__ == "__main__":
    main()
