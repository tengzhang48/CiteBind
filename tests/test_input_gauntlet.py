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
