# Note to GLM — you are clear to proceed

**From:** the driver
**Date:** 2026-08-31
**Supersedes:** the gating cadence only. Every standing rule in `docs/GLM_DEV_PLAN.md` §7 still
applies, unchanged.

Read `NOTE_TO_GLM_2026-08-31_T06_round2.md` first if you have not. This note says what happens
after it, and removes the wait.

---

## 1. What changed about how we work

Until now you stopped after each task for me to gate. Don't wait any more. Do R1 and R2, then keep
going into Phase 2 through the ledger in §3, committing per task and reporting per task as before.
I will review in batches, behind you rather than in front of you.

What has not changed: **you still do not make architecture decisions, and you still stop on the
conditions in §4.** Proceeding faster is not the same as deciding more.

---

## 2. Why you are not waiting for the Word run — and what that costs

Phase 1's real answer needs a human to open `spike_v1.docx` in Word for five minutes. That is
blocked on a machine none of us has here, on someone else's schedule. You should not idle against
it.

But be clear-eyed about the tradeoff, because the plan was deliberately risk-first and this is a
departure from it: **anything you build now that assumes the `citebind/1` document contract holds is
built on an unvalidated foundation.** If content controls turn out not to survive a Word
cross-document paste or a Track Changes edit, the contract changes and that work is rework.

So Phase 2 is scoped here to the layer that survives *any* outcome of the Word run. Turning an
identifier into verified, normalized bibliographic metadata is worth exactly as much if the
document contract has to be redesigned tomorrow. Getting that metadata *into a DOCX* is not — you
already built that in T-03, and it is the part under question.

Concretely: **build the resolver, not more document plumbing.**

---

## 3. Phase 2 ledger — reference acquisition

Same working style: one task at a time, tests first, watch them fail, full suite after, report in
the §5 format. Stay on `phase1-spike` (the name is now wrong; leave it — I will handle branches).

### T-07 — Identifier normalization

Pure functions, no network, no I/O. `normalize_doi`, `normalize_pmid`, and a `parse_identifier`
that decides which kind a string is, or refuses.

Real inputs to handle, because researchers paste all of these: bare `10.2147/prom.s8896`; the
`https://doi.org/…` and `http://dx.doi.org/…` forms; a `doi:` prefix; uppercase (DOIs are
case-insensitive in the suffix — decide the canonical form and *state it in a docstring*, because
a case-folding choice determines whether duplicate detection works); a trailing period from a
pasted sentence; surrounding whitespace and zero-width characters; a PMID with a `PMID:` prefix; a
PMCID (`PMC1234567`) which is **not** a PMID and must be refused as its own named case, not
silently treated as one.

**Acceptance:** each malformed class refuses with its own name. Two spellings of the same DOI
normalize equal. Do not write a validator that accepts anything shaped vaguely like a DOI —
`10.` followed by a registrant and a slash is the structural floor.

### T-08 — Transport seam and recorded fixtures

**This one has an architecture decision in it, so I am making it rather than leaving it to you:**
one small transport interface with two implementations — a real HTTP one and a replay one that
reads archived JSON from disk. Every resolver takes the transport as a parameter. Tests use replay
only. There is no network anywhere in the suite, and no monkeypatching of `socket` to enforce it at
the resolver layer — the seam is the enforcement.

Recording fixtures is the one place a live request is allowed, and it is a deliberate, separate act:
a small script that fetches one record and writes the **raw, unmodified** response next to the
existing `spike/reference_source_crossref.json`. Commit the raw response. That file is the
provenance for every assertion downstream, and it is what makes invariant 1 checkable by someone
who does not trust you. Record at least: the existing DOI, one record with missing optional fields
(no volume/issue/pages), one with many authors, and one PubMed record.

**Acceptance:** the replay transport is used by every test; malformed JSON, an HTTP error status, a
timeout, and an empty result set each produce a distinct named error. Add these input classes to
`tests/test_input_gauntlet.py` rather than starting a new file — that is what it is for.

### T-09 — Crossref resolver

DOI → `Reference`, mapping Crossref's fields onto the `citebind/1` model.

The whole risk here is one thing: **absent metadata must stay absent.** Crossref records are
routinely incomplete. A missing journal name, year, or page range is a missing field, never an
inferred one, never a plausible reconstruction, never a blank string standing in for a real value.
`metadata_source` records that Crossref said it, and `retrieved_at` when.

**Acceptance:** the archived record for `10.2147/prom.s8896` maps to the exact `Reference` already
hard-coded in `spike.py` — that existing constant becomes an independent oracle for the resolver,
which is the closest thing you have to a second opinion. The incomplete-record fixture yields a
`Reference` with those fields genuinely unset, and a test asserts they are unset rather than empty.

### T-10 — PubMed resolver

PMID → `Reference`, same shape, same absence rule, `metadata_source` distinguishing PubMed from
Crossref.

### T-11 — Two sources, one truth, no silent merge

When both sources answer for the same work, return a structured comparison — per field, what each
source said, and whether they agree. Disagreement is **reported**, never resolved by preference,
averaging, or picking the longer string.

**Acceptance:** a fixture pair disagreeing on year and on page range produces a per-field conflict
naming both values and both sources. Nothing in this module chooses. If you find yourself writing a
precedence rule, stop — that is a product decision and it is mine.

### T-12 — Title search returns candidates, never a selection

An exact-title query returns an ordered candidate list, each carrying its identifier, metadata, and
source. The API must make it impossible to obtain a `Reference` from a title query without an
explicit selection step. Not "defaults to the first result" — impossible.

**Acceptance:** a test asserting that a single-candidate result *still* requires selection. One
candidate is not a confirmation; it is a candidate, and the human confirming it is the only thing
standing between this product and the failure it exists to prevent.

---

## 4. Stop and report instead of deciding

Stop if any of these happen. A stop is a successful outcome, not a failure.

1. **You need a precedence rule** between Crossref and PubMed, or between candidates.
2. **You need a new field in `citebind/1`.** The schema is frozen until a reproduced failure
   requires a change.
3. **A task needs more than two attempts.** Same rule as before: describe what you tried, what the
   error was, and what you think the real obstacle is.
4. **You conclude a task in §3 is wrong**, or that its acceptance criterion cannot be met as
   written. Say so; do not quietly build something adjacent.
5. **You want to touch anything under the T-03/T-04 document contract**, or
   `SPIKE_INSTRUCTIONS.md`. That surface is frozen pending the Word run.

---

## 5. The rules that do not bend

From `GLM_DEV_PLAN.md` §7, and worth restating because Phase 2 is the first time they can actually
be violated at scale:

- **No model-generated bibliographic identity.** Every DOI, PMID, title, author, journal and year
  in a test or fixture comes from an archived response, not from you. This is the one rule whose
  violation invalidates the project rather than a task, and Phase 2 is where the temptation is
  real — a fixture is faster to type than to record.
- **No network in tests.** The transport seam, not a mock of a socket.
- **Content controls, never fields.**
- **No real manuscripts as fixtures.** Generate, or use archived public records.

---

## 6. What I will do

Review in batches behind you, and re-probe rather than re-read — you have seen how that goes, and
two rounds of it have made this code meaningfully better than either of us would have gotten alone.
I will also push this branch and get the Word run scheduled; neither is your problem.

One request. In each report, `SURPRISES` is still the field I read first, but add one line I will
now read second: **the thing you built that you would most like a second pair of eyes on.** You
have been right about where the weak spots were — the `item1.xml` collision and the CLI guard gaps
both came from you, not from me — and it is cheaper for you to point at them than for me to find
them.

Go.
