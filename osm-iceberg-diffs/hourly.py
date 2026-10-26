import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import os
    import shlex
    import statistics
    import subprocess
    import sys
    import time
    from datetime import datetime
    from pathlib import Path

    import marimo as mo
    import osmium
    import polars as pl
    import shapely

    import osm_iceberg as oi

    return Path, datetime, mo, oi, os, osmium, pl, shapely, shlex, statistics, subprocess, sys, time


@app.cell
def _(mo):
    mo.md("""
    # How fast can OSM replication diffs be applied to Iceberg, compared to PostGIS?

    [#124](https://github.com/fulton-ring/agent-content-demos/pull/124) kept a
    PostGIS copy of OpenStreetMap (OSM) current with osm2pgsql, which applied an
    hour of planet diffs in a median 8.4 s. It skipped DuckDB and GeoParquet
    because DuckDB's OSM reader can't apply diffs. An **Iceberg** table can:
    it supports row-level deletes and appends, and DuckDB can query it.

    This notebook loads the **same extract** into both, applies the **same hourly
    diffs** to both, and checks that both still give the same answers:

    - **PostGIS side:** #124's osm2pgsql import and diff apply, with its
      `flex.lua` and `service.py` copied unchanged.
    - **Iceberg side:** `osm_iceberg.py`. PyIceberg writes three tables (`nodes`,
      `ways`, `relations`) to a SQLite catalog and a local warehouse, and DuckDB
      reads them through `iceberg_scan`. Ways carry a line and relations an
      area, rebuilt whenever a member changes.

    The long minutely replay, with and without table maintenance, is in
    `replay.py`.
    """)
    return


@app.cell
def _(Path, os):
    EXTRACT_URL = os.environ.get(
        "EXTRACT_URL", "https://download.bbbike.org/osm/bbbike/WashingtonDC/WashingtonDC.osm.pbf"
    )
    REPLICATION = "https://planet.openstreetmap.org/replication/hour"
    DIFF_HOURS = int(os.environ.get("DIFF_HOURS", "16"))
    RUNS = int(os.environ.get("RUNS", "5"))
    HERE = Path(__file__).resolve().parent
    assert " " not in str(HERE), "run this from a path without spaces (it is mounted into Docker)"
    DATA = HERE / "data"
    RESULTS = HERE / "results"
    DATA.mkdir(exist_ok=True)
    RESULTS.mkdir(exist_ok=True)
    WAREHOUSE = DATA / "hourly-warehouse"
    # The same images as #124, pinned by digest: PostGIS 17-3.5 and osm2pgsql 2.3.1.
    POSTGIS_IMAGE = "postgis/postgis@sha256:01a6a70e41e6c4467c8f55f6063555ed72db2d6662cd0d571040d42eadaeb6f6"
    OSM2PGSQL_IMAGE = "iboates/osm2pgsql@sha256:6548a1e2492e08fa0d5ce987d382ad57c4b21c8a94ff00017c6109770a061b79"
    DB_URL = "postgresql://postgres:osm@127.0.0.1:15432/osm"
    OSM2PGSQL = (
        f"docker run --rm --network host --entrypoint osm2pgsql -e PGPASSWORD=osm"
        f" -v {DATA}:/data:ro -v {HERE}:/style:ro {OSM2PGSQL_IMAGE}"
        " --slim -d osm -U postgres -H 127.0.0.1 -P 15432 -O flex -S /style/flex.lua"
    )
    return DATA, DB_URL, DIFF_HOURS, EXTRACT_URL, OSM2PGSQL, POSTGIS_IMAGE, REPLICATION, RESULTS, RUNS, WAREHOUSE


@app.cell
def _(shlex, subprocess, time):
    def sh(cmd: str, may_fail: bool = False) -> str:
        """Run a command line (split, not passed to a shell); return stdout, fail loudly."""
        done = subprocess.run(shlex.split(cmd), capture_output=True, text=True)
        if done.returncode != 0 and not may_fail:
            raise RuntimeError(f"`{cmd[:100]}` failed: {done.stderr[-2000:]}")
        return done.stdout

    def timed(step) -> float:
        """Seconds one call of `step()` takes."""
        t0 = time.monotonic()
        step()
        return time.monotonic() - t0

    return sh, timed


