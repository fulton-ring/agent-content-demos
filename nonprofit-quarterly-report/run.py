"""One command: generate the site files, refresh, build, then drop in a second quarter and refresh again.

    python3 run.py

1. Clears inbox/ and output/.
2. Generates FY26-Q1 site submissions into inbox/FY26-Q1/ and runs the refresh.
   The output at that point is kept in snapshots/before/ (one quarter).
3. Drops FY26-Q2 submissions into inbox/FY26-Q2/ and runs the same refresh
   again, with no other changes. The result is output/ (two quarters).
4. Prints what changed between the two builds and writes output/run-log.txt.
"""

import io
import json
import shutil
import sys
import time
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from generate import generate  # noqa: E402
from refresh import refresh  # noqa: E402


def files(folder):
    return sorted(str(p.relative_to(folder)) for p in folder.rglob("*") if p.is_file())


def main():
    log = io.StringIO()

    def say(msg=""):
        print(msg)
        log.write(msg + "\n")

    t0 = time.perf_counter()
    inbox, out, before = HERE / "inbox", HERE / "output", HERE / "snapshots" / "before"
    for d in (inbox, out, before):
        if d.exists():
            shutil.rmtree(d)

    for step, qid in enumerate(["FY26-Q1", "FY26-Q2"], 1):
        t = time.perf_counter()
        folder, written = generate(qid, inbox)
        gen_s = time.perf_counter() - t
        say(f"[{step}] dropped {qid} into inbox/{qid}/: {len(written)} sites ({', '.join(written)}), "
            f"{len(list(folder.iterdir()))} files, generated in {gen_s:.2f}s")
        buf = io.StringIO()
        with redirect_stdout(buf):
            results, elapsed = refresh(inbox, out)
        for line in buf.getvalue().splitlines():
            say("    " + line)
        if step == 1:
            before.parent.mkdir(exist_ok=True)
            shutil.copytree(out, before)
            say(f"    kept this build in snapshots/before/ ({len(files(before))} files)")

    b, a = set(files(before)), set(files(out))
    say()
    say("before -> after (no code or config edited between the two refreshes):")
    say(f"    files added: {', '.join(sorted(a - b))}")
    say(f"    files rebuilt: {', '.join(sorted(a & b))}")
    q1_before = json.loads((before / "data" / "FY26-Q1.json").read_text())
    q1_after = json.loads((out / "data" / "FY26-Q1.json").read_text())
    same = json.dumps(q1_before, sort_keys=True) == json.dumps(q1_after, sort_keys=True)
    say(f"    FY26-Q1 numbers identical in both builds: {'yes' if same else 'NO'}")
    say(f"    report.html now shows: {results[-1]['label']}; dashboard quarters: {', '.join(r['quarter'] for r in results)}")
    say(f"total time: {time.perf_counter() - t0:.2f}s")
    (out / "run-log.txt").write_text(log.getvalue())


if __name__ == "__main__":
    main()
