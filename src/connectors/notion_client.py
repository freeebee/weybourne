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


_SAMPLE_RECENT_NOTES = [
    {"title": "Call with Axiom Asia", "date": "2026-07-30", "note_type": "GP Meeting",
     "attendees": "J. Chen; L. Tan (Axiom)", "url": "",
     "excerpt": "Fund VII pacing discussed; capacity story rests on two repeat GPs. "
                "Co-invest terms improved vs Fund VI. Follow-up: reference calls on the "
                "new Southeast Asia partner."},
    {"title": "Meeting with REVA", "date": "2026-07-29", "note_type": "GP Meeting",
     "attendees": "J. Chen; M. Osei (REVA)", "url": "",
     "excerpt": "Fund II raising at $400m target, 40% soft-circled. DPI on Fund I still "
                "0.3x — marks driven by two 2021 vintages. We remain cautious on "
                "valuation discipline."},
    {"title": "Reference call — Piting Capital", "date": "2026-07-28",
     "note_type": "Reference call", "attendees": "J. Chen", "url": "",
     "excerpt": "Former LP confirms the risk process is real; flagged turnover in the "
                "quant team during 2024. Worth probing key-person cover."},
]

_SAMPLE_EXECUTION_ITEMS = [
    {"title": "Axiom Asia Fund VII — legal review", "status": "In progress",
     "updated": "2026-07-31", "detail": "LPA with counsel; side-letter asks drafted."},
    {"title": "Capitala SBIC VI — subscription docs", "status": "Completed",
     "updated": "2026-07-29", "detail": "Signed and countersigned; wire scheduled."},
    {"title": "Q2 portfolio valuation pack", "status": "New",
     "updated": "2026-07-28", "detail": "Added to the monitoring queue for August."},
    {"title": "Piting Capital — redemption notice window", "status": "Completed",
     "updated": "2026-07-27", "detail": "Notice period confirmed; no action this quarter."},
]


# --------------------------------------------------------------------------- #
# Connector
# --------------------------------------------------------------------------- #

