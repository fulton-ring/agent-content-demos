"""Settings and file helpers shared by the three notebooks."""

import hashlib
import logging
import os
import pickle
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests
from numpy.lib import format as npy_format
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("storm")

HERE = Path(__file__).parent
CACHE = Path(os.environ.get("STORM_CACHE", Path.home() / ".cache" / "storm-yearly-regeneration"))
RESULTS = Path(os.environ.get("STORM_RESULTS", HERE / "results"))
WORKERS = int(os.environ.get("STORM_WORKERS", os.cpu_count() or 1))
# Synthetic years, in 1,000-year files as STORM publishes them, and the base seed.
YEARS = int(os.environ.get("STORM_YEARS", "10000"))
SEED = int(os.environ.get("STORM_SEED", "1"))
assert WORKERS >= 1, "STORM_WORKERS must be at least 1"
assert YEARS >= 1000 and YEARS % 1000 == 0, "STORM_YEARS must be a multiple of 1,000"


def cached(*parts: str) -> Path:
    """A path in the download cache, with its folder created."""
    path = CACHE.joinpath(*parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def session() -> requests.Session:
    """HTTP with bounded retries and backoff for rate limits and server errors."""
    retry = Retry(
        total=6,
        backoff_factor=5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=None,
        respect_retry_after_header=True,
    )
    client = requests.Session()
    client.mount("https://", HTTPAdapter(max_retries=retry))
    return client


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def download(url: str, target: Path) -> Path:
    """Fetch `url` to `target` once; later calls reuse the file."""
    if target.exists():
        return target
    log.info("downloading %s", url)
    response = session().get(url, timeout=300)
    response.raise_for_status()
    assert response.content, f"{url} returned an empty body"
    target.with_suffix(".partial").write_bytes(response.content)
    target.with_suffix(".partial").rename(target)
    return target


def write(table: pd.DataFrame, name: str, index: bool = False) -> None:
    """Save a result table under RESULTS."""
    path = RESULTS / name
    path.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(path, index=index, float_format="%.6g")


class _NumpyOnly(pickle.Unpickler):
    """Unpickles only NumPy arrays, dicts and lists, so a downloaded file can't run code."""

    allowed = {
        ("numpy.core.multiarray", "_reconstruct"),
        ("numpy._core.multiarray", "_reconstruct"),
        ("numpy.core.multiarray", "scalar"),
        ("numpy._core.multiarray", "scalar"),
        ("numpy", "ndarray"),
        ("numpy", "dtype"),
        ("_codecs", "encode"),
    }

    def find_class(self, module: str, name: str) -> object:
        if (module, name) not in self.allowed:
            raise pickle.UnpicklingError(f"refusing {module}.{name} in a downloaded .npy")
        return super().find_class(module, name)


def read_pickled_npy(path: Path) -> Any:
    """What STORM's pickled `.npy` files hold (a dict of lists or arrays), read safely."""
    with path.open("rb") as handle:
        version = npy_format.read_magic(handle)
        reader = (
            npy_format.read_array_header_1_0
            if version == (1, 0)
            else npy_format.read_array_header_2_0
        )
        _shape, _fortran, dtype = reader(handle)
        if not dtype.hasobject:
            return np.load(path)
        array = _NumpyOnly(handle, encoding="latin1").load()
    assert isinstance(array, np.ndarray) and array.shape == (), f"{path} is not a pickled dict"
    return array.item()
