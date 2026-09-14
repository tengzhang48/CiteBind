"""The structure verifier and round-trip differ.

``inspect`` answers "is this document structurally sound as a CiteBind
document?", with a named, severity-ranked finding for every damage mode.
``diff`` answers "what changed between two documents?", so the manual Word
round-trip has a machine-checkable result.

Every part of the untrusted input is parsed with the hardened parser
(``xmlsafe``); the document body is parsed directly, not through python-docx,
whose parser is not hardened.

Finding kinds are a closed enum (``FindingKind``). The severity table below is
the ONLY severity source, and ``tests/test_verify.py`` proves every kind is
triggerable by a fixture, so a kind can neither disappear from reporting nor
appear without classification.
"""

import zipfile
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional, Union

from lxml import etree

from .controls import scan_document_controls
from .model import CiteBindDocument
from .part import PayloadError, find_citebind_part, payload_to_dict
from .rendering import RenderingRefusal, render
from .schema import (
    CLUSTER_ID_DUPLICATE,
    CLUSTER_REFERENCE_UNKNOWN,
    REFERENCE_ID_DUPLICATE,
    SchemaError,
    validate_document,
)
from .xmlsafe import UnsafeXML, parse_xml_hardened

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _q(name: str) -> str:
    return f"{{{W_NS}}}{name}"


CITATION_PREFIX = "citebind:citation:"


class FindingKind(str, Enum):
    PAYLOAD_PART_MISSING = "payload_part_missing"
    PAYLOAD_INVALID = "payload_invalid"
    DUPLICATE_REFERENCE_ID = "duplicate_reference_id"
    DUPLICATE_CLUSTER_ID = "duplicate_cluster_id"
    DANGLING_CLUSTER_REFERENCE = "dangling_cluster_reference"
    REFERENCE_UNCITED = "reference_uncited"
    CONTROL_MISSING_FOR_CLUSTER = "control_missing_for_cluster"
    CONTROL_TAG_WITHOUT_CLUSTER = "control_tag_without_cluster"
    CONTROL_TAG_UNRECOGNIZED = "control_tag_unrecognized"
    CITATION_CONTROL_EMPTY = "citation_control_empty"
    CITATION_CONTROLS_INCONSISTENT = "citation_controls_inconsistent"
    BIBLIOGRAPHY_CONTROL_MISSING = "bibliography_control_missing"
    BIBLIOGRAPHY_CONTROL_DUPLICATE = "bibliography_control_duplicate"
    BIBLIOGRAPHY_COUNT_MISMATCH = "bibliography_count_mismatch"
    VISIBLE_TEXT_MISMATCH = "visible_text_mismatch"
    RENDERING_UNAVAILABLE = "rendering_unavailable"


_SEVERITY = {
    FindingKind.PAYLOAD_PART_MISSING: "error",
    FindingKind.PAYLOAD_INVALID: "error",
    FindingKind.DUPLICATE_REFERENCE_ID: "error",
    FindingKind.DUPLICATE_CLUSTER_ID: "error",
    FindingKind.DANGLING_CLUSTER_REFERENCE: "error",
    FindingKind.REFERENCE_UNCITED: "warning",
    FindingKind.CONTROL_MISSING_FOR_CLUSTER: "error",
    FindingKind.CONTROL_TAG_WITHOUT_CLUSTER: "error",
    FindingKind.CONTROL_TAG_UNRECOGNIZED: "note",
    FindingKind.CITATION_CONTROL_EMPTY: "error",
    FindingKind.CITATION_CONTROLS_INCONSISTENT: "warning",
    FindingKind.BIBLIOGRAPHY_CONTROL_MISSING: "error",
    FindingKind.BIBLIOGRAPHY_CONTROL_DUPLICATE: "error",
    FindingKind.BIBLIOGRAPHY_COUNT_MISMATCH: "warning",
    FindingKind.VISIBLE_TEXT_MISMATCH: "error",
    FindingKind.RENDERING_UNAVAILABLE: "note",
}

