"""Downloads with a bounded number of retries."""

from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

RETRIES = 8
CHUNK = 8 << 20


def session() -> requests.Session:
    # 429 is 4TU's rate limit; urllib3 waits for the server's Retry-After before retrying.
    retry = Retry(
        total=RETRIES,
        backoff_factor=10,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=None,
        respect_retry_after_header=True,
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
