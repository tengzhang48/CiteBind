"""Recovery of EndNote/Zotero references embedded in a DOCX (foreign.py).

Every fixture here is GENERATED: no manuscript, no vendor-produced file, no
network. The package builders below write the OOXML by hand precisely so the
tests exercise the shapes that break naive extractors — an instruction split
mid-token across runs, a field nested inside another field's result, a
citation in a footnote, a header part that exists in the ZIP but is not
related to anything.

The field-code shapes (``ADDIN ZOTERO_ITEM CSL_CITATION`` + CSL-JSON,
``ADDIN EN.CITE`` + ``<EndNote>`` XML, ``ADDIN CSL_CITATION`` for Mendeley)
are external knowledge, recorded in the 2026-09-14 interoperability review.
The fixtures encode our understanding of those formats; they are not proof
that a real Word document looks exactly like this. Only a real
Word/EndNote/Zotero round trip can establish that (review, "Validation").
"""

import hashlib
import json
import socket
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

import pytest

from citebind import word_fields
from citebind.foreign import classify_instruction, recover_references
from citebind.recovery_model import RecoveryError

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
V = "urn:schemas-microsoft-com:vml"
PKG_RELS = "http://schemas.openxmlformats.org/package/2006/relationships"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"

REL_TYPES = {
    "officeDocument": f"{R}/officeDocument",
    "footnotes": f"{R}/footnotes",
    "endnotes": f"{R}/endnotes",
    "header": f"{R}/header",
    "footer": f"{R}/footer",
    "styles": f"{R}/styles",
}


# --- package fixtures ----------------------------------------------------------


def document_xml(body: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{W}" xmlns:r="{R}" xmlns:mc="{MC}" xmlns:v="{V}">'
        f"<w:body>{body}</w:body></w:document>"
    )


def footnotes_xml(body: str) -> str:
    return (
        f'<w:footnotes xmlns:w="{W}">'
        f'<w:footnote w:id="1">{body}</w:footnote></w:footnotes>'
    )


def endnotes_xml(body: str) -> str:
    return (
        f'<w:endnotes xmlns:w="{W}">'
        f'<w:endnote w:id="1">{body}</w:endnote></w:endnotes>'
    )


def header_xml(body: str) -> str:
    return f'<w:hdr xmlns:w="{W}">{body}</w:hdr>'


def footer_xml(body: str) -> str:
    return f'<w:ftr xmlns:w="{W}">{body}</w:ftr>'


def _rels_xml(entries) -> str:
    relationships = "".join(
        f'<Relationship Id="rId{n}" Type={quoteattr(type_uri)} '
        f"Target={quoteattr(target)}{extra}/>"
        for n, (type_uri, target, extra) in enumerate(entries, start=1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{PKG_RELS}">{relationships}</Relationships>'
    )


CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    f'<Types xmlns="{CT}">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    "</Types>"
)


def make_docx(path, *, document=None, parts=None, rels=(), members=None, drop=()):
    """Write a minimal Word package: content types, package rels, document rels.

    ``rels`` are (kind, target) pairs written into
    ``word/_rels/document.xml.rels``; only parts named there are reachable
    the way Word reaches them.
    """
    entries: dict[str, object] = {
        "[Content_Types].xml": CONTENT_TYPES,
        "_rels/.rels": _rels_xml([(REL_TYPES["officeDocument"], "word/document.xml", "")]),
    }
    if document is not None:
        entries["word/document.xml"] = document
    entries["word/_rels/document.xml.rels"] = _rels_xml(
        [(REL_TYPES[kind], target, "") for kind, target in rels]
    )
    entries.update(parts or {})
    entries.update(members or {})
    for name in drop:
        entries.pop(name, None)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as package:
        for name, data in entries.items():
            package.writestr(name, data)
    return path


def simple_docx(tmp_path, body, name="doc.docx"):
    return make_docx(tmp_path / name, document=document_xml(body))


# --- field fixtures ------------------------------------------------------------


def instr_runs(*chunks, deleted=False):
    tag = "w:delInstrText" if deleted else "w:instrText"
    return "".join(
        f'<w:r><{tag} xml:space="preserve">{escape(chunk)}</{tag}></w:r>'
        for chunk in chunks
    )


def fld_char(kind):
    return f'<w:r><w:fldChar w:fldCharType="{kind}"/></w:r>'


def complex_field(*chunks, result="(1)", deleted=False):
    """A Word complex field: begin, instruction runs, separate, result, end."""
    text_tag = "w:delText" if deleted else "w:t"
    return (
        fld_char("begin")
        + instr_runs(*chunks, deleted=deleted)
        + fld_char("separate")
        + f"<w:r><{text_tag}>{escape(result)}</{text_tag}></w:r>"
        + fld_char("end")
    )


def simple_field(instruction, result="(1)"):
    return (
        f"<w:fldSimple w:instr={quoteattr(instruction)}>"
        f"<w:r><w:t>{escape(result)}</w:t></w:r></w:fldSimple>"
    )


def para(*inner):
    return "<w:p>" + "".join(inner) + "</w:p>"


def tracked(kind, inner):
    return (
        f'<w:{kind} w:id="7" w:author="A. Reviewer" w:date="2026-09-14T10:00:00Z">'
        f"{inner}</w:{kind}>"
    )


# --- vendor payload fixtures ----------------------------------------------------


def zotero_item(key="ABCD1234", **overrides):
    """One Zotero citationItem: identity, itemData (CSL-JSON), locators."""
    item = {
        "id": 4581,
        "uris": [f"http://zotero.org/users/12345/items/{key}"],
        "itemData": {
            "id": 4581,
            "type": "article-journal",
            "title": "Perspectives on electronic medical records adoption",
            "container-title": "Patient Related Outcome Measures",
            "page": "1-7",
            "volume": "2",
            "issue": "1",
            "DOI": "10.2147/PROM.S8896",
            "author": [
                {"family": "Belletti", "given": "Dan A."},
                {"family": "Zacker", "given": "Christopher"},
            ],
            "issued": {"date-parts": [["2011", 1]]},
        },
    }
    item.update(overrides)
    return item


def zotero_instruction(items, properties=None, prefix="ADDIN ZOTERO_ITEM CSL_CITATION "):
    payload = {
        "citationID": "aBcD1234",
        "properties": {
            "formattedCitation": "(Belletti & Zacker, 2011)",
            "plainCitation": "(Belletti & Zacker, 2011)",
            "noteIndex": 0,
        },
        "citationItems": items,
        "schema": "https://github.com/citation-style-language/schema/raw/master/csl-citation.json",
    }
    if properties is not None:
        payload["properties"] = properties
    return prefix + json.dumps(payload)


