import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import gzip
    import json
    import os
    import shlex
    import statistics
    import subprocess
    import sys
    import time
    import xml.etree.ElementTree as ET
    from collections.abc import Callable
    from datetime import datetime
    from pathlib import Path

    import httpx
    import marimo as mo
    import polars as pl

    return (ET, Callable, Path, datetime, gzip, httpx, json, mo, os, pl, shlex, statistics, subprocess, sys, time)


@app.cell
def _(mo):
    mo.md("""
    # Can a modern stack answer the queries people send to Overpass?

    Overpass is the API most people use to pull features out of OpenStreetMap
    (OSM). The main public instance rate-limits everyone. Hosting your own means
    running Overpass's own database and its sync scripts. The candidate here is
    **osm2pgsql → PostGIS behind a small FastAPI service** (`service.py`), which
    uses tools that GIS teams already run.

    We load **the same regional extract into both**, on the same machine, one at
    a time, and send ten typical queries to each over HTTP. We check that both
    sides return the same element IDs, then measure latency, disk, RAM and
    import time. Last, we apply the same OSM replication diffs to both and check
    they still agree.
    """)
    return


@app.cell
def _(Path, os):
    # Everything the run depends on. The BBBike extract is used because Geofabrik
    # was unreachable from our worker sessions; any .osm.pbf extract works.
    EXTRACT_URL = os.environ.get(
        "EXTRACT_URL", "https://download.bbbike.org/osm/bbbike/WashingtonDC/WashingtonDC.osm.pbf"
    )
    # Hourly planet replication diffs, starting at the extract's snapshot time.
    REPLICATION = "https://planet.openstreetmap.org/replication/hour"
    DIFF_HOURS = int(os.environ.get("DIFF_HOURS", "16"))
    RUNS = int(os.environ.get("RUNS", "7"))
    HERE = Path(__file__).resolve().parent
    assert " " not in str(HERE), "run this from a path without spaces (it is mounted into Docker)"
    DATA = HERE / "data"
    RESULTS = HERE / "results"
    DATA.mkdir(exist_ok=True)
    RESULTS.mkdir(exist_ok=True)
    # Images pinned by digest: Overpass 0.7.62.11 (wiktorn), PostGIS 17-3.5, osm2pgsql 2.3.1.
    OVERPASS_IMAGE = "wiktorn/overpass-api@sha256:9bb5f4a9b54cd225bf828c04c67e7f4010650ff4d70b72157a9473a9ba02d93c"
    POSTGIS_IMAGE = "postgis/postgis@sha256:01a6a70e41e6c4467c8f55f6063555ed72db2d6662cd0d571040d42eadaeb6f6"
    OSM2PGSQL_IMAGE = "iboates/osm2pgsql@sha256:6548a1e2492e08fa0d5ce987d382ad57c4b21c8a94ff00017c6109770a061b79"
    OVERPASS_URL = "http://127.0.0.1:12345/api/interpreter"
    CANDIDATE_URL = "http://127.0.0.1:18000/query"
    DB_URL = "postgresql://postgres:osm@127.0.0.1:15432/osm"
    # osm2pgsql runs in its own container and reaches PostgreSQL on the host network.
    OSM2PGSQL = (
        f"docker run --rm --network host --entrypoint sh -e PGPASSWORD=osm"
        f" -v {DATA}:/data:ro -v {HERE}:/style:ro {OSM2PGSQL_IMAGE} -c"
    )
    PSQL = "docker exec pg psql -U postgres -d osm -At"
    return (
        CANDIDATE_URL,
        DATA,
        DB_URL,
        DIFF_HOURS,
        EXTRACT_URL,
        HERE,
        OSM2PGSQL,
        OVERPASS_IMAGE,
        OVERPASS_URL,
        POSTGIS_IMAGE,
        PSQL,
        REPLICATION,
        RESULTS,
        RUNS,
    )


