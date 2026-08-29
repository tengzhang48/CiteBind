# Plan for GLM 5.3-flash: CiteBind Phase 0–1

**Date:** 2026-08-29
**You are:** the implementer.
**Someone else is:** the driver (reviews your work, runs the gates, owns git pushes and all
architecture decisions).
**Your scope for this document:** Phase 0 and Phase 1 only. Nothing else.

Read this file completely before writing any code. It contains facts you cannot infer from the
repository, and rules whose violation means the work gets reverted rather than reviewed.

---

## 1. What CiteBind is, in three sentences

CiteBind is a Word add-in that stores a manuscript's verified bibliographic records *inside the
DOCX itself*, in a versioned custom XML part, and renders citations and the bibliography
deterministically from that embedded data through tagged content controls (`w:sdt`). The point is
that the reference library travels with the manuscript: no external database, no account, no sync,
and a coauthor who has never installed CiteBind still sees correct text.

Read [`CiteBind_PLAN_2026-08-29.md`](CiteBind_PLAN_2026-08-29.md) in this same folder for the full
product plan. This document is the *execution* plan for the first two phases.

---

## 2. Facts about this machine you cannot infer

| Fact | Consequence for you |
| --- | --- |
| Linux VM (Jetstream), no Microsoft Word, no LibreOffice | You cannot open, save, or round-trip a DOCX through Word. Do not write code that assumes you can. Do not add a LibreOffice dependency. |
| Python 3.13.9, `python-docx` 1.2.0, `lxml` 6.1.1, `pytest` 9.1.1 | This is your stack for Phase 0–1. All of it is already installed. |
| Node v18.19.1 / npm 9.2.0 | **Too old** for current Office add-in tooling (wants Node 20+). Irrelevant for Phase 0–1 — you write no JavaScript. Flag it to the driver rather than upgrading anything. |
| Repo is at `/media/volume/cpu-vm/CiteBind`, symlinked as `~/CiteBind` | Work in the real path. |
| A sibling project, ArtifactCert, lives at `/media/volume/cpu-vm/ArtifactCert` | **Read-only reference.** See §3. You must not modify a single byte of it. |

### The Word problem, and how it is actually solved

Phase 1 asks whether tagged citations survive a real Word save/reopen. You cannot run that test
here. This is not a blocker, because ArtifactCert already solved the same problem, and the answer
is: **never open Word at all.**

ArtifactCert manipulates DOCX files purely as OPC zip packages via `python-docx` + `lxml`, and
obtains real Word-produced files by receiving them from collaborators as opaque inputs. You do the
same. Concretely, Phase 1 splits into two halves:

- **Everything you build (on Linux):** generate the fixture DOCX, insert the structures, inspect a
  returned DOCX, and diff before-vs-after. All of this is fully testable here.
- **One manual step someone else performs (on a machine with Word):** open the fixture, do a short
  scripted checklist, save, and hand the file back.

Your Phase 1 deliverable is therefore a *round-trip kit*: a generator, a verifier, and a one-page
human checklist. You never need Word to build or test any of it.

---

## 3. What ArtifactCert already tells us — read this before designing anything

The driver read ArtifactCert's DOCX layer. Four findings change what you should build. **Do not
re-derive these by reading ArtifactCert yourself; the summary below is sufficient, and browsing
that repo costs context you need for your own work.**

**3.1 — Hardened, fail-closed OOXML parsing is the house style.**
`src/artifactcert/opc_xml.py` parses every package part with `resolve_entities=False`,
`load_dtd=False`, `no_network=True`, `recover=False`, `huge_tree=False`, and then *additionally*
refuses any document containing a DOCTYPE or entity reference — because entity expansion would make
the parsed evidence differ from the bytes actually present. Adopt this posture. A DOCX from a
collaborator is untrusted input.

**3.2 — `w:sdt` is already treated as protected structured content.**
`src/artifactcert/docx_patch/safety.py` refuses to patch any paragraph containing a content
control, with the refusal code `PATCH_NOT_SAFE_CONTENT_CONTROL`. This is excellent news for
CiteBind's protection story — but it also means the product plan's claim that *"ordinary
surrounding prose can continue through ArtifactCert's normal Apply & Verify workflow"* is **false
today**: a paragraph containing a CiteBind citation currently cannot have any of its prose patched.
That is a Phase 6 problem, not yours. Do not attempt to fix it. Just do not design as though
prose-around-a-citation already works.