ENDNOTE_JOURNAL_RECORD = """<record>
  <rec-number>12</rec-number>
  <foreign-keys><key app="EN" db-id="s5wxr9v9k2f0" timestamp="1600000000">12</key></foreign-keys>
  <ref-type name="Journal Article">17</ref-type>
  <contributors><authors>
    <author>Belletti, Dan A.</author>
    <author>Zacker, Christopher</author>
  </authors></contributors>
  <titles>
    <title>Perspectives on electronic medical records adoption</title>
    <secondary-title>Patient Relat Outcome Meas</secondary-title>
  </titles>
  <periodical><full-title>Patient Related Outcome Measures</full-title></periodical>
  <pages>1-7</pages>
  <volume>2</volume>
  <number>1</number>
  <dates><year>2011</year><pub-dates><date>Jan</date></pub-dates></dates>
  <isbn>1179-271X</isbn>
  <accession-num>22915966</accession-num>
  <remote-database-name>PubMed</remote-database-name>
  <electronic-resource-num>10.2147/PROM.S8896</electronic-resource-num>
  <urls><related-urls><url>https://example.org/article</url></related-urls></urls>
  <abstract>An abstract that EndNote carries and CSL has a home for.</abstract>
  <keywords><keyword>medical records</keyword></keywords>
  <custom3>a vendor field with no CSL equivalent</custom3>
</record>"""

ENDNOTE_BOOK_RECORD = """<record>
  <rec-number>44</rec-number>
  <foreign-keys><key app="EN" db-id="s5wxr9v9k2f0" timestamp="1600000001">44</key></foreign-keys>
  <ref-type name="Book">6</ref-type>
  <contributors><authors><author>Tufte, Edward R.</author></authors>
  <secondary-authors><author>Editor, An</author></secondary-authors></contributors>
  <titles>
    <title><style face="normal" font="default" size="100%">The Visual Display of Quantitative Information</style></title>
    <secondary-title>Graphics Press Classics</secondary-title>
  </titles>
  <dates><year>1983</year></dates>
  <pub-location>Cheshire, CT</pub-location>
  <publisher>Graphics Press</publisher>
  <isbn>978-0961392147</isbn>
</record>"""


def endnote_instruction(*records, cite_extra="", prefix="ADDIN EN.CITE "):
    cites = "".join(
        f"<Cite><Author>Belletti</Author><Year>2011</Year><RecNum>12</RecNum>"
        f"<DisplayText>(Belletti &amp; Zacker, 2011)</DisplayText>{cite_extra}"
        f"{record}</Cite>"
        for record in records
    )
    return prefix + f"<EndNote>{cites}</EndNote>"


# --- helpers -------------------------------------------------------------------


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def codes(report):
    return [finding.code for finding in report.findings]


def by_id(report):
    return {record.id: record for record in report.records}


def titles(report):
    return [record.csl.get("title") for record in report.records]


# --- 1. field reading: runs, nesting, fldSimple, stories -------------------------


def test_instruction_split_across_runs_is_reassembled(tmp_path):
    # Word splits an instruction at arbitrary points, including mid-token and
    # inside the JSON. Reassembly per field is the whole game: a naive reader
    # that matches per-run finds nothing at all here.
    instruction = zotero_instruction([zotero_item()])
    cut_a, cut_b = 12, 40
    chunks = [instruction[:cut_a], instruction[cut_a:cut_b], instruction[cut_b:]]
    assert not chunks[0].endswith(" ")  # the split really is mid-token
    docx = simple_docx(tmp_path, para(complex_field(*chunks)))

    report = recover_references(docx)

    assert [c.source for c in report.citations] == ["zotero"]
    assert report.citations[0].instruction == instruction
    assert titles(report) == ["Perspectives on electronic medical records adoption"]
    assert not report.has_errors


def test_nested_field_instructions_do_not_merge(tmp_path):
    # A HYPERLINK field nested in the citation's RESULT, and a PAGE field
    # nested inside an outer IF field's INSTRUCTION. Concatenating instrText
    # per part (or per paragraph) would splice "HYPERLINK ..." into the
    # citation's JSON and produce one unparseable blob.
    instruction = zotero_instruction([zotero_item()])
    nested_result = (
        fld_char("begin")
        + instr_runs(instruction)
        + fld_char("separate")
        + fld_char("begin")
        + instr_runs('HYPERLINK "https://example.org"')
        + fld_char("separate")
        + "<w:r><w:t>(1)</w:t></w:r>"
        + fld_char("end")
        + fld_char("end")
    )
    nested_instruction = (
        fld_char("begin")
        + instr_runs("IF ")
        + fld_char("begin")
        + instr_runs("PAGE")
        + fld_char("separate")
        + "<w:r><w:t>3</w:t></w:r>"
        + fld_char("end")
        + instr_runs(' = 3 "yes" "no"')
        + fld_char("separate")
        + "<w:r><w:t>yes</w:t></w:r>"
        + fld_char("end")
    )
    docx = simple_docx(tmp_path, para(nested_result) + para(nested_instruction))

    report = recover_references(docx)

    assert [c.instruction for c in report.citations] == [instruction]
    assert len(report.records) == 1
    assert not report.has_errors


def test_two_citations_in_one_paragraph_stay_separate(tmp_path):
    first = zotero_instruction([zotero_item(key="AAAA1111")])
    second = zotero_instruction(
        [zotero_item(key="BBBB2222", itemData={"id": 2, "type": "book", "title": "Second"})]
    )
    docx = simple_docx(
        tmp_path, para(complex_field(first), "<w:r><w:t> and </w:t></w:r>", complex_field(second))
    )

    report = recover_references(docx)

    assert [c.instruction for c in report.citations] == [first, second]
    assert [c.field_index for c in report.citations] == sorted(
        c.field_index for c in report.citations
    )
    assert len(report.records) == 2
    assert [c.record_ids for c in report.citations] == [["zotero-0001"], ["zotero-0002"]]


def test_fld_simple_citation_is_recovered(tmp_path):
    instruction = zotero_instruction([zotero_item()])
    docx = simple_docx(tmp_path, para(simple_field(instruction)))

    report = recover_references(docx)

    assert [c.source for c in report.citations] == ["zotero"]
    assert report.citations[0].instruction == instruction
    assert len(report.records) == 1


def test_citation_inside_a_table_cell_is_recovered(tmp_path):
    instruction = endnote_instruction(ENDNOTE_JOURNAL_RECORD)
    body = (
        "<w:tbl><w:tr><w:tc>"
        + para(complex_field(instruction))
        + "</w:tc></w:tr></w:tbl>"
    )
    report = recover_references(simple_docx(tmp_path, body))

    assert [c.source for c in report.citations] == ["endnote"]
    assert len(report.records) == 1


def test_citation_inside_a_textbox_is_recovered(tmp_path):
    instruction = zotero_instruction([zotero_item()])
    body = para(
        "<w:r><w:pict><v:shape><v:textbox><w:txbxContent>"
        + para(complex_field(instruction))
        + "</w:txbxContent></v:textbox></v:shape></w:pict></w:r>"
    )
    report = recover_references(simple_docx(tmp_path, body))

    assert len(report.citations) == 1
    assert len(report.records) == 1


def test_alternate_content_fallback_is_not_counted_twice(tmp_path):
    # mc:Fallback repeats the mc:Choice content for older Word versions. Both
    # branches describe ONE citation; counting both would double every
    # textbox citation in a modern document.
    instruction = zotero_instruction([zotero_item()])
    field = para(complex_field(instruction))
    body = para(
        "<w:r><mc:AlternateContent>"
        f'<mc:Choice Requires="wps"><w:txbxContent>{field}</w:txbxContent></mc:Choice>'
        f"<mc:Fallback><w:pict><v:shape><v:textbox><w:txbxContent>{field}"
        "</w:txbxContent></v:textbox></v:shape></w:pict></mc:Fallback>"
        "</mc:AlternateContent></w:r>"
    )
    report = recover_references(simple_docx(tmp_path, body))

    assert len(report.citations) == 1
    assert len(report.records) == 1