@app.cell
def _(Callable, shlex, subprocess, time):
    def sh(cmd: str, may_fail: bool = False) -> str:
        """Run a shell-style command line (split, not passed to a shell); return stdout, fail loudly."""
        done = subprocess.run(shlex.split(cmd), capture_output=True, text=True)
        if done.returncode != 0 and not may_fail:
            raise RuntimeError(f"`{cmd[:100]}` failed: {done.stderr[-2000:]}")
        return done.stdout

    def peak_mem_mb(container: str) -> float:
        """Peak memory of a container so far, page cache included (cgroup v2 or v1)."""
        out = sh(
            f"docker exec {container} sh -c"
            " 'cat /sys/fs/cgroup/memory.peak 2>/dev/null || cat /sys/fs/cgroup/memory/memory.max_usage_in_bytes'"
        )
        return int(out.strip()) / 2**20

    def used_mem_mb(container: str) -> float:
        """Memory in use now, as `docker stats` reports it (page cache excluded)."""
        out = sh(f"docker stats --no-stream --format '{{{{.MemUsage}}}}' {container}")
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
    mo.md("""
    ## The data

    One public extract: BBBike's Washington DC extract (DC with Arlington,
    Alexandria and parts of Maryland; about 65 MB, 6.3 M nodes, 0.96 M ways).
    OSM data © OpenStreetMap contributors, ODbL. BBBike refreshes it weekly, so a
    later run loads a later snapshot. Both sides always load the same file, and
    the snapshot time is printed below.
    """)
    return


@app.cell
def _(DATA, EXTRACT_URL, OVERPASS_IMAGE, sh):
    if not (DATA / "extract.osm.pbf").exists():
        sh(f"curl -fsSL --retry 3 -o {DATA}/extract.osm.pbf {EXTRACT_URL}")
    snapshot = sh(
        f"docker run --rm -v {DATA}:/d:ro --entrypoint osmium {OVERPASS_IMAGE}"
        " fileinfo -g header.option.timestamp /d/extract.osm.pbf"
    ).strip()
    extract_mb = (DATA / "extract.osm.pbf").stat().st_size / 2**20
    print(f"extract: {extract_mb:.0f} MB, snapshot {snapshot}")
    return (snapshot,)


@app.cell
def _(mo):
    mo.md("""
    ## Side 1: Overpass, from the Docker image its wiki points to

    `wiktorn/overpass-api` is the image the Overpass wiki lists under "Via a
    Docker image". It isn't an official Overpass release, but it's the usual way
    to host Overpass. Its `init` mode only reads `.osm.bz2`, so we use the
    image's documented preprocess step to convert the PBF. That conversion counts
    as import time, because anyone hosting Overpass this way pays it too. Area
    generation, which `area[...]` queries need, is part of init. Diffs are off
    here; we apply them by hand later.
    """)
    return


@app.cell
def _(DATA, OVERPASS_IMAGE, peak_mem_mb, sh, snapshot, time, wait_until):
    sh("docker rm -f ovp pg", may_fail=True)
    sh("docker volume rm -f ovp_db", may_fail=True)
    _t0 = time.monotonic()
    sh(
        f"docker run -d --name ovp -p 12345:80 -v {DATA}:/data:ro -v ovp_db:/db"
        " -e OVERPASS_MODE=init -e OVERPASS_META=no"
        " -e OVERPASS_PLANET_URL=file:///data/extract.osm.pbf"
        " -e 'OVERPASS_PLANET_PREPROCESS=mv /db/planet.osm.bz2 /db/planet.osm.pbf"
        " && osmium cat -o /db/planet.osm.bz2 /db/planet.osm.pbf && rm /db/planet.osm.pbf'"
        " -e OVERPASS_STOP_AFTER_INIT=false -e OVERPASS_ALLOW_DUPLICATE_QUERIES=yes"
        f" {OVERPASS_IMAGE}"
    )
    wait_until(lambda: "ready to receive requests" in sh("docker logs ovp"), "the Overpass import", 4 * 3600)
    # The image leaves /db readable only by its overpass user when /db is a named
    # volume, so the web server can't reach the dispatcher's socket. Open it up.
    sh("docker exec ovp chmod 755 /db")
    _probe = "curl -sg --noproxy '*' 'http://127.0.0.1:12345/api/interpreter?data=[out:json];node(1);out;'"
    wait_until(lambda: '"generator"' in sh(_probe, may_fail=True), "Overpass to answer", 300)
    overpass_import_s = time.monotonic() - _t0
    overpass_import_peak_mb = peak_mem_mb("ovp")
    print(f"Overpass import: {overpass_import_s:.0f} s, peak memory {overpass_import_peak_mb:.0f} MB incl. page cache")
    return overpass_import_peak_mb, overpass_import_s


