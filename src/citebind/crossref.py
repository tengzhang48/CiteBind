"""The Crossref resolver: a DOI to a verified Reference, over the transport seam.

One rule above all: **absent metadata stays absent.** Crossref records are
routinely incomplete; a missing volume, issue, or page becomes None on the
Reference — never an inference, never a reconstruction, never an empty
string wearing a real value's clothes. Required fields (title, journal,
year) are different: a record without them cannot be a valid citebind/1
reference, so the resolver refuses by name rather than emitting a blank.

Provenance is part of the data: ``metadata_source`` records that Crossref
said it, ``retrieved_at`` records when. The timestamp is a parameter, not
a clock — the resolver is a pure mapping and tests stay deterministic.
"""

import urllib.parse
from typing import Optional

from .identifiers import normalize_doi
from .model import Reference
from .transport import (
    ResponseError,
    Transport,
    TransportResponse,
    check_status,
    decode_json,
)

CROSSREF_URL = "https://api.crossref.org/works/{doi}"
SELECT_WORK_FIELDS = "DOI,title,author,container-title,volume,issue,page,published"


def title_search_url(title: str, rows: int = 5) -> str:
    """The Crossref URL for an exact-title query (shared with the recorder)."""
    return (
        "https://api.crossref.org/works"
        f"?query.bibliographic={urllib.parse.quote(title, safe='')}"
        f"&rows={rows}&select={SELECT_WORK_FIELDS}"
    )


class ResponseShapeError(ResponseError):
    """The response parsed as JSON but is not a shape we can use."""

    def __init__(self, detail: str):
        super().__init__("unexpected_shape", detail)


class RecordIncompleteError(ResponseError):
    """The record lacks a required citebind/1 field; refused, never blanked."""

    def __init__(self, detail: str):
        super().__init__("missing_required_field", detail)


def _first_text(value) -> Optional[str]:
    if isinstance(value, list) and value and isinstance(value[0], str) and value[0].strip():
        return value[0]
    return None


def _year(message: dict) -> Optional[int]:
    for key in ("published", "issued", "created"):
        node = message.get(key) or {}
        parts = node.get("date-parts") or []
        if parts and parts[0] and isinstance(parts[0][0], int):
            return parts[0][0]
    return None


def _author_names(message: dict) -> list[str]:
    names: list[str] = []
    for author in message.get("author") or []:
        if "name" in author:  # organizational author
            names.append(author["name"])
        else:
            parts = [author.get("given"), author.get("family")]
            joined = " ".join(part for part in parts if part)
            if joined:
                names.append(joined)
    return names


def work_to_fields(message: dict) -> dict:
    """Crossref work message to a citebind/1 metadata dict (id/doi omitted).

    Public because the title-search layer reuses it for every candidate.
    """
    title = _first_text(message.get("title"))
    journal = _first_text(message.get("container-title"))
    year = _year(message)

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

    result: dict = {
        "title": title,
        "authors": _author_names(message),
        "journal": journal,
        "year": year,
        "metadata_source": "crossref",
    }
    for field, key in (("volume", "volume"), ("issue", "issue"), ("pages", "page")):
        value = message.get(key)
        if isinstance(value, str) and value.strip():
            result[field] = value
    return result


def _message(response: TransportResponse, doi: str) -> dict:
    check_status(response, source="crossref")
    document = decode_json(response, source="crossref")
    if not isinstance(document, dict) or not isinstance(document.get("message"), dict):
        raise ResponseShapeError(
            f"Crossref response for '{doi}' has no work message; "
            "the envelope shape is unexpected"
        )
    return document["message"]


def resolve_doi(
    doi: str,
    transport: Transport,
    reference_id: str,
    retrieved_at: str,
) -> Reference:
    """Resolve a DOI to a Reference using ``transport``.

    ``doi`` is normalized first (every spelling resolves through the same
    canonical URL). ``reference_id`` is the document-layer id (R001, ...)
    assigned by the caller; ``retrieved_at`` is the retrieval timestamp.
    """
    canonical = normalize_doi(doi)
    url = CROSSREF_URL.format(doi=canonical)
    message = _message(transport.fetch(url), canonical)

    fields = work_to_fields(message)
    return Reference.from_dict(
        {"id": reference_id, "doi": canonical, "retrieved_at": retrieved_at, **fields}
    )
