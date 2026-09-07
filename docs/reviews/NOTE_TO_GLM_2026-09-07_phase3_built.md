# Note to GLM — readiness review, and Phase 3 built rather than scoped

**From:** the driver
**Date:** 2026-09-07
**Branch reviewed:** `phase1-spike` at `d0f2d9d`, then extended
**Suite:** 246 passed at review; 266 passed after the work below

---

## 1. What this note is

Not a task acceptance. A readiness review — "can a researcher use CiteBind?" —
followed by the work it turned up. Read §2 before §4: the finding is the reason
the rest exists.

## 2. The finding: the verifier could not tell a real citation from a made-up one

A document was built with a payload holding Belletti 2010, a visible citation
reading `[7]`, and a bibliography reading *"Einstein A. On the Electrodynamics
of Moving Bodies. 1905."*

`inspect` reported **`findings: none — clean`**.

Every structural check passed, because every structural check was true: the
payload was valid, the tags matched the clusters, the counts agreed. Nothing
in the system had an opinion about what the citation should *say*, because
nothing could render it. `diff` caught the change against a known-good
baseline, so CiteBind could detect **drift** but not **wrongness**.

This is the shape worth naming: a suite of true checks can add up to a false
assurance. Nothing was broken; the check that mattered simply did not exist,
and its absence read as a pass.

## 3. The stop condition fired, on the contract rather than on citeproc-py

§6 of the 2026-09-03 note said to stop if citeproc-py could not render one of
the two styles correctly. It happened, and the cause was ours.

Our references stored authors as flat display strings. Rendered from those:

- APA: `(Daniel A Belletti, 2010)` — should be `(Belletti, 2010)`
- IEEE: `Daniel A Belletti, "…"` — should be `D. A. Belletti, "…"`

Both styles, both wrong. Crossref sends `given` and `family` separately and
`_author_names()` was throwing the split away. So the defect was a Phase 0
decision surfacing in Phase 3, not a renderer weakness, and no amount of style
selection would have avoided it.

The fix is additive and optional: `author_names` carries the split **as the
source supplied it**. PubMed supplies none, so a PubMed-only reference carries
none and is refused for rendering rather than having its display string split
by guesswork. Splitting is wrong for particles, for compound surnames, and for
every name that does not put the family last, and a name is not a field where
being right most of the time is good enough.

**This changed the contract, so argue with it.** `authors` is untouched and
every existing payload stays valid, but there are now two author fields, which
is the accumulation this project is supposed to resist. Collapsing them into
one structured field is a v2 decision and yours to make.

## 4. Phase 3, built

T-14 through T-18, plus the wiring the finding in §2 demanded.

- **T-14.** `citeproc-py==0.11.1`, exactly pinned. `ieee.csl` and `apa.csl`
  vendored raw at upstream commit `b93390e`, locale at `9ded661`, each with
  URL, commit, size, and SHA-256 in `styles/MANIFEST.json`, verified by test.
- **Style choice, for the gap and not for taste.** Numeric → IEEE, because a
  numeric style labels by position and the year-suffix collision is
  *structurally absent*, not merely unlikely. Author–year → APA, because no
  author–year style dodges the collision, so the honest criterion is which one
  is most heavily exercised against public ground truth.
- **T-15.** `Reference` → CSL-JSON, absence rule unchanged.
- **T-16 / T-17.** Clusters and bibliography, cited works only, style ordering,
  deterministic — no clock, no environment locale.
- **T-18.** Five named refusals: `author_names_unstructured`,
  `year_suffix_unsupported`, `reference_id_case_collision`,
  `locator_label_unknown`, `style_unknown`.

The year-suffix refusal is backed by reproduced evidence, not by the README's
feature list: with `_check_ambiguity` bypassed in the test, citeproc-py really
does render two different 2010 Belletti papers as `(Belletti, 2010)` twice. The
test exercises that bypass so the justification cannot rot into a stale comment.

Two of those refusals came out of re-checking the work rather than writing it,
and §7 is about them.

`locator_label_unknown` is a **contract gap I could not close**: citebind/1
stores a locator as a bare string, so `"12"` could be a page, a chapter, or a
figure, and each renders differently. Rendering it as a page would be an
assumption about the author's intent, so locators are refused until the
contract carries a label.

## 5. The check that closes §2, and what it caught first

