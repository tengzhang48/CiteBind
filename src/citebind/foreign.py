"""Recover the references EndNote and Zotero embed in a Word manuscript.

``recover_references(docx_path)`` reads a DOCX and returns a
:class:`~citebind.recovery_model.RecoveryReport`: the bibliographic records
the document carries inside its citation field codes, every citation
occurrence, and a named finding for everything that could not be recovered.

**These records are recovered, not verified.** They are what somebody's
reference library said, transported in the manuscript; CiteBind has not
resolved them against Crossref or PubMed and does not vouch for them. They
live in their own model (``citebind-recovery/1``) precisely so they can never
be mistaken for the verified ``citebind/1`` contract, whose references are
required to carry a DOI or PMID and a recorded metadata source. Nothing here
touches the input file, the verified schema, or the renderer, and nothing
here opens a socket.

What is supported
-----------------

- **Zotero** fields: ``ADDIN ZOTERO_ITEM CSL_CITATION`` followed by the
  add-in's CSL-JSON. Each ``citationItems[].itemData`` is already CSL, so it
  is preserved as-is (unknown keys included) rather than re-modelled.
- **EndNote** fields: ``ADDIN EN.CITE`` followed by
  ``<EndNote><Cite>…<record>…</record></Cite>…</EndNote>`` (the Traveling
  Library). The record XML is preserved verbatim; a documented subset is
  mapped to CSL and everything else stays in the raw XML with a finding
  naming what was not mapped.

What is recognized but NOT recovered — each reported, never silently dropped,
and never relabelled as something it is not:

- Mendeley fields (``ADDIN CSL_CITATION``): a different envelope and a
  different item identity. Calling them Zotero would put a false provenance
  on every record. Mendeley Cite's newer content-control form is not detected
  at all.
- Zotero/Mendeley **bookmark** storage: only the marker bookmark names are
  visible in the document; the citation data is not in the story parts.
- Word's own ``CITATION`` fields (the ``b:Sources`` bibliography).
- ``EN.REFLIST``/``ZOTERO_BIBL``: bibliography machinery, not a citation.
- Citations flattened to plain text ("Unlink Citations"): nothing is left to
  recover, and guessing from rendered text is how extractors invent
  references. Rendered text (``properties.formattedCitation``, EndNote's
  ``DisplayText``) is never read as metadata.

Deliberate limits, so a caller knows what "no findings" means: only the main
document, footnotes, endnotes, headers and footers are scanned — comments,
glossary/building-block parts and embedded sub-documents are not; fields
deleted under Track Changes are excluded (they are not in the document), while
a field whose instruction is only PARTLY deleted is reported as ambiguous
rather than resolved either way; item data nested deeper than
:data:`MAX_ITEM_DATA_DEPTH` is refused instead of recovered; LibreOffice
``.odt`` documents are a different format and out of scope.

The field-code shapes are external knowledge from the 2026-09-14
interoperability review, not something this repository can prove. The
structures are pinned by generated fixtures in ``tests/test_foreign.py``;
only a Word round trip with the real add-ins can confirm they match what
EndNote and Zotero write today.
"""

import copy
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Optional, Union

from lxml import etree

from . import word_fields
from .identifiers import IdentifierError, normalize_doi, normalize_pmid
from .recovery_model import (
    CitationOccurrence,
    RecoveredRecord,
    RecoveryFinding,
    RecoveryReport,
)
from .xmlsafe import UnsafeXML, parse_xml_hardened

ZOTERO = "zotero"
ENDNOTE = "endnote"
MENDELEY = "mendeley"

# Byte markers used only to notice citation machinery in parts Word cannot
# reach (see word_fields.unreferenced_marker_parts).
MARKER_BYTES = (
    b"ADDIN ZOTERO_ITEM",
    b"ADDIN ZOTERO_TEMP",
    b"ADDIN EN.CITE",
    b"ADDIN CSL_CITATION",
)

# CSL item data is a few levels deep (author -> list -> name -> parts).
# Anything past this is not item data; see _too_deep.
MAX_ITEM_DATA_DEPTH = 32

