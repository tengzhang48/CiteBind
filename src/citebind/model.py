"""Python dataclasses for the citebind/1 document contract.

``from_dict`` validates through :mod:`citebind.schema`, so a model instance is
by construction a valid citebind/1 payload.
"""

from dataclasses import dataclass, field
from typing import Any, Optional

from .schema import validate_document, validate_reference


@dataclass(frozen=True)
class AuthorName:
    """One author's name as the SOURCE gave it.

    Either a ``family``/``given`` split (Crossref supplies one) or a
    ``literal`` whole string (PubMed's "Belletti DA", and organizational
    authors, which have no split to give). CiteBind never converts one shape
    into the other: guessing where a given name ends and a family name begins
    is inventing metadata, and it is wrong for particles, compound surnames,
    and every name that does not put the family last.
    """

    family: Optional[str] = None
    given: Optional[str] = None
    literal: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        if self.literal is not None:
            return {"literal": self.literal}
        result: dict[str, Any] = {"family": self.family}
        if self.given is not None:
            result["given"] = self.given
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AuthorName":
        return cls(
            family=data.get("family"),
            given=data.get("given"),
            literal=data.get("literal"),
        )


@dataclass
class Reference:
    id: str
    title: str
    authors: list[str]
    journal: str
    year: int
    metadata_source: str
    retrieved_at: str
    doi: Optional[str] = None
    pmid: Optional[str] = None
    volume: Optional[str] = None
    issue: Optional[str] = None
    pages: Optional[str] = None
    # Present only when the metadata source supplied structured names.
    author_names: Optional[list[AuthorName]] = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.id,
            "title": self.title,
            "authors": list(self.authors),
            "journal": self.journal,
            "year": self.year,
            "metadata_source": self.metadata_source,
            "retrieved_at": self.retrieved_at,
        }
        # Optional keys are omitted, never emitted as null, so to_dict() output
        # is canonical: from_dict(to_dict(x)) == x and both validate identically.
        if self.doi is not None:
            result["doi"] = self.doi
        if self.pmid is not None:
            result["pmid"] = self.pmid
        if self.volume is not None:
            result["volume"] = self.volume
        if self.issue is not None:
            result["issue"] = self.issue
        if self.pages is not None:
            result["pages"] = self.pages
        if self.author_names is not None:
            result["author_names"] = [n.to_dict() for n in self.author_names]
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Reference":
        # Validate here, not only in CiteBindDocument.from_dict: this is the
        # constructor both resolvers use, so it is the boundary a malformed
        # API response actually crosses.
        validate_reference(data)
        return cls(
            id=data["id"],
            doi=data.get("doi"),
            pmid=data.get("pmid"),
            title=data["title"],
            authors=list(data["authors"]),
            journal=data["journal"],
            year=data["year"],
            volume=data.get("volume"),
            issue=data.get("issue"),
            pages=data.get("pages"),
            metadata_source=data["metadata_source"],
            retrieved_at=data["retrieved_at"],
            author_names=(
                [AuthorName.from_dict(n) for n in data["author_names"]]
                if data.get("author_names") is not None
                else None
            ),
        )


@dataclass
class CitationCluster:
    id: str
    reference_ids: list[str]
    locator: Optional[str] = None
    prefix: Optional[str] = None
    suffix: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.id,
            "reference_ids": list(self.reference_ids),
        }
        if self.locator is not None:
            result["locator"] = self.locator
        if self.prefix is not None:
            result["prefix"] = self.prefix
        if self.suffix is not None:
            result["suffix"] = self.suffix
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CitationCluster":
        return cls(
            id=data["id"],
            reference_ids=list(data["reference_ids"]),
            locator=data.get("locator"),
            prefix=data.get("prefix"),
            suffix=data.get("suffix"),
        )


@dataclass
class CiteBindDocument:
    schema_version: str
    selected_style: str
    references: list[Reference] = field(default_factory=list)
    citation_clusters: list[CitationCluster] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "selected_style": self.selected_style,
            "references": [r.to_dict() for r in self.references],
            "citation_clusters": [c.to_dict() for c in self.citation_clusters],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CiteBindDocument":
        validate_document(data)
        return cls(
            schema_version=data["schema_version"],
            selected_style=data["selected_style"],
            references=[Reference.from_dict(r) for r in data["references"]],
            citation_clusters=[CitationCluster.from_dict(c) for c in data["citation_clusters"]],
        )
