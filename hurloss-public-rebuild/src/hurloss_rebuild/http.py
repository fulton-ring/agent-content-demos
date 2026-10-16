"""Downloads with a bounded number of retries."""

from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

RETRIES = 5
CHUNK = 8 << 20


def session() -> requests.Session:
    retry = Retry(
        total=RETRIES, backoff_factor=2, status_forcelist=(500, 502, 503, 504), allowed_methods=None
    )
    client = requests.Session()
    client.mount("https://", HTTPAdapter(max_retries=retry))
    return client


def download(url: str, target: Path, timeout: int = 600) -> Path:
    """Stream `url` to `target` unless it is already there; fail on any HTTP error."""
    if target.exists():
        return target
    partial = target.with_suffix(target.suffix + ".partial")
    with session().get(url, stream=True, timeout=timeout) as response:
        response.raise_for_status()
        with partial.open("wb") as handle:
            for block in response.iter_content(chunk_size=CHUNK):
                handle.write(block)
    if partial.stat().st_size == 0:
        raise RuntimeError(f"empty download from {url}")
    partial.rename(target)
    return target