@app.cell
def _(mo):
    mo.md("""
    ## Side 2: the candidate, osm2pgsql into PostGIS

    osm2pgsql runs in `--slim` mode with the flex style in `flex.lua`. Slim mode
    keeps "middle" tables holding every node, way and relation with its tags,
    way node lists and relation members. That's Overpass's own data model, so
    recursion becomes a lookup. It's also what lets osm2pgsql apply diffs.
    `flex.lua` adds three tables with geometry and GiST and GIN indexes for
    tagged nodes, ways and named areas. Both PostgreSQL and osm2pgsql run with
    default settings. We start this after Overpass has finished so the two
    imports don't compete for the machine.
    """)
    return


@app.cell
def _(OSM2PGSQL, POSTGIS_IMAGE, PSQL, overpass_import_s, peak_mem_mb, sh, time, wait_until):
    assert overpass_import_s > 0
    sh(f"docker run -d --name pg -p 15432:5432 -e POSTGRES_PASSWORD=osm -e POSTGRES_DB=osm {POSTGIS_IMAGE}")
    # The image starts PostgreSQL, runs its init scripts, then restarts it once.
    wait_until(lambda: "1" in sh(f"{PSQL} -c 'select 1'", may_fail=True), "PostgreSQL to start", 120)
    time.sleep(3)
    wait_until(lambda: "1" in sh(f"{PSQL} -c 'select 1'", may_fail=True), "PostgreSQL to restart", 120)
    _t0 = time.monotonic()
    _peak = sh(
        f"{OSM2PGSQL} 'osm2pgsql --slim -d osm -U postgres -H 127.0.0.1 -P 15432"
        " -O flex -S /style/flex.lua /data/extract.osm.pbf"
        " && (cat /sys/fs/cgroup/memory.peak 2>/dev/null || cat /sys/fs/cgroup/memory/memory.max_usage_in_bytes)'"
    )
    candidate_import_s = time.monotonic() - _t0
    osm2pgsql_peak_mb = int(_peak.strip()) / 2**20
    postgres_import_peak_mb = peak_mem_mb("pg")
    print(
        f"candidate import: {candidate_import_s:.0f} s, peak memory "
        f"osm2pgsql {osm2pgsql_peak_mb:.0f} MB + PostgreSQL {postgres_import_peak_mb:.0f} MB"
    )
    return candidate_import_s, osm2pgsql_peak_mb, postgres_import_peak_mb


@app.cell
def _(CANDIDATE_URL, DB_URL, HERE, candidate_import_s, httpx, os, subprocess, sys, wait_until):
    assert candidate_import_s > 0
    service = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "service:app", "--port", "18000", "--log-level", "warning"],
        cwd=HERE,
        env={**os.environ, "CANDIDATE_DB_URL": DB_URL},
    )

    def _up() -> bool:
        try:
            _probe = {"type": "node", "tags": [{"key": "x", "value": "y"}]}
            return httpx.post(CANDIDATE_URL, json=_probe, timeout=5, trust_env=False).status_code == 200
        except httpx.HTTPError:
            return False

    wait_until(_up, "the candidate service", 60)
    return (service,)


@app.cell
def _(mo):
    mo.md("""
    ## The query set

    Ten queries cover the shapes the issue asked for: a tag filter in a bbox,
    around a point, an area by name, ways with their nodes, recursion down and
    up, and two HIFLD Next-style infrastructure pulls (substations, hospitals)
    within a county or state boundary. Overpass gets each one as QL with
    `out ids;`. The candidate gets the same query as JSON, which `service.py`
    turns into SQL. The JSON keeps QL's structure: element type, tag filters,
    one spatial filter, and an optional `(._;>;)` or `(._;<;)`.
    """)
    return


