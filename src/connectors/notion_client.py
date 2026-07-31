"""Notion connector — the four main Weybourne databases plus preference pages.

Live mode uses the Notion REST API with an integration token and the database
IDs from config. When ``NOTION_TOKEN`` is unset, the connector serves sample
records (mock mode) grounded in the real workspace so dedupe/screening screens
are demonstrable offline.

Property parsing follows the Property Guidebook:
  Contacts — Name (title), Email (email; the unique key), Title, Type, Employed By
  Companies — Name (title), Description, City, Country
  Funds — Name (title), Asset Class (multi), Geographic Focus (multi),
          Strategy Description, Status, Company
"""
from __future__ import annotations

from typing import Optional

from src import config
from src.schemas import CompanyRecord, ContactRecord, FundRecord

# --------------------------------------------------------------------------- #
# Sample data (mock mode)
# --------------------------------------------------------------------------- #

_SAMPLE_CONTACTS = [
    ContactRecord(id="c1", name="Catherine Wu", email="catherine@pitingcapital.com",
                  title="Portfolio Manager", type="GP - Investments", company="Piting Capital"),
    ContactRecord(id="c2", name="Jesús Argüelles", email="jarguelles@irvine.org",
                  title="Managing Director (Investments)", type="LP - Institutional / SFO",
                  company="The James Irvine Foundation"),
    ContactRecord(id="c3", name="Josh Katzin", email="josh@cavamont.com",
                  title="Partner", type="GP - Investments", company="Cavamont"),
]

_SAMPLE_COMPANIES = [
    CompanyRecord(id="co1", name="Piting Capital", description="China A-share long/short manager",
                  city="Hong Kong", country="China", domain="pitingcapital.com"),
    CompanyRecord(id="co2", name="Cavamont", description="Multi-strategy allocator",
                  city="London", country="UK", domain="cavamont.com"),
    CompanyRecord(id="co3", name="Dockside Platforms", description="Risk analytics platform",
                  city="New York", country="US", domain="dockside.com"),
]

_SAMPLE_FUNDS = [
    FundRecord(id="f1", name="Piting Capital Fund", asset_class=["Hedge Funds - Equity L/S"],
               geographic_focus=["🇨🇳 China"], status="Track",
               strategy_description="China A-share long/short.", company="Piting Capital"),
    FundRecord(id="f2", name="Capitala SBIC Fund VI, LP", asset_class=["Private Credit - Direct Lending"],
               geographic_focus=["🇺🇸 US"], status="Not reviewed",
               strategy_description="Lower-mid-market debt with minority equity co-invest.",
               company="Capitala Group"),
]


# --------------------------------------------------------------------------- #
# Connector
# --------------------------------------------------------------------------- #

