# CiteBind: Bounded Development and ArtifactCert Integration Plan

**Date:** 2026-08-29  
**Status:** Proposed plan; no implementation started  
**Working name:** CiteBind — verified references that travel with your manuscript

## 1. Product decision

CiteBind should be a separate project from ArtifactCert.

- **CiteBind creates and manages citations inside Word.**
- **ArtifactCert checks that those citations and references remain correct in a document handoff.**
- The self-contained DOCX is the interface between them. They do not need a shared database, account system, runtime, or web service.

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

This fits ArtifactCert well because ArtifactCert already treats the document as the controlled artifact. CiteBind gives that artifact more reliable, machine-readable citation structure.

## 2. Narrow first-version scope

The first version supports one practical workflow:

1. The researcher enters an exact title, DOI, or PMID.
2. CiteBind searches Crossref and/or PubMed.
3. The researcher selects and confirms the correct paper.
4. CiteBind stores normalized metadata inside the DOCX.
5. CiteBind inserts a tagged citation at the Word cursor.
6. Deterministic CSL code formats citations and the bibliography.
7. The DOCX is saved, shared, reopened, and remains self-contained.

For v1, support journal articles resolved by DOI and/or PMID. The data model may allow other record types later, but v1 should not implement them.

AI is optional and subordinate. It may normalize an entered title, rank search candidates, or explain metadata disagreements. It must never invent identifiers or bibliographic metadata, and it must not render the final citation format.

## 3. Explicitly out of scope

The first version is not:

- a general literature-discovery or deep-research system;
- a global Zotero/EndNote-style library;
- a PDF organizer or annotation manager;
- a collaborative editor or multi-user service;
- a cloud account or synchronization platform;
- an ArtifactCert subsystem;
- dependent on AI for ordinary DOI, PMID, or exact-title lookup;
- initially guaranteed to work identically in Word Online.

Target Word desktop on Windows and macOS first. Test platform behavior before making broader compatibility claims.

## 4. Minimal DOCX contract

Use a versioned custom XML part in the DOCX, for example `citebind/1`.

The minimum stored structure is:

```text
document
  schema_version
  selected_style
  references
    R001
      DOI and/or PMID
      title
      authors
      journal
      year
      volume/issue/pages when available
      metadata_source
      retrieved_at
  citation_clusters
    C001
      ordered reference IDs
      optional locator/prefix/suffix
```

In the Word body:

- each citation cluster is an inline content control tagged like `citebind:citation:C001`;
- the bibliography is a content control tagged `citebind:bibliography`;
- visible text is generated deterministically from the embedded data and selected CSL style.

Do not add provenance digests, permissions, approval states, or a general event ledger in v1. Add fields only when a real failure requires them.

## 5. Development phases

### Phase 0 — Contract and fixtures

- Create a new, independent repository.
- Write the small `citebind/1` schema and ownership boundary.
- Prepare a few real, legally shareable reference records and DOCX fixtures.
- Record expected behavior for save/reopen, copy/paste, move, delete, and renumbering.

**Exit condition:** the document contract can be explained on one page and contains only what the first experiment needs.

### Phase 1 — Word persistence spike

Do not start with AI, multiple providers, or the full CSL catalog.

- Embed one hard-coded DOI-resolved reference in custom XML.
- Insert one tagged citation content control at the cursor.
- Insert one tagged bibliography control.
- Save, close Word, reopen, and recover the reference-to-citation relationship.
- Confirm that a collaborator without CiteBind can still read the visible document normally.

**Exit condition:** structured citation identity survives an ordinary DOCX save/reopen cycle without an external library.

### Phase 2 — Verified reference acquisition

- Accept DOI, PMID, or exact title.
- Query Crossref and PubMed directly.
- Show candidate metadata and its source.
- Require the researcher to choose the intended record.
- Normalize identifiers and detect duplicate DOI/PMID records.
- Store the confirmed record inside the DOCX.

If Crossref and PubMed disagree, show the disagreement; do not silently merge uncertain fields.

**Exit condition:** no stored v1 reference depends on model-generated bibliographic identity.

### Phase 3 — Deterministic citation and bibliography updates

- Integrate a maintained CSL processor.
- Initially validate one numeric style and one author–year style.
- Insert citations at the cursor.
- Support multi-reference citation clusters.
- Renumber or re-render citations after insertion, movement, or deletion.
- Generate and update the bibliography from cited embedded records.

**Exit condition:** citations and bibliography remain mutually consistent after ordinary editing.

### Phase 4 — Editing robustness and portability

