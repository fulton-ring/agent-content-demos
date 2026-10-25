import marimo

__generated_with = "0.10.0"
app = marimo.App(width="medium")


@app.cell
def _():
    import json
    import os
    import statistics
    import subprocess
    import sys
    import time
    from collections.abc import Callable
    from pathlib import Path

    import httpx
    import marimo as mo
    import polars as pl

    return Callable, Path, httpx, json, mo, os, pl, statistics, subprocess, sys, time


@app.cell
def _(mo):
    mo.md(
        """
        # Can a modern stack answer the queries people send to Overpass?

        Overpass is the API most people use to pull features out of OpenStreetMap
        (OSM). The main public instance rate-limits everyone. Hosting your own means
        running Overpass's own database and its sync scripts. The candidate here is
        **osm2pgsql → PostGIS behind a small FastAPI service** (`service.py`), which
        uses tools that GIS teams already run.

        We load **the same regional extract into both**, on the same machine, one at
        a time, and send ten typical queries to each over HTTP. We check that both
        sides return the same element IDs, then measure latency, disk, RAM and
        import time. Last, we apply the same hour of OSM replication diffs to both.
        """
    )
    return


@app.cell
def _(Path, os):
    # Everything the run depends on. The BBBike extract is used because Geofabrik
    # was unreachable from our worker sessions; any .osm.pbf extract works.
    EXTRACT_URL = os.environ.get(
        "EXTRACT_URL",
        "https://download.bbbike.org/osm/bbbike/WashingtonDC/WashingtonDC.osm.pbf",
    )
    # One hour of planet replication diffs, 2026-10-24 00:00-01:00Z, right after
    # the extract's snapshot time.
    DIFF_URL = os.environ.get(
        "DIFF_URL",
        "https://planet.openstreetmap.org/replication/hour/000/123/714.osc.gz",
    )
    RUNS = int(os.environ.get("RUNS", "7"))
    HERE = Path(__file__).parent
    DATA = HERE / "data"
    RESULTS = HERE / "results"
    DATA.mkdir(exist_ok=True)
    RESULTS.mkdir(exist_ok=True)
    # Images pinned by digest: Overpass 0.7.62 (wiktorn), PostGIS 17-3.5, osm2pgsql 2.3.1.
    OVERPASS_IMAGE = "wiktorn/overpass-api@sha256:9bb5f4a9b54cd225bf828c04c67e7f4010650ff4d70b72157a9473a9ba02d93c"
    POSTGIS_IMAGE = "postgis/postgis@sha256:01a6a70e41e6c4467c8f55f6063555ed72db2d6662cd0d571040d42eadaeb6f6"
    OSM2PGSQL_IMAGE = "iboates/osm2pgsql@sha256:6548a1e2492e08fa0d5ce987d382ad57c4b21c8a94ff00017c6109770a061b79"
    OVERPASS_URL = "http://127.0.0.1:12345/api/interpreter"
    CANDIDATE_URL = "http://127.0.0.1:18000/query"
    DB_URL = "postgresql://postgres:osm@127.0.0.1:15432/osm"
    return (
        CANDIDATE_URL,
        DATA,
        DB_URL,
        DIFF_URL,
        EXTRACT_URL,
        HERE,
        OSM2PGSQL_IMAGE,
        OVERPASS_IMAGE,
        OVERPASS_URL,
        POSTGIS_IMAGE,
        RESULTS,
        RUNS,
    )


