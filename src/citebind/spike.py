"""The Phase 1 Word round-trip kit: generator and per-probe checker.

``make_spike`` writes a small, self-contained fixture document: ordinary
prose, one real open-access reference (hard-coded from the Crossref record
archived at ``spike/reference_source_crossref.json`` — never from memory,
never from the network), two citation controls for it, one bibliography.

``check_spike`` grades returned files probe by probe. Design rules come from
the review note of 2026-08-29 (F1/F2): files are identified by the names the
instructions promise, never inferred from content; every probe reads its own
evidence file where one exists; every row states which file it read, which
fact decided the verdict, and what it could not determine. A verdict may only
cite evidence that could have come out the other way.
"""

import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence, Union

from .controls import (
    insert_bibliography,
    insert_citation,
    read_document_root_hardened,
    scan_document_controls,
)
from .model import CiteBindDocument, CitationCluster, Reference
from .part import embed, extract

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _q(name: str) -> str:
    return f"{{{W_NS}}}{name}"


# Hard-coded from spike/reference_source_crossref.json (Crossref API response
# retrieved 2026-08-29; CC BY-NC 3.0). DO NOT "improve" these fields by hand:
# they are the verified record, and any change must come from the source.
BASELINE_REFERENCE: dict = {
    "id": "R001",
    "doi": "10.2147/prom.s8896",
    "title": (
        "Perspectives on electronic medical records adoption: "
        "electronic medical records (EMR) in outcomes research"
    ),
    "authors": ["Daniel A Belletti"],
    "journal": "Patient Related Outcome Measures",
    "year": 2010,
    "pages": "29",
    "metadata_source": "crossref",
    "retrieved_at": "2026-08-29T00:00:00Z",
}
BASELINE_DOI = BASELINE_REFERENCE["doi"]
BASELINE_CLUSTER_ID = "C001"
BASELINE_CITATION_TEXT = "[1]"
BASELINE_BIBLIOGRAPHY_ENTRY = (
    "1. Belletti DA. Perspectives on electronic medical records adoption: "
    "electronic medical records (EMR) in outcomes research. "
    "Patient Related Outcome Measures. 2010:29."
)
PROSE = [
    "Open-access publishing has made individual research articles easier to reach.",
    "This short document is used to check how citations behave during ordinary editing.",
]

# The four names the instructions promise, and the role each plays.
MAIN_NAME = "spike_v1.docx"
STEP1_NAME = "step1_reopened.docx"
PASTED_NAME = "pasted.docx"
RENAMED_NAME = "spike_renamed.docx"

SPIKE_DOCX_NAME = MAIN_NAME


def _baseline_document() -> CiteBindDocument:
    return CiteBindDocument(
        schema_version="1",
        selected_style="numeric",
        references=[Reference.from_dict(copy.deepcopy(BASELINE_REFERENCE))],
        citation_clusters=[
            CitationCluster(id=BASELINE_CLUSTER_ID, reference_ids=["R001"])
        ],
    )


