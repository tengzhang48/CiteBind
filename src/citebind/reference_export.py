"""Export recovered bibliographic records without touching a Word document.

The JSON recovery report retains source payloads. Exchange formats carry
library metadata, not Word field identity or citation-specific locators.
"""

import copy
import json
import math
import re
from dataclasses import dataclass, field

from lxml import etree

from .recovery_model import RecoveryFinding, RecoveryReport
from .xmlsafe import UnsafeXML, parse_xml_hardened

FORMATS = ("report", "csl-json", "ris", "bibtex", "endnote-xml")

# A reader can successfully report partial evidence with warnings. Publishing
# that evidence as a library needs a stricter gate: missing stories, ambiguous
# identities, broken field boundaries or recognized unreadable citations may
# leave references out even when the recovered records themselves are valid.
_INCOMPLETE_RECOVERY = frozenset({
    "part_missing", "part_rels_malformed", "part_root_unexpected",
    "relationship_target_invalid", "story_part_limit_reached",
    "field_unterminated", "field_end_without_begin", "instruction_outside_field",
    "record_identity_conflict", "mendeley_field_unsupported",
    "mendeley_bookmarks_unsupported", "zotero_bookmarks_unsupported",
    "zotero_temp_unsupported", "endnote_variant_unsupported",
    "word_citation_field_unsupported",
})


class ExportError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


@dataclass
class ReferenceExport:
    text: str
    findings: list[RecoveryFinding] = field(default_factory=list)


_RIS_TYPES = {
    "article-journal": "JOUR", "article-magazine": "MGZN",
    "article-newspaper": "NEWS", "book": "BOOK", "chapter": "CHAP",
    "paper-conference": "CPAPER", "report": "RPRT", "thesis": "THES",
    "webpage": "ELEC", "dataset": "DATA", "patent": "PAT",
    "software": "COMP", "manuscript": "UNPB",
}
_BIB_TYPES = {
    "article-journal": "article", "article-magazine": "article",
    "article-newspaper": "article", "book": "book", "chapter": "incollection",
    "paper-conference": "inproceedings", "report": "techreport",
    "thesis": "misc", "manuscript": "unpublished",
}
_RIS_FIELDS = {
    "title": "TI", "container-title": "T2", "publisher": "PB",
    "publisher-place": "CY", "volume": "VL", "issue": "IS",
    "page": "SP", "DOI": "DO", "URL": "UR", "ISBN": "SN",
    "ISSN": "SN", "abstract": "AB", "edition": "ET", "language": "LA",
}
_BIB_FIELDS = {
    "title": "title", "publisher": "publisher", "publisher-place": "address",
    "volume": "volume", "issue": "number", "page": "pages", "DOI": "doi",
    "URL": "url", "ISBN": "isbn", "ISSN": "issn", "abstract": "abstract",
    "edition": "edition", "language": "language", "PMID": "pmid",
}


def _warn(findings, code, message, record_id=None):
    findings.append(RecoveryFinding(code, message, record_id=record_id))


def _text(value, where):
    if not isinstance(value, str):
        raise ExportError("export_field_invalid", f"{where} must be a string")
    if any(ord(char) < 32 and char not in "\r\n\t" or ord(char) == 127 for char in value):
        raise ExportError("export_field_invalid", f"{where} contains an unsupported control character")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ExportError("export_field_invalid", f"{where} contains invalid Unicode") from error
    return value


def _single_line(value, where, findings, record_id):
    if where in {"volume", "issue", "page", "edition", "PMID"} and isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and not math.isfinite(value):
            raise ExportError("export_field_invalid", f"{where} is not finite")
        value = str(value)
        _warn(findings, "export_value_coerced", f"Numeric {where} converted to exchange-file text", record_id)
    value = _text(value, where)
    # RIS uses newlines as record boundaries. Normalize all separators before
    # adding tags so metadata cannot create another bibliographic record.
    normalized = " ".join(value.split())
    if normalized != value:
        _warn(findings, "export_whitespace_normalized",
              f"Whitespace in {where} was normalized for the exchange format", record_id)
    return normalized


