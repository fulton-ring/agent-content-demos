import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import json
    import os
    import re
    import shlex
    import shutil
    import statistics
    import subprocess
    import sys
    import time
    from collections.abc import Callable
    from pathlib import Path

    import duckdb
    import httpx
    import marimo as mo
    import polars as pl
    import psycopg

    from answer_key import QUERIES, UNSUPPORTED

    return (
        QUERIES,
        UNSUPPORTED,
        Callable,
        Path,
        duckdb,
        httpx,
        json,
        mo,
        os,
        pl,
        psycopg,
        re,
        shlex,
        shutil,
        statistics,
        subprocess,
        sys,
        time,
    )


@app.cell
def _(mo):
    mo.md("""
    # Can existing Overpass clients run on PostGIS or DuckDB?

    #123 showed that osm2pgsql and PostGIS answer common Overpass queries exactly and
    faster, but it took a JSON stand-in for Overpass QL. Overpass Turbo, scripts and
    our HIFLD Next and substation pulls all send QL. So the missing piece is a QL
    front end: something that turns QL into SQL.

    One already exists. **[Underpass-API](https://github.com/teritorio/Underpass-API)**
    (Teritorio, AGPL-3.0) serves `/interpreter` like Overpass, using the Rust parser
    **[overpass_parser_rust](https://github.com/teritorio/overpass_parser_rust)**
    (MIT). The parser compiles QL to SQL for PostGIS (on an Osmosis schema) or DuckDB
    (on QuackOSM's GeoParquet). This notebook:

    1. runs Underpass-API **as shipped** on both backends against a ~30-query
       answer key from a local Overpass, comparing full output (IDs, tags,
       coordinates, node lists, members, geometry);
    2. closes the gaps it finds **in Underpass-API**, as a patch to its parser and
       server plus schema adapters on our side, and runs the same key again;
    3. measures latency, build time and size, and points Overpass Turbo at the result.
    """)
    return


@app.cell
def _(Path, os):
    # Everything the run depends on. The extract is #123's, so its numbers stay comparable.
    EXTRACT_URL = os.environ.get(
        "EXTRACT_URL", "https://download.bbbike.org/osm/bbbike/WashingtonDC/WashingtonDC.osm.pbf"
    )
    RUNS = int(os.environ.get("RUNS", "5"))
    # Behind a TLS-intercepting proxy, the Docker builds need its CA bundle (optional).
    CA_BUNDLE = os.environ.get("DOCKER_CA_BUNDLE", "")
    HERE = Path(__file__).resolve().parent
    assert " " not in str(HERE), "run this from a path without spaces (it is mounted into Docker)"
    DATA = HERE / "data"
    BUILD = DATA / "build"
    OUT = HERE / "results" / "ql_compiler"
    for _d in (DATA, BUILD, OUT, DATA / "quackosm", DATA / "duckdb"):
        _d.mkdir(parents=True, exist_ok=True)
    # Pinned sources and images.
    UNDERPASS_REPO = "https://github.com/teritorio/Underpass-API"
    UNDERPASS_COMMIT = "e9bad11d4b0e4422af6a226d89178a779afeeda8"  # 2025-10-17
    PARSER_REPO = "https://github.com/teritorio/overpass_parser_rust"
    PARSER_COMMIT = "61f1f559ed260c02d491c69a581148586c14bfbc"  # 2026-10-22
    RUST_IMAGE = "rust@sha256:7fa728f3678acf5980d5db70960cf8491aff9411976789086676bdf0c19db39e"  # 1.90-slim
    OVERPASS_IMAGE = "wiktorn/overpass-api@sha256:9bb5f4a9b54cd225bf828c04c67e7f4010650ff4d70b72157a9473a9ba02d93c"
    POSTGIS_IMAGE = "postgis/postgis@sha256:01a6a70e41e6c4467c8f55f6063555ed72db2d6662cd0d571040d42eadaeb6f6"
    OVERPASS_URL = "http://127.0.0.1:12346/api/interpreter"
    UNDERPASS_URL = "http://127.0.0.1:9292/interpreter"
    DB_URL = "postgresql://postgres:osm@127.0.0.1:15433/osm"
    return (
        BUILD,
        CA_BUNDLE,
        DATA,
        DB_URL,
        EXTRACT_URL,
        HERE,
        OUT,
        OVERPASS_IMAGE,
        OVERPASS_URL,
        PARSER_COMMIT,
        PARSER_REPO,
        POSTGIS_IMAGE,
        RUNS,
        RUST_IMAGE,
        UNDERPASS_COMMIT,
        UNDERPASS_REPO,
        UNDERPASS_URL,
    )


@app.cell
def _(Callable, shlex, subprocess, time):
    def sh(cmd: str, may_fail: bool = False, stdin: str | None = None) -> str:
        """Run a shell-style command line (split, not passed to a shell); return stdout, fail loudly."""
        done = subprocess.run(shlex.split(cmd), capture_output=True, text=True, input=stdin)
        if done.returncode != 0 and not may_fail:
            raise RuntimeError(f"`{cmd[:120]}` failed: {done.stderr[-2000:]}")
        return done.stdout

    def wait_until(check: Callable[[], bool], what: str, limit_s: float) -> None:
        """Poll `check()` every 2 s until it's true, for at most `limit_s` seconds."""
        deadline = time.monotonic() + limit_s
        while time.monotonic() < deadline:
            if check():
                return
            time.sleep(2)
        raise TimeoutError(f"gave up waiting for {what}")

    return sh, wait_until