def make_spike(out_dir: Union[str, Path]) -> Path:
    """Write the spike fixture into ``out_dir``; return the path. No network."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / SPIKE_DOCX_NAME

    document = _new_document()
    plain = out_dir / "_plain_tmp.docx"
    document.save(plain)
    embed(plain, _baseline_document(), path)
    plain.unlink()
    return path


def _new_document():
    from docx import Document

    document = Document()
    document.add_paragraph(PROSE[0])
    document.add_paragraph(PROSE[1])
    paragraphs = document.paragraphs
    insert_citation(paragraphs[0], BASELINE_CLUSTER_ID, BASELINE_CITATION_TEXT)
    insert_citation(paragraphs[1], BASELINE_CLUSTER_ID, BASELINE_CITATION_TEXT)
    insert_bibliography(document, [BASELINE_BIBLIOGRAPHY_ENTRY])
    return document


# --- checker ---------------------------------------------------------------------


@dataclass
class ProbeRow:
    probe: str  # "P1".."P6"
    name: str
    verdict: str  # "PASS" | "FAIL"
    detail: str
    file_read: Optional[str] = None  # (a) which file this row graded
    cannot_determine: Optional[str] = None  # (c) what this row could not know


@dataclass
class SpikeReport:
    rows: list[ProbeRow] = field(default_factory=list)
    classification: list[str] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return bool(self.rows) and all(row.verdict == "PASS" for row in self.rows)


def _scan_file(path: Path):
    """(citation texts, bibliography entries) via the shared hardened scanner."""
    root = read_document_root_hardened(path)
    citations: list[tuple[str, str]] = []
    bibliography_entries: list[str] = []
    for sc in scan_document_controls(root):
        if sc.kind == "citation":
            citations.append((sc.tag, sc.text))
        elif sc.kind == "bibliography":
            bibliography_entries.extend(sc.entries)
    return citations, bibliography_entries


def _payload_matches(path: Path) -> bool:
    try:
        return extract(path) == _baseline_document()
    except Exception:
        return False


def _readability_error(path: Path) -> Optional[str]:
    """Why this file cannot be graded, or None if it can be.

    Classification probes readability: a file with a promised name that is
    not a readable DOCX must be reported as exactly that — the review note's
    rule that "could not classify" and "did not return" are different
    statements applies to damaged files too.
    """
    import zipfile

    from .xmlsafe import parse_xml_hardened

    try:
        with zipfile.ZipFile(path) as source:
            data = source.read("word/document.xml")
    except zipfile.BadZipFile:
        return "was returned but is not a readable DOCX (wrong save format, or damaged)"
    except OSError:
        return "was returned but could not be opened (not a regular file, or permission denied)"
    except KeyError:
        return "was returned but is a zip archive with no word/document.xml part"
    try:
        parse_xml_hardened(data)
    except Exception as error:
        return f"was returned but its document.xml was refused: {error}"
    return None


def _classify(paths: Sequence[Union[str, Path]]):
    """Map each returned file to its role by the name the instructions promise.

    Content-based inference is exactly what mislabeled the F2 run: whether a
    clipboard paste carries the payload is probe 4's question, not a
    classification signal. Duplicate, unrecognized, and unreadable names are
    reported, not silently resolved.
    """
    roles: dict[str, Optional[Path]] = {
        MAIN_NAME: None,
        STEP1_NAME: None,
        PASTED_NAME: None,
        RENAMED_NAME: None,
    }
    unrecognized: list[str] = []
    unreadable: dict[str, str] = {}
    promised = {name.lower(): name for name in roles}
    for raw in paths:
        path = Path(raw)
        name = path.name
        if not path.exists():
            unrecognized.append(
                f"{name} — passed but the file does not exist at {path}; "
                "it was not graded"
            )
        elif name.lower() in promised:
            role_name = promised[name.lower()]
            if roles[role_name] is not None:
                unrecognized.append(f"{name} (returned twice; grading the first, ignoring {path})")
            else:
                error = _readability_error(path)
                if error is not None:
                    unreadable[role_name] = error
                else:
                    roles[role_name] = path
        else:
            unrecognized.append(
                f"{name} — not one of the four names the instructions "
                "promise; it was not graded"
            )
    return roles, unrecognized, unreadable


def check_spike(paths: Sequence[Union[str, Path]]) -> SpikeReport:
    """Grade the returned files probe by probe.

    Evidence sources are independent where the workflow allows it: P1 reads
    only the step-1 save-as copy, P4 only pasted.docx, P6 only the save-as
    copy. P2, P3 and P5 necessarily read the end-state spike_v1.docx — each
    of their rows says so.
    """
    roles, unrecognized, unreadable = _classify(paths)
    rows: list[ProbeRow] = []

    classification: list[str] = []
    for role_name, path in roles.items():
        classification.append(
            f"{path} -> graded as {role_name}" if path is not None else f"{role_name}: NOT RETURNED"
        )
    classification.extend(f"unrecognized: {line}" for line in unrecognized)
    classification.extend(f"{name}: {reason}" for name, reason in unreadable.items())

    def missing_note(name: str) -> str:
        if name in unreadable:
            return f"{name} {unreadable[name]}"
        note = f"{name} was not returned"
        ungraded = [line.split(" — ")[0] for line in unrecognized] + [
            n for n in unreadable if n != name
        ]
        if ungraded:
            note += (
                "; returned file(s) that could not be graded: " + "; ".join(ungraded)
            )
        return note

    main: Optional[Path] = roles[MAIN_NAME]
    step1: Optional[Path] = roles[STEP1_NAME]
    pasted: Optional[Path] = roles[PASTED_NAME]
    renamed: Optional[Path] = roles[RENAMED_NAME]

    main_citations, main_bib = _scan_file(main) if main else ([], [])

    # --- P1: graded ONLY on the step-1 save-as copy --------------------------
    if step1 is None:
        rows.append(
            ProbeRow(
                probe="P1",
                name="open, save, close, reopen — payload and citations survive",
                verdict="FAIL",
                detail=(
                    f"{missing_note(STEP1_NAME)}; step 1 of the instructions "
                    "asks for this Save As copy, so the open/save/reopen cycle "
                    "could not be graded on its own evidence"
                ),
                file_read=None,
            )
        )
    else:
        payload_ok = _payload_matches(step1)
        citations, bib = _scan_file(step1)
        texts_ok = bool(citations) and all(
            text == BASELINE_CITATION_TEXT for _tag, text in citations
        )
        ok = payload_ok and len(citations) >= 2 and bool(bib) and texts_ok
        rows.append(
            ProbeRow(
                probe="P1",
                name="open, save, close, reopen — payload and citations survive",
                verdict="PASS" if ok else "FAIL",
                detail=(
                    f"deciding facts in {STEP1_NAME}: payload "
                    f"{'matches baseline' if payload_ok else 'missing or altered'}; "
                    f"{len(citations)} citation control(s) with text(s) "
                    f"{[text for _tag, text in citations]}; "
                    f"bibliography {'present' if bib else 'missing'}"
                ),
                file_read=str(step1),
            )
        )

    # --- P2: visible text layer on the end-state main document ----------------
    if main is None:
        rows.append(
            ProbeRow(
                probe="P2",
                name="ordinary prose edit — visible text stays intact and readable",
                verdict="FAIL",
                detail=missing_note(MAIN_NAME),
                file_read=None,
            )
        )
    else:
        texts_ok = bool(main_citations) and all(
            text == BASELINE_CITATION_TEXT for _tag, text in main_citations
        )
        bib_ok = any(entry.strip() for entry in main_bib)
        rows.append(
            ProbeRow(
                probe="P2",
                name="ordinary prose edit — visible text stays intact and readable",
                verdict="PASS" if (texts_ok and bib_ok) else "FAIL",
                detail=(
                    f"deciding fact in {MAIN_NAME}: citation visible text(s) "
                    f"{[text for _tag, text in main_citations]} "
                    f"{'match' if texts_ok else 'DO NOT match'} baseline "
                    f"{BASELINE_CITATION_TEXT!r}; bibliography text "
                    f"{'present' if bib_ok else 'missing'}"
                ),
                file_read=str(main),
                cannot_determine=(
                    "this row grades the end-state document, which also "
                    "contains the step-3 paste and the step-5 tracked edit; "
                    "a failure here cannot be attributed to step 2 alone"
                ),
            )
        )

    # --- P3: the paste within the document ------------------------------------
    if main is None:
        rows.append(
            ProbeRow(
                probe="P3",
                name="copy citation within the same document — a third control appears",
                verdict="FAIL",
                detail=missing_note(MAIN_NAME),
                file_read=None,
            )
        )
    else:
        count = len(main_citations)
        rows.append(
            ProbeRow(
                probe="P3",
                name="copy citation within the same document — a third control appears",
                verdict="PASS" if count >= 3 else "FAIL",
                detail=(
                    f"deciding fact in {MAIN_NAME}: found {count} citation "
                    "control(s), need at least 3 (2 original + 1 pasted copy)"
                ),
                file_read=str(main),
                cannot_determine=(
                    "if step 3 was skipped, this row fails without any Word "
                    "defect; the count cannot tell performed-and-lost from "
                    "not-performed"
                ),
            )
        )

    # --- P4: the cross-document paste, on its own file ------------------------
    if pasted is None:
        rows.append(
            ProbeRow(
                probe="P4",
                name="copy citation into a new blank document — control travels",
                verdict="FAIL",
                detail=(
                    f"{missing_note(PASTED_NAME)}; step 4 of the "
                    "instructions asks for this file"
                ),
                file_read=None,
            )
        )
    else:
        pasted_citations, _bib = _scan_file(pasted)
        nonempty = [text for _tag, text in pasted_citations if text.strip()]
        pasted_payload_state = _payload_file_exists(pasted)
        rows.append(
            ProbeRow(
                probe="P4",
                name="copy citation into a new blank document — control travels",
                verdict="PASS" if nonempty else "FAIL",
                detail=(
                    f"deciding fact in {PASTED_NAME}: {len(pasted_citations)} "
                    f"tagged citation control(s) with text(s) "
                    f"{[text for _tag, text in pasted_citations]}; "
                    f"payload part {pasted_payload_state}"
                ),
                file_read=str(pasted),
            )
        )

    # --- P5: Track Changes, on the end-state main document --------------------
    if main is None:
        rows.append(
            ProbeRow(
                probe="P5",
                name="edit next to a citation with Track Changes on — control survives",
                verdict="FAIL",
                detail=missing_note(MAIN_NAME),
                file_read=None,
            )
        )
    else:
        tracked = _has_tracked_changes(main)
        controls_ok = len(main_citations) >= 2 and all(
            text == BASELINE_CITATION_TEXT for _tag, text in main_citations
        )
        if not tracked:
            rows.append(
                ProbeRow(
                    probe="P5",
                    name="edit next to a citation with Track Changes on — control survives",
                    verdict="FAIL",
                    detail=(
                        f"deciding fact in {MAIN_NAME}: no tracked edits "
                        "(w:ins/w:del) found — step 5 was not performed or the "
                        "revisions were not saved"
                    ),
                    file_read=str(main),
                    cannot_determine=(
                        "absence of revisions cannot distinguish 'step skipped' "
                        "from 'Word discarded the revisions'"
                    ),
                )
            )
        else:
            rows.append(
                ProbeRow(
                    probe="P5",
                    name="edit next to a citation with Track Changes on — control survives",
                    verdict="PASS" if controls_ok else "FAIL",
                    detail=(
                        f"deciding fact in {MAIN_NAME}: tracked edits present; "
                        f"{len(main_citations)} citation control(s) "
                        f"{'with intact text' if controls_ok else 'lost or altered'}"
                    ),
                    file_read=str(main),
                )
            )

    # --- P6: the save-as copy, on its own file ---------------------------------
    if renamed is None:
        rows.append(
            ProbeRow(
                probe="P6",
                name="save-as under a new name — everything intact in the copy",
                verdict="FAIL",
                detail=(
                    f"{missing_note(RENAMED_NAME)}; step 6 of the "
                    "instructions asks for this file"
                ),
                file_read=None,
            )
        )
    else:
        renamed_payload_ok = _payload_matches(renamed)
        renamed_citations, renamed_bib = _scan_file(renamed)
        texts_ok = len(renamed_citations) >= 2 and all(
            text == BASELINE_CITATION_TEXT for _tag, text in renamed_citations
        )
        ok = renamed_payload_ok and texts_ok and bool(renamed_bib)
        rows.append(
            ProbeRow(
                probe="P6",
                name="save-as under a new name — everything intact in the copy",
                verdict="PASS" if ok else "FAIL",
                detail=(
                    f"deciding facts in {RENAMED_NAME}: payload "
                    f"{'matches baseline' if renamed_payload_ok else 'missing or altered'}; "
                    f"{len(renamed_citations)} citation control(s) with text(s) "
                    f"{[text for _tag, text in renamed_citations]}; "
                    f"bibliography {'present' if renamed_bib else 'missing'}"
                ),
                file_read=str(renamed),
            )
        )

    return SpikeReport(rows=rows, classification=classification)


def _payload_file_exists(path: Path) -> str:
    """The payload state of a file, as a plain three-state fact.

    Reported for pasted.docx because whether the library travels with a
    clipboard paste is the open question probe 4 exists to answer; the
    verdict never depends on it and no outcome is pre-labeled expected.
    """
    try:
        payload = extract(path)
    except Exception:
        return "present but unreadable"
    return "present" if payload is not None else "absent"


def _has_tracked_changes(path: Path) -> bool:
    root = read_document_root_hardened(path)
    return (
        len(list(root.iter(_q("ins")))) > 0
        or len(list(root.iter(_q("del")))) > 0
    )


def render_spike_report(report: SpikeReport) -> str:
    lines = ["files graded:"]
    lines.extend(f"  {line}" for line in report.classification)
    lines.append("")
    lines.append("probe  verdict  detail")
    lines.append("-----  ------  ------")
    for row in report.rows:
        lines.append(f"{row.probe:<6} {row.verdict:<7} {row.name}")
        lines.append(f"{'':<6} {'':<7} {row.detail}")
        if row.cannot_determine:
            lines.append(f"{'':<6} {'':<7} note: {row.cannot_determine}")
    lines.append(
        "overall: ALL PROBES PASS" if report.all_passed else "overall: FAILURES PRESENT"
    )
    return "\n".join(lines)
