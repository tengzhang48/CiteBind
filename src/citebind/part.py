"""Embed the citebind/1 payload into a DOCX as a custom XML part, and recover it.

The brief expected to write ``customXml/item1.xml``, but Word documents
(including python-docx's own default template) already use that part for the
built-in bibliography sources (``b:Sources``). CiteBind therefore allocates
the next free ``customXml/itemN.xml`` slot — the same convention Word uses
when adding a second custom XML part — and reuses its slot on re-embed. The
root namespace ``urn:citebind:citebind:1`` plus the fixed datastore GUID in
``itemPropsN.xml`` identify the part as ours.

Wiring follows the OPC convention: a package-level relationship in
``_rels/.rels`` to the item, an item-to-properties relationship in
``customXml/_rels/itemN.xml.rels``, and two overrides in
``[Content_Types].xml``.

Identification for ``extract`` is by content: any ``customXml/itemN.xml``
whose root is ``{urn:citebind:citebind:1}document``. (The GUID is wired for
Word's benefit; scanning by root keeps the reader independent of the slot
number.)
"""

import re
import zipfile
from pathlib import Path
from typing import Optional, Union

from lxml import etree

from .model import CiteBindDocument
from .xmlsafe import UnsafeXML, parse_xml_hardened

CITEBIND_NS = "urn:citebind:citebind:1"
CB = f"{{{CITEBIND_NS}}}"
ROOT_TAG = f"{CB}document"

DATASTORE_ITEM_ID = "26366BC3-6DD7-4AA2-9975-5716BAA0AD41"

CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
RELS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CUSTOM_XML_REL_TYPE = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/customXml"
)
CUSTOM_XML_PROPS_REL_TYPE = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/customXmlProps"
)
CUSTOM_XML_DATASTORE_NS = (
    "http://schemas.openxmlformats.org/officeDocument/2006/customXml"
)

CONTENT_TYPES_PART = "[Content_Types].xml"
PACKAGE_RELS_PART = "_rels/.rels"

_ITEM_RE = re.compile(r"^customXml/item(\d+)\.xml$")


class PayloadError(Exception):
    """The custom XML part is unusable as a citebind/1 payload."""

    def __init__(self, code: str, message: str):
        super().__init__(f"[{code}] {message}")
        self.code = code


# --- slot allocation -----------------------------------------------------------


def find_citebind_part(source: zipfile.ZipFile) -> Optional[str]:
    """Return the name of the item part carrying our payload root, if any.

    A custom XML item with a DOCTYPE is refused loudly even if it is not
    ours: untrusted input does not get the benefit of the doubt. A package
    carrying TWO citebind payload parts is refused as well — choosing one
    silently would be a coin flip (review note F4).
    """
    found: Optional[str] = None
    for name in source.namelist():
        if not _ITEM_RE.match(name):
            continue
        try:
            root = parse_xml_hardened(source.read(name))
        except UnsafeXML as error:
            if error.code == "doctype_declared":
                raise PayloadError(error.code, f"refusing {name}: {error}") from error
            continue
        if root.tag == ROOT_TAG:
            if found is not None:
                raise PayloadError(
                    "multiple_payload_parts",
                    f"citebind payload found in both {found} and {name}; "
                    "refusing to choose one",
                )
            found = name
    return found


def _item_numbers(names) -> set[int]:
    return {
        int(match.group(1))
        for name in names
        if (match := _ITEM_RE.match(name))
    }


def _allocate_slot(source: zipfile.ZipFile) -> int:
    existing = find_citebind_part(source)
    if existing is not None:
        return int(_ITEM_RE.match(existing).group(1))
    return max(_item_numbers(source.namelist()), default=0) + 1


# --- payload <-> XML -----------------------------------------------------------


def _sub(parent, name, text=None):
    element = etree.SubElement(parent, f"{CB}{name}")
    if text is not None:
        element.text = str(text)
    return element


