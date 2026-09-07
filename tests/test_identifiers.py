"""T-07: identifier normalization — pure functions, no network, no I/O.

Researchers paste identifiers in every shape. This suite pins what each
shape becomes and what each malformed shape is refused AS — a named error
per malformed class, never a silent guess.
"""

import pytest

from citebind.identifiers import (
    CODE_EMPTY_INPUT,
    CODE_NOT_A_DOI,
    CODE_NOT_A_PMID,
    CODE_PMCID_NOT_PMID,
    CODE_UNRECOGNIZED_IDENTIFIER,
    IdentifierError,
    normalize_doi,
    normalize_pmid,
    parse_identifier,
)


# --- DOI normalization: every spelling becomes one canonical form --------------


def test_normalize_doi_accepts_bare_doi():
    assert normalize_doi("10.2147/prom.s8896") == "10.2147/prom.s8896"


def test_normalize_doi_strips_https_doi_org():
    assert normalize_doi("https://doi.org/10.2147/prom.s8896") == "10.2147/prom.s8896"


def test_normalize_doi_strips_http_dx_doi_org():
    assert normalize_doi("http://dx.doi.org/10.2147/prom.s8896") == "10.2147/prom.s8896"


def test_normalize_doi_strips_doi_prefix():
    assert normalize_doi("doi:10.2147/prom.s8896") == "10.2147/prom.s8896"


def test_normalize_doi_lowercases_and_states_it():
    # The canonical form is all-lowercase. This decision is load-bearing:
    # duplicate detection depends on two case spellings folding together.
    assert normalize_doi("10.2147/PROM.S8896") == "10.2147/prom.s8896"
    assert normalize_doi("DOI:10.2147/Prom.S8896") == "10.2147/prom.s8896"
    assert "lowercase" in normalize_doi.__doc__


def test_normalize_doi_strips_trailing_period_from_pasted_sentence():
    # the DOI itself carries a sentence-final period from the paste; full
    # sentence extraction is out of scope
    assert normalize_doi("10.2147/prom.s8896.") == "10.2147/prom.s8896"


def test_normalize_doi_strips_whitespace_and_zero_width_characters():
    assert normalize_doi("  10.2147/prom.s8896  ") == "10.2147/prom.s8896"
    assert normalize_doi("10.2147\u200b/prom.s8896") == "10.2147/prom.s8896"
    assert normalize_doi("\u200f10.2147/prom.s8896\ufeff") == "10.2147/prom.s8896"
    assert normalize_doi("10.\u00ad2147/prom.s8896") == "10.2147/prom.s8896"


@pytest.mark.parametrize(
    "a, b",
    [
        ("10.2147/prom.s8896", "https://doi.org/10.2147/prom.s8896."),
        ("DOI:10.2147/PROM.S8896", "10.2147/prom.s8896"),
        ("http://dx.doi.org/10.2147/Prom.S8896", " doi:10.2147/prom.s8896 "),
    ],
)
def test_two_spellings_of_one_doi_normalize_equal(a, b):
    assert normalize_doi(a) == normalize_doi(b)


# --- DOI refusals: the structural floor is 10. + registrant + / + suffix -------


def test_normalize_doi_refuses_missing_10_prefix():
    with pytest.raises(IdentifierError) as e:
        normalize_doi("2147/prom.s8896")
    assert e.value.code == CODE_NOT_A_DOI


def test_normalize_doi_refuses_registrant_without_slash():
    with pytest.raises(IdentifierError) as e:
        normalize_doi("10.2147")
    assert e.value.code == CODE_NOT_A_DOI


def test_normalize_doi_refuses_empty_suffix():
    with pytest.raises(IdentifierError) as e:
        normalize_doi("10.2147/")
    assert e.value.code == CODE_NOT_A_DOI


def test_normalize_doi_refuses_internal_whitespace():
    with pytest.raises(IdentifierError) as e:
        normalize_doi("10.2147 / prom.s8896")
    assert e.value.code == CODE_NOT_A_DOI


