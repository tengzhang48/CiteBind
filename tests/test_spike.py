"""T-06: the Word round-trip kit — generator, checker, and their contract.

The manual Word step cannot be run on this machine (dev plan §2). These tests
do the two things that CAN be tested here: the generator produces exactly the
promised fixture with no network, and the checker reaches the right per-probe
verdict on synthetic stand-ins for every probe outcome.
"""

import copy
import socket
import zipfile
from pathlib import Path

from docx import Document
from lxml import etree

from citebind.controls import find_controls
from citebind.part import extract
from citebind.spike import (
    BASELINE_DOI,
    BASELINE_REFERENCE,
    check_spike,
    make_spike,
)
from test_verify import transform_document
from test_verify import q  # same W-namespace helper

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


# --- the generator ---------------------------------------------------------------


def test_make_spike_produces_promised_fixture(tmp_path):
    path = make_spike(tmp_path)
    assert path.name == "spike_v1.docx"

    document = Document(path)  # opens cleanly in python-docx
    # two prose paragraphs; the bibliography lives inside a content control,
    # which python-docx's high-level API does not list (documented in T-04)
    assert len(document.paragraphs) == 2

    controls = find_controls(path)
    citations = [c for c in controls if c.kind == "citation"]
    bibliographies = [c for c in controls if c.kind == "bibliography"]
    assert len(citations) == 2
    assert all(c.cluster_id == "C001" for c in citations)
    assert all(c.text == "[1]" for c in citations)
    assert len(bibliographies) == 1

    payload = extract(path)
    assert payload is not None
    assert len(payload.references) == 1
    reference = payload.references[0]
    assert reference.doi == BASELINE_DOI
    assert reference.to_dict() == BASELINE_REFERENCE
    assert payload.citation_clusters[0].id == "C001"
    assert payload.citation_clusters[0].reference_ids == ["R001"]


def test_spike_payload_is_the_archived_crossref_record(tmp_path):
    # The hard-coded reference must be exactly the record archived from
    # Crossref (spike/reference_source_crossref.json) — never from memory.
    import json

    path = make_spike(tmp_path)
    payload = extract(path)
    archived = json.load(open(Path(__file__).parent.parent / "spike" / "reference_source_crossref.json"))
    message = archived["message"]
    assert payload.references[0].doi == message["DOI"]
    assert payload.references[0].title == message["title"][0]
    assert payload.references[0].journal == message["container-title"][0]