@app.cell
def _(pl):
    CORE = (38.88, -77.05, 38.92, -77.00)  # downtown DC, as south, west, north, east
    WHOLE = (38.78, -77.23, 39.05, -76.84)  # the extract's clip box
    core, whole = ",".join(map(str, CORE)), ",".join(map(str, WHOLE))

    def tag(key: str, value: str, op: str = "=") -> dict[str, str]:
        return {"key": key, "value": value, "op": op}

    WHITE_HOUSE = {"lat": 38.8977, "lon": -77.0365, "radius_m": 500}
    ALEXANDRIA = [tag("name", "Alexandria"), tag("admin_level", "6")]
    DC = [tag("name", "District of Columbia"), tag("admin_level", "4")]
    ARLINGTON = [tag("name", "Arlington County"), tag("admin_level", "6")]
    # (name, Overpass QL, the candidate's JSON for the same query)
    QUERIES: list[tuple[str, str, dict]] = [
        (
            "tag in bbox (nodes)",
            f'node["amenity"="cafe"]({core});',
            {"type": "node", "tags": [tag("amenity", "cafe")], "bbox": CORE},
        ),
        (
            "tag in bbox (nwr)",
            f'nwr["amenity"="school"]({core});',
            {"type": "nwr", "tags": [tag("amenity", "school")], "bbox": CORE},
        ),
        (
            "regex tag, whole extract",
            f'nwr["name"~"^Starbucks"]({whole});',
            {"type": "nwr", "tags": [tag("name", "^Starbucks", "~")], "bbox": WHOLE},
        ),
        (
            "around a point",
            'node["amenity"="restaurant"](around:500,38.8977,-77.0365);',
            {"type": "node", "tags": [tag("amenity", "restaurant")], "around": WHITE_HOUSE},
        ),
        (
            "area by name",
            'area["name"="Alexandria"]["admin_level"="6"]->.a; nwr["leisure"="park"](area.a);',
            {"type": "nwr", "tags": [tag("leisure", "park")], "area": ALEXANDRIA},
        ),
        (
            "ways with their nodes",
            f'way["highway"="primary"]({core}); (._;>;);',
            {"type": "way", "tags": [tag("highway", "primary")], "bbox": CORE, "recurse": "down"},
        ),
        (
            "recurse down (relations)",
            f'rel["route"="subway"]({core}); (._;>;);',
            {"type": "relation", "tags": [tag("route", "subway")], "bbox": CORE, "recurse": "down"},
        ),
        (
            "recurse up (nodes)",
            f'node["railway"="station"]["station"="subway"]({core}); (._;<;);',
            {
                "type": "node",
                "tags": [tag("railway", "station"), tag("station", "subway")],
                "bbox": CORE,
                "recurse": "up",
            },
        ),
        (
            "substations in DC",
            'area["name"="District of Columbia"]["admin_level"="4"]->.a; nwr["power"="substation"](area.a);',
            {"type": "nwr", "tags": [tag("power", "substation")], "area": DC},
        ),
        (
            "hospitals in Arlington County",
            'area["name"="Arlington County"]["admin_level"="6"]->.a; nwr["amenity"="hospital"](area.a);',
            {"type": "nwr", "tags": [tag("amenity", "hospital")], "area": ARLINGTON},
        ),
    ]
    pl.DataFrame({"query": [q[0] for q in QUERIES], "Overpass QL": [q[1] for q in QUERIES]})
    return (QUERIES,)


@app.cell
def _(CANDIDATE_URL, OVERPASS_URL, httpx, time):
    client = httpx.Client(timeout=600, trust_env=False)

    def ask_overpass(ql: str) -> tuple[set[tuple[str, int]], float]:
        """Run QL on Overpass; return the (type, id) set and the seconds taken."""
        t0 = time.perf_counter()
        r = client.post(OVERPASS_URL, data={"data": f"[out:json][timeout:600];{ql}out ids;"})
        took = time.perf_counter() - t0
        r.raise_for_status()
        body = r.json()
        assert "remark" not in body, f"Overpass remark: {body['remark']}"
        return {(e["type"], e["id"]) for e in body["elements"]}, took

    def ask_candidate(spec: dict) -> tuple[set[tuple[str, int]], float]:
        """Run the JSON query on the candidate; return the (type, id) set and seconds."""
        t0 = time.perf_counter()
        r = client.post(CANDIDATE_URL, json=spec)
        took = time.perf_counter() - t0
        r.raise_for_status()
        return {(e["type"], e["id"]) for e in r.json()["elements"]}, took

    return ask_candidate, ask_overpass, client


