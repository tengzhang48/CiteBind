"""Word field plumbing: story parts and field instructions, strictly read-only.

This module knows about OOXML and nothing about reference managers. It answers
two questions for :mod:`citebind.foreign`:

- **which parts of this package are Word stories?** The main document part
  (via the package relationship, falling back to ``word/document.xml``) plus
  the footnotes, endnotes, headers and footers *related from the main document
  part*. A ``word/header9.xml`` that no relationship points at is a leftover,
  not content: Word never renders it, so recovering citations from it would
  invent citations no reader of the document can see. Such parts are reported,
  never scanned.
- **which field instructions does a story contain?** Word splits one
  instruction across many ``w:instrText`` runs and nests fields inside each
  other, so instructions are assembled with a per-field stack. Concatenating
  a part's ``w:instrText`` nodes — the obvious implementation — splices a
  ``HYPERLINK`` into a citation's JSON and merges two unrelated citations.

Untrusted input rules, mirroring the rest of the package: every part is parsed
with :func:`citebind.xmlsafe.parse_xml_hardened` (no DTD, no entities, no
network); part names that are absolute, contain a ``..`` segment or use
backslashes are refused; a package that lists the same member twice is refused
because two readers would disagree about which bytes are the part; and reads
are bounded by :data:`MAX_PART_BYTES` per part and :data:`MAX_TOTAL_BYTES` in
total, so a small ZIP cannot expand into an unbounded read.

Nothing here writes, and nothing here opens a socket.
"""

import posixpath
import zipfile
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterator, Optional, Union

from lxml import etree

from .recovery_model import RecoveryError
from .xmlsafe import UnsafeXML, parse_xml_hardened

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
MC_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006"
RELS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
OFFICE_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

# Uncompressed limits. 16 MiB is far above any real Word story part (Word's
# own documents keep the main document part in the low megabytes even for
# book-length manuscripts) and far below what a decompression bomb needs to
# hurt. The total budget covers a package that spreads the same trick across
# hundreds of headers.
MAX_PART_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_STORY_PARTS = 256

CONTENT_TYPES_PART = "[Content_Types].xml"
PACKAGE_RELS_PART = "_rels/.rels"
DEFAULT_DOCUMENT_PART = "word/document.xml"

# Story kinds in a fixed scan order, so a report is byte-identical between
# runs regardless of the order relationships happen to appear in.
_STORY_RELS = {
    f"{OFFICE_REL}/footnotes": "footnotes",
    f"{OFFICE_REL}/endnotes": "endnotes",
    f"{OFFICE_REL}/header": "header",
    f"{OFFICE_REL}/footer": "footer",
}
_STORY_ORDER = ("footnotes", "endnotes", "header", "footer")
_EXPECTED_ROOTS = {
    "document": "document",
    "footnotes": "footnotes",
    "endnotes": "endnotes",
    "header": "hdr",
    "footer": "ftr",
}

# Every issue code this module can report. foreign.py owns the severity of
# each one; the test suite holds the two lists to each other.
ISSUE_CODES = frozenset(
    {
        "package_incomplete",
        "part_rels_missing",
        "part_rels_malformed",
        "part_missing",
        "part_unreadable",
        "part_root_unexpected",
        "relationship_target_invalid",
        "relationship_target_external",
        "story_part_limit_reached",
        "field_unterminated",
        "field_end_without_begin",
        "instruction_outside_field",
        "field_instruction_partly_deleted",
        "alternate_content_ambiguous",
    }
)


def _q(name: str) -> str:
    return f"{{{W_NS}}}{name}"


_FLDCHAR = _q("fldChar")
_FLDCHAR_TYPE = _q("fldCharType")
_FLDSIMPLE = _q("fldSimple")
_INSTR = _q("instr")
_INSTRTEXT = _q("instrText")
_DELINSTRTEXT = _q("delInstrText")
_BOOKMARK_START = _q("bookmarkStart")
_BOOKMARK_NAME = _q("name")
_DELETED_WRAPPERS = {_q("del"), _q("moveFrom")}
_INSERTED_WRAPPERS = {_q("ins"), _q("moveTo")}
_MC_FALLBACK = f"{{{MC_NS}}}Fallback"
_MC_CHOICE = f"{{{MC_NS}}}Choice"
_MC_ALTERNATE_CONTENT = f"{{{MC_NS}}}AlternateContent"


@dataclass(frozen=True)
class PartIssue:
    """Something notable about the package's parts. Severity is foreign.py's."""

    code: str
    message: str
    part: Optional[str] = None


