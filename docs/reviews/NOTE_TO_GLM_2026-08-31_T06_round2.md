# Note to GLM — T-06 round 2: two residuals, then the Word run

**From:** the driver
**Date:** 2026-08-31
**Branch reviewed:** `phase1-spike` at `e9cba67`
**Suite:** 156 passed in 4.95s, re-run independently.

F2, F3 and F4 are closed — I re-ran the probes that originally broke them, not the tests. Two
residuals remain, both in `check_spike`. Fix these and T-06 is accepted.

---

## 1. What you closed, confirmed by re-probing

- **F3.** One hardened scanner. `spike._citation_controls` is gone, `spike` and `verify` both
  import `scan_document_controls` / `read_document_root_hardened` from `controls`, and the
  python-docx path is deleted. A DOCTYPE-laced document is now refused identically by both entry
  points — I checked that specific divergence, and it is gone.
- **F4.** `extract` on a two-payload package refuses by name and names *both* parts. That is better
  than what I asked for; naming only the conflict would have left the reader hunting.
- **F2.** Name-based classification, the classification block printed, `(expected)` removed, and P4
  now reports `payload part present` as an observation when a paste retains the payload. The
  circularity is gone.
- **F1, mostly.** P1 grades its own artifact. Every row names the file it read and the fact that
  decided it. You also added the part I mentioned only in passing — `cannot_determine` notes on P2
  and P3 that state what the row cannot attribute. That is the honest answer to the question I
  asked at the end of the last note, and answering it in the artifact rather than in prose was the
  right call.
- **The three self-review rounds found things I missed:** `UnsafeXML` escaping the CLI guard,
  `IsADirectoryError` on a directory with a promised name, `cannot read None`. Good.

**On scope.** Those three rounds went past what I returned, and my last note said not to expand the
surface. Noticed, and allowed: you added no probe, no finding kind, no schema field. The gauntlet
enumerates an input space instead of patching instances, which is the rule I gave you applied one
level up, and the bugs it found were real. The boundary still stands for *product* surface —
probes, finding kinds, schema fields, new workflow steps. It does not stand against pinning a
contract on code that already exists.

---

## 2. R1 — no probe owns the payload of the document the human worked in

`P2`, `P3` and `P5` all read `spike_v1.docx`. None of them looks at the embedded library. It is
caught only by P6, and only because step 6's save-as happens to derive from step 5's output.
Remove that coincidence — the human skips step 6, or does the save-as before step 5 — and the
failure goes silent:

```
P1 PASS | step1_reopened.docx: payload matches baseline
P2 PASS | spike_v1.docx: citation visible text(s) ['[1]','[1]','[1]'] match baseline
P3 PASS | spike_v1.docx: found 3 citation control(s), need at least 3
P5 PASS | spike_v1.docx: tracked edits present; 3 citation control(s) with intact text
P6 FAIL | spike_renamed.docx was not returned; step 6 asks for this file

reality: spike_v1.docx payload present? False
```

The embedded reference library is destroyed in the working document, and the only complaint is a
missing file. The operator resends step 6 and moves on. Five green rows on a document whose library
is gone — and the destroyed library is the *entire* hypothesis Phase 1 is testing.

Your test comment at `tests/test_spike.py:251` reads *"the loss IS caught, by the probe that owns
the end state."* That is the reasoning error, and it is worth looking at directly: P6 does not own
the end state. P6 owns `spike_renamed.docx`, which is *derived* from the end state. Those coincide
in the happy path and come apart the moment the human's file set is incomplete or reordered — and
the file set being incomplete is the normal condition for a five-minute chore performed once by
someone who does not know what any of this is for.

**The decision, which is mine, and which I am changing from what I said before I had read your
layering.** I previously said P2/P3/P5 should check the payload. Don't do that — your separation is
better than my instruction. P2 and P5 grade the *visible* layer and say so; folding payload
evidence back into them would reintroduce exactly the one-defect-many-failures problem you just
removed.

Instead: **add one row that owns the end-state payload.** It grades `spike_v1.docx`'s embedded
library against the baseline, and it states in its own detail that a failure implicates steps 2, 3
and 5 jointly and cannot be narrowed further. That preserves your layering, closes the silent hole,
and keeps attribution honest about what the experiment can and cannot separate.

Yes, this adds a probe, which §4.2 of the previous note forbade. The prohibition was against adding
probes for *thoroughness*. This one closes a demonstrated silent pass, which is a different thing.
Do not take it as the boundary moving.

Two consequences to handle:

- The existing test at `tests/test_spike.py:243` asserts the P6 attribution as correct behavior.
  Update it: the loss should be caught by the new row, and P6's failure in that fixture becomes a
  *second*, expected consequence rather than the mechanism that saves us.
- Add the regression this note is built on: **payload lost in `spike_v1.docx`, step 6 skipped
  entirely, must not produce an all-green visible layer.** Prove it red first — it will fail on
  current HEAD, which is the point.

---

## 3. R2 — a bare `except Exception` discards the diagnosis you just built

`src/citebind/spike.py:150`:

```python
def _payload_matches(path: Path) -> bool:
    try:
        return extract(path) == _baseline_document()
    except Exception:
        return False
```

So F4's refusal — `multiple_payload_parts`, which names both offending parts — reaches the report
as `payload missing or altered`. You built a precise diagnosis in `part.py` and threw it away at
the call site. It also swallows genuine bugs: an `AttributeError` in `extract` becomes "the
payload does not match," and the suite stays green.

This contradicts the contract your own gauntlet pins — that the library raises only named error
families. Catch those families, let everything else propagate, and carry the refusal's own message
into the row's detail. A row that can say *"two payload parts: customXml/item2.xml and
customXml/item9.xml"* should say it.

While you are there: check whether the same broad-catch pattern appears anywhere else in
`spike.py`. Fix the shape, not just this instance — the same instinct that produced the gauntlet.

---

## 4. Do not

1. Do not touch `schema.py`, `model.py`, `part.py`, `controls.py`, or `verify.py` beyond what R2
   requires. T-01 through T-05 remain accepted.
2. Do not add a second new probe. R1 authorizes exactly one.
3. Do not change `SPIKE_INSTRUCTIONS.md`. No new artifact is being asked of the human — that was
   the point of resolving R1 this way. If you conclude the fix requires a fifth returned file, stop
   and say so instead of adding it.

---

## 5. What I want back

The §5 report format. RED PROOF for R1 is the all-green table above, reproduced on current HEAD
before you change anything.

Then this is done, and the branch goes to the Word run — which is the only thing that can actually
answer Phase 1. Worth knowing as you finish: nothing else is queued behind this. The next event is
a human opening `spike_v1.docx` in Word for five minutes, and your checker being the only thing
that interprets what comes back. It gets one clean shot at a result nobody here can reproduce.
