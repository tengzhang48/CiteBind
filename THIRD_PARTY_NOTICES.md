# Third-party notices

The root MIT license covers CiteBind's original code and documentation. It does
not replace the licenses or attribution of third-party materials.

## Citation Style Language assets

The following files are redistributed unmodified under **Creative Commons
Attribution-ShareAlike 3.0 Unported (CC BY-SA 3.0)**:

| File | Source |
| --- | --- |
| `src/citebind/styles/apa.csl` | [CSL styles repository](https://github.com/citation-style-language/styles/blob/b93390e4352af47afc19144321a194f7ab7902bf/apa.csl) |
| `src/citebind/styles/ieee.csl` | [CSL styles repository](https://github.com/citation-style-language/styles/blob/b93390e4352af47afc19144321a194f7ab7902bf/ieee.csl) |
| `src/citebind/styles/locales-en-US.xml` | [CSL locales repository](https://github.com/citation-style-language/locales/blob/9ded661fc7bb995a5453a2025ca826ff404a4fbd/locales-en-US.xml) |

Copyright belongs to the respective authors and contributors identified in each
file's `<info>` section and upstream history. Those attribution and rights
elements remain intact. Exact upstream revisions, URLs, and SHA-256 hashes are
recorded in `src/citebind/styles/MANIFEST.json`.

The [full license text](LICENSES/CC-BY-SA-3.0.txt) is included, reproduced from
the [SPDX license list](https://github.com/spdx/license-list-data/blob/main/text/CC-BY-SA-3.0.txt).
Its authoritative terms are also available at
<https://creativecommons.org/licenses/by-sa/3.0/legalcode>.

Because distributions include these assets alongside MIT code, their package
metadata uses the expression `MIT AND CC-BY-SA-3.0`.

## Reference metadata fixtures

`spike/reference_source_crossref.json` and `spike/recordings/` contain public
bibliographic metadata obtained from Crossref and NCBI PubMed. They are test
inputs, not CiteBind-authored publications or private manuscripts. Source URLs
and available retrieval provenance are retained with the recordings. Missing
historical retrieval times have not been invented.

Publisher abstracts are omitted from the current fixtures; derived fixtures
record their source hashes and omitted fields. Bibliographic facts and source
links remain unchanged. See `spike/recordings/README.md` for the derivation policy.

Historical Git revisions include raw Crossref abstracts for
[10.1103/PhysRevLett.116.061102](https://doi.org/10.1103/PhysRevLett.116.061102)
(CC BY 3.0) and [10.1177/29768659261469390](https://doi.org/10.1177/29768659261469390)
(CC BY-NC 4.0), as identified by the license links in those records. Their
respective authors' rights and original licenses continue to apply to that
historical content; it is not relicensed under MIT.

## Installed dependencies

Dependencies are installed separately and carry their own license files:

- `python-docx`: MIT.
- `lxml`: BSD-3-Clause, with additional notices for its bundled components.
- `citeproc-py` 0.11.1: BSD-2-Clause-Views; its bundled CSL assets retain their
  upstream licenses.

Refer to each installed distribution for the full applicable notices.
