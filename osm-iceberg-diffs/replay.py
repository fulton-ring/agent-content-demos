import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import os
    import shutil
    import statistics
    import time
    from datetime import UTC, datetime, timedelta
    from pathlib import Path

    import httpx
    import marimo as mo
    import osmium
    import polars as pl
    from pyspark.sql import SparkSession

    import osm_iceberg as oi

    return Path, SparkSession, UTC, datetime, httpx, mo, oi, os, osmium, pl, shutil, statistics, time, timedelta


@app.cell
def _(mo):
    mo.md("""
    # Does an Iceberg copy of OSM hold up over a long minutely replay?

    Every Iceberg commit adds a metadata file, a manifest list and manifests, and
    every diff here makes three commits (nodes, ways, relations). With minutely
    diffs that's 180 commits an hour. Left alone, the metadata, the snapshots
    and the small data files pile up, and queries have to read through them.

    So we replay the same minutely planet diffs from the extract's snapshot on
    into three fresh Iceberg copies of the DC extract:

    - **left alone:** nothing but the diffs, for the first 300 (5 hours; it slows
      down too much to run further in reasonable time);
    - **PyIceberg only:** all 1,000 diffs (about 17 hours), with the settings
      PyIceberg itself honours (merge manifests on commit, delete old
      `metadata.json` files) and its `expire_snapshots` every 60 diffs;
    - **PyIceberg + Spark:** the same settings, and every 60 diffs (an hour of
      minutely diffs) Spark compacts small data files, expires old snapshots and
      rewrites manifests.

    Every 50 diffs we record metadata files and bytes, data files and their
    average size, snapshots, and how long the ten queries from `hourly.py` take.
    """)
    return


@app.cell
def _(Path, oi, os):
    MINUTES = int(os.environ.get("MINUTES", "1000"))
    LEFT_ALONE_MINUTES = int(os.environ.get("LEFT_ALONE_MINUTES", "300"))
    MAINTAIN_EVERY = int(os.environ.get("MAINTAIN_EVERY", "60"))
    CHECK_EVERY = int(os.environ.get("CHECK_EVERY", "50"))
    REPLICATION = "https://planet.openstreetmap.org/replication/minute"
    HERE = Path(__file__).resolve().parent
    DATA = HERE / "data"
    RESULTS = HERE / "results"
    MINUTE_DIR = DATA / "minute"
    MINUTE_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS.mkdir(exist_ok=True)
    PBF = DATA / "extract.osm.pbf"
    assert PBF.exists(), "run hourly.py first; it downloads the extract"
    # PyIceberg can't compact or rewrite manifests (see the README), but it honours
    # these: merge manifests as it appends, and keep only the last 5 metadata.json files.
    MAINTAINED_PROPERTIES = oi.TABLE_PROPERTIES | {
        "commit.manifest-merge.enabled": "true",
        "write.metadata.delete-after-commit.enabled": "true",
        "write.metadata.previous-versions-max": "5",
    }
    return (
        CHECK_EVERY,
        DATA,
        LEFT_ALONE_MINUTES,
        MAINTAINED_PROPERTIES,
        MAINTAIN_EVERY,
        MINUTES,
        MINUTE_DIR,
        PBF,
        REPLICATION,
        RESULTS,
    )


@app.cell
def _(mo):
    mo.md("""
    ## The diffs

    Minutely sequence numbers don't map exactly onto clock minutes, so we find
    the first file whose state ends just after the snapshot by reading
    `state.txt` files, then download `MINUTES` files from there.
    """)
    return


