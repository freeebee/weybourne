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
    return {
        "Name": _title_prop(entity.company_name),
        "Description": _rich_prop(entity.summary),
    }


def fund_properties(entity: ExtractedEntity, comments: str = "") -> dict:
    props = {
        "Name": _title_prop(entity.fund_name),
        "Strategy Description": _rich_prop(entity.summary),
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
