# Note to GLM — T-01 through T-05 accepted, T-06 returned

**From:** the driver
**Date:** 2026-08-29
**Branch reviewed:** `phase1-spike` at `1bb66eb`
**Suite:** 76 passed in 2.69s, re-run independently on this machine.

Read this whole note before touching code. It ends with three things not to do.

---

## 1. Accepted: T-01 through T-05

Good work, and specifically good in the places that were easy to fake and hard to do:

- **The baseline reference is real and provably so.** DOI `10.2147/prom.s8896`, archived raw
  Crossref record in `spike/reference_source_crossref.json`, and
  `test_spike_payload_is_the_archived_crossref_record` binding the fixture to that file. That is
  invariant 1 honored as a *mechanism* rather than a promise. It is the single thing I would have
  returned the whole branch over, and it is right.
- **You found the `customXml/item1.xml` collision and handled it.** Word's built-in bibliography
  sources (`b:Sources`) already occupy that slot, including in python-docx's default template.
  Writing there blind would have silently clobbered Word's own bibliography — a corruption we would
  probably have blamed on Word. Allocating the next free slot, reusing it on re-embed, and
  identifying the part by root namespace rather than by slot number is the correct resolution, and
  documenting it in the module docstring is why I could confirm it in one read.
- **`test_payload_survives_python_docx_rewrite_byte_identical` is the real probe**, not an
  approximation of it: byte comparison of both the item and the itemProps parts across a full
  repackage, then a re-extract. That test is the strongest evidence Phase 1 currently has.
- `test_make_spike_uses_no_network`, `test_generated_spike_introduces_no_fields`,
  `test_clean_document_reports_zero_findings`, and `set(FIXTURE_FOR_KIND) == set(FindingKind)`
  all do what they say. The exhaustiveness rule was honored, and the severity table is covered
  transitively through it — I checked, rather than assuming.

Do not revisit any of this while fixing T-06.

---

## 2. Returned: T-06

The generator is fine. The **checker** is what comes back. Two confirmed defects, both in the
grading layer, both of which cause `check-spike` to misreport *what broke* — on the one experiment
in this phase that nobody here can reproduce or re-run cheaply.

Before fixing either one, **reproduce it and paste the output.** A fix for a failure you never
observed is not a fix.

### F1 — Probe verdicts are not independent; one failure is reported as five

`P1`, `P2`, `P3` and `P5` are all graded from the same end-state `spike_v1.docx`, after the human
has performed steps 1–5 on it. So a failure introduced at *any* step is attributed to *every*
probe that reads the payload.

Reproduction — payload survives steps 1–3, then is lost during the step-5 Track Changes edit:

```
P1 FAIL  open, save, close, reopen        | payload missing or altered; 2 citation control(s)
P2 FAIL  ordinary prose edit ...          | citation text unchanged: ['[1]', '[1]']
P5 FAIL  edit next to a citation ...      | tracked edits present; 2 citation control(s) intact
P6 FAIL  save-as under a new name ...     | no save-as copy found among the returned files
```

Four wrong rows from one real defect. Three separate problems are visible in that output:

1. **Misattribution.** P1 blames the ordinary open/save cycle for a Track-Changes failure. Someone
   reading this table concludes that Word cannot even reopen the file, and never reaches the real
   cause.
2. **Detail lines that contradict their own verdict.** P2 and P5 print `FAIL` above a detail
   reporting everything they name as intact. The term that actually decided the verdict
   (`payload is None`) appears nowhere in the detail. A row must state the reason it failed.
3. **A row asserting a false fact about the world.** P6 says "no save-as copy found among the
   returned files." One *was* returned; the classifier could not identify it because the payload
   was gone. "I could not classify the returned files" and "you did not return the file" are
   different statements, and only one of them is true.

**What to change:** give the probes independent evidence. Step 1 should produce its own returned
artifact (a save-as copy made *before* any editing — name it in the instructions), and P1 should be
graded against that file alone. Any probe that cannot be isolated this way must say so in its own
row rather than borrowing another probe's evidence. Every detail line must contain the term that
decided the verdict.

Note the instruction file changes too — it currently promises three returned files. Keep it to one
page.

### F2 — Extra-file classification inverts on exactly the outcome the spike exists to discover

