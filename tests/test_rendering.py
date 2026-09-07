"""T-14..T-18: deterministic rendering, and the cases we refuse instead.

Ground-truth discipline (review note 2026-09-03 §5): rendered output that we
wrote ourselves, checked against a renderer we configured ourselves, tests
nothing. So the assertions here are of three clearly separated kinds, and each
one says which it is:

1. SOURCED -- checked against something outside this project (the upstream CSL
   locale bytes, the vendored style hashes).
2. STRUCTURAL -- properties that must hold whatever the exact string is
   (absence rule, determinism, only-cited-works, refusals firing by name).
3. RECORDED -- the exact text citeproc-py 0.11.1 plus the pinned style produce
   TODAY. These are drift detectors, not correctness proofs: no published
   IEEE or APA example was sourced for these particular records, and a
   recorded string agreeing with itself proves only that nothing changed.
   Marked RECORDED individually so nobody later mistakes one for a proof.
"""

import hashlib
import json
from pathlib import Path

import pytest

from citebind.crossref import resolve_doi
from citebind.model import AuthorName, CiteBindDocument, CitationCluster, Reference
from citebind.pubmed import resolve_pmid
from citebind.rendering import (
    CODE_AUTHOR_NAMES_UNSTRUCTURED,
    CODE_LOCATOR_LABEL_UNKNOWN,
    CODE_STYLE_UNKNOWN,
    CODE_YEAR_SUFFIX_UNSUPPORTED,
    LOCALE,
    STYLES,
    STYLES_DIR,
    RenderingRefusal,
    check_capability,
    render,
    to_csl_json,
)
from citebind.transport import ReplayTransport

RECORDINGS = Path(__file__).parent.parent / "spike" / "recordings" / "MANIFEST.json"


def recordings():
    return ReplayTransport(RECORDINGS)


def belletti():
    return resolve_doi("10.2147/prom.s8896", recordings(), "R001", "2026-09-07T00:00:00Z")


def gw150914():
    return resolve_doi(
        "10.1103/physrevlett.116.061102", recordings(), "R002", "2026-09-07T00:00:00Z"
    )


def document(*references, style="numeric", clusters=None):
    if clusters is None:
        clusters = [
            CitationCluster(id=f"C{i:03d}", reference_ids=[r.id])
            for i, r in enumerate(references, start=1)
        ]
    return CiteBindDocument(
        schema_version="1",
        selected_style=style,
        references=list(references),
        citation_clusters=clusters,
    )


# --- SOURCED -------------------------------------------------------------


def test_citeproc_py_is_the_pinned_version():
    """SOURCED: every RECORDED string below is only meaningful for one
    renderer version, and the maintainers state the 0.x API is not stable.
    If this fails, the recorded output is not evidence of anything until it is
    re-checked deliberately."""
    from importlib.metadata import version

    assert version("citeproc-py") == "0.11.1"


def test_bundled_locale_matches_upstream_at_the_pinned_commit():
    """SOURCED: the locale that actually renders is citeproc-py's bundled one.

    `CitationStylesStyle(locale=...)` takes a locale NAME and silently ignores
    a path -- a nonexistent path is accepted without error -- so the vendored
    file is not loaded and must not be described as if it were. It earns its
    place here instead: this asserts the dependency's en-US is byte-identical
    to upstream locales@9ded661, so the day citeproc-py's copy drifts from the
    commit we pinned, this test says so and the recorded strings below become
    suspect.
    """
    import citeproc

    bundled = (
        Path(citeproc.__file__).parent / "data" / "locales" / f"locales-{LOCALE}.xml"
    )
    vendored = STYLES_DIR / f"locales-{LOCALE}.xml"
    assert bundled.read_bytes() == vendored.read_bytes()