# schema error codes that have a dedicated finding kind; any other SchemaError
# becomes PAYLOAD_INVALID with the named code preserved in the detail.
_SCHEMA_CODE_TO_KIND = {
    REFERENCE_ID_DUPLICATE: FindingKind.DUPLICATE_REFERENCE_ID,
    CLUSTER_ID_DUPLICATE: FindingKind.DUPLICATE_CLUSTER_ID,
    CLUSTER_REFERENCE_UNKNOWN: FindingKind.DANGLING_CLUSTER_REFERENCE,
}


@dataclass
class Finding:
    kind: FindingKind
    severity: str
    detail: str


@dataclass
class Report:
    has_payload: bool
    schema_version: Optional[str]
    selected_style: Optional[str]
    reference_ids: list[str]
    cluster_ids: list[str]
    control_tags: list[str]
    # tag -> visible texts of every occurrence of that tag, in document order.
    # Duplicate tags are normal (a cluster cited twice) and must not collapse.
    control_texts: dict[str, list[str]]
    inventory: dict[str, int]
    findings: list[Finding] = field(default_factory=list)
    # The parsed payload, so diff can compare what references SAY and not only
    # which ids exist. inspect has already parsed it; withholding it forced
    # diff to treat a reference as an opaque presence.
    payload: Optional[dict] = None

    @property
    def is_clean(self) -> bool:
        return not self.findings


class DiffKind(str, Enum):
    PAYLOAD_LOST = "payload_lost"
    PAYLOAD_GAINED = "payload_gained"
    SCHEMA_VERSION_CHANGED = "schema_version_changed"
    STYLE_CHANGED = "style_changed"
    REFERENCE_LOST = "reference_lost"
    REFERENCE_GAINED = "reference_gained"
    CLUSTER_LOST = "cluster_lost"
    CLUSTER_GAINED = "cluster_gained"
    REFERENCE_CHANGED = "reference_changed"
    CLUSTER_CHANGED = "cluster_changed"
    CONTROL_LOST = "control_lost"
    CONTROL_GAINED = "control_gained"
    CONTROL_RENAMED = "control_renamed"
    CONTROL_TEXT_ALTERED = "control_text_altered"
    FIELD_INTRODUCED = "field_introduced"
    SDT_COUNT_CHANGED = "sdt_count_changed"


@dataclass
class DiffItem:
    kind: DiffKind
    detail: str


@dataclass
class DiffReport:
    items: list[DiffItem] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return not self.items


@dataclass
class _BodyScan:
    citation_texts: dict[str, list[str]]
    bibliography_present: bool
    bibliography_count: int
    bibliography_entry_count: int
    bibliography_entries: list[str]
    control_tags: list[str]
    control_texts: dict[str, list[str]]
    unrecognized_tags: list[str]
    inventory: dict[str, int]


def _scan_body(root) -> _BodyScan:
    """Inventory the body via the shared hardened scanner (controls module).

    Finding logic is unchanged: this only assembles the same facts the
    verifier has always reported, from the one scanner every caller now
    shares (review note F3).
    """
    scan = _BodyScan(
        citation_texts={},
        bibliography_present=False,
        bibliography_count=0,
        bibliography_entry_count=0,
        bibliography_entries=[],
        control_tags=[],
        control_texts={},
        unrecognized_tags=[],
        inventory={"sdt": 0, "fldChar": 0, "instrText": 0, "fldSimple": 0},
    )
    scanned = scan_document_controls(root)
    scan.inventory["sdt"] = len(scanned)
    for sc in scanned:
        if sc.kind == "citation":
            scan.citation_texts.setdefault(sc.cluster_id, []).append(sc.text)
            scan.control_tags.append(sc.tag)
            scan.control_texts.setdefault(sc.tag, []).append(sc.text)
        elif sc.kind == "bibliography":
            scan.bibliography_present = True
            scan.bibliography_count += 1
            scan.bibliography_entry_count = len(sc.entries)
            scan.bibliography_entries = list(sc.entries)
            scan.control_tags.append(sc.tag)
            scan.control_texts.setdefault(sc.tag, []).append(sc.text)
        elif sc.kind == "unrecognized":
            scan.unrecognized_tags.append(f"{sc.tag} ({sc.unrecognized_reason})")
    for name in ("fldChar", "instrText", "fldSimple"):
        scan.inventory[name] = sum(1 for _ in root.iter(_q(name)))
    return scan


