"""Title search: an ordered candidate list, never a selection.

The researcher types an exact title; the sources answer with ranked
candidates. This module returns those candidates — identifier, metadata,
source — and nothing else. It is structurally incapable of handing back a
Reference: candidates carry display metadata only, the CandidateList has
no default and no first-choice accessor, and the ONLY path to a Reference
is ``select()``, which names a candidate explicitly and re-resolves its
identifier through the transport. A fresh, verified fetch — never the
search payload — is what becomes a reference, because one candidate being
listed first is a search engine's opinion, and the human confirming it is
the only thing standing between this product and the failure it exists to
prevent.
"""

from dataclasses import dataclass
from typing import Optional

from .crossref import (
    ResponseShapeError,
    resolve_doi,
    title_search_url,
    work_to_fields,
)
from .identifiers import normalize_doi
from .model import Reference
from .pubmed import PUBMED_SUMMARY_URL, resolve_pmid, summary_to_fields
from .transport import (
    ResponseError,
    Transport,
    check_status,
    decode_json,
    require_non_empty,
)


@dataclass(frozen=True)
class Candidate:
    """One source's answer for a title query, for display and confirmation."""

    source: str  # "crossref" | "pubmed"
    kind: str  # "doi" | "pmid"
    identifier: str  # canonical form
    summary: dict  # citebind/1-shaped metadata fields, for the human


@dataclass(frozen=True)
class CandidateList:
    """Ranked candidates for one query. No default, no first accessor."""

    query_title: str
    candidates: tuple[Candidate, ...]

    def __iter__(self):
        return iter(self.candidates)

    def __len__(self) -> int:
        return len(self.candidates)


def _crossref_candidates(title: str, transport: Transport, rows: int) -> list[Candidate]:
    response = transport.fetch(title_search_url(title, rows))
    check_status(response, source="crossref")
    document = decode_json(response, source="crossref")
    items = (
        document.get("message", {}).get("items")
        if isinstance(document, dict)
        else None
    )
    if items is not None and (
        not isinstance(items, list)
        or not all(isinstance(item, dict) for item in items)
    ):
        raise ResponseShapeError(
            "Crossref search 'items' is not a list of work objects; "
            f"got {type(items).__name__}"
        )
    require_non_empty(items or [], source="crossref", what="title search")
    candidates: list[Candidate] = []
    for item in items:
        doi = item.get("DOI")
        if not doi:
            continue
        try:
            fields = work_to_fields(item)
        except ResponseError:
            # a candidate missing required fields is not offered as one:
            # it could never become a valid reference
            continue
        candidates.append(
            Candidate(
                source="crossref",
                kind="doi",
                identifier=normalize_doi(doi),
                summary=fields,
            )
        )
    return candidates


def _pubmed_candidates(title: str, transport: Transport) -> list[Candidate]:
    import urllib.parse

    search_url = (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
        f"?db=pubmed&retmode=json&term={urllib.parse.quote(title, safe='')}"
    )
    search_response = transport.fetch(search_url)
    check_status(search_response, source="pubmed")
    search = decode_json(search_response, source="pubmed")
    idlist = search.get("esearchresult", {}).get("idlist") if isinstance(search, dict) else None
    require_non_empty(idlist or [], source="pubmed", what="title search")

    summary_url = PUBMED_SUMMARY_URL.format(pmid=",".join(idlist))
    summary_response = transport.fetch(summary_url)
    check_status(summary_response, source="pubmed")
    summary = decode_json(summary_response, source="pubmed")
    result = summary.get("result", {})

    candidates: list[Candidate] = []
    for pmid in idlist:  # rank order, exactly as PubMed returned it
        doc = result.get(pmid)
        if not isinstance(doc, dict) or doc.get("error"):
            continue
        try:
            fields = summary_to_fields(pmid, doc)
        except ResponseError:
            continue
        candidates.append(
            Candidate(
                source="pubmed",
                kind="pmid",
                identifier=str(pmid),
                summary=fields,
            )
        )
    return candidates


def search_title(
    title: str,
    crossref: Optional[Transport] = None,
    pubmed: Optional[Transport] = None,
    rows: int = 5,
) -> CandidateList:
    """Query one or both sources for the exact title; return ranked candidates.

    At least one transport must be given. Candidates keep their source's
    rank order (Crossref items first, then PubMed). A query that matches
    nothing anywhere is refused (``empty_result``), never an empty list.
    """
    cleaned = " ".join(title.split())
    candidates: list[Candidate] = []
    if crossref is not None:
        candidates.extend(_crossref_candidates(cleaned, crossref, rows))
    if pubmed is not None:
        candidates.extend(_pubmed_candidates(cleaned, pubmed))
    if crossref is None and pubmed is None:
        raise ValueError("search_title requires at least one transport")
    require_non_empty(candidates, source="all requested sources", what="title search")
    return CandidateList(query_title=cleaned, candidates=tuple(candidates))


def select(
    candidate: Candidate,
    transport: Transport,
    reference_id: str,
    retrieved_at: str,
) -> Reference:
    """The explicit selection step: name a candidate, get a verified Reference.

    This re-resolves the candidate's identifier through ``transport`` — a
    fresh fetch of the identifier's own endpoint. The search payload is
    never trusted as the metadata source; if the resolution has not been
    recorded (or, in production, fails), selection fails loudly.
    """
    if candidate.kind == "doi":
        return resolve_doi(candidate.identifier, transport, reference_id, retrieved_at)
    if candidate.kind == "pmid":
        return resolve_pmid(candidate.identifier, transport, reference_id, retrieved_at)
    raise ValueError(f"unknown candidate kind: {candidate.kind!r}")
