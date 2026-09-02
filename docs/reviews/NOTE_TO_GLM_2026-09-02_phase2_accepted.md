# Note to GLM — R1/R2 and Phase 2 accepted; two cleanups, then hold

**From:** the driver
**Date:** 2026-09-02
**Branch reviewed:** `phase1-spike` at `2e0f697`
**Suite:** 245 passed in 5.28s, re-run independently.

---

## 1. Accepted

**R1 and R2 are closed.** I re-ran the probe that produced the all-green table, not your tests. P7
now fails on it and carries the joint-attribution note; the `multiple_payload_parts` refusal
reaches the row verbatim instead of being flattened into "does not match baseline."

**T-07 through T-12 are accepted.** Spot-checked by running the paths rather than reading them:
every DOI paste shape normalizes, PMCID refuses under its own code, `10.2147` fails the structural
floor, `volume` and `issue` are genuinely absent from `to_dict()` rather than empty, and there is
no route from a title query to a `Reference` that bypasses `select()`.

Four things you did that were not asked for, and that I would not have thought to ask for:

- **`same_source` in `compare()`.** Comparing a source with itself is not a cross-check. Correct,
  and the kind of refusal that prevents a whole class of false confidence later.
- **"None is silence, not a claim."** That distinction is load-bearing and most implementations get
  it wrong by treating a missing field as a disagreement.
- **`retrieved_at` injected rather than read from a clock.** Deterministic, and it means fixtures
  cannot drift underneath the tests.
- **The `2e0f697` self-catch.** Your own report flagged that the oracle test covered less than the
  claim it made, and you fixed the test rather than the claim. The "second pair of eyes" line
  earned its place on its first outing; keep using it that way.

## 2. The invariant was audited, and it held

You should know this was checked rather than trusted, because it is the one thing whose failure
would end the project rather than a task.

I fetched `10.2147/prom.s8896` live from `api.crossref.org` and diffed the response against your
archived fixture, field by field. Everything matches — including `member: 301`,
`is-referenced-by-count: 17`, and `prefix: 10.1080`, which differs from the DOI's own prefix.
Details like that are not reconstructable from memory; their presence is what makes the recording
provably a recording.

Invariant 1 holds. Expect it to be audited this way again, at random, whenever new fixtures land.
That is not distrust — it is the property being *verifiable* rather than promised, which is the
whole thesis of this product turned on its own development.

## 3. N1 — `HttpTransport` is used by nothing, and its docstring says otherwise

`src/citebind/transport.py:83` claims it is *"Used in production and by the recording script
only."* The recording script does not use it. `spike/record_fixtures.py:64` builds its own
`fetch()` directly on `urllib`, with a **different** User-Agent:

```
transport.py:162       CiteBind/0.1 (https://github.com/tengzhang48/CiteBind; mailto:example@example.org)
record_fixtures.py:33  CiteBind-recording/0.1 (mailto:example@example.org)
```

So every replay fixture in the suite was recorded over a code path production will never execute.
Crossref's polite-pool routing keys on exactly that header, so the two paths can receive different
service — the fixtures are not necessarily what `HttpTransport` would have been handed.

**This is the third instance of one shape,** and that is why it is worth more than the fix:

| | the deliverable | what actually ran |
|---|---|---|
| F3 (round 1) | `controls.find_controls` | `verify._scan_body`, `spike._citation_controls` |
| N1 (now) | `transport.HttpTransport` | `record_fixtures.fetch` |

Both times, the tested thing and the running thing were different objects, and a docstring asserted
they were the same. You fixed F3 by consolidating; do the same here — the recorder uses
`HttpTransport`, and the duplicate `fetch()` goes. Then the docstring becomes true by construction
rather than by assertion.

Worth asking yourself once, since you have now written this shape twice: what makes it feel natural
to write a second implementation instead of importing the first? If there is a real reason — the
recorder needing bytes rather than a `TransportResponse`, say — that reason is a design constraint
worth writing down, not routing around.

While you are there: `mailto:example@example.org` is a placeholder in shipping code. Crossref asks
for a reachable address to enter the polite pool. Flag it rather than inventing one — the real
address is the user's to give, and I will get it.

## 4. N2 — a leftover at the repo root

`inputs_old_archive_manifest.json` was committed in `2e0f697`, is referenced by nothing, and
contains a machine-specific absolute path (`/media/volume/cpu-vm/CiteBind/spike/...`). Delete it.
If something generates it, make that thing write into a gitignored location.

## 5. T-13 — investigate, do not integrate

After N1 and N2, **stop and report.** Do not begin Phase 3 rendering.

What I want first is evidence for a decision that is mine: **which CSL processor, if any, this
project should depend on in Python.** The eventual Word add-in will use `citeproc-js`, so anything
Python-side is justified only by what the *verifier* needs — checking that visible citation text
matches deterministic rendering is on the Phase 6 list, and that check cannot exist without a
renderer.

Produce a short written comparison, no code beyond throwaway spikes:

- what maintained CSL options exist for Python, with their actual maintenance state — last release,
  open issue volume, whether CSL 1.0.2 is supported;
- what each would cost us in dependency weight, given §7's lightweight-by-omission posture;
- whether rendering one numeric and one author–year style is achievable without a full CSL
  processor, and what we would give up (this is a real option, not a straw man — but be honest
  about which styles it excludes);
- your recommendation, with the strongest argument *against* it stated in full.

That last clause is the point of the task. I want the case against whatever you pick, argued
properly, because I am the one who has to live with the dependency.

## 6. Where this stands

Phase 2's exit condition is met: no stored reference depends on model-generated identity, and that
is now a checkable property rather than a claim. Phase 1's exit condition is **not** met and cannot
be met by anything either of us does — it needs a human opening `spike_v1.docx` in Word for five
minutes. That is the only thing standing between this branch and a real answer, and it is being
arranged.

Everything you build until then is scaffolding around an untested contract. You have built it
well. Do not let that fact make the contract feel more settled than it is.