# The one severity table. A finding code that is not classified here is
# treated as an error: an unclassified problem must never let a report look
# clean (the fail-open lesson from verify.py's payload handling).
_SEVERITY = {
    # package and parts
    "package_incomplete": "warning",
    "part_rels_missing": "warning",
    "part_rels_malformed": "warning",
    "part_missing": "warning",
    "part_unreadable": "error",
    "part_root_unexpected": "warning",
    "part_not_referenced": "warning",
    "relationship_target_invalid": "warning",
    "relationship_target_external": "note",
    "story_part_limit_reached": "warning",
    "scan_budget_exhausted": "warning",
    # field structure
    "field_unterminated": "warning",
    "field_end_without_begin": "warning",
    "instruction_outside_field": "warning",
    # Both mean the instruction this report shows may not be the instruction
    # Word acts on, which is a claim about the data itself, not about tidiness.
    "field_instruction_partly_deleted": "error",
    "alternate_content_ambiguous": "error",
    "tracked_deletion_skipped": "warning",
    "tracked_insertion_present": "warning",
    "bibliography_field_ignored": "note",
    # recognized but unsupported citation machinery
    "mendeley_field_unsupported": "warning",
    "mendeley_bookmarks_unsupported": "warning",
    "zotero_bookmarks_unsupported": "warning",
    "zotero_temp_unsupported": "warning",
    "endnote_variant_unsupported": "warning",
    "word_citation_field_unsupported": "warning",
    # Zotero payloads
    "zotero_json_malformed": "error",
    "zotero_json_duplicate_key": "error",
    "zotero_json_non_finite": "error",
    "zotero_citation_items_missing": "error",
    "zotero_citation_items_empty": "error",
    "zotero_citation_items_malformed": "error",
    "zotero_citation_item_malformed": "error",
    "zotero_item_data_missing": "error",
    "zotero_item_data_malformed": "error",
    "zotero_item_data_too_deep": "error",
    "zotero_item_incomplete": "warning",
    # EndNote payloads
    "endnote_payload_missing": "error",
    "endnote_payload_malformed": "error",
    "endnote_payload_unsafe": "error",
    "endnote_root_unexpected": "error",
    "endnote_cites_missing": "error",
    "endnote_cite_without_record": "error",
    "endnote_ref_type_unmapped": "warning",
    "endnote_fields_unmapped": "warning",
    "endnote_doi_unrecognized": "warning",
    "endnote_pmid_unrecognized": "warning",
    "endnote_author_names_literal": "note",
    # identity
    "record_identity_conflict": "warning",
}


def recover_references(docx_path: Union[str, Path]) -> RecoveryReport:
    """Recover embedded EndNote/Zotero references from a DOCX, read-only.

    Raises :class:`~citebind.recovery_model.RecoveryError` when the package
    itself cannot be inspected (not a ZIP, duplicate members, no main
    document part, hostile or oversized story data); everything a document
    can survive is a finding on the report instead.
    """
    path = Path(docx_path)
    report = RecoveryReport(source_sha256=_sha256(path))
    package = word_fields.open_package(path)
    try:
        stories, issues = word_fields.story_parts(package)
        for issue in issues:
            report.findings.append(_finding(issue.code, issue.message, part=issue.part))
        recorder = _Recorder(report)
        for story in stories:
            _scan_story(recorder, story)
        scanned = {story.name for story in stories}
        for name in word_fields.unreferenced_marker_parts(
            package, scanned, MARKER_BYTES
        ):
            report.findings.append(
                _finding(
                    "part_not_referenced",
                    f"{name} contains citation field markers but no relationship "
                    "reaches it; Word does not render it, so it is not recovered",
                    part=name,
                )
            )
        if package.budget_exhausted:
            report.findings.append(
                _finding(
                    "scan_budget_exhausted",
                    "some unreferenced parts were too large to check for citation "
                    "markers; this report does not rule them out",
                )
            )
    finally:
        package.close()
    return report


