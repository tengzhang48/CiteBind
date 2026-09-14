# CiteBind

**Verified references that travel with your manuscript.**

CiteBind is a planned Microsoft Word add-in that stores a manuscript's
bibliographic records *inside the DOCX itself*. Citations and the bibliography
are rendered deterministically from that embedded data, so a document can be
saved, emailed, reopened on another machine, or handed to a coauthor who has
never installed CiteBind — and every citation-to-reference relationship is
still recoverable, with no external library, account, or sync service.

> **Status: Python prototype; Word add-in not yet implemented.** References resolve,
> render, and verify from Python. Read-only recovery of EndNote and Zotero
> references from DOCX and reference-file exports are available. No
> Word add-in code has been written, and Phase 1's exit condition still needs a
> human running the spike document in Word. See
> [§ Current status](#current-status).

## The problem

EndNote's Traveling Library and Zotero's Word citations already embed reference
data in the manuscript. That data is recoverable without the complete original
library, although exporting and importing it does not automatically reconnect
the document's citations to a new library.

CiteBind aims to make citation identity and metadata independently inspectable:
a documented, versioned document contract; reference acquisition from named
sources; deterministic rendering with explicit limits; and checks that the
displayed citations agree with the embedded records. It can also recover
existing EndNote/Zotero records while preserving their native Word fields.

## How it works

```text
Crossref / PubMed
        |
        v
  CiteBind Word add-in
  search, verify, insert,
  format, update
        |
        v
 self-contained DOCX
        |
        v
     ArtifactCert
  inspect and verify only
        |
        v
   checked handoff
```

1. The researcher enters an exact title, DOI, or PMID.
2. CiteBind queries Crossref and/or PubMed directly.
3. The researcher selects and confirms the correct record.
4. Normalized metadata is stored in a versioned custom XML part in the DOCX.
5. A tagged content control is inserted at the cursor for the citation.
6. A maintained CSL processor renders citations and the bibliography
   deterministically from the embedded records.
7. The document is saved, shared, and reopened — still self-contained.

### AI is optional and subordinate

AI may normalize an entered title, rank search candidates, or explain a
metadata disagreement between sources. It **must never** invent identifiers or
bibliographic metadata, and it **must not** render the final citation format.
Ordinary DOI, PMID, and exact-title lookup does not depend on a model at all.

## The document contract

A versioned custom XML part, `citebind/1`, holds:

```text
document
  schema_version
  selected_style
  references
    R001
      DOI and/or PMID
      title, authors, journal, year
      author_names (family/given as the SOURCE gave it) when available
      volume/issue/pages when available
      metadata_source
      retrieved_at
  citation_clusters
    C001
      ordered reference IDs
      optional locator/prefix/suffix
```

In the Word body, each citation cluster is an inline content control tagged
`citebind:citation:C001`, and the bibliography is a content control tagged
`citebind:bibliography`. Visible text is generated from the embedded data and
the selected CSL style.

No provenance digests, permissions, approval states, or event ledger in v1.
Fields get added only when a real, reproduced failure requires them.

Recovered EndNote/Zotero data is kept in a separate `citebind-recovery/1` report.
It is labelled **recovered, not verified** and is not silently converted into
the stricter `citebind/1` contract.

## Recover references from an existing manuscript

After installing the package (`python -m pip install -e .`), run:

```console
python -m citebind recover-references manuscript.docx --out recovery.json
python -m citebind recover-references manuscript.docx --format csl-json --out references.json
python -m citebind recover-references manuscript.docx --format ris --out references.ris
```

The default JSON report retains original records, citation instructions,
citation-to-record links, and recovery findings. The command reads the source
DOCX without rewriting it and creates new output files only. BibTeX is also
available; native EndNote records can be exported as EndNote XML. Format
limitations are reported. A damaged supported citation prevents library export;
the diagnostic recovery report remains available.

This reads field-based citations, not a native EndNote or Zotero database. It
does not relink citations, verify metadata against an external service, or edit
the document's citation fields. See [formats, limitations, and Windows checks](docs/REFERENCE_RECOVERY.md).

## Scope of the first version

**In scope:** journal articles resolved by DOI and/or PMID; one numeric style
and one author–year style; Word desktop on Windows and macOS; export to
CSL-JSON and BibTeX.

**Out of scope:** general literature discovery or deep research; a global
Zotero/EndNote-style library; PDF organization or annotation; collaborative
editing; cloud accounts or sync; being an ArtifactCert subsystem; guaranteed
identical behavior in Word Online.

## Relationship to ArtifactCert

CiteBind and [ArtifactCert](https://github.com/tengzhang48/ArtifactCert) are
**separate projects with separate repositories**, and the self-contained DOCX
is the entire interface between them. There is no shared database, account
system, runtime, or web service.

- **CiteBind** creates, verifies, formats, and stores citations.
- **ArtifactCert** later checks that those structures remain correct across a
  document handoff — read-only, never editing them.

If CiteBind structures are broken, ArtifactCert reports "Open in CiteBind to
repair" rather than attempting to fix them. ArtifactCert must not become a
second citation editor. Integration work does not begin until the `citebind/1`
contract is stable (Phase 6).

## Development phases

| Phase | Goal | Exit condition |
| --- | --- | --- |
| 0 | Contract and fixtures | The document contract fits on one page |
| 1 | Word persistence spike | Citation identity survives save/reopen with no external library |
| 2 | Verified reference acquisition | No stored reference depends on model-generated identity |
| 3 | Deterministic citation and bibliography | Citations and bibliography stay mutually consistent |
| 4 | Editing robustness and portability | Document stays usable through realistic Word editing |
| 5 | Real-manuscript pilot | 5–10 real manuscripts complete without citation loss or drift |
| 6 | Read-only ArtifactCert adapter | ArtifactCert inspects without modifying |

Full detail, including per-phase task lists and the integration acceptance
test, is in [`docs/CiteBind_PLAN_2026-08-29.md`](docs/CiteBind_PLAN_2026-08-29.md).
The execution plan for Phase 0-1 -- task ledger, acceptance criteria, and the
implementer/driver protocol -- is in
[`docs/GLM_DEV_PLAN.md`](docs/GLM_DEV_PLAN.md).

## Current status

**Implemented** (Python, on the `phase1-spike` branch): identifier
normalization; the transport seam, meaning live HTTP plus a replay transport
backed by recorded raw API responses; Crossref and PubMed resolvers; structured
cross-source comparison; title search that returns candidates and never a
selection; the `citebind/1` custom XML part; tagged content controls;
deterministic rendering of citations and the bibliography in one numeric and
one author–year style, with named refusals where it cannot be correct; the
Phase 1 spike kit (`make-spike` and `check-spike`); and an `inspect` / `diff`
CLI. Read-only EndNote/Zotero DOCX reference recovery and library-file exports
are also implemented, separately from the verified `citebind/1` data model.

**Not implemented: the add-in itself.** There is no Office.js project. The
Python above is a resolver library and a document-inspection kit — it can write
and read a DOCX carrying `citebind/1` structures, but nothing runs inside Word.

**Phase 2 is complete**, accepted in review on 2026-09-02: no stored reference
depends on model-generated identity.

**Phase 3 is implemented.** Citations and the bibliography render
deterministically from the embedded payload through citeproc-py 0.11.1
(exactly pinned), with `ieee.csl` and `apa.csl` vendored raw at pinned
upstream commits. The renderer refuses, by name, five cases it cannot get
right rather than emitting a plausible wrong citation — including two works by
one author in one year, which real styles render 2009a/2009b and citeproc-py
does not.

Rendering closed a hole worth naming: `inspect` used to call a document clean
while it displayed `[7]` over a payload holding one reference, because nothing
could say what the citation *should* say. It now compares visible text against
the payload's rendering and reports `visible_text_mismatch`. The first time
that check ran it failed on this repository's own spike fixture, whose
bibliography line had been hand-written in a style the payload does not
produce; the fixture is now rendered rather than typed.

That work required one contract change, which is worth arguing with: a
reference may now carry `author_names`, the family/given split as the source
supplied it. Crossref sends that split and CiteBind used to discard it, and
without it *no* style renders an author label correctly — APA produced
`(Daniel A Belletti, 2010)` and IEEE `Daniel A Belletti,` instead of
`(Belletti, 2010)` and `D. A. Belletti,`. The field is optional because PubMed
supplies no split at all; a PubMed-only reference is refused for rendering
rather than having its display string guessed apart.

**Phase 1's exit condition is still unmet, and it is the blocking item.** It
needs a human in Word for about five minutes:

- generate the spike document: `python -m citebind make-spike`;
- follow [`spike/SPIKE_INSTRUCTIONS.md`](spike/SPIKE_INSTRUCTIONS.md) — save
  and reopen, edit around a citation, copy one within the document, copy one
  into a new document, and edit next to one with Track Changes on;
- return the four files: `python -m citebind check-spike <files...>`.

That spike answers the highest-risk question — whether tagged citations and
their embedded reference data survive real Word editing and handoff. Until it
runs, the `citebind/1` contract is not settled; it is unexamined. The
cross-document paste and Track Changes probes are pulled forward from Phase 4
deliberately: if content controls do not survive them, the contract itself
needs rethinking, and that is much cheaper to learn now than after Phase 3.

The returned Word paste example currently retains the citation control but
loses its reference library. The checker now requires both the control and
resolvable reference data for the cross-document paste probe to pass. Automatic
repair or transfer of the missing records has not been implemented; preserving
a citation's visible text alone is not proof of portability.

## Development discipline

- Keep CiteBind and ArtifactCert in separate repositories.
- Do not modify ArtifactCert until Phase 6.
- Solve one reproduced Word failure at a time.
- Prefer replacement and simplification over accumulating mechanisms.
- Every new state, service, or workflow step must solve an observed
  real-document problem.
- Keep Word-visible behavior explainable to a researcher in one sentence.
- Always preserve the ability to export and leave the system.