def test_vendored_styles_are_the_bytes_the_manifest_pins():
    """SOURCED: styles are committed raw; a hand-edited style file is a
    fabricated citation format. The manifest records the upstream commit, so
    these hashes are checkable against the CSL repository by anyone."""
    manifest = json.loads((STYLES_DIR / "MANIFEST.json").read_text())
    assert manifest["assets"], "manifest lists no assets"
    for asset in manifest["assets"]:
        body = (STYLES_DIR / asset["file"]).read_bytes()
        assert hashlib.sha256(body).hexdigest() == asset["sha256"], asset["file"]
        assert len(body) == asset["bytes"], asset["file"]
        assert len(asset["commit"]) == 40, "assets must pin a commit, not a branch"


# --- STRUCTURAL: T-15, the mapping ---------------------------------------


def test_mapping_keeps_the_structured_names_the_source_gave():
    item = to_csl_json(belletti())
    assert item["author"] == [{"family": "Belletti", "given": "Daniel A"}]
    assert item["id"] == "R001"
    assert item["issued"] == {"date-parts": [[2010]]}


def test_mapping_omits_absent_fields_rather_than_emptying_them():
    """The T-09 absence rule, unchanged: absent is absent, never ""."""
    reference = Reference(
        id="R001", title="A Paper", authors=["Ann Author"],
        author_names=[AuthorName(family="Author", given="Ann")],
        journal="J. Fixtures", year=2024, metadata_source="crossref",
        retrieved_at="2026-09-07T00:00:00Z", doi="10.1000/x",
    )
    item = to_csl_json(reference)
    for absent in ("volume", "issue", "page"):
        assert absent not in item
    assert item["DOI"] == "10.1000/x"


def test_mapping_carries_no_author_key_when_the_source_gave_no_structure():
    reference = resolve_pmid("22915950", recordings(), "R001", "2026-09-07T00:00:00Z")
    assert reference.author_names is None
    assert "author" not in to_csl_json(reference)


# --- STRUCTURAL: T-16 and T-17, rendering --------------------------------


def test_rendering_is_deterministic():
    doc = document(belletti())
    assert render(doc) == render(doc)


def test_bibliography_contains_only_cited_works():
    """T-17: an uncited reference is not in the bibliography."""
    doc = CiteBindDocument(
        schema_version="1", selected_style="numeric",
        references=[belletti(), gw150914()],
        citation_clusters=[CitationCluster(id="C001", reference_ids=["R001"])],
    )
    out = render(doc)
    assert len(out.bibliography) == 1
    assert "Belletti" in out.bibliography[0]
    assert "Abbott" not in out.bibliography[0]


def test_multi_reference_cluster_renders_both_references():
    doc = CiteBindDocument(
        schema_version="1", selected_style="numeric",
        references=[belletti(), gw150914()],
        citation_clusters=[CitationCluster(id="C001", reference_ids=["R001", "R002"])],
    )
    out = render(doc)
    assert len(out.bibliography) == 2
    assert out.citations["C001"].count("[") == 2


@pytest.mark.parametrize("style", sorted(STYLES))
def test_every_declared_style_renders(style):
    out = render(document(belletti(), style=style))
    assert out.citations["C001"]
    assert out.bibliography


# --- STRUCTURAL: T-18, the capability boundary ---------------------------


def test_unstructured_author_names_are_refused_by_name():
    """A PubMed record gives "Belletti DA" and no family/given split.

    DELIBERATE LOSS: rather than split the string (wrong for particles,
    compound surnames, and every name that does not put the family last),
    rendering refuses. Do not "fix" this by adding a splitter.
    """
    reference = resolve_pmid("22915950", recordings(), "R001", "2026-09-07T00:00:00Z")
    with pytest.raises(RenderingRefusal) as caught:
        render(document(reference))
    assert caught.value.code == CODE_AUTHOR_NAMES_UNSTRUCTURED


