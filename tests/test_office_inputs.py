"""Pictures, charts and slides out of Word, PowerPoint, Excel and OpenDocument files (jcc/office_inputs.py), and how such a
document is attached (jcc/documents.py, jcc/doc_inputs.py). Every fixture is built here, in memory."""
import base64
import io
import struct
import zipfile
import zlib
from unittest import mock

from jcc import config, doc_inputs, documents, office_inputs
from tests.helpers import EngineTestCase

REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
      'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
      'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
      'xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart"')


def png(width, height, shade=0):
    raw = b"".join(b"\x00" + bytes([shade, 80, 160]) * width for _ in range(height))
    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def jpeg(width, height):
    """Just enough of a JPEG for its size to be read (it is never drawn)."""
    return (b"\xff\xd8\xff\xc0" + (17).to_bytes(2, "big") + b"\x08" + height.to_bytes(2, "big") + width.to_bytes(2, "big")
            + b"\x03" + b"\x01\x22\x00\x02\x11\x01\x03\x11\x01" + b"\xff\xd9")


EMF = b"\x01\x00\x00\x00" + b"\x00" * 120


def rels(rows):
    body = "".join(f'<Relationship Id="{i}" Type="{REL}{t}" Target="{target}"{extra}/>' for i, t, target, extra in rows)
    return f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{body}</Relationships>'


CHART = (f'<c:chartSpace {NS}><c:chart><c:title><c:tx><c:rich><a:p><a:r><a:t>Sales by quarter</a:t></a:r></a:p></c:rich></c:tx></c:title>'
         '<c:plotArea><c:barChart><c:ser><c:tx><c:strRef><c:strCache><c:pt idx="0"><c:v>Sales</c:v></c:pt></c:strCache></c:strRef></c:tx>'
         '<c:cat><c:strRef><c:strCache><c:pt idx="0"><c:v>Q1</c:v></c:pt><c:pt idx="1"><c:v>Q2</c:v></c:pt></c:strCache></c:strRef></c:cat>'
         '<c:val><c:numRef><c:numCache><c:pt idx="0"><c:v>10</c:v></c:pt><c:pt idx="1"><c:v>12.5</c:v></c:pt></c:numCache></c:numRef></c:val>'
         '</c:ser></c:barChart></c:plotArea></c:chart></c:chartSpace>')


def docx(extra_parts=None):
    blip = '<w:r><w:drawing><a:graphic><a:graphicData><a:blip r:embed="{}"/></a:graphicData></a:graphic></w:drawing></w:r>'
    body = ("<w:p><w:r><w:t>Intro to the plan</w:t></w:r>" + blip.format("rId1") + blip.format("rId2") + blip.format("rId3") + "</w:p>"
            "<w:p><w:r><w:t>Later on</w:t></w:r>" + blip.format("rId4") + blip.format("rId5") + blip.format("rId7") + blip.format("rId8") + "</w:p>"
            '<w:p><w:r><w:drawing><a:graphic><a:graphicData><c:chart r:id="rId6"/></a:graphicData></a:graphic></w:drawing></w:r></w:p>')
    parts = {
        "word/document.xml": f"<w:document {NS}><w:body>{body}</w:body></w:document>",
        "word/_rels/document.xml.rels": rels([("rId1", "image", "media/image1.png", ""), ("rId2", "image", "media/icon.png", ""),
                                              ("rId3", "image", "media/drawing.emf", ""), ("rId4", "image", "media/copy.png", ""),
                                              ("rId5", "image", "media/photo.jpg", ""), ("rId6", "chart", "charts/chart1.xml", ""),
                                              ("rId7", "image", "https://example.com/tracker.png", ' TargetMode="External"'),
                                              ("rId8", "image", "../../../outside.png", "")]),
        "word/media/image1.png": png(400, 300), "word/media/icon.png": png(20, 20), "word/media/drawing.emf": EMF,
        "word/media/copy.png": png(400, 300), "word/media/photo.jpg": jpeg(300, 200), "word/charts/chart1.xml": CHART,
        "outside.png": png(500, 500, shade=9),
    }
    parts.update(extra_parts or {})
    return pack(parts)