@app.cell
def _(mo):
    mo.md("""
    ## Equivalence and latency

    Each query runs once to warm caches. Then it runs `RUNS` times on each side,
    alternating between them, and we report the median (p50) wall time over HTTP.
    A query is equivalent when both sides return exactly the same set of element
    types and IDs. Any difference is counted.
    """)
    return


@app.cell
def _(QUERIES, RESULTS, RUNS, ask_candidate, ask_overpass, pl, service, statistics):
    assert service.poll() is None, "candidate service died"
    _rows = []
    for _name, _ql, _spec in QUERIES:
        _o_ids, _ = ask_overpass(_ql)
        _c_ids, _ = ask_candidate(_spec)
        _o_times = []
        _c_times = []
        for _ in range(RUNS):
            _o_times.append(ask_overpass(_ql)[1])
            _c_times.append(ask_candidate(_spec)[1])
        _o_p50, _c_p50 = statistics.median(_o_times), statistics.median(_c_times)
        _rows.append(
            {
                "query": _name,
                "elements": len(_o_ids),
                "equivalent": _o_ids == _c_ids,
                "only in Overpass": len(_o_ids - _c_ids),
                "only in candidate": len(_c_ids - _o_ids),
                "Overpass p50 ms": round(_o_p50 * 1000, 1),
                "candidate p50 ms": round(_c_p50 * 1000, 1),
                "speed-up": round(_o_p50 / _c_p50, 1),
            }
        )
    query_results = pl.DataFrame(_rows)
    query_results.write_csv(RESULTS / "queries.csv")
    with pl.Config(tbl_rows=20, tbl_cols=10, tbl_width_chars=200):
        print(query_results)
    query_results
    return (query_results,)


@app.cell
def _(mo):
    mo.md("""
    ## Disk, RAM and import time

    Disk is Overpass's database directory against PostgreSQL's database size.
    "Steady RAM" is what `docker stats` reports after the queries (page cache
    excluded); for the candidate it adds the service process. "Import peak" is
    the cgroup's peak during import, page cache included. Both run on default
    settings, so neither side was tuned.
    """)
    return


@app.cell
def _(
    PSQL,
    RESULTS,
    candidate_import_s,
    osm2pgsql_peak_mb,
    overpass_import_peak_mb,
    overpass_import_s,
    pl,
    postgres_import_peak_mb,
    query_results,
    service,
    sh,
    used_mem_mb,
):
    assert query_results.height > 0
    _ovp_disk = int(sh("docker exec ovp du -sb /db/db").split()[0]) / 2**20
    _pg_disk = int(sh(f"{PSQL} -c \"select pg_database_size('osm')\"").strip()) / 2**20
    with open(f"/proc/{service.pid}/status") as _f:
        _service_rss = next(int(line.split()[1]) for line in _f if line.startswith("VmRSS")) / 1024
    resources = pl.DataFrame(
        [
            {
                "side": "Overpass",
                "disk MB": round(_ovp_disk),
                "steady RAM MB": round(used_mem_mb("ovp")),
                "import peak MB": round(overpass_import_peak_mb),
                "import s": round(overpass_import_s),
            },
            {
                "side": "candidate",
                "disk MB": round(_pg_disk),
                "steady RAM MB": round(used_mem_mb("pg") + _service_rss),
                "import peak MB": round(osm2pgsql_peak_mb + postgres_import_peak_mb),
                "import s": round(candidate_import_s),
            },
        ]
    )
    resources.write_csv(RESULTS / "resources.csv")
    print(resources)
    resources
    return (resources,)


