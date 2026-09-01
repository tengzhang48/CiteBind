"""Comparison of two sources answering for the same work.

One rule: **nothing here chooses.** When Crossref and PubMed disagree,
the comparison reports what each source said, per field, and marks the
disagreement. It never resolves by preference, averaging, string length,
or case-folding — agreement is exact equality, so formatting differences
surface as conflicts for a human to judge. There is deliberately no way
to obtain a merged Reference from this module: the merge surface does not
exist (asserted by test).

Identifier fields (doi, pmid, id) are the join keys, not claims: each
source is naturally silent about the other's identifier, and counting
that silence as disagreement would be noise.
"""

from dataclasses import dataclass

from .model import Reference

METADATA_FIELDS = ("title", "authors", "journal", "year", "volume", "issue", "pages")


class ComparisonError(Exception):
    """A comparison was requested that cannot be made, with a named reason."""

    def __init__(self, code: str, message: str):
        super().__init__(f"[{code}] {message}")
        self.code = code


@dataclass(frozen=True)
class FieldComparison:
    """One metadata field, with each source's claim (sources silent about a
    field are absent from ``claims``)."""

    field: str
    claims: dict[str, object]

    @property
    def agrees(self) -> bool:
        values = {repr(value) for value in self.claims.values()}
        return len(values) <= 1


@dataclass(frozen=True)
class Comparison:
    subject: str  # the work being compared, described by its identifiers
    fields: list[FieldComparison]

    @property
    def conflicts(self) -> list[FieldComparison]:
        return [fc for fc in self.fields if len(fc.claims) > 1 and not fc.agrees]


def compare(reference_a: Reference, reference_b: Reference) -> Comparison:
    """Compare two resolvers' answers for the same work, per field.

    Raises ComparisonError("same_source") when both references claim the
    same metadata_source: comparing a source with itself is not a
    cross-check and would silently collapse one source's claims over the
    other's.
    """
    source_a, source_b = reference_a.metadata_source, reference_b.metadata_source
    if source_a == source_b:
        raise ComparisonError(
            "same_source",
            f"both references claim metadata_source '{source_a}'; "
            "comparing a source with itself is not a cross-check",
        )

    fields: list[FieldComparison] = []
    for field_name in METADATA_FIELDS:
        claims: dict[str, object] = {}
        for source, reference in ((source_a, reference_a), (source_b, reference_b)):
            value = getattr(reference, field_name)
            if value is not None:  # None is silence, not a claim
                claims[source] = value
        fields.append(FieldComparison(field=field_name, claims=claims))

    identifiers = f"{source_a}={_subject_label(reference_a)}, {source_b}={_subject_label(reference_b)}"
    return Comparison(subject=identifiers, fields=fields)


def _subject_label(reference: Reference) -> str:
    return reference.doi or reference.pmid or reference.id


def render_comparison(comparison: Comparison) -> str:
    """A human-readable per-field report; both values shown on conflict."""
    lines = [f"comparison for: {comparison.subject}"]
    for fc in comparison.fields:
        if not fc.claims:
            lines.append(f"  {fc.field}: (no source stated a value)")
        elif fc.agrees:
            value = next(iter(fc.claims.values()))
            sources = ", ".join(sorted(fc.claims))
            lines.append(f"  {fc.field}: agrees — {sources}: {value!r}")
        else:
            parts = ", ".join(
                f"{source}: {value!r}" for source, value in sorted(fc.claims.items())
            )
            lines.append(f"  {fc.field}: CONFLICT — {parts}")
    return "\n".join(lines)
