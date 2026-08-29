"""T-02: the citebind/1 schema and data model.

Acceptance: three well-formed documents validate; five distinct malformed
documents are each rejected with a *named* error code, not a generic one.
"""

import pytest

from citebind.model import CiteBindDocument, CitationCluster, Reference
from citebind.schema import (
    CLUSTER_ID_DUPLICATE,
    CLUSTER_REFERENCE_UNKNOWN,
    KEY_UNKNOWN_TOP_LEVEL,
    REFERENCE_ID_DUPLICATE,
    REFERENCE_IDENTIFIER_MISSING,
    SCHEMA_VERSION_MISSING,
    SchemaError,
    validate_document,
)


def wellformed_minimal_doi():
    return {
        "schema_version": "1",
        "selected_style": "numeric",
        "references": [
            {
                "id": "R001",
                "doi": "10.1000/fixture-1",
                "title": "A Fixture Paper",
                "authors": ["Alpha Author", "Beta Author"],
                "journal": "Journal of Fixtures",
                "year": 2024,
                "metadata_source": "crossref",
                "retrieved_at": "2026-08-29T00:00:00Z",
            }
        ],
        "citation_clusters": [
            {"id": "C001", "reference_ids": ["R001"]},
        ],
    }


def wellformed_minimal_pmid():
    return {
        "schema_version": "1",
        "selected_style": "author-year",
        "references": [
            {
                "id": "R001",
                "pmid": "12345678",
                "title": "Another Fixture",
                "authors": ["Gamma Author"],
                "journal": "Journal of Fixtures II",
                "year": 2023,
                "metadata_source": "pubmed",
                "retrieved_at": "2026-08-29T00:00:00Z",
            }
        ],
        "citation_clusters": [],
    }


def wellformed_full():
    return {
        "schema_version": "1",
        "selected_style": "numeric",
        "references": [
            {
                "id": "R001",
                "doi": "10.1000/fixture-1",
                "pmid": "87654321",
                "title": "Full Record",
                "authors": ["Alpha Author"],
                "journal": "Journal of Fixtures",
                "year": 2024,
                "volume": "12",
                "issue": "3",
                "pages": "100-110",
                "metadata_source": "crossref",
                "retrieved_at": "2026-08-29T00:00:00Z",
            },
            {
                "id": "R002",
                "doi": "10.1000/fixture-2",
                "title": "Second Record",
                "authors": ["Beta Author"],
                "journal": "Journal of Fixtures II",
                "year": 2022,
                "metadata_source": "crossref",
                "retrieved_at": "2026-08-29T00:00:00Z",
            },
        ],
        "citation_clusters": [
            {
                "id": "C001",
                "reference_ids": ["R001", "R002"],
                "locator": "p. 4",
                "prefix": "see",
                "suffix": "et seq.",
            },
            {"id": "C002", "reference_ids": ["R001"]},
        ],
    }


# --- acceptance: well-formed documents accepted -------------------------------


@pytest.mark.parametrize(
    "factory",
    [wellformed_minimal_doi, wellformed_minimal_pmid, wellformed_full],
    ids=["minimal-doi", "minimal-pmid", "full"],
)
def test_accepts_wellformed_document(factory):
    validate_document(factory())  # must not raise


def test_from_dict_builds_dataclasses():
    doc = CiteBindDocument.from_dict(wellformed_full())
    assert doc.schema_version == "1"
    assert doc.selected_style == "numeric"
    assert isinstance(doc.references[0], Reference)
    assert doc.references[0].doi == "10.1000/fixture-1"
    assert doc.references[0].volume == "12"
    assert isinstance(doc.citation_clusters[0], CitationCluster)
    assert doc.citation_clusters[0].reference_ids == ["R001", "R002"]
    assert doc.citation_clusters[0].locator == "p. 4"


def test_roundtrip_dict_equality():
    original = wellformed_full()
    doc = CiteBindDocument.from_dict(original)
    assert doc.to_dict() == original
    assert CiteBindDocument.from_dict(doc.to_dict()) == doc


def test_uncited_reference_is_valid_at_schema_layer():
    payload = wellformed_minimal_doi()
    payload["citation_clusters"] = []  # R001 cited nowhere: valid while drafting
    validate_document(payload)  # must not raise


def test_empty_reference_and_cluster_lists_are_valid():
    payload = {
        "schema_version": "1",
        "selected_style": "numeric",
        "references": [],
        "citation_clusters": [],
    }
    validate_document(payload)  # must not raise


# --- acceptance: five distinct named rejections -------------------------------


def expected_code(exc_info):
    assert isinstance(exc_info.value, SchemaError)
    return exc_info.value.code


def test_rejects_missing_schema_version():
    payload = wellformed_minimal_doi()
    del payload["schema_version"]
    with pytest.raises(SchemaError) as exc_info:
        validate_document(payload)
    assert expected_code(exc_info) == SCHEMA_VERSION_MISSING


def test_rejects_duplicate_reference_ids():
    payload = wellformed_minimal_doi()
    clone = dict(payload["references"][0])
    clone["doi"] = "10.1000/fixture-clone"
    payload["references"].append(clone)
    with pytest.raises(SchemaError) as exc_info:
        validate_document(payload)
    assert expected_code(exc_info) == REFERENCE_ID_DUPLICATE


def test_rejects_cluster_pointing_at_missing_reference():
    payload = wellformed_minimal_doi()
    payload["citation_clusters"][0]["reference_ids"] = ["R999"]
    with pytest.raises(SchemaError) as exc_info:
        validate_document(payload)
    assert expected_code(exc_info) == CLUSTER_REFERENCE_UNKNOWN


def test_rejects_reference_with_neither_doi_nor_pmid():
    payload = wellformed_minimal_doi()
    del payload["references"][0]["doi"]
    with pytest.raises(SchemaError) as exc_info:
        validate_document(payload)
    assert expected_code(exc_info) == REFERENCE_IDENTIFIER_MISSING


def test_rejects_unknown_top_level_key():
    payload = wellformed_minimal_doi()
    payload["provenance_digest"] = "deadbeef"
    with pytest.raises(SchemaError) as exc_info:
        validate_document(payload)
    assert expected_code(exc_info) == KEY_UNKNOWN_TOP_LEVEL


def test_rejects_duplicate_cluster_ids():
    payload = wellformed_full()
    clone = dict(payload["citation_clusters"][1])
    payload["citation_clusters"].append(clone)
    with pytest.raises(SchemaError) as exc_info:
        validate_document(payload)
    assert expected_code(exc_info) == CLUSTER_ID_DUPLICATE


# --- distinctness of the named errors -----------------------------------------


def test_the_five_named_rejection_codes_are_all_distinct():
    codes = {
        SCHEMA_VERSION_MISSING,
        REFERENCE_ID_DUPLICATE,
        CLUSTER_REFERENCE_UNKNOWN,
        REFERENCE_IDENTIFIER_MISSING,
        KEY_UNKNOWN_TOP_LEVEL,
    }
    assert len(codes) == 5
