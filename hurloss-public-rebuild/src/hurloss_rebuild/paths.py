"""Where downloaded inputs and intermediate files live (outside the repo), and where results go."""

import os
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[2]


def results_dir() -> Path:
    """Output folder, overridable with HURLOSS_RESULTS."""
    root = Path(os.environ.get("HURLOSS_RESULTS", PROJECT_DIR / "results"))
    root.mkdir(parents=True, exist_ok=True)
    return root


def cache_dir() -> Path:
    """Root cache directory, overridable with HURLOSS_CACHE."""
    default = Path.home() / ".cache" / "hurloss-public-rebuild"
    root = Path(os.environ.get("HURLOSS_CACHE", default))
    root.mkdir(parents=True, exist_ok=True)
    return root


def cache_path(*parts: str) -> Path:
    """A path inside the cache, creating its parent directory."""
    path = cache_dir().joinpath(*parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
