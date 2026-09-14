# Rendering and CSL assets

CiteBind uses **citeproc-py 0.11.1**, pinned because its API and supported CSL
behavior may change between releases. It provides the common rendering rules
used to create CiteBind citation text and inspect it later.

The package includes unmodified IEEE and APA CSL styles at pinned upstream
revisions. `src/citebind/styles/MANIFEST.json` records their URLs and hashes.
The included en-US locale is an oracle for the locale bundled by citeproc-py;
tests check that the processor's locale matches it. Third-party attribution and
license terms are in [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).

The renderer supports a bounded subset of CSL behavior. It reports named
refusals for cases it cannot render correctly, including same-author/same-year
disambiguation and missing source-supplied author name parts. It does not guess
personal names from display strings or use an AI model to format citations.

When updating a processor or style pin, review the upstream change and the
resulting citation/bibliography examples. Keep the raw style files intact;
document and test a deliberate upstream update instead of editing style bytes
to match an expected result. Python rendering checks and native Word/add-in
compatibility checks provide different evidence and both remain necessary.
