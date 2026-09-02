# T-13: which CSL processor, if any, this project should depend on

**Date:** 2026-09-02
**Status:** Investigation only. No code integrated. The decision is the driver's.
**Question:** the Phase 6 verifier must check that visible citation text matches
deterministic rendering; that check needs a renderer. Which one, in Python?

---

## 1. The options, with their actual maintenance state (checked 2026-09-02, live)

### citeproc-py — the only maintained Python CSL processor found

- **Last release:** 0.11.1, **2026-09-01** — the day before this document. Releases:
  0.7.0 (2025-02), 0.8.x (2025-03/08), 0.9.x (2026-04), 0.10.x (2026-07/08), 0.11.1
  (2026-09). Active, multiple maintainers, CI testing Python 3.10–3.14.
- **Repo state:** 32 open issues, 7 open PRs, 169 stars (citeproc-py/citeproc-py).
- **CSL support:** aims at **CSL 1.0.2** (upgrade completed in 0.10.0, 2026-07).
  Passes **about 60%** of the official `citeproc-test` suite (its own README).
  Explicitly missing: **disambiguation/year-suffix**, et-al-subsequent-min/use-first,
  collapsing, punctuation-in-quote, display.
- **Deps:** `lxml` — which we already require. Python ≥ 3.9. BSD-2-Clause.
- **API:** 0.x semver; README concedes "API is not yet stable."
- **Styles:** can load individual CSL style files (flexible loading since 0.9.0), so
  we would vendor exactly two style XMLs plus the en-US locale — not the ~10k-style
  universe.

### citeproc-rs — eliminated

Archived by Zotero on **2026-08-13**, read-only. Rust with WASM focus; no stable
Python binding. Whatever its quality, a dead repo cannot be the dependency.

### citeproc-js — not Python

The Word add-in will use it (product plan). Listed here only because the add-in's
existence is an argument in §4 below.

### pandoc — eliminated

External Haskell binary; would drag a runtime the project does not otherwise have,
in direct tension with §7's lightweight-by-omission posture.

### Hand-rolled, two styles — a real option (see §3)

## 2. Dependency cost, against §7's posture

- **citeproc-py:** one new package, whose only hard dep (`lxml`) we already carry;
  ~388 kB wheel. The real cost is not bytes — it is **surface**: a 0.x-API library
  implementing a 100-page specification, pinned by us, whose bugs in the 40% become
  our rendering behavior. It also wants a styles companion; we would vendor two
  style files instead, which caps that surface.
- **hand-rolled:** zero dependencies. The cost is likewise not bytes but **surface,
  internalized**: every formatting rule of two styles becomes our code, our tests,
  and our bug reports, forever.
- **citeproc-rs / pandoc:** not comparable (dead / a binary runtime).

## 3. Rendering one numeric and one author–year style without a CSL processor

Achievable, and honestly scoped: a numeric style (IEEE-like: `[1]` … numbered
bibliography "A. Author. Title. Journal, vol. x, no. y, pp. z, year.") and a simple
author–year style (APA-like: `(Author, year)` … "Author, A. (year). Title. Journal,
vol.(issue), pages.") are each a page or two of deterministic code over the
`citebind/1` model, fully testable against a handful of fixed examples.

**What it genuinely gives up — not a straw man:**

- **Every other style, permanently.** A journal's submission checklist that demands
  Elsevier-harvard or Vancouver-with-issues is out of reach until a processor
  arrives; "add a style" becomes a code change instead of a style file.
- **Name-part handling.** Initials disambiguation, name particles, corporate
  authors-as-authors: all manual.
- **Author–year disambiguation.** Two papers, same authors, same year → real styles
  render 2009a/2009b. A hand-rolled renderer must either implement year-suffix
  logic itself or refuse the case — and note this cuts identically into
  citeproc-py, which *also* lacks disambiguation. Neither path escapes it; the
  escape is style choice (see §4).
- **Locale/typography rules.** Punctuation-in-quote, collapsing page ranges
  (123–129 → 123–9), et-al thresholds: manual if wanted.

## 4. Recommendation, and the strongest argument against it

**Recommendation: do not integrate citeproc-py now. Render the two v1 styles
hand-rolled (Phase 3), and record citeproc-py as the designated upgrade path the
moment a third style is genuinely required.** Vendor the two style files' *examples*
as golden tests, choose styles that avoid disambiguation pressure, and keep
`selected_style` validation limited to exactly those two names.

**The strongest argument against this recommendation, argued in full:** the
Phase 6 verifier's citation check — "visible text matches deterministic rendering"
— becomes **circular** with a hand-rolled renderer. Our renderer would be the
*only* implementation of our rendering: if it formats wrong, the document will
match the wrong formatting forever, every check passes, and nothing in the system
can ever notice. citeproc-py's bugs are bounded by an external, standardized test
suite and a public specification; ours would be bounded by our own imagination.
This is the verifier-independence principle the project applies everywhere else —
the recorder fetches from the same code path production uses precisely so two
implementations cannot drift — and a hand-rolled renderer *is* a second
implementation: one in the add-in (citeproc-js), one in Python (ours), checking
each other with no shared ground truth. A rendering disagreement between
citeproc-js and our Python code would be reported as a document defect when it is
in fact a renderer defect — a false alarm that lands on a researcher. The honest
form of this argument is that the choice is not "dependency vs no dependency" but
"whose bugs do we inherit": an external processor's documented, test-suite-bounded
bugs, or our own undocumented ones. If the driver weighs long-term verification
independence over §7's posture, citeproc-py with two vendored styles and a pinned
version is the defensible pick, accepting the 0.x API and the disambiguation gap
(as long as the author–year style is chosen to need none).

---

**Also reported, per the note:** the placeholder `mailto:example@example.org` in
`transport.py` is flagged, not invented — the reachable address is the user's to
give, and both polite-pool routing and future Crossref record fetches want it.
