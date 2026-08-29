"""The Phase 1 Word round-trip kit: generator and per-probe checker.

``make_spike`` writes a small, self-contained fixture document: ordinary
prose, one real open-access reference (hard-coded from the Crossref record
archived at ``spike/reference_source_crossref.json`` — never from memory,
never from the network), two citation controls for it, one bibliography.

``check_spike`` grades returned files probe by probe (dev plan §6, T-06):
PASS/FAIL per probe, naming exactly what survived. The only baseline it may
assume is the fixture this module itself generates.
"""

import copy
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence, Union

from .controls import insert_bibliography, insert_citation
from .model import CiteBindDocument, CitationCluster, Reference
from .part import embed, extract
from .verify import inspect
from .xmlsafe import parse_xml_hardened

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

SPIKE_DOCX_NAME = "spike_v1.docx"


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


@dataclass
class SpikeReport:
    rows: list[ProbeRow] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return bool(self.rows) and all(row.verdict == "PASS" for row in self.rows)


def _citation_controls(docx_path):
    with zipfile.ZipFile(docx_path) as source:
        root = parse_xml_hardened(source.read("word/document.xml"))
    citations = []
    bibliography = []
    for sdt in root.iter(_q("sdt")):
        tag_el = sdt.find(f"{_q('sdtPr')}/{_q('tag')}")
        tag = tag_el.get(_q("val")) if tag_el is not None else ""
        if tag == "citebind:bibliography":
            content = sdt.find(_q("sdtContent"))
            text = "".join(t.text or "" for t in content.iter(_q("t"))) if content is not None else ""
            bibliography.append(text)
        elif tag.startswith("citebind:citation:"):
            content = sdt.find(_q("sdtContent"))
            text = "".join(t.text or "" for t in content.iter(_q("t"))) if content is not None else ""
            citations.append((tag, text))
    return citations, bibliography


def _has_tracked_changes(docx_path) -> bool:
    with zipfile.ZipFile(docx_path) as source:
        root = parse_xml_hardened(source.read("word/document.xml"))
    return (
        len(list(root.iter(_q("ins")))) > 0
        or len(list(root.iter(_q("del")))) > 0
    )


def check_spike(
    main_path: Union[str, Path],
    extra_paths: Sequence[Union[str, Path]] = (),
) -> SpikeReport:
    """Grade the returned main file and any extra returned files, per probe."""
    rows: list[ProbeRow] = []
    main_path = Path(main_path)

    payload = extract(main_path) if main_path.exists() else None
    citations, bibliography = _citation_controls(main_path)
    structure = inspect(main_path)
    prose_readable = len(structure.control_tags) >= 2
    citation_count = len(citations)
    texts_ok = all(
        text == BASELINE_CITATION_TEXT for _tag, text in citations
    )
    payload_ok = payload == _baseline_document()

    rows.append(
        ProbeRow(
            probe="P1",
            name="open, save, close, reopen — payload and citations survive",
            verdict="PASS" if (payload_ok and citation_count >= 2 and bibliography) else "FAIL",
            detail=(
                f"payload {'matches' if payload_ok else 'missing or altered'}; "
                f"{citation_count} citation control(s); "
                f"bibliography {'present' if bibliography else 'missing'}"
            ),
        )
    )

    rows.append(
        ProbeRow(
            probe="P2",
            name="ordinary prose edit in an untouched paragraph — text stays readable",
            verdict="PASS" if (payload is not None and texts_ok and prose_readable) else "FAIL",
            detail=(
                f"citation text {'unchanged' if texts_ok else 'unexpected'}: "
                f"{[text for _tag, text in citations]}"
            ),
        )
    )

    rows.append(
        ProbeRow(
            probe="P3",
            name="copy citation within the same document — a third control appears",
            verdict="PASS" if citation_count >= 3 else "FAIL",
            detail=f"found {citation_count} citation control(s), need at least 3",
        )
    )

    # classify extras
    pasted_path: Optional[Path] = None
    renamed_path: Optional[Path] = None
    for extra in extra_paths:
        extra = Path(extra)
        extra_payload = extract(extra)
        extra_citations, _bib = _citation_controls(extra)
        if extra_payload is not None and renamed_path is None:
            renamed_path = extra
        elif extra_citations and pasted_path is None:
            pasted_path = extra

    if pasted_path is None:
        rows.append(
            ProbeRow(
                probe="P4",
                name="copy citation into a new blank document — control travels",
                verdict="FAIL",
                detail="no returned file contains a pasted citation without a payload",
            )
        )
    else:
        pasted_citations, _bib = _citation_controls(pasted_path)
        texts = [text for _tag, text in pasted_citations]
        rows.append(
            ProbeRow(
                probe="P4",
                name="copy citation into a new blank document — control travels",
                verdict="PASS" if any(text for text in texts) else "FAIL",
                detail=(
                    f"{len(pasted_citations)} citation control(s) in the pasted "
                    f"document, text(s) {texts}; note: the embedded reference "
                    "library does not travel with a clipboard paste (expected)"
                ),
            )
        )

    if not _has_tracked_changes(main_path):
        rows.append(
            ProbeRow(
                probe="P5",
                name="edit next to a citation with Track Changes on — control survives",
                verdict="FAIL",
                detail="no tracked edits found in the returned document; "
                "redo probe 5 with Track Changes turned on",
            )
        )
    else:
        rows.append(
            ProbeRow(
                probe="P5",
                name="edit next to a citation with Track Changes on — control survives",
                verdict="PASS" if (payload_ok and citation_count >= 2) else "FAIL",
                detail=f"tracked edits present; {citation_count} citation control(s) intact",
            )
        )

    if renamed_path is None:
        rows.append(
            ProbeRow(
                probe="P6",
                name="save-as under a new name — everything intact in the copy",
                verdict="FAIL",
                detail="no save-as copy found among the returned files",
            )
        )
    else:
        renamed_payload = extract(renamed_path)
        renamed_citations, renamed_bib = _citation_controls(renamed_path)
        ok = (
            renamed_payload == _baseline_document()
            and len(renamed_citations) >= 2
            and bool(renamed_bib)
        )
        rows.append(
            ProbeRow(
                probe="P6",
                name="save-as under a new name — everything intact in the copy",
                verdict="PASS" if ok else "FAIL",
                detail=f"{renamed_path.name}: payload "
                f"{'matches' if renamed_payload == _baseline_document() else 'altered'}; "
                f"{len(renamed_citations)} citation control(s); "
                f"bibliography {'present' if renamed_bib else 'missing'}",
            )
        )

    return SpikeReport(rows=rows)


def render_spike_report(report: SpikeReport) -> str:
    lines = ["probe  verdict  detail", "-----  ------  ------"]
    for row in report.rows:
        lines.append(f"{row.probe:<6} {row.verdict:<7} {row.name}")
        lines.append(f"{'':<6} {'':<7} {row.detail}")
    lines.append(
        "overall: ALL PROBES PASS" if report.all_passed else "overall: FAILURES PRESENT"
    )
    return "\n".join(lines)
