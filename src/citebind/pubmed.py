"""The PubMed resolver: a PMID to a verified Reference, over the transport seam.

Same shape and same absence rule as the Crossref resolver: a missing field
is None on the Reference. PubMed's esummary reports absent issues as the
empty string; an empty string is absence, and the resolver says so here so
nobody re-learns it in the document layer.

Mapping decisions (stated, not silent):
- journal prefers ``fulljournalname`` (the full name, consistent with what
  Crossref gives) and falls back to ``source`` (the ISO abbreviation);
- ``issue: ""`` is absence;
- authors are the ``name`` strings, verbatim — PubMed abbreviates initials
  ("Belletti D") where Crossref spells them out; that difference belongs to
  the comparison layer, not to a cleanup pass here;
- year comes from the leading year of ``pubdate``.

Provenance: ``metadata_source`` is "pubmed", ``retrieved_at`` is a
parameter — the resolver is a pure mapping.
"""

from typing import Optional

from .identifiers import normalize_pmid
from .model import Reference
from .transport import (
    ResponseError,
    Transport,
    TransportResponse,
    check_status,
    decode_json,
)

PUBMED_SUMMARY_URL = (
    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
    "?db=pubmed&retmode=json&id={pmid}"
)


class ResponseShapeError(ResponseError):
    """The response parsed as JSON but is not a shape we can use."""

    def __init__(self, detail: str):
        super().__init__("unexpected_shape", detail)


class RecordNotFoundError(ResponseError):
    """PubMed answered, but has no summary for this PMID."""

    def __init__(self, pmid: str, detail: str):
        super().__init__("record_not_found", f"no PubMed record for '{pmid}': {detail}")


def _first_text(value) -> Optional[str]:
    if isinstance(value, str) and value.strip():
        return value
    if isinstance(value, list) and value and isinstance(value[0], str) and value[0].strip():
        return value[0]
    return None


def _summary(response: TransportResponse, pmid: str) -> dict:
    check_status(response, source="pubmed")
    document = decode_json(response, source="pubmed")
    result = document.get("result") if isinstance(document, dict) else None
    if not isinstance(result, dict) or not result.get("uids"):
        raise RecordNotFoundError(pmid, "empty result")
    if isinstance(result.get(pmid), dict) and result[pmid].get("error"):
        raise RecordNotFoundError(pmid, str(result[pmid]["error"]))
    doc = result.get(pmid)
    if not isinstance(doc, dict):
        raise RecordNotFoundError(pmid, "no summary for the requested id")
    return doc


def _year(doc: dict) -> Optional[int]:
    for key in ("pubdate", "epubdate"):
        value = doc.get(key)
        if isinstance(value, str) and value[:4].isdigit():
            return int(value[:4])
    return None


def _journal(doc: dict) -> Optional[str]:
    full = _first_text(doc.get("fulljournalname"))
    if full is not None:
        return full
    return _first_text(doc.get("source"))


def summary_to_fields(pmid: str, doc: dict) -> dict:
    """PubMed esummary document to a citebind/1 metadata dict (id/pmid omitted).

    Public because the title-search layer reuses it for every candidate.
    """
    title = _first_text(doc.get("title"))
    journal = _journal(doc)
    year = _year(doc)

    missing = [
        name
        for name, value in (("title", title), ("journal", journal), ("year", year))
        if value is None
    ]
    if missing:
        raise RecordIncompleteError(
            f"record is missing required field(s): {', '.join(missing)}; "
            "a citebind reference cannot be built from it"
        )

    authors = doc.get("authors")
    if authors is not None and (
        not isinstance(authors, list)
        or not all(isinstance(author, dict) for author in authors)
    ):
        # Present but not a list of mappings: a shape we cannot read. Refused
        # rather than filtered, because filtering a malformed field silently
        # produced a reference with NO authors -- data loss dressed as a
        # record whose authors were simply absent.
        raise ResponseShapeError(
            f"PubMed 'authors' for '{pmid}' is not a list of author objects; "
            f"got {type(authors).__name__}"
        )

    result: dict = {
        "title": title,
        "authors": [
            author["name"]
            for author in authors or []
            if author.get("name")
        ],
        "journal": journal,
        "year": year,
        "metadata_source": "pubmed",
    }
    for field, key in (("volume", "volume"), ("issue", "issue"), ("pages", "pages")):
        value = doc.get(key)
        if isinstance(value, str) and value.strip():
            result[field] = value
    return result


class RecordIncompleteError(ResponseError):
    """The record lacks a required citebind/1 field; refused, never blanked."""

    def __init__(self, detail: str):
        super().__init__("missing_required_field", detail)


def resolve_pmid(
    pmid: str,
    transport: Transport,
    reference_id: str,
    retrieved_at: str,
) -> Reference:
    """Resolve a PMID to a Reference using ``transport``.

    ``pmid`` is normalized first (canonical digits, leading zeros dropped;
    PMCIDs are refused by name before any request is made).
    """
    canonical = normalize_pmid(pmid)
    url = PUBMED_SUMMARY_URL.format(pmid=canonical)
    doc = _summary(transport.fetch(url), canonical)

    fields = summary_to_fields(canonical, doc)
    return Reference.from_dict(
        {"id": reference_id, "pmid": canonical, "retrieved_at": retrieved_at, **fields}
    )
