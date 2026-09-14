# Roadmap

CiteBind is an experimental Python toolkit. Its first public scope is reference
recovery and inspectable citation data; the Word add-in remains a future project.

## Available

- Recover embedded EndNote and Zotero records from supported DOCX fields.
- Export a recovery report, CSL-JSON, RIS, BibTeX, and native EndNote XML.
- Resolve and compare journal-article metadata through Crossref and PubMed.
- Store and inspect CiteBind records and citation links inside DOCX files.
- Render a bounded set of IEEE/APA cases using pinned CSL assets and check
  displayed text against the stored data.

## Next validation work

1. Test real Zotero documents and additional EndNote versions.
2. Run import, refresh, save/reopen, and editing checks in Word for Windows.
3. Resolve the observed loss of reference data when a CiteBind citation is
   copied into a different document, preserving reference identity.
4. Expand supported input variants and rendering cases when real examples
   justify a change and can be represented by shareable regression fixtures.

## Later work

- A Word add-in for inserting, editing, moving, and updating CiteBind citations.
- Carefully scoped native EndNote/Zotero interoperability beyond recovery.
- A real-manuscript pilot and macOS Word testing.
- A separate ArtifactCert adapter that inspects CiteBind structures after the
  document contract is validated. There is no current runtime integration.

The project does not require a cloud account, a synchronization service, or an
AI model for ordinary reference lookup and recovery. A general reference-library
manager and PDF organizer are outside the current scope.
