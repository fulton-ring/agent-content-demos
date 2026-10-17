"""Download the blank IRS Schedule K-1 forms from irs.gov.

generate.py fills the 1120-S and 1041 forms with made-up values, and extract.py and
extract_vlm.py line scanned K-1s up with all of them for their box labels. They come
from the IRS's prior-year archive, whose files don't change, and each is hash-checked
so the box positions the code relies on still apply.
"""

import hashlib
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
FORMS = HERE / "forms"
IRS_PRIOR = "https://www.irs.gov/pub/irs-prior/"
# Local name: (name in the IRS archive, sha256)
SOURCES = {
    "f1065sk1--2018.pdf": ("f1065sk1--2018.pdf", "e6a1f9aa1a738d05e393e5160532456d9075a606c717f1193743ebdbaf7714a3"),
    "f1065sk1--2019.pdf": ("f1065sk1--2019.pdf", "d4ce03905cfc7254f6eaf74403085fcbf06f0f6e6041e18351c1b4363fa34d20"),
    "f1065sk1--2021.pdf": ("f1065sk1--2021.pdf", "0b400f0a6fb9b7897e69aedd4fbde5d610ea0f609680972791cd3adff38479b8"),
    "f1065sk1.pdf": ("f1065sk1--2025.pdf", "66098d4d48537ce2dac1f093d6351567957896e5843d8c524823b380068f6547"),
    "f1120ssk.pdf": ("f1120ssk--2025.pdf", "104ac7b1137cb78c9051d4e3424630dca233887f17928b311fef6fd578baacd0"),
    "f1041sk1.pdf": ("f1041sk1--2025.pdf", "d8d7b6eacabdf145474aee8385fcfeafe68bd2f69baaef52d9a8227ebcd45fc3"),
}


def download_checked(path: Path, url: str, sha: str) -> None:
    """Download url to path unless path already holds the file with this sha256. Exits if the file has changed."""
    if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == sha:
        return
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    data = urllib.request.urlopen(req, timeout=60).read()
    got = hashlib.sha256(data).hexdigest()
    if got != sha:
        sys.exit(f"{path.name}: the file at {url} has changed (sha256 {got}); this demo was built against a different file")
    path.write_bytes(data)


def main() -> None:
    FORMS.mkdir(exist_ok=True)
    for name, (remote, sha) in SOURCES.items():
        download_checked(FORMS / name, IRS_PRIOR + remote, sha)
        print(f"forms/{name}: ok")


if __name__ == "__main__":
    main()
