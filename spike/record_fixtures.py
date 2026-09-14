"""Record public bibliographic metadata as resolver fixtures.

This is the one place a live network request is allowed (dev plan review
note 2026-08-31, T-08). Run it by hand, on purpose:

    python spike/record_fixtures.py           # refuses to overwrite
    python spike/record_fixtures.py --force   # re-record everything

It fetches each target below through the production transport. Publisher
abstracts are omitted from public fixtures, with source/output SHA-256 hashes
and omitted JSON paths recorded in MANIFEST.json. Responses without abstracts
retain their original bytes. All remaining bibliographic values are unchanged.
The manifest also records the URL, retrieval time, and actual User-Agent.

A manifest written before 2026-09-06 carries no ``retrieved_at`` or
``user_agent``: those fields start here and are never backfilled, because a
retrieval time nobody recorded is a retrieval time nobody knows.

Target selection (all selected from live API responses, never from memory):
- 10.2147/prom.s8896 — the CiteBind spike reference (Belletti 2010)
- 10.22541/au.161220228.87275329/v1 — real record genuinely missing
  volume/issue/pages (selected from a Crossref bibliographic query,
  2026-08-31)
- 10.1103/physrevlett.116.061102 — real record with 1012 authors (GW150914,
  LIGO Scientific Collaboration and Virgo Collaboration)
- one PubMed record: the PMID comes from PubMed's own esearch on the exact
  title of the first record, then its esummary is recorded. The PMID is
  thus sourced from PubMed, not typed from memory.
"""

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from citebind.transport import USER_AGENT, HttpTransport

RECORDINGS_DIR = Path(__file__).parent / "recordings"


def slug(text: str) -> str:
    """A filename-safe slug: safe characters, and short enough for the FS.

    Query URLs are long, so long inputs keep a hash suffix for uniqueness
    while the head stays human-readable.
    """
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in text)
    if len(safe) > 140:
        digest = hashlib.sha256(text.encode()).hexdigest()[:12]
        safe = f"{safe[:127]}-{digest}"
    return safe

CROSSREF_DOIS = [
    "10.2147/prom.s8896",
    # genuinely missing volume/issue/pages, required fields present
    # (selected from a Crossref journal-article query, 2026-08-31)
    "10.1177/29768659261469390",
    "10.1103/physrevlett.116.061102",
    # missing the journal (container-title) entirely: the refusal fixture
    "10.22541/au.161220228.87275329/v1",
]

TITLE_FOR_PMID = (
    "Perspectives on electronic medical records adoption: "
    "electronic medical records (EMR) in outcomes research"
)


_TRANSPORT = HttpTransport(timeout=30.0)


def fetch(url: str) -> bytes:
    """Fetch over the same HttpTransport production uses (review note N1):
    fixtures must come from the code path that will serve readers, with the
    same User-Agent, or the recordings are not necessarily what production
    would have been handed. Returns the raw body bytes, unmodified."""
    return _TRANSPORT.fetch(url).body


def prepare_fixture(body: bytes) -> tuple[bytes, dict]:
    """Omit publisher abstracts and record exactly how a fixture was derived."""
    data = json.loads(body)
    omitted = []

    def visit(value, path=""):
        if isinstance(value, dict):
            for key in list(value):
                child = path + "/" + key.replace("~", "~0").replace("/", "~1")
                if key == "abstract":
                    del value[key]
                    omitted.append(child)
                else:
                    visit(value[key], child)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, f"{path}/{index}")

    visit(data)
    published = (
        (json.dumps(data, ensure_ascii=True, separators=(",", ":")) + "\n").encode("utf-8")
        if omitted else body
    )
    return published, {
        "source_sha256": hashlib.sha256(body).hexdigest(),
        "sha256": hashlib.sha256(published).hexdigest(),
        "omitted_fields": omitted,
    }


def main() -> int:
    force = "--force" in sys.argv
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path = RECORDINGS_DIR / "MANIFEST.json"
    recordings: list[dict] = []
    if manifest_path.exists() and not force:
        print(f"refusing to overwrite {manifest_path}; use --force to re-record")
        return 1

    def record(url: str, body: bytes, source: str) -> str:
        filename = f"{source}-{slug(url)}.json"
        target = RECORDINGS_DIR / filename
        published, provenance = prepare_fixture(body)
        target.write_bytes(published)
        recordings.append(
            {
                "url": url,
                "file": filename,
                "source": source,
                **provenance,
                # stamped as the bytes hit disk. The manifest has to carry
                # its own retrieval time: file mtimes do not survive a copy,
                # a checkout, or a zip, and this is the provenance record.
                "retrieved_at": datetime.now(timezone.utc).isoformat(
                    timespec="seconds"
                ),
            }
        )
        print(f"recorded {url} -> {filename} ({len(body)} bytes)")
        return filename

    # --- Crossref records ---------------------------------------------------
    for doi in CROSSREF_DOIS:
        url = f"https://api.crossref.org/works/{doi}"
        record(url, fetch(url), source="crossref")

    # --- Crossref title search (for the candidate-list fixtures) ------------
    from citebind.crossref import title_search_url

    record(
        title_search_url(TITLE_FOR_PMID),
        fetch(title_search_url(TITLE_FOR_PMID)),
        source="crossref",
    )

    # --- PubMed: PMID from PubMed's own esearch on the exact title ----------
    # PubMed's relevance ranking can put other papers first, so the script
    # fetches esummaries for the returned candidates and records the one
    # whose title matches the Crossref record's title (data-driven, never
    # hand-picked from memory).
    import urllib.parse

    term = urllib.parse.quote(TITLE_FOR_PMID)
    search_url = (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
        f"?db=pubmed&retmode=json&term={term}"
    )
    search_body = fetch(search_url)
    record(search_url, search_body, source="pubmed")
    pmids = json.loads(search_body)["esearchresult"]["idlist"]
    if not pmids:
        print("esearch returned no PMID for the spike title; not recording esummary")
        return 1
    summary_url = (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
        f"?db=pubmed&retmode=json&id={','.join(pmids)}"
    )
    summary_body = fetch(summary_url)
    record(summary_url, summary_body, source="pubmed")
    summary = json.loads(summary_body)
    # PubMed titles carry a sentence-final period where Crossref's do not;
    # fold trailing periods for the match (and remember this: it is exactly
    # the kind of per-field cross-source disagreement T-11 must report)
    wanted = TITLE_FOR_PMID.lower().rstrip(".")
    match = next(
        (
            uid
            for uid in summary["result"]["uids"]
            if summary["result"][uid].get("title", "").lower().rstrip(".") == wanted
        ),
        None,
    )
    if match is None:
        print("no esummary title matched the Crossref title; not recording a match")
        return 1
    single_url = (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
        f"?db=pubmed&retmode=json&id={match}"
    )
    record(single_url, fetch(single_url), source="pubmed")
    print(f"PMID for the spike title, verified by title match: {match}")

    manifest = {
        "recorded_with": "spike/record_fixtures.py",
        # Record the actual agent used for this retrieval.
        "user_agent": USER_AGENT,
        "recordings": recordings,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {manifest_path} ({len(recordings)} recordings)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