def payload_to_xml(doc: CiteBindDocument) -> bytes:
    root = etree.Element(f"{CB}document", schema_version=doc.schema_version)
    _sub(root, "selected_style", doc.selected_style)
    references = _sub(root, "references")
    for ref in doc.references:
        node = _sub(references, "reference")
        node.set("id", ref.id)
        for key in ("doi", "pmid", "title"):
            value = getattr(ref, key)
            if value is not None:
                _sub(node, key, value)
        authors = _sub(node, "authors")
        for author in ref.authors:
            _sub(authors, "author", author)
        if ref.author_names is not None:
            structured = _sub(node, "author_names")
            for name in ref.author_names:
                name_node = _sub(structured, "name")
                for key in ("family", "given", "literal"):
                    value = getattr(name, key)
                    if value is not None:
                        _sub(name_node, key, value)
        _sub(node, "journal", ref.journal)
        _sub(node, "year", ref.year)
        for key in ("volume", "issue", "pages"):
            value = getattr(ref, key)
            if value is not None:
                _sub(node, key, value)
        _sub(node, "metadata_source", ref.metadata_source)
        _sub(node, "retrieved_at", ref.retrieved_at)
    clusters = _sub(root, "citation_clusters")
    for cluster in doc.citation_clusters:
        node = _sub(clusters, "cluster")
        node.set("id", cluster.id)
        ids = _sub(node, "reference_ids")
        for reference_id in cluster.reference_ids:
            _sub(ids, "reference_id", reference_id)
        for key in ("locator", "prefix", "suffix"):
            value = getattr(cluster, key)
            if value is not None:
                _sub(node, key, value)
    return etree.tostring(
        etree.ElementTree(root), xml_declaration=True, encoding="UTF-8"
    )


def payload_to_dict(data: bytes) -> dict:
    """Convert payload XML bytes to its dict form WITHOUT schema validation.

    Used by the verifier to inspect payloads that may be damaged: structural
    findings (duplicate ids, dangling references) must be reportable even when
    full validation would abort on an earlier error.
    """
    root = parse_xml_hardened(data)
    if root.tag != ROOT_TAG:
        raise PayloadError(
            "payload_root_unrecognized",
            f"expected root {ROOT_TAG}, got {root.tag}",
        )
    payload: dict = {"schema_version": root.get("schema_version")}
    selected_style = root.find(f"{CB}selected_style")
    payload["selected_style"] = (
        selected_style.text if selected_style is not None else None
    )
    payload["references"] = [
        _reference_to_dict(node)
        for node in root.findall(f"{CB}references/{CB}reference")
    ]
    payload["citation_clusters"] = [
        _cluster_to_dict(node)
        for node in root.findall(f"{CB}citation_clusters/{CB}cluster")
    ]
    return payload


def xml_to_payload(data: bytes) -> CiteBindDocument:
    return CiteBindDocument.from_dict(payload_to_dict(data))


def _reference_to_dict(node) -> dict:
    result: dict = {"id": node.get("id")}
    for key in (
        "doi",
        "pmid",
        "title",
        "journal",
        "volume",
        "issue",
        "pages",
        "metadata_source",
        "retrieved_at",
    ):
        child = node.find(f"{CB}{key}")
        if child is not None and child.text is not None:
            result[key] = child.text
    year = node.find(f"{CB}year")
    if year is not None and year.text is not None:
        result["year"] = int(year.text)
    authors = node.find(f"{CB}authors")
    if authors is not None:
        result["authors"] = [
            author.text or "" for author in authors.findall(f"{CB}author")
        ]
    structured = node.find(f"{CB}author_names")
    if structured is not None:
        names = []
        for name_node in structured.findall(f"{CB}name"):
            name: dict = {}
            for key in ("family", "given", "literal"):
                child = name_node.find(f"{CB}{key}")
                if child is not None and child.text is not None:
                    name[key] = child.text
            names.append(name)
        result["author_names"] = names
    return result


def _cluster_to_dict(node) -> dict:
    result: dict = {"id": node.get("id")}
    ids = node.find(f"{CB}reference_ids")
    if ids is not None:
        result["reference_ids"] = [
            reference_id.text or ""
            for reference_id in ids.findall(f"{CB}reference_id")
        ]
    for key in ("locator", "prefix", "suffix"):
        child = node.find(f"{CB}{key}")
        if child is not None and child.text is not None:
            result[key] = child.text
    return result


# --- OPC package wiring ---------------------------------------------------------


def _item_props_xml() -> bytes:
    ds = f"{{{CUSTOM_XML_DATASTORE_NS}}}"
    root = etree.Element(
        f"{ds}datastoreItem", nsmap={"ds": CUSTOM_XML_DATASTORE_NS}
    )
    root.set(f"{ds}itemID", DATASTORE_ITEM_ID)
    return etree.tostring(
        etree.ElementTree(root), xml_declaration=True, encoding="UTF-8"
    )


def _item_rels_xml(n: int) -> bytes:
    root = etree.Element(f"{{{RELS_NS}}}Relationships")
    etree.SubElement(
        root,
        f"{{{RELS_NS}}}Relationship",
        Id="rId1",
        Type=CUSTOM_XML_PROPS_REL_TYPE,
        Target=f"itemProps{n}.xml",
    )
    return etree.tostring(
        etree.ElementTree(root), xml_declaration=True, encoding="UTF-8"
    )


