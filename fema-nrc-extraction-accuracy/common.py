"""What the four notebooks share: the documents, page text, one typed model call, and the scoring.

Everything here is used by at least two notebooks. Each notebook's own steps stay in its cells.
"""

import asyncio
import hashlib
import io
import json
import os
import re
import threading
import time
import urllib.request
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import pypdfium2 as pdfium
import pytesseract
from pydantic import BaseModel
from pydantic_ai import Agent, BinaryContent
from pydantic_ai.messages import ModelResponse
from pydantic_ai.models.openrouter import OpenRouterModelSettings
from rapidfuzz import fuzz

HERE = Path(__file__).parent
OUT = Path(os.environ.get("FEMA_NRC_OUTPUT_DIR", HERE / "output"))  # downloads and OCR, not committed
PDFIUM = threading.Lock()  # PDFium isn't thread-safe; Tesseract runs in threads
ANSWERS = HERE / "answers"  # model answers, committed so a reviewer can rescore without paying again

# The two models every pipeline is run with: the repo's usual Gemini, and a cheap model from another company.
MODELS = {
    "Gemini 3.8 Flash": "openrouter:google/gemini-3.8-flash",
    "Claude Haiku 5.5": "openrouter:anthropic/claude-haiku-5.5",
}
ATTEMPTS = 4
SETTINGS = OpenRouterModelSettings(temperature=0, max_tokens=16000, openrouter_usage={"include": True})

