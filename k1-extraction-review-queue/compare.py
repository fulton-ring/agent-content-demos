"""Put the pipelines side by side: output/comparison.md, from each one's metrics.json."""

import json
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "output"
PIPELINES = [("Tesseract and rules", OUT), ("Docling + Qwen3-VL 235B", OUT / "qwen3-vl-235b"),
             ("Docling + Qwen3-VL 30B", OUT / "qwen3-vl-30b")]
ROWS = [("Held-out set, all", "held_out_set"), ("Tuning set, all", "tuning_set"),
        ("Real K-1s, born-digital", "tuning / real / born-digital"),
        ("Held-out, real K-1 office scans", "held out / real / office scan"),
        ("Held-out, real K-1 bad scans", "held out / real / bad scan"),
        ("Held-out, made-up clean scans", "held out / made-up / clean scan"),
        ("Held-out, made-up office scans", "held out / made-up / office scan"),
        ("Held-out, made-up bad scans", "held out / made-up / bad scan")]


def pct(a, b):
    return f"{100 * a / b:.1f}%" if b else "n/a"


def main():
    loaded = [(name, json.loads((d / "metrics.json").read_text())) for name, d in PIPELINES if (d / "metrics.json").exists()]
    out = ["# Pipelines compared", "",
           "Same documents, same answer keys. \"Accepted\" values went straight through; the rest went to the review queue. "
           "A silent error is a wrong value that was accepted.", ""]
    for title, key in ROWS:
        out += [f"## {title}", "",
                "| Pipeline | Boxes | Accepted | Right when accepted | Sent to review | Misreads | Caught | Silent errors |",
                "|---|---|---|---|---|---|---|---|"]
        for name, m in loaded:
            s = m.get(key) or m["by_source"].get(key)
            if not s:
                continue
            out.append(f"| {name} | {s['boxes_checked']} | {s['accepted']} | {s['accepted_correct']} "
                       f"({pct(s['accepted_correct'], s['accepted'])}) | {s['sent_to_review']} "
                       f"({pct(s['sent_to_review'], s['boxes_checked'])}) | {s['wrong']} | {s['wrong_caught_by_review']} "
                       f"| {s['silent_errors']} |")
        out.append("")
    out += ["## Cost and time per document", "", "| Pipeline | Cost | Model time | Docling time | Total time |", "|---|---|---|---|---|"]
    for name, m in loaded:
        if "cost_usd_per_document" in m:
            out.append(f"| {name} | ${m['cost_usd_per_document']:.4f} | {m['model_seconds_per_document']}s "
                       f"| {m['docling_seconds_per_document']}s | {m['seconds_per_document']}s |")
        else:
            out.append(f"| {name} | $0 | none | none | {m['seconds_per_document']}s |")
    out.append("")
    for name, m in loaded:
        boxes = m["all"]["silent_error_boxes"]
        out.append(f"Silent errors, {name}: " + ("; ".join(boxes) if boxes else "none") + ".")
        out.append("")
    (OUT / "comparison.md").write_text("\n".join(out))
    print("\n".join(out))


if __name__ == "__main__":
    main()
