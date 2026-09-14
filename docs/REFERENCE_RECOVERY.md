# Recover EndNote and Zotero references from Word

CiteBind can inspect reference data embedded in a DOCX without opening Word,
contacting an external service, or changing the document. EndNote calls its
embedded records a Traveling Library. Zotero also embeds reference data in its
Word citations.

Recovery reports what is present in the file. It does not establish that a
record is correct, reconnect the document to a newly imported library, or edit
native citation fields. Attached PDFs and the complete original library are
not recovered from these citation records.

## Run it

Use Python 3.11 or newer. From a checkout containing this feature:

```console
python -m pip install -e .
python -m citebind recover-references "manuscript.docx" --out "recovery.json"
```

On Windows, `py` can be used in place of `python`. Save the recovery report
first: it contains the source-file SHA-256, recovered records and their original
data, citation-to-record links, complete citation instructions, and findings.
Source IDs and citation-specific data such as page locators remain available
in that report. The metadata status is `recovered_not_verified`.

Choose a library exchange format when needed:

```console
python -m citebind recover-references "manuscript.docx" --format csl-json --out "references.json"
python -m citebind recover-references "manuscript.docx" --format ris --out "references.ris"
python -m citebind recover-references "manuscript.docx" --format bibtex --out "references.bib"
python -m citebind recover-references "endnote-manuscript.docx" --format endnote-xml --out "references.xml"
```

Omit `--out` to write the result to standard output. Existing files are never
overwritten. Findings are printed to standard error; keep those messages with
an exchange file when its conversion reports information loss.

| Format | What it preserves |
| --- | --- |
| `report` (default) | Original recovered metadata and citation instructions, links between occurrences and records, and findings. This is the most complete recovery output. |
| `csl-json` | Recovered CSL fields, with unique export IDs. Zotero item data can retain its extra fields; EndNote-to-CSL mappings have documented limits in the findings. |
| `ris` | Common bibliographic fields in an exchange format understood by EndNote and Zotero. Unsupported fields/types and normalization are reported. |
| `bibtex` | Common bibliographic fields with escaped values and protected corporate author names. Unsupported fields/types and date precision losses are reported. |
| `endnote-xml` | Native EndNote record XML, including fields and styles not mapped to CSL. All recovered records must be EndNote records; mixed-source export is refused rather than dropping Zotero items. |

These exchange files transfer records, not editable Word citation objects.
Importing the file into a manager does **not** automatically relink the existing
citations. Keep the original DOCX and use the manager's own citation tools for
continued native editing.

EndNote author names are currently retained as whole literal strings in the
CSL mapping, with a finding explaining that the reader has not split personal
names into family and given names. Check name handling after CSL-JSON or BibTeX
import; those formats can otherwise treat the whole string as an organization
name. Native EndNote XML retains the original name representation and is the
preferred export when continuing in EndNote. RIS also reports cases where
name interpretation or shared ISBN/ISSN tags depend on the importing manager.

## Coverage and limits

- Supports `ADDIN ZOTERO_ITEM CSL_CITATION` fields carrying `citationItems`
  and `itemData`, and `ADDIN EN.CITE` fields carrying EndNote record XML.
- Handles field instructions split across Word runs, complex and simple fields,
  and citations in supported Word story parts. The report records each part
  and field location. Bibliography machinery is not treated as another citation.
- Recovers references without a DOI, including books, without forcing them into
  CiteBind's narrower verified journal-article schema. Unknown metadata is kept
  in the raw source data, with mapping limitations reported.
- Bookmark-based citation storage and other managers are outside this first
  reader. Recognizable unsupported structures are reported. Plain text citations
  cannot supply deleted embedded metadata; zero recovered records does not prove
  the manuscript contains no citations.
- Corrupt, incomplete, conflicting, or unsupported structures must be checked
  using the report. When recovery contains errors, CiteBind refuses library
  export rather than silently producing an incomplete library. The JSON report
  can still be saved and the command exits with status 1.
- Library export also stops for findings that can leave records missing or
  conflicting, such as a missing referenced story part or an unfinished field.
  These may be warnings in a successful partial recovery report; they still
  require review before the recovered records are presented as a library.
- An unreadable or unsafe package exits with status 2. Recovery uses hardened
  XML parsing and bounded package reads (16 MiB per part, 64 MiB total).
  It does not open external relationships.
- The original manager may change what metadata it embeds across versions.
  Python tests cover generated fixtures. Native compatibility claims require
  the Windows checks below and actual documents from the supported versions.

## Word for Windows acceptance check

Use copies of test documents. Record the Word, EndNote, and Zotero versions.

1. Make one EndNote document and one Zotero document. Include a journal article,
   a book without a DOI, a repeated citation, a multi-item citation with page
   locators, and a citation in a footnote. Save and close Word.
2. Run recovery and compare the records, citation associations, and locators in
   the JSON report against what each manager shows. Repeat after moving a
   citation and saving again. Inspect warnings and errors rather than relying
   only on the recovered count.
3. Confirm the source DOCX hash is unchanged after recovery. Reopen it and use
   Zotero **Refresh** or EndNote **Update Citations and Bibliography**. Existing
   citations should remain editable because recovery has not rewritten them.
4. Import each supported exchange format into a disposable library and compare
   titles, authors, reference types, dates, identifiers, and fields identified
   by conversion warnings. Do not assume new imported items reconnect the
   original document's citations.
5. Try a copy whose citations have been unlinked. Expect no structured recovery
   from those plain text citations. Also try a copy with one damaged field and
   confirm that a diagnostic report is available while library export refuses.

Record outcomes and retain the input/output examples outside the repository.
Do not add private manuscripts to the test suite.

## CiteBind's own copied citations

The separate `check-spike` command now requires a pasted citation's embedded
reference data to survive as well as its visible content control. The current
returned Word paste example fails this requirement. This change corrects the
test result; it does not implement automatic cross-document repair. Keep the
whole source DOCX when handing off CiteBind data until that transfer workflow
has been implemented and tested in Word.
