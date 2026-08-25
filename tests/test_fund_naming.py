"""Fund names must identify the fund, and Weybourne Comments belongs to the desk."""
from src.features.notion_sync import fund_properties, qualified_fund_name
from src.schemas import ExtractedEntity


def _title(props):
    return "".join(t["text"]["content"] for t in props["Name"]["title"])


class TestQualifiedFundName:
    def test_a_bare_vintage_gets_its_manager(self):
        # Letters say "Fund VI" because the letterhead supplies the rest. A CRM
        # row has no letterhead.
        assert qualified_fund_name("Fund VI", "Unicorn Partners") == "Unicorn Partners Fund VI"

    def test_arabic_numerals_too(self):
        assert qualified_fund_name("Fund 3", "Acme") == "Acme Fund 3"

    def test_a_leading_the_is_not_carried_through(self):
        # Rebuilt rather than prefixed, so this is not "Acme The Fund IV".
        assert qualified_fund_name("The Fund IV", "Acme") == "Acme Fund IV"

    def test_lowercase_is_normalised(self):
        assert qualified_fund_name("fund iv", "Acme") == "Acme Fund IV"

    def test_a_name_that_already_identifies_itself_is_untouched(self):
        # A fund name is a proper noun; this repairs one specific failure and
        # must not tidy anything else.
        for name in ("Hayfin Healthcare Opportunities Fund", "01 Advisors Fund IV",
                     "Fund of Funds", "Fundamental Growth", "Project Loki"):
            assert qualified_fund_name(name, "Acme") == name

    def test_a_name_already_starting_with_the_manager_is_untouched(self):
        assert (qualified_fund_name("Unicorn Partners Fund VI", "Unicorn Partners")
                == "Unicorn Partners Fund VI")

    def test_no_manager_means_no_guess(self):
        assert qualified_fund_name("Fund VI", "") == "Fund VI"
        assert qualified_fund_name("", "Acme") == ""


class TestFundProperties:
    ENTITY = ExtractedEntity(fund_name="Fund VI", company_name="Unicorn Partners",
                             strategy_description="China venture investments.",
                             asset_class="Venture Capital", geography="China")

    def test_the_written_name_is_the_qualified_one(self):
        assert _title(fund_properties(self.ENTITY)) == "Unicorn Partners Fund VI"

    def test_weybourne_comments_is_absent_on_a_new_fund(self):
        # The field is the desk's own standing record of a position — commitment
        # sizes, drawdown dates, who introduced whom. Seeding it from the email
        # that created the row wrote a description of one message into a field
        # read as fact.
        assert "Weybourne Comments" not in fund_properties(self.ENTITY)

    def test_comments_are_still_written_when_explicitly_supplied(self):
        # The parameter stays, so a caller that genuinely has desk commentary
        # (not an email summary) can still set it.
        props = fund_properties(self.ENTITY, comments="US$31m commitment approved.")
        assert props["Weybourne Comments"]["rich_text"][0]["text"]["content"] \
            == "US$31m commitment approved."

    def test_a_new_fund_still_enters_unreviewed(self):
        assert fund_properties(self.ENTITY)["Status"]["status"]["name"] == "Not reviewed"
