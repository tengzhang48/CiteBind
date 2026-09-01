"""T-10: the PubMed resolver — PMID to Reference over the transport seam.

Same shape and same absence rule as the Crossref resolver: a missing or
empty-string field is absence, never a blank stand-in. PubMed's esummary
reports issue as "" when there is none; the Reference must carry None.

Mapping decisions (stated, not silent):
- journal prefers ``fulljournalname`` (the full name, consistent with what
  Crossref gives), falling back to ``source`` (the ISO abbreviation);
- ``issue: ""`` is absence;
- authors are the ``name`` strings, verbatim;
- year comes from ``pubdate``'s leading year.
"""

import json
from pathlib import Path

import pytest

from citebind.pubmed import resolve_pmid
from citebind.transport import (
    CODE_MALFORMED_JSON,
    ReplayTransport,
    ResponseError,
    TransportError,
)

RECORDINGS = Path(__file__).parent.parent / "spike" / "recordings" / "MANIFEST.json"

SPIKE_PMID = "22915950"


def recordings() -> ReplayTransport:
    return ReplayTransport(RECORDINGS)


def manifest_with(tmp_path, url, body, status=200):
    (tmp_path / "body.json").write_bytes(body)
    (tmp_path / "MANIFEST.json").write_text(
        json.dumps({"recordings": [{"url": url, "file": "body.json", "status": status}]})
    )
    return ReplayTransport(tmp_path / "MANIFEST.json")


ESUMMARY_URL = (
    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
    f"?db=pubmed&retmode=json&id={SPIKE_PMID}"
)


def test_spike_pmid_resolves_from_the_recording():
    ref = resolve_pmid(
        SPIKE_PMID, recordings(), reference_id="R001", retrieved_at="2026-08-31T00:00:00Z"
    )
    assert ref.id == "R001"
    assert ref.pmid == "22915950"
    assert ref.metadata_source == "pubmed"
    assert ref.retrieved_at == "2026-08-31T00:00:00Z"
    # the title is verbatim, including PubMed's sentence-final period
    assert ref.title == (
        "Perspectives on electronic medical records adoption: "
        "electronic medical records (EMR) in outcomes research."
    )
    assert ref.authors == ["Belletti D", "Zacker C", "Mullins CD"]
    assert ref.year == 2010


def test_journal_prefers_full_name_and_falls_back():
    ref = resolve_pmid(
        SPIKE_PMID, recordings(), reference_id="R001", retrieved_at="2026-08-31T00:00:00Z"
    )
    assert ref.journal == "Patient related outcome measures"


def test_empty_string_fields_are_absence_not_value():
    ref = resolve_pmid(
        SPIKE_PMID, recordings(), reference_id="R001", retrieved_at="2026-08-31T00:00:00Z"
    )
    # PubMed reports issue as ""; the Reference must carry None
    assert ref.issue is None
    # real values stay real
    assert ref.volume == "1"
    assert ref.pages == "29-37"


def test_pmid_normalization_applies_before_the_url_is_built():
    ref = resolve_pmid(
        "PMID: 22915950",
        recordings(),
        reference_id="R001",
        retrieved_at="2026-08-31T00:00:00Z",
    )
    assert ref.pmid == "22915950"


def test_pmcid_refused_by_name_not_fetched():
    from citebind.identifiers import CODE_PMCID_NOT_PMID, IdentifierError

    with pytest.raises(IdentifierError) as e:
        resolve_pmid(
            "PMC3417895", recordings(), reference_id="R002", retrieved_at="2026-08-31T00:00:00Z"
        )
    assert e.value.code == CODE_PMCID_NOT_PMID


# --- refusals ---------------------------------------------------------------------


def test_http_error_status_refused():
    transport = manifest_with(_tmp(), ESUMMARY_URL, b"server exploded", status=500)
    with pytest.raises(ResponseError) as e:
        resolve_pmid(
            SPIKE_PMID, transport, reference_id="R003", retrieved_at="2026-08-31T00:00:00Z"
        )
    assert e.value.code == "http_error"


def test_malformed_json_refused():
    transport = manifest_with(_tmp(), ESUMMARY_URL, b"{not json")
    with pytest.raises(ResponseError) as e:
        resolve_pmid(
            SPIKE_PMID, transport, reference_id="R003", retrieved_at="2026-08-31T00:00:00Z"
        )
    assert e.value.code == CODE_MALFORMED_JSON


def test_unknown_pmid_refused_by_name():
    body = json.dumps(
        {
            "header": {"type": "esummary", "version": "0.3"},
            "result": {"uids": [], "22915950": {"error": "cannot get document summary"}},
        }
    ).encode()
    transport = manifest_with(_tmp(), ESUMMARY_URL, body)
    with pytest.raises(ResponseError) as e:
        resolve_pmid(
            SPIKE_PMID, transport, reference_id="R003", retrieved_at="2026-08-31T00:00:00Z"
        )
    assert e.value.code == "record_not_found"


def test_unrecorded_url_refused_by_name():
    with pytest.raises(TransportError) as e:
        resolve_pmid(
            "99999999", recordings(), reference_id="R004", retrieved_at="2026-08-31T00:00:00Z"
        )
    assert e.value.code == "url_not_recorded"


def _tmp():
    import tempfile

    return Path(tempfile.mkdtemp())