def test_normalize_doi_refuses_a_pmid():
    with pytest.raises(IdentifierError) as e:
        normalize_doi("12345678")
    assert e.value.code == CODE_NOT_A_DOI


def test_normalize_doi_refuses_empty_variants():
    for raw in ["", "   ", "\u200b\u200c"]:
        with pytest.raises(IdentifierError) as e:
            normalize_doi(raw)
        assert e.value.code == CODE_EMPTY_INPUT


# --- PMID normalization ---------------------------------------------------------


def test_normalize_pmid_accepts_bare_digits():
    assert normalize_pmid("12345678") == "12345678"


def test_normalize_pmid_strips_prefix_and_whitespace():
    assert normalize_pmid("PMID: 12345678") == "12345678"
    assert normalize_pmid("pmid:12345678") == "12345678"


def test_normalize_pmid_canonicalizes_leading_zeros():
    # PMIDs are integers; 01234567 and 1234567 must be detected as the same
    # record, so the canonical form drops leading zeros.
    assert normalize_pmid("01234567") == "1234567"


def test_normalize_pmid_refuses_letters():
    with pytest.raises(IdentifierError) as e:
        normalize_pmid("12a45678")
    assert e.value.code == CODE_NOT_A_PMID


def test_normalize_pmid_refuses_a_doi():
    with pytest.raises(IdentifierError) as e:
        normalize_pmid("10.2147/prom.s8896")
    assert e.value.code == CODE_NOT_A_PMID


# --- PMCID is its own named refusal, never a PMID -------------------------------


@pytest.mark.parametrize("raw", ["PMC1234567", "pmc1234567", "PMCID: PMC1234567"])
def test_pmcid_is_refused_as_its_own_named_case(raw):
    for fn in (normalize_pmid, parse_identifier):
        with pytest.raises(IdentifierError) as e:
            fn(raw)
        assert e.value.code == CODE_PMCID_NOT_PMID


def test_pmcid_error_message_says_what_it_is():
    with pytest.raises(IdentifierError) as e:
        normalize_pmid("PMC1234567")
    assert "PMCID" in str(e.value)
    assert "PMID" in str(e.value)


# --- parse_identifier: decides the kind, or refuses by name ---------------------


def test_parse_identifier_classifies_a_doi():
    ident = parse_identifier("https://doi.org/10.2147/prom.s8896")
    assert ident.kind == "doi"
    assert ident.value == "10.2147/prom.s8896"


def test_parse_identifier_classifies_a_pmid():
    ident = parse_identifier("PMID: 12345678")
    assert ident.kind == "pmid"
    assert ident.value == "12345678"


def test_parse_identifier_refuses_unknown_identifier_kinds_by_name():
    with pytest.raises(IdentifierError) as e:
        parse_identifier("ISBN 978-3-16-148410-0")
    assert e.value.code == CODE_UNRECOGNIZED_IDENTIFIER


def test_parse_identifier_refuses_empty_input_by_name():
    with pytest.raises(IdentifierError) as e:
        parse_identifier("   ")
    assert e.value.code == CODE_EMPTY_INPUT


def test_the_named_refusal_codes_are_distinct():
    codes = {
        CODE_EMPTY_INPUT,
        CODE_NOT_A_DOI,
        CODE_NOT_A_PMID,
        CODE_PMCID_NOT_PMID,
        CODE_UNRECOGNIZED_IDENTIFIER,
    }
    assert len(codes) == 5


@pytest.mark.parametrize("raw", ["0", "00", "0000000", "PMID:0", " 0 "])
def test_pmid_zero_is_refused_by_name(raw):
    """REGRESSION. Leading-zero stripping turned "0" into the canonical PMID
    "0", which PubMed never assigns — it numbers from 1. The request would
    have gone out and come back empty, and an empty PubMed result reads like
    "this record was withdrawn" rather than "you asked for a number that is
    not an identifier"."""
    with pytest.raises(IdentifierError) as caught:
        normalize_pmid(raw)
    assert caught.value.code == CODE_NOT_A_PMID
