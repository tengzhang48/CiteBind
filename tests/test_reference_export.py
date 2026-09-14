"""Exchange files must not silently turn recovered data into different records."""

import json

import pytest
from lxml import etree

from citebind.reference_export import ExportError, export_references
from citebind.recovery_model import RecoveredRecord, RecoveryFinding, RecoveryReport


def recovered(csl=None, *, source="zotero", raw=None):
    item = csl or {
        "type": "book", "title": "A book without a DOI",
        "author": [{"family": "Smith", "given": "Alex"}],
        "issued": {"date-parts": [[2020, 5, 2]]},
        "publisher": "Example Press", "ISBN": "9780000000000",
    }
    return RecoveryReport("a" * 64, [RecoveredRecord(
        "zotero-0001", source, item, raw if raw is not None else dict(item)
    )])


def codes(result):
    return {finding.code for finding in result.findings}


def test_csl_json_keeps_book_type_and_all_source_csl_fields():
    report = recovered()
    report.records[0].csl.update({"PMID": "123456", "custom-field": {"value": "kept"}})
    result = export_references(report, "csl-json")
    items = json.loads(result.text)
    assert items[0] == {"id": "zotero-0001", **report.records[0].csl}
    assert "DOI" not in items[0]
    assert "id" not in report.records[0].csl
    assert "library_export_not_relinked" in codes(result)


def test_csl_export_replaces_colliding_local_ids_without_mutating_source():
    report = recovered()
    report.records[0].csl["id"] = 7
    report.records.append(RecoveredRecord("endnote-0002", "endnote", {
        "id": 7, "type": "article-journal", "title": "A different item"
    }, "<record/>"))
    assert [i["id"] for i in json.loads(export_references(report, "csl-json").text)] == [
        "zotero-0001", "endnote-0002"
    ]
    assert report.records[0].csl["id"] == 7


@pytest.mark.parametrize("fmt", ["csl-json", "ris", "bibtex", "endnote-xml"])
def test_library_export_refuses_incomplete_recovery(fmt):
    report = recovered()
    report.findings.append(RecoveryFinding("missing_item_data", "One citation lacks data", "error"))
    with pytest.raises(ExportError, match="recovery_incomplete"):
        export_references(report, fmt)


def test_full_report_remains_available_for_incomplete_recovery():
    report = recovered()
    report.findings.append(RecoveryFinding("broken_field", "Needs checking", "error"))
    value = json.loads(export_references(report, "report").text)
    assert value["metadata_status"] == "recovered_not_verified"
    assert value["records"][0]["raw"]["ISBN"] == "9780000000000"
    assert value["findings"][0]["code"] == "broken_field"


def test_ris_preserves_metadata_and_prevents_line_injection():
    report = recovered()
    report.records[0].csl["title"] = "A title\nER  -\nTY  - JOUR"
    report.records[0].csl["author"].append({"literal": "Example Research Group"})
    text = export_references(report, "ris").text
    assert text.startswith("TY  - BOOK\r\n")
    assert text.count("\nER  -") == 1
    assert text.count("\nTY  -") == 0
    assert "AU  - Smith, Alex\r\n" in text
    assert "AU  - Example Research Group\r\n" in text
    assert "SN  - 9780000000000\r\n" in text
    assert "DA  - 2020/05/02\r\n" in text
    assert "export_whitespace_normalized" in codes(export_references(report, "ris"))
    assert "export_literal_name" in codes(export_references(report, "ris"))


def test_ris_does_not_silently_drop_metadata():
    report = recovered()
    report.records[0].csl["original-title"] = "An earlier title"
    result = export_references(report, "ris")
    loss = [f for f in result.findings if f.code == "export_fields_omitted"]
    assert loss and "original-title" in loss[0].message
    assert loss[0].record_id == "zotero-0001"


def test_bibtex_escapes_metacharacters_and_protects_corporate_authors():
    report = recovered()
    report.records[0].csl["title"] = "A 50% gain & {braces}_test"
    report.records[0].csl["author"] = [{"literal": "Research and Development"}]
    result = export_references(report, "bibtex")
    assert "@book{zotero-0001," in result.text
    assert r"50\% gain \& \{braces\}\_test" in result.text
    assert "author = {{Research and Development}}" in result.text
    assert "export_date_precision_lost" in codes(result)


def test_unknown_ris_type_is_reported_instead_of_disguised_as_article():
    report = recovered({"type": "dataset", "title": "Data"})
    result = export_references(report, "ris")
    assert result.text.startswith("TY  - DATA\r\n")
    report.records[0].csl["type"] = "performance"
    result = export_references(report, "ris")
    assert result.text.startswith("TY  - GEN\r\n")
    assert "export_type_generalized" in codes(result)


def test_endnote_xml_retains_native_fields_and_styles():
    raw = '<record><ref-type name="Book">6</ref-type><titles><title><style face="italic">Title</style></title></titles><custom1>Keep me</custom1></record>'
    report = recovered(source="endnote", raw=raw)
    result = export_references(report, "endnote-xml")
    root = etree.fromstring(result.text.encode())
    assert root.tag == "xml"
    assert root.findtext("records/record/custom1") == "Keep me"
    assert root.find("records/record/titles/title/style").get("face") == "italic"
    assert root.findtext("records/record/titles/title") == ""
    assert etree.tostring(root.find("records/record"), method="c14n") == etree.tostring(etree.fromstring(raw.encode()), method="c14n")


