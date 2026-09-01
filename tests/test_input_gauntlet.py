"""The input gauntlet: every input class x every entry point.

Why this file exists: three review rounds found the SAME bug class one
instance at a time (nonexistent path, then corrupt file, then directory,
then a traceback from the CLI guard forgetting UnsafeXML). This gauntlet
enumerates the input space systematically and pins the contract:

- the library may only raise narrow, named errors (PayloadError, UnsafeXML,
  SchemaError) or the file-level errors of the platform (OSError family,
  BadZipFile, KeyError) — never anything else;
- the CLI never prints a traceback, and its error message never contains a
  placeholder like "None".

Add a new input class here when a new kind of bad input is discovered; add
a new entry point to the loops when one is added to the package.
"""

import io
import os
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

from citebind.__main__ import main
from citebind.controls import find_controls
from citebind.part import extract
from citebind.spike import NAMED_INPUT_ERRORS, make_spike
from citebind.verify import inspect

# The library may raise exactly these error FAMILIES for bad input. The
# tuple is owned at runtime by citebind.spike (the one place that must
# catch them); the gauntlet holds the library to it. isinstance, not
# name-matching: FileNotFoundError/IsADirectoryError/PermissionError are
# OSError subclasses and are named members of this set.
NAMED_ERRORS = NAMED_INPUT_ERRORS


def make_zip(path: Path, entries: dict) -> None:
    with zipfile.ZipFile(path, "w") as z:
        for name, data in entries.items():
            z.writestr(name, data)


INPUT_CLASSES: dict[str, object] = {
    "missing": lambda p: None,
    "directory": lambda p: p.mkdir(),
    "empty_file": lambda p: p.write_bytes(b""),
    "text_file": lambda p: p.write_bytes(b"hello there"),
    "ole_doc_renamed": lambda p: p.write_bytes(b"\xd0\xcf\x11\xe0" + b"\x00" * 64),
    "empty_zip": lambda p: make_zip(p, {}),
    "zip_no_document_xml": lambda p: make_zip(p, {"x.txt": b"hi"}),
    "zip_document_xml_malformed": lambda p: make_zip(p, {"word/document.xml": b"<w:p"}),
    "zip_document_xml_doctype": lambda p: make_zip(p, {"word/document.xml": b"<!DOCTYPE x><x/>"}),
    "zip_document_xml_foreign_root": lambda p: make_zip(p, {"word/document.xml": b"<html/>"}),
    "permission_denied": lambda p: (p.write_bytes(b"secret"), os.chmod(p, 0)),
}