`check_spike` ignores the filenames its own instructions promise (`pasted.docx`,
`spike_renamed.docx`) and classifies the extras by content: the first file carrying a payload
becomes the save-as copy, the rest become the paste. Whether a clipboard paste carries the custom
XML part is **the open question probe 4 exists to answer.** If the answer is yes, the two files
swap roles silently:

```
P4 PASS  ... note: the embedded reference library does not travel with a clipboard paste (expected)
P6 PASS  pasted.docx: payload matches; 2 citation control(s); bibliography present
```

P6 graded `pasted.docx` as the save-as copy. P4 graded the save-as copy as the paste, and asserted
the library does not travel — the exact opposite of what happened in that run. Both rows say PASS,
so nothing raises an alarm and the finding is lost.

**What to change:** classify by the filenames the instructions promise, and print the classification
in the report so a human can see which file was graded as what. If a promised file is missing or a
returned file is unrecognized, say that plainly instead of inferring. And drop the parenthetical
"(expected)" from P4's detail — that clause hard-codes an answer to the question the probe is
asking.

### F3 — `find_controls` is not on any shipping path, and disagrees with the code that is

`controls.find_controls` is called from `tests/` and nowhere else. What actually runs is
`verify._scan_body` and `spike._citation_controls`. That is three implementations of "find the
CiteBind controls in this document," and they do not agree. `find_controls` reads through
python-docx, bypassing `parse_xml_hardened`:

```
verify.inspect(laced_with_doctype)        -> REFUSED: [doctype_declared]
controls.find_controls(laced_with_doctype) -> ACCEPTED, 3 controls
```

Two entry points reaching opposite trust decisions about the same bytes, while `xmlsafe.py`'s
docstring states that every package part is parsed hardened. Not exploitable today — python-docx
sets `resolve_entities=False`, so nothing expands — but `find_controls` is the public API the
add-in and the Phase 6 adapter will reach for, and `test_controls.py` currently certifies a
function that nothing ships.

**What to change:** one hardened scanner, used by all three callers. Delete the other two. If
`find_controls` is the right home for it, make `verify` and `spike` call it.

### F4 — Two payload parts is a coin flip

`part.find_citebind_part` silently keeps the first match (`if root.tag == ROOT_TAG and found is
None`). A package carrying two citebind payload parts should produce a named refusal, not a silent
choice. Cheap; fold it into this round.

---

## 3. The shape of all four, because it is one shape

Every finding above is a **claim resting on evidence that cannot support it**:

- P1 claims "the open/save cycle is broken" from a file that also went through four other steps.
- P4 claims "the library does not travel" from a file it identified *by assuming* the library does
  not travel.
- P6 claims "you did not return the file" when it means "I could not classify it."
- `test_controls.py` claims `find_controls` is correct, about a function no shipping path calls.

This is the same failure the CiteBind product exists to prevent — visible text asserting something
the underlying data does not support. Worth holding onto: **a verdict may only cite evidence that
could have come out the other way.** If P1 would read the same on a document where step 1 was never
performed, P1 is not measuring step 1.

The generalizable rule for the checker: each row states (a) which file it read, (b) which fact
decided the verdict, and (c) what it could not determine. A row that cannot fill in (a) is not
ready to render.

---

## 4. Do not

1. **Do not touch `src/citebind/schema.py`, `model.py`, `part.py`, or `verify.py`'s finding logic**
   beyond what F3 and F4 require. T-02 through T-05 are accepted. A fix that rewrites them comes
   back unreviewed.
2. **Do not add a probe, a finding kind, or a schema field** to make the checker more thorough.
   Fix the attribution; do not expand the surface.
3. **Do not weaken any test to make a fix pass.** If an accepted test now looks wrong to you, stop
   and say so rather than editing it — that is a decision, and decisions are mine.

---

## 5. What I want back

Reproduce F1 and F2 first and paste the output — that is your RED PROOF for this round, and it
comes from running the checker, not from a new unit test. Then fix, then add the tests that would
have caught each one (F1: a probe failing at step 5 must not produce a P1 failure; F2: a paste that
retains the payload must still be classified as the paste). Then the full suite.

Report in the §5 format from `docs/GLM_DEV_PLAN.md`. `SURPRISES` is the field I will read first.

One question I would like answered in your report, because you have looked at this code far more
recently than I have: **is there any probe in the current six that can fail for exactly one
reason?** If the answer is none, the kit needs a different shape rather than a repair, and I would
rather hear that from you now than discover it after the Word run.
