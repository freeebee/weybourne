"""A shared name is not a shared identity.

Two people called Amy Zhao, at two different firms, with two different email
addresses, were being merged at High confidence on an "exact name match" —
no adjudication, no web check, the survivor chosen by which record looked
richer. An email is an identifier; a name is not.
"""
from src.features.felix import detect


def card(cid, name, email="", employers=(), archived=False):
    return {
        "id": cid, "db": "contacts", "name": name, "title_prop": "Name",
        "email": email, "domain": email.split("@")[-1] if email else "",
        "url": f"https://notion.so/{cid}", "icon": None, "archived": archived,
        "created": "2026-01-01", "edited": "2026-01-01",
        "plain": {"Name": name}, "raw": {},
        "relations": {"🏢 Employed By": list(employers)},
    }


class TestContested:
    def test_different_employers_contest_a_name_match(self):
        group = detect.group_is_contested([
            card("a", "Amy Zhao", employers=["bai"]),
            card("b", "Amy Zhao", employers=["openspace"]),
        ])
        assert "different companies" in group

    def test_different_emails_contest_a_name_match(self):
        group = detect.group_is_contested([
            card("a", "Amy Zhao", email="amy.zhao@baifund.com"),
            card("b", "Amy Zhao", email="amy@openspace.vc"),
        ])
        assert "different email" in group

    def test_the_emoji_prefixed_employer_property_is_read(self):
        """The workspace calls it '🏢 Employed By'; literal matching missed it."""
        c = card("a", "Amy Zhao", employers=["bai"])
        assert detect.employers_of(c) == {"bai"}

    def test_nothing_contradicting_is_not_contested(self):
        assert detect.group_is_contested([
            card("a", "Amy Zhao", employers=["bai"]),
            card("b", "Amy Zhao"),
        ]) == ""

    def test_one_employer_absent_does_not_contest(self):
        """An empty field is not a disagreement — that is what Felix fills in."""
        assert detect.group_is_contested([
            card("a", "Amy Zhao", email="amy@bai.com"),
            card("b", "Amy Zhao"),
        ]) == ""

    def test_a_shared_employer_is_not_contested(self):
        assert detect.group_is_contested([
            card("a", "Amy Zhao", employers=["bai"]),
            card("b", "Amy Zhao", employers=["bai", "other"]),
        ]) == ""


class TestGrouping:
    def test_a_contested_name_group_is_flagged_not_merged(self):
        groups = detect.find_exact_duplicate_groups([
            card("a", "Amy Zhao", email="amy.zhao@baifund.com", employers=["bai"]),
            card("b", "Amy Zhao", email="amy@openspace.vc", employers=["openspace"]),
        ])
        name_groups = [g for g in groups if g["evidence"] == "name"]
        assert len(name_groups) == 1
        assert name_groups[0]["contested"]

    def test_a_shared_email_stays_an_exact_duplicate(self):
        """An address really is an identifier — that merge still stands."""
        groups = detect.find_exact_duplicate_groups([
            card("a", "Amy Zhao", email="amy@bai.com"),
            card("b", "Amy Z", email="amy@bai.com"),
        ])
        email_groups = [g for g in groups if g["evidence"] == "email"]
        assert len(email_groups) == 1
        assert not email_groups[0]["contested"]

    def test_an_uncontested_name_group_stays_an_exact_duplicate(self):
        groups = detect.find_exact_duplicate_groups([
            card("a", "Amy Zhao"),
            card("b", "Amy Zhao", employers=["bai"]),
        ])
        assert [g for g in groups if g["evidence"] == "name"][0]["contested"] == ""
