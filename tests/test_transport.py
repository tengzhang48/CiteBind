"""T-08: the transport seam.

One transport interface, two implementations: HTTP for the world, replay
from recorded raw responses for every test. No network anywhere in the
suite — the seam is the enforcement, not a socket mock. Malformed JSON, an
HTTP error status, a timeout, and an empty result set each refuse with
their own named code.
"""

import json
import socket
import urllib.error

import pytest

from citebind.transport import (
    CODE_CONNECTION_ERROR,
    CODE_EMPTY_RESULT,
    CODE_HTTP_ERROR,
    CODE_MALFORMED_JSON,
    CODE_TIMEOUT,
    CODE_URL_NOT_RECORDED,
    ReplayTransport,
    ResponseError,
    TransportError,
    TransportResponse,
    check_status,
    classify_urlopen_error,
    decode_json,
    require_non_empty,
)


def write_manifest(tmp_path, recordings):
    (tmp_path / "MANIFEST.json").write_text(json.dumps({"recordings": recordings}))
    return tmp_path / "MANIFEST.json"


# --- replay transport ------------------------------------------------------------


def test_replay_returns_recorded_body(tmp_path):
    manifest = write_manifest(
        tmp_path,
        [{"url": "https://api.crossref.org/works/10.1/x", "file": "one.json"}],
    )
    (tmp_path / "one.json").write_bytes(b'{"status": "ok"}')
    response = ReplayTransport(manifest).fetch("https://api.crossref.org/works/10.1/x")
    assert response.status == 200
    assert response.body == b'{"status": "ok"}'


def test_replay_preserves_recorded_error_status(tmp_path):
    manifest = write_manifest(
        tmp_path, [{"url": "https://api.crossref.org/works/9.9/none", "file": "e.json", "status": 404}]
    )
    (tmp_path / "e.json").write_bytes(b'{"status": "error"}')
    response = ReplayTransport(manifest).fetch("https://api.crossref.org/works/9.9/none")
    assert response.status == 404


def test_replay_unknown_url_refused_by_name(tmp_path):
    manifest = write_manifest(tmp_path, [])
    with pytest.raises(TransportError) as e:
        ReplayTransport(manifest).fetch("https://api.crossref.org/works/9.9/none")
    assert e.value.code == CODE_URL_NOT_RECORDED


def test_replay_malformed_manifest_refused_by_name(tmp_path):
    # a corrupt manifest is test-infrastructure damage, distinct from a
    # malformed source response
    (tmp_path / "MANIFEST.json").write_text("{not json")
    with pytest.raises(TransportError) as e:
        ReplayTransport(tmp_path / "MANIFEST.json")
    assert e.value.code == "malformed_manifest"


# --- response-level named errors --------------------------------------------------


def test_http_error_status_refused_by_name():
    with pytest.raises(ResponseError) as e:
        check_status(TransportResponse(404, b"{}"), source="crossref")
    assert e.value.code == CODE_HTTP_ERROR
    assert "404" in str(e.value)


def test_http_error_covers_5xx_too():
    with pytest.raises(ResponseError) as e:
        check_status(TransportResponse(503, b""), source="crossref")
    assert e.value.code == CODE_HTTP_ERROR


def test_ok_status_passes():
    check_status(TransportResponse(200, b"{}"), source="crossref")


def test_malformed_json_refused_by_name():
    with pytest.raises(ResponseError) as e:
        decode_json(TransportResponse(200, b"{not json"), source="crossref")
    assert e.value.code == CODE_MALFORMED_JSON


def test_valid_json_decodes():
    assert decode_json(TransportResponse(200, b'{"a": 1}'), source="crossref") == {"a": 1}


def test_empty_result_set_refused_by_name():
    with pytest.raises(ResponseError) as e:
        require_non_empty([], source="crossref", what="title search")
    assert e.value.code == CODE_EMPTY_RESULT


def test_non_empty_result_passes():
    require_non_empty([{"x": 1}], source="crossref", what="title search")


# --- timeout: named, classified without any network --------------------------------


def test_timeout_classified_by_name():
    error = classify_urlopen_error(socket.timeout("timed out"))
    assert isinstance(error, TransportError)
    assert error.code == CODE_TIMEOUT


def test_urllib_timeout_reason_classified_as_timeout():
    error = classify_urlopen_error(urllib.error.URLError(reason=socket.timeout("timed out")))
    assert error.code == CODE_TIMEOUT


def test_connection_refused_classified_by_name():
    error = classify_urlopen_error(
        urllib.error.URLError(reason=ConnectionRefusedError(111, "Connection refused"))
    )
    assert error.code == CODE_CONNECTION_ERROR


# --- the six codes are all distinct -------------------------------------------------


def test_all_transport_and_response_codes_are_distinct():
    codes = {
        CODE_TIMEOUT,
        CODE_CONNECTION_ERROR,
        CODE_URL_NOT_RECORDED,
        CODE_HTTP_ERROR,
        CODE_MALFORMED_JSON,
        CODE_EMPTY_RESULT,
    }
    assert len(codes) == 6


def test_recorder_uses_the_production_transport_not_a_second_one():
    # N1 pin: the recorder once carried its own urllib fetch with a
    # different User-Agent, so fixtures were recorded over a path
    # production never executes. It must go through HttpTransport.
    import re
    from pathlib import Path

    source = (
        Path(__file__).parent.parent / "spike" / "record_fixtures.py"
    ).read_text()
    assert "urllib.request" not in source, (
        "the recorder grew its own HTTP implementation again"
    )
    assert "HttpTransport" in source
    # one User-Agent, defined once, used by the transport the recorder takes.
    # Counted where it is DEFINED and where it is SENT, not where the words
    # appear: this assertion used to count every occurrence of the text, so
    # a docstring explaining the header read as a second User-Agent. Prose
    # about a header is a mention; these two lines are the header.
    transport_source = (
        Path(__file__).parent.parent / "src" / "citebind" / "transport.py"
    ).read_text()
    assert len(re.findall(r"(?m)^USER_AGENT = ", transport_source)) == 1
    assert len(re.findall(r'headers=\{"User-Agent"', transport_source)) == 1