def _read_document_root(docx_path) -> etree._Element:
    with zipfile.ZipFile(docx_path) as source:
        return parse_xml_hardened(source.read("word/document.xml"))


def _payload_part_exists(source: zipfile.ZipFile) -> bool:
    """Answer "is a citebind payload part plausibly present?" without a valid parse.

    True when some custom XML item part either carries our root or cannot be
    parsed at all (a dropped payload must not be masked by Word's own
    ``b:Sources`` item, which parses fine and is not ours).
    """
    for name in source.namelist():
        if not (
            name.startswith("customXml/item")
            and name.endswith(".xml")
            and "Props" not in name
        ):
            continue
        try:
            root = parse_xml_hardened(source.read(name))
        except UnsafeXML:
            return True
        if root.tag == "{urn:citebind:citebind:1}document":
            return True
    return False


def inspect(docx_path: Union[str, Path]) -> Report:
    root = _read_document_root(docx_path)
    scan = _scan_body(root)
    findings: list[Finding] = []

    with zipfile.ZipFile(docx_path) as source:
        part_name = None
        try:
            part_name = find_citebind_part(source)
        except PayloadError as error:
            findings.append(_finding(FindingKind.PAYLOAD_INVALID, str(error)))
        raw = None
        if part_name is not None:
            try:
                raw = payload_to_dict(source.read(part_name))
            except (UnsafeXML, PayloadError, ValueError) as error:
                findings.append(_finding(FindingKind.PAYLOAD_INVALID, str(error)))
        part_exists = part_name is not None or _payload_part_exists(source)
        if part_exists and raw is None and not findings:
            # FAIL-OPEN, closed. find_citebind_part skips an item it cannot
            # parse and _payload_part_exists then answers "yes, something is
            # there", so a corrupt payload produced has_payload=True, raw=None,
            # no finding at all -- and is_clean was True. A document whose
            # reference data is unreadable is the opposite of clean.
            findings.append(
                _finding(
                    FindingKind.PAYLOAD_INVALID,
                    "a citebind payload part is present but could not be read; "
                    "its XML is damaged or it is not a citebind payload",
                )
            )

    schema_version = selected_style = None
    reference_ids: list[str] = []
    cluster_ids: list[str] = []

    if raw is not None:
        schema_version = raw.get("schema_version")
        selected_style = raw.get("selected_style")
        references = raw.get("references") if isinstance(raw.get("references"), list) else []
        reference_ids = [r.get("id") for r in references if isinstance(r, dict)]
        clusters = (
            raw.get("citation_clusters")
            if isinstance(raw.get("citation_clusters"), list)
            else []
        )
        cluster_ids = [c.get("id") for c in clusters if isinstance(c, dict)]

        findings.extend(_findings_from_payload(raw))

        control_cluster_ids = set(scan.citation_texts)
        for cluster_id in cluster_ids:
            if cluster_id not in control_cluster_ids:
                findings.append(
                    _finding(
                        FindingKind.CONTROL_MISSING_FOR_CLUSTER,
                        f"cluster '{cluster_id}' has no citation control in the body",
                    )
                )
        for cluster_id in sorted(control_cluster_ids - set(cluster_ids)):
            findings.append(
                _finding(
                    FindingKind.CONTROL_TAG_WITHOUT_CLUSTER,
                    f"citation control tags cluster '{cluster_id}', "
                    "which is not in the payload",
                )
            )
        for cluster_id, texts in sorted(scan.citation_texts.items()):
            if any(text == "" for text in texts):
                findings.append(
                    _finding(
                        FindingKind.CITATION_CONTROL_EMPTY,
                        f"citation control for cluster '{cluster_id}' has no visible text",
                    )
                )
            if len(set(texts)) > 1:
                findings.append(
                    _finding(
                        FindingKind.CITATION_CONTROLS_INCONSISTENT,
                        f"citation controls for cluster '{cluster_id}' disagree: "
                        f"{sorted(set(texts))}",
                    )
                )
        if cluster_ids and not scan.bibliography_present:
            findings.append(
                _finding(
                    FindingKind.BIBLIOGRAPHY_CONTROL_MISSING,
                    "clusters exist but there is no bibliography control",
                )
            )
        elif scan.bibliography_present:
            if scan.bibliography_count > 1:
                findings.append(
                    _finding(
                        FindingKind.BIBLIOGRAPHY_CONTROL_DUPLICATE,
                        f"{scan.bibliography_count} bibliography controls in one "
                        "document; there is one bibliography, so the others are "
                        "stale copies and only the last was graded",
                    )
                )
            cited = _cited_reference_ids(raw)
            cited_existing = cited & set(reference_ids)
            if scan.bibliography_entry_count != len(cited_existing):
                findings.append(
                    _finding(
                        FindingKind.BIBLIOGRAPHY_COUNT_MISMATCH,
                        f"bibliography has {scan.bibliography_entry_count} entry(ies) "
                        f"for {len(cited_existing)} cited reference(s)",
                    )
                )

        findings.extend(_rendering_findings(raw, scan))

    for tag in scan.unrecognized_tags:
        findings.append(
            _finding(
                FindingKind.CONTROL_TAG_UNRECOGNIZED,
                f"unrecognized content control tag: {tag}",
            )
        )

    if not part_exists and scan.control_tags:
        findings.append(
            _finding(
                FindingKind.PAYLOAD_PART_MISSING,
                "content controls are present but the citebind payload part is not",
            )
        )

    return Report(
        has_payload=part_exists,
        schema_version=schema_version,
        selected_style=selected_style,
        reference_ids=reference_ids,
        cluster_ids=cluster_ids,
        control_tags=scan.control_tags,
        control_texts=scan.control_texts,
        inventory=scan.inventory,
        findings=findings,
        payload=raw,
    )


