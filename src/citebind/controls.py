"""Tagged content controls: the visible layer of CiteBind citations.

Every CiteBind structure is a ``w:sdt`` content control carrying a ``w:tag``
whose value lives in the ``citebind:`` namespace:

- ``citebind:citation:<cluster_id>`` — an INLINE control inside a paragraph;
- ``citebind:bibliography`` — a BLOCK control at body level.

Visible text is plain runs, so Word renders it for readers who have never
installed CiteBind. Rendering itself is Phase 3; here the caller supplies the
text. Content controls, never fields (dev plan §3.3).
"""

import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence, Union

from docx.document import Document as _Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

from .xmlsafe import parse_xml_hardened

CITATION_TAG_PREFIX = "citebind:citation:"
BIBLIOGRAPHY_TAG = "citebind:bibliography"
TAG_PREFIX = "citebind:"

_XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"


@dataclass
class ControlInfo:
    """A CiteBind-tagged content control recovered from a document."""

    tag: str
    kind: str  # "citation" | "bibliography" | "unknown"
    text: str
    cluster_id: Optional[str] = None


@dataclass
class ScannedControl:
    """Every ``w:sdt`` in a document body, classified.

    This is the single scanner all callers share (dev plan review note
    2026-08-29, F3): ``find_controls``, ``verify`` and ``spike`` must reach
    the same trust decision about the same bytes.
    """

    tag: str
    kind: str  # "citation" | "bibliography" | "unrecognized" | "untagged"
    cluster_id: Optional[str]
    text: str
    entries: list[str]  # per-block visible text (bibliography entries)
    unrecognized_reason: Optional[str] = None


def read_document_root_hardened(docx_path: Union[str, Path]):
    """Open a DOCX and parse ``word/document.xml`` with the hardened parser."""
    with zipfile.ZipFile(docx_path) as source:
        return parse_xml_hardened(source.read("word/document.xml"))


def scan_document_controls(root) -> list[ScannedControl]:
    """Classify every ``w:sdt`` in a parsed document root, in document order."""
    scanned: list[ScannedControl] = []
    for sdt in root.iter(qn("w:sdt")):
        tag_el = sdt.find(f"{qn('w:sdtPr')}/{qn('w:tag')}")
        tag = (tag_el.get(qn("w:val")) or "") if tag_el is not None else ""
        content = sdt.find(qn("w:sdtContent"))
        entries = [
            "".join(t.text or "" for t in child.iter(qn("w:t")))
            for child in content
        ] if content is not None else []
        text = "\n".join(entries)
        if not tag:
            scanned.append(ScannedControl("", "untagged", None, text, entries))
        elif tag.startswith(CITATION_TAG_PREFIX):
            cluster_id = tag[len(CITATION_TAG_PREFIX):] or None
            scanned.append(ScannedControl(tag, "citation", cluster_id, text, entries))
        elif tag == BIBLIOGRAPHY_TAG:
            scanned.append(ScannedControl(tag, "bibliography", None, text, entries))
        elif tag.startswith(TAG_PREFIX):
            scanned.append(
                ScannedControl(tag, "unrecognized", None, text, entries, "unknown citebind kind")
            )
        else:
            scanned.append(
                ScannedControl(
                    tag, "unrecognized", None, text, entries, "outside citebind namespace"
                )
            )
    return scanned


def _make_sdt_pr(alias: str, tag: str):
    sdt_pr = OxmlElement("w:sdtPr")
    alias_el = OxmlElement("w:alias")
    alias_el.set(qn("w:val"), alias)
    tag_el = OxmlElement("w:tag")
    tag_el.set(qn("w:val"), tag)
    sdt_pr.append(alias_el)
    sdt_pr.append(tag_el)
    return sdt_pr


def _make_run(text: str):
    run = OxmlElement("w:r")
    t = OxmlElement("w:t")
    t.set(_XML_SPACE, "preserve")
    t.text = text
    run.append(t)
    return run


def insert_citation(paragraph: Paragraph, cluster_id: str, visible_text: str) -> None:
    """Insert an inline citation control, appending to the paragraph's content."""
    sdt = OxmlElement("w:sdt")
    sdt.append(
        _make_sdt_pr(f"CiteBind citation {cluster_id}", f"{CITATION_TAG_PREFIX}{cluster_id}")
    )
    content = OxmlElement("w:sdtContent")
    content.append(_make_run(visible_text))
    sdt.append(content)
    paragraph._p.append(sdt)


def insert_bibliography(document: _Document, entries: Sequence[str]) -> None:
    """Insert a block-level bibliography control at the end of the body.

    Placed before the body's closing ``sectPr`` when present: block content
    after ``sectPr`` is invalid Word XML.
    """
    sdt = OxmlElement("w:sdt")
    sdt.append(_make_sdt_pr("CiteBind bibliography", BIBLIOGRAPHY_TAG))
    content = OxmlElement("w:sdtContent")
    for entry in entries:
        paragraph = OxmlElement("w:p")
        paragraph.append(_make_run(entry))
        content.append(paragraph)
    sdt.append(content)
    body = document.element.body
    sect_pr = body.find(qn("w:sectPr"))
    if sect_pr is not None:
        sect_pr.addprevious(sdt)
    else:
        body.append(sdt)


def find_controls(docx_path: Union[str, Path]) -> list[ControlInfo]:
    """Return every CiteBind-tagged control in the document, in document order.

    The document body is parsed with the hardened parser: a file that
    ``verify`` refuses is a file this public API refuses too (review note
    F3). Foreign-tagged and untagged content controls are not returned.
    """
    root = read_document_root_hardened(docx_path)
    infos: list[ControlInfo] = []
    for scanned in scan_document_controls(root):
        if scanned.kind == "citation":
            infos.append(
                ControlInfo(
                    tag=scanned.tag,
                    kind="citation",
                    text=scanned.text,
                    cluster_id=scanned.cluster_id,
                )
            )
        elif scanned.kind == "bibliography":
            infos.append(ControlInfo(tag=scanned.tag, kind="bibliography", text=scanned.text))
        elif scanned.kind == "unrecognized" and scanned.tag.startswith(TAG_PREFIX):
            infos.append(ControlInfo(tag=scanned.tag, kind="unknown", text=scanned.text))
    return infos
