"""Save a dated snapshot of what USGS currently publishes for the gages live Polymarket markets settle on.

USGS keeps no history of provisional values, so a later run can only compare against the approved record
if someone saved the provisional one. Writes snapshots/<YYYY-MM-DD>/{daily,continuous}_<site>.csv.
Run: uv run snapshot.py   (SNAPSHOT_START sets the first day, default 2026-09-01)
"""

import datetime as dt
import os
from pathlib import Path

import httpx

from fetch import usgs_items

SITES = {
    "07010000": "Mississippi River at St. Louis, MO",
    "07374000": "Mississippi River at Baton Rouge, LA",
    "10010000": "Great Salt Lake at Saltair Boat Harbor, UT",
}


def main() -> None:
    now = dt.datetime.now(dt.UTC)
    start = os.environ.get("SNAPSHOT_START", "2026-09-01")
    out = Path(os.environ.get("SNAPSHOT_DIR", Path(__file__).parent / "snapshots")) / now.date().isoformat()
    out.mkdir(parents=True, exist_ok=True)
    with httpx.Client() as client:
        for site, name in SITES.items():
            for collection in ("daily", "continuous"):
                params = {"monitoring_location_id": f"USGS-{site}", "time": f"{start}T00:00:00Z/.."}
                table = usgs_items(client, collection, params)
                assert table.height > 0, f"no {collection} values for {site}"
                path = out / f"{collection}_{site}.csv"
                table.write_csv(path)
                print(f"{name}: {collection} {table.height} rows -> {path}")
    (out / "fetched_at.txt").write_text(now.isoformat() + "\n")


if __name__ == "__main__":
    main()
