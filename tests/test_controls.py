"""T-04: tagged content controls — inline citations, block bibliography.

NOTE on acceptance 3 ("visible text readable by python-docx as ordinary
paragraph text"): python-docx 1.2.0's high-level ``Paragraph.text`` and
``Document.paragraphs`` silently SKIP content inside ``w:sdt`` (verified
empirically before writing these tests). The text is still ordinary ``w:t``
content in the body — which is what Word renders for a coauthor without
CiteBind — so these tests assert on python-docx's XML text nodes
(``itertext``) and would fail if the visible text were stored anywhere other
than plain runs. This python-docx API gap is exactly why ArtifactCert flags
content-control paragraphs as having incomplete canonical text (dev plan
§3.3); it is a known, deliberate loss at the high-level-API level.
"""

import zipfile

import pytest
from docx import Document
from lxml import etree

from citebind.controls import (
    find_controls,
    insert_bibliography,
    insert_citation,
)

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def q(name):
    return f"{{{W_NS}}}{name}"


@pytest.fixture
def populated(tmp_path):
    path = tmp_path / "populated.docx"
    document = Document()
    document.add_paragraph("As shown by prior work ")
    document.add_paragraph("Earlier results confirmed this ")
    document.add_paragraph("A plain paragraph with no citations.")
    paragraphs = document.paragraphs
    insert_citation(paragraphs[0], "C001", "[1]")
    insert_citation(paragraphs[1], "C002", "[2, 3]")
    insert_bibliography(
        document,
        [
            "A. Author. A Fixture Paper. Journal of Fixtures, 2024.",
            "B. Author. Another Fixture. Journal of Fixtures II, 2023.",
        ],
    )
    document.save(path)
    return path


# --- acceptance 1: exactly the expected number of w:sdt ------------------------


def test_document_contains_exactly_three_sdts(populated):
    xml = zipfile.ZipFile(populated).read("word/document.xml")
    tree = etree.fromstring(xml)
    assert len(list(tree.iter(q("sdt")))) == 3


# --- acceptance 2: find_controls recovers every tag, in document order ---------


def test_find_controls_returns_all_tags_in_document_order(populated):
    controls = find_controls(populated)
    assert [c.tag for c in controls] == [
        "citebind:citation:C001",
        "citebind:citation:C002",
        "citebind:bibliography",
    ]
    assert [c.kind for c in controls] == ["citation", "citation", "bibliography"]
    assert controls[0].cluster_id == "C001"
    assert controls[1].cluster_id == "C002"
    assert controls[2].cluster_id is None


def test_find_controls_returns_visible_text(populated):
    controls = find_controls(populated)
    assert controls[0].text == "[1]"
    assert controls[1].text == "[2, 3]"
    assert controls[2].text == (
        "A. Author. A Fixture Paper. Journal of Fixtures, 2024.\n"
        "B. Author. Another Fixture. Journal of Fixtures II, 2023."
    )


def test_find_controls_ignores_foreign_sdts(tmp_path):
    path = tmp_path / "foreign.docx"
    document = Document()
    document.add_paragraph("Plain ")
    paragraph = document.paragraphs[0]
    sdt = etree.SubElement(paragraph._p, q("sdt"))
    pr = etree.SubElement(sdt, q("sdtPr"))
    tag = etree.SubElement(pr, q("tag"))
    tag.set(q("val"), "some:other:tool")
    content = etree.SubElement(sdt, q("sdtContent"))
    run = etree.SubElement(content, q("r"))
    t = etree.SubElement(run, q("t"))
    t.text = "foreign text"
    document.save(path)
    assert find_controls(path) == []


# --- acceptance 3: visible text is ordinary text (coauthor guarantee) ----------


def _all_visible_text(element):
    # Join every w:t in document order. (lxml's itertext() is unusable here:
    # python-docx's custom element classes override .text as a computed
    # property, so itertext() returns duplicated text. Verified empirically.)
    return "".join(t.text or "" for t in element.iter(q("t")))


