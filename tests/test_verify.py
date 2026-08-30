"""T-05: structure verifier, round-trip differ, and minimal CLI.

Every damaged fixture is built by editing the DOCX XML directly — exactly
what an editor, a tool, or a bad handoff can do. The completeness test
enforces the design rule from the dev plan: the set of finding kinds is
exhaustive by construction, and adding a kind without a fixture that proves
it fails the suite.
"""

import copy
import zipfile

import pytest
from docx import Document
from lxml import etree

from citebind.controls import insert_bibliography, insert_citation
from citebind.model import CiteBindDocument
from citebind.part import embed
from citebind.__main__ import main
from citebind.verify import FindingKind, diff, inspect

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def q(name):
    return f"{{{W_NS}}}{name}"


PAYLOAD_DICT = {
    "schema_version": "1",
    "selected_style": "numeric",
    "references": [
        {
            "id": "R001",
            "doi": "10.1000/fixture-1",
            "title": "A Fixture Paper",
            "authors": ["Alpha Author"],
            "journal": "Journal of Fixtures",
            "year": 2024,
            "metadata_source": "crossref",
            "retrieved_at": "2026-08-29T00:00:00Z",
        }
    ],
    "citation_clusters": [
        {"id": "C001", "reference_ids": ["R001"]},
    ],
}


@pytest.fixture
def clean_spike(tmp_path):
    """A well-formed CiteBind document: R001, cluster C001 cited twice, bibliography."""
    path = tmp_path / "clean.docx"
    document = Document()
    document.add_paragraph("As shown by prior work ")
    document.add_paragraph("and confirmed again ")
    document.add_paragraph("Ordinary prose untouched by citations.")
    paragraphs = document.paragraphs
    insert_citation(paragraphs[0], "C001", "[1]")
    insert_citation(paragraphs[1], "C001", "[1]")
    insert_bibliography(document, ["A. Author. A Fixture Paper. Journal of Fixtures, 2024."])
    docx_path = tmp_path / "plain.docx"
    document.save(docx_path)
    payload = CiteBindDocument.from_dict(copy.deepcopy(PAYLOAD_DICT))
    embed(docx_path, payload, path)
    return path


def rewrite_xml(src, part, transform, dst):
    with zipfile.ZipFile(src) as zin:
        tree = etree.fromstring(zin.read(part))
        transform(tree)
        new = etree.tostring(tree, xml_declaration=True, encoding="UTF-8", standalone=True)
        with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                if item.filename == part:
                    zout.writestr(item.filename, new)
                else:
                    zout.writestr(item.filename, zin.read(item.filename))


def citebind_part(path):
    with zipfile.ZipFile(path) as source:
        for name in source.namelist():
            if name.startswith("customXml/item") and name.endswith(".xml"):
                root = etree.fromstring(zipfile.ZipFile(path).read(name))
                if root.tag == "{urn:citebind:citebind:1}document":
                    return name
    raise AssertionError("no citebind payload part found")


def drop_citebind_part(src, dst):
    part = citebind_part(src)
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            if item.filename == part:
                continue
            zout.writestr(item.filename, zin.read(item.filename))


def transform_document(src, transform, dst):
    rewrite_xml(src, "word/document.xml", transform, dst)


def transform_payload(src, transform, dst):
    rewrite_xml(src, citebind_part(src), transform, dst)


def first_citation_sdt(tree):
    for sdt in tree.iter(q("sdt")):
        tag = sdt.find(f"{q('sdtPr')}/{q('tag')}")
        if tag is not None and (tag.get(q("val")) or "").startswith("citebind:citation:"):
            return sdt
    raise AssertionError("no citation control found")


# --- damage fixtures, one per acceptance case ----------------------------------


def damage_payload_removed(clean_spike, tmp_path):
    out = tmp_path / "d1.docx"
    drop_citebind_part(clean_spike, out)
    return out


def damage_controls_stripped(clean_spike, tmp_path):
    out = tmp_path / "d2.docx"

    def strip(tree):
        for sdt in list(tree.iter(q("sdt"))):
            parent = sdt.getparent()
            if parent is not None:
                parent.remove(sdt)

    transform_document(clean_spike, strip, out)
    return out


def damage_tag_renamed(clean_spike, tmp_path):
    out = tmp_path / "d3.docx"

    def rename(tree):
        for sdt in tree.iter(q("sdt")):
            tag = sdt.find(f"{q('sdtPr')}/{q('tag')}")
            if tag is not None and (tag.get(q("val")) or "").startswith("citebind:citation:"):
                tag.set(q("val"), "some:other:tool")

    transform_document(clean_spike, rename, out)
    return out


