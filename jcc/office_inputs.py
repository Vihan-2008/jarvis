"""Reading Word, PowerPoint, Excel and OpenDocument files without running anything in them: the words (slide by slide for a
deck), the pictures in them (PNG and JPEG, in the order they appear), and charts and SmartArt written out as text.

These files are zip archives of XML. Only named parts are read; every part is size-checked; XML that declares a DTD or
entities is refused; a relationship may only point inside the archive (an external link is ignored).
"""
from __future__ import annotations

import hashlib
import io
import posixpath
import re
import zipfile
import xml.etree.ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
C = "{http://schemas.openxmlformats.org/drawingml/2006/chart}"
V = "{urn:schemas-microsoft-com:vml}"
REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"

MOST_ENTRIES, MOST_EXPANDED, MOST_PART = 3000, 100_000_000, 20_000_000
MOST_PICTURES, PICTURE_BYTES, MOST_PIXELS = 20, 5_000_000, 20_000_000
SLIDES = 300


class OfficeError(ValueError):
    pass


class Package:
    def __init__(self, name: str, data: bytes):
        self.name = name
        try:
            self.zip = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile:
            raise OfficeError(f"{name} could not be opened. The file may be damaged.") from None
        entries = self.zip.infolist()
        if len(entries) > MOST_ENTRIES or sum(i.file_size for i in entries) > MOST_EXPANDED or any(
                i.file_size > MOST_PART and i.filename.endswith(".xml") for i in entries):
            raise OfficeError(f"{name} unpacks to far more than its size, so JARVIS did not open it.")
        self.names = {i.filename for i in entries}

    def read(self, part: str) -> bytes | None:
        if part not in self.names:
            return None
        info = self.zip.getinfo(part)
        if info.file_size > MOST_PART:
            return None
        return self.zip.read(part)

    def xml(self, part: str):
        content = self.read(part)
        if content is None:
            return None
        if b"<!DOCTYPE" in content or b"<!ENTITY" in content:
            raise OfficeError("Document entities are unsupported.")
        try:
            return ET.fromstring(content)
        except ET.ParseError:
            return None

    def rels(self, part: str) -> dict[str, tuple[str, str]]:
        """A part's relationships: id -> (type ending, the part it points to inside the archive)."""
        folder, base = posixpath.split(part)
        root = self.xml(posixpath.join(folder, "_rels", base + ".rels"))
        found = {}
        for rel in (root.iter(REL + "Relationship") if root is not None else []):
            target = rel.get("Target") or ""
            if rel.get("TargetMode") == "External" or not target or re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I):
                continue
            where = posixpath.normpath(target.lstrip("/") if target.startswith("/") else posixpath.join(folder, target))
            if where.startswith("..") or where.startswith("/"):
                continue
            found[rel.get("Id") or ""] = ((rel.get("Type") or "").rsplit("/", 1)[-1], where)
        return found


class Reading:
    """What came out of a document: its text (with [picture-NN.ext] where each picture belongs) and the pictures."""

    def __init__(self, name: str):
        self.name, self.lines, self.pictures, self.charts = name, [], [], 0
        self.skipped_format = self.skipped_small = self.over = 0
        self.count, self.unit, self.kind = None, "page", ""
        self._seen_parts, self._seen_hashes = {}, set()

    def picture(self, package: Package, part: str) -> str:
        """Take the picture at this part (once); returns the marker to put in the text, or "" if it was left out."""
        if part in self._seen_parts:
            return self._seen_parts[part]
        from jcc.image_inputs import dimensions
        data = package.read(part) or b""
        marker = ""
        kind = ".png" if data.startswith(b"\x89PNG\r\n\x1a\n") else ".jpg" if data.startswith(b"\xff\xd8") else ""
        if not kind:
            if data:
                self.skipped_format += 1
        elif len(data) <= PICTURE_BYTES:
            try:
                width, height = dimensions(data, kind)
            except ValueError:
                width = height = 0
            digest = hashlib.sha256(data).hexdigest()
            if not width or width * height > MOST_PIXELS:
                self.skipped_format += 1
            elif min(width, height) < 100 or width * height < 20_000 or max(width, height) > 8 * min(width, height):
                self.skipped_small += 1                       # (icons, bullets, lines and borders)
            elif digest in self._seen_hashes:
                pass                                          # (the same picture again, such as a logo on every slide)
            elif len(self.pictures) >= MOST_PICTURES:
                self.over += 1
            else:
                self._seen_hashes.add(digest)
                file = f"picture-{len(self.pictures) + 1:02d}{kind}"
                self.pictures.append((file, data))
                marker = f"[{file}]"
        self._seen_parts[part] = marker
        return marker


def _text(element, tag=A + "t") -> str:
    return "".join(t.text or "" for t in element.iter(tag))