def test_footnote_and_endnote_citations_are_recovered_with_their_part(tmp_path):
    zotero = zotero_instruction([zotero_item()])
    endnote = endnote_instruction(ENDNOTE_BOOK_RECORD)
    docx = make_docx(
        tmp_path / "stories.docx",
        document=document_xml(para("<w:r><w:t>Body prose.</w:t></w:r>")),
        parts={
            "word/footnotes.xml": footnotes_xml(para(complex_field(zotero))),
            "word/endnotes.xml": endnotes_xml(para(complex_field(endnote))),
        },
        rels=[("footnotes", "footnotes.xml"), ("endnotes", "endnotes.xml")],
    )

    report = recover_references(docx)

    assert {c.part for c in report.citations} == {
        "word/footnotes.xml",
        "word/endnotes.xml",
    }
    assert {c.source for c in report.citations} == {"zotero", "endnote"}
    assert len(report.records) == 2


def test_referenced_header_scanned_orphan_part_reported_not_recovered(tmp_path):
    # "Prefer referenced story parts": header1 is related from the document
    # part and is real content; header9 is a leftover ZIP entry Word does not
    # reach. Recovering the orphan would invent citations that no reader of
    # the document can see -- but ignoring it silently would hide data.
    referenced = zotero_instruction([zotero_item(key="HEAD0001")])
    orphan = zotero_instruction([zotero_item(key="ORPH0001")])
    docx = make_docx(
        tmp_path / "headers.docx",
        document=document_xml(para("<w:r><w:t>Body.</w:t></w:r>")),
        parts={
            "word/header1.xml": header_xml(para(complex_field(referenced))),
            "word/header9.xml": header_xml(para(complex_field(orphan))),
        },
        rels=[("header", "header1.xml")],
    )

    report = recover_references(docx)

    assert [c.part for c in report.citations] == ["word/header1.xml"]
    assert [r.source_ids for r in report.records] == [
        ["http://zotero.org/users/12345/items/HEAD0001", "4581"]
    ]
    assert "part_not_referenced" in codes(report)
    assert any(f.part == "word/header9.xml" for f in report.findings)


def test_footer_referenced_from_the_document_part_is_scanned(tmp_path):
    instruction = zotero_instruction([zotero_item()])
    docx = make_docx(
        tmp_path / "footer.docx",
        document=document_xml(para("<w:r><w:t>Body.</w:t></w:r>")),
        parts={"word/footer1.xml": footer_xml(para(complex_field(instruction)))},
        rels=[("footer", "footer1.xml")],
    )

    report = recover_references(docx)

    assert [c.part for c in report.citations] == ["word/footer1.xml"]


def test_referenced_story_part_missing_from_package_is_reported(tmp_path):
    docx = make_docx(
        tmp_path / "gap.docx",
        document=document_xml(para("<w:r><w:t>Body.</w:t></w:r>")),
        rels=[("footnotes", "footnotes.xml")],
    )

    report = recover_references(docx)

    assert "part_missing" in codes(report)


def test_damaged_relationship_part_is_reported_not_silently_empty(tmp_path):
    # Found by the hostile probe: a relationship part that is not a
    # Relationships document yielded no relationships, no stories and no
    # findings -- a document whose footnotes are unreachable reported as
    # cleanly empty.
    docx = make_docx(
        tmp_path / "badrels.docx",
        document=document_xml(para("<w:r><w:t>Body.</w:t></w:r>")),
        members={"word/_rels/document.xml.rels": "<notRelationships/>"},
    )

    report = recover_references(docx)

    assert "part_rels_malformed" in codes(report)


def test_one_part_reachable_twice_is_scanned_once(tmp_path):
    # Found by the hostile probe: a header relationship aimed at the main
    # document part made every citation in the body count twice.
    instruction = zotero_instruction([zotero_item()])
    docx = make_docx(
        tmp_path / "twice.docx",
        document=document_xml(para(complex_field(instruction))),
        rels=[("header", "document.xml")],
    )

    report = recover_references(docx)

    assert len(report.citations) == 1
    assert len(report.records) == 1


def test_deleted_field_is_excluded_and_reported(tmp_path):
    # A citation the author deleted under Track Changes is not a citation in
    # this document. It must not be recovered -- and must not vanish quietly
    # either, or the report claims a completeness it does not have.
    deleted = zotero_instruction([zotero_item(key="DELE0001")])
    kept = zotero_instruction([zotero_item(key="KEPT0001")])
    body = para(tracked("del", complex_field(deleted, deleted=True))) + para(
        complex_field(kept)
    )

    report = recover_references(simple_docx(tmp_path, body))

    assert [c.record_ids for c in report.citations] == [["zotero-0001"]]
    assert report.records[0].source_ids[0].endswith("KEPT0001")
    assert "tracked_deletion_skipped" in codes(report)
    assert all("DELE0001" not in json.dumps(r.raw) for r in report.records)


def test_move_from_field_is_excluded_and_reported(tmp_path):
    moved = zotero_instruction([zotero_item(key="MOVE0001")])
    body = para(tracked("moveFrom", complex_field(moved, deleted=True)))

    report = recover_references(simple_docx(tmp_path, body))

    assert report.records == []
    assert report.citations == []
    assert "tracked_deletion_skipped" in codes(report)


def test_inserted_field_is_recovered_and_flagged(tmp_path):
    # The opposite decision from w:del: inserted content IS in the document.
    # Recover it, but say that the document has unresolved tracked changes.
    instruction = zotero_instruction([zotero_item()])
    body = para(tracked("ins", complex_field(instruction)))

    report = recover_references(simple_docx(tmp_path, body))

    assert len(report.records) == 1
    assert "tracked_insertion_present" in codes(report)
    assert not report.has_errors


def test_unterminated_field_is_reported_not_dropped(tmp_path):
    instruction = zotero_instruction([zotero_item()])
    body = para(fld_char("begin") + instr_runs(instruction) + fld_char("separate"))

    report = recover_references(simple_docx(tmp_path, body))

    assert "field_unterminated" in codes(report)
    assert len(report.records) == 1  # the instruction is complete; the field is not


def test_field_end_without_begin_does_not_crash(tmp_path):
    body = para(fld_char("end")) + para(complex_field(zotero_instruction([zotero_item()])))

    report = recover_references(simple_docx(tmp_path, body))

    assert "field_end_without_begin" in codes(report)
    assert len(report.records) == 1


def test_document_without_citations_is_clean_and_empty(tmp_path):
    report = recover_references(simple_docx(tmp_path, para("<w:r><w:t>Prose.</w:t></w:r>")))

    assert report.records == []
    assert report.citations == []
    assert report.findings == []
    assert not report.has_errors


def test_unrelated_fields_are_ignored_without_findings(tmp_path):
    body = para(complex_field("PAGE")) + para(complex_field(r'TOC \o "1-3"'))

    report = recover_references(simple_docx(tmp_path, body))

    assert report.citations == []
    assert report.findings == []


# --- 2. Zotero CSL-JSON ----------------------------------------------------------