def classify_instruction(instruction: str) -> str:
    """Name the citation machinery in a field instruction.

    Returns ``zotero``, ``zotero_temp``, ``endnote``, ``endnote_data``,
    ``mendeley``, ``word``, ``bibliography`` or ``other``. Whitespace is
    collapsed for matching only; the instruction itself is never rewritten.
    """
    text = " ".join((instruction or "").split()).upper()
    if not text:
        return "other"
    for prefix, kind in (
        ("ADDIN ZOTERO_ITEM CSL_CITATION", ZOTERO),
        ("ADDIN ZOTERO_TEMP", "zotero_temp"),
        ("ADDIN ZOTERO_BIBL", "bibliography"),
        ("ADDIN EN.REFLIST", "bibliography"),
        ("ADDIN EN.CITE.DATA", "endnote_data"),
        ("ADDIN EN.CITE", ENDNOTE),
        ("ADDIN MENDELEY BIBLIOGRAPHY", "bibliography"),
        ("ADDIN MENDELEY_BIBLIOGRAPHY", "bibliography"),
        ("ADDIN CSL_CITATION", MENDELEY),
        ("CITATION ", "word"),
        ("BIBLIOGRAPHY", "bibliography"),
    ):
        if text.startswith(prefix):
            return kind
    return "other"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _finding(code: str, message: str, **context) -> RecoveryFinding:
    return RecoveryFinding(
        code=code, message=message, severity=_SEVERITY.get(code, "error"), **context
    )


# --- scanning a story part ---------------------------------------------------------


class _Recorder:
    """Report state shared across parts: records, ids, and one-shot notices."""

    def __init__(self, report: RecoveryReport):
        self.report = report
        self._by_content: dict[tuple[str, str], str] = {}
        self._by_identity: dict[tuple[str, str], str] = {}
        self._counts: dict[str, int] = {}
        self._noticed: set[str] = set()

    def finding(self, code: str, message: str, **context) -> None:
        self.report.findings.append(_finding(code, message, **context))

    def notice_once(self, code: str, message: str) -> None:
        if code not in self._noticed:
            self._noticed.add(code)
            self.finding(code, message)

    def add_record(
        self,
        source: str,
        csl: dict[str, Any],
        raw: Union[dict[str, Any], str],
        source_ids: list[str],
        identity_keys: list[str],
    ) -> tuple[str, bool]:
        """Register a record; return its id and whether it is new.

        Two records collapse into one only when their source data is
        genuinely identical. Sharing an item id is NOT enough: a library item
        edited between two citations gives two different records under one
        id, and picking a winner would silently discard what the document
        actually says. Those stay distinct and are reported.
        """
        content_key = _canonical(raw)
        existing = (
            self._by_content.get((source, content_key))
            if content_key is not None
            else None
        )
        if existing is not None:
            return existing, False

        self._counts[source] = self._counts.get(source, 0) + 1
        record_id = f"{source}-{self._counts[source]:04d}"
        csl = dict(csl)
        # The record's own id: our deterministic one, so a CSL-JSON export of
        # this report has unique ids. The vendor's id is never lost -- it is
        # in raw and in source_ids.
        csl["id"] = record_id
        self.report.records.append(
            RecoveredRecord(
                id=record_id,
                source=source,
                csl=csl,
                raw=raw,
                source_ids=list(source_ids),
            )
        )
        if content_key is not None:
            self._by_content[(source, content_key)] = record_id

        for key in identity_keys:
            other = self._by_identity.get((source, key))
            if other is not None and other != record_id:
                self.finding(
                    "record_identity_conflict",
                    f"{other} and {record_id} both claim the source identity "
                    f"{key!r} but their record data differs; both are kept, "
                    "and neither is verified",
                    record_id=record_id,
                )
                break
        for key in identity_keys:
            self._by_identity.setdefault((source, key), record_id)
        return record_id, True


def _canonical(raw: Union[dict[str, Any], str]) -> Optional[str]:
    """A comparison key for record data: JSON key order is not information.

    None when the data is nested too deeply to serialize. Such a record is
    simply never deduplicated — losing a merge is harmless, where letting a
    RecursionError out of the library is not.
    """
    if isinstance(raw, str):
        return raw
    try:
        return json.dumps(
            raw, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        )
    except (RecursionError, ValueError, TypeError):
        return None