def _chart(package: Package, part: str) -> str:
    """A chart written out: its title, then each series with its categories and values (as the file last saved them)."""
    root = package.xml(part)
    if root is None:
        return ""
    title = next((" ".join(_text(t).split()) for t in root.iter(C + "title")), "")
    rows = []
    for series in root.iter(C + "ser"):
        label = " ".join("".join(v.text or "" for v in tx.iter(C + "v")) for tx in series.iter(C + "tx")).strip()
        cats = [v.text or "" for cat in series.iter(C + "cat") for v in cat.iter(C + "v")]
        vals = [v.text or "" for val in series.iter(C + "val") for v in val.iter(C + "v")]
        pairs = ", ".join(f"{c} {v}".strip() for c, v in zip(cats or [""] * len(vals), vals))
        if not vals:                                   # (no numbers saved with the chart: where they come from)
            source = next((f.text for val in series.iter(C + "val") for f in val.iter(C + "f") if f.text), "")
            pairs = f"its numbers are the cells {source}" if source else "no numbers were saved with it"
        rows.append(f"- {label or 'Series'}: {pairs[:1500]}")
    return ("Chart" + (f": {title}" if title else "") + "\n" + "\n".join(rows[:20])).strip()


def _docx(package: Package, reading: Reading) -> None:
    reading.kind = "docx"
    part = "word/document.xml"
    root = package.xml(part)
    if root is None:
        raise OfficeError(f"{package.name} could not be opened. The file may be damaged.")
    rels = package.rels(part)
    if root.find(f".//{W}p") is None:                  # (Strict Open XML names things differently: its words, at least)
        reading.lines.append("\n".join(t.strip() for t in root.itertext() if t.strip()))

    def paragraph_line(paragraph) -> str:
        words = "".join(t.text or "" for t in paragraph.iter(W + "t")).strip()
        marks = []
        for ref in [b.get(R + "embed") for b in paragraph.iter(A + "blip")] + [v.get(R + "id") for v in paragraph.iter(V + "imagedata")]:
            if ref in rels and rels[ref][0] == "image":
                marker = reading.picture(package, rels[ref][1])
                if marker:
                    marks.append(marker)
        for ref in [c.get(R + "id") for c in paragraph.iter(C + "chart")]:
            if ref in rels and rels[ref][0] == "chart":
                chart = _chart(package, rels[ref][1])
                if chart:
                    reading.charts += 1
                    marks.append(chart)
        return " ".join([words] + marks).strip()

    def add(line: str) -> None:
        if line and (not reading.lines or reading.lines[-1] != line):
            reading.lines.append(line)

    body = root.find(W + "body")
    for block in (list(body) if body is not None else []):
        if block.tag == W + "p":
            add(paragraph_line(block))
        elif block.tag == W + "tbl":                   # (a table, row by row: "Region | Sales")
            rows = []
            for row in block.iter(W + "tr"):
                cells = [" ".join(filter(None, (paragraph_line(p) for p in cell.iter(W + "p")))) for cell in row.findall(W + "tc")]
                if any(cells):
                    rows.append(" | ".join(cells))
            add("\n".join(rows))
        else:                                          # (content controls and the like: their paragraphs in order)
            for paragraph in block.iter(W + "p"):
                add(paragraph_line(paragraph))
    for diagram in sorted(n for n in package.names if re.fullmatch(r"word/diagrams/data\d+\.xml", n)):
        tree = package.xml(diagram)
        if tree is not None:
            words = " · ".join(w for w in (" ".join(t.text.split()) for t in tree.iter(A + "t") if t.text) if w)
            if words:
                reading.lines.append("Diagram: " + words)