def _run_cli(argv):
    """Run main() capturing output; return (rc, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = main(argv)
    return rc, out.getvalue(), err.getvalue()


@pytest.fixture(params=sorted(INPUT_CLASSES), ids=str)
def bad_input(request, tmp_path):
    path = tmp_path / "input.docx"
    INPUT_CLASSES[request.param](path)
    return path


# --- library surface: only named errors may escape -----------------------------


@pytest.mark.parametrize(
    "name,fn",
    [("inspect", inspect), ("find_controls", find_controls), ("extract", extract)],
)
def test_library_only_raises_named_errors(bad_input, name, fn):
    try:
        fn(bad_input)
        return  # a clean answer (payload absent, controls empty, ...) is fine
    except Exception as error:
        assert isinstance(error, NAMED_ERRORS), (
            f"{name} escaped with an unnamed {type(error).__name__}: {error}"
        )


# --- CLI surface: never a traceback, always a defined exit code ----------------


def test_cli_inspect_never_tracebacks(bad_input, capsys):
    rc, out, err = _run_cli(["inspect", str(bad_input)])
    assert rc in (0, 1, 2)
    assert "Traceback" not in err


def test_cli_diff_never_tracebacks(bad_input, tmp_path, capsys):
    good = make_spike(tmp_path / "good")
    rc, out, err = _run_cli(["diff", str(bad_input), str(good)])
    assert rc in (0, 1, 2)
    assert "Traceback" not in err


def test_cli_check_spike_never_tracebacks(bad_input, tmp_path, capsys):
    clean = make_spike(tmp_path / "clean")
    masquerading = tmp_path / "pasted.docx"
    if bad_input.is_dir():
        masquerading.mkdir()
    elif bad_input.exists() and os.access(bad_input, os.R_OK):
        masquerading.write_bytes(bad_input.read_bytes())
    elif bad_input.exists():
        masquerading.write_bytes(b"unreadable")
    rc, out, err = _run_cli(["check-spike", str(clean), str(masquerading)])
    assert rc in (0, 1, 2)
    assert "Traceback" not in err


def test_cli_make_spike_never_tracebacks_and_names_the_problem(tmp_path, capsys):
    blocker = tmp_path / "blocker"
    blocker.write_text("i am a file, not a directory")
    rc, out, err = _run_cli(["make-spike", "--out", str(blocker)])
    assert rc != 0
    assert "Traceback" not in err
    assert "None" not in err  # the message must name the real target


def test_cli_inspect_unsafe_xml_is_named_not_traceback(tmp_path, capsys):
    # The regression that motivated the gauntlet: a DOCTYPE-laced document
    # used to escape the CLI guard as UnsafeXML and print a traceback.
    path = tmp_path / "laced.docx"
    make_zip(path, {"word/document.xml": b"<!DOCTYPE x><x/>"})
    rc, out, err = _run_cli(["inspect", str(path)])
    assert rc == 2
    assert "doctype_declared" in err
    assert "Traceback" not in err


# --- Phase 2 response-level input classes (T-08) ---------------------------------
# The same contract as above, extended to the transport seam: bad responses
# are refused by name and never crash.

import socket
import urllib.error

from citebind.transport import (
    TransportError,
    CODE_CONNECTION_ERROR,
    CODE_EMPTY_RESULT,
    CODE_HTTP_ERROR,
    CODE_MALFORMED_JSON,
    CODE_TIMEOUT,
    CODE_URL_NOT_RECORDED,
    ReplayTransport,
    ResponseError,
    TransportResponse,
    check_status,
    classify_urlopen_error,
    decode_json,
    require_non_empty,
)

_RESPONSE_CLASSES = {
    "http_404": (TransportResponse(404, b'{"status": "error"}'), CODE_HTTP_ERROR),
    "http_500": (TransportResponse(500, b"<html>boom</html>"), CODE_HTTP_ERROR),
    "malformed_json": (TransportResponse(200, b"{not json"), CODE_MALFORMED_JSON),
}


@pytest.mark.parametrize("kind", sorted(_RESPONSE_CLASSES))
def test_bad_responses_are_refused_by_name(kind):
    response, expected_code = _RESPONSE_CLASSES[kind]
    if kind.startswith("http_"):
        with pytest.raises(ResponseError) as e:
            check_status(response, source="crossref")
    else:
        with pytest.raises(ResponseError) as e:
            decode_json(response, source="crossref")
    assert e.value.code == expected_code


def test_empty_result_set_refused_by_name():
    with pytest.raises(ResponseError) as e:
        require_non_empty([], source="crossref", what="title search")
    assert e.value.code == CODE_EMPTY_RESULT


def test_timeout_classified_by_name():
    error = classify_urlopen_error(socket.timeout("timed out"))
    assert isinstance(error, TransportError)
    assert error.code == CODE_TIMEOUT


def test_connection_error_classified_by_name():
    error = classify_urlopen_error(
        urllib.error.URLError(reason=ConnectionRefusedError(111, "refused"))
    )
    assert isinstance(error, TransportError)
    assert error.code == CODE_CONNECTION_ERROR


def test_replay_unknown_url_named(tmp_path):
    manifest = tmp_path / "MANIFEST.json"
    manifest.write_text(_json.dumps({"recordings": []}))
    with pytest.raises(TransportError) as e:
        ReplayTransport(manifest).fetch("https://api.crossref.org/works/9.9/none")
    assert e.value.code == CODE_URL_NOT_RECORDED


def test_replay_corrupt_manifest_named(tmp_path):
    path = tmp_path / "MANIFEST.json"
    path.write_text("{not json")
    with pytest.raises(TransportError) as e:
        ReplayTransport(path)
    assert e.value.code == "malformed_manifest"


import json as _json


def test_response_error_codes_all_distinct():
    codes = {
        CODE_HTTP_ERROR,
        CODE_MALFORMED_JSON,
        CODE_EMPTY_RESULT,
        CODE_TIMEOUT,
        CODE_CONNECTION_ERROR,
        CODE_URL_NOT_RECORDED,
    }
    assert len(codes) == 6