def _scan_story(recorder: _Recorder, story: word_fields.StoryPart) -> None:
    fields, issues = word_fields.read_fields(story.root)
    for issue in issues:
        recorder.finding(issue.code, issue.message, part=story.name)

    inserted = 0
    for field in fields:
        kind = classify_instruction(field.instruction)
        if kind == "other":
            continue
        where = {"part": story.name, "field_index": field.index}
        # A partly deleted instruction is ambiguous, not deleted: read_fields
        # has already reported it, and the field is recovered as stored.
        if field.deleted and not field.instruction_partly_deleted:
            recorder.finding(
                "tracked_deletion_skipped",
                f"a {kind} field here is deleted under Track Changes, so it is not "
                "recovered: it is not part of this document's text",
                **where,
            )
            continue
        if kind == "bibliography":
            recorder.finding(
                "bibliography_field_ignored",
                "a reference-manager bibliography field is formatting machinery, "
                "not a citation; its records come from the citation fields",
                **where,
            )
            continue
        if field.inserted:
            inserted += 1

        source = {"zotero_temp": ZOTERO, "endnote_data": ENDNOTE}.get(kind, kind)
        occurrence = CitationOccurrence(
            source=source,
            part=story.name,
            field_index=field.index,
            record_ids=[],
            instruction=field.instruction,
        )
        recorder.report.citations.append(occurrence)

        if kind == ZOTERO:
            _recover_zotero(recorder, occurrence, where)
        elif kind == ENDNOTE:
            _recover_endnote(recorder, occurrence, where)
        elif kind == MENDELEY:
            recorder.finding(
                "mendeley_field_unsupported",
                "a Mendeley citation field was found; its records are not "
                "recovered, and they are not Zotero's",
                **where,
            )
        elif kind == "zotero_temp":
            recorder.finding(
                "zotero_temp_unsupported",
                "a Zotero temporary (unprocessed) citation was found; it carries "
                "no item data to recover",
                **where,
            )
        elif kind == "endnote_data":
            recorder.finding(
                "endnote_variant_unsupported",
                "an EN.CITE.DATA field was found; this EndNote variant is not "
                "read by this recovery",
                **where,
            )
        elif kind == "word":
            recorder.finding(
                "word_citation_field_unsupported",
                "a Word CITATION field was found; its record lives in Word's own "
                "b:Sources part, which this recovery does not read",
                **where,
            )

    if inserted:
        recorder.finding(
            "tracked_insertion_present",
            f"{inserted} citation field(s) in this part are inside tracked "
            "insertions; they are recovered, but the document has unresolved "
            "tracked changes",
            part=story.name,
        )
    _scan_bookmarks(recorder, story)


def _scan_bookmarks(recorder: _Recorder, story: word_fields.StoryPart) -> None:
    names = word_fields.bookmark_names(story.root)
    for prefix, code, manager in (
        ("ZOTERO_", "zotero_bookmarks_unsupported", "Zotero"),
        ("MENDELEY_", "mendeley_bookmarks_unsupported", "Mendeley"),
    ):
        marked = [name for name in names if name.upper().startswith(prefix)]
        if marked:
            recorder.finding(
                code,
                f"{len(marked)} bookmark(s) named like {manager}'s bookmark "
                f"storage (e.g. {marked[0]!r}) are present; in bookmark mode the "
                "citation data is not in the document parts and is not recovered",
                part=story.name,
            )


# --- Zotero: CSL-JSON in the field instruction ----------------------------------------


class _DuplicateKey(Exception):
    """A JSON object repeated a key; which value is the record is ambiguous."""


class _NonFinite(Exception):
    """A JSON number was NaN or Infinity; not a value CSL can carry."""


def _no_duplicate_keys(pairs):
    seen: set[str] = set()
    for key, _value in pairs:
        if key in seen:
            raise _DuplicateKey(key)
        seen.add(key)
    return dict(pairs)


def _refuse_non_finite(token):
    raise _NonFinite(token)


def _finite_float(token: str) -> float:
    """Refuse a float literal that is not finite.

    ``parse_constant`` only sees the literal tokens NaN/Infinity/-Infinity.
    An overflowing literal like ``1e999`` slips past it, becomes ``inf``, and
    then serializes back out as ``Infinity`` — which is not JSON, so every
    downstream reader of this report would choke on a value we invented by
    passing it through.
    """
    value = float(token)
    if not math.isfinite(value):
        raise _NonFinite(token)
    return value


