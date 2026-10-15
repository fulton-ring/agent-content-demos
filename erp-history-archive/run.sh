#!/usr/bin/env bash
# One command: build the synthetic GP database in SQL Server, archive it,
# reconcile the archive against the source, turn the source off, then answer
# the auditor queries from the archive alone.
set -euo pipefail
cd "$(dirname "$0")"

CONTAINER=gp-history-source
PORT=${GP_PORT:-14330}
IMAGE=mcr.microsoft.com/mssql/server:2022-latest
export GP_HOST="localhost:${PORT}" GP_DB=TWOSYN GP_READER=gp_archive_reader
# Throwaway passwords for a throwaway local server
export MSSQL_SA_PASSWORD="Gp!$(openssl rand -hex 12)"
export GP_READER_PASSWORD="Rd!$(openssl rand -hex 12)"

step() { printf '\n== %s\n' "$1"; }
declare -A T
timed() { local name=$1; shift; local s=$(date +%s.%N); "$@"; T[$name]=$(echo "$(date +%s.%N) - $s" | bc); }

step "Python environment"
[ -x .venv/bin/python ] || python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt
PY=.venv/bin/python

step "Start SQL Server 2022 (Developer edition) in Docker"
docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
docker run -d --name "$CONTAINER" -e ACCEPT_EULA=Y -e MSSQL_PID=Developer \
  -e MSSQL_SA_PASSWORD="$MSSQL_SA_PASSWORD" -p "${PORT}:1433" "$IMAGE" >/dev/null
$PY - <<'EOF'
import os, time, pymssql
for _ in range(90):
    try:
        pymssql.connect(os.environ["GP_HOST"], "sa", os.environ["MSSQL_SA_PASSWORD"], login_timeout=2).close(); break
    except Exception:
        time.sleep(2)
else:
    raise SystemExit("SQL Server did not start")
EOF

step "Build the synthetic GP company database (source)"
timed generate $PY source/generate.py

step "Export the archive with a read-only login"
timed export $PY archive/export.py

step "Reconcile source reports against the archive"
timed reconcile $PY reconcile.py

step "Turn the source off"
docker rm -f "$CONTAINER" >/dev/null
echo "SQL Server container removed. Everything below reads build/ only."

step "Auditor queries, answered from the archive alone"
mkdir -p results/samples
s=$(date +%s.%N)
q() { local out=$1; shift; { echo "\`python query.py $*\`"; echo; $PY query.py "$@" --markdown; } > "results/samples/$out.md"; echo "results/samples/$out.md"; }
q trial_balance_2024_12          trial_balance year=2024 period=12
q vendor_payment_history_V0001   vendor_payment_history vendor=V0001
q open_ar_at_2025-06-30          open_ar_at_date as_of=2025-06-30
q journal_entries_by_sa          journal_entries_by_user user=sa from=2023-01-01 to=2026-09-30
q journal_entries_by_GL.ACCT_2026-05 journal_entries_by_user user=GL.ACCT from=2026-05-01 to=2026-05-31
q document_trail_INV0000701      document_trail document=INV0000701
q document_trail_voided_payment  document_trail document=PMT0001500
q unusual_journal_entries        unusual_journal_entries from=2023-01-01 to=2026-09-30
# The same query from the Parquet files instead of the DuckDB file
$PY query.py trial_balance year=2024 period=12 --parquet --csv build/tb_from_parquet.csv
$PY query.py trial_balance year=2024 period=12 --csv build/tb_from_duckdb.csv
cmp -s build/tb_from_parquet.csv build/tb_from_duckdb.csv && echo "Parquet and DuckDB give the same trial balance"
T[queries]=$(echo "$(date +%s.%N) - $s" | bc)

{
  echo "# Timings from the last run"
  echo
  echo "| Step | Seconds |"
  echo "|---|---:|"
  for k in generate export reconcile queries; do printf '| %s | %.1f |\n' "$k" "${T[$k]}"; done
} > results/timings.md
cat results/timings.md
echo
echo "Done. See results/reconciliation.md"
