"""The smallest monitor: check every HIFLD Next source endpoint once and append one row each to a log.

Run it daily and the log becomes the record the archive doesn't keep. `run.sh` runs it once.
Settings (optional): SOURCES (default sources.csv), MONITOR_LOG (default log/checks.csv), NETWORK (default local).
"""

import csv
import datetime as dt
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

HERE = Path(__file__).parent
SOURCES = Path(os.environ.get("SOURCES", HERE / "sources.csv"))
LOG = Path(os.environ.get("MONITOR_LOG", HERE / "log" / "checks.csv"))
NETWORK = os.environ.get("NETWORK", "local")
UA = {"User-Agent": "public-endpoint-monitor/0.1 (+https://github.com/fulton-ring/agent-content-demos)"}
FIELDS = ["run_started", "checked_at", "network", "id", "url", "http", "status", "seconds"]


def check(source: dict[str, str], run_started: str) -> dict[str, str]:
    """One GET with one retry. up: 2xx/3xx; blocked: 401/403/429; gone: 404/410; down: 5xx or no answer."""
    started = time.monotonic()
    code = "no answer"
    for attempt in range(2):
        try:
            code = str(requests.get(source["url"], headers=UA, timeout=30).status_code)
        except requests.RequestException as e:
            code = type(e).__name__
        if code.isdigit() and int(code) < 500:
            break
        time.sleep(5 * (attempt + 1))
    status = "down"
    if code.isdigit():
        n = int(code)
        status = "up" if n < 400 else "gone" if n in (404, 410) else "blocked" if n in (401, 403, 429) else "down"
    return {
        "run_started": run_started,
        "checked_at": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "network": NETWORK,
        "id": source["id"],
        "url": source["url"],
        "http": code,
        "status": status,
        "seconds": f"{time.monotonic() - started:.1f}",
    }


def main() -> None:
    assert SOURCES.exists(), f"missing source list {SOURCES}"
    with SOURCES.open() as f:
        sources = list(csv.DictReader(f))
    assert sources, "source list is empty"
    started = time.monotonic()
    run_started = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    with ThreadPoolExecutor(8) as ex:
        rows = list(ex.map(lambda s: check(s, run_started), sources))
    LOG.parent.mkdir(parents=True, exist_ok=True)
    new_file = not LOG.exists()
    with LOG.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if new_file:
            writer.writeheader()
        writer.writerows(rows)
    counts = {s: sum(r["status"] == s for r in rows) for s in ("up", "blocked", "gone", "down")}
    print(f"monitor: {len(rows)} endpoints in {time.monotonic() - started:.1f} s, {counts}, appended to {LOG.name}")


if __name__ == "__main__":
    main()