def test_multi_item_citation_links_every_record_and_keeps_the_instruction(tmp_path):
    first = zotero_item(key="AAAA1111")
    second = zotero_item(
        key="BBBB2222",
        id=99,
        uris=["http://zotero.org/users/12345/items/BBBB2222"],
        itemData={"id": 99, "type": "book", "title": "A Book", "publisher": "Press"},
    )
    first.update({"locator": "45", "label": "page", "prefix": "see also ",
                  "suffix": ", and later", "suppress-author": True})
    instruction = zotero_instruction([first, second])

    report = recover_references(simple_docx(tmp_path, para(complex_field(instruction))))

    assert report.citations[0].record_ids == ["zotero-0001", "zotero-0002"]
    # Citation-specific data belongs to the OCCURRENCE, not the record: the
    # same book cited twice with different pages is one record, two locators.
    assert report.citations[0].instruction == instruction
    for fragment in ('"locator": "45"', '"suppress-author": true', '"prefix": "see also "'):
        assert fragment in report.citations[0].instruction
    for record in report.records:
        assert "locator" not in record.raw and "locator" not in record.csl


def test_book_without_doi_is_recovered(tmp_path):
    # The contract obstacle from the review: citebind/1 requires DOI or PMID,
    # so a book cannot be represented there. Recovery is a separate space and
    # must not drop it.
    item = zotero_item(
        key="BOOK0001",
        itemData={
            "id": 7,
            "type": "book",
            "title": "The Visual Display of Quantitative Information",
            "publisher": "Graphics Press",
            "publisher-place": "Cheshire, CT",
            "ISBN": "978-0961392147",
            "issued": {"date-parts": [["1983"]]},
            "author": [{"family": "Tufte", "given": "Edward R."}],
        },
    )
    report = recover_references(
        simple_docx(tmp_path, para(complex_field(zotero_instruction([item]))))
    )

    record = report.records[0]
    assert record.csl["type"] == "book"
    assert record.csl["ISBN"] == "978-0961392147"
    assert "DOI" not in record.csl
    assert not report.has_errors


def test_unknown_item_data_keys_and_original_ids_are_preserved(tmp_path):
    item = zotero_item(key="RAWW0001")
    item["itemData"]["note"] = "Zotero extra field"
    item["itemData"]["vendor-only-key"] = {"nested": [1, 2, 3]}
    report = recover_references(
        simple_docx(tmp_path, para(complex_field(zotero_instruction([item]))))
    )

    record = report.records[0]
    assert record.raw["itemData"]["vendor-only-key"] == {"nested": [1, 2, 3]}
    assert record.raw["itemData"]["note"] == "Zotero extra field"
    assert record.raw["itemData"]["id"] == 4581  # the vendor's own id, untouched
    assert record.raw["uris"] == ["http://zotero.org/users/12345/items/RAWW0001"]
    assert "http://zotero.org/users/12345/items/RAWW0001" in record.source_ids
    assert record.csl["id"] == record.id  # ours, so an export has unique ids
    assert record.csl["vendor-only-key"] == {"nested": [1, 2, 3]}


def test_missing_item_data_is_an_error_and_other_items_survive(tmp_path):
    without = {"id": 12, "uris": ["http://zotero.org/users/12345/items/NODATA01"]}
    instruction = zotero_instruction([without, zotero_item(key="GOOD0001")])

    report = recover_references(simple_docx(tmp_path, para(complex_field(instruction))))

    assert "zotero_item_data_missing" in codes(report)
    assert report.has_errors
    assert len(report.records) == 1  # the well-formed sibling is still recovered
    assert report.citations[0].record_ids == ["zotero-0001"]


def test_incomplete_item_data_is_reported_not_guessed(tmp_path):
    item = zotero_item(key="THIN0001", itemData={"id": 3, "container-title": "A Journal"})
    report = recover_references(
        simple_docx(tmp_path, para(complex_field(zotero_instruction([item]))))
    )

    assert "zotero_item_incomplete" in codes(report)
    record = report.records[0]
    assert "title" not in record.csl and "type" not in record.csl


def test_rendered_citation_text_is_never_used_as_metadata(tmp_path):
    # properties.formattedCitation is the add-in's rendering. It is not
    # evidence about the record, and guessing from it is how extractors
    # invent references.
    item = {"id": 5, "uris": ["http://zotero.org/users/12345/items/RENDER01"]}
    instruction = zotero_instruction(
        [item],
        properties={"formattedCitation": "(Smith, 2001, Nature)", "plainCitation": "(Smith, 2001)"},
    )
    report = recover_references(simple_docx(tmp_path, para(complex_field(instruction))))

    assert report.records == []
    assert report.citations[0].record_ids == []
    assert report.citations[0].instruction == instruction  # preserved for the human
    assert "zotero_item_data_missing" in codes(report)


def test_malformed_json_is_an_error_and_the_next_field_still_recovers(tmp_path):
    broken = "ADDIN ZOTERO_ITEM CSL_CITATION {\"citationItems\": [{\"itemData\": "
    good = zotero_instruction([zotero_item(key="AFTER001")])
    body = para(complex_field(broken)) + para(complex_field(good))

    report = recover_references(simple_docx(tmp_path, body))

    assert "zotero_json_malformed" in codes(report)
    assert report.has_errors
    assert len(report.records) == 1
    assert [c.source for c in report.citations] == ["zotero", "zotero"]
    assert report.citations[0].record_ids == []


def test_duplicate_json_keys_are_refused(tmp_path):
    # json.loads keeps the last duplicate silently: two different itemData
    # objects for one item would collapse to whichever came last, and the
    # recovered record would not be the one the document contains.
    payload = (
        '{"citationItems": [{"id": 1, "itemData": {"title": "First"},'
        ' "itemData": {"title": "Second"}}]}'
    )
    instruction = "ADDIN ZOTERO_ITEM CSL_CITATION " + payload

    report = recover_references(simple_docx(tmp_path, para(complex_field(instruction))))

    assert "zotero_json_duplicate_key" in codes(report)
    assert report.has_errors
    assert report.records == []


def test_non_finite_json_numbers_are_refused(tmp_path):
    instruction = (
        'ADDIN ZOTERO_ITEM CSL_CITATION {"citationItems": '
        '[{"id": NaN, "itemData": {"title": "T"}}]}'
    )
    report = recover_references(simple_docx(tmp_path, para(complex_field(instruction))))

    assert "zotero_json_non_finite" in codes(report)
    assert report.has_errors
    assert report.records == []


def test_empty_citation_items_is_an_error_not_a_silent_pass(tmp_path):
    # A Zotero field that cites nothing is a corrupt supported citation, not
    # a citation with zero references. Passing it silently would let a
    # damaged document export as a complete library.
    body = para(complex_field(zotero_instruction([]))) + para(
        complex_field(zotero_instruction([zotero_item()]))
    )

    report = recover_references(simple_docx(tmp_path, body))

    assert "zotero_citation_items_empty" in codes(report)
    assert report.has_errors
    assert len(report.records) == 1  # the sound citation beside it survives


