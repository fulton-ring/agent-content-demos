"""STORM synthetic tracks (Bloemendaal et al.), North Atlantic, from 4TU.ResearchData (CC0).

- Present climate: STORM v4, 10,000 years resampled from IBTrACS 1980-2018
  (doi:10.4121/12706085.v4).
- Future climate: SSP5-8.5 2015-2050, four high-resolution GCMs, as deltas on IBTrACS
  (doi:10.4121/14237678.v2).

Each 1,000-year North Atlantic text file is read straight out of the published zip with HTTP
range requests (`remotezip`), so the other basins are never downloaded.
"""

from pathlib import Path
from zipfile import ZipInfo

from remotezip import RemoteZip

from hurloss_rebuild import http
from hurloss_rebuild.paths import cache_path

PRESENT_ZIP = (
    "https://data.4tu.nl/file/01b2ebc7-7903-42ef-b46b-f43b9175dbf4/"
    "78b72e86-b074-4478-9dc4-7280deb756ab"
)
FUTURE_ZIPS = {
    "CMCC-CM2-VHR4": "bdc3820c-7b7e-41de-8def-792f50b06c49",
    "CNRM-CM6-1-HR": "3b08e6a8-2824-435f-a141-9509a9922cfe",
    "EC-Earth3P-HR": "2eaeb5f6-40f3-4f94-9f9c-ca7aad3237fc",
    "HadGEM3-GC31-HM": "f35142d6-d858-4874-9a51-2dc08462d45f",
}
FUTURE_DATASET = "https://data.4tu.nl/file/98900e17-8e01-4d70-b3b6-ca1a1da2f194/"
YEARS_PER_FILE = 1000
FILES_PER_SET = 10


def member_name(model: str | None, index: int) -> str:
    """File name inside the zip for one 1,000-year North Atlantic sample."""
    if not 0 <= index < FILES_PER_SET:
        raise ValueError(f"STORM sample index out of range: {index}")
    if model is None:
        return f"STORM_DATA_IBTRACS_NA_1000_YEARS_{index}.txt"
    return f"STORM_DATA_{model}_NA_1000_YEARS_{index}_IBTRACSDELTA.txt"


def find_member(archive: RemoteZip, name: str) -> ZipInfo:
    matches = [
        i for i in archive.infolist() if i.filename == name or i.filename.endswith("/" + name)
    ]
    if len(matches) != 1:
        raise RuntimeError(f"{name} not found once in the STORM zip")
    return matches[0]


def fetch_all(model: str | None, files: int) -> list[Path]:
    """The first `files` 1,000-year NA files of one climate, cached locally.

    Missing files come out of one zip session, so 4TU sees one directory read per climate
    rather than one per file.
    """
    if not 1 <= files <= FILES_PER_SET:
        raise ValueError(f"STORM files out of range: {files}")
    targets = [cache_path("storm", member_name(model, index)) for index in range(files)]
    missing = [target for target in targets if not target.exists()]
    if not missing:
        return targets
    url = PRESENT_ZIP if model is None else FUTURE_DATASET + FUTURE_ZIPS[model]
    with RemoteZip(url, session=http.session()) as archive:
        for target in missing:
            partial = target.with_suffix(".partial")
            partial.write_bytes(archive.read(find_member(archive, target.name)))
            partial.rename(target)
    return targets