def _names(value, where, findings, record_id):
    if not isinstance(value, list):
        raise ExportError("export_field_invalid", f"{where} must be a list of CSL names")
    for name in value:
        if not isinstance(name, dict):
            raise ExportError("export_field_invalid", f"{where} contains a non-object name")
        if not name.get("literal") and not name.get("family"):
            raise ExportError("export_field_invalid", f"{where} name has no literal or family")
        if "literal" in name and any(key in name for key in (
            "family", "given", "suffix", "dropping-particle", "non-dropping-particle"
        )):
            raise ExportError("export_field_invalid", f"{where} name mixes literal and personal-name data")
        omitted = set(name) - {"literal", "family", "given", "suffix", "dropping-particle", "non-dropping-particle"}
        if omitted:
            _warn(findings, "export_name_options_omitted",
                  f"{where} name options omitted: {', '.join(sorted(omitted))}", record_id)
        for key, item in name.items():
            if key in {"literal", "family", "given", "suffix", "dropping-particle", "non-dropping-particle"}:
                _text(item, f"{where}.{key}")
        yield name


def _name_parts(name):
    family = " ".join(filter(None, (name.get("non-dropping-particle"), name.get("family"))))
    given = " ".join(filter(None, (name.get("given"), name.get("dropping-particle"))))
    return family, given, name.get("suffix", "")


def _date(value, where):
    if not isinstance(value, dict):
        raise ExportError("export_field_invalid", f"{where} must be a CSL date object")
    parts = value.get("date-parts")
    if parts is not None:
        if (not isinstance(parts, list) or not parts or not isinstance(parts[0], list)
                or not 1 <= len(parts[0]) <= 3):
            raise ExportError("export_field_invalid", f"{where} has invalid date-parts")
        first = []
        for part in parts[0]:
            if isinstance(part, int) and not isinstance(part, bool):
                first.append(part)
            elif isinstance(part, str) and re.fullmatch(r"-?[0-9]+", part):
                try:
                    first.append(int(part))
                except ValueError as error:
                    raise ExportError("export_field_invalid", f"{where} has an invalid date number") from error
            else:
                raise ExportError("export_field_invalid", f"{where} has invalid date-parts")
        if len(first) > 1 and not 1 <= first[1] <= 12:
            raise ExportError("export_field_invalid", f"{where} has invalid month")
        if len(first) > 2 and not 1 <= first[2] <= 31:
            raise ExportError("export_field_invalid", f"{where} has invalid day")
        return first, None
    literal = value.get("literal", value.get("raw"))
    if literal is not None:
        return None, _text(literal, where)
    raise ExportError("export_field_invalid", f"{where} has no date-parts or literal")


def _omissions(csl, used, findings, record_id):
    omitted = sorted(set(csl) - used - {"id", "type"})
    if omitted:
        _warn(findings, "export_fields_omitted",
              "Exchange format omits CSL fields: " + ", ".join(omitted)
              + "; use the recovery report or CSL-JSON to retain them", record_id)