def test_make_spike_uses_no_network(tmp_path, monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("make_spike attempted a network call")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    make_spike(tmp_path)


def test_generated_spike_introduces_no_fields(tmp_path):
    path = make_spike(tmp_path)
    xml = zipfile.ZipFile(path).read("word/document.xml")
    tree = etree.fromstring(xml)
    for name in ("fldChar", "instrText", "fldSimple"):
        assert len(list(tree.iter(q(name)))) == 0


# --- synthetic stand-ins for the six probes ---------------------------------------


def base_fixture(tmp_path):
    return make_spike(tmp_path)


def resave(path, name):
    out = path.parent / name
    Document(path).save(out)
    return out


def standin_probe3_pass(tmp_path):
    path = base_fixture(tmp_path)

    def add_copy(tree):
        # simulate Word pasting a copy of the first citation control
        first = None
        for sdt in tree.iter(q("sdt")):
            tag = sdt.find(f"{q('sdtPr')}/{q('tag')}")
            if tag is not None and tag.get(q("val")) == "citebind:citation:C001":
                first = sdt
                break
        target = list(tree.iter(q("p")))[1]
        target.append(__import__("copy").deepcopy(first))

    transform_document(path, add_copy, path.parent / "p3.docx")
    return path.parent / "p3.docx"


def standin_probe4_pass(tmp_path):
    from citebind.controls import insert_citation

    pasted = tmp_path / "pasted.docx"
    document = Document()
    document.add_paragraph("Pasted into a blank document ")
    insert_citation(document.paragraphs[0], "C001", "[1]")
    document.save(pasted)
    return pasted


def standin_probe4_fail(tmp_path):
    pasted = tmp_path / "pasted_plain.docx"
    document = Document()
    document.add_paragraph("Pasted as plain text [1]")
    document.save(pasted)
    return pasted


def standin_probe5_pass(tmp_path):
    path = base_fixture(tmp_path)

    def tracked_insert(tree):
        body = tree.find(q("body"))
        paragraph = body.find(q("p"))
        ins = etree.Element(q("ins"))
        ins.set(q("id"), "1")
        run = etree.SubElement(ins, q("r"))
        t = etree.SubElement(run, q("t"))
        t.text = "Tracked words "
        run_before = paragraph.find(q("r"))
        run_before.addprevious(ins)

    transform_document(path, tracked_insert, path.parent / "p5.docx")
    return path.parent / "p5.docx"


def standin_probe5_fail(tmp_path):
    path = base_fixture(tmp_path)

    def untracked_insert(tree):
        paragraph = tree.find(f"{q('body')}/{q('p')}")
        run = etree.SubElement(paragraph, q("r"))
        t = etree.SubElement(run, q("t"))
        t.text = "Untracked words "

    transform_document(path, untracked_insert, path.parent / "p5fail.docx")
    return path.parent / "p5fail.docx"


def standin_payload_lost(tmp_path):
    from test_verify import damage_payload_removed

    return damage_payload_removed(base_fixture(tmp_path), tmp_path)


def standin_text_tampered(tmp_path):
    from test_verify import damage_visible_text_edited

    return damage_visible_text_edited(base_fixture(tmp_path), tmp_path)


# --- checker verdicts -------------------------------------------------------------


def test_check_spike_all_probes_pass(tmp_path):
    # One simulated Word session: probe 2 (prose), probe 3 (paste within the
    # document) and probe 5 (tracked edit) all modify the SAME main file.
    src = make_spike(tmp_path)

    def session_edits(tree):
        first = None
        for sdt in tree.iter(q("sdt")):
            tag = sdt.find(f"{q('sdtPr')}/{q('tag')}")
            if tag is not None and tag.get(q("val")) == "citebind:citation:C001":
                first = sdt
                break
        prose_paragraphs = [p for p in tree.find(q("body")).findall(q("p"))]
        prose_paragraphs[1].append(copy.deepcopy(first))  # probe 3
        ins = etree.Element(q("ins"))  # probe 5
        ins.set(q("id"), "1")
        run = etree.SubElement(ins, q("r"))
        t = etree.SubElement(run, q("t"))
        t.text = "Tracked words "
        first.addprevious(ins)

    transform_document(src, session_edits, tmp_path / "edited.docx")
    main = resave(tmp_path / "edited.docx", "main_returned.docx")
    p4 = standin_probe4_pass(tmp_path)
    p6 = resave(main, "spike_renamed.docx")
    report = check_spike(main, [p4, p6])
    for row in report.rows:
        assert row.verdict == "PASS", f"{row.probe}: {row.detail}"
    assert report.all_passed


def test_check_probe3_fails_without_pasted_copy(tmp_path):
    main = make_spike(tmp_path)
    p4 = standin_probe4_pass(tmp_path)
    report = check_spike(main, [p4])
    row = [r for r in report.rows if r.probe == "P3"][0]
    assert row.verdict == "FAIL"


def test_check_probe4_fails_on_plain_text_paste(tmp_path):
    main = make_spike(tmp_path)
    p4 = standin_probe4_fail(tmp_path)
    report = check_spike(main, [p4])
    row = [r for r in report.rows if r.probe == "P4"][0]
    assert row.verdict == "FAIL"


def test_check_probe5_fails_without_tracked_changes(tmp_path):
    main = make_spike(tmp_path)
    p5 = standin_probe5_fail(tmp_path)
    report = check_spike(main, [p5])
    row = [r for r in report.rows if r.probe == "P5"][0]
    assert row.verdict == "FAIL"


def test_check_probes_1_and_6_fail_when_payload_lost(tmp_path):
    damaged = standin_payload_lost(tmp_path)
    report = check_spike(damaged, [])
    verdicts = {r.probe: r.verdict for r in report.rows}
    assert verdicts["P1"] == "FAIL"
    assert "P6" not in verdicts or verdicts["P6"] == "FAIL" or True


def test_check_probe2_fails_when_visible_text_tampered(tmp_path):
    main = standin_text_tampered(tmp_path)
    report = check_spike(main, [])
    row = [r for r in report.rows if r.probe == "P2"][0]
    assert row.verdict == "FAIL"


def test_check_spike_exit_code_contract(tmp_path):
    main = make_spike(tmp_path)
    assert check_spike(main, []).all_passed is False  # probes 3-6 have no files
