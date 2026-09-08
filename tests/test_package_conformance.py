"""OPC and Word preflight for the documents CiteBind produces.

PARTIAL, and the name matters: passing here means the package is internally
consistent and carries the Word-specific structure we know to check. It is not
a conformance proof, and it is not a substitute for opening the file in Word.
Two of the checks below exist only because an external review found what they
now catch, which is a fair measure of how complete the rest of it is.


These are structural checks Word performs before it offers to "repair" a
file. They exist because a malformed package fails the Phase 1 spike for the
WRONG REASON: a repair prompt caused by our own invalid attribute would read
as "Word does not preserve content controls", and the spike would be recorded
as evidence against the architecture instead of against a typo.

The audit is exercised against a planted defect below, so a green run here
means the checks can actually fail.
"""

import posixpath
import re
import zipfile

import pytest

from citebind.spike import make_spike

CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
RELS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

# ECMA-376 ST_Guid. Word's own parts use this form; ours did not, for the
# project's first weeks (see part.DATASTORE_ITEM_ID).
ST_GUID = re.compile(
    r"^\{[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}\}$"
)


def audit(path) -> list[str]:
    """Return every OPC problem found in the package at ``path``."""
    from lxml import etree

    problems: list[str] = []
    with zipfile.ZipFile(path) as package:
        names = [n for n in package.namelist() if not n.endswith("/")]

        content_types = etree.fromstring(package.read("[Content_Types].xml"))
        defaults = {
            node.get("Extension", "").lower()
            for node in content_types.findall(f"{{{CT_NS}}}Default")
        }
        overrides = {
            node.get("PartName")
            for node in content_types.findall(f"{{{CT_NS}}}Override")
        }
        for name in names:
            if name == "[Content_Types].xml" or f"/{name}" in overrides:
                continue
            extension = name.rsplit(".", 1)[-1].lower() if "." in name else ""
            if extension not in defaults:
                problems.append(f"no content type for part /{name}")
        for part in overrides:
            if part.lstrip("/") not in names:
                problems.append(f"Override names a missing part: {part}")

        for name in names:
            if not name.endswith(".rels"):
                continue
            base = posixpath.dirname(posixpath.dirname(name))
            for node in etree.fromstring(package.read(name)).findall(
                f"{{{RELS_NS}}}Relationship"
            ):
                if node.get("TargetMode") == "External":
                    continue
                resolved = posixpath.normpath(
                    posixpath.join(base, node.get("Target"))
                )
                if resolved not in names:
                    problems.append(
                        f"{name}: relationship {node.get('Id')} targets "
                        f"{resolved}, which is not in the package"
                    )

        item_ids: list[str] = []
        for name in names:
            if "itemProps" in name:
                match = re.search(r'itemID="([^"]+)"', package.read(name).decode())
                if match:
                    item_ids.append(match.group(1))
                    if not ST_GUID.match(match.group(1)):
                        problems.append(
                            f"{name}: itemID {match.group(1)!r} is not ST_Guid"
                        )
        # ds:itemID must be unique among a document's custom XML data parts.
        # Syntactic validity was checked before uniqueness was, and a single
        # fixed GUID satisfies the first while failing the second.
        if len(item_ids) != len(set(item_ids)):
            duplicates = sorted({i for i in item_ids if item_ids.count(i) > 1})
            problems.append(f"duplicate ds:itemID values: {duplicates}")

        # A custom XML part is related FROM the main document part. Our reader
        # finds the payload by scanning zip members, so every Python test can
        # pass while Word's relationship graph never reaches it.
        document_rels = "word/_rels/document.xml.rels"
        if document_rels in names:
            related = {
                node.get("Target")
                for node in etree.fromstring(package.read(document_rels)).findall(
                    f"{{{RELS_NS}}}Relationship"
                )
                if node.get("Type", "").endswith("/customXml")
            }
            for name in names:
                if re.match(r"^customXml/item\d+\.xml$", name):
                    if f"../{name}" not in related:
                        problems.append(
                            f"{name} is in the package but no relationship in "
                            f"{document_rels} points at it"
                        )

        document = etree.fromstring(package.read("word/document.xml"))
        for sdt in document.iter(f"{W}sdt"):
            tag = sdt.find(f"{W}sdtPr/{W}tag")
            content = sdt.find(f"{W}sdtContent")
            if tag is None or not tag.get(f"{W}val"):
                problems.append("a w:sdt carries no tag value")
            if content is None or len(content) == 0:
                problems.append("a w:sdt has empty sdtContent")
    return problems


@pytest.fixture
def spike(tmp_path):
    return make_spike(tmp_path)


def test_spike_document_is_opc_conformant(spike):
    """The file a human carries to a machine with Word."""
    assert audit(spike) == []


def test_the_audit_catches_a_planted_defect(spike, tmp_path):
    """Mutation test of the gate itself: strip the braces off the itemID, the
    exact defect that shipped, and confirm the audit reports it. A gate that
    cannot fail certifies nothing."""
    broken = tmp_path / "broken.docx"
    with zipfile.ZipFile(spike) as source, zipfile.ZipFile(broken, "w") as target:
        for item in source.infolist():
            data = source.read(item.filename)
            if "itemProps" in item.filename:
                data = data.replace(b'itemID="{', b'itemID="').replace(b'}"', b'"')
            target.writestr(item.filename, data)
    problems = audit(broken)
    assert any("ST_Guid" in problem for problem in problems), problems


def test_the_audit_catches_duplicate_item_ids(spike, tmp_path):
    """Mutation test: give two itemProps parts the same ID — the exact state
    embedding beside a clobbered CiteBind slot used to produce."""
    broken = tmp_path / "dup_ids.docx"
    with zipfile.ZipFile(spike) as source, zipfile.ZipFile(broken, "w") as target:
        first = None
        for item in source.infolist():
            data = source.read(item.filename)
            if "itemProps" in item.filename:
                match = re.search(rb'itemID="([^"]+)"', data)
                if first is None and match:
                    first = match.group(1)
                elif match:
                    data = data.replace(match.group(1), first)
            target.writestr(item.filename, data)
    problems = audit(broken)
    assert any("duplicate ds:itemID" in problem for problem in problems), problems


def test_the_audit_catches_a_payload_word_cannot_reach(spike, tmp_path):
    """Mutation test: move the relationship back to the package root, which is
    where CiteBind put it until an external review caught it.

    Our own reader still finds the payload by scanning zip members, so this
    document passes `inspect` — which is exactly why the audit has to be the
    thing that notices."""
    from lxml import etree

    broken = tmp_path / "wrong_rel_parent.docx"
    with zipfile.ZipFile(spike) as source, zipfile.ZipFile(broken, "w") as target:
        for item in source.infolist():
            data = source.read(item.filename)
            if item.filename == "word/_rels/document.xml.rels":
                root = etree.fromstring(data)
                for node in list(root.findall(f"{{{RELS_NS}}}Relationship")):
                    target_attr = node.get("Target", "")
                    if node.get("Type", "").endswith("/customXml") and target_attr.endswith(
                        "item2.xml"
                    ):
                        root.remove(node)
                data = etree.tostring(root, xml_declaration=True, encoding="UTF-8")
            target.writestr(item.filename, data)
    problems = audit(broken)
    assert any("no relationship" in problem for problem in problems), problems

    # and the point: the verifier is happy with it
    from citebind.verify import inspect

    assert inspect(broken).is_clean