@dataclass(frozen=True)
class FieldIssue:
    """Something notable about a story's field structure."""

    code: str
    message: str


@dataclass(frozen=True)
class StoryPart:
    name: str
    kind: str
    root: etree._Element


@dataclass(frozen=True)
class WordField:
    """One Word field, with its instruction reassembled from its own runs."""

    index: int  # document order within the part, by where the field STARTS
    instruction: str
    kind: str  # "complex" | "simple"
    depth: int  # 0 at top level, 1+ when nested inside another field
    deleted: bool  # inside w:del / w:moveFrom, or written as w:delInstrText
    inserted: bool  # inside w:ins / w:moveTo
    unterminated: bool = False
    instruction_partly_deleted: bool = False  # part of the instruction is w:del'd


class _PartUnreadable(Exception):
    """A member exists but its bytes cannot be produced."""


# --- package -------------------------------------------------------------------


class WordPackage:
    """A DOCX opened read-only, with bounded reads and a total byte budget."""

    def __init__(self, path: Union[str, Path]):
        self.path = Path(path)
        try:
            self._zip = zipfile.ZipFile(self.path)
        except zipfile.BadZipFile as error:
            raise RecoveryError(
                "zip_unreadable", f"{self.path} is not a readable ZIP package: {error}"
            ) from error
        names = self._zip.namelist()
        duplicates = sorted(
            name for name, count in Counter(names).items() if count > 1
        )
        if duplicates:
            # Readers disagree about which copy is "the" part: Python's
            # zipfile serves the last, other tools serve the first. A recovery
            # report that depends on which reader you used is not evidence.
            raise RecoveryError(
                "duplicate_zip_member",
                f"{self.path} lists {len(duplicates)} member(s) more than once "
                f"({', '.join(duplicates[:3])}); which bytes are the part is ambiguous",
            )
        invalid = sorted(name for name in names if not _valid_part_name(name))
        if invalid:
            raise RecoveryError(
                "invalid_part_name",
                f"{self.path} contains member name(s) that are not valid package "
                f"parts ({', '.join(invalid[:3])})",
            )
        self.names = names
        self._spent = 0
        self.budget_exhausted = False

    def close(self) -> None:
        self._zip.close()

    def has(self, name: str) -> bool:
        return name in self._zip.NameToInfo

    def read(self, name: str) -> bytes:
        """Read one member, bounded by the per-part and total limits."""
        info = self._zip.NameToInfo[name]
        if info.file_size > MAX_PART_BYTES:
            raise RecoveryError(
                "story_part_too_large",
                f"{name} declares {info.file_size} uncompressed bytes, over the "
                f"{MAX_PART_BYTES} byte limit for one part",
            )
        if self._spent + info.file_size > MAX_TOTAL_BYTES:
            raise RecoveryError(
                "story_data_too_large",
                f"reading {name} would take this package past the {MAX_TOTAL_BYTES} "
                "byte total limit for story data",
            )
        data = self._read_bounded(name)
        if len(data) > MAX_PART_BYTES:
            # The central directory understated the size; trust the bytes.
            raise RecoveryError(
                "story_part_too_large",
                f"{name} produced more than {MAX_PART_BYTES} bytes; its declared "
                "size understates its content",
            )
        self._spent += len(data)
        return data

    def peek(self, name: str) -> Optional[bytes]:
        """Read a member for scanning only; give up rather than refuse.

        Used for parts Word does not reach (see ``unreferenced_marker_parts``):
        an unreachable part being huge is a reason to skip it, not a reason to
        refuse the whole document.
        """
        info = self._zip.NameToInfo[name]
        too_big = info.file_size > MAX_PART_BYTES
        if too_big or self._spent + info.file_size > MAX_TOTAL_BYTES:
            self.budget_exhausted = True
            return None
        try:
            data = self._read_bounded(name)
        except _PartUnreadable:
            return None
        self._spent += len(data)
        return data

    def _read_bounded(self, name: str) -> bytes:
        try:
            with self._zip.open(name) as stream:
                return stream.read(MAX_PART_BYTES + 1)
        except (zipfile.BadZipFile, EOFError, RuntimeError, ValueError) as error:
            raise _PartUnreadable(str(error)) from error


def open_package(path: Union[str, Path]) -> WordPackage:
    """Open a DOCX for recovery. Raises RecoveryError for unusable packages."""
    return WordPackage(path)