@app.cell
def _(MINUTES, MINUTE_DIR, PBF, REPLICATION, datetime, httpx, osmium, time, timedelta):
    client = httpx.Client(timeout=60, follow_redirects=True)

    def seq_path(seq: int) -> str:
        return f"{REPLICATION}/{seq // 10**6:03d}/{seq // 1000 % 1000:03d}/{seq % 1000:03d}"

    def fetch(url: str) -> bytes:
        """GET with up to 5 tries and backoff: planet.openstreetmap.org sometimes drops a connection."""
        for attempt in range(5):
            try:
                r = client.get(url)
                r.raise_for_status()
                return r.content
            except httpx.HTTPError:
                if attempt == 4:
                    raise
                time.sleep(2**attempt)
        raise AssertionError("unreachable")

    def ends_at(url: str) -> tuple[int, datetime]:
        fields = dict(line.split("=", 1) for line in fetch(url).decode().splitlines() if "=" in line)
        return int(fields["sequenceNumber"]), datetime.fromisoformat(fields["timestamp"].replace("\\", ""))

    snapshot = datetime.fromisoformat(
        osmium.io.Reader(str(PBF), osmium.osm.osm_entity_bits.NOTHING).header().get("osmosis_replication_timestamp")
    )
    _latest, _latest_at = ends_at(f"{REPLICATION}/state.txt")
    first_seq = _latest - int((_latest_at - snapshot).total_seconds() // 60) + 1
    # Step towards the file covering the first minute after the snapshot (bounded).
    for _ in range(200):
        _, _end = ends_at(f"{seq_path(first_seq)}.state.txt")
        _, _prev_end = ends_at(f"{seq_path(first_seq - 1)}.state.txt")
        if _prev_end <= snapshot < _end:
            break
        first_seq += -1 if _prev_end > snapshot else 1
    else:
        raise RuntimeError("couldn't find the first minutely diff after the snapshot")
    assert _end - snapshot <= timedelta(minutes=2), f"first diff {first_seq} ends {_end}"
    minute_files = []
    for _seq in range(first_seq, first_seq + MINUTES):
        _path = MINUTE_DIR / f"{_seq}.osc.gz"
        if not _path.exists():
            _path.write_bytes(fetch(f"{seq_path(_seq)}.osc.gz"))
        minute_files.append(_path)
    _, _last_end = ends_at(f"{seq_path(first_seq + MINUTES - 1)}.state.txt")
    print(f"{len(minute_files)} minutely diffs from {first_seq}, covering {snapshot} to {_last_end}")
    return (minute_files,)


@app.cell
def _(mo):
    mo.md("""
    ## Maintenance, with Spark

    PyIceberg 0.12 can only expire snapshots, and it then leaves their files on
    disk. It can't compact data files or rewrite manifests. DuckDB's iceberg
    extension can't do any of the three. So full maintenance runs in Spark 4.1
    in local mode, with Iceberg's Spark runtime and a JDBC catalog pointed at
    PyIceberg's SQLite catalog file: both see the same tables. Per table:

    - `rewrite_data_files`: bin-packs small data files into 16 MB ones;
    - `expire_snapshots`: keeps only the current snapshot and deletes the files
      only older ones used;
    - `rewrite_manifests`: merges the manifests into a few.
    """)
    return


@app.cell
def _(DATA, SparkSession, UTC, datetime, oi, time):
    def spark_for(warehouse) -> SparkSession:
        """A local Spark session on the same catalog that PyIceberg writes."""
        return (
            SparkSession.builder.master("local[4]")
            .appName(warehouse.name)
            .config(
                "spark.jars.packages",
                "org.apache.iceberg:iceberg-spark-runtime-4.1_2.13:1.12.0,org.xerial:sqlite-jdbc:3.50.3.0",
            )
            .config("spark.jars.ivy", str(DATA / "ivy"))
            .config("spark.sql.extensions", "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions")
            .config("spark.sql.catalog.osm", "org.apache.iceberg.spark.SparkCatalog")
            .config("spark.sql.catalog.osm.type", "jdbc")
            .config("spark.sql.catalog.osm.uri", f"jdbc:sqlite:{warehouse}/catalog.db")
            .config("spark.sql.catalog.osm.warehouse", f"file://{warehouse}")
            # PyIceberg commits between maintenance runs, so never serve a cached table.
            .config("spark.sql.catalog.osm.cache-enabled", "false")
            .config("spark.ui.enabled", "false")
            .getOrCreate()
        )

    def maintain_with_spark(spark: SparkSession) -> dict[str, float]:
        """Compact, expire and rewrite manifests on each table; return seconds per step."""
        took = {"compact s": 0.0, "expire s": 0.0, "manifests s": 0.0}
        for name in oi.SCHEMAS:
            for step, sql in [
                ("compact s", f"CALL osm.system.rewrite_data_files(table => 'osm.osm.{name}')"),
                (
                    "expire s",
                    f"CALL osm.system.expire_snapshots(table => 'osm.osm.{name}',"
                    " older_than => current_timestamp(), retain_last => 1)",
                ),
                ("manifests s", f"CALL osm.system.rewrite_manifests(table => 'osm.osm.{name}')"),
            ]:
                t0 = time.monotonic()
                spark.sql(sql).collect()
                took[step] += time.monotonic() - t0
        return took

    def expire_with_pyiceberg(catalog) -> dict[str, float]:
        """PyIceberg's only maintenance: drop all but the current snapshot from each table's metadata."""
        t0 = time.monotonic()
        for name in oi.SCHEMAS:
            catalog.load_table(f"osm.{name}").maintenance.expire_snapshots().older_than(datetime.now(UTC)).commit()
        return {"expire s": time.monotonic() - t0}

    return expire_with_pyiceberg, maintain_with_spark, spark_for


@app.cell
def _(oi, statistics, time):
    def table_stats(catalog, warehouse) -> dict[str, float]:
        """Metadata and data-file counts on disk and in the current snapshots, summed over the tables."""
        stats = {"metadata files": 0, "metadata MB": 0.0, "data files": 0, "data MB": 0.0}
        stats |= {"live data files": 0, "snapshots": 0}
        for name in oi.SCHEMAS:
            for kind in ("metadata", "data"):
                # Spark writes through Hadoop's local filesystem, which adds a .crc beside each file; skip those.
                files = [p for p in (warehouse / "osm" / name / kind).rglob("*") if p.is_file() and p.suffix != ".crc"]
                stats[f"{kind} files"] += len(files)
                stats[f"{kind} MB"] += sum(p.stat().st_size for p in files) / 2**20
            table = catalog.load_table(f"osm.{name}")
            stats["live data files"] += table.inspect.files().num_rows
            stats["snapshots"] += len(table.metadata.snapshots)
        return stats

    def query_ms(catalog) -> float:
        """The ten queries, each the median of 3 runs, summed: what a reader waits for all ten."""
        con = oi.connect()
        oi.refresh_views(con, catalog)
        con.execute(oi.AREAS)
        total = 0.0
        for _, spec in oi.QUERIES:
            runs = []
            for _ in range(3):
                t0 = time.perf_counter()
                oi.iceberg_ids(con, spec)
                runs.append((time.perf_counter() - t0) * 1000)
            total += statistics.median(runs)
        return total

    return query_ms, table_stats


@app.cell
def _(
    CHECK_EVERY,
    DATA,
    MAINTAIN_EVERY,
    PBF,
    expire_with_pyiceberg,
    maintain_with_spark,
    minute_files,
    oi,
    query_ms,
    shutil,
    spark_for,
    table_stats,
    time,
):
    def replay(
        label: str, properties: dict[str, str], minutes: int, maintenance: str | None
    ) -> tuple[list, list, list]:
        """Import a fresh copy, apply `minutes` diffs, maintaining with "pyiceberg" or "spark" every MAINTAIN_EVERY.

        Returns per-diff, per-check and per-maintenance rows.
        """
        warehouse = DATA / f"replay-{label.replace(' ', '-').lower()}"
        shutil.rmtree(warehouse, ignore_errors=True)
        catalog = oi.open_catalog(warehouse)
        oi.create_tables(catalog, PBF, properties)
        spark = spark_for(warehouse) if maintenance == "spark" else None
        diffs, checks, runs = [], [], []
        checks.append(
            {"variant": label, "diffs applied": 0, "query ms": query_ms(catalog)} | table_stats(catalog, warehouse)
        )
        for i, path in enumerate(minute_files[:minutes], start=1):
            t0 = time.monotonic()
            oi.apply_diff(catalog, path)
            diffs.append({"variant": label, "diff": i, "apply s": time.monotonic() - t0})
            if maintenance and i % MAINTAIN_EVERY == 0:
                before = table_stats(catalog, warehouse)
                took = maintain_with_spark(spark) if spark else expire_with_pyiceberg(catalog)
                after = table_stats(catalog, warehouse)
                runs.append(
                    {"variant": label, "after diff": i, **took, "total s": sum(took.values())}
                    | {f"{k} before": before[k] for k in ("live data files", "snapshots", "metadata files")}
                    | {f"{k} after": after[k] for k in ("live data files", "snapshots", "metadata files")}
                )
            if i % CHECK_EVERY == 0:
                checks.append(
                    {"variant": label, "diffs applied": i, "query ms": query_ms(catalog)}
                    | table_stats(catalog, warehouse)
                )
                print(label, checks[-1], flush=True)
        if spark is not None:
            spark.stop()
        return diffs, checks, runs

    return (replay,)


@app.cell
def _(LEFT_ALONE_MINUTES, MAINTAINED_PROPERTIES, MINUTES, RESULTS, oi, pl, replay):
    _variants = [
        replay("left alone", oi.TABLE_PROPERTIES, LEFT_ALONE_MINUTES, None),
        replay("PyIceberg only", MAINTAINED_PROPERTIES, MINUTES, "pyiceberg"),
        replay("PyIceberg + Spark", MAINTAINED_PROPERTIES, MINUTES, "spark"),
    ]
    diffs = pl.DataFrame([row for v in _variants for row in v[0]])
    checks = pl.DataFrame([row for v in _variants for row in v[1]])
    maintenance = pl.DataFrame([row for v in _variants for row in v[2]], infer_schema_length=None)
    diffs.write_csv(RESULTS / "replay_diffs.csv")
    checks.write_csv(RESULTS / "replay_checks.csv")
    maintenance.write_csv(RESULTS / "replay_maintenance.csv")
    return checks, diffs, maintenance


@app.cell
def _(mo):
    mo.md("""
    ## Results

    **Apply time per minutely diff.** Under 60 s means Iceberg keeps up with a
    minutely feed. Diffs 201 to 300 compare the three copies at the same point;
    the last hundred show whether a copy drifts.
    """)
    return


@app.cell
def _(diffs, pl):
    apply_summary = diffs.group_by("variant", maintain_order=True).agg(
        pl.col("apply s").median().round(2).alias("median s"),
        pl.col("apply s").min().round(2).alias("min s"),
        pl.col("apply s").max().round(2).alias("max s"),
        pl.col("apply s").filter(pl.col("diff") <= 100).median().round(2).alias("median s, first 100"),
        pl.col("apply s").filter(pl.col("diff").is_between(201, 300)).median().round(2).alias("median s, 201-300"),
        pl.col("apply s")
        .filter(pl.col("diff") > pl.col("diff").max() - 100)
        .median()
        .round(2)
        .alias("median s, last 100"),
        (pl.col("apply s") > 60).sum().alias("diffs over 60 s"),
    )
    print(apply_summary)
    apply_summary
    return (apply_summary,)


@app.cell
def _(mo):
    mo.md("""
    **Growth.** Files and bytes on disk under each table's `metadata/` and
    `data/` folders, data files the current snapshot uses, snapshots, and the
    ten queries' total time, summed over the three tables.
    """)
    return


@app.cell
def _(checks, pl):
    growth = checks.with_columns(
        (pl.col("data MB") / pl.col("data files") * 1024).round(0).alias("avg data file KB"),
        pl.col("metadata MB").round(1),
        pl.col("data MB").round(0),
        pl.col("query ms").round(0),
    ).select(
        "variant",
        "diffs applied",
        "metadata files",
        "metadata MB",
        "data files",
        "live data files",
        "avg data file KB",
        "snapshots",
        "query ms",
    )
    with pl.Config(tbl_rows=60, tbl_cols=12, tbl_width_chars=220):
        print(growth)
    growth
    return (growth,)


@app.cell
def _(mo):
    mo.md("""
    **Maintenance cost.** One row per run (every 60 diffs), summed over the three
    tables, and what it cleared.
    """)
    return


@app.cell
def _(maintenance, pl):
    with pl.Config(tbl_rows=30, tbl_cols=14, tbl_width_chars=250):
        print(maintenance.with_columns(pl.selectors.ends_with(" s").round(1)))
    maintenance
    return


@app.cell
def _(RESULTS, apply_summary, growth, maintenance, pl):
    _end = growth.group_by("variant", maintain_order=True).agg(pl.all().last())
    _start = growth.group_by("variant", maintain_order=True).agg(pl.all().first())
    _lines = []
    for _row, _first, _apply in zip(
        _end.iter_rows(named=True), _start.iter_rows(named=True), apply_summary.iter_rows(named=True), strict=True
    ):
        _lines.append(
            f"{_row['variant']}: apply median {_apply['median s']} s (max {_apply['max s']}); after "
            f"{_row['diffs applied']} diffs {_row['metadata files']} metadata files / {_row['metadata MB']} MB, "
            f"{_row['live data files']} live data files (avg {_row['avg data file KB']} KB on disk), "
            f"{_row['snapshots']} snapshots; ten queries {_first['query ms']:.0f} ms at start, {_row['query ms']:.0f} ms at end"
        )
    for _variant, _runs in maintenance.group_by("variant", maintain_order=True):
        _lines.append(
            f"maintenance, {_variant[0]}: {_runs.height} runs, median {_runs['total s'].median():.1f} s "
            f"(range {_runs['total s'].min():.1f}-{_runs['total s'].max():.1f})"
        )
    (RESULTS / "replay_summary.txt").write_text("\n".join(_lines) + "\n")
    print("\n".join(_lines))
    return


if __name__ == "__main__":
    app.run()