def _too_deep(value: Any, limit: int) -> bool:
    """True when a decoded JSON value nests deeper than ``limit``.

    Iterative: measuring depth recursively would fail exactly where it
    matters. CSL item data is a handful of levels deep; anything past the
    limit is not item data this recovery will vouch for, and deep-copying it
    is itself a RecursionError waiting to happen.
    """
    stack = [(value, 1)]
    while stack:
        node, depth = stack.pop()
        if depth > limit:
            return True
        if isinstance(node, dict):
            stack.extend((child, depth + 1) for child in node.values())
        elif isinstance(node, list):
            stack.extend((child, depth + 1) for child in node)
    return False


def _recover_zotero(
    recorder: _Recorder, occurrence: CitationOccurrence, where: dict
) -> None:
    text = occurrence.instruction.strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        recorder.finding(
            "zotero_json_malformed",
            "a Zotero citation field carries no JSON object; nothing to recover",
            **where,
        )
        return
    try:
        payload = json.loads(
            text[start : end + 1],
            object_pairs_hook=_no_duplicate_keys,
            parse_constant=_refuse_non_finite,
            parse_float=_finite_float,
        )
    except _DuplicateKey as error:
        recorder.finding(
            "zotero_json_duplicate_key",
            f"a Zotero citation's JSON repeats the key {error.args[0]!r}; which "
            "value is the record is ambiguous, so the citation is skipped",
            **where,
        )
        return
    except _NonFinite as error:
        recorder.finding(
            "zotero_json_non_finite",
            f"a Zotero citation's JSON contains {error.args[0]}, which is not a "
            "finite JSON number; the citation is skipped",
            **where,
        )
        return
    except (ValueError, RecursionError) as error:
        recorder.finding(
            "zotero_json_malformed",
            f"a Zotero citation's JSON could not be parsed: {error}",
            **where,
        )
        return
    if not isinstance(payload, dict):
        recorder.finding(
            "zotero_json_malformed",
            "a Zotero citation's JSON is not an object; the citation is skipped",
            **where,
        )
        return

    items = payload.get("citationItems")
    if items is None:
        recorder.finding(
            "zotero_citation_items_missing",
            "a Zotero citation's JSON has no citationItems; no record can be "
            "recovered from it",
            **where,
        )
        return
    if not isinstance(items, list):
        recorder.finding(
            "zotero_citation_items_malformed",
            "a Zotero citation's citationItems is not a list; the citation is "
            "skipped",
            **where,
        )
        return
    if not items:
        # A citation field that cites nothing is a damaged citation, not a
        # citation of zero references: Zotero does not write one.
        recorder.finding(
            "zotero_citation_items_empty",
            "a Zotero citation field cites no items at all; the field is present "
            "but carries nothing to recover",
            **where,
        )
        return

    for position, item in enumerate(items):
        if not isinstance(item, dict):
            recorder.finding(
                "zotero_citation_item_malformed",
                f"citation item {position} is not an object; it is skipped",
                **where,
            )
            continue
        item_data = item.get("itemData")
        if item_data is None:
            recorder.finding(
                "zotero_item_data_missing",
                f"citation item {position} carries no itemData: the document "
                "cites a record it does not contain. Its identity is preserved "
                "in the citation instruction; the record is not recovered",
                **where,
            )
            continue
        if not isinstance(item_data, dict):
            recorder.finding(
                "zotero_item_data_malformed",
                f"citation item {position} has itemData that is not an object; "
                "it is skipped",
                **where,
            )
            continue
        if _too_deep(item_data, MAX_ITEM_DATA_DEPTH):
            recorder.finding(
                "zotero_item_data_too_deep",
                f"citation item {position} has item data nested deeper than "
                f"{MAX_ITEM_DATA_DEPTH} levels, which is not plausible CSL item "
                "data; no record is made from it. The payload itself is still in "
                "this citation's instruction",
                **where,
            )
            continue

        raw: dict[str, Any] = {"itemData": copy.deepcopy(item_data)}
        for key in ("id", "uri", "uris", "itemKey", "key"):
            if key in item:
                raw[key] = copy.deepcopy(item[key])
        source_ids = _zotero_source_ids(item, item_data)
        identity = [
            value for value in source_ids if isinstance(value, str) and "://" in value
        ] or source_ids[:1]

        record_id, is_new = recorder.add_record(
            ZOTERO, copy.deepcopy(item_data), raw, source_ids, identity
        )
        occurrence.record_ids.append(record_id)
        if is_new:
            missing = [key for key in ("type", "title") if not item_data.get(key)]
            if missing:
                recorder.finding(
                    "zotero_item_incomplete",
                    f"recovered item data has no {' and no '.join(missing)}; it is "
                    "preserved as found and nothing is guessed for it",
                    record_id=record_id,
                    **where,
                )