def _valid_part_name(name: str) -> bool:
    if "\\" in name or name.startswith("/"):
        return False
    segments = name.rstrip("/").split("/")
    return all(segment not in ("", ".", "..") for segment in segments)


def _resolve(base: str, target: str) -> Optional[str]:
    """Resolve a relationship target to a package part name, or None."""
    if target.startswith("/"):
        candidate = target[1:]
    else:
        candidate = posixpath.normpath(posixpath.join(base, target))
    if candidate.startswith("../") or candidate in ("", ".", ".."):
        return None
    return candidate if _valid_part_name(candidate) else None


def _relationships(package: WordPackage, rels_part: str, issues: list[PartIssue]):
    """Yield (type, resolved part name) for one .rels part."""
    if not package.has(rels_part):
        return
    try:
        root = parse_xml_hardened(package.read(rels_part))
    except (UnsafeXML, _PartUnreadable) as error:
        issues.append(
            PartIssue("part_unreadable", f"cannot read {rels_part}: {error}", rels_part)
        )
        return
    if root.tag != f"{{{RELS_NS}}}Relationships":
        # Not a relationships document. Reading zero relationships out of it
        # would report a manuscript whose footnotes and headers cannot be
        # reached as a document that simply has none.
        issues.append(
            PartIssue(
                "part_rels_malformed",
                f"{rels_part} has root {root.tag}, not Relationships; the parts it "
                "should point at cannot be reached",
                rels_part,
            )
        )
        return
    base = posixpath.dirname(posixpath.dirname(rels_part))
    for node in root.findall(f"{{{RELS_NS}}}Relationship"):
        target = node.get("Target") or ""
        if (node.get("TargetMode") or "").lower() == "external":
            issues.append(
                PartIssue(
                    "relationship_target_external",
                    f"{rels_part} points outside the package at {target!r}; not read",
                    rels_part,
                )
            )
            continue
        resolved = _resolve(base, target)
        if resolved is None:
            issues.append(
                PartIssue(
                    "relationship_target_invalid",
                    f"{rels_part} has a target {target!r} that does not name a part "
                    "inside this package; not read",
                    rels_part,
                )
            )
            continue
        yield node.get("Type") or "", resolved


def _rels_part_for(part_name: str) -> str:
    directory, base = posixpath.split(part_name)
    return posixpath.join(directory, "_rels", base + ".rels")


def _main_document_name(package: WordPackage, issues: list[PartIssue]) -> str:
    if not package.has(CONTENT_TYPES_PART):
        issues.append(
            PartIssue(
                "package_incomplete",
                f"the package has no {CONTENT_TYPES_PART}; it is not a complete "
                "Word document and may be missing more than that",
            )
        )
    for rel_type, name in _relationships(package, PACKAGE_RELS_PART, issues):
        if rel_type == f"{OFFICE_REL}/officeDocument" and package.has(name):
            return name
    if package.has(DEFAULT_DOCUMENT_PART):
        return DEFAULT_DOCUMENT_PART
    raise RecoveryError(
        "document_part_missing",
        f"{package.path} has no main document part: no officeDocument "
        f"relationship and no {DEFAULT_DOCUMENT_PART}",
    )


def _parse_story(package: WordPackage, name: str) -> etree._Element:
    return parse_xml_hardened(package.read(name))