def _ris(record, findings):
    csl, rid = record.csl, record.id
    kind = _RIS_TYPES.get(csl["type"], "GEN")
    if kind == "GEN":
        _warn(findings, "export_type_generalized", f"CSL type {csl['type']!r} exported as RIS GEN", rid)
    rows = [f"TY  - {kind}", f"ID  - {rid}"]
    used = set(_RIS_FIELDS) | {"author", "editor", "issued", "PMID"}
    for key, tag in _RIS_FIELDS.items():
        if key in csl:
            value = _single_line(csl[key], key, findings, rid)
            if key == "page":
                bounds = re.fullmatch(r"([A-Za-z]*[0-9]+)\s*[-\u2013]\s*([A-Za-z]*[0-9]+)", value)
                if bounds:
                    rows.extend([f"SP  - {bounds[1]}", f"EP  - {bounds[2]}"])
                    continue
                if not re.fullmatch(r"[A-Za-z]*[0-9]+", value):
                    _warn(findings, "export_page_range_unparsed", "Page expression retained in RIS SP; importer handling may vary", rid)
            rows.append(f"{tag}  - {value}")
    if "ISBN" in csl and "ISSN" in csl:
        _warn(findings, "export_serial_numbers_ambiguous", "ISBN and ISSN both use RIS SN; some importers retain only one", rid)
    for key, tag in (("author", "AU"), ("editor", "ED")):
        for name in _names(csl.get(key, []), key, findings, rid):
            if name.get("literal"):
                value = name["literal"]
                _warn(findings, "export_literal_name", f"RIS {tag} retains the literal {key} text; corporate-name interpretation varies by importer", rid)
            else:
                family, given, suffix = _name_parts(name)
                value = ", ".join(filter(None, (family, given, suffix)))
            rows.append(f"{tag}  - {_single_line(value, key, findings, rid)}")
    if "PMID" in csl:
        rows.append("AN  - PMID:" + _single_line(csl["PMID"], "PMID", findings, rid))
        _warn(findings, "export_pmid_accession", "PMID stored as a labelled RIS accession number; importer support varies", rid)
    if "issued" in csl:
        date, literal = _date(csl["issued"], "issued")
        if date:
            rows.extend([f"PY  - {date[0]}", "DA  - " + "/".join(
                str(n) if i == 0 else f"{n:02d}" for i, n in enumerate(date))])
            if len(csl["issued"].get("date-parts", [])) > 1 or set(csl["issued"]) - {"date-parts"}:
                _warn(findings, "export_date_precision_lost", "RIS retains the first issued date; ranges/qualifiers remain in the recovery report", rid)
        elif literal is not None:
            rows.append("Y1  - " + _single_line(literal, "issued.literal", findings, rid))
            _warn(findings, "export_literal_date", "Unparsed issued date stored as RIS Y1; importer support varies", rid)
    _omissions(csl, used, findings, rid)
    return "\r\n".join(rows + ["ER  -", ""])


