"""Contacts on Weybourne's own domains are colleagues, not counterparties."""
from src.features.notion_sync import default_contact_type


def test_weybourne_domains_are_internal():
    assert default_contact_type("jinghan.chen@weybourneholdings.com") == "Internal"
    assert default_contact_type("WBInvestments@Weybourne.co.uk") == "Internal"


def test_everyone_else_defaults_gp():
    assert default_contact_type("allan@fifecapital.com.au") == "GP - Investments"
    assert default_contact_type("") == "GP - Investments"
