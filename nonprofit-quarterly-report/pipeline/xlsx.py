"""Minimal .xlsx reader and writer using only the standard library.

Enough to write the sample site spreadsheets and to read back what Excel,
Google Sheets or LibreOffice save: one or more sheets of plain values,
shared or inline strings, numbers. Formatting and formulas are ignored
(a formula cell is read as its cached value).
"""

import re
import zipfile
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


def _col_letter(i):
    s = ""
    i += 1
    while i:
        i, rem = divmod(i - 1, 26)
        s = chr(65 + rem) + s
    return s


def _col_index(ref):
    letters = re.match(r"[A-Z]+", ref).group(0)
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n - 1


def write_xlsx(path, sheets):
    """sheets: list of (sheet_name, rows); each row is a list of str/int/float/None."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        class Z:  # fixed timestamps so the same data always gives the same file
            @staticmethod
            def writestr(name, data):
                zf.writestr(zipfile.ZipInfo(name, (2025, 1, 1, 0, 0, 0)), data, zipfile.ZIP_DEFLATED)
        z = Z
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   + "".join(f'<Override PartName="/xl/worksheets/sheet{i + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                             for i in range(len(sheets)))
                   + "</Types>")
        z.writestr("_rels/.rels",
                   f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="{REL_NS}">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                   "</Relationships>")
        z.writestr("xl/workbook.xml",
                   f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="{NS["m"]}" xmlns:r="{NS["r"]}"><sheets>'
                   + "".join(f'<sheet name="{escape(name)}" sheetId="{i + 1}" r:id="rId{i + 1}"/>' for i, (name, _) in enumerate(sheets))
                   + "</sheets></workbook>")
        z.writestr("xl/_rels/workbook.xml.rels",
                   f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="{REL_NS}">'
                   + "".join(f'<Relationship Id="rId{i + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i + 1}.xml"/>'
                             for i in range(len(sheets)))
                   + "</Relationships>")
        for i, (_, rows) in enumerate(sheets):
            out = [f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="{NS["m"]}"><sheetData>']
            for r, row in enumerate(rows):
                out.append(f'<row r="{r + 1}">')
                for c, v in enumerate(row):
                    if v is None or v == "":
                        continue
                    ref = f"{_col_letter(c)}{r + 1}"
                    if isinstance(v, (int, float)) and not isinstance(v, bool):
                        out.append(f'<c r="{ref}"><v>{v}</v></c>')
                    else:
                        out.append(f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(v))}</t></is></c>')
                out.append("</row>")
            out.append("</sheetData></worksheet>")
            z.writestr(f"xl/worksheets/sheet{i + 1}.xml", "".join(out))


def read_xlsx(path, sheet=0):
    """Return the rows of one sheet (by index or name) as lists of str/float/None."""
    with zipfile.ZipFile(path) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in root.findall("m:si", NS):
                shared.append("".join(t.text or "" for t in si.iter(f"{{{NS['m']}}}t")))
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        targets = {r.get("Id"): r.get("Target") for r in rels}
        entries = wb.findall("m:sheets/m:sheet", NS)
        entry = entries[sheet] if isinstance(sheet, int) else next(e for e in entries if e.get("name") == sheet)
        target = targets[entry.get(f"{{{NS['r']}}}id")].lstrip("/")
        if not target.startswith("xl/"):
            target = "xl/" + target
        root = ET.fromstring(z.read(target))
    rows = []
    for row in root.iter(f"{{{NS['m']}}}row"):
        r = int(row.get("r")) - 1
        while len(rows) <= r:
            rows.append([])
        cells = rows[r]
        for c in row.findall("m:c", NS):
            idx = _col_index(c.get("r"))
            t = c.get("t")
            if t == "inlineStr":
                val = "".join(x.text or "" for x in c.iter(f"{{{NS['m']}}}t"))
            else:
                v = c.find("m:v", NS)
                if v is None or v.text is None:
                    val = None
                elif t == "s":
                    val = shared[int(v.text)]
                elif t in ("str", "b", "e"):
                    val = v.text
                else:
                    val = float(v.text)
            while len(cells) <= idx:
                cells.append(None)
            cells[idx] = val
    return rows