def _rendering_findings(raw: dict, scan: _BodyScan) -> list[Finding]:
    """Compare what the document SHOWS against what its payload RENDERS.

    Until Phase 3 there was no answer to "what should this citation say?", so
    a document could be structurally perfect and still show [7] over a payload
    holding one reference, or a bibliography naming a paper the payload does
    not contain, and every check passed. That hole is what this closes: the
    payload is the source of truth and the visible text is derived from it, so
    any disagreement is a finding.

    A refusal from the renderer is reported as a NOTE, never swallowed: a
    check that silently does not run is worse than one that fails, because the
    report still reads clean.
    """
    try:
        document = CiteBindDocument.from_dict(raw)
    except (SchemaError, KeyError, TypeError):
        # Already reported as PAYLOAD_INVALID; nothing to render from.
        return []
    try:
        rendered = render(document)
    except RenderingRefusal as refusal:
        return [
            _finding(
                FindingKind.RENDERING_UNAVAILABLE,
                f"visible text was NOT checked against rendering: {refusal}",
            )
        ]
    except Exception as error:
        # Deliberately broad, and the one place in this module that is. inspect
        # exists to report on documents that are already damaged, so a renderer
        # that throws on a hostile payload must become a finding, not a
        # traceback -- a verifier that dies on bad input has no answer for the
        # case it was built for. The catch still carries diagnosis (review note
        # R2): the exception type and message are in the report.
        return [
            _finding(
                FindingKind.RENDERING_UNAVAILABLE,
                "visible text was NOT checked against rendering: the renderer "
                f"failed unexpectedly ({type(error).__name__}: {error})",
            )
        ]

    findings: list[Finding] = []
    for cluster_id, texts in sorted(scan.citation_texts.items()):
        expected = rendered.citations.get(cluster_id)
        if expected is None:
            continue
        for actual in sorted(set(texts)):
            if actual != expected:
                findings.append(
                    _finding(
                        FindingKind.VISIBLE_TEXT_MISMATCH,
                        f"citation '{cluster_id}' shows {actual!r} but its payload "
                        f"renders as {expected!r}",
                    )
                )
    if scan.bibliography_present and scan.bibliography_entries != rendered.bibliography:
        findings.append(
            _finding(
                FindingKind.VISIBLE_TEXT_MISMATCH,
                "bibliography text does not match what the payload renders: "
                f"shows {scan.bibliography_entries} but renders as "
                f"{rendered.bibliography}",
            )
        )
    return findings


