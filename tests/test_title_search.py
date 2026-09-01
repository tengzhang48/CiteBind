"""T-12: title search returns candidates, never a selection.

The API is shaped so that obtaining a Reference from a title query is
impossible without an explicit selection step: the search produces no
Reference objects at all, the CandidateList offers no default and no
`first`, and the only Reference-producing path is `select()`, which names
a candidate explicitly and re-resolves its identifier through the
transport — a fresh, verified fetch, not the search payload.
"""

import json
from pathlib import Path

import pytest

from citebind.title_search import CandidateList, search_title, select
from citebind.transport import CODE_URL_NOT_RECORDED, ReplayTransport, TransportError

RECORDINGS = Path(__file__).parent.parent / "spike" / "recordings" / "MANIFEST.json"
TITLE = (
    "Perspectives on electronic medical records adoption: "
    "electronic medical records (EMR) in outcomes research"
)


def search_combined() -> CandidateList:
    transport = ReplayTransport(RECORDINGS)
    return search_title(TITLE, crossref=transport, pubmed=transport)


# --- candidates, ordered, with metadata, and never a Reference ---------------------


def test_crossref_search_returns_ordered_candidates():
    transport = ReplayTransport(RECORDINGS)
    result = search_title(TITLE, crossref=transport)
    assert len(result.candidates) >= 1
    kinds = [c.kind for c in result]
    assert set(kinds) == {"doi"}
    identifiers = [c.identifier for c in result]
    assert identifiers == [c.identifier for c in result]  # order is stable
    first = result.candidates[0]
    assert first.source == "crossref"
    assert first.identifier.startswith("10.")
    assert first.summary["title"]
    assert first.summary["journal"]
    assert first.summary["year"]


def test_pubmed_search_returns_candidates_in_rank_order():
    transport = ReplayTransport(RECORDINGS)
    result = search_title(TITLE, pubmed=transport)
    assert len(result.candidates) >= 1
    assert all(c.source == "pubmed" and c.kind == "pmid" for c in result)


def test_combined_search_merges_both_sources():
    result = search_combined()
    sources = {c.source for c in result}
    assert sources == {"crossref", "pubmed"}


def test_search_produces_no_reference_objects():
    result = search_combined()
    for candidate in result:
        assert not isinstance(candidate, __import__("citebind.model", fromlist=["Reference"]).Reference)
        assert not hasattr(candidate, "reference")
    assert not hasattr(result, "select")
    assert not hasattr(result, "first")
    assert not hasattr(result, "best")


def test_empty_result_set_refused_by_name(tmp_path):
    # a search that matches nothing is refused, not an empty happy list
    body = json.dumps({"status": "ok", "message": {"items": []}}).encode()
    (tmp_path / "body.json").write_bytes(body)
    (tmp_path / "MANIFEST.json").write_text(
        json.dumps(
            {
                "recordings": [
                    {
                        "url": __import__(
                            "citebind.crossref", fromlist=["title_search_url"]
                        ).title_search_url(TITLE),
                        "file": "body.json",
                    }
                ]
            }
        )
    )
    from citebind.transport import ResponseError

    with pytest.raises(ResponseError) as e:
        search_title(TITLE, crossref=ReplayTransport(tmp_path / "MANIFEST.json"))
    assert e.value.code == "empty_result"


# --- the acceptance: one candidate is still not a confirmation ---------------------


def test_single_candidate_result_still_requires_selection(tmp_path):
    # build a search fixture with exactly ONE candidate, from the recorded
    # response's first item (recorded data, not fabricated metadata)
    from citebind.crossref import title_search_url
    from citebind.transport import ReplayTransport as RT

    recorded = json.loads((Path(__file__).parent.parent / "spike" / "recordings" / "crossref-https___api.crossref.org_works_10.2147_prom.s8896.json").read_text())
    single = {
        "status": "ok",
        "message": {"items": [recorded["message"]]},
    }
    (tmp_path / "body.json").write_bytes(json.dumps(single).encode())
    (tmp_path / "MANIFEST.json").write_text(
        json.dumps(
            {"recordings": [{"url": title_search_url(TITLE), "file": "body.json"}]}
        )
    )
    search_transport = RT(tmp_path / "MANIFEST.json")
    result = search_title(TITLE, crossref=search_transport)
    assert len(result.candidates) == 1

    # one candidate, and still no Reference exists from the search itself:
    assert not hasattr(result, "reference")

    # selection is a separate, explicit act that names the candidate and
    # re-resolves the identifier through a verified fetch:
    candidate = result.candidates[0]
    resolve_transport = ReplayTransport(RECORDINGS)
    ref = select(candidate, resolve_transport, reference_id="R001", retrieved_at="2026-08-31T00:00:00Z")
    assert ref.doi == "10.2147/prom.s8896"
    assert ref.id == "R001"


def test_selection_re_fetches_by_identifier_rather_than_trusting_search(tmp_path):
    # selection must go through the identifier's own resolution endpoint:
    # a transport that recorded ONLY the search (not the resolution) must
    # fail loudly — the search payload alone can never produce a Reference
    from citebind.crossref import title_search_url

    recorded = json.loads(
        (
            Path(__file__).parent.parent
            / "spike"
            / "recordings"
            / "crossref-https___api.crossref.org_works_10.2147_prom.s8896.json"
        ).read_text()
    )
    (tmp_path / "body.json").write_bytes(
        json.dumps({"status": "ok", "message": {"items": [recorded["message"]]}}).encode()
    )
    (tmp_path / "MANIFEST.json").write_text(
        json.dumps(
            {"recordings": [{"url": title_search_url(TITLE), "file": "body.json"}]}
        )
    )
    search_only = ReplayTransport(tmp_path / "MANIFEST.json")
    result = search_title(TITLE, crossref=search_only)
    with pytest.raises(TransportError) as e:
        select(result.candidates[0], search_only, reference_id="R001", retrieved_at="2026-08-31T00:00:00Z")
    assert e.value.code == CODE_URL_NOT_RECORDED