# FEMA Flood Insurance Studies: every FIS report the Map Service Center listed on 2026-11-01 for 12 counties drawn
# with random.Random(175) from the Census 2024 county gazetteer (1_ocr_share.py shows the draw). A county's search
# also lists neighbouring countywide studies, which are kept.
FIS = {  # product ID: (county drawn, effective date, sha256)
    "35001CV001": ("35039", "04/02/2002", "32d83dee4f1c9dc64f48cf9575f4bf6d37c35250f05b201d2817c41fee673a8a"),
    "35001CV001C": ("35039", "08/16/2012", "6a722fcc836da5da19e14b3e70046efed47f3c9d7ef58cb5f7b02df5fd2c3795"),
    "35001CV001D": ("35039", "11/04/2016", "073c502bda92b2c77c8f8ec29dc574504c685472ca8af1a4783bb9c12a454d32"),
    "35001CV002": ("35039", "04/02/2002", "1cd157ce6301bdd69f6d0fda991890db4ca19878e60d73281a916f1f081e30d7"),
    "35001CV002C": ("35039", "08/16/2012", "1d2401ec8b038089d1e6195644e2638c3e2b958642e999e8ad88d464efcab003"),
    "35001CV002D": ("35039", "11/04/2016", "f946c8d5235173e9a2c8b8f645304322f65d673f30a609d96bea3816d969bc54"),
    "350049V000": ("35039", "08/05/1997", "00ff66e4f040d9cff2b0485adfd26370ae66c2b0c97636fe5096e3edb44fac39"),
    "350050V000": ("35039", "08/05/1997", "4280a86356920921fe0c2daba78df07cdaa5b51c593110c6e224bf504a826c01"),
    "350052V000A": ("35039", "02/16/2006", "0e843194e3bb5a00aa076b1a8cd7fed0a857332caf158b42022dabf40debcde8"),
    "35006CV000A": ("35039", "12/17/2010", "bd4e401d07524cd22675f45da4a3504e2bcaf8650f3576568d5578b8dfabffe0"),
    "35039CV000A": ("35039", "03/15/2012", "d26cb50cc8a722100e8f11b924f7e98a714d3e6fb51695993d10d57648b18a59"),
    "35049CV000A": ("35039", "06/17/2008", "3423cc327b5f38c63e1ba7323ea67428dfd730e1cdb4ce1e92ea2d3191808df8"),
    "35049CV001B": ("35039", "12/04/2012", "638c803d78af1bd4cf7fa88f341ca18894640d6385031970dd4581527e1c501c"),
    "35049CV002B": ("35039", "12/04/2012", "3290d63dc42d9c0120903cd55689c1b5d4c0aa3810f80acbcfab9be446af272f"),
    "35049CV003B": ("35039", "12/04/2012", "fabd67793a878e3de97b23b87599fcd90fe1ce12888294ae06262175b528f1ad"),
    "35053CV000A": ("35039", "05/02/2016", "107cfebc2aa574a3d23b9a4a7d9b332b954e72c5ea7769d0de2f759f096b549b"),
    "20143CV000A": ("20143", "12/21/2023", "3bbbd6b9102eba4d7f499ec0f03c8f710f0770c9534f8fa00feaf011b7bac70f"),
    "060194V000": ("06051", "06/05/1997", "d455ee2a7266f6a774af1a1a3666a28ed7d5ca2487b5cf946f197fea6f957faa"),
    "06051CV000A": ("06051", "02/18/2011", "f8c71ca74d63ab07cfaaf371be2724ff67a2b8fe8b73f76b860ba5656abcab4b"),
    "06051CV000B": ("06051", "12/18/2012", "e1061e594ff09069879ee8862e7cf56d5ca5003e5269be8a2a2cb394442bfc21"),
    "060724V000": ("06051", "09/30/1992", "4eaa85046401b7011c94a654e268c189033fd36f50cc327936ae55c74d3d57d2"),
    "530049V000": ("53025", "09/30/1988", "ede04e286927996b8429d092eecee8c1f5d21e202181ed4d12df52be5f571e79"),
    "530051V000": ("53025", "09/30/1988", "e689da2b7a07f22df01ea70e1719c978ce5f816f246f27bbb869ccc6212dae62"),
    "530053V000": ("53025", "01/05/1989", "d83d555e9a859f48b7f9b6e43898f9cb9dea4e4af9e0b0a061dbcc350952e0cd"),
    "530056V000": ("53025", "07/15/1988", "cf559efb5f4b28a0741a8fd9563b8caf5ca6f5d549a2af15edb7f122fe4d6882"),
    "53025CV000A": ("53025", "02/18/2009", "dd853ef5ba88d9b8000f2cc39f5e72e13e6e080d4eaadc629eceb6499b781dc1"),
    "450126V000": ("45061", "12/15/1990", "bbba3a2fc5c3666a8e9a5c79d5b5d700585f450064766c03c93c759286a74c61"),
    "45061CV000A": ("45061", "11/19/2008", "55cdcfecc58ae9f4ee9d76a3844bc33c533113bc16f185950e6504630edc525a"),
    "510001V000": ("51001", "06/01/1984", "92b0c1793637fa377f4896ee67605eb6e25fdcd05448b9712962305d57c7afc0"),
    "510002V000": ("51001", "06/01/1984", "bc5d27fdb2dcfd8dc77ca93a34c8c1473c369568048dacc97a7f5c8beb8dc094"),
    "510003V000": ("51001", "05/17/1982", "8720fd1a6fb934d4819592d939dfb68f29373c794cec51ef74e17a6d53872cc2"),
    "510004V000": ("51001", "10/15/1982", "4a1f6ac95471e09e4f30fb2784c7e2b0efc866211821480e16d3441abf86e5e5"),
    "510005V000": ("51001", "03/02/1982", "2d532c481bbdddc2b791c90ea61fe3b2729c2fc3b028f225958712f6aaf3f60c"),
    "51001CV000A": ("51001", "03/16/2009", "0662124c36ae0b4a0c355dd4120ce77e5e9ce48deef8310939e198384bc794a0"),
    "51001CV000B": ("51001", "05/18/2015", "c0f3c57523ef65e72423508e3cf6cef32fad53f1fa2976491e39da9832ed4d6b"),
    "510218V000": ("51001", "11/03/1981", "5c897f58e634b715facce8f1c95448e0f73c30bbee89cf6c316bc349c0fbe2f5"),
    "510242V000": ("51001", "06/15/1981", "3b7d8b472f61404bfd7d8709c8283e469cd70352925f51dbaecfcb1dea182588"),
    "510298V000": ("51001", "06/15/1981", "fed63cb94225a437d40babb26b3a340e7608c7d3bb34c78c53a95e752eda9a4b"),
    "510009V000": ("51005", "02/19/1992", "264b6a9f2d232127c52a8677fea51bec7d0810f9242ed6c00af69c4088337507"),
    "510038V000": ("51005", "03/01/1978", "59342d47fa46e9e5d8a2475968ef6f56a86dac8d8ed994591435869a04a101e5"),
    "51005CV000A": ("51005", "12/17/2010", "85a534f278e82e3097ee444064d67d27fdc2724a9a0c240902158e0f4119fd21"),
    "510220V000": ("51005", "01/16/1987", "851e0ae595485511959bdcb46335dfcd7f75d07dba93c7516a4ef6bf0e5123b4"),
    "39029CV000A": ("39029", "04/05/2006", "97af91eda35c72536c9d0aecfac759aff76d3d3363deb82ed9b895a2e75e40f6"),
    "39029CV000B": ("39029", "05/02/2012", "617ab23e81be576016c819b500286261f09681fa4a2dab7f38f086deeb3140b7"),
    "390518V000": ("39029", "01/05/1982", "5257356253f72b7a80a54bb3e45a448c14763db5569e808d63d0460b2708db6b"),
    "39099CV001A": ("39029", "11/18/2009", "be91a3894b8afbb7cd3572837efea99a426d9f947118b9239942a89d6d484fd8"),
    "39099CV002A": ("39029", "11/18/2009", "d72f49e2d24f180594610375b5701d577d6bb2ab9bfce5baa67ecec75da0cc30"),
    "39151CV001A": ("39029", "09/29/2011", "d9516fa756050d37fc434a979fb27f791bafd3249fff8943a0d1cbe2b36a6710"),
    "39151CV001B": ("39029", "02/16/2012", "212b860a8b10cbe2b816f7bd4f8fa4e15deb0c0d2bf7b33065f745204e958264"),
    "39151CV001C": ("39029", "09/14/2018", "695e35a08d9102ec259ef4361d6df6b6fc49bdaec9c89951bfba5f3d8a2000bc"),
    "39151CV002A": ("39029", "09/29/2011", "419b734c08b5944aadef0de8654a711e3828f873a28ddf6fdf9ecac54ba1fdb2"),
    "39151CV002B": ("39029", "02/16/2012", "ad7fc049f0c0239c381f87aa9d65ed2a41c98a6a8b6446c255a030b01b7cdedf"),
    "39151CV002C": ("39029", "09/14/2018", "d5455950360ac5a757dbeb8e380f7f921fbb1563dbad755d5756bf5340912f0a"),
    "39151CV003C": ("39029", "09/14/2018", "36e79a69c790cc5a312987dfe862fdad248340e5f783e00596c82a621bb4690b"),
    "190023V000": ("19017", "07/16/1990", "e58d853707e932e4345b8b2c40f36a52bd823f0cac25d046281770a4d7ed51ae"),
    "19017CV000": ("19017", "07/16/1990", "244f3028ab83150b898dc7809ffd6f1f145f6d43c64ab6a20b33a6cfb51ac73d"),
    "19017CV000A": ("19017", "03/04/2008", "1f0c181e27ddf7db1f6991cdc0efe29fca0f20b93c3c1331a42f754e47017728"),
    "19017CV000B": ("19017", "01/29/2021", "e4cd7c1f081cde1ddc61f80412c5adfda8a1f7c2640aaf3e116303f4c6fd8f03"),
    "21119CV000A": ("21119", "09/16/2015", "2d29a6b718b9970e449e320acb20719e881c84ee4456792e1476f24588f99455"),
    "21119CV000B": ("21119", "08/14/2024", "a83929ac11dd81d91e4aeb7361afeea3fd53b15b37d85e7b932acd219c5744c0"),
    "47013CV000A": ("47013", "09/28/2007", "3e0ebf859e7900efdb14be6226098654c6502b0724a085634b05265f96a7944d"),
    "475431V000": ("47013", "09/30/1992", "97f7cfd0ff1cf420b7baeb383e07ef0705216f9576be961081b5ba46f09d7a2b"),
    "475435V000": ("47013", "03/05/1984", "ea5dd9e837381092b235242d8edf12e552ffe60cd23057e4c454c3153ffa0738"),
    "080172V000": ("08117", "06/20/2001", "7847b2f6ea11a201701f2d25ae1f1cdc2129ad63cba24ba38faf4839fa26c201"),
    "080201V000": ("08117", "08/09/2001", "d96b2f945dd071bedd52b6b30a8fd1fee9998413a4a2e993d4c942e9b8fb50c2"),
    "080245V000": ("08117", "11/02/1994", "88601cadd292de305e3279f58f7b41b3a8e1ff599b67fcf7a1f0b1c8ede61739"),
    "080290V000": ("08117", "08/09/2001", "25c9ea4091cd910915bfc56b5b303993e47fb51216123ba53b6e018c7610dde6"),
    "08117CV000A": ("08117", "11/16/2011", "f76afbe0313dd37f0d6428231c7f99db1af92e346a35ed65f19c6027aabb94ed"),
    "08117CV001B": ("08117", "11/16/2018", "ebeeb23b99f43e05ad271f5ed020fc3109b4850642ad735009d64ab2695b20f3"),
    "08117CV002B": ("08117", "11/16/2018", "4c0e2ec08628de4ca21c52e0fb68c9bd90e3194864746cf03dac94c694e41db3"),
}