def _cited_reference_ids(raw: dict) -> set[str]:
    clusters = (
        raw.get("citation_clusters")
        if isinstance(raw.get("citation_clusters"), list)
        else []
    )
    cited: set[str] = set()
    for cluster in clusters:
        if isinstance(cluster, dict):
            cited.update(cluster.get("reference_ids") or [])
    return cited


def _findings_from_payload(raw: dict) -> list[Finding]:
    """Structural payload checks that survive partially-damaged payloads.

    These run on the raw dict, before full validation: a payload with BOTH a
    duplicate id and a schema-violating field must still report the duplicate
    by name. Validation errors without a dedicated kind surface as
    PAYLOAD_INVALID with the named schema code in the detail.
    """
    findings: list[Finding] = []
    emitted: set[FindingKind] = set()

    references = raw.get("references") if isinstance(raw.get("references"), list) else []
    ref_ids = [r.get("id") for r in references if isinstance(r, dict)]
    seen: set[str] = set()
    for ref_id in ref_ids:
        if ref_id in seen:
            findings.append(
                _finding(
                    FindingKind.DUPLICATE_REFERENCE_ID,
                    f"reference id '{ref_id}' appears more than once",
                )
            )
            emitted.add(FindingKind.DUPLICATE_REFERENCE_ID)
        seen.add(ref_id)

    clusters = (
        raw.get("citation_clusters") if isinstance(raw.get("citation_clusters"), list) else []
    )
    seen_clusters: set[str] = set()
    for cluster in clusters:
        if not isinstance(cluster, dict):
            continue
        cluster_id = cluster.get("id")
        if cluster_id in seen_clusters:
            findings.append(
                _finding(
                    FindingKind.DUPLICATE_CLUSTER_ID,
                    f"cluster id '{cluster_id}' appears more than once",
                )
            )
            emitted.add(FindingKind.DUPLICATE_CLUSTER_ID)
        seen_clusters.add(cluster_id)
        for ref_id in cluster.get("reference_ids") or []:
            if ref_id not in seen:
                findings.append(
                    _finding(
                        FindingKind.DANGLING_CLUSTER_REFERENCE,
                        f"cluster '{cluster_id}' cites missing reference '{ref_id}'",
                    )
                )
                emitted.add(FindingKind.DANGLING_CLUSTER_REFERENCE)

    cited = _cited_reference_ids(raw)
    for ref_id in sorted(set(ref_ids) - cited):
        findings.append(
            _finding(FindingKind.REFERENCE_UNCITED, f"reference '{ref_id}' is cited nowhere")
        )

    try:
        validate_document(raw)
    except SchemaError as error:
        mapped = _SCHEMA_CODE_TO_KIND.get(error.code)
        if mapped is None or mapped not in emitted:
            findings.append(_finding(FindingKind.PAYLOAD_INVALID, str(error)))
    return findings


