"""Tagged content controls: the visible layer of CiteBind citations.

Every CiteBind structure is a ``w:sdt`` content control carrying a ``w:tag``
whose value lives in the ``citebind:`` namespace:

- ``citebind:citation:<cluster_id>`` — an INLINE control inside a paragraph;
- ``citebind:bibliography`` — a BLOCK control at body level.

Visible text is plain runs, so Word renders it for readers who have never
installed CiteBind. Rendering itself is Phase 3; here the caller supplies the
text. Content controls, never fields (dev plan §3.3).
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence, Union

from docx import Document
from docx.document import Document as _Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

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


def _visible_text(content) -> str:
    """Join the text of the control's content; blocks (paragraphs) with newlines."""
    if content is None:
        return ""
    chunks = [
        "".join(t.text or "" for t in child.iter(qn("w:t"))) for child in content
    ]
    return "\n".join(chunks)


def find_controls(docx_path: Union[str, Path]) -> list[ControlInfo]:
    """Return every CiteBind-tagged control in the document, in document order."""
    document = Document(docx_path)
    controls: list[ControlInfo] = []
    for sdt in document.element.body.iter(qn("w:sdt")):
        tag_el = sdt.find(f"{qn('w:sdtPr')}/{qn('w:tag')}")
        if tag_el is None:
            continue
        tag = tag_el.get(qn("w:val")) or ""
        if not tag.startswith(TAG_PREFIX):
            continue
        if tag.startswith(CITATION_TAG_PREFIX):
            kind = "citation"
            cluster_id = tag[len(CITATION_TAG_PREFIX):] or None
        elif tag == BIBLIOGRAPHY_TAG:
            kind = "bibliography"
            cluster_id = None
        else:
            kind = "unknown"
            cluster_id = None
        controls.append(
            ControlInfo(
                tag=tag,
                kind=kind,
                text=_visible_text(sdt.find(qn("w:sdtContent"))),
                cluster_id=cluster_id,
            )
        )
    return controls