@app.cell
def _(mo):
    mo.md("""
    ## Freshness: applying replication diffs

    Both sides get the same planet-wide hourly `osmChange` files, starting at the
    extract's snapshot time, one hour at a time. BBBike has no regional diff feed,
    and Geofabrik's was out of reach, so each file is the whole planet's hour.
    That's an upper bound on a regional feed's work. Both databases also take in
    the out-of-region objects it contains.

    - Overpass applies each file with `update_from_dir`, the same step its own
      update loop runs.
    - osm2pgsql needs each object to appear only once per file, so each file
      first goes through `osmium merge-changes -s`. That's what
      `osm2pgsql-replication` does internally, and it counts in the candidate's
      time.

    We apply 16 hours rather than one: the first hours after midnight UTC carry
    no edits in DC, so one hour alone wouldn't test anything local.
    """)
    return


@app.cell
def _(DATA, DIFF_HOURS, REPLICATION, datetime, resources, sh, snapshot):
    assert resources.height == 2

    def seq_path(seq: int) -> str:
        """Replication files live at AAA/BBB/CCC for sequence number AAABBBCCC."""
        return f"{REPLICATION}/{seq // 10**6:03d}/{seq // 1000 % 1000:03d}/{seq % 1000:03d}"

    def state(url: str) -> tuple[int, datetime]:
        """Sequence number and timestamp from a replication state.txt."""
        fields = dict(line.split("=", 1) for line in sh(f"curl -fsSL {url}").splitlines() if "=" in line)
        return int(fields["sequenceNumber"]), datetime.fromisoformat(fields["timestamp"].replace("\\", ""))

    # Hourly sequence numbers go up by one an hour; file N covers the hour ending at its timestamp.
    _latest_seq, _latest_at = state(f"{REPLICATION}/state.txt")
    _start_at = datetime.fromisoformat(snapshot)
    first_seq = _latest_seq - int((_latest_at - _start_at).total_seconds() // 3600) + 1
    _, _first_ends = state(f"{seq_path(first_seq)}.state.txt")
    assert (_first_ends - _start_at).total_seconds() == 3600, f"diff {first_seq} ends {_first_ends}, not 1 h in"
    diff_files = []
    for _seq in range(first_seq, first_seq + DIFF_HOURS):
        _path = DATA / f"hour-{_seq}.osc.gz"
        if not _path.exists():
            sh(f"curl -fsSL --retry 3 -o {_path} {seq_path(_seq)}.osc.gz")
        diff_files.append(_path)
    print(f"{len(diff_files)} hourly diffs from sequence {first_seq} ({snapshot} onwards)")
    return (diff_files,)


@app.cell
def _(DATA, OSM2PGSQL, OVERPASS_IMAGE, Path, RESULTS, diff_files, pl, sh, statistics, time):
    def apply_to_overpass(path: Path) -> float:
        """Apply one .osc.gz to Overpass the way its update loop does; return seconds."""
        sh("docker exec ovp sh -c 'rm -rf /db/diffin && mkdir /db/diffin'")
        sh(f"docker cp {path} ovp:/db/diffin/changes.osc.gz")
        sh("docker exec ovp sh -c 'gunzip /db/diffin/changes.osc.gz && chown -R overpass /db/diffin'")
        version = sh("docker exec ovp osmium fileinfo -e -g data.timestamp.last /db/diffin/changes.osc").strip()
        t0 = time.monotonic()
        sh(
            f"docker exec -u overpass ovp /app/bin/update_from_dir --osc-dir=/db/diffin --version={version} --flush-size=16"
        )
        return time.monotonic() - t0

    def apply_to_candidate(path: Path) -> float:
        """Simplify one .osc.gz and apply it with osm2pgsql --append; return seconds."""
        t0 = time.monotonic()
        sh(
            f"docker run --rm -v {DATA}:/d --entrypoint osmium {OVERPASS_IMAGE}"
            f" merge-changes -s -O -o /d/simple-{path.name} /d/{path.name}"
        )
        sh(
            f"{OSM2PGSQL} 'osm2pgsql --append --slim -d osm -U postgres -H 127.0.0.1 -P 15432"
            f" -O flex -S /style/flex.lua /data/simple-{path.name}'"
        )
        return time.monotonic() - t0

    _rows = []
    for _path in diff_files:
        _rows.append(
            {
                "diff": _path.name,
                "MB": round(_path.stat().st_size / 2**20, 1),
                "Overpass s": round(apply_to_overpass(_path), 1),
                "candidate s": round(apply_to_candidate(_path), 1),
            }
        )
    diff_times = pl.DataFrame(_rows)
    diff_times.write_csv(RESULTS / "diffs.csv")
    overpass_diff_s = statistics.median(diff_times["Overpass s"].to_list())
    candidate_diff_s = statistics.median(diff_times["candidate s"].to_list())
    with pl.Config(tbl_rows=30):
        print(diff_times)
    print(f"median per planet hour: Overpass {overpass_diff_s:.1f} s, candidate {candidate_diff_s:.1f} s")
    diff_times
    return candidate_diff_s, overpass_diff_s


@app.cell
def _(mo):
    mo.md("""
    Did the edits land the same way on both sides? We take every node the diffs
    created or changed inside the extract's box, keep its final version, and check
    that both sides now hold exactly those tags and coordinates. Then we rerun the
    ten queries once each.
    """)
    return


@app.cell
def _(DATA, ET, OVERPASS_IMAGE, OVERPASS_URL, PSQL, candidate_diff_s, client, diff_files, gzip, json, sh):
    assert candidate_diff_s > 0
    _names = " ".join(f"/d/{p.name}" for p in diff_files)
    sh(
        f"docker run --rm -v {DATA}:/d --entrypoint osmium {OVERPASS_IMAGE} merge-changes -s -O -o /d/all.osc.gz {_names}"
    )
    _box = (38.78, -77.23, 39.05, -76.84)
    expected: dict[int, tuple[float, float, dict[str, str]]] = {}
    for _action in ET.parse(gzip.open(DATA / "all.osc.gz")).getroot():
        for _el in _action:
            if _action.tag == "delete" or _el.tag != "node":
                continue
            _lat, _lon = float(_el.get("lat", "nan")), float(_el.get("lon", "nan"))
            if _box[0] <= _lat <= _box[2] and _box[1] <= _lon <= _box[3]:
                expected[int(_el.get("id", "0"))] = (_lat, _lon, {t.get("k", ""): t.get("v", "") for t in _el})
    _ids = ",".join(map(str, expected))
    _r = client.post(OVERPASS_URL, data={"data": f"[out:json];node(id:{_ids});out body;"})
    _r.raise_for_status()
    overpass_nodes = {e["id"]: (e["lat"], e["lon"], e.get("tags", {})) for e in _r.json()["elements"]}
    _rows = sh(
        f"{PSQL} -F '\t' -c \"select id, lat, lon, coalesce(tags, '{{}}') from planet_osm_nodes where id in ({_ids})\""
    )
    candidate_nodes = {}
    for _line in _rows.splitlines():
        _id, _lat, _lon, _tags = _line.split("\t")
        candidate_nodes[int(_id)] = (int(_lat) / 1e7, int(_lon) / 1e7, json.loads(_tags))
    return candidate_nodes, expected, overpass_nodes


@app.cell
def _(RESULTS, candidate_nodes, expected, json, overpass_nodes):
    def matches(want: tuple[float, float, dict], got: tuple[float, float, dict] | None) -> bool:
        """Same tags, and coordinates equal at OSM's 1e-7 degree precision."""
        return got is not None and abs(want[0] - got[0]) < 1e-6 and abs(want[1] - got[1]) < 1e-6 and want[2] == got[2]

    freshness = {
        "changed nodes in the box": len(expected),
        "tagged": sum(1 for v in expected.values() if v[2]),
        "current in Overpass": sum(matches(v, overpass_nodes.get(k)) for k, v in expected.items()),
        "current in candidate": sum(matches(v, candidate_nodes.get(k)) for k, v in expected.items()),
    }
    (RESULTS / "freshness.json").write_text(json.dumps(freshness, indent=2))
    print(freshness)
    freshness
    return (freshness,)


@app.cell
def _(QUERIES, RESULTS, ask_candidate, ask_overpass, freshness, pl):
    assert freshness["changed nodes in the box"] > 0, "no local edits in these hours; raise DIFF_HOURS"
    _rows = []
    for _name, _ql, _spec in QUERIES:
        _o, _ = ask_overpass(_ql)
        _c, _ = ask_candidate(_spec)
        _rows.append(
            {
                "query": _name,
                "elements": len(_o),
                "equivalent after diff": _o == _c,
                "only in Overpass": len(_o - _c),
                "only in candidate": len(_c - _o),
            }
        )
    after_diff = pl.DataFrame(_rows)
    after_diff.write_csv(RESULTS / "after_diff.csv")
    with pl.Config(tbl_rows=20, tbl_width_chars=200):
        print(after_diff)
    after_diff
    return (after_diff,)


@app.cell
def _(mo):
    mo.md("""
    ## What the candidate can't do

    The service covers the subset above and nothing else. These are the Overpass QL
    features it lacks. Each says whether PostGIS could add it cheaply or whether
    it needs a different design.

    | # | QL feature | Candidate | Cost to add |
    |---|---|---|---|
    | 1 | QL text itself (a parser) | JSON equivalent only | a parser for this subset; not sized |
    | 2 | Named sets, unions, differences beyond `(._;>;)` / `(._;<;)` | no | needs a QL interpreter over SQL steps |
    | 3 | `foreach`, `for`, `if`, `complete`, `retro` | no | imperative; needs the interpreter |
    | 4 | `>>` / `<<` (recursive closure, sub-relations) | no | recursive CTE over `members` |
    | 5 | `rel(r)`, `way(r)`, `node(w)` with roles, `rel(bn)` etc. | no | one join each on the middle tables |
    | 6 | `is_in`, `pivot`, `map_to_area`, `area(id)` lookups | no | `ST_Contains` on `areas_geo`; area IDs need the 2.4e9/3.6e9 offsets |
    | 7 | Attic: `[date:]`, `[diff:]`, `[adiff:]`, `changed`, `newer`, `user`, `uid` | no | osm2pgsql keeps no history or metadata; a different store |
    | 8 | Output modes: `out body/skel/meta/tags`, `geom`, `center`, `bb`, `qt` sort | IDs only | `body`, `geom` and `center` come cheap from the tables; `meta` needs metadata on import |
    | 9 | `out count`, `[out:csv]` | no | trivial |
    | 10 | Evaluators and `make`/`convert` (`t[]`, `length()`, `per_member`, `per_vertex`) | no | per-element SQL expressions; a lot of surface |
    | 11 | `poly:` filter, `around` on sets (`around.a:`), `(if: ...)` filters | no | `around`/`poly` are one PostGIS call each; `if` needs the evaluator |
    | 12 | Untagged nodes in spatial filters (`node(bbox)` with no tag) | no | `process_untagged_node` in `flex.lua`, at a disk cost |
    | 13 | Global `[maxsize:]`, `[timeout:]`, and the dispatcher's per-client quotas | no | `statement_timeout`, plus a gateway |

    **13 features unsupported.** Items 5, 6, 9, 11 and 12 are small additions on
    the same tables. Items 1–4 and 10 add up to an Overpass QL interpreter. Item 7
    needs a different kind of database.
    """)
    return


@app.cell
def _(RESULTS, after_diff, candidate_diff_s, freshness, overpass_diff_s, query_results, service, sh, snapshot):
    _summary = (
        f"Extract snapshot: {snapshot}\n"
        f"Equivalent queries: {int(query_results['equivalent'].sum())}/{query_results.height} before diffs, "
        f"{int(after_diff['equivalent after diff'].sum())}/{after_diff.height} after\n"
        f"Median speed-up across queries: {query_results['speed-up'].median():.1f}x\n"
        f"Diff apply, median per planet hour: Overpass {overpass_diff_s:.1f} s, candidate {candidate_diff_s:.1f} s\n"
        f"Changed nodes in the box current on both sides: Overpass {freshness['current in Overpass']}, "
        f"candidate {freshness['current in candidate']} of {freshness['changed nodes in the box']}\n"
    )
    (RESULTS / "summary.txt").write_text(_summary)
    print(_summary)
    service.terminate()
    sh("docker stop ovp pg", may_fail=True)
    return


if __name__ == "__main__":
    app.run()
