#!/usr/bin/env bash
# One command: start SeaweedFS (S3-compatible object store) and PostGIS in Docker, download the HIFLD Next layers,
# write the four layouts, run every query both ways, and write results/. Every number in README.md comes from this run.
set -euo pipefail
cd "$(dirname "$0")"
command -v uv >/dev/null || { echo "uv is needed: https://docs.astral.sh/uv/getting-started/installation/"; exit 1; }
command -v docker >/dev/null || { echo "Docker is needed for SeaweedFS and PostGIS"; exit 1; }

export S3_ENDPOINT="${S3_ENDPOINT:-localhost:8333}"
export PG_DSN="${PG_DSN:-host=localhost port=5432 user=postgres password=bench dbname=postgres}"

docker rm -f -v gvp-seaweedfs gvp-postgis >/dev/null 2>&1 || true
docker run -d --name gvp-seaweedfs -p 8333:8333 chrislusf/seaweedfs:3.97 server -s3 -dir=/data >/dev/null
docker run -d --name gvp-postgis -p 5432:5432 -e POSTGRES_PASSWORD=bench --shm-size=1g postgis/postgis:17-3.5 >/dev/null
trap 'docker rm -f -v gvp-seaweedfs gvp-postgis >/dev/null 2>&1 || true' EXIT

# Ready means SeaweedFS accepts a write (its volume server starts after the S3 port opens) and PostgreSQL answers.
for _ in $(seq 1 60); do
  curl -s --noproxy '*' -o /dev/null -X PUT "http://${S3_ENDPOINT}/hifld" || true
  code=$(curl -s --noproxy '*' -o /dev/null -w '%{http_code}' -X PUT --data ok "http://${S3_ENDPOINT}/hifld/ready" || true)
  if [ "$code" = "200" ] && docker exec gvp-postgis pg_isready -U postgres -q; then
    break
  fi
  sleep 2
done
sleep 5  # PostGIS restarts once after its init scripts run

mkdir -p "${RESULTS_DIR:-results}"
uv run benchmark.py 2>&1 | tee "${RESULTS_DIR:-results}/run_log.txt"