def test_overflowing_float_literal_is_refused_as_non_finite(tmp_path):
    # 1e999 is not the literal token NaN/Infinity, so a parse_constant guard
    # never sees it -- json.loads quietly returns inf, which then serializes
    # back out as invalid JSON for every downstream consumer.
    instruction = (
        'ADDIN ZOTERO_ITEM CSL_CITATION {"citationItems":[{"itemData":'
        '{"type":"book","title":"T","volume":1e999}}]}'
    )
    report = recover_references(simple_docx(tmp_path, para(complex_field(instruction))))

    assert "zotero_json_non_finite" in codes(report)
    assert report.has_errors
    assert report.records == []
    assert json.dumps(report.to_dict())  # the report is still ordinary JSON


def test_absurdly_nested_item_data_is_refused_with_the_instruction_kept(tmp_path):
    nested = "[" * 600 + "0" + "]" * 600
    instruction = (
        'ADDIN ZOTERO_ITEM CSL_CITATION {"citationItems":[{"itemData":'
        '{"type":"book","title":"T","extra":' + nested + "}}]}"
    )
    report = recover_references(simple_docx(tmp_path, para(complex_field(instruction))))

    assert "zotero_item_data_too_deep" in codes(report)
    assert report.has_errors
    assert report.records == []
    # Nothing is lost: the whole payload is still in the citation instruction.
    assert report.citations[0].instruction == instruction


def test_two_alternate_content_choices_are_ambiguous_not_two_citations(tmp_path):
    # Word writes one mc:Choice and one mc:Fallback. Two Choices with
    # different content means the branch Word renders depends on which
    # extensions it understands -- which this reader cannot know.
    first = para(complex_field(zotero_instruction([zotero_item(key="CHOICE01")])))
    second = para(complex_field(zotero_instruction([zotero_item(key="CHOICE02")])))
    body = (
        "<mc:AlternateContent>"
        f'<mc:Choice Requires="one">{first}</mc:Choice>'
        f'<mc:Choice Requires="two">{second}</mc:Choice>'
        f"<mc:Fallback>{first}</mc:Fallback>"
        "</mc:AlternateContent>"
    )

    report = recover_references(simple_docx(tmp_path, body))

    assert len(report.citations) == 1  # the first Choice, as Word would pick
    assert "alternate_content_ambiguous" in codes(report)
    assert report.has_errors


def test_alternate_content_with_only_a_fallback_is_still_read(tmp_path):
    instruction = zotero_instruction([zotero_item()])
    body = (
        "<mc:AlternateContent><mc:Fallback>"
        + para(complex_field(instruction))
        + "</mc:Fallback></mc:AlternateContent>"
    )

    report = recover_references(simple_docx(tmp_path, body))

    assert len(report.citations) == 1  # nothing else offers the content
    assert len(report.records) == 1


def test_partly_deleted_instruction_is_ambiguous_not_a_deleted_citation(tmp_path):
    # Half of this instruction is deleted under Track Changes. Accepting and
    # rejecting the changes give different instructions, so calling the field
    # "deleted" (or quietly using one of the two readings) states more than
    # the document does.
    live = zotero_instruction([zotero_item()])
    field = (
        fld_char("begin")
        + instr_runs(live)
        + tracked("del", instr_runs(" obsolete instruction", deleted=True))
        + fld_char("separate")
        + fld_char("end")
    )

    report = recover_references(simple_docx(tmp_path, para(field)))

    assert "field_instruction_partly_deleted" in codes(report)
    assert report.has_errors
    assert "tracked_deletion_skipped" not in codes(report)
    assert len(report.citations) == 1
    assert report.citations[0].instruction == live + " obsolete instruction"


def test_citation_items_not_a_list_is_refused(tmp_path):
    instruction = 'ADDIN ZOTERO_ITEM CSL_CITATION {"citationItems": {"id": 1}}'
    report = recover_references(simple_docx(tmp_path, para(complex_field(instruction))))

    assert "zotero_citation_items_malformed" in codes(report)
    assert report.records == []


def test_mendeley_field_is_reported_not_labelled_zotero(tmp_path):
    # Mendeley's field carries CSL-JSON too, but with a different envelope
    # and different item identity. Calling it Zotero would put a false
    # provenance on every recovered record.
    instruction = 'ADDIN CSL_CITATION {"citationItems":[{"id":"x"}],"mendeley":{"formattedCitation":"(1)"}}'
    report = recover_references(simple_docx(tmp_path, para(complex_field(instruction))))

    assert [c.source for c in report.citations] == ["mendeley"]
    assert report.records == []
    assert "mendeley_field_unsupported" in codes(report)
    assert classify_instruction(instruction) == "mendeley"


def test_zotero_bookmark_storage_is_detected_and_reported(tmp_path):
    body = (
        '<w:bookmarkStart w:id="1" w:name="ZOTERO_BREF_9aQ1x2"/>'
        '<w:bookmarkEnd w:id="1"/>'
        + para("<w:r><w:t>(Belletti &amp; Zacker, 2011)</w:t></w:r>")
    )
    report = recover_references(simple_docx(tmp_path, body))

    assert "zotero_bookmarks_unsupported" in codes(report)
    assert report.records == []
    assert report.citations == []


def test_zotero_bibliography_field_is_not_a_citation_occurrence(tmp_path):
    instruction = 'ADDIN ZOTERO_BIBL {"uncited":[],"omitted":[],"custom":[]} CSL_BIBLIOGRAPHY'
    body = para(complex_field(zotero_instruction([zotero_item()]))) + para(
        complex_field(instruction)
    )

    report = recover_references(simple_docx(tmp_path, body))

    assert len(report.citations) == 1
    assert "bibliography_field_ignored" in codes(report)


def test_word_own_citation_field_is_named_not_recovered(tmp_path):
    body = para(complex_field(r"CITATION Bel11 \l 1033 "))

    report = recover_references(simple_docx(tmp_path, body))

    assert [c.source for c in report.citations] == ["word"]
    assert report.records == []
    assert "word_citation_field_unsupported" in codes(report)


# --- 3. EndNote XML ---------------------------------------------------------------


def test_endnote_journal_record_maps_to_csl_and_keeps_raw_xml(tmp_path):
    instruction = endnote_instruction(ENDNOTE_JOURNAL_RECORD)
    report = recover_references(simple_docx(tmp_path, para(complex_field(instruction))))

    record = report.records[0]
    assert record.source == "endnote"
    assert record.id == "endnote-0001"
    assert record.csl["type"] == "article-journal"
    assert record.csl["title"] == "Perspectives on electronic medical records adoption"
    assert record.csl["container-title"] == "Patient Related Outcome Measures"
    assert record.csl["volume"] == "2"
    assert record.csl["issue"] == "1"
    assert record.csl["page"] == "1-7"
    assert record.csl["issued"] == {"date-parts": [[2011]]}
    assert record.csl["DOI"] == "10.2147/prom.s8896"  # house canonical form
    assert record.csl["PMID"] == "22915966"
    assert record.csl["ISSN"] == "1179-271X"  # EndNote shares one field for both
    assert record.csl["URL"] == "https://example.org/article"
    assert record.csl["abstract"].startswith("An abstract")
    # Names are carried as the source wrote them: "Belletti, Dan A." is not
    # split into family/given, because that guess is wrong for particles,
    # compound surnames and institutional authors (model.AuthorName).
    assert record.csl["author"] == [
        {"literal": "Belletti, Dan A."},
        {"literal": "Zacker, Christopher"},
    ]
    assert isinstance(record.raw, str)
    assert "<rec-number>12</rec-number>" in record.raw
    assert "<custom3>a vendor field with no CSL equivalent</custom3>" in record.raw
    assert record.source_ids == ["endnote:db=s5wxr9v9k2f0:rec=12"]


