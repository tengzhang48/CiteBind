"""OPC conformance of the documents CiteBind produces.

These are the structural checks Word performs before it offers to "repair" a
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

        for name in names:
            if "itemProps" in name:
                match = re.search(r'itemID="([^"]+)"', package.read(name).decode())
                if match and not ST_GUID.match(match.group(1)):
                    problems.append(f"{name}: itemID {match.group(1)!r} is not ST_Guid")

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
