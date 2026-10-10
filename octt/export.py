# OpenCTT - course timetabler. Derived from OpenCTT by Ivan Ćurak.
# This program is free software; you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation; either version 2 of
# the License, or (at your option) any later version. See the LICENSE file.
"""Reports -> .pdf / .html / .xlsx, chosen by the file extension. XLSX is written by hand (zip + XML): one sheet per page, tables only."""
import re
import zipfile
from dataclasses import dataclass
from html import escape
from html.parser import HTMLParser
from pathlib import Path

from octt.i18n import is_rtl
from octt.reports import Page, to_html

FORMATS = "PDF (*.pdf);;HTML (*.html);;Excel (*.xlsx)"


@dataclass
class Style:
    font: str = ""  # "" = the bundled font of the current language
    size: float = 0  # pt; 0 = the default (8 PDF, 10 HTML, 11 Excel)
    header: str = "#e8e8e8"  # background of table headers
    colors: bool = True  # lessons keep their course colour
    borders: bool = True


def restyle(html: str, st: Style) -> str:
    """The reports hard-code their look as HTML attributes; swap those for the chosen style."""
    html = html.replace("bgcolor='#e8e8e8'", f"bgcolor='{st.header}'")
    if not st.colors:
        html = re.sub(r"(<td[^>]*?) bgcolor='[^']*'", r"\1", html)
        html = re.sub(r" style='background-color:[^']*'", "", html)
    return html if st.borders else html.replace("border='1'", "border='0'")


class _Rows(HTMLParser):
    """Collects the text of every <tr><td|th> in a page body; <br> becomes a line break."""

    def __init__(self):
        super().__init__()
        self.rows, self.cell, self.bg = [], None, None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.rows.append([])
        elif tag in ("td", "th"):
            self.cell, self.bg = [], dict(attrs).get("bgcolor")
        elif tag == "br" and self.cell is not None:
            self.cell.append("\n")

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None:
            self.rows[-1].append(("".join(self.cell).strip(), self.bg))
            self.cell = None

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)


def _col(i: int) -> str:
    return (_col(i // 26 - 1) if i >= 26 else "") + chr(65 + i % 26)


def _sheet(page: Page, st: Style, fills: list[str]) -> str:
    """fills collects the distinct background colours. Style ids: 1 title text, 2 table cell, 3 + i table cell filled with fills[i]."""
    p = _Rows()
    p.feed(page.body)
    rows = [[(page.title, None)], [(re.sub("<[^>]+>", "", page.subtitle), None)], []] + p.rows

    xml = ""
    for r, row in enumerate(rows, 1):
        xml += f'<row r="{r}">'
        for c, (v, bg) in enumerate(row):
            bg = st.header if bg == "#e8e8e8" else bg
            if r <= 2:
                sid = 1
            elif bg and (st.colors or bg == st.header):
                if bg not in fills:
                    fills.append(bg)
                sid = 3 + fills.index(bg)
            else:
                sid = 2
            xml += f'<c r="{_col(c)}{r}" s="{sid}" t="inlineStr"><is><t xml:space="preserve">{escape(v)}</t></is></c>'
        xml += "</row>"
    rtl = ' rightToLeft="1"' if is_rtl() else ""
    return ('<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<sheetViews><sheetView workbookViewId="0"{rtl}/></sheetViews><cols><col min="1" max="30" width="22" customWidth="1"/></cols>'
            f"<sheetData>{xml}</sheetData></worksheet>")


def write_xlsx(pages: list[Page], path: str, st: Style = Style()) -> None:
    fills: list[str] = []
    sheets = [_sheet(p, st, fills) for p in pages]  # first: this fills `fills`, which styles.xml needs
    names = []
    for i, p in enumerate(pages, 1):  # sheet names: <= 31 chars, no []:*?/\, unique
        base = re.sub(r"[\[\]:*?/\\]", " ", re.sub("<[^>]+>", "", p.title)).strip()[:25] or "Sheet"
        names.append(f"{base} {i}")
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    n = len(pages)
    parts = {
        "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            + "".join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                      for i in range(1, n + 1)) + "</Types>",
        "_rels/.rels": '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Id="rId1" Type="{rel}/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        "xl/workbook.xml": f'<?xml version="1.0" encoding="UTF-8"?><workbook {ns} xmlns:r="{rel}"><sheets>'
            + "".join(f'<sheet name="{escape(nm)}" sheetId="{i}" r:id="rId{i}"/>' for i, nm in enumerate(names, 1)) + "</sheets></workbook>",
        "xl/_rels/workbook.xml.rels": '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + "".join(f'<Relationship Id="rId{i}" Type="{rel}/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1, n + 1))
            + f'<Relationship Id="rId{n + 1}" Type="{rel}/styles" Target="styles.xml"/></Relationships>',
        "xl/styles.xml": f'<?xml version="1.0" encoding="UTF-8"?><styleSheet {ns}>'
            f'<fonts count="1"><font><sz val="{st.size or 11:g}"/><name val="{escape(st.font or "Arial")}"/></font></fonts>'
            '<fills count="%d"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>' % (2 + len(fills))
            + "".join(f'<fill><patternFill patternType="solid"><fgColor rgb="FF{c.lstrip("#").upper()}"/></patternFill></fill>' for c in fills)
            + '</fills><borders count="2"><border/><border><left style="thin"/><right style="thin"/><top style="thin"/><bottom style="thin"/></border></borders>'
            '<cellStyleXfs count="1"><xf/></cellStyleXfs><cellXfs count="%d"><xf/>' % (3 + len(fills))
            + '<xf applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>'
            + f'<xf borderId="{int(st.borders)}" applyBorder="1" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>'
            + "".join(f'<xf fillId="{i + 2}" borderId="{int(st.borders)}" applyFill="1" applyBorder="1" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>'
                      for i in range(len(fills))) + "</cellXfs></styleSheet>",
        **{f"xl/worksheets/sheet{i}.xml": x for i, x in enumerate(sheets, 1)},
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in parts.items():
            z.writestr(name, data)


def write_html(pages: list[Page], path: str, st: Style = Style()) -> None:
    body = restyle("".join(to_html(p, i == 0) for i, p in enumerate(pages)), st)
    fonts = ", ".join(([f"'{st.font}'"] if st.font else []) + ["Inter", "Cairo", "sans-serif"])
    line = "1px solid #888" if st.borders else "0"
    Path(path).write_text(
        f'<!doctype html><html dir="{"rtl" if is_rtl() else "ltr"}"><meta charset="utf-8"><title>{pages[0].title}</title>'
        f"<style>body{{font-family:{fonts};font-size:{st.size or 10:g}pt}}table{{border-collapse:collapse}}"
        f"td,th{{border:{line};padding:4px;vertical-align:top}}h2{{margin-top:2em}}</style><body>" + body, encoding="utf-8")


def write(pages: list[Page], path: str, st: Style = Style()) -> None:
    """Format from the extension (.pdf default)."""
    if not pages:
        raise ValueError("nothing to print")
    ext = Path(path).suffix.lower()
    if ext == ".html":
        write_html(pages, path, st)
    elif ext == ".xlsx":
        write_xlsx(pages, path, st)
    else:
        from octt.pdf import write_pdf  # Qt only when needed
        write_pdf(pages, path, st)
