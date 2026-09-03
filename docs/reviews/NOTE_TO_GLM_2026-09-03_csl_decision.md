# Note to GLM — T-13 accepted, the decision made, Phase 3 scoped

**From:** the driver
**Date:** 2026-09-03
**Branch reviewed:** `phase1-spike` at `86977b1`
**Suite:** 246 passed in 6.53s, re-run independently.

---

## 1. N1 and N2 accepted

The recorder runs on `HttpTransport`, the duplicate `fetch()` is gone, there is one `USER_AGENT`,
and the stray root manifest is deleted. You **flagged** the placeholder mailto rather than
inventing one — `FIXME(driver)` in `transport.py`. That was the right instinct and I want it named:
inventing a plausible contact address is the same reflex as inventing plausible metadata, and you
declined it without being told twice. I will get the real address.

## 2. T-13 accepted — and audited

Every checkable claim in `docs/CSL_PROCESSOR_RESEARCH.md` was verified against live sources, not
read:

- 0.11.1 released 2026-09-01, 0.10.0 on 2026-07-07, `requires_python >=3.9`, `lxml` the only hard
  dependency, 388 kB wheel — all exact against PyPI.
- 169 stars, 32 open issues, 7 open PRs — exact. GitHub reports a *combined* `open_issues_count`
  of 39; you separated them correctly, which is the specific place that number is usually quoted
  wrong.
- BSD-2-Clause — verified from the LICENSE text. GitHub's API reports `NOASSERTION`, so your
  reading is more accurate than the API's.
- CSL 1.0.2, "about 60%" of the citeproc-test suite, disambiguation/year-suffix among the missing
  features, "the API is not yet stable" — all four verbatim from the README.
- **citeproc-rs archived on 2026-08-13.** I went after this one hardest, because a precise date
  attached to a dead repository is a classic shape for a fabricated fact: `archived_at` is null and
  the last push was 2024-08-06. It is correct — the repo's `updated_at` is `2026-08-13T14:29:56Z`.
  You sourced a real date from a non-obvious field and did not round it off or hedge it.

A research document is the easiest place in this project to produce confident, checkable, wrong
statements, and nothing in the test suite would have caught one. Yours had none. That is the
standard; expect the same audit on the next one.

## 3. The decision: citeproc-py

**You argued yourself out of your own recommendation, and the counter-argument wins.**

You recommended hand-rolling two styles. Then you stated the case against it in full, as the task
required, and that case is decisive: a hand-rolled Python renderer would be the *only*
implementation of our own rendering, which makes the Phase 6 check — "visible text matches
deterministic rendering" — circular. Render it wrong once and the document matches the wrong
rendering forever, every check passing, nothing in the system able to notice. Meanwhile the add-in
runs citeproc-js, so we would hold two implementations with no shared ground truth, and every
disagreement between them would reach a researcher as a document defect when it is a renderer
defect.

For a project whose entire thesis is that a claim must rest on evidence that could have falsified
it, a renderer that grades its own output is not acceptable. citeproc-py and citeproc-js both aim
at one public specification and one public test suite. That shared ground truth is the whole
purchase.

**Decision: depend on citeproc-py, pinned, with two vendored style files.** Recorded here so it can
be argued with later: the honest cost is that a processor passing about 60% of the official suite
is a weak oracle, and we are buying its bugs. We are buying them because they are *external,
documented, and bounded by a public test suite*, where ours would be bounded by our own
imagination.

Writing the strongest argument against your own recommendation is what made this decidable. Keep
doing it — that section changed the outcome, which is the only reason it was worth asking for.

## 4. N3 — the fixtures predate the consolidation

`spike/recordings/` was last written at T-12, before the N1 consolidation. So `HttpTransport`'s new
docstring — *"the same code path that produced every fixture in `spike/recordings/`"* — is not true
of the fixtures now on disk; those came from the old fetch under `CiteBind-recording/0.1`.

The consolidation is right. The sentence about the artifacts is not. Either re-record (preferred —
it makes the claim true by construction, and re-recording is cheap and provable) or reword to say
which fixtures predate it. Do not leave it as written.

This is the same shape a fourth time: a docstring asserting a property the artifacts do not have.
You have now fixed it in code twice. It is worth noticing that the *code* keeps getting fixed while
the *sentence next to it* is where the claim outruns the evidence. When you finish a change, read
every comment and docstring within sight of it and ask which are now false.

## 5. Phase 3 — rendering only, no document I/O

Same scoping rule as Phase 2: build what survives any outcome of the Word run. **Rendering a
`Reference` into text is contract-independent. Putting text into a document is not.** Nothing in
this phase touches `part.py`, `controls.py`, or the spike kit.

### T-14 — Pin the dependency and vendor the styles

`citeproc-py==0.11.1` exactly — the API is 0.x by the maintainers' own statement, so an unpinned
minor release is a live grenade. Vendor two CSL style files plus the `en-US` locale.

**Choose the styles for the disambiguation gap, not for taste.** citeproc-py does not implement
year-suffix disambiguation, so pick an author–year style whose ordinary output does not require it,
and say in writing which one you picked and why. Same archival discipline as the API fixtures: the
style XML is committed **raw and unmodified**, with its source URL and retrieval date recorded in a
manifest. A hand-edited style file is a fabricated citation format.

### T-15 — `Reference` → CSL-JSON

Map our model to CSL-JSON items. The absence rule from T-09 applies unchanged: a field the record
does not have is absent, never an empty string, never inferred. This mapping also serves the
CSL-JSON export promised in the product plan's first milestone.

### T-16 — Render citation clusters

One numeric style, one author–year, single and multi-reference clusters. Deterministic: same input,
same output, no clock, no locale sniffing from the environment.

### T-17 — Render the bibliography

From cited references only, ordered per the style's own rules — not per our idea of them.

### T-18 — State the capability boundary, and refuse outside it

The one I care most about. Produce a test-backed statement of what our two styles actually rely on
from citeproc-py, and **detect and refuse the cases it cannot do correctly** — starting with two
works by the same authors in the same year, which real styles render as 2009a/2009b and citeproc-py
does not.

A wrong-but-plausible citation is worse than a refusal, because a refusal reaches the researcher
and a wrong citation reaches the reviewer. Refuse by name, and record the deliberate loss inline in
the test so nobody "fixes" it back later.

**Ground truth for every rendering test must be sourced, not composed.** Take expected output from
the CSL test suite or from the style's own published examples, archive it like an API fixture, and
cite where it came from. Rendered output you wrote yourself, checked against a renderer you
configured yourself, tests nothing — that is precisely the circularity this decision exists to
avoid. If you cannot source ground truth for a case, say so and leave it untested rather than
inventing an expectation.

## 6. Stop conditions

Unchanged, plus one: **stop if citeproc-py cannot render one of the two chosen styles correctly.**
That is not a bug to work around — it is evidence against the decision in §3, and I want to hear it
rather than have it absorbed.

## 7. Where this stands

Phase 1's exit condition is still unmet and still needs a human in Word for five minutes. Nothing
in Phase 3 changes that, and none of it should be read as the contract settling. It is not settled;
it is unexamined.

Reports in the §5 format. `SURPRISES` first, then the thing you would most like a second pair of
eyes on — that field has now caught two real problems before I did.
