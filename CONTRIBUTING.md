# Contributing to CiteBind

Small, reproducible improvements to reference recovery, export fidelity, and
document inspection are welcome. Include a generated example and the expected
behavior when reporting a bug. Do not upload private manuscripts, library
databases, access tokens, or recovery reports containing private research.

## Development setup

Create a virtual environment as described in the README. Using that environment's
Python interpreter, run:

```console
python -m pip install -e ".[dev]"
python -m pytest -q
```

Use `python -m pytest` so tests run with the interpreter where CiteBind is
installed. The suite uses generated DOCX files and saved public metadata;
ordinary tests do not call live Crossref or PubMed services.

## Making changes

- Preserve original documents and native citation fields during recovery.
- Keep recovered, unverified metadata separate from the `citebind/1` model.
- Report unsupported structures and incomplete exports explicitly.
- Add a regression test for a reproduced behavior defect. Documentation-only
  edits do not require new unit tests.
- Keep changes independent of ArtifactCert and other local repositories.
- Generate DOCX fixtures programmatically; keep manual Word evidence outside Git.

The [document contract](docs/DOCUMENT_CONTRACT.md) describes the data models.
The [rendering notes](docs/RENDERING.md) explain the pinned CSL processor and
style assets. Updating those pins requires checking the affected renderings.

## Fixture provenance

The metadata fixtures have source and derivation information in
[`spike/recordings/README.md`](spike/recordings/README.md). Preserve factual values
from their source; do not manufacture a DOI, author, date, or retrieval time to
make a test pass. Synthetic malformed-input fixtures should be clearly identified
as synthetic.

`python spike/record_fixtures.py` deliberately contacts live APIs and writes new
fixtures. It refuses an existing manifest unless `--force` is supplied. Review
the generated diff and provenance before committing. Ordinary verification
does not require re-recording.

## Build and check an installation

```console
python -m build
```

Install the resulting wheel into a fresh virtual environment. From outside the
checkout, run `python -m citebind --help`, generate a sample with `make-spike`, and
inspect it. This checks that the distribution includes its runtime CSL assets.
Both wheels and source distributions must include the applicable licenses.

CI runs Python tests on Linux and Windows and checks source/wheel packaging.
A Windows Python test run does not exercise Microsoft Word. Use the
[Word persistence test](spike/SPIKE_INSTRUCTIONS.md) and
[EndNote/Zotero acceptance procedure](docs/REFERENCE_RECOVERY.md#word-for-windows-acceptance-check)
for native compatibility evidence, recording the application versions used.