def test_citation_text_reads_as_ordinary_paragraph_text(populated):
    document = Document(populated)
    texts = [_all_visible_text(p._p) for p in document.paragraphs]
    assert texts[0] == "As shown by prior work [1]"
    assert texts[1] == "Earlier results confirmed this [2, 3]"
    assert texts[2] == "A plain paragraph with no citations."


def test_bibliography_text_reads_as_ordinary_text(populated):
    document = Document(populated)
    body_text = _all_visible_text(document.element.body)
    assert "A. Author. A Fixture Paper. Journal of Fixtures, 2024." in body_text
    assert "B. Author. Another Fixture. Journal of Fixtures II, 2023." in body_text


# --- acceptance 4: inline citation inside a paragraph, bibliography at body ----


def test_citation_control_sits_inside_paragraph(populated):
    xml = zipfile.ZipFile(populated).read("word/document.xml")
    tree = etree.fromstring(xml)
    for sdt in tree.iter(q("sdt")):
        tag = sdt.find(f"{q('sdtPr')}/{q('tag')}")
        if tag is None or not tag.get(q("val"), "").startswith("citebind:citation:"):
            continue
        parent = sdt.getparent()
        assert parent.tag == q("p"), "citation control must be inline in a paragraph"


def test_bibliography_control_sits_at_body_level(populated):
    xml = zipfile.ZipFile(populated).read("word/document.xml")
    tree = etree.fromstring(xml)
    body = tree.find(q("body"))
    bib = None
    for sdt in tree.iter(q("sdt")):
        tag = sdt.find(f"{q('sdtPr')}/{q('tag')}")
        if tag is not None and tag.get(q("val")) == "citebind:bibliography":
            bib = sdt
    assert bib is not None
    assert bib.getparent() is body
    # block content must precede the body's sectPr to be valid Word XML
    sect_pr = body.find(q("sectPr"))
    if sect_pr is not None:
        assert list(body).index(bib) < list(body).index(sect_pr)


# --- acceptance 5: python-docx rewrite preserves all tags -----------------------


def test_controls_survive_python_docx_rewrite(populated, tmp_path):
    resaved = tmp_path / "resaved.docx"
    Document(populated).save(resaved)
    xml = zipfile.ZipFile(resaved).read("word/document.xml")
    tree = etree.fromstring(xml)
    assert len(list(tree.iter(q("sdt")))) == 3
    assert [c.tag for c in find_controls(resaved)] == [
        "citebind:citation:C001",
        "citebind:citation:C002",
        "citebind:bibliography",
    ]
    assert [c.text for c in find_controls(resaved)][0] == "[1]"


# --- F3: the public finder is on the hardened path, same as the verifier ------


def test_find_controls_refuses_doctype_laced_document(tmp_path):
    from citebind.xmlsafe import UnsafeXML

    path = tmp_path / "laced.docx"
    document = Document()
    document.add_paragraph("Has a citation control. ")
    insert_citation(document.paragraphs[0], "C001", "[1]")
    document.save(path)
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(tmp_path / "out.docx", "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            if item.filename == "word/document.xml":
                xml = zin.read(item.filename)
                xml = xml.replace(
                    b"<?xml version='1.0' encoding='UTF-8' standalone='yes'?>",
                    b"<!DOCTYPE document [<!ENTITY x \"y\">]>", 1,
                )
                zout.writestr(item.filename, xml)
            else:
                zout.writestr(item.filename, zin.read(item.filename))
    with pytest.raises(UnsafeXML) as exc_info:
        find_controls(tmp_path / "out.docx")
    assert exc_info.value.code == "doctype_declared"


def test_find_controls_and_verifier_see_the_same_controls(tmp_path):
    from citebind.verify import inspect

    path = tmp_path / "doc.docx"
    document = Document()
    document.add_paragraph("Cite ")
    document.add_paragraph("Again ")
    insert_citation(document.paragraphs[0], "C001", "[1]")
    insert_citation(document.paragraphs[1], "C001", "[1]")
    document.save(path)
    assert [c.tag for c in find_controls(path)] == [
        c for c in inspect(path).control_tags
    ]