Test the operations researchers actually perform:

- insert a new citation before existing numeric citations;
- move a cited paragraph;
- copy and paste a citation cluster within the document;
- copy a cluster between documents without silent ID collision;
- delete a citation and update the bibliography;
- edit around a citation with Track Changes enabled;
- save, close, reopen, and continue working;
- export CSL-JSON, BibTeX, and optionally RIS.

Define recoverable behavior for damaged or stale content controls. The tool should report the problem and offer a bounded repair; it should not guess silently.

**Exit condition:** the document remains usable and self-contained through realistic Word editing.

### Phase 5 — Real-manuscript pilot

- Use several real manuscripts, not fabricated benchmark papers.
- Include both numeric and author–year journals.
- Test on Word for Windows and macOS.
- Include handoffs to coauthors who do not have CiteBind installed.
- Record failures before expanding the feature set.

**Exit condition:** at least 5–10 real manuscript workflows complete without citation loss, silent metadata substitution, or bibliography drift.

### Phase 6 — Read-only ArtifactCert adapter

Start this only after `citebind/1` is stable and the Word spike succeeds.

ArtifactCert may then recognize CiteBind structures and check:

- the schema version is supported;
- reference IDs and citation-cluster IDs are unique;
- every citation points to an embedded reference;
- every supported-profile reference has a verified DOI and/or PMID;
- visible citation text matches deterministic rendering;
- the bibliography matches the cited references and selected style;
- no references, clusters, or bibliography entries are orphaned unexpectedly;
- citation structures survived comparison between original and updated candidates;
- a handoff did not introduce unintended citation/reference changes.

ArtifactCert must not become a second citation editor. CiteBind content controls and custom XML are protected structured content. If they are broken, ArtifactCert should report, “Open in CiteBind to repair,” after which the corrected DOCX can be frozen and checked again.

Ordinary surrounding prose can continue through ArtifactCert's normal A001 Apply & Verify workflow.

## 6. Integration acceptance test

The initial integration is complete when ArtifactCert can inspect a CiteBind document without modifying it and correctly detect at least:

1. a citation cluster whose reference is missing;
2. duplicate or conflicting embedded identifiers;
3. a stale visible citation after metadata/style change;
4. an uncited bibliography entry or a cited reference missing from the bibliography;
5. a citation/reference change between two DOCX candidates;
6. preservation of all CiteBind structures through an unrelated ArtifactCert prose edit.

## 7. First CiteBind milestone

The first useful milestone should demonstrate this entire sequence:

1. Enter an exact paper title.
2. Resolve and confirm its DOI or PMID.
3. Save the record inside the DOCX.
4. Insert the citation in two locations.
5. Add a second paper before the first citation and update numbering.
6. Move, copy, and delete citation clusters.
7. Regenerate a correct bibliography.
8. Save and reopen the document offline.
9. Recover every citation-to-reference relationship without an external library.
10. Export the embedded library as CSL-JSON and BibTeX.

That milestone establishes the distinctive value: the verified reference library travels with the manuscript.

## 8. Development discipline

- Keep CiteBind and ArtifactCert in separate repositories.
- Do not modify ArtifactCert until Phase 6.
- Solve one reproduced Word failure at a time.
- Prefer replacement and simplification over accumulating mechanisms.
- Every new state, service, or workflow step must solve an observed real-document problem.
- Keep Word-visible behavior understandable to a researcher in one sentence.
- Preserve the ability to export and leave the system.

## 9. Immediate next action

Create the separate repository and perform only the Phase 1 persistence spike. That experiment will answer the highest-risk question—whether tagged citations and their embedded reference data survive real Word editing and handoff—before substantial product development begins.

## 10. Review notes (added 2026-08-29)

### 10.1 Verification of the "ArtifactCert untouched" claim

Checked directly rather than assumed. In `/media/volume/cpu-vm/ArtifactCert`:

- `git status --short` shows no modified or staged files. The only untracked
  items are pre-existing evidence-bundle notes and three manuscript DOCXs, none
  CiteBind-related.