@app.cell
def _(mo):
    mo.md("""
    ## The data

    The same public extract as #124: BBBike's Washington DC extract (about 65 MB,
    6.3 M nodes, 0.96 M ways). Then the planet's hourly `osmChange` files from
    the extract's snapshot time on. BBBike has no regional feed, so each file is
    a whole planet hour, and both sides take in the whole hour, as in #124.
    OSM data © OpenStreetMap contributors, ODbL.
    """)
    return


@app.cell
def _(DATA, DIFF_HOURS, EXTRACT_URL, REPLICATION, datetime, osmium, sh):
    pbf = DATA / "extract.osm.pbf"
    if not pbf.exists():
        sh(f"curl -fsSL --retry 3 -o {pbf} {EXTRACT_URL}")
    snapshot = osmium.io.Reader(str(pbf), osmium.osm.osm_entity_bits.NOTHING).header().get(
        "osmosis_replication_timestamp"
    )
    assert snapshot, "the extract has no replication timestamp"

    def seq_path(seq: int) -> str:
        """Replication files live at AAA/BBB/CCC for sequence number AAABBBCCC."""
        return f"{REPLICATION}/{seq // 10**6:03d}/{seq // 1000 % 1000:03d}/{seq % 1000:03d}"

    def state(url: str) -> tuple[int, datetime]:
        fields = dict(line.split("=", 1) for line in sh(f"curl -fsSL {url}").splitlines() if "=" in line)
        return int(fields["sequenceNumber"]), datetime.fromisoformat(fields["timestamp"].replace("\\", ""))

    # Hourly sequence numbers go up by one an hour; file N covers the hour ending at its timestamp.
    _latest_seq, _latest_at = state(f"{REPLICATION}/state.txt")
    _start = datetime.fromisoformat(snapshot)
    _first = _latest_seq - int((_latest_at - _start).total_seconds() // 3600) + 1
    _, _first_ends = state(f"{seq_path(_first)}.state.txt")
    assert (_first_ends - _start).total_seconds() == 3600, f"diff {_first} ends {_first_ends}, not 1 h in"
    diff_files = []
    for _seq in range(_first, _first + DIFF_HOURS):
        _path = DATA / f"hour-{_seq}.osc.gz"
        if not _path.exists():
            sh(f"curl -fsSL --retry 3 -o {_path} {seq_path(_seq)}.osc.gz")
        diff_files.append(_path)
    print(f"extract snapshot {snapshot}; {len(diff_files)} hourly diffs from sequence {_first}")
    return diff_files, pbf, snapshot


@app.cell
def _(mo):
    mo.md("""
    ## Import, Iceberg side

    DuckDB's `ST_ReadOSM` reads the extract (it is fast, but reads only `.pbf`,
    so diffs go through pyosmium instead). PyIceberg appends nodes, then DuckDB
    builds each way's line from its nodes, then each named multipolygon or
    boundary relation's area from its member ways (`ST_BuildArea`), and
    PyIceberg appends those. One table property matters for diffs: PyIceberg
    can only delete rows by rewriting the whole data file that holds them
    (copy-on-write), so we cap data files at 16 MB to keep each rewrite small.
    """)
    return


@app.cell
def _(WAREHOUSE, oi, pbf, sh, timed):
    TABLE_PROPERTIES = {"write.target-file-size-bytes": str(16 * 2**20)}
    sh(f"rm -rf {WAREHOUSE}")
    catalog = oi.open_catalog(WAREHOUSE)
    iceberg_import_s = timed(lambda: oi.create_tables(catalog, pbf, TABLE_PROPERTIES))
    iceberg_import_mb = int(sh(f"du -sb {WAREHOUSE}").split()[0]) / 2**20
    print(f"Iceberg import: {iceberg_import_s:.0f} s, {iceberg_import_mb:.0f} MB on disk")
    return catalog, iceberg_import_mb, iceberg_import_s


@app.cell
def _(mo):
    mo.md("""
    ## Import, PostGIS side

    As in #124: osm2pgsql in `--slim` mode with #124's `flex.lua`, default
    settings for both PostgreSQL and osm2pgsql.
    """)
    return


@app.cell
def _(DB_URL, OSM2PGSQL, POSTGIS_IMAGE, iceberg_import_s, os, sh, sys, time, timed):
    assert iceberg_import_s > 0
    sh("docker rm -fv pg", may_fail=True)
    sh(f"docker run -d --name pg -p 15432:5432 -e POSTGRES_PASSWORD=osm -e POSTGRES_DB=osm {POSTGIS_IMAGE}")
    # The image starts PostgreSQL, runs its init scripts, then restarts it once: wait for both.
    for _attempt in range(2):
        for _ in range(60):
            if "1" in sh("docker exec pg psql -U postgres -d osm -h 127.0.0.1 -Atc 'select 1'", may_fail=True):
                break
            time.sleep(2)
        time.sleep(3)
    postgis_import_s = timed(lambda: sh(f"{OSM2PGSQL} /data/extract.osm.pbf"))
    os.environ["CANDIDATE_DB_URL"] = DB_URL
    sys.path.insert(0, os.getcwd())
    import service  # #124's query service, called in-process

    service.pool.open(wait=True)
    with service.pool.connection() as _conn:
        postgis_import_mb = _conn.execute("select pg_database_size('osm')").fetchone()[0] / 2**20
    print(f"PostGIS import: {postgis_import_s:.0f} s, {postgis_import_mb:.0f} MB on disk")
    return postgis_import_mb, postgis_import_s, service


@app.cell
def _(mo):
    mo.md("""
    ## Same answers before the diffs?

    #124's ten queries, as the JSON its `service.py` takes. `service.py` turns
    each into PostGIS SQL; `oi.iceberg_ids` turns the same JSON into DuckDB SQL
    over the Iceberg tables, following the same rules (which elements count as
    inside an area, what a relation's location is). Both return element types
    and IDs. Each query runs once to warm up, then `RUNS` times on each side;
    we report the median. Both are called in-process, so neither pays for HTTP.
    """)
    return


@app.cell
def _(oi, service, statistics, time):
    def ask_postgis(spec: dict) -> set[tuple[str, int]]:
        return {(e.type, e.id) for e in service.query(service.Query(**spec)).elements}

    def compare(catalog, runs: int) -> list[dict]:
        """Run the ten queries on both sides; return one row per query."""
        con = oi.connect()
        oi.refresh_views(con, catalog)
        con.execute(oi.AREAS)
        rows = []
        for name, spec in oi.QUERIES:
            ice, pg = oi.iceberg_ids(con, spec), ask_postgis(spec)
            ice_ms, pg_ms = [], []
            for _ in range(runs):
                t0 = time.perf_counter()
                oi.iceberg_ids(con, spec)
                ice_ms.append((time.perf_counter() - t0) * 1000)
                t0 = time.perf_counter()
                ask_postgis(spec)
                pg_ms.append((time.perf_counter() - t0) * 1000)
            rows.append(
                {
                    "query": name,
                    "elements": len(pg),
                    "same IDs": ice == pg,
                    "only in Iceberg": len(ice - pg),
                    "only in PostGIS": len(pg - ice),
                    "Iceberg+DuckDB p50 ms": round(statistics.median(ice_ms)) if runs else None,
                    "PostGIS p50 ms": round(statistics.median(pg_ms)) if runs else None,
                }
            )
        return rows

    return (compare,)


@app.cell
def _(RESULTS, RUNS, catalog, compare, pl, postgis_import_s):
    assert postgis_import_s > 0
    before = pl.DataFrame(compare(catalog, RUNS))
    before.write_csv(RESULTS / "queries_before.csv")
    with pl.Config(tbl_rows=20, tbl_cols=10, tbl_width_chars=200):
        print(before)
    before
    return (before,)


@app.cell
def _(mo):
    mo.md("""
    ## Applying the hourly diffs

    One file at a time, alternating sides.

    - **PostGIS:** pyosmium first keeps only each element's last version (what
      `osmium merge-changes -s` did in #124, which osm2pgsql needs), then
      `osm2pgsql --append`. That's #124's step; its time includes the Docker
      start of osm2pgsql, as #124's did.
    - **Iceberg:** `oi.apply_diff`. It reads the file with pyosmium (last version
      only), then commits each table in one transaction (delete the old rows,
      append the new ones): nodes first; then ways, the changed ones plus
      unchanged ways that use a changed node, with their lines rebuilt; then
      relations, the changed ones plus areas whose member ways were rebuilt.
      That is three commits per diff, since Iceberg commits one table at a time.
    """)
    return


@app.cell
def _(DATA, OSM2PGSQL, Path, before, catalog, diff_files, oi, osmium, pl, sh, statistics, timed):
    assert before.height == 10

    class _Copy(osmium.SimpleHandler):
        def __init__(self, writer: osmium.SimpleWriter) -> None:
            super().__init__()
            self.writer = writer

        def node(self, n: osmium.osm.Node) -> None:
            self.writer.add_node(n)

        def way(self, w: osmium.osm.Way) -> None:
            self.writer.add_way(w)

        def relation(self, r: osmium.osm.Relation) -> None:
            self.writer.add_relation(r)

    def apply_to_postgis(path: Path) -> None:
        """Keep each element's last version, then osm2pgsql --append."""
        simple = DATA / f"simple-{path.name}"
        merged = osmium.MergeInputReader()
        merged.add_file(str(path))
        writer = osmium.SimpleWriter(str(simple), overwrite=True)
        merged.apply(_Copy(writer), simplify=True)
        writer.close()
        sh(f"{OSM2PGSQL} --append /data/{simple.name}")

    _rows = []
    for _path in diff_files:
        _stats = {}
        _iceberg_s = timed(lambda: _stats.update(oi.apply_diff(catalog, _path)))
        _rows.append(
            {
                "diff": _path.name,
                "MB": round(_path.stat().st_size / 2**20, 1),
                "Iceberg s": round(_iceberg_s, 1),
                "PostGIS s": round(timed(lambda: apply_to_postgis(_path)), 1),
                **{k: round(v, 2) if isinstance(v, float) else v for k, v in _stats.items()},
            }
        )
    diff_times = pl.DataFrame(_rows)
    diff_times.write_csv(DATA.parent / "results" / "diffs.csv")
    iceberg_diff_s = statistics.median(diff_times["Iceberg s"].to_list())
    postgis_diff_s = statistics.median(diff_times["PostGIS s"].to_list())
    with pl.Config(tbl_rows=30, tbl_cols=20, tbl_width_chars=250):
        print(diff_times)
    print(f"median per planet hour: Iceberg {iceberg_diff_s:.1f} s, PostGIS {postgis_diff_s:.1f} s")
    diff_times
    return diff_times, iceberg_diff_s, postgis_diff_s


@app.cell
def _(mo):
    mo.md("""
    ## Did the edits land, and is the geometry right?

    First the check from #124: every node the diffs created or changed inside
    the extract's box, at its last version, must hold exactly those tags and
    coordinates on both sides.

    Then the derived geometry, which is the hard part. For every way in the box
    that the diffs changed, or that uses a node they changed, the Iceberg line
    must equal PostGIS's `ways_geo` line point for point. The same goes for every
    named area relation either side holds, against osm2pgsql's `areas_geo`, by
    comparing areas (the two build multipolygons with different code, so ring
    order and start points can differ).
    """)
    return


@app.cell
def _(catalog, diff_files, diff_times, oi, service, shapely):
    assert diff_times.height == len(diff_files)
    _s, _w, _n, _e = oi.WHOLE
    expected: dict[int, tuple[float, float, dict] | None] = {}
    for _path in diff_files:
        _raw, _deleted = oi.read_osm(_path)
        for _node in _raw["nodes"].to_pylist():
            if _s <= _node["lat"] <= _n and _w <= _node["lon"] <= _e:
                expected[_node["id"]] = (_node["lat"], _node["lon"], dict(_node["tags"] or []))
            else:
                expected.pop(_node["id"], None)  # moved out of the box
        for _id in _deleted["nodes"]:
            expected.pop(_id, None)
    _ids = sorted(expected)
    _con = oi.connect()
    oi.refresh_views(_con, catalog)
    _ice = {
        r[0]: (r[1], r[2], dict(r[3] or {}))
        for r in _con.execute("select id, lat, lon, tags from nodes where list_contains($1, id)", [_ids]).fetchall()
    }
    with service.pool.connection() as _conn:
        _pg = {
            r[0]: (r[1] / 1e7, r[2] / 1e7, r[3] or {})
            for r in _conn.execute("select id, lat, lon, tags from planet_osm_nodes where id = any(%s)", (_ids,))
        }

    def _same(want: tuple, got: tuple | None) -> bool:
        return got is not None and abs(want[0] - got[0]) < 1e-6 and abs(want[1] - got[1]) < 1e-6 and want[2] == got[2]

    # Ways in the box whose line could have changed: changed ways, and ways using changed nodes.
    _changed_ways = set()
    for _path in diff_files:
        _changed_ways |= set(oi.read_osm(_path)[0]["ways"]["id"].to_pylist())
    _box = f"xmax >= {_w} and xmin <= {_e} and ymax >= {_s} and ymin <= {_n}"
    _way_lines = dict(
        _con.execute(
            f"select id, geom from ways where {_box} and (list_contains($1, id) or list_has_any(nodes, $2))",
            [sorted(_changed_ways), _ids],
        ).fetchall()
    )
    with service.pool.connection() as _conn:
        _pg_lines = dict(
            _conn.execute(
                "select way_id, ST_AsBinary(geom) from ways_geo where way_id = any(%s)", (list(_way_lines),)
            ).fetchall()
        )
        _pg_areas = dict(
            _conn.execute("select -area_id, ST_AsBinary(geom) from areas_geo where area_id < 0").fetchall()
        )
    _ice_areas = dict(_con.execute("select id, geom from relations where geom is not null").fetchall())

    def _same_line(a: bytes, b: bytes | None) -> bool:
        return b is not None and shapely.equals_exact(shapely.from_wkb(a), shapely.from_wkb(b), 1e-7)

    def _same_area(a: bytes, b: bytes | None) -> bool:
        if b is None:
            return False
        ga, gb = shapely.from_wkb(a), shapely.from_wkb(b)
        return shapely.area(shapely.symmetric_difference(ga, gb)) <= 1e-9 * max(shapely.area(gb), 1e-12)

    freshness = {
        "changed nodes in the box": len(expected),
        "current in Iceberg": int(sum(_same(v, _ice.get(k)) for k, v in expected.items())),
        "current in PostGIS": int(sum(_same(v, _pg.get(k)) for k, v in expected.items())),
        "ways in the box to recheck": len(_way_lines),
        "same line on both sides": int(sum(_same_line(g, _pg_lines.get(i)) for i, g in _way_lines.items())),
        "area relations in PostGIS": len(_pg_areas),
        "area relations in Iceberg": len(_ice_areas),
        "same area on both sides": int(sum(_same_area(g, _pg_areas.get(i)) for i, g in _ice_areas.items())),
    }
    freshness
    return (freshness,)


@app.cell
def _(RESULTS, catalog, compare, freshness, pl):
    import json

    (RESULTS / "freshness.json").write_text(json.dumps(freshness, indent=2))
    print(freshness)
    after = pl.DataFrame(compare(catalog, 0)).drop("Iceberg+DuckDB p50 ms", "PostGIS p50 ms")
    after.write_csv(RESULTS / "queries_after.csv")
    with pl.Config(tbl_rows=20, tbl_cols=10, tbl_width_chars=200):
        print(after)
    after
    return (after,)


@app.cell
def _(
    RESULTS,
    after,
    before,
    diff_times,
    freshness,
    iceberg_diff_s,
    iceberg_import_mb,
    iceberg_import_s,
    postgis_diff_s,
    postgis_import_mb,
    postgis_import_s,
    service,
    sh,
    snapshot,
):
    _summary = (
        f"Extract snapshot: {snapshot}\n"
        f"Import: Iceberg {iceberg_import_s:.0f} s / {iceberg_import_mb:.0f} MB, "
        f"PostGIS {postgis_import_s:.0f} s / {postgis_import_mb:.0f} MB\n"
        f"Diff apply per planet hour, median (range) of {diff_times.height}: "
        f"Iceberg {iceberg_diff_s:.1f} s ({diff_times['Iceberg s'].min()}-{diff_times['Iceberg s'].max()}), "
        f"PostGIS {postgis_diff_s:.1f} s ({diff_times['PostGIS s'].min()}-{diff_times['PostGIS s'].max()})\n"
        f"Same IDs: {int(before['same IDs'].sum())}/{before.height} queries before diffs, "
        f"{int(after['same IDs'].sum())}/{after.height} after\n"
        f"Changed nodes in the box current: Iceberg {freshness['current in Iceberg']}, "
        f"PostGIS {freshness['current in PostGIS']} of {freshness['changed nodes in the box']}\n"
        f"Rebuilt way lines equal to PostGIS: {freshness['same line on both sides']} of "
        f"{freshness['ways in the box to recheck']}; areas equal: {freshness['same area on both sides']} of "
        f"{freshness['area relations in Iceberg']} (PostGIS has {freshness['area relations in PostGIS']})\n"
    )
    (RESULTS / "hourly_summary.txt").write_text(_summary)
    print(_summary)
    service.pool.close()
    sh("docker rm -fv pg", may_fail=True)
    return


if __name__ == "__main__":
    app.run()