def test_endnote_ref_type_name_determines_csl_type(tmp_path):
    instruction = endnote_instruction(ENDNOTE_BOOK_RECORD)
    report = recover_references(simple_docx(tmp_path, para(complex_field(instruction))))

    record = report.records[0]
    assert record.csl["type"] == "book"
    assert record.csl["title"] == "The Visual Display of Quantitative Information"
    assert record.csl["publisher"] == "Graphics Press"
    assert record.csl["publisher-place"] == "Cheshire, CT"
    assert record.csl["ISBN"] == "978-0961392147"  # book, so ISBN not ISSN
    # secondary-title on a book is the series, NOT a container.
    assert record.csl["collection-title"] == "Graphics Press Classics"
    assert "container-title" not in record.csl
    assert record.csl["editor"] == [{"literal": "Editor, An"}]


def test_endnote_unknown_ref_type_leaves_type_unset_and_reports(tmp_path):
    record_xml = ENDNOTE_JOURNAL_RECORD.replace(
        '<ref-type name="Journal Article">17</ref-type>',
        '<ref-type name="Aggregated Database">55</ref-type>',
    )
    report = recover_references(
        simple_docx(tmp_path, para(complex_field(endnote_instruction(record_xml))))
    )

    assert "endnote_ref_type_unmapped" in codes(report)
    assert "type" not in report.records[0].csl
    assert report.records[0].csl["title"]  # everything unambiguous still maps


def test_endnote_unmapped_fields_stay_in_raw_with_a_finding(tmp_path):
    report = recover_references(
        simple_docx(
            tmp_path, para(complex_field(endnote_instruction(ENDNOTE_JOURNAL_RECORD)))
        )
    )

    unmapped = [f for f in report.findings if f.code == "endnote_fields_unmapped"]
    assert unmapped, codes(report)
    assert "custom3" in unmapped[0].message
    assert "keywords" in unmapped[0].message
    assert unmapped[0].record_id == "endnote-0001"


def test_endnote_multiple_cites_in_one_field_become_multiple_records(tmp_path):
    instruction = endnote_instruction(ENDNOTE_JOURNAL_RECORD, ENDNOTE_BOOK_RECORD)
    report = recover_references(simple_docx(tmp_path, para(complex_field(instruction))))

    assert len(report.citations) == 1
    assert report.citations[0].record_ids == ["endnote-0001", "endnote-0002"]
    assert {r.csl["type"] for r in report.records} == {"article-journal", "book"}


def test_en_reflist_is_bibliography_machinery_not_an_occurrence(tmp_path):
    reflist = (
        "ADDIN EN.REFLIST <EndNote><Cite><Author>Belletti</Author>"
        f"{ENDNOTE_JOURNAL_RECORD}</Cite></EndNote>"
    )
    body = para(complex_field(endnote_instruction(ENDNOTE_JOURNAL_RECORD))) + para(
        complex_field(reflist)
    )

    report = recover_references(simple_docx(tmp_path, body))

    assert len(report.citations) == 1  # the bibliography is not a second citation
    assert len(report.records) == 1
    assert "bibliography_field_ignored" in codes(report)


def test_endnote_cite_without_a_record_is_an_error(tmp_path):
    # Traveling Library disabled: the field cites something the document does
    # not carry. Reporting this is the point -- "recovered nothing" must not
    # look like "there was nothing to recover".
    instruction = (
        "ADDIN EN.CITE <EndNote><Cite><Author>Belletti</Author>"
        "<Year>2011</Year><RecNum>12</RecNum></Cite></EndNote>"
    )
    report = recover_references(simple_docx(tmp_path, para(complex_field(instruction))))

    assert "endnote_cite_without_record" in codes(report)
    assert report.has_errors
    assert report.records == []
    assert report.citations[0].record_ids == []
    assert report.citations[0].instruction == instruction


def test_endnote_field_without_a_payload_is_an_error(tmp_path):
    report = recover_references(
        simple_docx(tmp_path, para(complex_field("ADDIN EN.CITE ")))
    )

    assert "endnote_payload_missing" in codes(report)
    assert report.has_errors


def test_endnote_malformed_payload_is_an_error(tmp_path):
    instruction = "ADDIN EN.CITE <EndNote><Cite><record><title>unclosed"
    report = recover_references(simple_docx(tmp_path, para(complex_field(instruction))))

    assert "endnote_payload_malformed" in codes(report)
    assert report.has_errors
    assert report.records == []


def test_endnote_payload_with_a_doctype_is_refused(tmp_path):
    # The hardened parser's rule reaches inside the field instruction too: an
    # entity-laced payload is refused before it is parsed, not after.
    instruction = (
        "ADDIN EN.CITE <!DOCTYPE EndNote [<!ENTITY xxe SYSTEM 'file:///etc/passwd'>]>"
        "<EndNote><Cite><record><titles><title>&xxe;</title></titles></record></Cite></EndNote>"
    )
    report = recover_references(simple_docx(tmp_path, para(complex_field(instruction))))

    assert "endnote_payload_unsafe" in codes(report)
    assert report.has_errors
    assert report.records == []


def test_endnote_unrecognized_doi_is_reported_not_invented(tmp_path):
    record_xml = ENDNOTE_JOURNAL_RECORD.replace(
        "<electronic-resource-num>10.2147/PROM.S8896</electronic-resource-num>",
        "<electronic-resource-num>see publisher website</electronic-resource-num>",
    )
    report = recover_references(
        simple_docx(tmp_path, para(complex_field(endnote_instruction(record_xml))))
    )

    assert "endnote_doi_unrecognized" in codes(report)
    assert "DOI" not in report.records[0].csl
    assert "see publisher website" in report.records[0].raw


def test_endnote_accession_number_is_only_a_pmid_when_the_database_says_so(tmp_path):
    record_xml = ENDNOTE_JOURNAL_RECORD.replace(
        "<remote-database-name>PubMed</remote-database-name>",
        "<remote-database-name>Web of Science</remote-database-name>",
    )
    report = recover_references(
        simple_docx(tmp_path, para(complex_field(endnote_instruction(record_xml))))
    )

    record = report.records[0]
    assert "PMID" not in record.csl  # a WoS accession number is not a PMID
    assert "22915966" in record.raw


def test_endnote_non_numeric_year_is_carried_as_written(tmp_path):
    record_xml = ENDNOTE_JOURNAL_RECORD.replace(
        "<year>2011</year>", "<year>in press</year>"
    )
    report = recover_references(
        simple_docx(tmp_path, para(complex_field(endnote_instruction(record_xml))))
    )

    assert report.records[0].csl["issued"] == {"raw": "in press"}


def test_endnote_absurd_year_is_carried_not_converted(tmp_path):
    # Found by the hostile probe: int("9" * 5000) raises ValueError in
    # CPython (the 4300-digit conversion limit), which escaped recovery as an
    # unnamed error. A number that long is not a year in any case.
    record_xml = ENDNOTE_JOURNAL_RECORD.replace(
        "<year>2011</year>", "<year>%s</year>" % ("9" * 5000)
    )
    report = recover_references(
        simple_docx(tmp_path, para(complex_field(endnote_instruction(record_xml))))
    )

    assert report.records[0].csl["issued"] == {"raw": "9" * 5000}