@app.cell
def _(mo):
    mo.md("""
    ## The data

    #123's extract: BBBike's Washington DC extract (DC, Arlington, Alexandria and
    parts of Maryland; about 65 MB). OSM data © OpenStreetMap contributors, ODbL.
    BBBike refreshes it weekly; the snapshot time is printed below.
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
    print(f"extract snapshot {snapshot}")
    return (snapshot,)


@app.cell
def _(mo):
    mo.md("""
    ## Step 1: build Underpass-API and its parser, as shipped and patched

    Both are Rust. We build them in a pinned `rust` container: the parser's
    `overpass2sql` CLI twice (as shipped and with our patch), and the Underpass-API
    server once, patched, with only its PostGIS backend (the DuckDB backend needs
    libduckdb; we drive DuckDB from Python with the same parser instead).

    Our patches are in `underpass/`. `overpass_parser_rust.patch` (MIT) changes the
    grammar, the SQL it emits and the two dialects; `underpass_api.patch` (AGPL-3.0)
    makes the server return SQL errors as HTTP 400 instead of panicking, and builds
    against the patched parser. The cells further down list what each fixes.
    """)
    return


@app.cell
def _(
    BUILD,
    CA_BUNDLE,
    HERE,
    PARSER_COMMIT,
    PARSER_REPO,
    RUST_IMAGE,
    UNDERPASS_COMMIT,
    UNDERPASS_REPO,
    os,
    sh,
    shutil,
    snapshot,
    time,
):
    assert snapshot

    def checkout(repo: str, commit: str, path: str) -> None:
        """A clean checkout of `repo` at `commit` in BUILD/path."""
        shutil.rmtree(BUILD / path, ignore_errors=True)
        sh(f"git clone -q {repo} {BUILD / path}")
        sh(f"git -C {BUILD / path} checkout -q {commit}")

    def cargo(workdir: str, args: str) -> None:
        """Run cargo in the rust container, with the proxy and CA passed through when set."""
        proxy = os.environ.get("HTTPS_PROXY", "")
        env = f"-e HTTPS_PROXY={proxy} -e HTTP_PROXY={proxy}" if proxy else ""
        ca = f"-v {CA_BUNDLE}:/ca.crt:ro -e CARGO_HTTP_CAINFO=/ca.crt" if CA_BUNDLE else ""
        sh(f"docker run --rm --network host {env} {ca} -v {BUILD}:/b -w /b/{workdir} {RUST_IMAGE} cargo {args}")

    _t0 = time.monotonic()
    checkout(PARSER_REPO, PARSER_COMMIT, "parser_shipped")
    cargo("parser_shipped", "build --release -q")
    checkout(PARSER_REPO, PARSER_COMMIT, "overpass_parser_rust")
    sh(f"git -C {BUILD / 'overpass_parser_rust'} apply {HERE / 'underpass' / 'overpass_parser_rust.patch'}")
    cargo("overpass_parser_rust", "build --release -q")
    checkout(UNDERPASS_REPO, UNDERPASS_COMMIT, "Underpass-API")
    sh(f"git -C {BUILD / 'Underpass-API'} apply {HERE / 'underpass' / 'underpass_api.patch'}")
    cargo("Underpass-API", "build --release -q -p underpass-api --no-default-features --features postgres")
    PARSER_SHIPPED = BUILD / "parser_shipped" / "target" / "release" / "overpass2sql"
    PARSER_PATCHED = BUILD / "overpass_parser_rust" / "target" / "release" / "overpass2sql"
    assert PARSER_SHIPPED.exists() and PARSER_PATCHED.exists()
    print(f"built both parsers and the server in {time.monotonic() - _t0:.0f} s")
    return PARSER_PATCHED, PARSER_SHIPPED


@app.cell
def _(mo):
    mo.md("""
    ## The reference: Overpass

    Same image and settings as #123 (`wiktorn/overpass-api`, the image the Overpass
    wiki points to), on its own port so it doesn't collide with `benchmark.py`.
    """)
    return


@app.cell
def _(DATA, OVERPASS_IMAGE, PARSER_PATCHED, sh, wait_until):
    assert PARSER_PATCHED.exists()
    sh("docker rm -fv ql_ovp ql_pg ql_api", may_fail=True)
    sh("docker volume rm -f ql_ovp_db", may_fail=True)
    sh(
        f"docker run -d --name ql_ovp -p 12346:80 -v {DATA}:/data:ro -v ql_ovp_db:/db"
        " -e OVERPASS_MODE=init -e OVERPASS_META=no"
        " -e OVERPASS_PLANET_URL=file:///data/extract.osm.pbf"
        " -e 'OVERPASS_PLANET_PREPROCESS=mv /db/planet.osm.bz2 /db/planet.osm.pbf"
        " && osmium cat -o /db/planet.osm.bz2 /db/planet.osm.pbf && rm /db/planet.osm.pbf'"
        " -e OVERPASS_STOP_AFTER_INIT=false -e OVERPASS_ALLOW_DUPLICATE_QUERIES=yes"
        f" {OVERPASS_IMAGE}"
    )
    wait_until(lambda: "ready to receive requests" in sh("docker logs ql_ovp"), "the Overpass import", 4 * 3600)
    sh("docker exec ql_ovp chmod 755 /db")  # see #123: the web server can't reach the dispatcher otherwise
    _probe = "curl -sg --noproxy '*' 'http://127.0.0.1:12346/api/interpreter?data=[out:json];node(1);out;'"
    wait_until(lambda: '"generator"' in sh(_probe, may_fail=True), "Overpass to answer", 300)
    overpass_ready = True
    return (overpass_ready,)


@app.cell
def _(mo):
    mo.md("""
    ## Backend 1: PostGIS on Underpass-API's Osmosis schema

    Underpass-API's README loads the extract with **Osmosis** (`pgsnapshot` schema
    with way linestrings), then runs its own `init.sql` (tag indexes and assembled
    multipolygons for `area` queries). We follow it exactly, using
    `underpass/osmosis.Dockerfile`, a copy of its Osmosis image.

    Then our adapter, `underpass/postgres_init.sql`, adds what the parser's SQL
    needs and the schema lacks: jsonb tags (Osmosis stores hstore, but the parser
    now emits jsonb operators), and each relation's geometry as the collection of its
    members' geometries, because Overpass finds a relation in a bbox or area through
    its members. `underpass/postgres_views.sql` replaces Underpass-API's `view.sql`
    and adds relation members in Overpass's JSON shape.
    """)
    return


@app.cell
def _(BUILD, CA_BUNDLE, DATA, DB_URL, HERE, POSTGIS_IMAGE, overpass_ready, psycopg, sh, shutil, time, wait_until):
    assert overpass_ready
    sh(
        f"docker run -d --name ql_pg --shm-size 1g -p 15433:5432 -e POSTGRES_PASSWORD=osm -e POSTGRES_DB=osm {POSTGIS_IMAGE}"
    )
    _psql = "docker exec ql_pg psql -U postgres -d osm -Atc"
    # The image starts PostgreSQL, runs its init scripts, then restarts it once.
    wait_until(lambda: "1" in sh(f"{_psql} 'select 1'", may_fail=True), "PostgreSQL to start", 120)
    time.sleep(3)
    wait_until(lambda: "1" in sh(f"{_psql} 'select 1'", may_fail=True), "PostgreSQL to restart", 120)
    sh(f"{_psql} 'create extension if not exists hstore'")

    _ctx = BUILD / "osmosis"
    _ctx.mkdir(exist_ok=True)
    shutil.copy(HERE / "underpass" / "osmosis.Dockerfile", _ctx / "Dockerfile")
    (_ctx / "ca.crt").write_bytes(open(CA_BUNDLE, "rb").read() if CA_BUNDLE else b"")
    sh(f"docker build -q --network host -t ql-osmosis {_ctx}")

    _examples = "/usr/share/doc/osmosis/examples"
    pg_times = {}
    _t0 = time.monotonic()
    sh(
        f"docker run --rm --network host -e PGPASSWORD=osm -v {DATA}:/data:ro ql-osmosis sh -c"
        f" 'psql -h 127.0.0.1 -p 15433 -U postgres -d osm -q -v ON_ERROR_STOP=1"
        f" -f {_examples}/pgsnapshot_schema_0.6.sql -f {_examples}/pgsnapshot_schema_0.6_linestring.sql"
        " && osmosis -q --read-pbf /data/extract.osm.pbf"
        " --write-pgsql host=127.0.0.1:15433 database=osm user=postgres password=osm'"
    )
    pg_times["Osmosis load"] = time.monotonic() - _t0
    with psycopg.connect(DB_URL, autocommit=True) as _con:
        for _name, _file in [
            ("Underpass-API init.sql", BUILD / "Underpass-API" / "src" / "postgres_osmosis" / "init.sql"),
            ("our adapter", HERE / "underpass" / "postgres_init.sql"),
        ]:
            _t0 = time.monotonic()
            _con.execute(_file.read_text())
            pg_times[_name] = time.monotonic() - _t0
        pg_mb = _con.execute("select pg_database_size('osm')").fetchone()[0] / 2**20
    print({k: f"{v:.0f} s" for k, v in pg_times.items()}, f"database {pg_mb:,.0f} MB")
    return pg_mb, pg_times


@app.cell
def _(BUILD, DB_URL, HERE, RUST_IMAGE, UNDERPASS_URL, httpx, pg_times, sh, wait_until):
    assert pg_times
    # The patched server, with our views mounted in place of its own view.sql.
    sh(
        f"docker run -d --name ql_api --network host -v {BUILD / 'Underpass-API'}:/app"
        f" -v {HERE / 'underpass' / 'postgres_views.sql'}:/app/src/postgres_osmosis/view.sql:ro -w /app"
        f" -e BACKEND=PostgresOsmosis -e DB={DB_URL} {RUST_IMAGE} target/release/underpass-api serve"
    )

    def _up() -> bool:
        try:
            return httpx.get(UNDERPASS_URL.replace("interpreter", "up"), timeout=5, trust_env=False).status_code == 204
        except httpx.HTTPError:
            return False

    wait_until(_up, "the Underpass-API server", 60)
    underpass_ready = True
    return (underpass_ready,)


@app.cell
def _(mo):
    mo.md("""
    ## Backend 2: DuckDB on Parquet

    Underpass-API's DuckDB backend reads QuackOSM's GeoParquet: one row per feature
    with tags and geometry, but **no way node lists or relation members**, so it can't
    recurse. We keep QuackOSM for what it is good at, assembling multipolygons for
    `area` queries, and build the raw tables the issue asks for with DuckDB's own
    `ST_ReadOSM` (`underpass/duckdb_build.sql`):

    - `nodes`, `ways` (with node lists and their line geometry) and `relations` (with
      members and the collection of member geometries), and `areas` from QuackOSM;
    - each sorted along a Hilbert curve with a bbox column, so Parquet row-group
      statistics prune spatial filters (Underpass-API's own trick).

    `underpass/duckdb_views.sql` exposes them under the view names the parser's SQL
    reads. For the as-shipped run we also build Underpass-API's own tables.
    """)
    return


@app.cell
def _(BUILD, DATA, HERE, Path, duckdb, sh, sys, time, underpass_ready):
    assert underpass_ready
    duck_times = {}
    _qosm = DATA / "quackosm" / "dc_nofilter_noclip_compact.parquet"
    _t0 = time.monotonic()
    sh(
        f"{Path(sys.executable).parent / 'quackosm'} --no-sort --silent --ignore-cache"
        f" --working-directory {DATA / 'quackosm'} --output {_qosm} {DATA / 'extract.osm.pbf'}"
    )
    duck_times["QuackOSM GeoParquet"] = time.monotonic() - _t0

    _sql = (HERE / "underpass" / "duckdb_build.sql").read_text()
    for _k, _v in {"{pbf}": DATA / "extract.osm.pbf", "{quackosm}": _qosm, "{out}": DATA / "duckdb"}.items():
        _sql = _sql.replace(_k, str(_v))
    _t0 = time.monotonic()
    duckdb.connect().execute(_sql)
    duck_times["our tables (ST_ReadOSM + QuackOSM areas)"] = time.monotonic() - _t0

    # Underpass-API's own DuckDB tables, for the as-shipped run.
    _init = (BUILD / "Underpass-API" / "src" / "duckdb_quackosm" / "init.sql").read_text()
    _t0 = time.monotonic()
    duckdb.connect().execute(_init.replace("#{parquet}", str(_qosm)))
    duck_times["Underpass-API init.sql (as shipped)"] = time.monotonic() - _t0

    duck_mb = {
        "QuackOSM GeoParquet": _qosm.stat().st_size / 2**20,
        "our tables": sum(p.stat().st_size for p in (DATA / "duckdb").glob("*.parquet")) / 2**20,
    }
    print({k: f"{v:.0f} s" for k, v in duck_times.items()}, {k: f"{v:.0f} MB" for k, v in duck_mb.items()})
    return duck_mb, duck_times


@app.cell
def _(mo):
    mo.md("""
    ## The answer key

    31 queries, all in `answer_key.py`: #123's ten (now with full output, not
    `out ids`), overpass-turbo wizard and example shapes, HIFLD-style infrastructure
    pulls (substations, power lines, hospitals, fire stations), and set and recursion
    queries. Each runs on the local Overpass, and its JSON is the answer.

    A query **matches** when both sides return the same elements and, for each, the
    same fields: tags, coordinates, node lists, members, center, bounds and geometry.
    Coordinates may differ by 1e-7 degrees (about 1 cm), the last digit Overpass
    prints, because Overpass rounds centres differently.
    """)
    return


@app.cell
def _(QUERIES, pl):
    pl.DataFrame({"query": [q[0] for q in QUERIES], "Overpass QL": [q[1] for q in QUERIES]})
    return


@app.cell
def _(OVERPASS_URL, UNDERPASS_URL, httpx):
    client = httpx.Client(timeout=600, trust_env=False)

    def ask_http(url: str, ql: str) -> list[dict]:
        """POST QL to an Overpass-compatible endpoint and return its elements, or raise with its error."""
        r = client.post(url, data={"data": ql})
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text.strip()[:300]}")
        body = r.json()
        assert "remark" not in body, f"remark: {body['remark']}"
        return body["elements"]

    def ask_overpass(ql: str) -> list[dict]:
        return ask_http(OVERPASS_URL, ql)

    def ask_underpass(ql: str) -> list[dict]:
        return ask_http(UNDERPASS_URL, ql)

    def close(a: object, b: object) -> bool:
        """Equal, except that floats may differ by 1e-7 (Overpass's last printed digit)."""
        if isinstance(a, float) and isinstance(b, (float, int)) or isinstance(b, float) and isinstance(a, int):
            return abs(float(a) - float(b)) <= 1.01e-7
        if isinstance(a, dict) and isinstance(b, dict):
            return a.keys() == b.keys() and all(close(a[k], b[k]) for k in a)
        if isinstance(a, list) and isinstance(b, list):
            return len(a) == len(b) and all(close(x, y) for x, y in zip(a, b, strict=True))
        return a == b

    def compare(expected: list[dict], got: list[dict]) -> str:
        """'match', or what differs: missing and extra elements, duplicates, and fields that differ."""
        exp = {(e["type"], e["id"]): e for e in expected}
        res = {(e["type"], e["id"]): e for e in got}
        problems = []
        if exp.keys() - res.keys():
            problems.append(f"{len(exp.keys() - res.keys())} missing")
        if res.keys() - exp.keys():
            problems.append(f"{len(res.keys() - exp.keys())} extra")
        if len(got) - len(res) != len(expected) - len(exp):
            problems.append("duplicates differ")
        fields: dict[str, int] = {}
        for key in exp.keys() & res.keys():
            for f in exp[key].keys() | res[key].keys():
                if not close(exp[key].get(f), res[key].get(f)):
                    fields[f] = fields.get(f, 0) + 1
        problems += [f"{f} differs on {n}" for f, n in sorted(fields.items())]
        return "; ".join(problems) or "match"

    return ask_overpass, ask_underpass, client, compare


@app.cell
def _(DATA, QUERIES, ask_overpass, json):
    # The answer key itself: Overpass's output for every query (kept in data/, not committed).
    answers = {name: ask_overpass(ql) for name, ql in QUERIES}
    (DATA / "answer_key.json").write_text(json.dumps(answers))
    print(f"{len(answers)} answers, {sum(len(v) for v in answers.values()):,} elements in all")
    return (answers,)


@app.cell
def _(mo):
    mo.md("""
    ## Run 1: Underpass-API as shipped

    The shipped parser's SQL, run on each backend with Underpass-API's own views
    (directly, not through its server, which panics on the first SQL error). Each
    DuckDB query runs in a child process, because one of them crashes DuckDB.
    """)
    return


@app.cell
def _(BUILD, DATA, DB_URL, PARSER_SHIPPED, QUERIES, answers, compare, json, pl, psycopg, subprocess, sys):
    _pg_views = (BUILD / "Underpass-API" / "src" / "postgres_osmosis" / "view.sql").read_text()
    _duck_views = (
        (BUILD / "Underpass-API" / "src" / "duckdb_quackosm" / "view.sql")
        .read_text()
        .replace("#{parquet}", str(DATA / "quackosm" / "dc_nofilter_noclip_compact.parquet"))
    )
    # Run one DuckDB query in a fresh process: argv = views SQL, query SQL; prints the JSON rows.
    _duck_child = (
        "import duckdb, json, sys\n"
        "c = duckdb.connect(); c.execute(sys.argv[1])\n"
        "print(json.dumps([r[0] if isinstance(r[0], str) else json.dumps(r[0]) for r in c.execute(sys.argv[2]).fetchall()]))"
    )

    def _status(name: str, ql: str, dialect: str) -> str:
        parsed = subprocess.run([str(PARSER_SHIPPED), dialect], input=ql, capture_output=True, text=True)
        if parsed.returncode != 0:
            return "parse error"
        sql = parsed.stdout
        try:
            if dialect == "postgres":
                with psycopg.connect(DB_URL) as con:
                    con.execute(_pg_views)
                    statements = [s for s in sql.split(";\n") if s.strip()]
                    for s in statements[:-1]:
                        con.execute(s)
                    rows = [r[0] for r in con.execute(statements[-1]).fetchall()]
            else:
                run = subprocess.run(
                    [sys.executable, "-c", _duck_child, _duck_views, sql], capture_output=True, text=True, timeout=600
                )
                if run.returncode < 0:
                    return "DuckDB crashed"
                if run.returncode != 0:
                    return "SQL error: " + run.stderr.strip().splitlines()[-1][:120]
                rows = [json.loads(r) for r in json.loads(run.stdout)]
        except psycopg.Error as e:
            return "SQL error: " + str(e).splitlines()[0][:120]
        return compare(answers[name], rows)

    _rows = [
        {"query": _name, "PostGIS": _status(_name, _ql, "postgres"), "DuckDB": _status(_name, _ql, "duckdb")}
        for _name, _ql in QUERIES
    ]
    shipped = pl.DataFrame(_rows)
    shipped
    return (shipped,)


@app.cell
def _(OUT, pl, shipped):
    def _kind(status: str) -> str:
        """Group a status into match, parse error, DuckDB crashed, SQL error or wrong output."""
        if status in ("match", "parse error", "DuckDB crashed"):
            return status
        return "SQL error" if status.startswith("SQL error") else "wrong output"

    shipped.write_csv(OUT / "as_shipped.csv")
    shipped_summary = pl.DataFrame(
        [
            {"backend": b, "outcome": k, "queries": n}
            for b in ("PostGIS", "DuckDB")
            for k, n in shipped[b].map_elements(_kind, return_dtype=pl.String).value_counts().iter_rows()
        ]
    ).sort("backend", "queries", descending=[False, True])
    shipped_summary
    return (shipped_summary,)


@app.cell
def _(mo):
    mo.md("""
    ## What we changed

    Each gap is named by where it sits: **parser** (the grammar), **SQL** (what the
    parser emits) or **schema** (what the backend tables hold).

    | gap | where | fix |
    |---|---|---|
    | no end-of-input anchor: anything not understood (and everything after it) was silently dropped | parser | `SOI ~ … ~ EOI`, and a named error for out-of-scope features |
    | settings other than `[out:json][timeout:]` in that order (`[bbox:]`, `[maxsize:]`) | parser | settings in any order; `[bbox:]` applied to every query without its own |
    | `around:r,lat,lon`; radius applied in degrees, not metres | parser, SQL | point form; `ST_DWithin` on geography (PostGIS), an azimuthal-equidistant projection (DuckDB) |
    | key regex `[~"k"~"v"]`, case-insensitive `,i` (it ended up inside the regex) | parser, SQL | both, with dialect regex functions (DuckDB's `~` is a full match) |
    | `>`, `>>`, `<`, `<<` all emitted one hard-coded query, wrong for most inputs | parser, SQL | one query per operator, following Overpass's definitions |
    | `node(w)`, `way(r)`, `rel(bn)` read jsonb members and a function no schema has | SQL, schema | written against node lists and members; members added to both schemas |
    | `._` / `.a` as a statement, so `(._;>;)` failed | parser | allowed |
    | `out` printed geometry by default, coordinates for `out ids`/`out tags`, GeoJSON for nodes, `ST_PointOnSurface` as center | SQL | fields as Overpass prints them; center is the bbox centre; `out count` |
    | tags as hstore (Osmosis) but jsonb operators in the SQL: every tag filter failed | schema | jsonb tags with a GIN index (adapter) |
    | relation geometry NULL (PostGIS), so relations never matched a bbox or area | schema | collection of member geometries (both backends) |
    | area filter as a join: elements in two matching areas came out twice | SQL | `EXISTS` |
    | DuckDB: bbox SQL read `.xmax` off a geometry; `jsonb` type; polygon kept in a session variable crashed DuckDB | SQL | dialect fixes; polygons in a temp table |
    | open polygons in `poly:` | SQL | ring closed as Overpass does |
    | QuackOSM has no node lists or members | schema | raw tables from `ST_ReadOSM` |
    | server panicked on any SQL error (client saw a dropped connection) | server | HTTP 400 with the error |
    """)
    return


@app.cell
def _(mo):
    mo.md("""
    ## Run 2: patched, on both backends

    PostGIS through the patched Underpass-API server over HTTP, the way a client
    sees it; DuckDB in-process from Python with the patched parser (parse plus
    query). Each query runs once to warm caches, then `RUNS` times on each side in
    turn; latency is the median (p50).
    """)
    return


@app.cell
def _(DATA, HERE, PARSER_PATCHED, duckdb, json, subprocess):
    duck = duckdb.connect()
    duck.execute((HERE / "underpass" / "duckdb_views.sql").read_text().replace("{out}", str(DATA / "duckdb")))

    def ask_duckdb(ql: str) -> list[dict]:
        """Compile QL with the patched parser and run it on the DuckDB views; temp tables are rolled back."""
        parsed = subprocess.run([str(PARSER_PATCHED), "duckdb"], input=ql, capture_output=True, text=True)
        if parsed.returncode != 0:
            raise RuntimeError("parse error")
        duck.execute("BEGIN")
        try:
            rows = duck.execute(parsed.stdout).fetchall()
        finally:
            duck.execute("ROLLBACK")
        return [json.loads(r[0]) if isinstance(r[0], str) else r[0] for r in rows]

    return (ask_duckdb,)


@app.cell
def _(QUERIES, RUNS, answers, ask_duckdb, ask_overpass, ask_underpass, compare, pl, statistics, time):
    def _timed(ask, ql: str) -> float:
        t0 = time.perf_counter()
        ask(ql)
        return time.perf_counter() - t0

    _rows = []
    for _name, _ql in QUERIES:
        _status: dict[str, str] = {}
        for _side, _ask in [("PostGIS", ask_underpass), ("DuckDB", ask_duckdb)]:
            try:
                _status[_side] = compare(answers[_name], _ask(_ql))
            except Exception as e:  # a failing query is a result: record it in the table
                _status[_side] = f"error: {str(e)[:120]}"
        _times: dict[str, list[float]] = {"Overpass": [], "PostGIS": [], "DuckDB": []}
        for _ in range(RUNS):
            for _side, _ask in [("Overpass", ask_overpass), ("PostGIS", ask_underpass), ("DuckDB", ask_duckdb)]:
                if not _status.get(_side, "").startswith("error"):
                    _times[_side].append(_timed(_ask, _ql))
        _p50 = {f"{s} p50 ms": round(statistics.median(t) * 1000) if t else None for s, t in _times.items()}
        _rows.append({"query": _name, "elements": len(answers[_name]), **_status, **_p50})
    patched = pl.DataFrame(_rows)
    patched
    return (patched,)


@app.cell
def _(OUT, patched, pl):
    patched.write_csv(OUT / "patched.csv")
    _n = patched.height
    latency = pl.DataFrame(
        {
            "side": ["Overpass", "PostGIS (Underpass-API)", "DuckDB (patched parser)"],
            "queries matching Overpass": [
                f"{_n}/{_n}",
                f"{(patched['PostGIS'] == 'match').sum()}/{_n}",
                f"{(patched['DuckDB'] == 'match').sum()}/{_n}",
            ],
            "p50 of per-query p50s, ms": [
                patched["Overpass p50 ms"].median(),
                patched["PostGIS p50 ms"].median(),
                patched["DuckDB p50 ms"].median(),
            ],
            "faster than Overpass on": [
                "",
                f"{(patched['PostGIS p50 ms'] < patched['Overpass p50 ms']).sum()}/{_n}",
                f"{(patched['DuckDB p50 ms'] < patched['Overpass p50 ms']).sum()}/{_n}",
            ],
        }
    )
    latency
    return (latency,)


@app.cell
def _(patched, pl):
    # The queries that don't match, and why.
    patched.filter((pl.col("PostGIS") != "match") | (pl.col("DuckDB") != "match")).select("query", "PostGIS", "DuckDB")
    return


@app.cell
def _(mo):
    mo.md("""
    ## Out of scope: does each fail with a clear error?

    The issue rules out attic queries, `foreach`/`if`/`complete` and evaluators.
    Underpass-API implements `foreach` (and `convert`), so that one runs; we check
    it against Overpass too.
    """)
    return


@app.cell
def _(OUT, UNSUPPORTED, ask_overpass, ask_underpass, compare, pl, re):
    _rows = []
    for _name, _ql in UNSUPPORTED:
        try:
            _got = ask_underpass(_ql)
            _outcome = "runs; " + compare(ask_overpass(_ql), _got) + " against Overpass"
        except RuntimeError as e:
            _msg = re.search(r"unsupported Overpass QL feature: [^<\n]*", str(e))
            _outcome = _msg.group(0) if _msg else "error without a feature name: " + str(e)[:80]
        _rows.append({"feature": _name, "PostGIS endpoint": _outcome})
    unsupported = pl.DataFrame(_rows)
    unsupported.write_csv(OUT / "out_of_scope.csv")
    unsupported
    return (unsupported,)


@app.cell
def _(mo):
    mo.md("""
    ## Overpass Turbo against the PostGIS endpoint

    Overpass Turbo reads `{{data:overpass,server=…}}` from the query, so the public
    overpass-turbo.eu can be pointed at our endpoint unchanged (Underpass-API allows
    CORS from any origin). `underpass/turbo_screenshot.js` opens it in Playwright
    with a DC substations-and-power-lines query and saves a screenshot. It needs Node
    and Playwright; the cell skips it without them.
    """)
    return


@app.cell
def _(HERE, OUT, UNDERPASS_URL, latency, sh, shutil):
    assert latency is not None
    if shutil.which("node"):
        _out = sh(
            f"node {HERE / 'underpass' / 'turbo_screenshot.js'} {UNDERPASS_URL.replace('interpreter', '')}"
            f" {OUT / 'overpass_turbo.png'}",
            may_fail=True,
        )
        print(_out.strip() or "screenshot failed (is Playwright installed?)")
    else:
        print("node not found: skipped the Overpass Turbo screenshot")
    return


@app.cell
def _(mo):
    mo.md("""
    ## How big is it, and how much of QL does it cover?

    Lines of Rust, not counting blank lines, comments or the crates' unit tests;
    *shared* is the grammar and everything outside the two dialect files.
    """)
    return


@app.cell
def _(BUILD, HERE, OUT, pl, sh):
    def _loc(path) -> int:
        """Non-blank, non-comment lines before any `#[cfg(test)]` module."""
        code = path.read_text().split("#[cfg(test)]")[0]
        return sum(1 for line in code.splitlines() if line.strip() and not line.strip().startswith("//"))

    _src = BUILD / "overpass_parser_rust" / "src"
    _dialects = {"postgres.rs", "duckdb.rs"}
    _shared = [p for p in _src.rglob("*.rs") if p.name not in _dialects]
    _patch = sh(f"git -C {BUILD / 'overpass_parser_rust'} diff --shortstat").strip()
    size = pl.DataFrame(
        {
            "part": [
                "parser, shared (grammar + Rust)",
                "PostgreSQL dialect",
                "DuckDB dialect",
                "Underpass-API server",
                "our SQL adapters (PostGIS init + views, DuckDB build + views)",
            ],
            "lines": [
                sum(_loc(p) for p in _shared) + _loc(BUILD / "overpass_parser_rust" / "overpass.pest"),
                _loc(_src / "sql_dialect" / "postgres.rs"),
                _loc(_src / "sql_dialect" / "duckdb.rs"),
                sum(_loc(p) for p in (BUILD / "Underpass-API" / "src").rglob("*.rs")),
                sum(
                    sum(
                        1
                        for line in (HERE / "underpass" / f).read_text().splitlines()
                        if line.strip() and not line.startswith("--")
                    )
                    for f in ("postgres_init.sql", "postgres_views.sql", "duckdb_build.sql", "duckdb_views.sql")
                ),
            ],
        }
    )
    size.write_csv(OUT / "size.csv")
    print("our parser patch:", _patch)
    size
    return


@app.cell
def _(OUT, pl):
    # The Overpass QL language reference's features, and where the patched compiler stands on each.
    # yes = in the answer key and matching, or checked by hand; partial = see note; no = named error.
    FEATURES = [
        ("settings", "[out:json]", "yes", ""),
        ("settings", "[out:xml], csv, custom, popup", "no", "JSON only"),
        ("settings", "[timeout:]", "yes", "becomes statement_timeout"),
        ("settings", "[maxsize:]", "partial", "parsed, ignored"),
        ("settings", "[bbox:]", "yes", ""),
        ("settings", "[date:], [diff:], [adiff:]", "no", "needs history"),
        ("block", "union ( ... )", "yes", ""),
        ("block", "difference ( ... - ... )", "yes", ""),
        ("block", "if", "no", ""),
        ("block", "foreach", "yes", "Underpass-API's; matches Overpass on our one test"),
        ("block", "for, complete, retro, compare", "no", ""),
        ("statement", "item (._, .a)", "yes", ""),
        ("statement", "recurse >, >>, <, <<", "yes", ""),
        ("statement", "is_in, map_to_area", "no", ""),
        ("statement", "timeline, local, make", "no", ""),
        ("statement", "convert", "partial", "Underpass-API's; not in the answer key"),
        ("query", "node, way, rel, nwr, area", "yes", ""),
        ("query", "nw, nr, wr, derived", "no", "not in the grammar"),
        ("filter", "tag =, !=, exists, !exists", "yes", ""),
        ("filter", "value regex ~, !~", "yes", "in PostgreSQL's or DuckDB's (RE2) regex dialect"),
        ("filter", 'key regex ~"k"~"v"', "yes", ""),
        ("filter", "case-insensitive ,i", "yes", ""),
        ("filter", "bbox", "yes", ""),
        ("filter", "recurse n, w, r, bn, bw, br, with roles", "yes", "bw, br untested"),
        ("filter", "input set (.a)", "yes", ""),
        ("filter", "id, id:", "yes", ""),
        (
            "filter",
            "around (point, set)",
            "partial",
            "several points are treated as points, not a polyline; set radius approximate on DuckDB",
        ),
        ("filter", "poly", "yes", ""),
        ("filter", "area (area.a), area(id)", "yes", "way areas keep the way id, not id + 2400000000"),
        ("filter", "pivot, newer, changed, user, uid, if:", "no", ""),
        ("out", "ids, skel, body, tags", "yes", ""),
        ("out", "meta", "partial", "version and timestamp; no user names"),
        ("out", "count", "partial", "no areas key"),
        ("out", "center, bb", "yes", ""),
        ("out", "geom", "partial", "ways yes; relation member geometry no"),
        ("out", "qt, asc", "partial", "accepted; order not guaranteed"),
        ("out", "limit (out 10), noids", "no", ""),
    ]
    coverage = pl.DataFrame(FEATURES, schema=["group", "feature", "status", "note"], orient="row")
    coverage.write_csv(OUT / "coverage.csv")
    print(coverage["status"].value_counts().sort("status"))
    coverage
    return (coverage,)


@app.cell
def _(OUT, coverage, duck_mb, duck_times, latency, patched, pg_mb, pg_times, shipped_summary, snapshot, unsupported):
    _n = patched.height
    _lines = [
        f"Extract snapshot: {snapshot}",
        f"Answer key: {_n} queries",
        "As shipped: "
        + ", ".join(f"{r['backend']} {r['outcome']} {r['queries']}" for r in shipped_summary.iter_rows(named=True)),
        f"Patched: PostGIS {(patched['PostGIS'] == 'match').sum()}/{_n} match, DuckDB {(patched['DuckDB'] == 'match').sum()}/{_n} match",
        "Median of per-query p50s (ms): " + ", ".join(f"{r[0]} {r[2]}" for r in latency.iter_rows()),
        "PostGIS build: " + ", ".join(f"{k} {v:.0f} s" for k, v in pg_times.items()) + f"; database {pg_mb:,.0f} MB",
        "DuckDB build: "
        + ", ".join(f"{k} {v:.0f} s" for k, v in duck_times.items())
        + "; "
        + ", ".join(f"{k} {v:.0f} MB" for k, v in duck_mb.items()),
        "Out of scope: " + "; ".join(f"{r[0]}: {r[1]}" for r in unsupported.iter_rows()),
        "QL features: "
        + ", ".join(f"{s} {n}" for s, n in coverage["status"].value_counts().sort("status").iter_rows()),
    ]
    (OUT / "summary.txt").write_text("\n".join(_lines) + "\n")
    print("\n".join(_lines))
    return


@app.cell
def _(mo):
    mo.md("""
    ## What didn't work, and what this doesn't show

    - **As shipped, nothing ran** on either backend (table above). Underpass-API's
      backends lag its parser: the parser moved to jsonb and new SQL, the Osmosis
      views kept hstore, and the DuckDB dialect broke on DuckDB 1.4's spatial
      extension. The fixes are mostly small, but there are many.
    - **QuackOSM 0.19 fails on DuckDB 2.0**, so DuckDB is pinned to 1.4.
    - **The parser's own unit tests**: 12 of its 32 pin the exact SQL text, which
      our patch changes, so they need new expected text before this goes upstream.
      No test query fails to parse.
    - **One region, one machine, no load test**, and the DuckDB timings are
      in-process, while PostGIS and Overpass are over HTTP.
    - **Our adapters are built once**: relation geometry and the DuckDB tables are
      not kept current by diffs, unlike #123's osm2pgsql setup.
    """)
    return


@app.cell
def _(client, sh, unsupported):
    assert unsupported is not None
    client.close()
    sh("docker rm -fv ql_ovp ql_pg ql_api", may_fail=True)
    sh("docker volume rm -f ql_ovp_db", may_fail=True)
    print("removed the containers")
    return


if __name__ == "__main__":
    app.run()