def test_endnote_xml_refuses_mixed_sources_instead_of_dropping_zotero():
    report = recovered(source="endnote", raw="<record/>")
    report.records.append(RecoveredRecord("zotero-0002", "zotero", {"type": "book"}, {}))
    with pytest.raises(ExportError, match="endnote_source_required"):
        export_references(report, "endnote-xml")


def test_endnote_export_refuses_unsafe_xml():
    raw = '<!DOCTYPE record [<!ENTITY x "hidden">]><record><title>&x;</title></record>'
    with pytest.raises(ExportError, match="invalid_endnote_record"):
        export_references(recovered(source="endnote", raw=raw), "endnote-xml")


@pytest.mark.parametrize("fmt", ["csl-json", "ris", "bibtex"])
def test_export_refuses_missing_type_without_inventing_one(fmt):
    report = recovered({"title": "Unknown kind"})
    with pytest.raises(ExportError, match="export_type_missing"):
        export_references(report, fmt)


@pytest.mark.parametrize("fmt", ["ris", "bibtex"])
def test_malformed_csl_metadata_has_named_export_error(fmt):
    report = recovered({"type": "book", "author": ["not a CSL name object"]})
    with pytest.raises(ExportError, match="export_field_invalid"):
        export_references(report, fmt)


def test_empty_recovery_cannot_be_mistaken_for_a_successful_library_export():
    with pytest.raises(ExportError, match="no_recovered_references"):
        export_references(RecoveryReport("a" * 64), "csl-json")


def test_unknown_format_is_named():
    with pytest.raises(ExportError, match="export_format_unknown"):
        export_references(recovered(), "not-a-format")


@pytest.mark.parametrize("fmt", ["ris", "bibtex"])
def test_name_options_omitted_by_exchange_format_are_reported(fmt):
    report = recovered()
    report.records[0].csl["author"][0]["static-ordering"] = True
    result = export_references(report, fmt)
    assert "export_name_options_omitted" in codes(result)


@pytest.mark.parametrize("fmt", ["ris", "bibtex"])
def test_ambiguous_literal_and_personal_name_is_not_silently_reinterpreted(fmt):
    report = recovered()
    report.records[0].csl["author"] = [{"literal": "The Group", "family": "Smith"}]
    with pytest.raises(ExportError, match="export_field_invalid"):
        export_references(report, fmt)


def test_report_can_preserve_invalid_unicode_escape_from_foreign_json():
    report = recovered()
    report.records[0].raw["damaged-value"] = "\ud800"
    result = export_references(report, "report")
    assert json.loads(result.text.encode("utf-8"))["records"][0]["raw"]["damaged-value"] == "\ud800"


@pytest.mark.parametrize("fmt", ["ris", "bibtex"])
@pytest.mark.parametrize("bad_text", ["bad\x00title", "bad\ud800title"])
def test_invalid_exchange_text_has_named_error(fmt, bad_text):
    report = recovered({"type": "book", "title": bad_text})
    with pytest.raises(ExportError, match="export_field_invalid"):
        export_references(report, fmt)


@pytest.mark.parametrize("fmt", ["ris", "bibtex"])
def test_integer_strings_in_csl_dates_are_exportable_without_changing_source(fmt):
    report = recovered()
    report.records[0].csl["issued"] = {"date-parts": [["2011", "01", "2"]]}
    result = export_references(report, fmt)
    assert "2011" in result.text
    assert report.records[0].csl["issued"]["date-parts"] == [["2011", "01", "2"]]


@pytest.mark.parametrize("fmt", ["ris", "bibtex"])
def test_numeric_csl_variables_are_exported_and_coercion_is_reported(fmt):
    report = recovered({"type": "article-journal", "title": "Example", "volume": 12, "issue": 2, "page": 42})
    result = export_references(report, fmt)
    assert "12" in result.text and "42" in result.text
    assert "export_value_coerced" in codes(result)
    assert report.records[0].csl["volume"] == 12


def test_bad_field_error_identifies_the_reference():
    report = recovered({"type": "book", "issued": {"date-parts": [[2020, 99]]}})
    with pytest.raises(ExportError, match="zotero-0001.*invalid month"):
        export_references(report, "ris")


def test_ris_emits_separate_page_bounds_and_reports_shared_serial_tag():
    report = recovered({"type": "chapter", "page": "29-40", "ISBN": "book-id", "ISSN": "series-id"})
    result = export_references(report, "ris")
    assert "SP  - 29\r\nEP  - 40\r\n" in result.text
    assert "export_serial_numbers_ambiguous" in codes(result)


def test_bibtex_uses_month_name_and_reports_nonstandard_container():
    report = recovered({"type": "report", "title": "Report", "container-title": "Report series", "issued": {"date-parts": [[2020, 5]]}})
    result = export_references(report, "bibtex")
    assert "month = {May}" in result.text
    assert "export_nonstandard_container" in codes(result)


def test_nonfinite_value_in_report_gets_named_serialization_error():
    report = recovered()
    report.records[0].raw["invalid"] = float("nan")
    with pytest.raises(ExportError, match="export_json_invalid"):
        export_references(report, "report")