def _pptx(package: Package, reading: Reading) -> None:
    reading.kind, reading.unit = "pptx", "slide"
    deck = package.xml("ppt/presentation.xml")
    if deck is None:
        raise OfficeError(f"{package.name} could not be opened. The file may be damaged.")
    rels = package.rels("ppt/presentation.xml")
    slides = [rels[s.get(R + "id")][1] for s in deck.iter(P + "sldId") if s.get(R + "id") in rels and rels[s.get(R + "id")][0] == "slide"]
    if not slides:                                     # (Strict Open XML: the slides in file order, words only)
        for part in sorted((n for n in package.names if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                           key=lambda n: int(re.search(r"(\d+)\.xml$", n).group(1)))[:SLIDES]:
            root = package.xml(part)
            if root is not None:
                reading.lines.append("\n".join(t.strip() for t in root.itertext() if t.strip()))
        return
    reading.count = len(slides)
    for number, part in enumerate(slides[:SLIDES], 1):
        root = package.xml(part)
        if root is None:
            continue
        links = package.rels(part)
        body = []
        for paragraph in root.iter(A + "p"):
            words = " ".join(_text(paragraph).split())
            if words:
                body.append(words)
        for ref in [b.get(R + "embed") for b in root.iter(A + "blip")]:
            if ref in links and links[ref][0] == "image":
                marker = reading.picture(package, links[ref][1])
                if marker:
                    body.append(marker)
        for kind, where in links.values():
            if kind == "chart":
                chart = _chart(package, where)
                if chart:
                    reading.charts += 1
                    body.append(chart)
            elif kind == "diagramData":
                tree = package.xml(where)
                words = " · ".join(" ".join(t.text.split()) for t in tree.iter(A + "t") if t.text and t.text.strip()) if tree is not None else ""
                if words:
                    body.append("Diagram: " + words)
            elif kind == "notesSlide":
                tree = package.xml(where)
                notes = " ".join(" ".join(_text(p).split()) for p in tree.iter(A + "p")).strip() if tree is not None else ""
                notes = re.sub(r"\s*\b\d+\s*$", "", notes)       # (the slide number a notes page carries)
                if notes:
                    body.append("Speaker notes: " + notes)
        reading.lines.append(f"## Slide {number}\n\n" + "\n".join(body))


def _xlsx(package: Package, reading: Reading) -> None:
    reading.kind = "xlsx"
    book = package.xml("xl/workbook.xml")
    shared_root = package.xml("xl/sharedStrings.xml")
    shared = ["".join(t.text or "" for t in item.iter(S + "t")) for item in shared_root.findall(S + "si")] if shared_root is not None else []
    rels = package.rels("xl/workbook.xml")
    sheets = [(s.get("name") or f"Sheet {i}", rels[s.get(R + "id")][1]) for i, s in enumerate(book.iter(S + "sheet"), 1)
              if s.get(R + "id") in rels] if book is not None else []
    if not sheets:                                     # (no workbook list: the sheet files in order)
        sheets = [(f"Sheet {i}", n) for i, n in enumerate(sorted((n for n in package.names if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n)),
                                                                 key=lambda n: int(re.search(r"(\d+)\.xml$", n).group(1))), 1)]
    left = 200_000                                     # (characters of cells in all; a huge sheet is cut, and says so)
    for name, part in sheets[:12]:
        root = package.xml(part)
        if root is None:
            continue
        rows = []
        for row in root.iter(S + "row"):
            cells = []
            for cell in row.findall(S + "c"):
                kind, value = cell.get("t"), cell.find(S + "v")
                if kind == "s" and value is not None and (value.text or "").strip().isdigit() and int(value.text) < len(shared):
                    cells.append(shared[int(value.text)])
                elif kind == "inlineStr":
                    cells.append("".join(t.text or "" for t in cell.iter(S + "t")))
                else:
                    cells.append(value.text or "" if value is not None else "")
            line = " | ".join(c.strip() for c in cells).strip(" |")
            if line:
                rows.append(line)
                left -= len(line)
            if left <= 0:
                rows.append("(the rest of this workbook is left out: it is too long)")
                break
        reading.lines.append(f"## Sheet: {name}\n\n" + "\n".join(rows) if rows else f"## Sheet: {name}\n\n(empty)")
        if left <= 0:
            break
    for chart in sorted((n for n in package.names if re.fullmatch(r"xl/charts/chart\d+\.xml", n)), key=lambda n: int(re.search(r"(\d+)", n).group(1))):
        text = _chart(package, chart)
        if text:
            reading.charts += 1
            reading.lines.append(text)
    for media in sorted(n for n in package.names if n.startswith("xl/media/")):
        marker = reading.picture(package, media)
        if marker:
            reading.lines.append(marker)


def _odt(package: Package, reading: Reading) -> None:
    reading.kind = "odt"
    root = package.xml("content.xml")
    if root is None:
        raise OfficeError(f"{package.name} could not be opened. The file may be damaged.")
    reading.lines.append("\n".join(t.strip() for t in root.itertext() if t.strip()))
    for media in sorted(n for n in package.names if n.startswith("Pictures/")):
        marker = reading.picture(package, media)
        if marker:
            reading.lines.append(marker)


def read(name: str, suffix: str, data: bytes) -> Reading:
    package = Package(name, data)
    reading = Reading(name)
    {".docx": _docx, ".pptx": _pptx, ".xlsx": _xlsx, ".odt": _odt}[suffix](package, reading)
    return reading


def text(reading: Reading) -> str:
    return "\n\n".join(line for line in reading.lines if line.strip())


def notice(reading: Reading) -> str:
    """The toast for a document that came through only in part ("" when all of it did)."""
    kept, left = len(reading.pictures), reading.skipped_format
    parts = []
    if left:
        parts.append((f"{kept} picture{'s' if kept != 1 else ''} attached, {left} left out" if kept else
                      f"{left} picture{'s' if left != 1 else ''} left out")
                     + " because JARVIS cannot show their format. Attach a PDF copy to include everything.")
    if reading.over:
        parts.append(f"only the first {MOST_PICTURES} pictures are attached.")
    return (f"{reading.name}: " + " ".join(parts)) if parts else ""
