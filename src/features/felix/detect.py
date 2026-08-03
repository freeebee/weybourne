"""Deterministic issue detection — pure functions over "cards".

A card is a normalised view of one raw Notion page (build with
``card_from_page``): plain values for comparing, raw payloads for writing.
Nothing here touches the network or the model, which is what makes this the
package's main unit-test surface.

Confidence discipline (the spec's): only exact identifiers (email, corporate
domain, squashed-name identity) reach High on their own. Name similarity alone
NEVER exceeds a review candidate — those go to the adjudicator, and "unsure"
dies there as a recommendation.
"""
from __future__ import annotations

from src.connectors.notion_client import plain_value, relation_ids
from src.features.dedupe import _name_score, _squash, domain_of

REVIEW_THRESHOLD = 0.72

GENERIC_DOMAINS = {
    "gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com",
    "yahoo.com", "icloud.com", "me.com", "aol.com", "proton.me",
    "protonmail.com", "msn.com", "qq.com", "163.com", "126.com",
}

# Spec's fill-priority lists; the run filters these against the LIVE schema so
# a renamed property is skipped, never guessed at.
PRIORITY_PROPS = {
    "contacts": ["Employed By", "Type", "Weybourne Comments"],
    "companies": ["Description", "City", "Country"],
    "funds": ["Company Name", "Asset Class", "Geographic Focus", "Status",
              "Strategy Description", "Responsible Person"],
    "notes": ["Note Type", "Date"],
}


def card_from_page(page: dict, db: str) -> dict:
    """Normalise a raw Notion page into a comparable card."""
    props = page.get("properties") or {}
    plain: dict = {}
    raw: dict = {}
    relations: dict = {}
    title = ""
    title_prop = ""
    email = ""
    for name, payload in props.items():
        t, v = plain_value(payload)
        plain[name] = v
        raw[name] = payload
        if t == "title":
            title, title_prop = v, name
        elif t == "email" and not email:
            email = v or ""
        elif t == "relation":
            relations[name] = relation_ids(page, name)
    return {
        "id": page.get("id", ""),
        "db": db,
        "name": title,
        "title_prop": title_prop,
        "email": email.strip().lower(),
        "domain": domain_of(email or ""),
        "url": page.get("url", ""),
        "icon": page.get("icon"),
        "archived": bool(page.get("archived")),
        "created": page.get("created_time", ""),
        "edited": page.get("last_edited_time", ""),
        "plain": plain,
        "raw": raw,
        "relations": relations,
    }


def _empty(value) -> bool:
    return value in ("", None, [], False) if not isinstance(value, bool) else False


def filled_count(card: dict) -> int:
    return sum(0 if _empty(v) else 1 for v in card["plain"].values())


def relation_count(card: dict) -> int:
    return sum(len(ids) for ids in card["relations"].values())


# -- duplicates ------------------------------------------------------------- #

def find_exact_duplicate_groups(cards: list[dict]) -> list[dict]:
    """Groups sharing an exact identifier — High confidence by the spec.

    Keys: exact email (contacts), exact squashed non-empty name. Corporate
    domains identify the EMPLOYER, not identity — two colleagues share one —
    so domains are deliberately not a duplicate key.
    """
    groups: dict[tuple, list[dict]] = {}
    for c in cards:
        if c["archived"]:
            continue
        if c["email"]:
            groups.setdefault(("email", c["email"]), []).append(c)
        sq = _squash(c["name"])
        if sq:
            groups.setdefault(("name", sq), []).append(c)
    seen: set[frozenset] = set()
    out = []
    for (kind, key), members in groups.items():
        ids = frozenset(m["id"] for m in members)
        if len(ids) < 2 or ids in seen:
            continue
        seen.add(ids)
        out.append({"evidence": kind, "key": key,
                    "cards": sorted(members, key=lambda m: m["id"])})
    return out


def find_fuzzy_duplicate_pairs(cards: list[dict],
                               threshold: float = REVIEW_THRESHOLD) -> list[dict]:
    """Similar-but-not-identical pairs for the adjudicator, via blocking —
    candidates only compared inside shared buckets (squashed 4-char prefix,
    email domain, first name token), never all-pairs."""
    buckets: dict[tuple, list[int]] = {}
    active = [c for c in cards if not c["archived"] and c["name"]]
    for i, c in enumerate(active):
        sq = _squash(c["name"])
        if sq:
            buckets.setdefault(("pre", sq[:4]), []).append(i)
        if c["domain"] and c["domain"] not in GENERIC_DOMAINS:
            buckets.setdefault(("dom", c["domain"]), []).append(i)
        first = c["name"].lower().split()[0] if c["name"].split() else ""
        if len(first) > 2:
            buckets.setdefault(("tok", first), []).append(i)
    seen: set[tuple] = set()
    out = []
    for members in buckets.values():
        for ai in range(len(members)):
            for bi in range(ai + 1, len(members)):
                a, b = active[members[ai]], active[members[bi]]
                key = tuple(sorted((a["id"], b["id"])))
                if key in seen:
                    continue
                seen.add(key)
                if _squash(a["name"]) == _squash(b["name"]):
                    continue                     # exact — handled elsewhere
                if a["email"] and b["email"] and a["email"] != b["email"]:
                    continue                     # distinct identifiers
                score = _name_score(a["name"], b["name"])
                if score >= threshold:
                    out.append({"a": a, "b": b, "score": round(score, 3)})
    out.sort(key=lambda p: -p["score"])
    return out