@app.cell
def _(Callable, subprocess, time):
    def sh(cmd: list[str], may_fail: bool = False) -> str:
        """Run a command and return stdout; fail loudly on a non-zero exit."""
        done = subprocess.run(cmd, capture_output=True, text=True)
        if done.returncode != 0 and not may_fail:
            raise RuntimeError(f"{' '.join(cmd[:4])} failed: {done.stderr[-2000:]}")
        return done.stdout

    def peak_mem_mb(container: str) -> float:
        """Peak memory of a container so far, page cache included (cgroup v1 or v2)."""
        out = sh(
            ["docker", "exec", container, "sh", "-c",
             "cat /sys/fs/cgroup/memory.peak 2>/dev/null"
             " || cat /sys/fs/cgroup/memory/memory.max_usage_in_bytes"]
        )
        return int(out.strip()) / 2**20

    def used_mem_mb(container: str) -> float:
        """Memory in use now, as `docker stats` reports it (page cache excluded)."""
        out = sh(["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", container])
        used = out.split("/")[0].strip()
        for unit, factor in [("GiB", 1024), ("MiB", 1), ("KiB", 1 / 1024), ("B", 1 / 2**20)]:
            if used.endswith(unit):
                return float(used[: -len(unit)]) * factor
        raise ValueError(f"unexpected docker stats output: {out!r}")

    def wait_until(check: Callable[[], bool], what: str, limit_s: float) -> None:
        """Poll `check()` every 2 s until it's true, for at most `limit_s` seconds."""
        deadline = time.monotonic() + limit_s
        while time.monotonic() < deadline:
            if check():
                return
            time.sleep(2)
        raise TimeoutError(f"gave up waiting for {what}")

    return peak_mem_mb, sh, used_mem_mb, wait_until


@app.cell
def _(mo):
    mo.md(
        """
        ## The data

        One public extract: BBBike's Washington DC extract (DC with Arlington,
        Alexandria and parts of Maryland; about 65 MB, 6.3 M nodes, 0.96 M ways).
        OSM data © OpenStreetMap contributors, ODbL. BBBike refreshes it weekly, so a
        later run loads a later snapshot. Both sides always load the same file, and
        the snapshot time is printed below.
        """
    )
    return


@app.cell
def _(DATA, DIFF_URL, EXTRACT_URL, OVERPASS_IMAGE, sh):
    for _url, _name in [(EXTRACT_URL, "extract.osm.pbf"), (DIFF_URL, "diff.osc.gz")]:
        if not (DATA / _name).exists():
            sh(["curl", "-fsSL", "--retry", "3", "-o", str(DATA / _name), _url])
    snapshot = sh(
        ["docker", "run", "--rm", "-v", f"{DATA}:/d:ro", "--entrypoint", "osmium",
         OVERPASS_IMAGE, "fileinfo", "-g", "header.option.timestamp", "/d/extract.osm.pbf"]
    ).strip()
    extract_mb = (DATA / "extract.osm.pbf").stat().st_size / 2**20
    print(f"extract: {extract_mb:.0f} MB, snapshot {snapshot}")
    return extract_mb, snapshot


@app.cell
def _(mo):
    mo.md(
        """
        ## Side 1: Overpass, from the Docker image its wiki points to

        `wiktorn/overpass-api` is the image the Overpass wiki lists under "Via a
        Docker image". It isn't an official Overpass release, but it's the usual way
        to host Overpass. Its `init` mode only reads `.osm.bz2`, so we use the
        image's documented preprocess step to convert the PBF. That conversion counts
        as import time, because anyone hosting Overpass this way pays it too. Area
        generation, which `area[...]` queries need, is part of init. Diffs are off
        here; we apply one hour of them by hand later.
        """
    )
    return