def _zotero_source_ids(item: dict, item_data: dict) -> list[str]:
    """The vendor's own identifiers for this item, most global first."""
    values: list[str] = []
    uris = item.get("uris")
    if isinstance(uris, list):
        values.extend(uri for uri in uris if isinstance(uri, str))
    if isinstance(item.get("uri"), str):
        values.append(item["uri"])
    for candidate in (item.get("id"), item_data.get("id")):
        if isinstance(candidate, (str, int)) and not isinstance(candidate, bool):
            values.append(str(candidate))
    seen: set[str] = set()
    return [value for value in values if not (value in seen or seen.add(value))]


# --- EndNote: Traveling Library XML in the field instruction ------------------------

# An explicit ref-type NAME is the only thing that decides a CSL type here.
# EndNote's numeric codes are not read: they are vendor-internal, and getting
# one wrong turns a thesis into a journal article silently.
_REF_TYPE_TO_CSL = {
    "journal article": "article-journal",
    "electronic article": "article-journal",
    "book": "book",
    "edited book": "book",
    "book section": "chapter",
    "conference paper": "paper-conference",
    "conference proceedings": "paper-conference",
    "thesis": "thesis",
    "report": "report",
    "web page": "webpage",
    "newspaper article": "article-newspaper",
    "magazine article": "article-magazine",
    "dataset": "dataset",
}
# Types whose secondary-title IS the container (journal, book being excerpted,
# proceedings). For a book, secondary-title is the series, which is a
# different CSL variable -- mapping it to container-title would claim the book
# appeared inside its own series.
_CONTAINER_TYPES = {
    "article-journal",
    "chapter",
    "paper-conference",
    "article-newspaper",
    "article-magazine",
}
_SERIES_TYPES = {"book"}
# EndNote keeps ISSN and ISBN in one <isbn> field, so the record type decides
# which one it is. With no type, it is neither: it stays in the raw record.
_ISSN_TYPES = {"article-journal", "article-newspaper", "article-magazine"}
_ISBN_TYPES = {"book", "chapter", "paper-conference", "thesis", "report"}
_NUMBER_TYPES = {"report", "thesis"}
_PUBMED_DATABASES = ("pubmed", "medline", "nlm")
_MAX_YEAR_DIGITS = 8

_ENDNOTE_CONTAINERS = {
    "titles": {"title", "secondary-title"},
    "contributors": {"authors", "secondary-authors"},
    "dates": {"year"},
    "periodical": {"full-title"},
    "urls": {"related-urls", "web-urls"},
}
_ENDNOTE_MAPPED_LEAVES = {
    "ref-type",
    "pages",
    "volume",
    "number",
    "edition",
    "language",
    "abstract",
    "publisher",
    "pub-location",
    "isbn",
    "accession-num",
    "electronic-resource-num",
    "remote-database-name",
    "remote-database-provider",
}
_ENDNOTE_IDENTITY = {"rec-number", "foreign-keys", "source-app", "database"}