def damage_reference_deleted(clean_spike, tmp_path):
    out = tmp_path / "d4.docx"

    def delete_reference(tree):
        for node in tree.iter("{urn:citebind:citebind:1}reference"):
            node.getparent().remove(node)

    transform_payload(clean_spike, delete_reference, out)
    return out


def damage_visible_text_edited(clean_spike, tmp_path):
    out = tmp_path / "d5.docx"

    def edit_text(tree):
        t = first_citation_sdt(tree).find(f"{q('sdtContent')}/{q('r')}/{q('t')}")
        t.text = "[7]"

    transform_document(clean_spike, edit_text, out)
    return out


# --- acceptance case 6 + the five damage cases ---------------------------------


def test_clean_document_reports_zero_findings(clean_spike):
    report = inspect(clean_spike)
    assert report.findings == []


def test_plain_docx_without_citebind_reports_zero_findings(tmp_path):
    path = tmp_path / "plain.docx"
    document = Document()
    document.add_paragraph("Nothing to see here.")
    document.save(path)
    report = inspect(path)
    assert report.findings == []
    assert report.has_payload is False


def test_payload_removed_is_detected_by_name(clean_spike, tmp_path):
    report = inspect(damage_payload_removed(clean_spike, tmp_path))
    kinds = [f.kind for f in report.findings]
    assert kinds == [FindingKind.PAYLOAD_PART_MISSING]


def test_controls_stripped_is_detected_by_name(clean_spike, tmp_path):
    report = inspect(damage_controls_stripped(clean_spike, tmp_path))
    kinds = {f.kind for f in report.findings}
    assert FindingKind.CONTROL_MISSING_FOR_CLUSTER in kinds
    assert FindingKind.BIBLIOGRAPHY_CONTROL_MISSING in kinds
    assert FindingKind.CONTROL_TAG_UNRECOGNIZED not in kinds


def test_renamed_tag_is_detected_distinctly_from_stripping(clean_spike, tmp_path):
    report = inspect(damage_tag_renamed(clean_spike, tmp_path))
    kinds = {f.kind for f in report.findings}
    assert FindingKind.CONTROL_MISSING_FOR_CLUSTER in kinds
    assert FindingKind.CONTROL_TAG_UNRECOGNIZED in kinds


def test_dangling_cluster_reference_is_detected_by_name(clean_spike, tmp_path):
    report = inspect(damage_reference_deleted(clean_spike, tmp_path))
    kinds = {f.kind for f in report.findings}
    assert FindingKind.DANGLING_CLUSTER_REFERENCE in kinds
    assert FindingKind.PAYLOAD_INVALID not in kinds


def test_hand_edited_visible_text_is_detected(clean_spike, tmp_path):
    report = inspect(damage_visible_text_edited(clean_spike, tmp_path))
    kinds = {f.kind for f in report.findings}
    assert FindingKind.CITATION_CONTROLS_INCONSISTENT in kinds


# --- report content ------------------------------------------------------------


def test_report_carries_structure(clean_spike):
    report = inspect(clean_spike)
    assert report.has_payload is True
    assert report.schema_version == "1"
    assert report.selected_style == "numeric"
    assert report.reference_ids == ["R001"]
    assert report.cluster_ids == ["C001"]
    assert sorted(report.control_tags) == [
        "citebind:bibliography",
        "citebind:citation:C001",
        "citebind:citation:C001",
    ]
    assert report.inventory["sdt"] == 3
    assert report.inventory["fldChar"] == 0
    assert report.inventory["instrText"] == 0
    assert report.inventory["fldSimple"] == 0


# --- every finding kind has a fixture that proves it (exhaustive by design) ----


def fixture_duplicate_reference_id(clean_spike, tmp_path):
    out = tmp_path / "dup_ref.docx"

    def duplicate(tree):
        refs = tree.find("{urn:citebind:citebind:1}references")
        clone = copy.deepcopy(refs[0])
        refs.append(clone)

    transform_payload(clean_spike, duplicate, out)
    return out


def fixture_duplicate_cluster_id(clean_spike, tmp_path):
    out = tmp_path / "dup_cluster.docx"

    def duplicate(tree):
        clusters = tree.find("{urn:citebind:citebind:1}citation_clusters")
        clone = copy.deepcopy(clusters[0])
        clusters.append(clone)

    transform_payload(clean_spike, duplicate, out)
    return out


def fixture_payload_invalid(clean_spike, tmp_path):
    out = tmp_path / "invalid.docx"

    def drop_style(tree):
        style = tree.find("{urn:citebind:citebind:1}selected_style")
        style.getparent().remove(style)

    transform_payload(clean_spike, drop_style, out)
    return out


