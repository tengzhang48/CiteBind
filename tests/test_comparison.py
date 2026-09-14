"""T-11: two sources, one truth, no silent merge.

When both sources answer for the same work, compare() returns a structured
per-field comparison: what each source said, and whether they agree.
Agreement is EXACT equality — formatting differences (case, trailing
punctuation) surface as conflicts for a human, because deciding they are
"the same" would be a precedence rule, and nothing in this module decides.

The real recorded pair already disagrees: Crossref says pages "29",
authors [Daniel A Belletti], journal "Patient Related Outcome Measures",
title without a final period; PubMed says "29-37", three authors,
"Patient related outcome measures", title with a final period. Year
agrees at 2010. These fixtures are the acceptance.
"""

from pathlib import Path

import pytest

from citebind.crossref import resolve_doi
from citebind.model import Reference
from citebind.pubmed import resolve_pmid
from citebind.comparison import ComparisonError, compare, render_comparison
from citebind.transport import ReplayTransport

RECORDINGS = Path(__file__).parent.parent / "spike" / "recordings" / "MANIFEST.json"


def recorded_pair() -> tuple[Reference, Reference]:
    transport = ReplayTransport(RECORDINGS)
    crossref_ref = resolve_doi(
        "10.2147/prom.s8896", transport, reference_id="R001", retrieved_at="2026-08-31T00:00:00Z"
    )
    pubmed_ref = resolve_pmid(
        "22915950", transport, reference_id="R001", retrieved_at="2026-08-31T00:00:00Z"
    )
    return crossref_ref, pubmed_ref


def by_field(comparison, field):
    return next(fc for fc in comparison.fields if fc.field == field)


# --- the real recorded pair --------------------------------------------------------


def test_real_pair_conflicts_are_reported_per_field_with_both_values():
    crossref_ref, pubmed_ref = recorded_pair()
    comparison = compare(crossref_ref, pubmed_ref)

    pages = by_field(comparison, "pages")
    assert pages.agrees is False
    assert pages.claims == {
        "crossref": "29",
        "pubmed": "29-37",
    }
    authors = by_field(comparison, "authors")
    assert authors.agrees is False
    assert authors.claims["crossref"] == ["Daniel A Belletti"]
    assert authors.claims["pubmed"] == ["Belletti D", "Zacker C", "Mullins CD"]
    # title: the trailing period is a reported conflict, not silently folded
    title = by_field(comparison, "title")
    assert title.agrees is False
    assert title.claims["pubmed"].endswith(".")


def test_real_pair_agreements_are_reported_too():
    crossref_ref, pubmed_ref = recorded_pair()
    comparison = compare(crossref_ref, pubmed_ref)
    year = by_field(comparison, "year")
    assert year.agrees is True
    assert year.claims == {"crossref": 2010, "pubmed": 2010}
    assert by_field(comparison, "pages") in comparison.conflicts
    assert by_field(comparison, "year") not in comparison.conflicts


def test_one_sided_fields_are_shown_without_being_conflicts():
    # Crossref did not state a volume for this work; PubMed did. Silence is
    # not disagreement: one claim, no conflict, shown so the human sees it.
    crossref_ref, pubmed_ref = recorded_pair()
    comparison = compare(crossref_ref, pubmed_ref)
    volume = by_field(comparison, "volume")
    assert volume.claims == {"pubmed": "1"}
    assert volume.agrees is True
    assert volume not in comparison.conflicts


def test_both_silent_fields_report_no_claims():
    crossref_ref, pubmed_ref = recorded_pair()
    comparison = compare(crossref_ref, pubmed_ref)
    issue = by_field(comparison, "issue")
    assert issue.claims == {}
    assert issue.agrees is True


# --- a synthetic year disagreement (the acceptance's second field) -----------------


def test_year_disagreement_names_both_values_and_both_sources():
    crossref_ref, pubmed_ref = recorded_pair()
    # move the PubMed record's year to force a year conflict: a synthetic
    # edit of a TEST to exercise the comparison logic — no fabricated value
    # enters any product fixture
    pubmed_shifted = Reference.from_dict(
        {**pubmed_ref.to_dict(), "year": 2011}
    )
    comparison = compare(crossref_ref, pubmed_shifted)
    year = by_field(comparison, "year")
    assert year.agrees is False
    assert year.claims == {"crossref": 2010, "pubmed": 2011}
    assert year in comparison.conflicts


# --- nothing chooses ---------------------------------------------------------------


def test_comparison_cannot_produce_a_merged_reference():
    crossref_ref, pubmed_ref = recorded_pair()
    comparison = compare(crossref_ref, pubmed_ref)
    # structurally impossible: there is no merge surface to call
    assert not hasattr(comparison, "to_reference")
    assert not hasattr(comparison, "merged")
    assert not hasattr(comparison, "resolve")
    import citebind.comparison as module

    for attr in dir(module):
        if attr.startswith("merge") or attr.startswith("to_reference"):
            pytest.fail(f"comparison module grew a choosing function: {attr}")


def test_comparing_a_source_with_itself_is_refused_by_name():
    crossref_ref, _ = recorded_pair()
    twin = Reference.from_dict({**crossref_ref.to_dict()})
    with pytest.raises(ComparisonError) as e:
        compare(crossref_ref, twin)
    assert e.value.code == "same_source"


def test_render_shows_both_values_per_conflict():
    crossref_ref, pubmed_ref = recorded_pair()
    text = render_comparison(compare(crossref_ref, pubmed_ref))
    assert "29" in text and "29-37" in text
    assert "crossref" in text and "pubmed" in text
