"""Record raw API responses as resolver fixtures. DELIBERATE LIVE ACT.

This is the one place a live network request is allowed (dev plan review
note 2026-08-31, T-08). Run it by hand, on purpose:

    python spike/record_fixtures.py           # refuses to overwrite
    python spike/record_fixtures.py --force   # re-record everything

It fetches each target below and writes the RAW, UNMODIFIED response bytes
into ``spike/recordings/``, plus a MANIFEST.json mapping each URL to its
file. The raw bytes are the provenance for every downstream assertion —
never reformat, never "clean up", never edit a recording.

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

import json
import sys
import urllib.request
from pathlib import Path

RECORDINGS_DIR = Path(__file__).parent / "recordings"
USER_AGENT = "CiteBind-recording/0.1 (mailto:example@example.org)"

CROSSREF_DOIS = [
    "10.2147/prom.s8896",
    "10.22541/au.161220228.87275329/v1",
    "10.1103/physrevlett.116.061102",
]

TITLE_FOR_PMID = (
    "Perspectives on electronic medical records adoption: "
    "electronic medical records (EMR) in outcomes research"
)


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def slug(text: str) -> str:
    return text.replace("/", "_").replace(":", "_").lower()


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
        target.write_bytes(body)  # raw bytes, unmodified
        recordings.append({"url": url, "file": filename, "source": source})
        print(f"recorded {url} -> {filename} ({len(body)} bytes)")
        return filename

    # --- Crossref records ---------------------------------------------------
    for doi in CROSSREF_DOIS:
        url = f"https://api.crossref.org/works/{doi}"
        record(url, fetch(url), source="crossref")

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
        "recordings": recordings,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"wrote {manifest_path} ({len(recordings)} recordings)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