# Old NRC reports: 10 drawn with random.Random(175) from the 68 NUREG reports dated 1975-1984 that OSTI lists as
# NRC-sponsored with full text (3_old_nrc_scans.py shows the draw). OSTI serves the same scans NRC holds.
NRC = {  # OSTI ID: (report number, sha256)
    "6623512": ("NUREG/CR-3892 Vol. 4", "ab0018aeb7a00198ce6a74fa94e650247a1e26786056285e1e3b2e9784bca4dc"),
    "5507271": ("NUREG/CR-2405", "33b18c606d2e939fb0217f65c2a75843a856724db2b6c4d853562ab874b125c7"),
    "1083948": ("NUREG/CR-1757", "1a4b4e5285e30b67a038425d2a52d552d2fd7d354dafe0587185d2b7f407f9d3"),
    "10125120": ("NUREG/CR-1322", "966a499f4420ed22a30e6210227ae3b06f52efb4e87b57d2270dfc39282d0871"),
    "5239714": ("BNL-NUREG-29569", "05369a6f808d6535c6dc418968651c720325ab4e11387ff83dab067640fa8a39"),
    "5063304": ("NUREG/CR-2015 Vol. 6", "df03b85275d34cd1467c535c5441d8ff0d2590fdd5b7dfa42f88ddcea0964491"),
    "5777799": ("NUREG/CR-1724", "b9307d4f33cfc0456c9239340f854686745c0ea4fd84bb047f592735a92c7749"),
    "6613275": ("NUREG/CR-1250 Vol. 2 Pt. 1", "86a109b386a27d643f239619a654ca750eeb014d7dc6e22ba43c9eaebc31a90e"),
    "1083928": ("NUREG/CR-2168", "85e0dce4f8e8a2f7365c8c561823d00e3ef3c1f826e78ac2aadacb3ce10364e6"),
    "5533698": ("NUREG/CR-2977", "16a5c6cce6463ab5b885a44fdb5186f56a5a4a0e44401fa8ad31a3e92746bb74"),
}