def _props_content_type(root) -> str:
    """Mirror the props content type already used in this document, if any.

    The python-docx template carries legacy ``...customXmlProperties+xml``
    (old Word output); ECMA-376 registers ``...customXmlProps+xml``. Within
    one document, consistency matters more than which of the two we pick.
    """
    ct = f"{{{CT_NS}}}"
    for node in root.findall(f"{ct}Override"):
        if re.match(r"^/customXml/itemProps\d+\.xml$", node.get("PartName", "")):
            return node.get("ContentType")
    return "application/vnd.openxmlformats-officedocument.customXmlProps+xml"


def _updated_content_types(data: bytes, n: int) -> bytes:
    root = parse_xml_hardened(data)
    ct = f"{{{CT_NS}}}"
    props_part = f"/customXml/itemProps{n}.xml"
    existing = {node.get("PartName") for node in root.findall(f"{ct}Override")}
    if props_part not in existing:
        etree.SubElement(
            root,
            f"{ct}Override",
            PartName=props_part,
            ContentType=_props_content_type(root),
        )
    # The item data part needs an Override only when no Default covers .xml.
    has_xml_default = any(
        node.get("Extension", "").lower() == "xml" for node in root.findall(f"{ct}Default")
    )
    if not has_xml_default and f"/customXml/item{n}.xml" not in existing:
        etree.SubElement(
            root,
            f"{ct}Override",
            PartName=f"/customXml/item{n}.xml",
            ContentType="application/vnd.openxmlformats-officedocument.customXml+xml",
        )
    return etree.tostring(
        etree.ElementTree(root), xml_declaration=True, encoding="UTF-8"
    )


def _updated_package_rels(data: bytes, n: int) -> bytes:
    root = parse_xml_hardened(data)
    rels = f"{{{RELS_NS}}}"
    target = f"customXml/item{n}.xml"
    existing_targets = {
        node.get("Target")
        for node in root.findall(f"{rels}Relationship")
        if node.get("Type") == CUSTOM_XML_REL_TYPE
    }
    if target in existing_targets:
        return data
    numeric_ids = []
    for node in root.findall(f"{rels}Relationship"):
        raw = node.get("Id", "")
        if raw.startswith("rId") and raw[3:].isdigit():
            numeric_ids.append(int(raw[3:]))
    etree.SubElement(
        root,
        f"{{{RELS_NS}}}Relationship",
        Id=f"rId{max(numeric_ids, default=0) + 1}",
        Type=CUSTOM_XML_REL_TYPE,
        Target=target,
    )
    return etree.tostring(
        etree.ElementTree(root), xml_declaration=True, encoding="UTF-8"
    )


def embed(
    docx_path: Union[str, Path],
    doc: CiteBindDocument,
    out_path: Union[str, Path],
) -> str:
    """Write ``doc`` into a copy of ``docx_path`` as the citebind custom XML part.

    Returns the name of the item part written (e.g. ``customXml/item2.xml``).
    Refuses to overwrite a foreign payload occupying CiteBind's existing slot.
    """
    payload = payload_to_xml(doc)
    with zipfile.ZipFile(docx_path) as source:
        existing = find_citebind_part(source)
        if existing is not None:
            current_root = parse_xml_hardened(source.read(existing))
            if current_root.tag != ROOT_TAG:
                raise PayloadError(
                    "embed_refuses_foreign_part",
                    f"{docx_path} already carries a foreign {existing}; "
                    "refusing to overwrite",
                )
        n = _allocate_slot(source)
        part_name = f"customXml/item{n}.xml"
        replacements: dict[str, bytes] = {
            part_name: payload,
            f"customXml/itemProps{n}.xml": _item_props_xml(),
            f"customXml/_rels/item{n}.xml.rels": _item_rels_xml(n),
            CONTENT_TYPES_PART: _updated_content_types(
                source.read(CONTENT_TYPES_PART), n
            ),
            PACKAGE_RELS_PART: _updated_package_rels(
                source.read(PACKAGE_RELS_PART), n
            ),
        }
        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as target:
            replaced: set[str] = set()
            for item in source.infolist():
                if item.filename in replacements:
                    target.writestr(item.filename, replacements[item.filename])
                    replaced.add(item.filename)
                else:
                    target.writestr(item.filename, source.read(item.filename))
            for name, data in replacements.items():
                if name not in replaced:
                    target.writestr(name, data)
    return part_name


def extract(docx_path: Union[str, Path]) -> Optional[CiteBindDocument]:
    """Return the embedded CiteBindDocument, or None if this DOCX has no payload."""
    with zipfile.ZipFile(docx_path) as source:
        part_name = find_citebind_part(source)
        if part_name is None:
            return None
        data = source.read(part_name)
    return xml_to_payload(data)
