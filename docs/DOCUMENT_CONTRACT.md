# Document contracts

CiteBind keeps authored citation data and recovered foreign metadata in separate
models. Neither model changes merely because a new field appears in a manuscript.

## CiteBind data: `citebind/1`

The Python library serializes its data model into a versioned DOCX custom XML part.
The schema and validation rules live in `src/citebind/schema.py` and
`src/citebind/model.py`.

```text
document
  schema_version
  selected_style
  references
    id, DOI and/or PMID, title, authors, journal, year
    author_names (source-supplied family/given names, when available)
    volume, issue, pages (when available)
    metadata_source, retrieved_at
  citation_clusters
    id, ordered reference_ids, optional locator/prefix/suffix
```

This model currently covers journal articles resolved by DOI and/or PMID.
Source attribution is retained; schema validity alone is not proof that a
reference was independently verified.

Word content controls associate displayed text with records:

- Citation cluster: `citebind:citation:C001` (using the actual cluster ID).
- Bibliography: `citebind:bibliography`.

`inspect` checks payload structure, control associations, and supported visible
rendering. `diff` compares two documents' CiteBind structures. These commands
are not general EndNote/Zotero validators.

## Foreign recovery: `citebind-recovery/1`

`recover-references` reads native EndNote/Zotero fields without rewriting the
document and produces a separate report. The report retains:

- The source DOCX SHA-256.
- Recovered records with source identities, mapped CSL data, and raw metadata.
- Citation occurrences, part locations, and original field instructions.
- Findings describing malformed, unsupported, ambiguous, or unmapped content.

Its metadata status is `recovered_not_verified`. It can contain books and other
records outside `citebind/1`; recovery does not silently convert those records
into the stricter model. Conflicting records remain visible for review.

Library export applies additional completeness checks. The JSON report remains
the source of diagnostic detail when a library export is refused. See the
[recovery guide](REFERENCE_RECOVERY.md) for formats and limitations.