**3.3 — The incumbents' failure mode is already modeled, and it is fields.**
`src/artifactcert/docx_manifest.py::paragraph_flags()` flags paragraphs as `field`,
`citation_manager_field` (Zotero/EndNote/Mendeley), `math`, or `content_control`, documented as
"why this paragraph's canonical text is an INCOMPLETE rendering of what a reader sees." Reference
managers use Word *fields*, whose cached result text is not part of trustworthy canonical text.
**CiteBind must use content controls (`w:sdt`), never fields.** This is the central design
distinction; do not let it drift.

**3.4 — There is a ready-made shape for your verifier.**
`src/artifactcert/docx_patch/regression.py` builds a before/after structural inventory counting
`fldChar`, `instrText`, `fldSimple`, `bookmarkStart`, `hyperlink`, `oMath`, `sdt`, and `drawing`,
then reports unexpected paragraph changes. Your round-trip verifier (T-05) is the same idea
specialized to CiteBind structures. Build your own — do not import from ArtifactCert, and do not
create a dependency between the two repos.

**3.5 — Fixtures are generated, never borrowed.**
`tests/docx_fixtures.py` in ArtifactCert opens with: *"Everything here is generated
programmatically; no private manuscript or publisher proof is ever used as a development
fixture."* Same rule here, absolutely. There are real unpublished manuscripts on this machine.
None of them enter this repository, in any form, ever.

---

## 4. How we work together

One task at a time, in order. For each task:

1. You read the task brief in §6.
2. You write the tests **first**, and run them to watch them **fail** — a test you never saw fail
   proves nothing. Paste the failing output in your report.
3. You implement until they pass.
4. You run the **whole** suite, not just your new tests.
5. You report back in the format in §5, pasting real terminal output.
6. The driver gates: reviews the diff, re-runs the suite independently, and either accepts the
   task or returns it with specifics.
7. Only after acceptance do you start the next task.

Rules about this loop:

- **Do not batch tasks.** Finishing T-02 and T-03 in one go makes the diff unreviewable and both
  get returned.
- **Do not self-certify.** "Tests pass" without pasted output is treated as unverified.
- **Two failed attempts on the same task = stop and report.** Do not keep trying. Describe what you
  tried, what the error was, and what you think the real obstacle is. Escalation is a valid, useful
  outcome; a fourth silent rewrite is not.
- **Do not make architecture decisions.** If a task seems to require one (a new dependency, a
  schema change, a different file layout), stop and ask. Proposing is welcome; deciding is not.

---

## 5. Report format

After every task, report exactly this:

```
TASK: T-0N
STATUS: complete | blocked | needs-decision

FILES CHANGED:
  <path>  (+N/-M)

TESTS ADDED: <names>

RED PROOF (before implementing):
  <pasted pytest output showing the new tests failing, with the assertion messages>

GREEN PROOF (full suite, after implementing):
  <pasted pytest tail: "N passed in Xs">

DECISIONS I MADE: <anything you chose that the brief did not specify>
SURPRISES: <anything that did not behave as the brief predicted>
NOT DONE: <anything in the brief you did not deliver, and why>
```

`NOT DONE` being non-empty is fine and honest. `NOT DONE` being empty when it should not be is the
one thing that will get your work distrusted wholesale.

---

## 6. Task ledger — Phase 0 and Phase 1

Work in a branch: `git checkout -b phase1-spike`. Commit after each accepted task. **Never push,
never force, never rewrite history** — the driver owns the remote.

### T-01 — Repository scaffold

**Goal:** a working, installable, testable Python package skeleton. No CiteBind logic yet.

**Deliver:**
- `pyproject.toml` — package name `citebind`, `src/` layout, deps `python-docx`, `lxml`; dev dep
  `pytest`. Requires Python ≥3.11.
- `src/citebind/__init__.py` with `__version__`.
- `tests/test_scaffold.py` — one test importing `citebind` and asserting `__version__` is a
  non-empty string.
- `pytest.ini` or `[tool.pytest.ini_options]` pointing at `tests/`.

**Acceptance:** `pip install -e .` succeeds; `pytest` collects and passes; `python -c "import
citebind"` works from a different directory.

**Do not:** add a CLI framework, a config system, logging infrastructure, or a `utils` module.

---

### T-02 — The `citebind/1` schema and data model

**Goal:** the document contract, as a validating schema plus a Python model, with nothing embedded
in a DOCX yet.

**Deliver:**
- `src/citebind/schema.py` — the `citebind/1` structure as documented in §4 of the product plan:
  `schema_version`, `selected_style`, `references` (each with DOI and/or PMID, title, authors,
  journal, year, optional volume/issue/pages, `metadata_source`, `retrieved_at`), and
  `citation_clusters` (each with ordered reference IDs and optional locator/prefix/suffix).
- `src/citebind/model.py` — dataclasses `Reference`, `CitationCluster`, `CiteBindDocument`, with
  `to_dict()` / `from_dict()`.