def fixture_reference_uncited(clean_spike, tmp_path):
    from citebind.model import Reference

    out = tmp_path / "uncited.docx"
    document = Document(clean_spike)
    payload = CiteBindDocument.from_dict(copy.deepcopy(PAYLOAD_DICT))
    payload.references.append(
        Reference(
            id="R002",
            doi="10.1000/fixture-2",
            title="Uncited Record",
            authors=["Beta Author"],
            journal="Journal of Fixtures II",
            year=2023,
            metadata_source="crossref",
            retrieved_at="2026-08-29T00:00:00Z",
        )
    )
    fresh = tmp_path / "fresh.docx"
    document.save(fresh)
    plain = tmp_path / "plain2.docx"
    document.save(plain)
    insert_citation(document.paragraphs[0], "C001", "[1]")
    insert_bibliography(document, ["A. Author. A Fixture Paper. Journal of Fixtures, 2024."])
    embed(plain, payload, out)
    return out


def fixture_control_tag_without_cluster(clean_spike, tmp_path):
    out = tmp_path / "orphan_control.docx"

    def drop_clusters(tree):
        clusters = tree.find("{urn:citebind:citebind:1}citation_clusters")
        clusters.getparent().remove(clusters)

    transform_payload(clean_spike, drop_clusters, out)
    return out


def fixture_citation_control_empty(clean_spike, tmp_path):
    out = tmp_path / "empty_text.docx"

    def empty_text(tree):
        t = first_citation_sdt(tree).find(f"{q('sdtContent')}/{q('r')}/{q('t')}")
        t.text = ""

    transform_document(clean_spike, empty_text, out)
    return out


def fixture_bibliography_count_mismatch(clean_spike, tmp_path):
    out = tmp_path / "bib_mismatch.docx"

    def add_entry(tree):
        for sdt in tree.iter(q("sdt")):
            tag = sdt.find(f"{q('sdtPr')}/{q('tag')}")
            if tag is not None and tag.get(q("val")) == "citebind:bibliography":
                content = sdt.find(q("sdtContent"))
                p = etree.SubElement(content, q("p"))
                r = etree.SubElement(p, q("r"))
                t = etree.SubElement(r, q("t"))
                t.text = "Phantom entry that nobody cited."

    transform_document(clean_spike, add_entry, out)
    return out


FIXTURE_FOR_KIND = {
    FindingKind.PAYLOAD_PART_MISSING: damage_payload_removed,
    FindingKind.PAYLOAD_INVALID: fixture_payload_invalid,
    FindingKind.DUPLICATE_REFERENCE_ID: fixture_duplicate_reference_id,
    FindingKind.DUPLICATE_CLUSTER_ID: fixture_duplicate_cluster_id,
    FindingKind.DANGLING_CLUSTER_REFERENCE: damage_reference_deleted,
    FindingKind.REFERENCE_UNCITED: fixture_reference_uncited,
    FindingKind.CONTROL_MISSING_FOR_CLUSTER: damage_controls_stripped,
    FindingKind.CONTROL_TAG_WITHOUT_CLUSTER: fixture_control_tag_without_cluster,
    FindingKind.CONTROL_TAG_UNRECOGNIZED: damage_tag_renamed,
    FindingKind.CITATION_CONTROL_EMPTY: fixture_citation_control_empty,
    FindingKind.CITATION_CONTROLS_INCONSISTENT: damage_visible_text_edited,
    FindingKind.BIBLIOGRAPHY_CONTROL_MISSING: damage_controls_stripped,
    FindingKind.BIBLIOGRAPHY_COUNT_MISMATCH: fixture_bibliography_count_mismatch,
}


def test_every_finding_kind_is_covered_by_a_fixture():
    assert set(FIXTURE_FOR_KIND) == set(FindingKind)


@pytest.mark.parametrize("kind", sorted(FindingKind, key=lambda k: k.value))
def test_each_damage_mode_is_detected_and_named(clean_spike, tmp_path, kind):
    damaged = FIXTURE_FOR_KIND[kind](clean_spike, tmp_path)
    report = inspect(damaged)
    assert kind in [f.kind for f in report.findings], (
        f"{kind.value} not detected; got {[f.kind.value for f in report.findings]}"
    )


def test_findings_carry_severity(clean_spike, tmp_path):
    report = inspect(damage_reference_deleted(clean_spike, tmp_path))
    dangling = [f for f in report.findings if f.kind == FindingKind.DANGLING_CLUSTER_REFERENCE]
    assert dangling[0].severity == "error"
    report = inspect(fixture_reference_uncited(clean_spike, tmp_path))
    uncited = [f for f in report.findings if f.kind == FindingKind.REFERENCE_UNCITED]
    assert uncited[0].severity == "warning"