@app.cell
def _(DATA, OVERPASS_IMAGE, peak_mem_mb, sh, snapshot, time, wait_until):
    for _c in ["ovp", "pg"]:
        sh(["docker", "rm", "-f", _c], may_fail=True)
    sh(["docker", "volume", "rm", "-f", "ovp_db"], may_fail=True)
    _t0 = time.monotonic()
    sh(
        ["docker", "run", "-d", "--name", "ovp", "-p", "12345:80",
         "-v", f"{DATA}:/data:ro", "-v", "ovp_db:/db",
         "-e", "OVERPASS_MODE=init", "-e", "OVERPASS_META=no",
         "-e", "OVERPASS_PLANET_URL=file:///data/extract.osm.pbf",
         "-e", "OVERPASS_PLANET_PREPROCESS=mv /db/planet.osm.bz2 /db/planet.osm.pbf"
               " && osmium cat -o /db/planet.osm.bz2 /db/planet.osm.pbf && rm /db/planet.osm.pbf",
         "-e", "OVERPASS_STOP_AFTER_INIT=false",
         "-e", "OVERPASS_ALLOW_DUPLICATE_QUERIES=yes",
         OVERPASS_IMAGE]
    )
    _probe = "http://127.0.0.1:12345/api/interpreter?data=[out:json];node(1);out;"
    wait_until(lambda: '"generator"' in sh(["curl", "-s", _probe], may_fail=True),
               "the Overpass import", 4 * 3600)
    overpass_import_s = time.monotonic() - _t0
    overpass_import_peak_mb = peak_mem_mb("ovp")
    print(f"Overpass ({snapshot}) import: {overpass_import_s:.0f} s, "
          f"peak memory {overpass_import_peak_mb:.0f} MB incl. page cache")
    return overpass_import_peak_mb, overpass_import_s


@app.cell
def _(mo):
    mo.md(
        """
        ## Side 2: the candidate, osm2pgsql into PostGIS

        osm2pgsql runs in `--slim` mode with the flex style in `flex.lua`. Slim mode
        keeps "middle" tables holding every node, way and relation with its tags,
        way node lists and relation members. That's Overpass's own data model, so
        recursion becomes a lookup. It's also what lets osm2pgsql apply diffs.
        `flex.lua` adds three tables with geometry and GiST and GIN indexes for
        tagged nodes, ways and named areas. Both PostgreSQL and osm2pgsql run with
        default settings. We start this after Overpass has finished so the two
        imports don't compete for the machine.
        """
    )
    return


@app.cell
def _(
    DATA,
    HERE,
    OSM2PGSQL_IMAGE,
    POSTGIS_IMAGE,
    overpass_import_s,
    peak_mem_mb,
    sh,
    time,
    wait_until,
):
    assert overpass_import_s > 0
    sh(["docker", "run", "-d", "--name", "pg", "-p", "15432:5432",
        "-e", "POSTGRES_PASSWORD=osm", "-e", "POSTGRES_DB=osm", POSTGIS_IMAGE])
    wait_until(
        lambda: "1" in sh(["docker", "exec", "pg", "psql", "-U", "postgres", "-d", "osm",
                           "-Atc", "select 1"], may_fail=True),
        "PostgreSQL to start", 120,
    )
    time.sleep(3)  # the image restarts postgres once after its init scripts
    wait_until(
        lambda: "1" in sh(["docker", "exec", "pg", "psql", "-U", "postgres", "-d", "osm",
                           "-Atc", "select 1"], may_fail=True),
        "PostgreSQL to restart", 120,
    )
    _t0 = time.monotonic()
    _log = sh(
        ["docker", "run", "--rm", "--network", "host", "--entrypoint", "sh",
         "-e", "PGPASSWORD=osm", "-v", f"{DATA}:/data:ro", "-v", f"{HERE}:/style:ro",
         OSM2PGSQL_IMAGE, "-c",
         "osm2pgsql --slim -d osm -U postgres -H 127.0.0.1 -P 15432"
         " -O flex -S /style/flex.lua /data/extract.osm.pbf"
         " && (cat /sys/fs/cgroup/memory.peak 2>/dev/null"
         " || cat /sys/fs/cgroup/memory/memory.max_usage_in_bytes)"]
    )
    candidate_import_s = time.monotonic() - _t0
    osm2pgsql_peak_mb = int(_log.strip()) / 2**20
    postgres_import_peak_mb = peak_mem_mb("pg")
    print(f"candidate import: {candidate_import_s:.0f} s, peak memory "
          f"osm2pgsql {osm2pgsql_peak_mb:.0f} MB + PostgreSQL {postgres_import_peak_mb:.0f} MB")
    return candidate_import_s, osm2pgsql_peak_mb, postgres_import_peak_mb