def test_endnote_record_without_a_database_id_is_not_identified_by_recnum(tmp_path):
    # RecNum is a row number in one person's library. Two libraries reuse it
    # constantly; merging on it alone would fuse unrelated references.
    first = """<record><rec-number>12</rec-number>
      <ref-type name="Book">6</ref-type>
      <titles><title>First book</title></titles></record>"""
    second = """<record><rec-number>12</rec-number>
      <ref-type name="Book">6</ref-type>
      <titles><title>A different book, same row number</title></titles></record>"""
    body = para(complex_field(endnote_instruction(first))) + para(
        complex_field(endnote_instruction(second))
    )

    report = recover_references(simple_docx(tmp_path, body))

    assert len(report.records) == 2
    assert all(record.source_ids == [] for record in report.records)
    assert "record_identity_conflict" not in codes(report)


# --- 4. identity: dedup and conflict ----------------------------------------------


def test_identical_records_cited_twice_are_one_record(tmp_path):
    instruction = zotero_instruction([zotero_item(key="SAME0001")])
    body = para(complex_field(instruction)) + para(complex_field(instruction))

    report = recover_references(simple_docx(tmp_path, body))

    assert len(report.records) == 1
    assert [c.record_ids for c in report.citations] == [["zotero-0001"], ["zotero-0001"]]
    assert not report.has_errors


def test_same_item_id_with_different_data_stays_two_records_and_is_reported(tmp_path):
    # The author edited the reference in their library between citations, or
    # two libraries collided on a URI. Merging would silently pick a winner.
    original = zotero_item(key="CONF0001")
    edited = zotero_item(key="CONF0001")
    edited["itemData"] = dict(edited["itemData"], title="A different title entirely")
    body = para(complex_field(zotero_instruction([original]))) + para(
        complex_field(zotero_instruction([edited]))
    )

    report = recover_references(simple_docx(tmp_path, body))

    assert len(report.records) == 2
    assert report.citations[0].record_ids == ["zotero-0001"]
    assert report.citations[1].record_ids == ["zotero-0002"]
    conflicts = [f for f in report.findings if f.code == "record_identity_conflict"]
    assert len(conflicts) == 1
    assert "zotero-0001" in conflicts[0].message
    assert conflicts[0].record_id == "zotero-0002"


def test_endnote_same_library_record_edited_between_citations_is_reported(tmp_path):
    edited = ENDNOTE_JOURNAL_RECORD.replace(
        "<volume>2</volume>", "<volume>3</volume>"
    )
    body = para(complex_field(endnote_instruction(ENDNOTE_JOURNAL_RECORD))) + para(
        complex_field(endnote_instruction(edited))
    )

    report = recover_references(simple_docx(tmp_path, body))

    assert len(report.records) == 2
    assert "record_identity_conflict" in codes(report)


def test_key_order_alone_does_not_make_two_records(tmp_path):
    item = zotero_item(key="ORDR0001")
    reordered = json.loads(json.dumps(item))
    reordered["itemData"] = dict(reversed(list(reordered["itemData"].items())))
    body = para(complex_field(zotero_instruction([item]))) + para(
        complex_field(zotero_instruction([reordered]))
    )

    report = recover_references(simple_docx(tmp_path, body))

    assert len(report.records) == 1
    assert "record_identity_conflict" not in codes(report)


def test_records_from_different_managers_never_merge(tmp_path):
    body = para(complex_field(zotero_instruction([zotero_item()]))) + para(
        complex_field(endnote_instruction(ENDNOTE_JOURNAL_RECORD))
    )

    report = recover_references(simple_docx(tmp_path, body))

    assert [r.id for r in report.records] == ["zotero-0001", "endnote-0001"]
    assert {r.source for r in report.records} == {"zotero", "endnote"}


def test_record_ids_are_deterministic_across_runs(tmp_path):
    body = (
        para(complex_field(endnote_instruction(ENDNOTE_JOURNAL_RECORD)))
        + para(complex_field(zotero_instruction([zotero_item(key="D0000001")])))
        + para(complex_field(zotero_instruction([zotero_item(key="D0000002")])))
    )
    docx = simple_docx(tmp_path, body)

    first = recover_references(docx).to_dict()
    second = recover_references(docx).to_dict()

    assert first == second
    assert [r["id"] for r in first["records"]] == [
        "endnote-0001",
        "zotero-0001",
        "zotero-0002",
    ]


# --- 5. package safety: hostile and broken input ------------------------------------


def test_source_hash_is_of_the_original_bytes_and_the_file_is_untouched(tmp_path):
    docx = simple_docx(tmp_path, para(complex_field(zotero_instruction([zotero_item()]))))
    before = sha256(docx)
    listing_before = sorted(p.name for p in tmp_path.iterdir())
    mtime_before = docx.stat().st_mtime_ns

    report = recover_references(docx)

    assert report.source_sha256 == before
    assert sha256(docx) == before
    assert docx.stat().st_mtime_ns == mtime_before
    assert sorted(p.name for p in tmp_path.iterdir()) == listing_before


