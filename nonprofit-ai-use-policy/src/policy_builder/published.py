"""Measure published AI policy templates the same way as our policies: PDF pages, words and reading level.

The PDFs are downloaded when this runs and cached outside git; they are not ours to commit.
"""

from pathlib import Path

import requests
from pydantic import BaseModel
from pypdf import PdfReader
from textstat import textstat

from policy_builder.checks import ensure_syllable_dictionary

PUBLISHED = {
    "NTEN Generative AI Use Policy template (2024)": "https://word.nten.org/wp-content/uploads/2024/07/GAI-Policy-Template.pdf",
    "Community IT acceptable use of AI tools template (2026)": "https://communityit.com/wp-content/uploads/2026/05/Template-Acceptable-Use-of-AI-Tools-in-the-Nonprofit-Workplace-2026.pdf",
    "Fundraising.AI nonprofit governance policy template (2025)": "https://fundraising.ai/wp-content/uploads/2025/06/FAI_-Nonprofit-Governance-Policy-Template-vF.pdf",
    "Center for Nonprofit AI policy template": "https://centerfornonprofitai.org/downloads/CNAI-Nonprofit-AI-Policy-Template.pdf",
    "Vermont guidelines for use of generative AI (2026)": "https://digitalservices.vermont.gov/sites/digitalservices/files/documents/Guidelines_for_Use_of_Generative_AI_Updated.pdf",
    "Indiana AI policy v1.1 (2024)": "https://www.in.gov/dA/878cfc28c3/State-of-Indiana-Artificial-Intelligence-Policy.pdf?language_id=1",
}


class PdfMeasure(BaseModel):
    document: str
    pages: int
    words: int
    flesch_kincaid_grade: float
    flesch_reading_ease: float


def download(url: str, cache: Path) -> Path:
    path = cache / url.split("?")[0].rsplit("/", 1)[-1]
    if not path.exists():
        response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
        response.raise_for_status()
        cache.mkdir(parents=True, exist_ok=True)
        path.write_bytes(response.content)
    return path


def measure_pdf(document: str, path: Path) -> PdfMeasure:
    """Extract text with pypdf and score it as one block, the same way for every PDF."""
    ensure_syllable_dictionary()
    reader = PdfReader(path)
    text = " ".join((page.extract_text() or "") for page in reader.pages)
    return PdfMeasure(
        document=document,
        pages=len(reader.pages),
        words=textstat.lexicon_count(text),
        flesch_kincaid_grade=round(textstat.flesch_kincaid_grade(text), 1),
        flesch_reading_ease=round(textstat.flesch_reading_ease(text), 1),
    )


def measure_published(cache: Path) -> list[PdfMeasure]:
    measures = []
    for document, url in PUBLISHED.items():
        try:
            measures.append(measure_pdf(document, download(url, cache)))
        except requests.RequestException as error:
            print(f"Skipped {document}: {error}")
    return measures