def story_parts(package: WordPackage) -> tuple[list[StoryPart], list[PartIssue]]:
    """Return the Word stories to scan, in a deterministic order, plus issues.

    The main document part is required: if it cannot be read or is not a
    ``w:document``, the whole package is refused, because a recovery report
    from an unreadable manuscript body would be a report about nothing. Any
    OTHER story failing is a finding — the readable parts are still recovered.
    """
    issues: list[PartIssue] = []
    main = _main_document_name(package, issues)
    try:
        root = _parse_story(package, main)
    except (UnsafeXML, _PartUnreadable) as error:
        raise RecoveryError(
            "document_part_unreadable", f"cannot read {main}: {error}"
        ) from error
    if root.tag != _q("document"):
        raise RecoveryError(
            "document_root_unexpected",
            f"{main} has root {root.tag}, not {_q('document')}; this is not a "
            "WordprocessingML document",
        )
    stories = [StoryPart(main, "document", root)]

    rels_part = _rels_part_for(main)
    if not package.has(rels_part):
        issues.append(
            PartIssue(
                "part_rels_missing",
                f"{main} has no {rels_part}; footnotes, endnotes, headers and "
                "footers cannot be reached the way Word reaches them",
                main,
            )
        )
        return stories, issues

    referenced: list[tuple[int, str, str]] = []
    # The main document is already a story: a relationship aimed back at it
    # (or two relationships aimed at one header) must not make its citations
    # count twice.
    seen: set[str] = {main}
    for rel_type, name in _relationships(package, rels_part, issues):
        kind = _STORY_RELS.get(rel_type)
        if kind is None or name in seen:
            continue
        seen.add(name)
        referenced.append((_STORY_ORDER.index(kind), name, kind))
    referenced.sort()
    if len(referenced) > MAX_STORY_PARTS:
        issues.append(
            PartIssue(
                "story_part_limit_reached",
                f"{len(referenced)} story parts are related from {main}; only the "
                f"first {MAX_STORY_PARTS} are scanned",
                main,
            )
        )
        referenced = referenced[:MAX_STORY_PARTS]

    for _rank, name, kind in referenced:
        if not package.has(name):
            issues.append(
                PartIssue(
                    "part_missing",
                    f"{main} relates a {kind} part {name} that is not in the package",
                    name,
                )
            )
            continue
        try:
            root = _parse_story(package, name)
        except (UnsafeXML, _PartUnreadable) as error:
            issues.append(
                PartIssue("part_unreadable", f"cannot read {name}: {error}", name)
            )
            continue
        if root.tag != _q(_EXPECTED_ROOTS[kind]):
            issues.append(
                PartIssue(
                    "part_root_unexpected",
                    f"{name} is related as a {kind} part but its root is {root.tag}; "
                    "scanned anyway",
                    name,
                )
            )
        stories.append(StoryPart(name, kind, root))
    return stories, issues


def unreferenced_marker_parts(
    package: WordPackage, scanned: set[str], markers: tuple[bytes, ...]
) -> list[str]:
    """Name the unreachable ``word/*.xml`` parts that contain citation markers.

    These are NOT recovered (Word does not render them), but a package
    carrying a header full of Zotero fields that nothing points at is exactly
    the kind of fact a recovery report must not swallow.
    """
    found: list[str] = []
    for name in sorted(package.names):
        if name in scanned or not name.startswith("word/") or not name.endswith(".xml"):
            continue
        if name.startswith("word/_rels/"):
            continue
        data = package.peek(name)
        if data is not None and any(marker in data for marker in markers):
            found.append(name)
    return found


# --- fields --------------------------------------------------------------------


@dataclass(frozen=True)
class _Flags:
    deleted: bool = False
    inserted: bool = False


def _walk(root) -> Iterator[tuple[etree._Element, _Flags]]:
    """Pre-order walk carrying tracked-change context, one MCE branch only.

    Iterative rather than recursive: a hostile part can nest elements deeply
    enough to end a recursive walk in a RecursionError, which is not one of
    the named failures this library is allowed to raise.

    ``mc:AlternateContent`` offers the same content twice — an ``mc:Choice``
    for consumers that understand some extension, an ``mc:Fallback`` for
    everyone else. Walking both counts every textbox citation twice, so
    exactly one branch is walked: the first Choice (what Word picks), or the
    Fallback when there is no Choice at all. More than one Choice is
    genuinely ambiguous and ``read_fields`` reports it.
    """
    stack: list[tuple[etree._Element, _Flags]] = [(root, _Flags())]
    while stack:
        element, flags = stack.pop()
        tag = element.tag
        yield element, flags
        child_flags = flags
        if tag in _DELETED_WRAPPERS:
            child_flags = replace(flags, deleted=True)
        elif tag in _INSERTED_WRAPPERS:
            child_flags = replace(flags, inserted=True)
        if tag == _MC_ALTERNATE_CONTENT:
            branch = _selected_branch(element)
            if branch is not None:
                stack.append((branch, child_flags))
            continue
        for child in reversed(list(element)):
            stack.append((child, child_flags))


def _selected_branch(alternate_content):
    """The one branch of an mc:AlternateContent to read, or None."""
    fallback = None
    for child in alternate_content:
        if child.tag == _MC_CHOICE:
            return child
        if child.tag == _MC_FALLBACK and fallback is None:
            fallback = child
    return fallback


@dataclass
class _Frame:
    index: int
    chunks: list[str]
    depth: int
    deleted: bool  # the field BEGAN inside a tracked deletion
    inserted: bool
    separated: bool = False
    live_runs: int = 0
    deleted_runs: int = 0