def _finding(kind: FindingKind, detail: str) -> Finding:
    return Finding(kind=kind, severity=_SEVERITY[kind], detail=detail)


def _by_id(payload: Optional[dict], key: str) -> dict[str, dict]:
    entries = (payload or {}).get(key)
    if not isinstance(entries, list):
        return {}
    return {
        entry.get("id"): entry
        for entry in entries
        if isinstance(entry, dict) and entry.get("id")
    }


def _content_changes(
    before: Optional[dict], after: Optional[dict], key: str, kind: DiffKind
) -> list[DiffItem]:
    """Report entries that exist in both documents but no longer say the same.

    diff used to compare ids only, so a handoff that rewrote a reference's
    title, year, or authors -- or deleted a required field outright, leaving a
    payload that no longer validates -- came back "no differences". Presence
    was standing in for identity: a reference is what it CLAIMS, not merely
    that its id is still in the list.
    """
    before_by_id = _by_id(before, key)
    after_by_id = _by_id(after, key)
    items: list[DiffItem] = []
    for entry_id in sorted(set(before_by_id) & set(after_by_id)):
        old, new = before_by_id[entry_id], after_by_id[entry_id]
        if old == new:
            continue
        changed = sorted(
            field_name
            for field_name in set(old) | set(new)
            if old.get(field_name) != new.get(field_name)
        )
        details = "; ".join(
            f"{name}: {old.get(name)!r} -> {new.get(name)!r}" for name in changed
        )
        items.append(DiffItem(kind, f"'{entry_id}' changed — {details}"))
    return items


def diff(before_path: Union[str, Path], after_path: Union[str, Path]) -> DiffReport:
    before = inspect(before_path)
    after = inspect(after_path)
    items: list[DiffItem] = []

    if before.has_payload and not after.has_payload:
        items.append(DiffItem(DiffKind.PAYLOAD_LOST, "citebind payload part disappeared"))
    if after.has_payload and not before.has_payload:
        items.append(DiffItem(DiffKind.PAYLOAD_GAINED, "citebind payload part appeared"))
    if (
        before.has_payload
        and after.has_payload
        and before.schema_version != after.schema_version
    ):
        items.append(
            DiffItem(
                DiffKind.SCHEMA_VERSION_CHANGED,
                f"{before.schema_version} -> {after.schema_version}",
            )
        )
    if (
        before.has_payload
        and after.has_payload
        and before.selected_style != after.selected_style
    ):
        items.append(
            DiffItem(
                DiffKind.STYLE_CHANGED,
                f"{before.selected_style} -> {after.selected_style}",
            )
        )

    before_refs, after_refs = set(before.reference_ids), set(after.reference_ids)
    for ref_id in sorted(before_refs - after_refs):
        items.append(DiffItem(DiffKind.REFERENCE_LOST, f"reference '{ref_id}' disappeared"))
    for ref_id in sorted(after_refs - before_refs):
        items.append(DiffItem(DiffKind.REFERENCE_GAINED, f"reference '{ref_id}' appeared"))

    items.extend(
        _content_changes(
            before.payload, after.payload, "references", DiffKind.REFERENCE_CHANGED
        )
    )
    items.extend(
        _content_changes(
            before.payload,
            after.payload,
            "citation_clusters",
            DiffKind.CLUSTER_CHANGED,
        )
    )

    before_clusters, after_clusters = set(before.cluster_ids), set(after.cluster_ids)
    for cluster_id in sorted(before_clusters - after_clusters):
        items.append(DiffItem(DiffKind.CLUSTER_LOST, f"cluster '{cluster_id}' disappeared"))
    for cluster_id in sorted(after_clusters - before_clusters):
        items.append(DiffItem(DiffKind.CLUSTER_GAINED, f"cluster '{cluster_id}' appeared"))

    # Occurrence-level multiset diff: a cluster legitimately cited twice means
    # two controls share one tag, and losing one of them must still register.
    before_counts = Counter(before.control_tags)
    after_counts = Counter(after.control_tags)
    lost_tags = sorted((before_counts - after_counts).elements())
    gained_tags = sorted((after_counts - before_counts).elements())

    renamed_pairs: list[tuple[str, str]] = []
    for lost in list(lost_tags):
        if not lost.startswith(CITATION_PREFIX):
            continue
        lost_texts = set(before.control_texts.get(lost, []))
        for gained in gained_tags:
            if not gained.startswith(CITATION_PREFIX):
                continue
            if (
                lost_texts & set(after.control_texts.get(gained, []))
                and lost[len(CITATION_PREFIX):] != gained[len(CITATION_PREFIX):]
            ):
                renamed_pairs.append((lost, gained))
                lost_tags.remove(lost)
                gained_tags.remove(gained)
                break
    for lost, gained in renamed_pairs:
        items.append(
            DiffItem(DiffKind.CONTROL_RENAMED, f"{lost} -> {gained}")
        )
    for tag in lost_tags:
        items.append(DiffItem(DiffKind.CONTROL_LOST, f"control '{tag}' disappeared"))
    for tag in gained_tags:
        items.append(DiffItem(DiffKind.CONTROL_GAINED, f"control '{tag}' appeared"))

    for tag, before_texts in before.control_texts.items():
        after_texts = after.control_texts.get(tag)
        if after_texts is not None and before_texts != after_texts:
            items.append(
                DiffItem(
                    DiffKind.CONTROL_TEXT_ALTERED,
                    f"control '{tag}' visible text changed: "
                    f"{before_texts} -> {after_texts}",
                )
            )

    for name in ("fldChar", "instrText", "fldSimple"):
        delta = after.inventory[name] - before.inventory[name]
        if delta > 0:
            items.append(
                DiffItem(
                    DiffKind.FIELD_INTRODUCED,
                    f"{name} count increased by {delta}; CiteBind never introduces fields",
                )
            )

    delta_sdt = after.inventory["sdt"] - before.inventory["sdt"]
    explained = len(gained_tags) - len(lost_tags)
    if delta_sdt != explained:
        items.append(
            DiffItem(
                DiffKind.SDT_COUNT_CHANGED,
                f"sdt count changed by {delta_sdt}, control changes explain {explained}",
            )
        )

    return DiffReport(items=items)