def choose_survivor(cards: list[dict]) -> tuple[dict, list[dict]]:
    """Deterministic survivor: most relations, then most filled properties,
    then oldest created. Returns (survivor, losers)."""
    ranked = sorted(cards, key=lambda c: (-relation_count(c), -filled_count(c),
                                          c["created"] or "9999"))
    return ranked[0], ranked[1:]


def plan_merge_transfers(survivor: dict, loser: dict) -> dict:
    """The copy-only transfer plan: survivor keeps its non-empty values,
    loser's values fill survivor's empties, lists are unioned, and
    both-set-and-different is a CONFLICT (logged, never overwritten).
    Every transferred value is verbatim from the loser — nothing is invented.
    """
    transfers, conflicts = [], []
    for name, l_val in loser["plain"].items():
        if name == loser.get("title_prop") or _empty(l_val):
            continue
        s_val = survivor["plain"].get(name)
        payload = loser["raw"].get(name, {})
        ptype = payload.get("type", "")
        if ptype in ("multi_select", "relation"):
            s_list, l_list = list(s_val or []), list(l_val or [])
            union = s_list + [x for x in l_list if x not in s_list]
            if sorted(union) != sorted(s_list):
                transfers.append({"property": name, "kind": "union",
                                  "value": union, "ptype": ptype})
        elif _empty(s_val):
            transfers.append({"property": name, "kind": "fill",
                              "payload": payload, "ptype": ptype})
        elif s_val != l_val:
            conflicts.append({"property": name, "survivor": s_val, "loser": l_val})
    return {"transfers": transfers, "conflicts": conflicts}


# -- other issue kinds ------------------------------------------------------ #

def find_missing_props(cards: list[dict], db: str,
                       schema_props: set[str]) -> list[dict]:
    wanted = [p for p in PRIORITY_PROPS.get(db, []) if p in schema_props]
    out = []
    for c in cards:
        if c["archived"]:
            continue
        missing = [p for p in wanted
                   if p in c["plain"] and _empty(c["plain"][p])
                   and not c["relations"].get(p)]
        if missing:
            out.append({"card": c, "missing": missing})
    return out


def find_dangling_relations(cards: list[dict], relation_map: dict,
                            ids_by_db: dict) -> list[dict]:
    """Relation ids pointing at pages absent from a COMPLETE scan of their
    target DB (i.e. archived/removed). Only relations whose target DB was
    fully scanned are judged — anything else is out of scope, not dangling."""
    out = []
    for c in cards:
        if c["archived"]:
            continue
        for prop, ids in c["relations"].items():
            target_db = relation_map.get((c["db"], prop))
            if not target_db or target_db not in ids_by_db or not ids:
                continue
            live_ids = ids_by_db[target_db]
            dangling = [i for i in ids if i not in live_ids]
            if dangling:
                out.append({"card": c, "property": prop, "dangling": dangling,
                            "keep": [i for i in ids if i in live_ids]})
    return out


def find_formatting_issues(cards: list[dict]) -> list[dict]:
    """High-confidence mechanical fixes only: title whitespace and email
    casing. Word-casing rewrites are acronym-hazardous and are NOT proposed."""
    out = []
    for c in cards:
        if c["archived"]:
            continue
        name = c["name"]
        cleaned = " ".join(name.split())
        if name and cleaned != name:
            out.append({"card": c, "kind": "title_whitespace",
                        "property": c["title_prop"], "from": name, "to": cleaned})
        email_raw = ""
        for prop, payload in c["raw"].items():
            if payload.get("type") == "email" and payload.get("email"):
                email_raw = payload["email"]
                if email_raw != email_raw.strip().lower():
                    out.append({"card": c, "kind": "email_case", "property": prop,
                                "from": email_raw,
                                "to": email_raw.strip().lower()})
    return out


def find_icon_issues(cards: list[dict], standard_icon: str) -> list[dict]:
    """Pages missing an icon. Applied only when a standard icon is configured
    for the DB; otherwise the caller downgrades to a recommendation."""
    return [{"card": c, "icon": standard_icon}
            for c in cards if not c["archived"] and not c["icon"]]


def infer_employers(contacts: list[dict], companies: list[dict],
                    employed_by_prop: str = "Employed By") -> dict:
    """Exact corporate email-domain matching only.

    Returns {"links": [...], "company_candidates": [...]}: links are High
    (contact's corporate domain exactly matches a company's known domain or
    website), candidates are contacts whose corporate domain matches NO
    company — a possible company creation, which stays Medium and is re-deduped
    by the caller before anything is created.
    """
    def _host_domain(url: str) -> str:
        host = str(url).split("//")[-1].split("/")[0].strip().lower()
        return host[4:] if host.startswith("www.") else host

    by_domain: dict[str, dict] = {}
    for co in companies:
        for prop, payload in co["raw"].items():
            t, v = plain_value(payload)
            if t == "url" and v:
                dom = _host_domain(v)
                if dom:
                    by_domain.setdefault(dom, co)
        if co.get("domain"):
            by_domain.setdefault(co["domain"], co)
    links, candidates = [], []
    for c in contacts:
        if c["archived"] or not c["domain"] or c["domain"] in GENERIC_DOMAINS:
            continue
        if c["relations"].get(employed_by_prop):
            continue                            # already linked
        hit = by_domain.get(c["domain"])
        if hit is not None:
            links.append({"contact": c, "company": hit, "domain": c["domain"]})
        else:
            candidates.append({"contact": c, "domain": c["domain"]})
    return {"links": links, "company_candidates": candidates}