def _recover_endnote(
    recorder: _Recorder, occurrence: CitationOccurrence, where: dict
) -> None:
    text = occurrence.instruction.strip()
    start, end = text.find("<"), text.rfind(">")
    if start < 0 or end < start:
        recorder.finding(
            "endnote_payload_missing",
            "an EndNote citation field carries no XML payload: the Traveling "
            "Library is absent, so the cited record is not in this document",
            **where,
        )
        return
    try:
        root = parse_xml_hardened(text[start : end + 1].encode("utf-8"))
    except UnsafeXML as error:
        code = (
            "endnote_payload_malformed"
            if error.code == "xml_syntax"
            else "endnote_payload_unsafe"
        )
        recorder.finding(
            code, f"an EndNote citation payload was refused: {error}", **where
        )
        return
    if etree.QName(root).localname != "EndNote":
        recorder.finding(
            "endnote_root_unexpected",
            f"an EndNote citation payload has root {root.tag!r}, not <EndNote>; "
            "it is not a shape this recovery reads",
            **where,
        )
        return

    cites = root.findall("Cite")
    if not cites:
        recorder.finding(
            "endnote_cites_missing",
            "an EndNote payload contains no <Cite> elements; nothing to recover",
            **where,
        )
        return
    for position, cite in enumerate(cites):
        record_element = cite.find("record")
        if record_element is None:
            recorder.finding(
                "endnote_cite_without_record",
                f"cite {position} carries no <record>: the Traveling Library was "
                "not written for it, so the cited reference is not in this "
                "document. Nothing is inferred from the displayed text",
                **where,
            )
            continue
        csl, source_ids, pending = _endnote_record_to_csl(record_element)
        raw = etree.tostring(record_element, encoding="unicode", with_tail=False)
        record_id, is_new = recorder.add_record(
            ENDNOTE, csl, raw, source_ids, list(source_ids)
        )
        occurrence.record_ids.append(record_id)
        if is_new:
            for code, message in pending:
                recorder.finding(code, message, record_id=record_id, **where)
            if csl.get("author") or csl.get("editor"):
                recorder.notice_once(
                    "endnote_author_names_literal",
                    "EndNote names are recovered as written (\"Family, Given\" as "
                    "one literal string). They are not split into family/given: "
                    "that guess is wrong for particles, compound surnames and "
                    "organizations",
                )


def _text_at(element, path: str) -> str:
    """The text of one child path, with EndNote's <style> wrappers flattened."""
    found = element.find(path)
    return "".join(found.itertext()).strip() if found is not None else ""