NUMBER = re.compile(r"\d+(?:[.,]\d+)*")  # a number as the NRC key counts it: digits with any . or , inside


def fetch(url: str, path: Path, sha256: str) -> Path:
    """Download `url` to `path` once, and fail loudly if the file isn't the one the answer key was made from."""
    if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == sha256:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=300) as response:
                data = response.read()
            break
        except OSError as e:
            if attempt == 2:
                raise RuntimeError(f"couldn't download {url}: {e}") from e
            time.sleep(5 * (attempt + 1))
    if (got := hashlib.sha256(data).hexdigest()) != sha256:
        raise RuntimeError(f"{url} has changed since the sample was drawn (sha256 {got})")
    path.write_bytes(data)
    return path


def fis_pdf(product: str) -> Path:
    url = f"https://msc.fema.gov/portal/downloadProduct?productID={product}"
    return fetch(url, OUT / "fis" / f"{product}.pdf", FIS[product][2])


def nrc_pdf(osti_id: str) -> Path:
    return fetch(f"https://www.osti.gov/servlets/purl/{osti_id}", OUT / "nrc" / f"{osti_id}.pdf", NRC[osti_id][1])


def text_layer(pdf: Path, page: int) -> str:
    """The text a PDF carries for a page (1-based), as a text-layer reader would get it."""
    with PDFIUM:
        return pdfium.PdfDocument(pdf)[page - 1].get_textpage().get_text_bounded()


