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


def vintage_of(name: str) -> str | None:
    """The vintage/series number in a fund name, if it has one.

    'Capitala SBIC Fund VI' -> '6'. Successive vintages of the same franchise
    are separate funds, so a differing number rules out a duplicate however
    similar the rest of the name is.
    """
    numbers = [t for t in normalize_name(name).split() if t.isdigit()]
    return numbers[-1] if numbers else None


def domain_of(email: str) -> str:
    email = (email or "").strip().lower()
    return email.split("@", 1)[1] if "@" in email else ""


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def _squash(name: str) -> str:
    """Lower-case with everything but letters/digits removed — no token logic.

    'FIFECAPITAL' and 'Fife Capital' both squash to 'fifecapital'."""
    return re.sub(r"[^\w]", "", (name or "").lower())


def _name_score(a_raw: str, b_raw: str) -> float:
    """Best of the token-normalised and squashed comparisons.

    Token normalisation strips noise words ('capital', 'partners'), which is
    right for 'Blackstone Capital Partners' vs 'Blackstone' — but it mangles
    concatenated names: 'FIFECAPITAL' keeps its full string while
    'Fife Capital' collapses to 'fife', and the two stop matching. The
    squashed comparison catches exactly that case, so take the max.
    """
    return max(_similarity(normalize_name(a_raw), normalize_name(b_raw)),
               _similarity(_squash(a_raw), _squash(b_raw)))


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
        if name_n and name_n == normalize_name(c.name):
            # The exact same full name is a direct match — 'Allan Fife' IS the
            # 'Allan Fife' in the CRM unless something else says otherwise.
            matches.append(DedupeMatch(db="contacts", matched_name=c.name, matched_id=c.id,
                                       score=1.0, reason="exact name match"))
            continue
        score = _name_score(name, c.name)
        if score >= REVIEW_THRESHOLD:
            # A merely-similar name never proves identity — two people can share
            # one. Cap fuzzy name matches into the review band so they are
            # surfaced for a human rather than merged automatically.
            capped = min(score, DUPLICATE_THRESHOLD - 0.01)
            matches.append(DedupeMatch(db="contacts", matched_name=c.name, matched_id=c.id,
                                       score=round(capped, 3),
                                       reason="name similarity (no email match)"))
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
        score = _name_score(name, co.name)
        if score >= REVIEW_THRESHOLD:
            matches.append(DedupeMatch(db="companies", matched_name=co.name, matched_id=co.id,
                                       score=round(score, 3), reason="name similarity"))
    return _decision("company", name, matches)


def match_fund(name: str, funds: list[FundRecord]) -> DedupeDecision:
    name_n = normalize_name(name)
    vintage = vintage_of(name)
    matches: list[DedupeMatch] = []
    for f in funds:
        score = _name_score(name, f.name)
        if score < REVIEW_THRESHOLD:
            continue
        other_vintage = vintage_of(f.name)
        if vintage and other_vintage and vintage != other_vintage:
            # Fund VII is not a duplicate of Fund VI, however similar the names.
            # Surface it as a related fund for review, never as a duplicate.
            matches.append(DedupeMatch(
                db="funds", matched_name=f.name, matched_id=f.id,
                score=round(min(score, REVIEW_THRESHOLD), 3),
                reason=f"same franchise, different vintage ({other_vintage} vs {vintage})",
            ))
            continue
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

    # Cross-corroboration: two individually-uncertain matches that point at
    # each other are one strong one. If the matched CRM contact is already
    # tagged to (a name-match of) the extracted company, both the contact and
    # the company are near-certainly the same entities — upgrade review-band
    # decisions to link_existing and say why.
    contact_d, company_d = out.get("contact"), out.get("company")
    if contact_d and contact_d.best_match:
        crm_contact = next(
            (c for c in contacts if c.id and c.id == contact_d.best_match.matched_id), None)
        crm_company = (crm_contact.company or "") if crm_contact else ""
        corroborated = bool(
            crm_company
            and (_name_score(crm_company, entity.company_name) >= REVIEW_THRESHOLD
                 or (company_d and company_d.best_match
                     and _name_score(crm_company, company_d.best_match.matched_name)
                     >= REVIEW_THRESHOLD)))
        if corroborated:
            note = (f"corroborated: the CRM contact is tagged to "
                    f"'{crm_company}', matching the extracted company")
            for d in (contact_d, company_d):
                if d and d.best_match and d.recommended_action == "review":
                    d.recommended_action = "link_existing"  # type: ignore[assignment]
                    d.is_duplicate = True
                    d.best_match.reason += f" + {note}"
    return out