def test_same_author_same_year_is_refused_in_author_year_style():
    """T-18's headline case, and the reason it exists.

    RECORDED EVIDENCE (citeproc-py 0.11.1, apa.csl at the pinned commit): two
    different 2010 papers by Belletti both render as "(Belletti, 2010)". A
    real style renders them 2010a/2010b. citeproc-py does not implement
    year-suffix disambiguation, so the two citations are indistinguishable and
    a reader cannot tell which paper is meant.

    DELIBERATE LOSS: we refuse the document instead of emitting the ambiguous
    pair. A refusal reaches the researcher; a wrong citation reaches the
    reviewer. If a future citeproc-py implements year-suffix, this test should
    be rewritten to assert 2010a/2010b -- not deleted.
    """
    first = belletti()
    second = Reference(
        id="R002", title="Another 2010 paper", authors=["Daniel A Belletti"],
        author_names=[AuthorName(family="Belletti", given="Daniel A")],
        journal="Patient Related Outcome Measures", year=2010,
        metadata_source="crossref", retrieved_at="2026-09-07T00:00:00Z",
        doi="10.1000/second",
    )
    doc = document(first, second, style="author-year")
    with pytest.raises(RenderingRefusal) as caught:
        render(doc)
    assert caught.value.code == CODE_YEAR_SUFFIX_UNSUPPORTED

    # The evidence for the refusal, exercised so it cannot rot: with the check
    # bypassed, citeproc-py really does render the two identically.
    from citebind import rendering

    original = rendering.check_capability
    rendering.check_capability = lambda _doc: None
    try:
        out = rendering.render(doc)
    finally:
        rendering.check_capability = original
    assert out.citations["C001"] == out.citations["C002"] == "(Belletti, 2010)"


def test_numeric_style_does_not_refuse_the_same_collision():
    """The collision is structurally absent in a numeric style: [1] and [2]
    are distinct whatever the authors and years are. This is why the numeric
    style was chosen for the gap rather than for taste."""
    first = belletti()
    second = Reference(
        id="R002", title="Another 2010 paper", authors=["Daniel A Belletti"],
        author_names=[AuthorName(family="Belletti", given="Daniel A")],
        journal="Patient Related Outcome Measures", year=2010,
        metadata_source="crossref", retrieved_at="2026-09-07T00:00:00Z",
        doi="10.1000/second",
    )
    out = render(document(first, second, style="numeric"))
    assert out.citations["C001"] != out.citations["C002"]


def test_locator_without_a_label_is_refused():
    """citebind/1 stores locator as a bare string, so "12" could be a page, a
    chapter, or a figure, and each renders differently. Rendering it as a page
    would be an assumption about the author's intent. The contract needs a
    label field before locators can be rendered."""
    doc = CiteBindDocument(
        schema_version="1", selected_style="numeric", references=[belletti()],
        citation_clusters=[
            CitationCluster(id="C001", reference_ids=["R001"], locator="12")
        ],
    )
    with pytest.raises(RenderingRefusal) as caught:
        render(doc)
    assert caught.value.code == CODE_LOCATOR_LABEL_UNKNOWN


def test_unknown_style_is_refused_by_name():
    with pytest.raises(RenderingRefusal) as caught:
        check_capability(document(belletti(), style="chicago"))
    assert caught.value.code == CODE_STYLE_UNKNOWN


# --- RECORDED: drift detectors, not correctness proofs -------------------


def test_recorded_numeric_output():
    """RECORDED, NOT SOURCED. This is what citeproc-py 0.11.1 + ieee.csl at
    the pinned commit produce for this record today. No published IEEE example
    was sourced for this record, so this proves only that output has not
    drifted -- never that it is correct IEEE. If it changes, find out why
    before updating it."""
    out = render(document(belletti(), style="numeric"))
    assert out.citations["C001"] == "[1]"
    assert out.bibliography == [
        '[1]D. A. Belletti, “Perspectives on electronic medical records adoption: electronic medical records (EMR) in outcomes research”, Patient Related Outcome Measures, p. 29, 2010, doi: 10.2147/prom.s8896.'
    ]


def test_recorded_author_year_output():
    """RECORDED, NOT SOURCED -- see the note above."""
    out = render(document(belletti(), style="author-year"))
    assert out.citations["C001"] == "(Belletti, 2010)"
    assert out.bibliography == [
        'Belletti, D. A. (2010). Perspectives on electronic medical records adoption: electronic medical records (EMR) in outcomes research. Patient Related Outcome Measures, 29. https://doi.org/10.2147/prom.s8896'
    ]