# --- diff ------------------------------------------------------------------------


def test_diff_of_identical_documents_is_clean(clean_spike):
    report = diff(clean_spike, clean_spike)
    assert report.items == []


def test_diff_detects_control_text_alteration(clean_spike, tmp_path):
    damaged = damage_visible_text_edited(clean_spike, tmp_path)
    report = diff(clean_spike, damaged)
    kinds = [item.kind for item in report.items]
    assert [k.name for k in kinds] == ["CONTROL_TEXT_ALTERED"]


def test_diff_detects_payload_loss(clean_spike, tmp_path):
    damaged = damage_payload_removed(clean_spike, tmp_path)
    report = diff(clean_spike, damaged)
    assert "PAYLOAD_LOST" in [i.kind.name for i in report.items]


def test_diff_detects_introduced_fields(clean_spike, tmp_path):
    out = tmp_path / "fields.docx"

    def inject_field(tree):
        p = tree.find(f"{q('body')}/{q('p')}")
        r1 = etree.SubElement(p, q("r"))
        fld = etree.SubElement(r1, q("fldChar"))
        fld.set(q("fldCharType"), "begin")
        r2 = etree.SubElement(p, q("r"))
        instr = etree.SubElement(r2, q("instrText"))
        instr.text = " PAGE "
        r3 = etree.SubElement(p, q("r"))
        fld2 = etree.SubElement(r3, q("fldChar"))
        fld2.set(q("fldCharType"), "end")

    transform_document(clean_spike, inject_field, out)
    report = diff(clean_spike, out)
    assert "FIELD_INTRODUCED" in [i.kind.name for i in report.items]


def test_diff_detects_renamed_control(clean_spike, tmp_path):
    out = tmp_path / "renamed.docx"

    def rename(tree):
        for sdt in tree.iter(q("sdt")):
            tag = sdt.find(f"{q('sdtPr')}/{q('tag')}")
            if tag is not None and tag.get(q("val")) == "citebind:citation:C001":
                tag.set(q("val"), "citebind:citation:C009")
                return

    transform_document(clean_spike, rename, out)
    report = diff(clean_spike, out)
    names = [i.kind.name for i in report.items]
    assert "CONTROL_RENAMED" in names
    assert "CONTROL_LOST" not in names


def test_diff_detects_gained_reference(clean_spike, tmp_path):
    out = tmp_path / "more_refs.docx"
    payload = CiteBindDocument.from_dict(copy.deepcopy(PAYLOAD_DICT))
    from citebind.model import Reference

    payload.references.append(
        Reference(
            id="R002",
            doi="10.1000/fixture-2",
            title="Second Record",
            authors=["Beta Author"],
            journal="Journal of Fixtures II",
            year=2023,
            metadata_source="crossref",
            retrieved_at="2026-08-29T00:00:00Z",
        )
    )
    payload.citation_clusters.append(
        __import__("citebind.model", fromlist=["CitationCluster"]).CitationCluster(
            id="C002", reference_ids=["R002"]
        )
    )
    plain = tmp_path / "plain3.docx"
    Document(clean_spike).save(plain)
    embed(plain, payload, out)
    report = diff(clean_spike, out)
    names = [i.kind.name for i in report.items]
    assert "REFERENCE_GAINED" in names
    assert "CLUSTER_GAINED" in names


# --- CLI -------------------------------------------------------------------------


def test_cli_inspect_exit_codes(clean_spike, tmp_path, capsys):
    assert main(["inspect", str(clean_spike)]) == 0
    damaged = damage_reference_deleted(clean_spike, tmp_path)
    assert main(["inspect", str(damaged)]) == 1
    out = capsys.readouterr().out
    assert "dangling_cluster_reference" in out


def test_cli_diff_exit_codes(clean_spike, tmp_path, capsys):
    damaged = damage_visible_text_edited(clean_spike, tmp_path)
    assert main(["diff", str(clean_spike), str(clean_spike)]) == 0
    assert main(["diff", str(clean_spike), str(damaged)]) == 1
    out = capsys.readouterr().out
    assert "control_text_altered" in out


def test_cli_gives_clean_error_not_traceback_for_non_docx(tmp_path, capsys):
    bad = tmp_path / "notes.txt"
    bad.write_text("not a docx")
    assert main(["inspect", str(bad)]) == 2
    err = capsys.readouterr().err
    # message names the file and the problem; never a traceback
    assert err.startswith("error:") and "notes.txt" in err
    assert "Traceback" not in err
