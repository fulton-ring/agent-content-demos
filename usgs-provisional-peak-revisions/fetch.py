"""HTTP helpers shared by the snapshot script and the notebook: USGS OGC API v1 and IEM HADS archive."""

import io
import os
import time

import httpx
import polars as pl

USGS_OGC = os.environ.get("USGS_OGC_URL", "https://api.waterdata.usgs.gov/ogcapi/v1")
IEM_HADS = os.environ.get("IEM_HADS_URL", "https://mesonet.agron.iastate.edu/cgi-bin/request/hads.py")
MAX_PAGES = 50
MAX_TRIES = 5


def get(client: httpx.Client, url: str, params: dict[str, str] | None = None) -> httpx.Response:
    """GET with bounded retries and backoff on 429, 5xx and network errors. Raises on final failure."""
    for attempt in range(MAX_TRIES):
        try:
            resp = client.get(url, params=params, timeout=180)
        except httpx.TransportError:
            time.sleep(2**attempt * 3)
            continue
        if resp.status_code == 429 or resp.status_code >= 500:
            time.sleep(int(resp.headers.get("retry-after", 0)) or 2**attempt * 5)
            continue
        resp.raise_for_status()
        return resp
    raise RuntimeError(f"gave up after {MAX_TRIES} tries: {url} {params}")


def usgs_items(client: httpx.Client, collection: str, params: dict[str, str]) -> pl.DataFrame:
    """All features of a USGS OGC collection query, following `next` links, as a flat table."""
    url: str | None = f"{USGS_OGC}/collections/{collection}/items"
    query: dict[str, str] | None = {"f": "json", "limit": "50000", "skipGeometry": "true", **params}
    key = os.environ.get("USGS_API_KEY")
    if key:
        client.headers["X-Api-Key"] = key
    rows: list[dict] = []
    for _ in range(MAX_PAGES):
        if url is None:
            break
        body = get(client, url, query).json()
        rows.extend(f["properties"] for f in body.get("features", []))
        url = next((link["href"] for link in body.get("links", []) if link["rel"] == "next"), None)
        query = None
    else:
        raise RuntimeError(f"more than {MAX_PAGES} pages for {collection} {params}")
    return pl.DataFrame(rows, infer_schema_length=None)


def iem_hads(client: httpx.Client, station: str, start: str, end: str) -> pl.DataFrame:
    """Real-time SHEF values as transmitted, from the IEM HADS/DCP archive, long format.

    Columns: utc (datetime), var (SHEF code such as HGIRGZ), value (float). Empty if nothing archived.
    """
    params = {"stations": station, "sts": start, "ets": end, "what": "txt", "delim": "comma"}
    text = get(client, IEM_HADS, params).text
    if not text.startswith("station"):
        raise RuntimeError(f"unexpected IEM response for {station}: {text[:200]}")
    wide = pl.read_csv(io.StringIO(text), infer_schema_length=0)
    if wide.height == 0:
        return pl.DataFrame(schema={"utc": pl.Datetime, "var": pl.String, "value": pl.Float64})
    return (
        wide.drop("station")
        .unpivot(index="utc_valid", variable_name="var", value_name="value")
        .with_columns(
            pl.col("utc_valid").str.to_datetime("%Y-%m-%d %H:%M:%S").alias("utc"),
            pl.col("value").cast(pl.Float64, strict=False),
        )
        .drop_nulls("value")
        .select("utc", "var", "value")
    )
