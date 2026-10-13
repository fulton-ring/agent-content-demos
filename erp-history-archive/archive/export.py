"""Copy every table of the GP company database into a DuckDB file and Parquet.

Connects with a login that can only read (db_datareader), proves it cannot
write, copies each table, then reads the archive back and compares a
fingerprint of every row against the source. Writes archive/manifest.json.
"""

import csv
import datetime as dt
import decimal
import hashlib
import json
import os
import shutil
import sys
import time

import duckdb
import pymssql

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "build")

TYPE_MAP = {"char": "VARCHAR", "varchar": "VARCHAR", "nchar": "VARCHAR", "nvarchar": "VARCHAR",
            "text": "VARCHAR", "tinyint": "UTINYINT", "smallint": "SMALLINT", "int": "INTEGER",
            "bigint": "BIGINT", "datetime": "TIMESTAMP", "date": "DATE", "bit": "BOOLEAN"}


def duck_type(data_type, precision, scale):
    if data_type in ("numeric", "decimal"):
        return f"DECIMAL({precision},{scale})"
    return TYPE_MAP[data_type]


def norm(v):
    """Canonical text for one value, the same whichever engine it came from."""
    if v is None:
        return "\\N"
    if isinstance(v, decimal.Decimal):
        return f"{v:.5f}"
    if isinstance(v, (dt.datetime, dt.date)):
        return v.strftime("%Y-%m-%d %H:%M:%S") if isinstance(v, dt.datetime) else v.isoformat()
    if isinstance(v, str):
        return v.rstrip(" ")
    return str(int(v))


def fingerprint(rows):
    """Order-independent fingerprint: sum of row hashes modulo 2**128."""
    total = 0
    for r in rows:
        h = hashlib.sha256("\x1f".join(norm(v) for v in r).encode()).digest()
        total = (total + int.from_bytes(h[:16], "big")) % (1 << 128)
    return f"{total:032x}"


def main():
    host = os.environ.get("GP_HOST", "localhost:14330")
    db = os.environ.get("GP_DB", "TWOSYN")
    user = os.environ.get("GP_READER", "gp_archive_reader")
    pw = os.environ["GP_READER_PASSWORD"]

    src = pymssql.connect(host, user, pw, db)
    cur = src.cursor()

    # Prove the login is read-only before touching anything
    try:
        cur.execute("UPDATE GL00100 SET ACTDESCR = ACTDESCR WHERE 1 = 0")
        src.commit()
        sys.exit("refusing to run: the archive login can write to the source database")
    except pymssql.Error as e:
        src.rollback()
        write_refused = str(e).split("DB-Lib")[0].strip(" b'\"(),0123456789")[:160]

    cur.execute("""SELECT t.TABLE_NAME, c.COLUMN_NAME, c.DATA_TYPE, c.NUMERIC_PRECISION, c.NUMERIC_SCALE
                   FROM INFORMATION_SCHEMA.TABLES t JOIN INFORMATION_SCHEMA.COLUMNS c
                     ON c.TABLE_NAME = t.TABLE_NAME AND c.TABLE_SCHEMA = t.TABLE_SCHEMA
                   WHERE t.TABLE_TYPE = 'BASE TABLE' AND t.TABLE_SCHEMA = 'dbo'
                   ORDER BY t.TABLE_NAME, c.ORDINAL_POSITION""")
    tables = {}
    for t, col, typ, prec, scale in cur.fetchall():
        tables.setdefault(t, []).append((col, duck_type(typ, prec, scale)))

    if os.path.exists(OUT):
        shutil.rmtree(OUT)
    os.makedirs(os.path.join(OUT, "parquet"))
    duck_path = os.path.join(OUT, "gp_archive.duckdb")
    duck = duckdb.connect(duck_path)
    duck.execute("CREATE SCHEMA gp")

    manifest = {"source": {"server": host, "database": db, "login": user,
                           "write_attempt": f"refused: {write_refused}"},
                "extracted_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "tables": []}
    started = time.perf_counter()
    for t, cols in tables.items():
        names = [c for c, _ in cols]
        cur.execute(f"SELECT {', '.join(names)} FROM dbo.{t}")
        rows = cur.fetchall()
        src_fp = fingerprint(rows)
        # GP pads char columns with trailing spaces; the archive stores them trimmed.
        trimmed = [tuple(v.rstrip(" ") if isinstance(v, str) else v for v in r) for r in rows]
        duck.execute(f"CREATE TABLE gp.{t} ({', '.join(f'{c} {ty}' for c, ty in cols)})")
        if trimmed:
            # Bulk load through a CSV file; inserting row by row is about 20 times slower
            tmp = os.path.join(OUT, f"{t}.csv")
            with open(tmp, "w", newline="") as f:
                csv.writer(f, quoting=csv.QUOTE_ALL).writerows([[norm(v) for v in r] for r in trimmed])
            duck.execute(f"COPY gp.{t} FROM '{tmp}' (FORMAT csv, HEADER false, QUOTE '\"', NULL '\\N')")
            os.remove(tmp)
        duck.execute(f"COPY gp.{t} TO '{os.path.join(OUT, 'parquet', t + '.parquet')}' (FORMAT parquet)")
        manifest["tables"].append({"table": t, "columns": len(names), "source_rows": len(rows),
                                   "source_fingerprint": src_fp})
    export_seconds = time.perf_counter() - started
    duck.close()
    src.close()

    # Read the archive back, from both the DuckDB file and the Parquet files
    duck = duckdb.connect(duck_path, read_only=True)
    for entry in manifest["tables"]:
        t = entry["table"]
        names = [c for c, _ in tables[t]]
        rows = duck.execute(f"SELECT {', '.join(names)} FROM gp.{t}").fetchall()
        prows = duck.execute(f"SELECT {', '.join(names)} FROM read_parquet('{os.path.join(OUT, 'parquet', t + '.parquet')}')").fetchall()
        entry["archive_rows"] = len(rows)
        entry["archive_fingerprint"] = fingerprint(rows)
        entry["parquet_fingerprint"] = fingerprint(prows)
        entry["match"] = (entry["source_rows"] == entry["archive_rows"]
                          and entry["source_fingerprint"] == entry["archive_fingerprint"] == entry["parquet_fingerprint"])
    duck.close()

    manifest["export_seconds"] = round(export_seconds, 1)
    manifest["duckdb_bytes"] = os.path.getsize(duck_path)
    manifest["parquet_bytes"] = sum(os.path.getsize(os.path.join(OUT, "parquet", f))
                                    for f in os.listdir(os.path.join(OUT, "parquet")))
    with open(os.path.join(OUT, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    bad = [e["table"] for e in manifest["tables"] if not e["match"]]
    print(f"exported {len(manifest['tables'])} tables, "
          f"{sum(e['source_rows'] for e in manifest['tables'])} rows in {export_seconds:.1f}s; "
          f"fingerprint mismatches: {bad or 'none'}", file=sys.stderr)


if __name__ == "__main__":
    main()
