"""Validation of the citebind/1 document contract.

The validator is fail-closed and names every rejection with a stable code.
Forward compatibility is explicit: an unknown key is an error, never a silent
ignore (product plan §4: "forward-compat must be explicit, not silent").
"""

SCHEMA_VERSION = "1"

SCHEMA_VERSION_MISSING = "schema_version_missing"
SCHEMA_VERSION_UNSUPPORTED = "schema_version_unsupported"
KEY_UNKNOWN_TOP_LEVEL = "key_unknown_top_level"
KEY_UNKNOWN_REFERENCE = "key_unknown_reference"
KEY_UNKNOWN_CLUSTER = "key_unknown_cluster"
REFERENCE_ID_DUPLICATE = "reference_id_duplicate"
REFERENCE_ID_MISSING = "reference_id_missing"
REFERENCE_IDENTIFIER_MISSING = "reference_identifier_missing"
CLUSTER_ID_DUPLICATE = "cluster_id_duplicate"
CLUSTER_ID_MISSING = "cluster_id_missing"
CLUSTER_REFERENCE_UNKNOWN = "cluster_reference_unknown"
CLUSTER_EMPTY = "cluster_empty"
FIELD_INVALID = "field_invalid"

DOCUMENT_KEYS = {"schema_version", "selected_style", "references", "citation_clusters"}
REFERENCE_REQUIRED_KEYS = {
    "id",
    "title",
    "authors",
    "journal",
    "year",
    "metadata_source",
    "retrieved_at",
}
REFERENCE_OPTIONAL_KEYS = {"doi", "pmid", "volume", "issue", "pages"}
CLUSTER_REQUIRED_KEYS = {"id", "reference_ids"}
CLUSTER_OPTIONAL_KEYS = {"locator", "prefix", "suffix"}


class SchemaError(Exception):
    """A citebind/1 payload violates the contract.

    ``code`` names the violation; distinct violations have distinct codes.
    """

    def __init__(self, code: str, message: str):
        super().__init__(f"[{code}] {message}")
        self.code = code


def _require_nonempty_str(container: dict, key: str, code: str, where: str) -> str:
    value = container.get(key)
    if not isinstance(value, str) or not value:
        raise SchemaError(code, f"{where}: '{key}' must be a non-empty string")
    return value


def validate_document(document: dict) -> None:
    """Validate a citebind/1 payload dict; raise SchemaError on any violation."""
    if not isinstance(document, dict):
        raise SchemaError(FIELD_INVALID, "document must be a mapping")

    unknown = set(document) - DOCUMENT_KEYS
    if unknown:
        names = ", ".join(sorted(unknown))
        raise SchemaError(
            KEY_UNKNOWN_TOP_LEVEL,
            f"unknown top-level key(s): {names}; forward compatibility is explicit",
        )

    if "schema_version" not in document:
        raise SchemaError(SCHEMA_VERSION_MISSING, "document has no 'schema_version'")
    if document["schema_version"] != SCHEMA_VERSION:
        raise SchemaError(
            SCHEMA_VERSION_UNSUPPORTED,
            f"expected schema_version '{SCHEMA_VERSION}', "
            f"got {document['schema_version']!r}",
        )

    _require_nonempty_str(
        document, "selected_style", FIELD_INVALID, "document"
    )

    references = document.get("references")
    if not isinstance(references, list):
        raise SchemaError(FIELD_INVALID, "'references' must be a list")

    seen_reference_ids: set[str] = set()
    for reference in references:
        _validate_reference(reference, seen_reference_ids)

    clusters = document.get("citation_clusters")
    if not isinstance(clusters, list):
        raise SchemaError(FIELD_INVALID, "'citation_clusters' must be a list")

    seen_cluster_ids: set[str] = set()
    for cluster in clusters:
        _validate_cluster(cluster, seen_cluster_ids, seen_reference_ids)


def _validate_reference(reference: dict, seen_ids: set[str]) -> None:
    if not isinstance(reference, dict):
        raise SchemaError(FIELD_INVALID, "each reference must be a mapping")

    allowed = REFERENCE_REQUIRED_KEYS | REFERENCE_OPTIONAL_KEYS
    unknown = set(reference) - allowed
    if unknown:
        names = ", ".join(sorted(unknown))
        raise SchemaError(KEY_UNKNOWN_REFERENCE, f"unknown reference key(s): {names}")

    where = "reference"
    ref_id = _require_nonempty_str(reference, "id", REFERENCE_ID_MISSING, where)
    if ref_id in seen_ids:
        raise SchemaError(
            REFERENCE_ID_DUPLICATE, f"two references share id '{ref_id}'"
        )
    seen_ids.add(ref_id)

    for key in REFERENCE_REQUIRED_KEYS - {"id", "authors", "year"}:
        _require_nonempty_str(reference, key, FIELD_INVALID, f"reference '{ref_id}'")

    if not isinstance(reference["authors"], list) or not all(
        isinstance(a, str) and a for a in reference["authors"]
    ):
        raise SchemaError(
            FIELD_INVALID, f"reference '{ref_id}': 'authors' must be a list of non-empty strings"
        )

    year = reference["year"]
    if isinstance(year, bool) or not isinstance(year, int):
        raise SchemaError(FIELD_INVALID, f"reference '{ref_id}': 'year' must be an integer")

    has_doi = isinstance(reference.get("doi"), str) and bool(reference["doi"].strip())
    has_pmid = isinstance(reference.get("pmid"), str) and bool(reference["pmid"].strip())
    if not has_doi and not has_pmid:
        raise SchemaError(
            REFERENCE_IDENTIFIER_MISSING,
            f"reference '{ref_id}' has neither DOI nor PMID",
        )

    for key in REFERENCE_OPTIONAL_KEYS - {"doi", "pmid"}:
        value = reference.get(key)
        if value is not None and (not isinstance(value, str) or not value):
            raise SchemaError(
                FIELD_INVALID, f"reference '{ref_id}': '{key}' must be a non-empty string"
            )


def _validate_cluster(cluster: dict, seen_ids: set[str], reference_ids: set[str]) -> None:
    if not isinstance(cluster, dict):
        raise SchemaError(FIELD_INVALID, "each citation cluster must be a mapping")

    allowed = CLUSTER_REQUIRED_KEYS | CLUSTER_OPTIONAL_KEYS
    unknown = set(cluster) - allowed
    if unknown:
        names = ", ".join(sorted(unknown))
        raise SchemaError(KEY_UNKNOWN_CLUSTER, f"unknown cluster key(s): {names}")

    cluster_id = _require_nonempty_str(cluster, "id", CLUSTER_ID_MISSING, "cluster")
    if cluster_id in seen_ids:
        raise SchemaError(CLUSTER_ID_DUPLICATE, f"two clusters share id '{cluster_id}'")
    seen_ids.add(cluster_id)

    ref_list = cluster.get("reference_ids")
    if not isinstance(ref_list, list) or not ref_list:
        raise SchemaError(CLUSTER_EMPTY, f"cluster '{cluster_id}' cites no references")
    for ref_id in ref_list:
        if ref_id not in reference_ids:
            raise SchemaError(
                CLUSTER_REFERENCE_UNKNOWN,
                f"cluster '{cluster_id}' references unknown reference id '{ref_id}'",
            )

    for key in CLUSTER_OPTIONAL_KEYS:
        value = cluster.get(key)
        if value is not None and (not isinstance(value, str) or not value):
            raise SchemaError(
                FIELD_INVALID, f"cluster '{cluster_id}': '{key}' must be a non-empty string"
            )