- `tests/test_schema.py`.

**Acceptance — the validator must accept 3 well-formed documents and reject each of these
distinctly, with a named error, not a generic one:**
1. missing `schema_version`;
2. two references sharing an ID;
3. a citation cluster referencing a reference ID that does not exist;
4. a reference with neither DOI nor PMID;
5. an unknown top-level key (forward-compat must be explicit, not silent).

**Note:** a reference ID appearing in no cluster is **valid** at this layer (an uncited reference
is a real intermediate state while drafting). Whether it is *reportable* is a verifier question,
T-05, not a schema question.

**Do not:** add provenance digests, permissions, approval states, or an event ledger. The product
plan forbids them in v1 explicitly.

---

### T-03 — Embed and recover the custom XML part

**Goal:** write the `citebind/1` payload into a real DOCX and read it back out.

**Deliver:**
- `src/citebind/part.py` — `embed(docx_path, doc: CiteBindDocument, out_path)` and
  `extract(docx_path) -> CiteBindDocument | None`. Writes `customXml/item1.xml`, its
  `itemProps1.xml` with a stable datastore GUID, the `[Content_Types].xml` overrides, and the
  document-level relationship.
- Parse every part with the hardened settings from §3.1. Refuse DOCTYPE and entity references.
- `tests/test_part.py`.

**Acceptance:**
1. After `embed`, `zipfile.ZipFile(out).namelist()` contains the custom XML part.
2. `extract` returns a model equal to the one embedded.
3. `python-docx` can still open the output and read its paragraph text.
4. **The load-bearing one:** open the embedded file with `python-docx` and `.save()` it to a new
   path — a rewrite of the whole package — then `extract` again and assert the payload survived
   *and is byte-identical*. python-docx is not Word, but it is a real, independent repackager, and
   a payload that does not survive it will not survive Word either.
5. A DOCX with no CiteBind part returns `None`, and does not raise.
6. A DOCX whose custom XML part contains a DOCTYPE is **refused** with a named error.

---

### T-04 — Insert tagged content controls

**Goal:** put the visible, tagged structures into the document body.

**Deliver:**
- `src/citebind/controls.py`:
  - `insert_citation(paragraph, cluster_id, visible_text)` — an **inline** `w:sdt` whose
    `w:sdtPr/w:tag` is `citebind:citation:<cluster_id>`, with an `w:alias`, wrapping a run holding
    the rendered text.
  - `insert_bibliography(document, entries)` — a **block-level** `w:sdt` tagged
    `citebind:bibliography`.
  - `find_controls(docx_path)` — return every CiteBind-tagged control with its tag, kind
    (citation/bibliography), and current visible text.
- `tests/test_controls.py`.

**Acceptance:**
1. A generated document contains exactly the expected number of `w:sdt` elements.
2. `find_controls` recovers every tag inserted, in document order.
3. Visible text is readable by `python-docx` as ordinary paragraph text (this is the
   coauthor-without-CiteBind guarantee — assert it, do not assume it).
4. The inline citation control sits **inside** a paragraph, and the bibliography control sits at
   **body** level. Assert on the actual XML parent, not on rendered text.
5. Round-trip through `python-docx` `.save()` preserves all tags (same probe as T-03 acceptance 4).

**Do not:** render citation text from CSL yet. Visible text is a caller-supplied string in this
task. Deterministic rendering is Phase 3.

---

### T-05 — Structure verifier and round-trip differ

**Goal:** the tool that answers "did the structures survive?" — the half of Phase 1 that gives the
manual Word step its meaning.

**Deliver:**
- `src/citebind/verify.py`:
  - `inspect(docx_path) -> Report` — schema version, reference IDs, cluster IDs, control tags,
    a structural inventory (`sdt` count, and `fldChar`/`instrText`/`fldSimple` counts so we can
    prove we introduced **no fields**), plus findings: cluster with no matching reference,
    duplicate IDs, control tag with no cluster in the payload, reference cited nowhere.
  - `diff(before_path, after_path) -> DiffReport` — what was lost, gained, renamed, or altered.
- A minimal CLI: `python -m citebind inspect <docx>` and `python -m citebind diff <a> <b>`.
- `tests/test_verify.py`.

**Acceptance — build synthetic "damaged" fixtures by editing the XML directly, and prove each
damage mode is detected and named *distinctly* (not all reported as one generic "broken"):**
1. custom XML part removed, controls intact;
2. controls stripped, payload intact;
3. a control's tag renamed to something outside the `citebind:` namespace;
4. a reference deleted from the payload while its cluster remains;
5. visible text edited by hand so it no longer matches the payload;
6. nothing damaged — reports clean, with **zero** findings.

