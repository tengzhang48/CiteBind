"""Independent integration checks for incomplete or ambiguous recovery."""

import json

import pytest

from citebind.foreign import recover_references
from citebind.reference_export import ExportError, export_references
from test_foreign import (
    complex_field, document_xml, fld_char, instr_runs, make_docx,
    para, simple_docx, tracked, zotero_instruction, zotero_item,
)


def test_unterminated_supported_field_cannot_be_exported_as_a_complete_library(tmp_path):
    field = fld_char("begin") + instr_runs(zotero_instruction([zotero_item()])) + fld_char("separate")
    report = recover_references(simple_docx(tmp_path, para(field)))
    assert report.records
    with pytest.raises(ExportError, match="recovery_incomplete"):
        export_references(report, "csl-json")


def test_missing_referenced_story_cannot_produce_a_complete_library(tmp_path):
    source = make_docx(tmp_path / "missing.docx",
        document=document_xml(para(complex_field(zotero_instruction([zotero_item()])))),
        rels=[("footnotes", "missing.xml")])
    report = recover_references(source)
    with pytest.raises(ExportError, match="recovery_incomplete"):
        export_references(report, "csl-json")


def test_conflicting_item_identity_requires_review_before_library_export(tmp_path):
    first, second = zotero_item(), zotero_item()
    second["itemData"]["title"] = "A conflicting title"
    body = para(complex_field(zotero_instruction([first, second])))
    report = recover_references(simple_docx(tmp_path, body))
    assert len(report.records) == 2
    with pytest.raises(ExportError, match="recovery_incomplete"):
        export_references(report, "csl-json")


def test_empty_citation_does_not_disappear_beside_a_valid_citation(tmp_path):
    body = para(complex_field(zotero_instruction([])), complex_field(zotero_instruction([zotero_item()])))
    report = recover_references(simple_docx(tmp_path, body))
    assert report.has_errors


def test_exponential_float_overflow_remains_available_as_a_diagnostic_report(tmp_path):
    instruction = 'ADDIN ZOTERO_ITEM CSL_CITATION {"citationItems":[{"itemData":{"type":"book","title":"T","volume":1e999}}]}'
    report = recover_references(simple_docx(tmp_path, para(complex_field(instruction))))
    assert report.has_errors
    assert json.loads(export_references(report, "report").text)["citations"]


def test_deep_foreign_json_is_reported_without_a_recursion_crash(tmp_path):
    nested = '[' * 600 + '0' + ']' * 600
    instruction = 'ADDIN ZOTERO_ITEM CSL_CITATION {"citationItems":[{"itemData":{"type":"book","title":"T","extra":' + nested + '}}]}'
    report = recover_references(simple_docx(tmp_path, para(complex_field(instruction))))
    assert report.has_errors
    assert json.loads(export_references(report, "report").text)["findings"]


def test_multiple_alternate_choices_are_not_counted_as_two_citations(tmp_path):
    one = para(complex_field(zotero_instruction([zotero_item()])))
    another = zotero_item(key="ALTERNAT")
    another["itemData"]["title"] = "Alternative rendering"
    two = para(complex_field(zotero_instruction([another])))
    body = '<mc:AlternateContent><mc:Choice Requires="one">' + one + '</mc:Choice><mc:Choice Requires="two">' + two + '</mc:Choice><mc:Fallback>' + one + '</mc:Fallback></mc:AlternateContent>'
    report = recover_references(simple_docx(tmp_path, body))
    assert len(report.citations) == 1
    assert report.has_errors  # the reader cannot establish the active Word branch


def test_partially_deleted_instruction_is_ambiguous_not_a_deleted_citation(tmp_path):
    field = fld_char("begin") + instr_runs(zotero_instruction([zotero_item()]))
    field += tracked("del", instr_runs("obsolete instruction", deleted=True))
    field += fld_char("separate") + fld_char("end")
    report = recover_references(simple_docx(tmp_path, para(field)))
    assert report.has_errors
