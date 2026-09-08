"""T-09: the Crossref resolver — DOI to Reference over the transport seam.

The whole risk is one rule: absent metadata stays absent. A missing volume,
issue, or page is None — never inferred, never reconstructed, never an
empty string standing in for a real value. The archived response for
10.2147/prom.s8896 must map to the exact Reference hard-coded in spike.py:
that constant is an independent oracle for this resolver.
"""

from pathlib import Path

import json

import pytest

from citebind.crossref import resolve_doi
from citebind.model import Reference
from citebind.spike import BASELINE_REFERENCE
from citebind.transport import ReplayTransport, ResponseError

RECORDINGS = Path(__file__).parent.parent / "spike" / "recordings" / "MANIFEST.json"

ORACLE_DOI = "10.2147/prom.s8896"
ORACLE_RETRIEVED_AT = "2026-08-29T00:00:00Z"


def recordings() -> ReplayTransport:
    return ReplayTransport(RECORDINGS)


# --- the oracle: the spike constant is reproduced from the raw recording -------


def test_spike_record_maps_to_the_exact_baseline_reference():
    ref = resolve_doi(
        ORACLE_DOI,
        recordings(),
        reference_id="R001",
        retrieved_at=ORACLE_RETRIEVED_AT,
    )
    assert ref == Reference.from_dict(BASELINE_REFERENCE)


def test_two_recordings_days_apart_map_to_one_reference(tmp_path):
    # The oracle claim, made explicit: the raw response archived on
    # 2026-08-29 and the independent recording made on 2026-08-31 both map
    # to the same Reference (modulo retrieved_at). Two fetches, four days
    # apart, agreeing through the resolver is what makes the hard-coded
    # constant trustworthy rather than merely consistent.
    import json

    from citebind.transport import ReplayTransport as RT

    archive = Path(__file__).parent.parent / "spike" / "reference_source_crossref.json"
    url = "https://api.crossref.org/works/10.2147/prom.s8896"
    (tmp_path / "MANIFEST.json").write_text(
        json.dumps(
            {
                "recordings": [
                    {"url": url, "file": str(archive.resolve()), "status": 200}
                ]
            }
        )
    )
    old_ref = resolve_doi(
        url.split("/works/")[1], RT(tmp_path / "MANIFEST.json"), reference_id="R001",
        retrieved_at="2026-08-29T00:00:00Z",
    )
    fresh_ref = resolve_doi(
        ORACLE_DOI, recordings(), reference_id="R001",
        retrieved_at="2026-08-31T00:00:00Z",
    )
    strip = lambda ref: {k: v for k, v in ref.to_dict().items() if k != "retrieved_at"}
    assert strip(old_ref) == strip(fresh_ref)
    assert old_ref == Reference.from_dict(BASELINE_REFERENCE)
    assert fresh_ref == Reference.from_dict(
        {**BASELINE_REFERENCE, "retrieved_at": "2026-08-31T00:00:00Z"}
    )


def test_resolver_accepts_url_and_prefixed_spellings_via_canonical_form():
    # normalization happens before the URL is built, so every spelling of
    # the DOI resolves through the same recorded response
    for spelling in (
        "10.2147/prom.s8896",
        "https://doi.org/10.2147/prom.s8896",
        "DOI:10.2147/PROM.S8896",
    ):
        ref = resolve_doi(
            spelling, recordings(), reference_id="R001", retrieved_at=ORACLE_RETRIEVED_AT
        )
        assert ref.doi == "10.2147/prom.s8896"


def test_resolver_sets_provenance_fields():
    ref = resolve_doi(
        ORACLE_DOI, recordings(), reference_id="R007", retrieved_at="2026-12-01T12:00:00Z"
    )
    assert ref.metadata_source == "crossref"
    assert ref.retrieved_at == "2026-12-01T12:00:00Z"
    assert ref.id == "R007"


# --- absent metadata stays absent ------------------------------------------------


def test_incomplete_record_leaves_optional_fields_genuinely_unset():
    ref = resolve_doi(
        "10.1177/29768659261469390",
        recordings(),
        reference_id="R002",
        retrieved_at="2026-08-31T00:00:00Z",
    )
    # None, not "" and not a plausible reconstruction
    assert ref.volume is None
    assert ref.issue is None
    assert ref.pages is None
    assert ref.title == "Climate determinism reborn"
    assert ref.journal == "Dialogues on Climate Change"
    assert ref.year == 2026
    # the model must still validate as citebind/1
    ref.to_dict()


def test_many_author_record_maps_all_authors():
    ref = resolve_doi(
        "10.1103/physrevlett.116.061102",
        recordings(),
        reference_id="R003",
        retrieved_at="2026-08-31T00:00:00Z",
    )
    assert len(ref.authors) == 1012
    # names are mapped verbatim: Crossref's given name carries a thin space
    # (U+2009) in these initials, and the resolver does not "clean" real
    # data — given + " " + family, exactly as recorded
    assert ref.authors[0] == "B.\u2009P. Abbott"
    assert ref.volume == "116"
    assert ref.pages is None  # this record has no page range


# --- refusals: required metadata absent is loud, never blank ---------------------


def test_record_without_journal_is_refused_by_name():
    with pytest.raises(ResponseError) as e:
        resolve_doi(
            "10.22541/au.161220228.87275329/v1",
            recordings(),
            reference_id="R004",
            retrieved_at="2026-08-31T00:00:00Z",
        )
    assert e.value.code == "missing_required_field"
    assert "journal" in str(e.value)


def test_unrecorded_url_refused_by_name():
    from citebind.transport import CODE_URL_NOT_RECORDED, TransportError

    with pytest.raises(TransportError) as e:
        resolve_doi(
            "10.9999/not-recorded-anywhere",
            recordings(),
            reference_id="R005",
            retrieved_at="2026-08-31T00:00:00Z",
        )
    assert e.value.code == CODE_URL_NOT_RECORDED


class _Canned:
    """A transport that returns one body, for shapes no recording contains."""

    def __init__(self, body):
        self.body = body if isinstance(body, bytes) else json.dumps(body).encode()

    def fetch(self, url):
        from citebind.transport import TransportResponse

        return TransportResponse(status=200, body=self.body)


@pytest.mark.parametrize(
    "author",
    ["not a list", ["a plain string"], {"family": "Solo"}, 7],
    ids=["string", "list-of-strings", "bare-mapping", "number"],
)
def test_malformed_author_field_is_refused_by_name(author):
    """REGRESSION. Crossref is a live external API, and an error page, a shape
    change, or a proxy's rewritten body can put a string where the list of
    author objects belongs. Iterating a string yields characters, so
    ``author.get`` raised AttributeError from two frames down — an unnamed
    crash in a module whose entire design is refusing by name.
    """
    from citebind.crossref import ResponseShapeError

    body = {
        "message": {
            "title": ["T"],
            "container-title": ["J"],
            "author": author,
            "published": {"date-parts": [[2024]]},
        }
    }
    with pytest.raises(ResponseShapeError) as caught:
        resolve_doi("10.1000/x", _Canned(body), "R001", "2026-09-08T00:00:00Z")
    assert caught.value.code == "unexpected_shape"