class NotionConnector:
    def __init__(self):
        self.live = config.notion_configured()

    # -- low-level -------------------------------------------------------- #
    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {config.NOTION_TOKEN}",
            "Notion-Version": config.NOTION_VERSION,
            "Content-Type": "application/json",
        }

    def _query_db(self, db_id: str, page_size: int = 100) -> list[dict]:
        import requests

        results, cursor = [], None
        while True:
            payload = {"page_size": page_size}
            if cursor:
                payload["start_cursor"] = cursor
            resp = requests.post(
                f"{config.NOTION_BASE_URL}/databases/{db_id}/query",
                headers=self._headers(),
                json=payload,
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            results.extend(data.get("results", []))
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
        return results

    # -- reads: main databases ------------------------------------------- #
    def list_contacts(self) -> list[ContactRecord]:
        if not self.live or not config.NOTION_CONTACTS_DB:
            return list(_SAMPLE_CONTACTS)
        return [_contact_from_page(p) for p in self._query_db(config.NOTION_CONTACTS_DB)]

    def list_companies(self) -> list[CompanyRecord]:
        if not self.live or not config.NOTION_COMPANIES_DB:
            return list(_SAMPLE_COMPANIES)
        return [_company_from_page(p) for p in self._query_db(config.NOTION_COMPANIES_DB)]

    def list_funds(self) -> list[FundRecord]:
        if not self.live or not config.NOTION_FUNDS_DB:
            return list(_SAMPLE_FUNDS)
        return [_fund_from_page(p) for p in self._query_db(config.NOTION_FUNDS_DB)]

    # -- reads: page text (CHAO preference pages, notes) ----------------- #
    def get_page_text(self, page_id: str, max_depth: int = 2) -> str:
        """Return the plain-text content of a page (recursively, shallow)."""
        if not self.live:
            return _SAMPLE_PREF_TEXT.get(page_id, "")
        return self._blocks_text(page_id, depth=0, max_depth=max_depth)

    def _blocks_text(self, block_id: str, depth: int, max_depth: int) -> str:
        import requests

        lines, cursor = [], None
        while True:
            resp = requests.get(
                f"{config.NOTION_BASE_URL}/blocks/{block_id}/children",
                headers=self._headers(),
                params={"page_size": 100, **({"start_cursor": cursor} if cursor else {})},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            for block in data.get("results", []):
                lines.append(_block_plain_text(block))
                if block.get("has_children") and depth < max_depth:
                    lines.append(self._blocks_text(block["id"], depth + 1, max_depth))
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
        return "\n".join(l for l in lines if l)

    # -- writes ----------------------------------------------------------- #
    def create_page(self, db_id: str, properties: dict) -> dict:
        """Create a page in a database. No-op preview in mock mode."""
        if not self.live:
            return {"id": "mock-page", "url": "https://notion.so/mock", "mock": True,
                    "properties_preview": properties}
        import requests

        resp = requests.post(
            f"{config.NOTION_BASE_URL}/pages",
            headers=self._headers(),
            json={"parent": {"database_id": db_id}, "properties": properties},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()


# --------------------------------------------------------------------------- #
# Property parsers
# --------------------------------------------------------------------------- #

def _prop(page: dict, name: str) -> dict:
    return (page.get("properties") or {}).get(name, {}) or {}


def _title(page: dict, name: str) -> str:
    return "".join(t.get("plain_text", "") for t in _prop(page, name).get("title", []))


def _rich(page: dict, name: str) -> str:
    return "".join(t.get("plain_text", "") for t in _prop(page, name).get("rich_text", []))


def _email(page: dict, name: str) -> str:
    return _prop(page, name).get("email") or ""


def _select(page: dict, name: str) -> str:
    sel = _prop(page, name).get("select")
    return sel.get("name", "") if sel else ""


def _status(page: dict, name: str) -> str:
    st = _prop(page, name).get("status")
    return st.get("name", "") if st else ""


def _multi(page: dict, name: str) -> list[str]:
    return [o.get("name", "") for o in _prop(page, name).get("multi_select", [])]


def _contact_from_page(p: dict) -> ContactRecord:
    return ContactRecord(
        id=p.get("id"),
        name=_title(p, "Name"),
        email=_email(p, "Email"),
        title=_rich(p, "Title") or _select(p, "Title"),
        type=_select(p, "Type"),
    )


def _company_from_page(p: dict) -> CompanyRecord:
    name = _title(p, "Name")
    return CompanyRecord(
        id=p.get("id"),
        name=name,
        description=_rich(p, "Description"),
        city=_rich(p, "City"),
        country=_rich(p, "Country"),
    )


def _fund_from_page(p: dict) -> FundRecord:
    return FundRecord(
        id=p.get("id"),
        name=_title(p, "Name"),
        asset_class=_multi(p, "Asset Class"),
        geographic_focus=_multi(p, "Geographic Focus"),
        strategy_description=_rich(p, "Strategy Description"),
        status=_status(p, "Status") or _select(p, "Status"),
    )


def _block_plain_text(block: dict) -> str:
    btype = block.get("type", "")
    payload = block.get(btype, {}) or {}
    rich = payload.get("rich_text", [])
    text = "".join(t.get("plain_text", "") for t in rich)
    if btype in ("heading_1", "heading_2", "heading_3") and text:
        return f"## {text}"
    if btype in ("bulleted_list_item", "numbered_list_item") and text:
        return f"- {text}"
    return text


# Minimal offline stand-in so the CHAO screening screen works without Notion.
_SAMPLE_PREF_TEXT = {
    config.CHAO_PAGES["general"]: (
        "General preferences: prefer concentrated, high-conviction manager relationships. "
        "Communication is direct and to the point. Expand acronyms on first use."
    ),
    config.CHAO_PAGES["private_growth"]: (
        "Private Growth — growth engine exploiting illiquidity premium. Target nominal >11% p.a., "
        "real >US CPI + 8%. 7-10yr horizons; commitments 7.5-15% of NAV; ~40 managers steady state. "
        "Bottom-up manager underwriting; weight to PE and venture. All exposure via managers, no direct."
    ),
    config.CHAO_PAGES["public_growth"]: (
        "Public Growth — directional public equity; nominal >7% p.a., real >US CPI + 4%; beat FTSE All "
        "World. Prefer actively managed strategies to outperform benchmarks."
    ),
    config.CHAO_PAGES["diversifiers"]: (
        "Diversifiers — returns NOT explained by market/credit factors. Multi-strat, relative value, "
        "macro, trend/managed futures, alt risk premia, niche (ILS), gold, commodities, bitcoin. "
        "Nominal >5% p.a., real >US CPI + 2%; max 0.50 correlation to FTSE All World; 3-12m liquidity."
    ),
    config.CHAO_PAGES["learnings"]: (
        "Learnings — do not regurgitate a manager's own claims; verify mechanism and evidence; "
        "exclude table-stakes attractions; surface the most obvious deal-specific risk even if outside "
        "stated preferences."
    ),
}


def sleeve_page_id(sleeve: str) -> Optional[str]:
    """Map a strategy sleeve name to its CHAO preference page id."""
    return {
        "Private Growth": config.CHAO_PAGES["private_growth"],
        "Public Growth": config.CHAO_PAGES["public_growth"],
        "Diversifiers": config.CHAO_PAGES["diversifiers"],
    }.get(sleeve)
