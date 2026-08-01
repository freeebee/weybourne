"""Dedupe logic — the guard against creating duplicate Notion entries."""
from src.features.dedupe import (
    DUPLICATE_THRESHOLD,
    dedupe_entity,
    domain_of,
    match_company,
    match_contact,
    match_fund,
    normalize_name,
)
from src.schemas import CompanyRecord, ContactRecord, ExtractedEntity, FundRecord

CONTACTS = [
    ContactRecord(id="c1", name="Catherine Wu", email="catherine@pitingcapital.com",
                  company="Piting Capital"),
    ContactRecord(id="c2", name="Josh Katzin", email="josh@cavamont.com", company="Cavamont"),
]
COMPANIES = [
    CompanyRecord(id="co1", name="Piting Capital", domain="pitingcapital.com"),
    CompanyRecord(id="co2", name="Cavamont", domain="cavamont.com"),
]
FUNDS = [
    FundRecord(id="f1", name="Piting Capital Fund"),
    FundRecord(id="f2", name="Capitala SBIC Fund VI, LP"),
]


class TestNormalizeName:
    def test_strips_legal_and_noise_tokens(self):
        assert normalize_name("Capitala SBIC Fund VI, LP") == "capitala sbic 6"

    def test_case_and_punctuation_insensitive(self):
        assert normalize_name("Piting Capital!!") == normalize_name("piting capital")

    def test_roman_numerals_become_arabic(self):
        # A fund named with roman numerals should match its arabic-numeral twin.
        assert normalize_name("Growth Fund IV") == normalize_name("Growth 4")


def test_domain_of():
    assert domain_of("Katie.Courtney@Cendana.com") == "cendana.com"
    assert domain_of("not-an-email") == ""


class TestContactMatching:
    def test_exact_email_is_a_definite_duplicate(self):
        # Email is the unique key for Contacts per the Property Guidebook.
        decision = match_contact("catherine@pitingcapital.com", "C. Wu", CONTACTS)
        assert decision.is_duplicate
        assert decision.recommended_action == "link_existing"
        assert decision.best_match.score == 1.0

    def test_email_match_is_case_insensitive(self):
        decision = match_contact("Catherine@PitingCapital.COM", "", CONTACTS)
        assert decision.is_duplicate

    def test_new_contact_is_created(self):
        decision = match_contact("katie.courtney@cendanacapital.com", "Katie Courtney", CONTACTS)
        assert not decision.is_duplicate
        assert decision.recommended_action == "create"

    def test_similar_name_different_email_needs_review_not_auto_merge(self):
        # Two people can share a name; never silently merge on name alone.
        decision = match_contact("c.wu@othershop.com", "Catherine Wu", CONTACTS)
        assert decision.recommended_action == "review"
        assert not decision.is_duplicate


class TestCompanyMatching:
    def test_exact_domain_is_a_duplicate(self):
        decision = match_company("Piting Capital Management", "pitingcapital.com", COMPANIES)
        assert decision.is_duplicate
        assert "domain" in decision.best_match.reason

    def test_name_variant_matches_without_domain(self):
        decision = match_company("Piting Capital", "", COMPANIES)
        assert decision.best_match.score >= DUPLICATE_THRESHOLD

    def test_unrelated_company_is_new(self):
        decision = match_company("Old Well Labs", "oldwelllabs.com", COMPANIES)
        assert decision.recommended_action == "create"


class TestFundMatching:
    def test_legal_suffix_variation_still_matches(self):
        decision = match_fund("Capitala SBIC Fund VI", FUNDS)
        assert decision.is_duplicate

    def test_different_vintage_is_not_a_duplicate(self):
        # Fund VII is a genuinely different fund from Fund VI.
        decision = match_fund("Capitala SBIC Fund VII", FUNDS)
        assert not decision.is_duplicate

    def test_new_fund_is_created(self):
        decision = match_fund("Cendana Capital Fund VII", FUNDS)
        assert decision.recommended_action == "create"


class TestDedupeEntity:
    def test_runs_all_three_checks(self):
        entity = ExtractedEntity(
            fund_name="Cendana Capital Fund VII", company_name="Cendana Capital",
            company_domain="cendanacapital.com", contact_name="Katie Courtney",
            contact_email="katie.courtney@cendanacapital.com",
        )
        decisions = dedupe_entity(entity, CONTACTS, COMPANIES, FUNDS)
        assert set(decisions) == {"contact", "company", "fund"}
        assert all(d.recommended_action == "create" for d in decisions.values())

    def test_omits_checks_for_absent_fields(self):
        entity = ExtractedEntity(contact_name="Someone", contact_email="s@x.com")
        decisions = dedupe_entity(entity, CONTACTS, COMPANIES, FUNDS)
        assert set(decisions) == {"contact"}

    def test_existing_relationship_is_recognised_end_to_end(self):
        entity = ExtractedEntity(
            fund_name="Piting Capital Fund", company_name="Piting Capital",
            company_domain="pitingcapital.com", contact_name="Catherine Wu",
            contact_email="catherine@pitingcapital.com",
        )
        decisions = dedupe_entity(entity, CONTACTS, COMPANIES, FUNDS)
        assert all(d.is_duplicate for d in decisions.values())