def test_recovery_makes_no_network_calls(tmp_path, monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("recovery must not touch the network")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    docx = simple_docx(
        tmp_path, para(complex_field(endnote_instruction(ENDNOTE_JOURNAL_RECORD)))
    )

    assert len(recover_references(docx).records) == 1


def test_document_part_with_a_doctype_is_refused(tmp_path):
    docx = make_docx(
        tmp_path / "laced.docx",
        document='<!DOCTYPE w:document [<!ENTITY x "y">]><w:document xmlns:w="%s"/>' % W,
    )
    with pytest.raises(RecoveryError) as error:
        recover_references(docx)
    assert error.value.code == "document_part_unreadable"
    assert "doctype" in str(error.value).lower()


def test_footnotes_part_with_a_doctype_is_reported_and_the_body_still_recovers(tmp_path):
    docx = make_docx(
        tmp_path / "mixed.docx",
        document=document_xml(para(complex_field(zotero_instruction([zotero_item()])))),
        parts={"word/footnotes.xml": '<!DOCTYPE x><w:footnotes xmlns:w="%s"/>' % W},
        rels=[("footnotes", "footnotes.xml")],
    )

    report = recover_references(docx)

    assert "part_unreadable" in codes(report)
    assert report.has_errors
    assert len(report.records) == 1  # the readable part is still recovered


def test_duplicate_zip_members_are_refused(tmp_path):
    path = tmp_path / "dupes.docx"
    body = para(complex_field(zotero_instruction([zotero_item()])))
    make_docx(path, document=document_xml(body))
    with zipfile.ZipFile(path, "a") as package:
        package.writestr("word/document.xml", document_xml(para("<w:r><w:t>other</w:t></w:r>")))

    with pytest.raises(RecoveryError) as error:
        recover_references(path)
    assert error.value.code == "duplicate_zip_member"


def test_not_a_zip_is_refused_by_name(tmp_path):
    path = tmp_path / "prose.docx"
    path.write_bytes(b"This is not a package at all.")

    with pytest.raises(RecoveryError) as error:
        recover_references(path)
    assert error.value.code == "zip_unreadable"


def test_package_without_a_document_part_is_refused(tmp_path):
    path = tmp_path / "nodoc.docx"
    with zipfile.ZipFile(path, "w") as package:
        package.writestr("[Content_Types].xml", CONTENT_TYPES)

    with pytest.raises(RecoveryError) as error:
        recover_references(path)
    assert error.value.code == "document_part_missing"


def test_document_part_with_a_foreign_root_is_refused(tmp_path):
    docx = make_docx(tmp_path / "html.docx", document="<html><body/></html>")

    with pytest.raises(RecoveryError) as error:
        recover_references(docx)
    assert error.value.code == "document_root_unexpected"


def test_part_name_escaping_the_package_is_refused(tmp_path):
    path = tmp_path / "escape.docx"
    make_docx(path, document=document_xml(para("<w:r><w:t>x</w:t></w:r>")))
    with zipfile.ZipFile(path, "a") as package:
        package.writestr("../outside.xml", "<x/>")

    with pytest.raises(RecoveryError) as error:
        recover_references(path)
    assert error.value.code == "invalid_part_name"


def test_relationship_target_outside_the_package_is_skipped(tmp_path):
    docx = make_docx(
        tmp_path / "traversal.docx",
        document=document_xml(para(complex_field(zotero_instruction([zotero_item()])))),
        rels=[("header", "../../../etc/passwd")],
    )

    report = recover_references(docx)

    assert "relationship_target_invalid" in codes(report)
    assert len(report.records) == 1


def test_oversized_story_part_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(word_fields, "MAX_PART_BYTES", 4096)
    padding = "<w:r><w:t>%s</w:t></w:r>" % ("x" * 8192)
    docx = simple_docx(tmp_path, para(padding))

    with pytest.raises(RecoveryError) as error:
        recover_references(docx)
    assert error.value.code == "story_part_too_large"


def test_total_story_data_budget_is_enforced(tmp_path, monkeypatch):
    monkeypatch.setattr(word_fields, "MAX_TOTAL_BYTES", 3000)
    filler = header_xml(para("<w:r><w:t>%s</w:t></w:r>" % ("y" * 1500)))
    docx = make_docx(
        tmp_path / "big.docx",
        document=document_xml(para("<w:r><w:t>body</w:t></w:r>")),
        parts={f"word/header{n}.xml": filler for n in (1, 2, 3)},
        rels=[("header", f"header{n}.xml") for n in (1, 2, 3)],
    )

    with pytest.raises(RecoveryError) as error:
        recover_references(docx)
    assert error.value.code == "story_data_too_large"


def test_documented_limits_are_the_documented_values():
    assert word_fields.MAX_PART_BYTES == 16 * 1024 * 1024
    assert word_fields.MAX_TOTAL_BYTES == 64 * 1024 * 1024


def test_only_named_errors_escape_for_bad_input(tmp_path):
    cases = {
        "missing": lambda p: None,
        "directory": lambda p: p.mkdir(),
        "empty_file": lambda p: p.write_bytes(b""),
        "text_file": lambda p: p.write_bytes(b"hello there"),
        "empty_zip": lambda p: make_docx(p, drop=("word/document.xml",)),
        "truncated_zip": lambda p: p.write_bytes(b"PK\x03\x04" + b"\x00" * 40),
        "document_malformed": lambda p: make_docx(p, document="<w:p"),
    }
    for name, build in cases.items():
        path = tmp_path / f"{name}.docx"
        build(path)
        try:
            recover_references(path)
        except (RecoveryError, OSError) as error:
            assert not isinstance(error, RecoveryError) or error.code
        except Exception as error:  # noqa: BLE001 - the point of the test
            pytest.fail(f"{name} escaped with unnamed {type(error).__name__}: {error}")


# --- 6. the report itself -----------------------------------------------------------


def test_report_to_dict_is_json_serializable_and_labelled_unverified(tmp_path):
    body = para(complex_field(zotero_instruction([zotero_item()]))) + para(
        complex_field(endnote_instruction(ENDNOTE_JOURNAL_RECORD))
    )
    report = recover_references(simple_docx(tmp_path, body))

    payload = json.loads(json.dumps(report.to_dict()))

    assert payload["format"] == "citebind-recovery/1"
    assert payload["metadata_status"] == "recovered_not_verified"
    assert len(payload["records"]) == 2
    assert payload["citations"][0]["record_ids"] == ["zotero-0001"]
    assert payload["source_sha256"] == sha256(simple_docx(tmp_path, body, "again.docx"))


def test_every_citation_record_id_resolves_to_a_record(tmp_path):
    body = (
        para(complex_field(zotero_instruction([zotero_item(key="A1"), zotero_item(key="B2")])))
        + para(complex_field(endnote_instruction(ENDNOTE_JOURNAL_RECORD, ENDNOTE_BOOK_RECORD)))
        + para(complex_field(zotero_instruction([zotero_item(key="A1")])))
    )
    report = recover_references(simple_docx(tmp_path, body))

    known = by_id(report)
    assert len(known) == len(report.records)  # ids are unique
    for citation in report.citations:
        for record_id in citation.record_ids:
            assert record_id in known
    # Every record carries its own id in its CSL too, so an exported
    # CSL-JSON library has the same identities as the report.
    for record in report.records:
        assert record.csl["id"] == record.id


def test_a_real_python_docx_package_reads_clean_and_silent(tmp_path):
    # The generated fixtures above are minimal by design; this one is a whole
    # package as a real producer writes it (docProps, customXml, styles,
    # fontTable...). A recovery run over it must produce no records and no
    # noise: if ordinary parts raised findings, every real report would be
    # full of them and nobody would read the real ones.
    from docx import Document

    path = tmp_path / "plain.docx"
    document = Document()
    document.add_paragraph("Ordinary prose with no citations in it.")
    document.save(path)

    report = recover_references(path)

    assert report.records == []
    assert report.citations == []
    assert report.findings == []


def test_every_issue_code_word_fields_can_emit_has_a_severity():
    # word_fields reports structural issues by code; foreign.py owns the
    # severity table. A code in neither list still produces a finding (the
    # severity defaults to "error"), so a subset check alone passes while the
    # code silently escapes classification -- which is how part_rels_malformed
    # first shipped. Read the codes out of the source instead.
    import inspect
    import re

    from citebind.foreign import _SEVERITY

    emitted = set(
        re.findall(
            r'(?:Part|Field)Issue\(\s*"([a-z_]+)"', inspect.getsource(word_fields)
        )
    )
    assert emitted, "no issue codes found; the scan pattern no longer matches"
    assert emitted <= word_fields.ISSUE_CODES
    assert word_fields.ISSUE_CODES <= set(_SEVERITY)


def test_classify_instruction_names_each_supported_family():
    assert classify_instruction(zotero_instruction([zotero_item()])) == "zotero"
    assert classify_instruction(endnote_instruction(ENDNOTE_JOURNAL_RECORD)) == "endnote"
    assert classify_instruction("ADDIN EN.REFLIST <EndNote/>") == "bibliography"
    assert classify_instruction(" PAGE ") == "other"
    assert classify_instruction("") == "other"