def read_fields(root) -> tuple[list[WordField], list[FieldIssue]]:
    """Assemble every field in one story, each from its own runs.

    The stack is the point. ``w:instrText`` belongs to the innermost field
    that has begun and not yet reached its ``w:fldChar separate``; a nested
    ``HYPERLINK`` in a citation's result never lands in the citation's
    instruction, and two adjacent citations never merge.
    """
    fields: list[WordField] = []
    issues: list[FieldIssue] = []
    stack: list[_Frame] = []
    next_index = 0
    stray_instructions = 0
    unmatched_ends = 0
    ambiguous_alternates = 0

    for element, flags in _walk(root):
        tag = element.tag
        if tag == _MC_ALTERNATE_CONTENT:
            if len(element.findall(_MC_CHOICE)) > 1:
                ambiguous_alternates += 1
        elif tag == _FLDCHAR:
            char_type = element.get(_FLDCHAR_TYPE)
            if char_type == "begin":
                stack.append(
                    _Frame(
                        index=next_index,
                        chunks=[],
                        depth=len(stack),
                        deleted=flags.deleted,
                        inserted=flags.inserted,
                    )
                )
                next_index += 1
            elif char_type == "separate":
                if stack:
                    stack[-1].separated = True
            elif char_type == "end":
                if stack:
                    fields.append(_close(stack.pop()))
                else:
                    unmatched_ends += 1
        elif tag == _INSTRTEXT or tag == _DELINSTRTEXT:
            if stack and not stack[-1].separated:
                frame = stack[-1]
                frame.chunks.append(element.text or "")
                if tag == _DELINSTRTEXT or flags.deleted:
                    frame.deleted_runs += 1
                else:
                    frame.live_runs += 1
            else:
                stray_instructions += 1
        elif tag == _FLDSIMPLE:
            fields.append(
                WordField(
                    index=next_index,
                    instruction=element.get(_INSTR) or "",
                    kind="simple",
                    depth=len(stack),
                    deleted=flags.deleted,
                    inserted=flags.inserted,
                )
            )
            next_index += 1

    if stack:
        issues.append(
            FieldIssue(
                "field_unterminated",
                f"{len(stack)} field(s) begin and never end; their instructions are "
                "reported as far as they were readable",
            )
        )
        for frame in stack:
            fields.append(_close(frame, unterminated=True))
    if unmatched_ends:
        issues.append(
            FieldIssue(
                "field_end_without_begin",
                f"{unmatched_ends} field end marker(s) have no matching begin; the "
                "field structure of this part is damaged",
            )
        )
    if stray_instructions:
        issues.append(
            FieldIssue(
                "instruction_outside_field",
                f"{stray_instructions} instruction run(s) sit outside any field "
                "instruction; they belong to no field and were not used",
            )
        )
    if ambiguous_alternates:
        issues.append(
            FieldIssue(
                "alternate_content_ambiguous",
                f"{ambiguous_alternates} mc:AlternateContent element(s) offer more "
                "than one mc:Choice; which branch Word renders depends on the "
                "extensions it supports, so only the first is read",
            )
        )
    partly_deleted = sum(1 for field in fields if field.instruction_partly_deleted)
    if partly_deleted:
        issues.append(
            FieldIssue(
                "field_instruction_partly_deleted",
                f"{partly_deleted} field instruction(s) are partly deleted under "
                "Track Changes: accepting and rejecting the changes give different "
                "instructions, and this report shows the instruction as stored",
            )
        )
    fields.sort(key=lambda field: field.index)
    return fields, issues


def _close(frame: _Frame, unterminated: bool = False) -> WordField:
    """Finish a field, deciding what its tracked-change state actually is.

    Deleted means the whole field is gone: it began inside a deletion, or
    every run of its instruction is deleted text. A field with SOME deleted
    instruction runs is a different thing — accepting and rejecting the
    changes give two different instructions — and is flagged rather than
    quietly treated as either one.
    """
    partly_deleted = frame.deleted_runs > 0 and frame.live_runs > 0
    deleted = frame.deleted or (frame.deleted_runs > 0 and frame.live_runs == 0)
    return WordField(
        index=frame.index,
        instruction="".join(frame.chunks),
        kind="complex",
        depth=frame.depth,
        deleted=deleted,
        inserted=frame.inserted,
        unterminated=unterminated,
        instruction_partly_deleted=partly_deleted,
    )


def bookmark_names(root) -> list[str]:
    """Every ``w:bookmarkStart`` name in a story, in document order."""
    return [
        name
        for element in root.iter(_BOOKMARK_START)
        if (name := element.get(_BOOKMARK_NAME))
    ]