def pptx():
    def slide(words, picture_rel=None):
        pic = f'<p:pic><p:blipFill><a:blip r:embed="{picture_rel}"/></p:blipFill></p:pic>' if picture_rel else ""
        return f"<p:sld {NS}><p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>{words}</a:t></a:r></a:p></p:txBody></p:sp>{pic}</p:spTree></p:cSld></p:sld>"
    parts = {
        "ppt/presentation.xml": f'<p:presentation {NS}><p:sldIdLst><p:sldId id="256" r:id="rId2"/><p:sldId id="257" r:id="rId1"/></p:sldIdLst></p:presentation>',
        "ppt/_rels/presentation.xml.rels": rels([("rId1", "slide", "slides/slide1.xml", ""), ("rId2", "slide", "slides/slide2.xml", "")]),
        "ppt/slides/slide2.xml": slide("Opening slide", "rId1"),
        "ppt/slides/_rels/slide2.xml.rels": rels([("rId1", "image", "../media/logo.png", ""), ("rId9", "notesSlide", "../notesSlides/notesSlide1.xml", "")]),
        "ppt/slides/slide1.xml": slide("Closing slide", "rId1"),
        "ppt/slides/_rels/slide1.xml.rels": rels([("rId1", "image", "../media/logo.png", ""), ("rId2", "chart", "../charts/chart1.xml", "")]),
        "ppt/notesSlides/notesSlide1.xml": f"<p:notes {NS}><p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>Say hello first</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:notes>",
        "ppt/media/logo.png": png(300, 120), "ppt/charts/chart1.xml": CHART,
    }
    return pack(parts)


S_NS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'


def xlsx():
    """A workbook whose sheets are listed out of file order, with shared and inline text, and a chart saved without its
    numbers (as some programs write them)."""
    def cell(ref, value, kind=None):
        if kind == "inlineStr":
            return f'<c r="{ref}" t="inlineStr"><is><t>{value}</t></is></c>'
        return f'<c r="{ref}"{f" t={chr(34)}{kind}{chr(34)}" if kind else ""}><v>{value}</v></c>'
    sheet = lambda rows: f"<worksheet {S_NS}><sheetData>" + "".join(f"<row>{''.join(r)}</row>" for r in rows) + "</sheetData></worksheet>"
    parts = {
        "xl/workbook.xml": f'<workbook {S_NS}><sheets><sheet name="Budget" sheetId="1" r:id="rId2"/><sheet name="Notes" sheetId="2" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": rels([("rId1", "worksheet", "worksheets/sheet1.xml", ""), ("rId2", "worksheet", "worksheets/sheet2.xml", "")]),
        "xl/sharedStrings.xml": f'<sst {S_NS}><si><t>Item</t></si><si><t>Cost</t></si><si><r><t>Re</t></r><r><t>nt</t></r></si></sst>',
        "xl/worksheets/sheet2.xml": sheet([[cell("A1", 0, "s"), cell("B1", 1, "s")], [cell("A2", 2, "s"), cell("B2", 1200)]]),
        "xl/worksheets/sheet1.xml": sheet([[cell("A1", "Pay on the 1st", "inlineStr")]]),
        "xl/charts/chart1.xml": (f'<c:chartSpace {NS}><c:chart><c:plotArea><c:barChart><c:ser><c:val><c:numRef><c:f>Budget!$B$2:$B$2</c:f>'
                                 '</c:numRef></c:val></c:ser></c:barChart></c:plotArea></c:chart></c:chartSpace>'),
        "xl/media/image1.png": png(400, 300),
    }
    return pack(parts)


def pack(parts):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in parts.items():
            archive.writestr(name, content if isinstance(content, bytes) else content.encode("utf-8"))
    return buffer.getvalue()


