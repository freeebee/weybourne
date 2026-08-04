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

# Fill-priority lists, matching the Error Tracking page's definitions. Real
# property names carry emoji ("🏢 Employed By"), so these are matched through
# ``match_prop`` rather than compared literally — and anything the live schema
# does not have is skipped, never guessed at.
PRIORITY_PROPS = {
    "contacts": ["Employed By", "Type", "Title", "Description"],
    "companies": ["Description", "City", "Country"],
    "funds": ["Company", "Asset Class", "Geographic Focus", "Status",
              "Quality", "Weybourne Comments", "Strategy Description"],
    "notes": ["Note Type", "Attendees", "Thoughts / Considerations", "Date"],
}


def _prop_key(name: str) -> str:
    """A property name reduced to its comparable core: no emoji, no
    punctuation, no case. '🏢 Employed By' and 'employed by' both become
    'employedby'."""
    return "".join(ch for ch in (name or "").lower() if ch.isalnum())


def match_prop(schema_props, *candidates: str) -> str:
    """The real schema property matching any of ``candidates``.

    Notion property names in this workspace carry emoji prefixes, so a literal
    comparison silently matches nothing — which reads as "no gaps found"
    rather than as a bug. Returns "" when none matches.
    """
    by_key = {_prop_key(p): p for p in schema_props}
    for cand in candidates:
        hit = by_key.get(_prop_key(cand))
        if hit:
            return hit
    return ""


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
    # Resolved against the live schema, so the emoji-prefixed real names
    # ("🏢 Employed By") are found rather than silently missed.
    wanted = [m for m in (match_prop(schema_props, p)
                          for p in PRIORITY_PROPS.get(db, [])) if m]
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


import re as _re

_BARE_EMAIL = _re.compile(r"^[^\s<>@]+@[^\s<>@]+\.[^\s<>@]+$")
_EMAIL_ANY = _re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")

# Tokens kept exactly as typed when proper-casing a person's name: credentials,
# honours, generational suffixes, and company-form suffixes that occasionally
# appear on contact rows.
_NAME_KEEP = {
    "CFA", "CAIA", "CPA", "CA", "FRM", "MBA", "PHD", "MD", "JD", "OBE", "CBE",
    "MBE", "KC", "QC", "SC", "II", "III", "IV", "VI", "VII", "VIII",
    "LLC", "LLP", "PLC", "GMBH", "SA", "AG", "PTE", "BV", "NV", "KK", "SARL",
}
# Lowercase particles that are CORRECT lowercase in many names.
_NAME_PARTICLES = {
    "van", "de", "der", "den", "von", "di", "da", "del", "della", "dela",
    "bin", "binti", "binte", "al", "el", "le", "la", "ter", "ten", "te",
    "op", "'t", "y", "e", "und", "of", "the", "and",
}


def _cap_segmented(word: str) -> str:
    """Capitalise a single name word, keeping hyphen/apostrophe structure:
    JEAN-PAUL → Jean-Paul, O'BRIEN → O'Brien."""
    def cap(seg: str) -> str:
        return seg[:1].upper() + seg[1:].lower() if seg else seg
    return "-".join("'".join(cap(p) for p in h.split("'"))
                    for h in word.split("-"))


def proper_name_case(name: str) -> str:
    """Proper capitalisation for a person's name — conservative.

    Only words that are FULLY uppercase (3+ letters) or fully lowercase are
    touched; mixed-case words (McDonald, deVere) are trusted as typed.
    Credentials (CFA, CAIA), generational suffixes (III) and lowercase name
    particles (van, de, bin) are preserved. Words containing digits are left
    alone entirely.
    """
    out = []
    for tok in name.split():
        head, core, tail = "", tok, ""
        while core and core[0] in "(\"'":
            head, core = head + core[0], core[1:]
        while core and core[-1] in ",.;:)\"'":
            core, tail = core[:-1], core[-1] + tail
        letters = core.replace("-", "").replace("'", "")
        if (not letters.isalpha()
                or core.upper() in _NAME_KEEP
                or (core.islower() and core in _NAME_PARTICLES)):
            out.append(tok)
        elif core.isupper() and len(letters) >= 3:
            out.append(head + _cap_segmented(core) + tail)
        elif core.islower():
            out.append(head + _cap_segmented(core) + tail)
        else:
            out.append(tok)
    return " ".join(out)


def find_formatting_issues(cards: list[dict]) -> list[dict]:
    """High-confidence mechanical fixes: title whitespace, person-name casing
    (contacts only — company and fund names are acronym-hazardous), and email
    hygiene.

    Emails: a bare address is lowercased; a value that is NOT a bare address
    but contains exactly one email ("C- 5165874019 W- ... roy@carmo.com",
    "Allison Stavro <allison@sinefine.co>") becomes an ``email_extract`` fix
    down to the bare address, carrying the leftover text as ``junk`` so the
    run can propose homes for it (title, phone, description) separately.
    A value with several different addresses is left alone — choosing one
    would be a guess.
    """
    out = []
    for c in cards:
        if c["archived"]:
            continue
        name = c["name"]
        cleaned = " ".join(name.split())
        if c["db"] == "contacts" and cleaned:
            cleaned = proper_name_case(cleaned)
        if name and cleaned != name:
            kind = ("title_whitespace"
                    if cleaned == " ".join(name.split()) else "name_case")
            out.append({"card": c, "kind": kind,
                        "property": c["title_prop"], "from": name, "to": cleaned})
        for prop, payload in c["raw"].items():
            if payload.get("type") == "email" and payload.get("email"):
                email_raw = payload["email"]
                addr = email_raw.strip()
                if _BARE_EMAIL.match(addr):
                    if email_raw != addr.lower():
                        out.append({"card": c, "kind": "email_case",
                                    "property": prop,
                                    "from": email_raw, "to": addr.lower()})
                    continue
                found = _EMAIL_ANY.findall(email_raw)
                if len({f.lower() for f in found}) == 1:
                    junk = " ".join(
                        email_raw.replace(found[0], " ").split()).strip(" ,;|<>-")
                    out.append({"card": c, "kind": "email_extract",
                                "property": prop, "from": email_raw,
                                "to": found[0].lower(), "junk": junk})
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
