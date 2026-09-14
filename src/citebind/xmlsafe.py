"""Hardened XML parsing for untrusted OOXML parts.

House style (learned from ArtifactCert's OPC layer): every package part is
parsed with ``resolve_entities=False``, ``load_dtd=False``, ``no_network=True``,
``recover=False``, ``huge_tree=False`` — and a part containing a DOCTYPE or an
entity reference is refused outright, because entity expansion would make the
parsed content differ from the bytes actually present.
"""

from lxml import etree

_PARSER = etree.XMLParser(
    resolve_entities=False,
    load_dtd=False,
    no_network=True,
    recover=False,
    huge_tree=False,
)


class UnsafeXML(Exception):
    """An XML part was refused before parsing: it is not plain XML."""

    def __init__(self, code: str, message: str):
        super().__init__(f"[{code}] {message}")
        self.code = code


def parse_xml_hardened(data: bytes) -> etree._Element:
    """Parse untrusted XML bytes, refusing DOCTYPEs and entity references."""
    if b"<!DOCTYPE" in data or b"<!doctype" in data:
        raise UnsafeXML(
            "doctype_declared",
            "refusing XML containing a DOCTYPE declaration",
        )
    try:
        tree = etree.fromstring(data, parser=_PARSER)
    except etree.XMLSyntaxError as error:
        raise UnsafeXML("xml_syntax", f"refusing malformed XML: {error}") from error
    for _event, element in etree.iterwalk(tree, events=("end",)):
        if isinstance(element, etree._Entity):
            raise UnsafeXML(
                "entity_reference",
                f"refusing XML containing an entity reference: {element.name}",
            )
    return tree
