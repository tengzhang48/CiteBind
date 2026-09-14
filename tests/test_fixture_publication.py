"""Publishing fixtures must preserve bibliographic values and provenance."""

import hashlib
import json
from pathlib import Path
import runpy


ROOT = Path(__file__).resolve().parents[1]
prepare_fixture = runpy.run_path(str(ROOT / "spike" / "record_fixtures.py"))["prepare_fixture"]


def test_abstracts_omitted_without_changing_other_values():
    data = {"message": {"abstract": "publisher prose", "items": [
        {"abstract": "other prose", "title": ["A title"],
         "author": [{"family": "García", "given": "A."}], "year": 2020}
    ]}}
    original = json.dumps(data).encode()
    published, provenance = prepare_fixture(original)
    assert json.loads(original) == data
    assert json.loads(published) == {"message": {"items": [
        {"title": ["A title"], "author": [{"family": "García", "given": "A."}], "year": 2020}
    ]}}
    assert provenance == {
        "source_sha256": hashlib.sha256(original).hexdigest(),
        "sha256": hashlib.sha256(published).hexdigest(),
        "omitted_fields": ["/message/abstract", "/message/items/0/abstract"],
    }


def test_abstract_free_response_keeps_original_bytes():
    original = b'{ "message" : { "title": ["Fixture"], "author": [] } }\n'
    published, provenance = prepare_fixture(original)
    assert published == original
    assert provenance["source_sha256"] == provenance["sha256"]
    assert provenance["omitted_fields"] == []


def test_committed_fixtures_are_abstract_free_and_match_manifest():
    directory = ROOT / "spike" / "recordings"
    manifest = json.loads((directory / "MANIFEST.json").read_text(encoding="utf-8"))
    for entry in manifest["recordings"]:
        body = (directory / entry["file"]).read_bytes()
        unchanged, provenance = prepare_fixture(body)
        assert unchanged == body, entry["file"]
        assert not provenance["omitted_fields"], entry["file"]
        assert hashlib.sha256(body).hexdigest() == entry["sha256"]