def page_png(pdf: Path, page: int, dpi: int = 150) -> bytes:
    with PDFIUM:
        image = pdfium.PdfDocument(pdf)[page - 1].render(scale=dpi / 72).to_pil().convert("RGB")
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


def tesseract(pdf: Path, page: int) -> tuple[str, float]:
    """Tesseract 5 on the page at 300 dpi, default settings: its text and mean word confidence (0-100). Cached."""
    saved = OUT / "tesseract" / f"{pdf.stem}-p{page}.json"
    if not saved.exists():
        with PDFIUM:
            image = pdfium.PdfDocument(pdf)[page - 1].render(scale=300 / 72).to_pil()
        data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
        words = [(w, float(c)) for w, c in zip(data["text"], data["conf"], strict=True) if w.strip() and float(c) >= 0]
        text = pytesseract.image_to_string(image)
        confidence = sum(c for _, c in words) / len(words) if words else 0.0
        saved.parent.mkdir(parents=True, exist_ok=True)
        saved.write_text(json.dumps({"text": text, "confidence": confidence}))
    stored = json.loads(saved.read_text())
    return stored["text"], stored["confidence"]


async def ask(
    model: str, output_type: type[BaseModel], instructions: str, parts: list[Any], saved: Path, slots: asyncio.Semaphore
) -> dict:
    """One typed model call, or the answer an earlier run saved at `saved`.

    Returns the answer, OpenRouter's cost for every attempt, and the seconds taken. After ATTEMPTS failures it
    returns the error instead, so a failed call is a result to report rather than a crash.
    """
    if saved.exists():
        return json.loads(saved.read_text())
    agent = Agent(model, output_type=output_type, instructions=instructions, retries=2)
    spent = {"usd": 0.0, "seconds": 0.0, "failed_attempts": 0, "error": ""}
    async with slots:
        for attempt in range(ATTEMPTS):
            t0 = time.time()
            try:
                result = await agent.run(parts, model_settings=SETTINGS)
            except Exception as e:  # rate limits, network errors, output that failed the schema after retries
                spent["seconds"] += time.time() - t0
                spent["failed_attempts"] += 1
                spent["error"] = f"{type(e).__name__}: {e!s:.200}"
                print(f"{saved.relative_to(ANSWERS)}: attempt {attempt + 1} failed: {spent['error']}")
                await asyncio.sleep(10 * (attempt + 1))
                continue
            spent["seconds"] += time.time() - t0
            spent["usd"] += sum(
                float((m.provider_details or {}).get("cost") or 0)
                for m in result.new_messages()
                if isinstance(m, ModelResponse)
            )
            assert isinstance(result.output, BaseModel), "the model answered with text, not the schema"
            answer = {"output": result.output.model_dump(mode="json"), **spent, "error": ""}
            break
        else:
            answer = {"output": None, **spent}
    saved.parent.mkdir(parents=True, exist_ok=True)
    saved.write_text(json.dumps(answer, indent=1))
    return answer


def image(png: bytes) -> BinaryContent:
    return BinaryContent(png, media_type="image/png")


def norm(value: Any) -> str:
    """A value in a form that compares fairly: numbers by value, dashes and asterisks as blank, text loosely.

    From messy-document-parsing/pipelines.py, trimmed to what these documents need.
    """
    text = re.sub(r"\s+", "", str(value)).lower().replace("−", "-").replace("–", "-").replace("—", "-")
    if re.fullmatch(r"[-.…_*]*|n/?a|notdetermined", text):
        return ""
    number = re.fullmatch(r"(-?)\$?(\d[\d,]*\.?\d*|\.\d+)%?", text)
    if number:
        try:
            amount = Decimal(number.group(2).replace(",", ""))
        except InvalidOperation:
            return text
        return "#" + format((-amount if number.group(1) else amount).normalize(), "f")
    return re.sub(r"[^a-z0-9.%]+", "", text)


def same(found: Any, key: Any) -> bool:
    f, k = norm(found), norm(key)
    if f.startswith("#") or k.startswith("#") or not f or not k:
        return f == k
    return fuzz.ratio(f, k) >= 85