class OfficeReadingTests(EngineTestCase):
    def test_word_pictures_come_in_order_and_only_the_right_ones(self):
        reading = office_inputs.read("notes.docx", ".docx", docx())
        self.assertEqual([name for name, _ in reading.pictures], ["picture-01.png", "picture-02.jpg"])
        self.assertEqual(reading.skipped_small, 1)           # the 20 x 20 icon
        self.assertEqual(reading.skipped_format, 1)          # the EMF drawing
        self.assertEqual(reading.charts, 1)
        text = office_inputs.text(reading)
        self.assertIn("Intro to the plan [picture-01.png]", text)
        self.assertIn("Later on [picture-02.jpg]", text)     # (the copy of picture 1 is not taken twice)
        self.assertIn("Chart: Sales by quarter", text)
        self.assertIn("- Sales: Q1 10, Q2 12.5", text)
        self.assertNotIn("outside", text)                    # (a link out of the archive, or to the web, is never followed)
        self.assertEqual(office_inputs.notice(reading),
                         "notes.docx: 2 pictures attached, 1 left out because JARVIS cannot show their format. Attach a PDF copy to include everything.")

    def test_a_deck_comes_slide_by_slide_in_its_own_order(self):
        reading = office_inputs.read("deck.pptx", ".pptx", pptx())
        self.assertEqual(reading.count, 2)
        self.assertEqual(reading.unit, "slide")
        text = office_inputs.text(reading)
        self.assertLess(text.index("Opening slide"), text.index("Closing slide"))
        self.assertIn("## Slide 1\n\nOpening slide\n[picture-01.png]\nSpeaker notes: Say hello first", text)
        self.assertEqual(len(reading.pictures), 1)           # (the logo on both slides is one picture)
        self.assertIn("Chart: Sales by quarter", text)
        self.assertEqual(office_inputs.notice(reading), "")

    def test_a_word_table_reads_row_by_row(self):
        table = ("<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Region</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Sales</w:t></w:r></w:p></w:tc></w:tr>"
                 "<w:tr><w:tc><w:p><w:r><w:t>North</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>120</w:t></w:r></w:p></w:tc></w:tr></w:tbl>")
        data = pack({"word/document.xml": f"<w:document {NS}><w:body><w:p><w:r><w:t>Before</w:t></w:r></w:p>{table}"
                                          "<w:p><w:r><w:t>After</w:t></w:r></w:p></w:body></w:document>"})
        text = office_inputs.text(office_inputs.read("t.docx", ".docx", data))
        self.assertEqual(text, "Before\n\nRegion | Sales\nNorth | 120\n\nAfter")

    def test_a_workbook_reads_sheet_by_sheet_in_its_own_order(self):
        reading = office_inputs.read("budget.xlsx", ".xlsx", xlsx())
        text = office_inputs.text(reading)
        self.assertIn("## Sheet: Budget\n\nItem | Cost\nRent | 1200", text)
        self.assertLess(text.index("## Sheet: Budget"), text.index("## Sheet: Notes\n\nPay on the 1st"))
        self.assertIn("- Series: its numbers are the cells Budget!$B$2:$B$2", text)
        self.assertEqual([name for name, _ in reading.pictures], ["picture-01.png"])

    def test_hostile_archives_are_refused(self):
        with self.assertRaises(ValueError) as caught:
            office_inputs.read("bomb.docx", ".docx", pack({f"word/x{n}.xml": "" for n in range(3001)}))
        self.assertEqual(str(caught.exception), "bomb.docx unpacks to far more than its size, so JARVIS did not open it.")
        with mock.patch.object(office_inputs, "MOST_EXPANDED", 1000):
            with self.assertRaises(ValueError):
                office_inputs.read("big.docx", ".docx", docx())
        with self.assertRaises(ValueError):
            office_inputs.read("entity.docx", ".docx", docx({"word/document.xml": '<!DOCTYPE d [<!ENTITY x "y">]><d>&x;</d>'}))
        with self.assertRaises(ValueError) as caught:
            office_inputs.read("junk.pptx", ".pptx", b"not a zip at all")
        self.assertIn("could not be opened", str(caught.exception))
        with self.assertRaises(ValueError):
            office_inputs.read("empty.pptx", ".pptx", pack({"other.xml": "<x/>"}))

    def test_more_than_twenty_pictures_are_cut_and_said(self):
        parts = {"word/document.xml": f"<w:document {NS}><w:body><w:p>"
                 + "".join(f'<a:blip r:embed="rId{n}"/>' for n in range(25)) + "</w:p></w:body></w:document>",
                 "word/_rels/document.xml.rels": rels([(f"rId{n}", "image", f"media/i{n}.png", "") for n in range(25)])}
        parts.update({f"word/media/i{n}.png": png(200, 200, shade=n) for n in range(25)})
        reading = office_inputs.read("many.docx", ".docx", pack(parts))
        self.assertEqual(len(reading.pictures), 20)
        self.assertEqual(office_inputs.notice(reading), "many.docx: only the first 20 pictures are attached.")


class OfficeAttachTests(EngineTestCase):
    def test_a_document_with_pictures_is_kept_for_a_job(self):
        cfg = config.load()
        result = documents.extract("notes.docx", base64.b64encode(docx()).decode(), cfg)
        self.assertEqual(result["label"], "2 pictures · 1 chart")
        folder = cfg.state_dir / "doc-inputs" / result["doc_id"]
        self.assertEqual(sorted(p.name for p in folder.iterdir()), ["manifest.json", "picture-01.png", "picture-02.jpg", "text.md"])
        self.assertIn("[picture-01.png]", result["text"])
        self.assertIn("left out because JARVIS cannot show their format", result["notice"])
        work = self.tmp / "job"
        prepared = doc_inputs.prepare(cfg, [result["doc_id"]], work)
        self.assertEqual([p.name for p in prepared[0]["pictures"]], ["picture-01.png", "picture-02.jpg"])
        self.assertIn("Word document", doc_inputs.prompt(prepared))

    def test_a_deck_is_labelled_by_slides(self):
        cfg = config.load()
        result = documents.extract("deck.pptx", base64.b64encode(pptx()).decode(), cfg)
        self.assertEqual(result["label"], "2 slides · 1 picture · 1 chart")

    def test_a_document_without_pictures_stays_text_for_the_assistant(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("word/document.xml", f"<w:document {NS}><w:body><w:p><w:r><w:t>Hello document</w:t></w:r></w:p></w:body></w:document>")
        result = documents.extract("plain.docx", base64.b64encode(buffer.getvalue()).decode(), config.load())
        self.assertNotIn("doc_id", result)
        self.assertIn("Hello document", result["text"])
        self.assertEqual(result["notes"], [])
