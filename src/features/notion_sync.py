"""Turn a triaged, deduped entity into Notion pages in the main databases.

Property construction follows the Property Guidebook:
  Contacts  — Name (title), Email, Title, Type, Description
  Companies — Name (title), Description, City, Country
  Funds     — Name (title), Asset Class (multi), Geographic Focus (multi),
              Strategy Description, Status, Weybourne Comments

Two safety properties of this module:

1. **Nothing is written unless dedupe cleared it.** ``plan_creations`` only
   proposes a page where the dedupe decision is ``create``. Entities in the
   ``review`` band (a plausible but not certain match) are returned as
   proposals marked ``needs_review`` so the UI can ask a human first, and
   ``link_existing`` never creates anything.
2. **Building the payload and sending it are separate steps.** ``plan_creations``
   is pure — it can be rendered for confirmation — and only ``apply_plan``
   talks to Notion.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

from src import config
from src.connectors.notion_client import NotionConnector
from src.schemas import DedupeDecision, ExtractedEntity

EntityKind = Literal["contact", "company", "fund"]


@dataclass
class CreationProposal:
    """A single proposed Notion page, pending confirmation."""
    kind: EntityKind
    db_id: Optional[str]
    title: str
    properties: dict
    needs_review: bool = False
    review_reason: str = ""
    existing_match: Optional[str] = None


@dataclass
class SyncResult:
    created: list[tuple[str, str]] = field(default_factory=list)   # (kind, page url/id)
    skipped: list[tuple[str, str]] = field(default_factory=list)   # (kind, reason)
    errors: list[tuple[str, str]] = field(default_factory=list)    # (kind, error)


# --------------------------------------------------------------------------- #
# Property builders
# --------------------------------------------------------------------------- #

def _title_prop(text: str) -> dict:
    return {"title": [{"text": {"content": text[:2000]}}]}


def _rich_prop(text: str) -> dict:
    return {"rich_text": [{"text": {"content": text[:2000]}}]} if text else {"rich_text": []}


def _multi_prop(values: list[str]) -> dict:
    return {"multi_select": [{"name": v} for v in values if v]}


def contact_properties(entity: ExtractedEntity) -> dict:
    props = {
        "Name": _title_prop(entity.contact_name),
        "Title": _rich_prop(entity.contact_title),
    }
    if entity.contact_email:
        props["Email"] = {"email": entity.contact_email}
    # Inbound fund managers are GP-side investment contacts by default; the UI
    # lets a human change this before the page is created.
    props["Type"] = {"select": {"name": "GP - Investments"}}
    if entity.summary:
        props["Description"] = _rich_prop(entity.summary)
    return props


def company_properties(entity: ExtractedEntity) -> dict:
    props = {
        "Name": _title_prop(entity.company_name),
        "Description": _rich_prop(entity.summary),
    }
    if entity.company_city:
        props["City"] = _rich_prop(entity.company_city)
    if entity.company_country:
        props["Country"] = _rich_prop(entity.company_country)
    return props


def fund_properties(entity: ExtractedEntity, comments: str = "") -> dict:
    # The fullest strategy text available; vintage and target size are folded in
    # here rather than as separate properties, since the Property Guidebook
    # defines no dedicated fields for them.
    strategy = entity.strategy_description or entity.summary
    facts = " · ".join(x for x in (
        f"Vintage {entity.vintage}" if entity.vintage else "",
        f"Target {entity.target_size}" if entity.target_size else "",
    ) if x)
    if facts:
        strategy = f"{facts} — {strategy}" if strategy else facts

    props = {
        "Name": _title_prop(entity.fund_name),
        "Strategy Description": _rich_prop(strategy),
        # New inbound opportunities enter the pipeline unreviewed.
        "Status": {"status": {"name": "Not reviewed"}},
    }
    if entity.asset_class:
        props["Asset Class"] = _multi_prop([entity.asset_class])
    if entity.geography:
        props["Geographic Focus"] = _multi_prop([entity.geography])
    if comments:
        props["Weybourne Comments"] = _rich_prop(comments)
    return props


def patch_property(payload: dict, value: str) -> dict:
    """Rebuild a property payload with a user-edited value, keeping its type.

    Lets the UI expose proposals as editable plain text without knowing the
    Notion payload shapes.
    """
    if "title" in payload:
        return _title_prop(value)
    if "rich_text" in payload:
        return _rich_prop(value)
    if "email" in payload:
        return {"email": value or None}
    if "select" in payload:
        return {"select": {"name": value}} if value else {"select": None}
    if "status" in payload:
        return {"status": {"name": value}} if value else payload
    if "multi_select" in payload:
        return _multi_prop([v.strip() for v in value.split(",")])
    return payload


# --------------------------------------------------------------------------- #
# Email notes
# --------------------------------------------------------------------------- #
# Convention observed in the live Notes DB (Note Type = "Email"):
#   Name (title)      — "Email: <subject> — <sender> / <company>"
#   Note Type         — select "Email"
#   Date              — the day the email was received
#   Thoughts / Considerations — a short summary of what the email says
#   Attendees / 🏢 Companies / Fund — relations to the matched records
#   Page body         — the full email text as paragraphs

COMPANIES_RELATION_PROP = "\U0001f3e2 Companies"   # the DB property name includes the glyph


def email_note_properties(subject: str, sender_name: str, company_name: str,
                          received: str, summary: str,
                          contact_ids: list[str] | None = None,
                          company_ids: list[str] | None = None,
                          fund_ids: list[str] | None = None) -> dict:
    who = " / ".join(x for x in (sender_name, company_name) if x)
    title = f"Email: {subject}" + (f" — {who}" if who else "")
    props = {
        "Name": _title_prop(title),
        "Note Type": {"select": {"name": "Email"}},
        "Thoughts / Considerations": _rich_prop(summary),
    }
    if received:
        props["Date"] = {"date": {"start": received[:10]}}
    if contact_ids:
        props["Attendees"] = {"relation": [{"id": i} for i in contact_ids]}
    if company_ids:
        props[COMPANIES_RELATION_PROP] = {"relation": [{"id": i} for i in company_ids]}
    if fund_ids:
        props["Fund"] = {"relation": [{"id": i} for i in fund_ids]}
    return props


def email_note_children(body_text: str, max_blocks: int = 60) -> list[dict]:
    """The email body as paragraph blocks (Notion caps rich_text at 2000 chars)."""
    blocks = []
    for para in (body_text or "").replace("\r\n", "\n").split("\n"):
        para = para.strip()
        if not para:
            continue
        while para and len(blocks) < max_blocks:
            chunk, para = para[:1800], para[1800:]
            blocks.append({
                "object": "block", "type": "paragraph",
                "paragraph": {"rich_text": [{"text": {"content": chunk}}]},
            })
        if len(blocks) >= max_blocks:
            break
    return blocks


def describe_properties(props: dict) -> list[tuple[str, str]]:
    """Human-readable (property, value) pairs for a proposal's Notion payload.

    Lets the UI show exactly what a page will be created with before approval.
    """
    out: list[tuple[str, str]] = []
    for name, payload in props.items():
        if "title" in payload:
            value = "".join(t["text"]["content"] for t in payload["title"])
        elif "rich_text" in payload:
            value = "".join(t["text"]["content"] for t in payload["rich_text"])
        elif "email" in payload:
            value = payload["email"]
        elif "select" in payload:
            value = payload["select"]["name"]
        elif "status" in payload:
            value = payload["status"]["name"]
        elif "multi_select" in payload:
            value = ", ".join(o["name"] for o in payload["multi_select"])
        else:
            value = str(payload)
        if value:
            out.append((name, value))
    return out


# --------------------------------------------------------------------------- #
# Planning + applying
# --------------------------------------------------------------------------- #

_DB_FOR_KIND = {
    "contact": lambda: config.NOTION_CONTACTS_DB,
    "company": lambda: config.NOTION_COMPANIES_DB,
    "fund": lambda: config.NOTION_FUNDS_DB,
}

_NAME_FOR_KIND = {
    "contact": lambda e: e.contact_name,
    "company": lambda e: e.company_name,
    "fund": lambda e: e.fund_name,
}


def plan_creations(
    entity: ExtractedEntity,
    decisions: dict[str, DedupeDecision],
    comments: str = "",
) -> list[CreationProposal]:
    """Build the list of proposed Notion pages for a triaged entity.

    Pure: makes no network calls. A ``link_existing`` decision yields no
    proposal; a ``review`` decision yields one flagged ``needs_review``.
    """
    proposals: list[CreationProposal] = []
    builders = {
        "contact": lambda: contact_properties(entity),
        "company": lambda: company_properties(entity),
        "fund": lambda: fund_properties(entity, comments),
    }

    for kind in ("company", "contact", "fund"):
        decision = decisions.get(kind)
        if decision is None:
            continue
        name = _NAME_FOR_KIND[kind](entity)
        if not name:
            continue
        if decision.recommended_action == "link_existing":
            continue
        match = decision.best_match
        proposals.append(
            CreationProposal(
                kind=kind,  # type: ignore[arg-type]
                db_id=_DB_FOR_KIND[kind](),
                title=name,
                properties=builders[kind](),
                needs_review=decision.recommended_action == "review",
                review_reason=(
                    f"possible duplicate of '{match.matched_name}' "
                    f"({match.score:.0%} {match.reason})"
                    if match and decision.recommended_action == "review"
                    else ""
                ),
                existing_match=match.matched_name if match else None,
            )
        )
    return proposals


def apply_plan(
    proposals: list[CreationProposal],
    notion: NotionConnector | None = None,
    approved_kinds: set[str] | None = None,
) -> SyncResult:
    """Create the approved proposals in Notion.

    ``approved_kinds`` is the explicit human confirmation: only proposals whose
    kind appears in it are created. Passing None approves only the proposals
    that did not need review.
    """
    notion = notion or NotionConnector()
    result = SyncResult()

    for p in proposals:
        approved = (
            p.kind in approved_kinds if approved_kinds is not None else not p.needs_review
        )
        if not approved:
            result.skipped.append((p.kind, p.review_reason or "not approved"))
            continue
        if not p.db_id and notion.live:
            result.skipped.append((p.kind, "no database id configured"))
            continue
        try:
            page = notion.create_page(p.db_id or "mock-db", p.properties)
            result.created.append((p.kind, page.get("url") or page.get("id", "")))
        except Exception as e:  # noqa: BLE001 - surface per-entity, don't abort the batch
            result.errors.append((p.kind, str(e)))
    return result