- HEAD is still detached at `a95733c` (2026-08-28, "Review of the Evidence
  Bundle v1 short plan (GLM)").
- Both existing worktrees are untouched: `/home/exouser/ac-t8-integration`
  (`f162b60`, `integration/t8-proof-round-v2`) and
  `/media/volume/cpu-vm/ac-integrate-v2` (`34107ee`,
  `milestone/docx-internal-pilot-2026-08-28`).

The claim holds. This plan is proposal-only; no code has moved.

### 10.2 Risk flag 1 — pull one paste/track-changes probe into Phase 1

Phase 1 is correctly identified as the highest-risk step, but the specific
failure mode most likely to kill an add-in of this shape is deferred to
Phase 4: content-control tag survival through **copy/paste between documents**
and through **Track Changes** editing. Word's behavior there is the thing that
breaks tagged-structure designs, and a hard failure would change the whole
document contract — not just the Phase 4 robustness work.

Recommendation: add a single paste-and-track-changes probe to the Phase 1
spike. Concretely, extend the Phase 1 exit condition to:

> Structured citation identity survives an ordinary DOCX save/reopen cycle
> without an external library, **and** survives one copy/paste of a citation
> cluster into a second document and one edit made adjacent to a cluster with
> Track Changes enabled.

If that probe fails, the `citebind/1` contract needs rethinking before Phase 2,
not after Phase 3.

### 10.3 Risk flag 2 — decide what "self-contained" means for Word Online

§3 puts Word Online out of scope for v1. That is a defensible call for the
authoring path, but Word Online is the most likely place a real coauthor sits,
and coauthor handoff is the central value claim. The two readings differ in
what they commit to:

- **Readable-but-inert.** A collaborator in Word Online sees correct visible
  citation and bibliography text (it is ordinary generated text) but cannot
  insert or update citations. This is essentially free given the current design.
- **Editable there.** Requires the add-in to work in Word Online, which is a
  materially larger platform commitment.

Recommendation: state the readable-but-inert guarantee explicitly in §3 as a v1
promise, and verify it in the Phase 5 pilot handoffs. Leaving it unstated risks
a coauthor's first experience contradicting the "travels with your manuscript"
claim.

### 10.4 Otherwise

The bounded structure is sound: separate repos, DOCX-as-interface, read-only
ArtifactCert adapter deferred to Phase 6, AI subordinate and barred from
generating bibliographic identity. The §9 next action — create the repo, do
only the Phase 1 spike — is the right first move, with the §10.2 amendment.

### 10.5 Finding from ArtifactCert's DOCX layer — §5 overstates what works today

Checked ArtifactCert's actual Word handling (2026-08-29). It never opens Word:
DOCX files are treated as untrusted OPC zip packages and manipulated with
`python-docx` + `lxml`, with real Word-produced files arriving from
collaborators as opaque inputs. Four consequences for this plan:

1. **The protection boundary already exists, and is stricter than §5 assumes.**
   `src/artifactcert/docx_patch/safety.py` refuses to patch any paragraph
   containing a content control, with code `PATCH_NOT_SAFE_CONTENT_CONTROL`.
   CiteBind citation clusters will therefore be protected from ArtifactCert
   edits on day one, with no ArtifactCert change required.

2. **But §5's closing claim is false today.** "Ordinary surrounding prose can
   continue through ArtifactCert's normal A001 Apply & Verify workflow" does
   not hold: the refusal is per-paragraph, so a paragraph containing a CiteBind
   citation currently cannot have *any* of its prose patched. The real Phase 6
   work is not "teach ArtifactCert to protect CiteBind structures" — that is
   done — but "teach ArtifactCert to patch prose *around* an sdt safely."
   §5 should be amended to say so.

3. **The competitor's failure mode is already modeled, and it is fields.**
   `docx_manifest.py::paragraph_flags()` flags `citation_manager_field` for
   Zotero/EndNote/Mendeley, under the heading "why this paragraph's canonical
   text is an INCOMPLETE rendering of what a reader sees" — the cached result
   text of a field is not trustworthy canonical text. This is independent
   evidence for CiteBind's core design choice, and it hardens one rule:
   CiteBind must use content controls, never fields.

4. **The verifier shape and the no-Word workflow are both borrowable.**
   `docx_patch/regression.py` builds a before/after structural inventory
   (counts of `sdt`, `fldChar`, `instrText`, `fldSimple`, `bookmarkStart`,
   `hyperlink`, `oMath`, `drawing`) plus unexpected-paragraph-change detection
   — which is exactly the shape of the Phase 1 round-trip verifier. And
   ArtifactCert's fixtures are all generated programmatically, never real
   manuscripts, which is the rule CiteBind should inherit verbatim.

Practical effect on sequencing: Phase 1 does **not** require Word on the
development machine. It splits into a generator + verifier + one-page human
checklist built and tested on Linux, and a five-minute manual open/edit/save
performed wherever Word actually lives. See `GLM_DEV_PLAN.md`, task T-06.