def _endnote_record_to_csl(record) -> tuple[dict[str, Any], list[str], list[tuple]]:
    """Map the documented subset of an EndNote record to CSL.

    Returns (csl, source_ids, pending findings). Nothing is invented: a field
    that cannot be mapped without guessing stays in the raw record XML and is
    named in an ``endnote_fields_unmapped`` finding.
    """
    csl: dict[str, Any] = {}
    pending: list[tuple[str, str]] = []
    unmapped: list[str] = []

    ref_type = record.find("ref-type")
    type_name = (ref_type.get("name") or "").strip() if ref_type is not None else ""
    csl_type = _REF_TYPE_TO_CSL.get(type_name.lower())
    if csl_type:
        csl["type"] = csl_type
    else:
        pending.append(
            (
                "endnote_ref_type_unmapped",
                f"EndNote reference type {type_name or '(none given)'!r} has no CSL "
                "type in this mapping; the record is recovered without a type "
                "rather than guessed into one",
            )
        )

    for path, key in (
        ("titles/title", "title"),
        ("abstract", "abstract"),
        ("language", "language"),
        ("edition", "edition"),
        ("publisher", "publisher"),
        ("pub-location", "publisher-place"),
        ("pages", "page"),
        ("volume", "volume"),
    ):
        value = _text_at(record, path)
        if value:
            csl[key] = value

    secondary = _text_at(record, "titles/secondary-title")
    full_title = _text_at(record, "periodical/full-title")
    if csl_type in _CONTAINER_TYPES:
        container = full_title or secondary
        if container:
            csl["container-title"] = container
        if full_title and secondary and full_title != secondary:
            unmapped.append("titles/secondary-title")
    elif csl_type in _SERIES_TYPES:
        if secondary:
            csl["collection-title"] = secondary
        if full_title:
            unmapped.append("periodical/full-title")
    else:
        unmapped.extend(
            name
            for name, value in (
                ("titles/secondary-title", secondary),
                ("periodical/full-title", full_title),
            )
            if value
        )

    number = _text_at(record, "number")
    if number:
        if csl_type in _CONTAINER_TYPES:
            csl["issue"] = number
        elif csl_type in _NUMBER_TYPES:
            csl["number"] = number
        else:
            unmapped.append("number")

    for path, key in (
        ("contributors/authors/author", "author"),
        ("contributors/secondary-authors/author", "editor"),
    ):
        names = [
            {"literal": text}
            for element in record.findall(path)
            if (text := "".join(element.itertext()).strip())
        ]
        if names:
            csl[key] = names

    year = _text_at(record, "dates/year")
    if year:
        # A plain number is a date; anything else ("in press", "n.d.",
        # "1983-84") is carried as the source wrote it rather than parsed into
        # one. The length bound is not cosmetic: int() on a 5000-digit string
        # raises ValueError in CPython (the 4300-digit conversion limit), and
        # a number that long was never a year.
        numeric = year.isdigit() and len(year) <= _MAX_YEAR_DIGITS
        csl["issued"] = {"date-parts": [[int(year)]]} if numeric else {"raw": year}

    isbn = _text_at(record, "isbn")
    if isbn:
        if csl_type in _ISSN_TYPES:
            csl["ISSN"] = isbn
        elif csl_type in _ISBN_TYPES:
            csl["ISBN"] = isbn
        else:
            unmapped.append("isbn")

    doi = _text_at(record, "electronic-resource-num")
    if doi:
        try:
            csl["DOI"] = normalize_doi(doi)
        except IdentifierError as error:
            pending.append(
                (
                    "endnote_doi_unrecognized",
                    f"the DOI field holds {doi!r}, which is not a DOI ({error}); it "
                    "stays in the raw record and is not mapped",
                )
            )

    accession = _text_at(record, "accession-num")
    if accession:
        database = " ".join(
            (
                _text_at(record, "remote-database-name"),
                _text_at(record, "remote-database-provider"),
            )
        ).lower()
        if any(token in database for token in _PUBMED_DATABASES):
            try:
                csl["PMID"] = normalize_pmid(accession)
            except IdentifierError as error:
                pending.append(
                    (
                        "endnote_pmid_unrecognized",
                        f"the accession number {accession!r} came from a PubMed "
                        f"database but is not a PMID ({error}); not mapped",
                    )
                )
        else:
            # An accession number is only a PMID when the record says it came
            # from PubMed. From Web of Science or Embase it is a different
            # namespace entirely, and mislabelling it would send a verifier to
            # the wrong record.
            unmapped.append("accession-num")

    urls = [
        text
        for path in ("urls/related-urls/url", "urls/web-urls/url")
        for element in record.findall(path)
        if (text := "".join(element.itertext()).strip())
    ]
    if urls:
        csl["URL"] = urls[0]
    if len(urls) > 1:
        unmapped.append(f"urls ({len(urls) - 1} beyond the first)")

    for child in record:
        name = etree.QName(child).localname if isinstance(child.tag, str) else None
        if name is None or name in _ENDNOTE_IDENTITY or name in _ENDNOTE_MAPPED_LEAVES:
            continue
        if name in _ENDNOTE_CONTAINERS:
            unmapped.extend(
                f"{name}/{etree.QName(sub).localname}"
                for sub in child
                if isinstance(sub.tag, str)
                and etree.QName(sub).localname not in _ENDNOTE_CONTAINERS[name]
            )
            continue
        unmapped.append(name)

    if unmapped:
        listed = ", ".join(sorted(set(unmapped)))
        pending.append(
            (
                "endnote_fields_unmapped",
                f"{len(set(unmapped))} EndNote field(s) have no CSL mapping here and "
                f"are preserved only in the raw record: {listed}",
            )
        )
    return csl, _endnote_source_ids(record), pending


def _endnote_source_ids(record) -> list[str]:
    """The record's identity in its home library, or nothing.

    A RecNum is a row number in ONE library's database: two libraries reuse
    the same numbers constantly. Only the (db-id, rec-number) pair is an
    identity, and a record without a db-id gets no identity at all rather
    than a false one.
    """
    key = record.find("foreign-keys/key")
    db_id = (key.get("db-id") or "").strip() if key is not None else ""
    rec_number = _text_at(record, "rec-number")
    if db_id and rec_number:
        return [f"endnote:db={db_id}:rec={rec_number}"]
    if db_id:
        return [f"endnote:db={db_id}"]
    return []
