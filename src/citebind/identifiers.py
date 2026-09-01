"""Identifier normalization: DOI and PMID strings to canonical forms.

Canonical DOI form: **all-lowercase**, prefixes and URL wrappers removed,
trailing sentence punctuation and zero-width characters stripped. This is a
load-bearing decision, not a cosmetic one: DOIs are case-insensitive, and
whether duplicate detection works depends entirely on two case spellings of
the same DOI folding to one string. "10.2147/PROM.S8896" and
"https://doi.org/10.2147/prom.s8896." must be one record.

Canonical PMID form: bare digits with leading zeros dropped (PMIDs are
integers; 01234567 and 1234567 are the same record).

The DOI validator enforces the structural floor from the dev plan —
"10." + registrant digits + "/" + non-empty suffix — and deliberately not
the DOI handbook's finer registrant-length rules: refusing a real identifier
is a worse failure than accepting an odd-shaped one.

Zero-width and invisible directional characters stripped anywhere in the
input (they ride along from PDF and browser copies): U+200B, U+200C,
U+200D, U+200E, U+200F, U+2060, U+FEFF, U+00AD. Every
malformed class is refused with its own named code, never silently guessed.
"""

import re
from dataclasses import dataclass

# Zero-width and invisible characters that ride along from PDF/browser copies.
_INVISIBLE = "\u200b\u200c\u200d\u200e\u200f\u2060\ufeff\u00ad"

_DOI_FLOOR = re.compile(r"^10\.\d+/\S+$")
_PMCID = re.compile(r"^(pmcid:\s*)?pmc\d*$", re.IGNORECASE)
_PMID_PREFIX = re.compile(r"^pmid:\s*", re.IGNORECASE)
_DOI_PREFIX = re.compile(r"^doi:\s*", re.IGNORECASE)
_DOI_URL = re.compile(r"^(https?://(dx\.)?doi\.org/)", re.IGNORECASE)

CODE_EMPTY_INPUT = "empty_input"
CODE_NOT_A_DOI = "not_a_doi"
CODE_NOT_A_PMID = "not_a_pmid"
CODE_PMCID_NOT_PMID = "pmcid_not_pmid"
CODE_UNRECOGNIZED_IDENTIFIER = "unrecognized_identifier"


class IdentifierError(Exception):
    """An identifier string was refused, with a named reason."""

    def __init__(self, code: str, message: str):
        super().__init__(f"[{code}] {message}")
        self.code = code


@dataclass(frozen=True)
class Identifier:
    """A recognized identifier in canonical form."""

    kind: str  # "doi" | "pmid"
    value: str


def _clean(raw: str) -> str:
    for ch in _INVISIBLE:
        raw = raw.replace(ch, "")
    return raw.strip()


def _require_nonempty(cleaned: str) -> str:
    if not cleaned:
        raise IdentifierError(
            CODE_EMPTY_INPUT,
            "identifier is empty (only whitespace or invisible characters)",
        )
    return cleaned


def normalize_doi(raw: str) -> str:
    """Return the canonical (lowercase) form of a DOI string.

    Accepts bare DOIs, ``https://doi.org/…``, ``http://dx.doi.org/…`` and
    ``doi:`` prefixed forms, uppercase in any position, surrounding
    whitespace, zero-width characters, and a single trailing sentence
    period. Raises IdentifierError with code ``not_a_doi`` for anything
    that does not meet the structural floor (``10.`` + registrant digits +
    ``/`` + non-empty suffix) and ``empty_input`` for empty input.
    """
    cleaned = _require_nonempty(_clean(raw))
    while True:
        stripped = _DOI_URL.sub("", cleaned, count=1)
        stripped = _DOI_PREFIX.sub("", stripped, count=1)
        stripped = stripped.strip().rstrip(".")
        if stripped == cleaned:
            break
        cleaned = stripped
    candidate = cleaned.lower()
    if not _DOI_FLOOR.match(candidate):
        raise IdentifierError(
            CODE_NOT_A_DOI,
            f"'{candidate}' is not a DOI: the structural floor is "
            "'10.' + registrant digits + '/' + a non-empty suffix",
        )
    return candidate


def normalize_pmid(raw: str) -> str:
    """Return the canonical form of a PMID: bare digits, no leading zeros.

    Accepts bare digit strings and ``PMID:``-prefixed forms (case
    -insensitive, optional space). Raises IdentifierError with code
    ``pmcid_not_pmid`` for PMC identifiers (a different thing, refused by
    name rather than silently treated as a PMID), ``not_a_pmid`` for
    anything containing non-digits, and ``empty_input`` for empty input.
    """
    cleaned = _require_nonempty(_clean(raw))
    cleaned = _PMID_PREFIX.sub("", cleaned, count=1).strip()
    if not cleaned:
        raise IdentifierError(
            CODE_EMPTY_INPUT, "identifier is empty after the PMID: prefix"
        )
    if _PMCID.match(cleaned) and cleaned.lower().startswith("pmc"):
        raise IdentifierError(
            CODE_PMCID_NOT_PMID,
            f"'{cleaned}' is a PMCID (a PubMed Central ID), not a PMID; "
            "this library stores PMIDs",
        )
    if not cleaned.isdigit():
        raise IdentifierError(
            CODE_NOT_A_PMID,
            f"'{cleaned}' is not a PMID: PMIDs are bare digits",
        )
    return str(int(cleaned))


def parse_identifier(raw: str) -> "Identifier":
    """Decide which kind of identifier a string is, or refuse by name.

    Returns an Identifier with kind "doi" or "pmid" and the canonical value.
    Refusals, each with its own code: ``empty_input``; ``pmcid_not_pmid``
    (PMC identifiers are their own named case); ``unrecognized_identifier``
    (nothing this library knows how to verify); plus whatever
    normalize_doi/normalize_pmid raise for well-labeled but malformed
    values (``not_a_doi``, ``not_a_pmid``).
    """
    cleaned = _require_nonempty(_clean(raw))
    lowered = cleaned.lower()
    if lowered.startswith("pmcid:") or _PMCID.match(cleaned):
        raise IdentifierError(
            CODE_PMCID_NOT_PMID,
            f"'{cleaned}' is a PMCID (a PubMed Central ID), not a PMID; "
            "this library stores PMIDs",
        )
    if (
        lowered.startswith("doi:")
        or lowered.startswith("https://doi.org/")
        or lowered.startswith("http://doi.org/")
        or lowered.startswith("https://dx.doi.org/")
        or lowered.startswith("http://dx.doi.org/")
        or cleaned.startswith("10.")
    ):
        return Identifier("doi", normalize_doi(cleaned))
    if lowered.startswith("pmid:") or cleaned.isdigit():
        return Identifier("pmid", normalize_pmid(cleaned))
    raise IdentifierError(
        CODE_UNRECOGNIZED_IDENTIFIER,
        f"'{cleaned}' is not an identifier this library recognizes "
        "(expected a DOI or a PMID)",
    )
