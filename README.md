# CiteBind

Recover embedded references from Word documents, export them to reference
managers, and inspect citation data stored inside a DOCX.

**Status: experimental Python package.** EndNote/Zotero reference recovery and
exports work from the command line. The planned Word add-in is not implemented.
Native Word, EndNote, and Zotero compatibility checks remain in progress.

## What you can use today

| Feature | Available behavior |
| --- | --- |
| Recover EndNote references | Read embedded Traveling Library records from supported Word citation fields. |
| Recover Zotero references | Read embedded item data from supported Word citation fields. |
| Export records | Save a detailed JSON report, CSL-JSON, RIS, BibTeX, or native EndNote XML. |
| Inspect CiteBind documents | Check CiteBind's embedded records, citation links, and displayed text; compare two DOCX files. |
| Python library | Resolve references through Crossref/PubMed, compare metadata, and create/render CiteBind structures. |

Recovery reads the source DOCX without rewriting it. Existing native citation
fields stay in the original document. Recovered metadata is **not independently
verified**, and importing an exported reference file does not automatically
relink Word citations to a new library.

EndNote and Zotero already embed reference data in Word documents. CiteBind
provides a separate way to inspect and recover that data without requiring the
original reference library.

## Install from source

Requires **Python 3.11 or newer** and Git for the clone command. You can also
download and extract the repository ZIP, then open a terminal in that folder.
Microsoft Word is not required to run the Python tools.

```console
git clone https://github.com/tengzhang48/CiteBind.git
cd CiteBind
```

On Windows, in PowerShell:

```powershell
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install .
.venv\Scripts\python.exe -m citebind --help
```

On Linux or macOS:

```console
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/python -m citebind --help
```

In the examples below, replace `python` with the virtual environment's Python
path shown above. Installation downloads Python dependencies; reference recovery
and document inspection run locally without a network connection or an AI model.
Crossref/PubMed lookup functions use those services over the network.

## Recover references

```console
python -m citebind recover-references manuscript.docx --out recovery.json
python -m citebind recover-references manuscript.docx --format ris --out references.ris
python -m citebind recover-references manuscript.docx --format csl-json --out references.json
python -m citebind recover-references manuscript.docx --format bibtex --out references.bib
python -m citebind recover-references endnote-manuscript.docx --format endnote-xml --out references.xml
```

Start with the JSON report: it retains source records, citation instructions,
citation-to-record links, and findings. Output files must be new; existing files
are never overwritten. Recovery errors or findings that indicate missing or
conflicting records prevent library export, while recoverable data remains
available in the report.

Use native EndNote XML when continuing in EndNote. It preserves fields and name
representations that other export formats may not carry. EndNote author names
remain literal strings in the CSL mapping and require checking after import.

See the [recovery guide](docs/REFERENCE_RECOVERY.md) for supported fields,
conversion limits, exit codes, and a Word for Windows test procedure.

## Try a generated CiteBind document

```console
python -m citebind make-spike --out sample
python -m citebind inspect sample/spike_v1.docx
python -m citebind diff before.docx after.docx
```

`inspect` and `diff` check **CiteBind's own structures**. Use `recover-references`
for EndNote/Zotero fields. The sample generator creates a new test DOCX from
public bibliographic metadata; it does not require a private manuscript.

The [Word test instructions](spike/SPIKE_INSTRUCTIONS.md) cover save/reopen,
editing, and copying citations. Current Word evidence shows that copying a
CiteBind citation into a different document can lose its embedded reference
data. Automatic transfer or repair is not implemented. Keep the complete source
DOCX when sharing CiteBind records.

## Current limits and direction

- Field-based EndNote and Zotero recovery is supported; bookmark-based storage,
  unlinked plain text citations, and other managers have limits described in the
  recovery guide.
- CiteBind does not edit native EndNote/Zotero fields or their library databases.
- Rendering uses pinned IEEE and APA CSL styles through `citeproc-py`, with
  explicit refusals for unsupported cases, including author–year disambiguation.
- Python checks and generated fixtures do not establish compatibility with all
  Word/add-in versions. Real Zotero document testing and Windows import/refresh
  checks remain necessary.

CiteBind is separate from ArtifactCert. A DOCX is the intended interface;
CiteBind has no runtime dependency on ArtifactCert. The planned adapter and Word
add-in are described in the [roadmap](docs/ROADMAP.md).

## Development and licensing

See [CONTRIBUTING.md](CONTRIBUTING.md) for installation, offline tests, fixture
provenance, and build checks, and the [document contract](docs/DOCUMENT_CONTRACT.md)
for the two data models.

CiteBind's original code and documentation use the [MIT license](LICENSE).
Bundled CSL styles and the locale retain **CC BY-SA 3.0**. Public reference
fixtures have separate provenance. See [third-party notices](THIRD_PARTY_NOTICES.md).