def _bib_escape(value):
    replacements = {"\\": r"\textbackslash{}", "{": r"\{", "}": r"\}",
                    "$": r"\$", "%": r"\%", "&": r"\&", "_": r"\_",
                    "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}
    return "".join(replacements.get(char, char) for char in value)


def _bibtex(record, findings):
    csl, rid = record.csl, record.id
    kind = _BIB_TYPES.get(csl["type"], "misc")
    if kind == "misc":
        _warn(findings, "export_type_generalized", f"CSL type {csl['type']!r} exported as BibTeX misc", rid)
    values = []
    fields = dict(_BIB_FIELDS)
    fields["container-title"] = "journal" if kind == "article" else "booktitle"
    if "container-title" in csl and kind not in {"article", "incollection", "inproceedings"}:
        _warn(findings, "export_nonstandard_container", "Container title retained as booktitle; standard BibTeX styles may ignore it for this entry type", rid)
    for key, tag in fields.items():
        if key in csl:
            values.append((tag, _bib_escape(_single_line(csl[key], key, findings, rid))))
    for key in ("author", "editor"):
        names = []
        for name in _names(csl.get(key, []), key, findings, rid):
            if name.get("literal"):
                names.append("{" + _bib_escape(_single_line(name["literal"], key, findings, rid)) + "}")
            else:
                family, given, suffix = _name_parts(name)
                value = ", ".join(filter(None, (family, suffix, given)))
                names.append(_bib_escape(_single_line(value, key, findings, rid)))
        if names:
            values.append((key, " and ".join(names)))
    if "issued" in csl:
        date, literal = _date(csl["issued"], "issued")
        if date:
            values.append(("year", str(date[0])))
            if len(date) > 1:
                months = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")
                values.append(("month", months[date[1] - 1]))
            if len(date) > 2 or len(csl["issued"].get("date-parts", [])) > 1 or set(csl["issued"]) - {"date-parts"}:
                _warn(findings, "export_date_precision_lost", "BibTeX retains year/month; full dates and qualifiers remain in the recovery report", rid)
        elif literal is not None:
            values.append(("note", _bib_escape("Issued: " + _single_line(literal, "issued.literal", findings, rid))))
            _warn(findings, "export_literal_date", "Unparsed issued date retained in a BibTeX note", rid)
    _omissions(csl, set(fields) | {"author", "editor", "issued"}, findings, rid)
    return "@" + kind + "{" + rid + ",\n" + ",\n".join(
        f"  {key} = {{{value}}}" for key, value in values) + "\n}\n"


def _json_text(value):
    try:
        return json.dumps(value, ensure_ascii=True, indent=2, allow_nan=False) + "\n"
    except (ValueError, TypeError, RecursionError) as error:
        raise ExportError("export_json_invalid", "Recovered data cannot be represented as JSON: " + str(error)) from error


def export_references(report: RecoveryReport, format: str = "report") -> ReferenceExport:
    if format not in FORMATS:
        raise ExportError("export_format_unknown", f"Unknown format: {format}")
    if format == "report":
        # Escapes also preserve malformed Unicode from foreign JSON in a
        # diagnostic report without crashing its UTF-8 file/console writer.
        return ReferenceExport(_json_text(report.to_dict()))
    blockers = sorted({finding.code for finding in report.findings
                       if finding.severity == "error" or finding.code in _INCOMPLETE_RECOVERY})
    if blockers:
        raise ExportError("recovery_incomplete", "Recovery needs review before library export: "
                          + ", ".join(blockers) + "; save the JSON report for the recovered data and details")
    if not report.records:
        raise ExportError("no_recovered_references", "No supported embedded records were recovered; save the JSON report for details")
    findings = [RecoveryFinding(
        "library_export_not_relinked",
        "Recovered metadata is unverified. Importing a library file does not relink existing Word citations. "
        "The JSON recovery report retains original records and citation instructions.",
        severity="note",
    )]
    seen = set()
    for position, record in enumerate(report.records, start=1):
        if (not isinstance(record.id, str) or not re.fullmatch(r"[A-Za-z0-9:_-]+", record.id)
                or record.id in seen):
            raise ExportError("export_record_id_invalid", f"Record {position} has a duplicate or unsafe export ID: {record.id!r}")
        seen.add(record.id)
    if format == "endnote-xml":
        root = etree.Element("xml")
        records = etree.SubElement(root, "records")
        for record in report.records:
            if record.source != "endnote" or not isinstance(record.raw, str):
                raise ExportError("endnote_source_required", f"{record.id}: EndNote XML export requires native EndNote records for every item; use CSL-JSON or RIS for mixed sources")
            try:
                item = parse_xml_hardened(record.raw.encode("utf-8"))
                if item.tag != "record":
                    raise ValueError("Expected a record element")
            except (UnsafeXML, ValueError, etree.XMLSyntaxError) as error:
                raise ExportError("invalid_endnote_record", f"{record.id}: {error}") from error
            records.append(item)
        return ReferenceExport(etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=False).decode("utf-8"), findings)
    for record in report.records:
        if not isinstance(record.csl.get("type"), str) or not record.csl["type"].strip():
            raise ExportError("export_type_missing", f"{record.id} has no known CSL type; retain its original metadata in the recovery report")
    if format == "csl-json":
        items = [dict(copy.deepcopy(record.csl), id=record.id) for record in report.records]
        return ReferenceExport(_json_text(items), findings)
    renderer = _ris if format == "ris" else _bibtex
    rendered = []
    for record in report.records:
        try:
            rendered.append(renderer(record, findings))
        except ExportError as error:
            raise ExportError(error.code, f"{record.id}: {error.message}") from error
    return ReferenceExport(("\r\n" if format == "ris" else "\n").join(rendered), findings)