Case 6 is not filler. A verifier that cannot say "this is fine" is a verifier nobody will trust
when it says "this is broken."

**Design rule, from a bug that shipped in ArtifactCert:** do not hand-maintain a list of finding
codes or damage kinds in more than one place. Make the set exhaustive by construction, and add a
test that fails when a new kind is unclassified. A hand-written list that nobody revisits when a
member is added is exactly how a real finding once became silently invisible in that project.

---

### T-06 — The Word round-trip kit

**Goal:** make the manual Word step a five-minute, unambiguous, hard-to-do-wrong chore, and make
its result machine-checkable.

**Deliver:**
- `python -m citebind make-spike` → writes `spike/spike_v1.docx` containing: two paragraphs of
  ordinary prose; one hard-coded, real, DOI-resolved reference in the payload (use a genuine open
  DOI — e.g. a well-known open-access paper — hard-coded, **no network call**); two citation
  controls for it in different paragraphs; one bibliography control.
- `spike/SPIKE_INSTRUCTIONS.md` — a numbered checklist for the human, **one page maximum**,
  covering six probes:
  1. open in Word, change nothing, save, close, reopen;
  2. type a sentence of ordinary prose in an untouched paragraph, save;
  3. copy a citation control and paste it elsewhere **in the same document**;
  4. copy a citation control and paste it **into a brand-new blank document**, save that separately;
  5. with **Track Changes on**, edit the prose immediately adjacent to a citation control, save;
  6. save-as `.docx` under a new name and return every file produced.
- `python -m citebind check-spike <returned.docx> [...]` → a PASS/FAIL table, one row per probe,
  naming exactly what survived and what did not.
- `tests/test_spike.py` — tests the generator and the checker against synthetic stand-ins for each
  outcome. You cannot test the Word step; you *can* test that the checker correctly reads a file in
  which each probe passed or failed.

**Acceptance:** the fixture opens cleanly in `python-docx`; the instructions fit on one page and
name no CiteBind internals; `check-spike` produces a per-probe verdict, never a single blanket
"OK"; and the generator uses **no network**.

**Why probes 3–5 matter:** they are pulled forward from Phase 4 deliberately. If content controls
do not survive cross-document paste or Track Changes, the `citebind/1` contract itself needs
rethinking — and that is far cheaper to learn now than after Phase 3 is built on top of it.

---

## 7. Standing rules

**Product invariants — these outlive Phase 1:**

1. **No model-generated bibliographic identity, ever.** No DOI, PMID, author list, year, or journal
   name may originate from a language model. In Phase 0–1 every reference is hard-coded from a real
   source; from Phase 2 it comes from Crossref or PubMed. If you find yourself typing plausible
   metadata from memory, stop — that is the single failure this product exists to prevent.
2. **Content controls, never fields.** See §3.3.
3. **Visible text stays readable without CiteBind.** A coauthor who never installs it must see
   correct, ordinary text.
4. **The document is self-contained.** No external store, no network at read time, no account.
5. **No speculative schema fields.** Add a field when a reproduced failure requires it, not when
   it seems likely to be useful.

**Process rules:**

6. **Never modify `/media/volume/cpu-vm/ArtifactCert`.** Read-only reference. Not one byte, not
   even a typo fix, not even a test.
7. **Never import from ArtifactCert** or create a dependency between the repos. The DOCX is the
   only interface between these projects.
8. **No real manuscripts as fixtures.** Generate everything. There are unpublished papers on this
   machine; none of them touch this repo.
9. **No network in tests.** Not even in Phase 2 — record fixtures instead.
10. **Run it, don't read it.** Do not report that code works because it looks correct. In
    ArtifactCert, a DOCX engine was reviewed, praised, and green — and could not execute at all,
    because a name was unimported on every return path. It had been read rather than run.
11. **When you add a check, trace who already calls the thing you are checking.** A new guard
    changes the meaning of every call site above it.
12. **Record deliberate losses in the test, inline.** If you knowingly give up a case, write down
    why, next to the assertion, so nobody "fixes" it back later.

---

## 8. Explicitly not your job right now

Do not build, and do not scaffold in anticipation of: Crossref or PubMed lookup (Phase 2); any CSL
processor or citation rendering (Phase 3); the Office.js/TypeScript add-in (later); any ArtifactCert
integration (Phase 6); a UI of any kind; a config system; a plugin architecture; a database;
async anything; or a `utils` module.

If a task in §6 seems to need one of these, it does not — re-read the brief, and if it still seems
to, stop and ask.

---

## 9. First action

Confirm you have read this file by reporting, before any code:

- the branch you created;
- your one-line statement of what Phase 1 proves;
- the single thing in this document you think is most likely to be wrong.

Then start T-01.
