"""T-14..T-18: deterministic citation and bibliography rendering.

Rendering is contract-independent: it turns a :class:`CiteBindDocument` into
text and never touches a DOCX. Nothing here knows what Word is.

Why citeproc-py rather than our own renderer (review note 2026-09-03 §3): a
hand-rolled renderer would be the only implementation of our own rendering,
which makes the Phase 6 check -- "visible text matches deterministic
rendering" -- circular. citeproc-py and citeproc-js aim at one public
specification and one public test suite; that shared ground truth is the
purchase. The cost is bought knowingly: citeproc-py passes about 60% of the
official suite, so it is a weak oracle, and the gaps that touch our two styles
are named and REFUSED here rather than rendered wrong.

The refusal rule, from the same note: a wrong-but-plausible citation is worse
than a refusal, because a refusal reaches the researcher and a wrong citation
reaches the reviewer.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from citeproc import Citation, CitationItem, CitationStylesBibliography
from citeproc import CitationStylesStyle, formatter
from citeproc.source.json import CiteProcJSON

from .model import CiteBindDocument, Reference

STYLES_DIR = Path(__file__).parent / "styles"

# The two styles of the first version, chosen for the disambiguation gap and
# not for taste (T-14):
#
# - "numeric" -> IEEE. A numeric style labels citations by position, so
#   year-suffix disambiguation -- the feature citeproc-py does not implement --
#   cannot arise. The gap is structurally absent, not merely unlikely.
# - "author-year" -> APA 7th. Every author-year style needs 2009a/2009b when
#   one author publishes twice in a year, so no author-year style dodges the
#   gap; APA was chosen because it is the most widely specified and the most
#   heavily exercised in the public test suite, which makes the renderer's
#   behaviour easiest to check against something outside this project. The
#   collision it cannot render is refused by name below.
STYLES = {
    "numeric": "ieee.csl",
    "author-year": "apa.csl",
}

# The locale is citeproc-py's BUNDLED en-US, not the copy in styles/.
# `CitationStylesStyle(locale=...)` takes a locale NAME and silently ignores a
# path -- a nonexistent path is accepted without error -- so claiming we load
# the vendored file would be false. The vendored copy earns its place as an
# oracle instead: test_rendering.py asserts the bundled locale is byte-identical
# to upstream at the pinned commit, so the day the dependency's locale drifts
# from upstream, the suite says so.
LOCALE = "en-US"

CODE_STYLE_UNKNOWN = "style_unknown"
CODE_AUTHOR_NAMES_UNSTRUCTURED = "author_names_unstructured"
CODE_YEAR_SUFFIX_UNSUPPORTED = "year_suffix_unsupported"
CODE_LOCATOR_LABEL_UNKNOWN = "locator_label_unknown"
CODE_ITEM_UNRESOLVED = "item_unresolved"


class RenderingRefusal(Exception):
    """Rendering stopped rather than emit a citation that could be wrong.

    ``code`` names the refusal; distinct refusals have distinct codes, so a
    caller can tell "we cannot do this yet" from "your document is broken".
    """

    def __init__(self, code: str, message: str):
        super().__init__(f"[{code}] {message}")
        self.code = code


def to_csl_json(reference: Reference) -> dict:
    """T-15: one Reference to one CSL-JSON item.

    The absence rule from T-09 is unchanged: a field the record does not have
    is absent from the item, never an empty string and never inferred. This
    mapping is also the CSL-JSON export promised in the product plan.
    """
    item: dict = {
        "id": reference.id,
        "type": "article-journal",
        "title": reference.title,
        "container-title": reference.journal,
        "issued": {"date-parts": [[reference.year]]},
    }
    if reference.author_names is not None:
        item["author"] = [name.to_dict() for name in reference.author_names]
    for source_field, csl_field in (
        ("volume", "volume"),
        ("issue", "issue"),
        ("pages", "page"),
        ("doi", "DOI"),
    ):
        value = getattr(reference, source_field)
        if value is not None:
            item[csl_field] = value
    return item


def _first_label(reference: Reference) -> Optional[str]:
    """The name a style would put in an author-year citation, or None."""
    if not reference.author_names:
        return None
    first = reference.author_names[0]
    return first.family or first.literal


def check_capability(document: CiteBindDocument) -> None:
    """T-18: refuse, by name, every case our two styles cannot render right.

    Called by :func:`render` before anything is rendered. Each refusal below
    is a deliberate loss with a reproduced reason, not a TODO.
    """
    style_key = document.selected_style
    if style_key not in STYLES:
        raise RenderingRefusal(
            CODE_STYLE_UNKNOWN,
            f"selected_style '{style_key}' is not one of: "
            f"{', '.join(sorted(STYLES))}",
        )

    cited_ids = {rid for c in document.citation_clusters for rid in c.reference_ids}
    by_id = {r.id: r for r in document.references}

    # 1. No structured names -> no style can produce a correct author label.
    #    Crossref supplies given/family and CiteBind now keeps it; PubMed
    #    supplies only "Belletti DA" and there is nothing to keep. Splitting
    #    the flat display string would be guesswork: it is wrong for
    #    particles ("van der Berg"), for compound surnames, and for every
    #    name that does not put the family last.
    for reference_id in sorted(cited_ids):
        reference = by_id.get(reference_id)
        if reference is not None and reference.author_names is None:
            raise RenderingRefusal(
                CODE_AUTHOR_NAMES_UNSTRUCTURED,
                f"reference '{reference_id}' has no structured author names "
                f"(metadata_source={reference.metadata_source!r}), so no style "
                "can render its author label correctly; CiteBind will not guess "
                "the family/given split from the display string",
            )

    # 2. Year-suffix disambiguation. citeproc-py does not implement it: two
    #    2010 papers by Belletti both render as "(Belletti, 2010)", which a
    #    reader cannot tell apart. Reproduced against citeproc-py 0.11.1 and
    #    pinned in test_rendering.py. Numeric styles label by position, so
    #    the collision cannot arise there.
    if style_key == "author-year":
        seen: dict[tuple[str, int], str] = {}
        for reference_id in sorted(cited_ids):
            reference = by_id.get(reference_id)
            if reference is None:
                continue
            label = _first_label(reference)
            if label is None:
                continue
            key = (label, reference.year)
            if key in seen:
                raise RenderingRefusal(
                    CODE_YEAR_SUFFIX_UNSUPPORTED,
                    f"references '{seen[key]}' and '{reference_id}' share first "
                    f"author '{label}' and year {reference.year}; the style "
                    "renders them as 2010a/2010b and citeproc-py does not "
                    "implement year-suffix disambiguation, so both would render "
                    "identically and a reader could not tell which paper is "
                    "cited",
                )
            seen[key] = reference_id

    # 3. A locator with no label. The citebind/1 contract stores locator as a
    #    bare string, so "12" could be a page, a chapter, a figure, or an
    #    equation, and each renders differently. Rendering it as a page would
    #    be an assumption about the author's intent.
    for cluster in document.citation_clusters:
        if cluster.locator is not None:
            raise RenderingRefusal(
                CODE_LOCATOR_LABEL_UNKNOWN,
                f"cluster '{cluster.id}' carries locator {cluster.locator!r}, but "
                "citebind/1 stores no locator LABEL, so CiteBind cannot know "
                "whether it names a page, a chapter, or a figure; the contract "
                "needs a label field before locators can be rendered",
            )


@dataclass
class Rendering:
    """What a document renders to. Deterministic for a given input."""

    # cluster id -> the citation's visible text, e.g. "C001" -> "[1]"
    citations: dict[str, str]
    # bibliography entries, ordered by the STYLE's rules, cited works only
    bibliography: list[str]


def _style_path(style_key: str) -> Path:
    return STYLES_DIR / STYLES[style_key]


def render(document: CiteBindDocument) -> Rendering:
    """T-16 and T-17: render every cluster and the bibliography.

    Deterministic: the same document renders to the same text. Nothing here
    reads the clock, the environment's locale, or the network -- the style and
    locale are files pinned in the repository and in the citeproc-py pin.
    """
    check_capability(document)

    cited_ids = {rid for c in document.citation_clusters for rid in c.reference_ids}
    items = [
        to_csl_json(reference)
        for reference in document.references
        if reference.id in cited_ids
    ]

    source = CiteProcJSON(items)
    style = CitationStylesStyle(
        str(_style_path(document.selected_style)), locale=LOCALE, validate=False
    )
    bibliography = CitationStylesBibliography(style, source, formatter.plain)

    unresolved: list[str] = []
    citations: dict[str, Citation] = {}
    for cluster in document.citation_clusters:
        cluster_items = []
        for reference_id in cluster.reference_ids:
            kwargs = {}
            if cluster.prefix is not None:
                kwargs["prefix"] = cluster.prefix
            if cluster.suffix is not None:
                kwargs["suffix"] = cluster.suffix
            cluster_items.append(CitationItem(reference_id, **kwargs))
        citation = Citation(cluster_items)
        citations[cluster.id] = citation
        bibliography.register(citation)

    rendered = {
        cluster_id: str(bibliography.cite(citation, unresolved.append))
        for cluster_id, citation in citations.items()
    }
    if unresolved:
        # A cluster naming a reference the document does not carry. The schema
        # already refuses this, so reaching here means the payload was built
        # around the validator; refuse rather than emit a citation to nothing.
        raise RenderingRefusal(
            CODE_ITEM_UNRESOLVED,
            f"citation items could not be resolved: {sorted(set(unresolved))}",
        )
    return Rendering(
        citations=rendered,
        bibliography=[str(entry) for entry in bibliography.bibliography()],
    )