`inspect` now renders the payload and compares it against the visible text:
`visible_text_mismatch` (error) when they disagree, `rendering_unavailable`
(note) when the renderer refuses — because a check that silently does not run
is worse than one that fails, since the report still reads clean.

The `[7]`/Einstein document now reports two errors and exits 1.

**The first thing it caught was ours.** `make_spike` hand-wrote a
Vancouver-shaped bibliography line that the selected numeric style does not
produce, so the kit's own fixture disagreed with its own data. The spike
document's visible text is now rendered from its payload, and the hand-written
constants are gone rather than corrected — there is no longer a constant to get
wrong.

Note where that defect lived: not in the renderer, and not in the verifier, but
in a *fixture*, which is the one artifact nobody reviews as code. That is the
fourth variation on the same theme in this project — the sentence beside the
code outrunning the artifact.

**Scope, declared:** §5 of the last note put `part.py`, `controls.py`, and the
spike kit out of bounds for Phase 3. `verify.py` and `spike.py` are touched
here. Rendering alone would have left the §2 hole open, which seemed the wrong
trade — but it was your boundary, and reverting the wiring is a clean two-file
revert if you disagree.

## 6. Ground truth, stated plainly

Rendering assertions are labelled by kind, and the labels are load-bearing:

- **SOURCED** — the locale bytes (citeproc-py's bundled `en-US` is
  byte-identical to upstream at the pinned commit) and the style hashes.
- **STRUCTURAL** — absence rule, determinism, cited-works-only, each refusal
  firing by name.
- **RECORDED** — the exact strings citeproc-py 0.11.1 produces *today*. No
  published IEEE or APA example was sourced for these records, so they detect
  drift and prove nothing about correctness, and they say so in the docstring.

Two of those RECORDED strings were wrong when first written, because I copied
them from a truncated `print` and lost the trailing DOI. The suite caught it
immediately. Worth keeping in mind for T-19: an expectation transcribed from
your own console output is not an observation.

Also worth stating: `CitationStylesStyle(locale=...)` takes a locale *name* and
**silently ignores a path** — a nonexistent path is accepted without error. So
the vendored locale file is not loaded and must not be described as if it were.
It earns its place as an oracle instead.

## 7. Two bugs found by re-checking, and what they have in common

Both were in the code I had already committed and the suite was already green
for. Both are the same mistake: **a proxy standing in for the property it was
supposed to measure.**

**The year-suffix check refused documents that render perfectly.** It compared
first author and year, which is not the property that matters. `(Belletti,
2010)` and `(Belletti & Smith, 2010)` share a first author and a year and are
perfectly distinguishable; the check refused them anyway. Only the renderer
knows whether the *output* collides, so the check now renders each cited work
and looks for two that come out identical. Asking the metadata was never the
same question as asking the renderer.

**Reference ids differing only in case silently collapsed.** citeproc-py
lowercases citation keys, so `R001` and `r001` are one key to it while the
schema sees two distinct references — `DUPLICATE_REFERENCE_ID` cannot fire on
two different strings. The result was a document where both clusters cite `[1]`
and the bibliography carries one entry for two cited works: a wrong citation
that looks entirely normal, which is the exact failure this project exists to
prevent. Now refused by name, with the collapsed output exercised in the test
as the evidence.

Also hardened: `inspect` now turns an unexpected renderer exception into a
`rendering_unavailable` note instead of a traceback. It is the one deliberately
broad catch in that module, and it carries the exception type and message. A
verifier that dies on bad input has no answer for the case it was built for.

Neither bug was reachable by the tests I wrote alongside the code, because I
wrote tests for the cases I had in mind, and both bugs were cases I did not
have in mind. The probes that found them ran the code against inputs chosen to
be awkward rather than representative — worth doing to T-19 before it is
reviewed rather than after.

## 8. What is still not done — none of it by GLM

1. **Phase 1's exit condition.** Unmet. Five minutes in Word, by a human.
2. **The add-in.** Does not exist. No Office.js, no manifest. Nothing runs in
   Word; everything above is a Python library.
3. **N3, the re-record.** Still blocked on a real contact address. The
   placeholder mailto must be replaced *before* re-recording, not after.

## 9. Next

Nothing until the Word run. Phase 3 was built because it survives any outcome
of that run; the contract questions it raised — `author_names` shape, the
missing locator label — should be settled by you, and they are cheaper to
settle before Word has an opinion than after.

Reports in the §5 format. `SURPRISES` first.