# --- rendering -------------------------------------------------------------------


def render_report(report: Report, path: Union[str, Path]) -> str:
    lines = [f"CiteBind inspect: {path}"]
    if report.has_payload and report.schema_version is None:
        lines.append("payload: present (unreadable)")
    elif report.has_payload:
        lines.append(
            f"payload: present (schema_version={report.schema_version}, "
            f"style={report.selected_style})"
        )
    else:
        lines.append("payload: absent")
    lines.append(f"references: {', '.join(report.reference_ids) or '(none)'}")
    lines.append(f"clusters: {', '.join(report.cluster_ids) or '(none)'}")
    lines.append(f"controls: {', '.join(report.control_tags) or '(none)'}")
    inv = report.inventory
    lines.append(
        f"inventory: sdt={inv['sdt']} fldChar={inv['fldChar']} "
        f"instrText={inv['instrText']} fldSimple={inv['fldSimple']}"
    )
    if report.is_clean:
        lines.append("findings: none — clean")
    else:
        lines.append(f"findings: {len(report.findings)}")
        for finding in report.findings:
            lines.append(f"  [{finding.severity}] {finding.kind.value}: {finding.detail}")
    return "\n".join(lines)


def render_diff(report: DiffReport, before: Union[str, Path], after: Union[str, Path]) -> str:
    lines = [f"CiteBind diff: {before} -> {after}"]
    if report.is_clean:
        lines.append("no structural differences")
    else:
        lines.append(f"{len(report.items)} difference(s):")
        for item in report.items:
            lines.append(f"  {item.kind.value}: {item.detail}")
    return "\n".join(lines)
