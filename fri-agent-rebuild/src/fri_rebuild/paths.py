"""Where downloaded inputs and intermediate files live (outside the repo)."""

import os
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[2]
RESULTS_DIR = PROJECT_DIR / "results"
HAZARDS_DIR = PROJECT_DIR / "hazards"
EXPERIMENTS_DIR = PROJECT_DIR / "experiments"


def cache_dir() -> Path:
    """Root cache directory, overridable with FRI_CACHE."""
    root = Path(os.environ.get("FRI_CACHE", Path.home() / ".cache" / "fri-agent-rebuild"))
    root.mkdir(parents=True, exist_ok=True)
    return root


def cache_path(*parts: str) -> Path:
    """A path inside the cache, creating its parent directory."""
    path = cache_dir().joinpath(*parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
