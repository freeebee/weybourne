"""Dedupe an extracted entity against the Contacts / Companies / Funds databases.

The logic here is pure and deterministic (no network, no model calls) so it is
fully unit-testable. It is intentionally conservative: the goal is to avoid
creating a duplicate of an existing fund, company, or contact, while not
silently merging two genuinely different entities.

Matching rules, in priority order:
  Contacts  — Email is the unique key (per the Property Guidebook). An exact
              (case-insensitive) email match is a definite duplicate. Otherwise
              a strong name match is surfaced for review, not auto-merged.
  Companies — Exact domain match is a definite duplicate; otherwise fuzzy name.
  Funds     — Fuzzy name match on a normalised name (legal/common tokens
              stripped).
"""
from __future__ import annotations

import difflib
import re

from src.schemas import (
    CompanyRecord,
    ContactRecord,
    DedupeDecision,
    DedupeMatch,
    ExtractedEntity,
    FundRecord,
)

# Tokens that carry no distinguishing signal when comparing fund/company names.
_NOISE_TOKENS = {
    "the", "fund", "funds", "lp", "llc", "ltd", "limited", "l.p", "l.p.", "plc",
    "inc", "co", "company", "partners", "capital", "management", "advisors",
    "group", "holdings", "gp", "sicav", "ucits", "vehicle",
}
_ROMAN_ARABIC = {
    "i": "1", "ii": "2", "iii": "3", "iv": "4", "v": "5", "vi": "6",
    "vii": "7", "viii": "8", "ix": "9", "x": "10",
}

# Thresholds — a "duplicate" call must clear the high bar; the review band
# surfaces a likely match without auto-linking.
DUPLICATE_THRESHOLD = 0.90
REVIEW_THRESHOLD = 0.72


def normalize_name(name: str) -> str:
    """Lower-case, strip punctuation and noise tokens, normalise fund numerals."""
    name = name.lower()
    name = re.sub(r"[^\w\s]", " ", name)
    tokens = [t for t in name.split() if t and t not in _NOISE_TOKENS]
    tokens = [_ROMAN_ARABIC.get(t, t) for t in tokens]
    return " ".join(tokens).strip()


def domain_of(email: str) -> str:
    email = (email or "").strip().lower()
    return email.split("@", 1)[1] if "@" in email else ""


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def _action_for(score: float) -> str:
    if score >= DUPLICATE_THRESHOLD:
        return "link_existing"
    if score >= REVIEW_THRESHOLD:
        return "review"
    return "create"


def match_contact(email: str, name: str, contacts: list[ContactRecord]) -> DedupeDecision:
    email_l = (email or "").strip().lower()
    name_n = normalize_name(name)
    matches: list[DedupeMatch] = []
    for c in contacts:
        if email_l and c.email and c.email.strip().lower() == email_l:
            matches.append(DedupeMatch(db="contacts", matched_name=c.name, matched_id=c.id,
                                       score=1.0, reason="exact email match (unique key)"))
            continue
        score = _similarity(name_n, normalize_name(c.name))
        if score >= REVIEW_THRESHOLD:
            matches.append(DedupeMatch(db="contacts", matched_name=c.name, matched_id=c.id,
                                       score=round(score, 3), reason="name similarity"))
    return _decision("contact", name, matches)


def match_company(name: str, domain: str, companies: list[CompanyRecord]) -> DedupeDecision:
    domain_l = (domain or "").strip().lower()
    name_n = normalize_name(name)
    matches: list[DedupeMatch] = []
    for co in companies:
        if domain_l and co.domain and co.domain.strip().lower() == domain_l:
            matches.append(DedupeMatch(db="companies", matched_name=co.name, matched_id=co.id,
                                       score=1.0, reason="exact domain match"))
            continue
        score = _similarity(name_n, normalize_name(co.name))
        if score >= REVIEW_THRESHOLD:
            matches.append(DedupeMatch(db="companies", matched_name=co.name, matched_id=co.id,
                                       score=round(score, 3), reason="name similarity"))
    return _decision("company", name, matches)


def match_fund(name: str, funds: list[FundRecord]) -> DedupeDecision:
    name_n = normalize_name(name)
    matches: list[DedupeMatch] = []
    for f in funds:
        score = _similarity(name_n, normalize_name(f.name))
        if score >= REVIEW_THRESHOLD:
            matches.append(DedupeMatch(db="funds", matched_name=f.name, matched_id=f.id,
                                       score=round(score, 3), reason="name similarity"))
    return _decision("fund", name, matches)


def _decision(kind: str, name: str, matches: list[DedupeMatch]) -> DedupeDecision:
    matches.sort(key=lambda m: m.score, reverse=True)
    best = matches[0] if matches else None
    is_dup = bool(best and best.score >= DUPLICATE_THRESHOLD)
    action = _action_for(best.score) if best else "create"
    return DedupeDecision(
        entity_kind=kind,  # type: ignore[arg-type]
        name=name,
        is_duplicate=is_dup,
        best_match=best,
        all_matches=matches,
        recommended_action=action,  # type: ignore[arg-type]
    )


def dedupe_entity(
    entity: ExtractedEntity,
    contacts: list[ContactRecord],
    companies: list[CompanyRecord],
    funds: list[FundRecord],
) -> dict[str, DedupeDecision]:
    """Run all three dedupe checks for an extracted entity; keys present only
    where the entity carries the relevant name/email."""
    out: dict[str, DedupeDecision] = {}
    if entity.contact_email or entity.contact_name:
        out["contact"] = match_contact(entity.contact_email, entity.contact_name, contacts)
    if entity.company_name:
        out["company"] = match_company(entity.company_name, entity.company_domain, companies)
    if entity.fund_name:
        out["fund"] = match_fund(entity.fund_name, funds)
    return out
