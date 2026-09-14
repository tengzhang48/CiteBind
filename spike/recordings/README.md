# Public metadata fixtures

These fixtures contain bibliographic metadata from Crossref and NCBI PubMed.
They exercise resolver behavior without requiring network access during tests.
The manifest maps each response to its source URL. The older
`../reference_source_crossref.json` is a second archived response for
<https://api.crossref.org/works/10.2147/prom.s8896>, used to compare independently
recorded bibliographic values.

## Public derivation policy

Publisher abstracts are not needed to test citation identity and can have
different licensing from bibliographic metadata. The recorder removes JSON
`abstract` fields and preserves every other parsed value. It records:

- `source_sha256`: SHA-256 of the original response bytes.
- `sha256`: SHA-256 of the committed fixture bytes.
- `omitted_fields`: JSON Pointer paths removed from the original response.

When no fields are omitted, the bytes and both hashes are identical. A derived
fixture is not described as a raw, unmodified API response. The original responses
for the two historical derived fixtures remain recoverable from Git commit
`6b605858f16710a44505853f19d684caa5e82214`; see the root third-party notices for
their abstract licenses. No bibliographic values were invented or corrected.

## Historical provenance

The checked-in responses predate the shared `HttpTransport` recorder and do not
have reliable recorded retrieval times or User-Agent metadata. Those missing
facts remain missing. Publication cleanup recorded source/output hashes and
removed abstracts; it did not fetch replacement responses or claim a new
retrieval date. New runs of `python spike/record_fixtures.py` record the actual
retrieval time and User-Agent through the production transport.

The fixture for DOI `10.1103/physrevlett.116.061102` retains all 1012 authors;
the missing-volume/issue/pages and missing-journal examples retain those
absences. Do not replace them merely to obtain easier test inputs.