class NotionConnector:
    # The live workspace holds ~10k contacts / ~8k companies. Full pulls take
    # minutes, so three layers keep reads fast:
    #   1. an in-memory cache (10 min) for within-process speed,
    #   2. a persistent disk snapshot (data/notion_cache.json) so restarts
    #      don't re-pull the workspace,
    #   3. delta sync — only pages edited since the last sync are fetched and
    #      merged into the snapshot. A full re-pull happens if the snapshot is
    #      older than 7 days (deltas can't see deletions/archives).
    _LIST_CACHE_TTL = 600        # seconds, in-memory
    _FULL_REFRESH_AFTER = 7 * 86400  # seconds, disk snapshot age forcing full pull

    def __init__(self):
        self.live = config.notion_configured()
        self._list_cache: dict = {}

    def _cached(self, key: str, loader):
        import time

        hit = self._list_cache.get(key)
        if hit and time.time() - hit[0] < self._LIST_CACHE_TTL:
            return hit[1]
        value = loader()
        self._list_cache[key] = (time.time(), value)
        return value

    # -- persistent snapshot + delta sync --------------------------------- #

    _DISK_PATH = config.BASE_DIR / "data" / "notion_cache.json"

    def _disk_load(self) -> dict:
        import json
        try:
            return json.loads(self._DISK_PATH.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - absent or corrupt → start fresh
            return {}

    def _disk_save(self, store: dict) -> None:
        import json
        try:
            self._DISK_PATH.parent.mkdir(parents=True, exist_ok=True)
            self._DISK_PATH.write_text(json.dumps(store, ensure_ascii=False),
                                       encoding="utf-8")
        except Exception:  # noqa: BLE001 - a failed save just means a re-pull later
            pass

    def _collection(self, key: str, db_id: str, parse, model,
                    property_ids: Optional[list] = None) -> list:
        """Load a big collection via memory → disk snapshot → delta sync."""
        import datetime as dt
        import time

        def load():
            store = self._disk_load()
            entry = store.get(key)
            pull_started = dt.datetime.now(dt.timezone.utc).isoformat()

            fresh_enough = (
                entry
                and (time.time() - entry.get("saved_epoch", 0)) < self._FULL_REFRESH_AFTER
            )
            if fresh_enough:
                # Delta: only pages edited since the last sync.
                pages = self._query_db(
                    db_id,
                    filter_payload={"timestamp": "last_edited_time",
                                    "last_edited_time":
                                        {"on_or_after": entry["synced_at"]}},
                    property_ids=property_ids,
                )
                records = {r["id"]: r for r in entry["records"]}
                for p in pages:
                    parsed = parse(p).model_dump()
                    records[parsed.get("id") or p["id"]] = parsed
                merged = list(records.values())
            else:
                pages = self._query_db(db_id, property_ids=property_ids)
                merged = [parse(p).model_dump() for p in pages]

            store[key] = {"synced_at": pull_started,
                          "saved_epoch": entry.get("saved_epoch", time.time())
                              if fresh_enough else time.time(),
                          "records": merged}
            self._disk_save(store)
            return [model(**r) for r in merged]

        return self._cached(key, load)

    # -- low-level -------------------------------------------------------- #
    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {config.NOTION_TOKEN}",
            "Notion-Version": config.NOTION_VERSION,
            "Content-Type": "application/json",
        }

    def _query_db(self, db_id: str, page_size: int = 100,
                  filter_payload: Optional[dict] = None,
                  sorts: Optional[list] = None,
                  property_ids: Optional[list] = None) -> list[dict]:
        """Paginated query with 5xx resilience.

        Live databases can 500 server-side — either on payload size or on a
        specific row whose formula/rollup property errors inside Notion. On a
        5xx the page size is halved and retried; if a tiny page still 500s the
        rows fetched so far are returned rather than failing the caller (the
        app degrades to a partial list instead of a dead feature).

        ``property_ids`` (Notion property IDs, not names) narrows the returned
        properties via filter_properties — both smaller payloads and a way to
        avoid pathological computed properties entirely.
        """
        import sys
        import time

        import requests

        url = f"{config.NOTION_BASE_URL}/databases/{db_id}/query"
        params = [("filter_properties", pid) for pid in (property_ids or [])]

        results, cursor = [], None
        size = page_size
        while True:
            payload = {"page_size": size}
            if filter_payload:
                payload["filter"] = filter_payload
            if sorts:
                payload["sorts"] = sorts
            if cursor:
                payload["start_cursor"] = cursor
            try:
                resp = requests.post(url, headers=self._headers(), params=params,
                                     json=payload, timeout=90)
            except (requests.exceptions.Timeout,
                    requests.exceptions.ConnectionError) as e:
                if size > 5:
                    size = max(5, size // 4)
                    time.sleep(1)
                    continue
                print(f"[notion] {type(e).__name__} on {db_id} after "
                      f"{len(results)} rows — returning partial list",
                      file=sys.stderr)
                break
            if resp.status_code >= 500:
                if size > 5:
                    size = max(5, size // 4)
                    time.sleep(1)
                    continue
                print(f"[notion] persistent 5xx on {db_id} after "
                      f"{len(results)} rows — returning partial list",
                      file=sys.stderr)
                break
            if resp.status_code == 429:
                time.sleep(float(resp.headers.get("Retry-After", 1)))
                continue
            resp.raise_for_status()
            data = resp.json()
            results.extend(data.get("results", []))
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
        return results

    def _property_ids(self, db_id: str, names: list[str]) -> list[str]:
        """Property IDs for the given property names (empty on any failure)."""
        import requests

        try:
            resp = requests.get(f"{config.NOTION_BASE_URL}/databases/{db_id}",
                                headers=self._headers(), timeout=30)
            resp.raise_for_status()
            props = resp.json().get("properties", {})
            return [v["id"] for k, v in props.items() if k in names]
        except Exception:  # noqa: BLE001 - narrowing is an optimisation only
            return []

    # -- reads: main databases ------------------------------------------- #
    def list_contacts(self) -> list[ContactRecord]:
        if not self.live or not config.NOTION_CONTACTS_DB:
            return list(_SAMPLE_CONTACTS)
        return self._collection("contacts", config.NOTION_CONTACTS_DB,
                                _contact_from_page, ContactRecord)

    def list_companies(self) -> list[CompanyRecord]:
        if not self.live or not config.NOTION_COMPANIES_DB:
            return list(_SAMPLE_COMPANIES)
        return self._collection("companies", config.NOTION_COMPANIES_DB,
                                _company_from_page, CompanyRecord)

    def list_funds(self) -> list[FundRecord]:
        if not self.live or not config.NOTION_FUNDS_DB:
            return list(_SAMPLE_FUNDS)
        # Only the properties the app reads: the Funds DB has computed
        # properties that 500 inside Notion when evaluated for some rows.
        pids = self._property_ids(config.NOTION_FUNDS_DB, [
            "Fund Name", "Name", "Asset Class", "Geographic Focus",
            "Strategy Description", "Status", "Company Name",
        ])
        return self._collection("funds", config.NOTION_FUNDS_DB,
                                _fund_from_page, FundRecord, property_ids=pids)

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

    # -- reads: What's new ------------------------------------------------ #
    def list_recent_notes(self, days: int = 7) -> list[dict]:
        """Meeting notes edited in the window: title/date/type/attendees/excerpt."""
        if not self.live or not config.NOTION_NOTES_DB:
            return list(_SAMPLE_RECENT_NOTES)
        import datetime as dt

        since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
        pages = self._query_db(
            config.NOTION_NOTES_DB,
            filter_payload={"timestamp": "last_edited_time",
                            "last_edited_time": {"on_or_after": since}},
            sorts=[{"timestamp": "last_edited_time", "direction": "descending"}],
        )
        notes = []
        for p in pages:
            notes.append({
                "title": _title(p, "Name"),
                "date": (_prop(p, "Date").get("date") or {}).get("start", "")
                        or p.get("last_edited_time", "")[:10],
                "note_type": _select(p, "Note Type"),
                "attendees": "",  # relation ids only; names need extra fetches
                "url": p.get("url", ""),
                "excerpt": _rich(p, "Thoughts / Considerations"),
            })
        return notes

    def list_execution_items(self, days: int = 7) -> list[dict]:
        """FI execution monitoring dashboard items edited in the window.

        The dashboard's exact schema isn't assumed: the title property is found
        by type, and the first status/select property is used as the status.
        """
        if not self.live or not config.NOTION_EXECUTION_DB:
            return list(_SAMPLE_EXECUTION_ITEMS)
        import datetime as dt

        since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
        pages = self._query_db(
            config.NOTION_EXECUTION_DB,
            filter_payload={"timestamp": "last_edited_time",
                            "last_edited_time": {"on_or_after": since}},
            sorts=[{"timestamp": "last_edited_time", "direction": "descending"}],
        )
        items = []
        for p in pages:
            props = p.get("properties") or {}
            title = next((("".join(t.get("plain_text", "") for t in v.get("title", [])))
                          for v in props.values() if v.get("type") == "title"), "")
            status = next((v.get("status", {}).get("name", "")
                           for v in props.values() if v.get("type") == "status"), "") \
                or next((v.get("select", {}).get("name", "")
                         for v in props.values() if v.get("type") == "select"), "")
            detail = next((("".join(t.get("plain_text", "") for t in v.get("rich_text", [])))
                           for v in props.values() if v.get("type") == "rich_text"), "")
            items.append({
                "title": title, "status": status or "Updated",
                "updated": p.get("last_edited_time", "")[:10],
                "detail": detail, "url": p.get("url", ""),
            })
        return items

    # -- writes ----------------------------------------------------------- #
    def create_page(self, db_id: str, properties: dict,
                    children: Optional[list] = None) -> dict:
        """Create a page in a database. No-op preview in mock mode.

        ``children`` are Notion block objects for the page body (e.g. the full
        text of an email saved as a note).
        """
        if not self.live:
            return {"id": "mock-page", "url": "https://notion.so/mock", "mock": True,
                    "properties_preview": properties}
        import requests

        payload = {"parent": {"database_id": db_id}, "properties": properties}
        if children:
            payload["children"] = children[:100]   # Notion caps children per request
        resp = requests.post(
            f"{config.NOTION_BASE_URL}/pages",
            headers=self._headers(),
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def update_page(self, page_id: str, properties: dict) -> dict:
        """Update properties on an existing page. No-op preview in mock mode."""
        if not self.live:
            return {"id": page_id, "url": "https://notion.so/mock", "mock": True,
                    "properties_preview": properties}
        import requests

        resp = requests.patch(
            f"{config.NOTION_BASE_URL}/pages/{page_id}",
            headers=self._headers(),
            json={"properties": properties},
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
    # The live Funds DB titles the page 'Fund Name' and carries the manager as
    # 'Company Name' (rich text); accept the guidebook's 'Name' as fallback.
    return FundRecord(
        id=p.get("id"),
        name=_title(p, "Fund Name") or _title(p, "Name"),
        asset_class=_multi(p, "Asset Class"),
        geographic_focus=_multi(p, "Geographic Focus"),
        strategy_description=_rich(p, "Strategy Description"),
        status=_status(p, "Status") or _select(p, "Status"),
        company=_rich(p, "Company Name"),
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
