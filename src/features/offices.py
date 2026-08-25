"""The canonical multi-office format for a company's Address property.

One office per line, headquarters first:

    London, UK — 25 Old Broad Street, EC2N 1HQ
    Sydney, Australia — Level 15, 1 Macquarie Place, NSW 2000

`City, Country`, an em dash, then the street address exactly as the firm
publishes it. Fix It Felix writes this format when it researches missing
offices; the travel planner parses it to geocode the office in the city
actually being visited. A line without the em dash is treated as one
freeform address (legacy single-office records stay valid as they are).
"""
from __future__ import annotations

_SEP = " — "


def format_office_lines(offices: list[dict]) -> str:
    """Render [{city, country, address}, ...] into the canonical lines."""
    lines = []
    for o in offices or []:
        address = (o.get("address") or "").strip()
        if not address:
            continue
        place = ", ".join(p for p in ((o.get("city") or "").strip(),
                                      (o.get("country") or "").strip()) if p)
        lines.append(f"{place}{_SEP}{address}" if place else address)
    return "\n".join(lines)


def parse_office_lines(text: str) -> list[dict]:
    """Parse the Address property back into [{city, country, address}, ...].

    Lines that don't follow the format come back as an address with no
    city/country — callers fall back to the company's own City field.
    """
    offices = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        if _SEP in line:
            place, address = line.split(_SEP, 1)
            city, _, country = place.partition(", ")
            offices.append({"city": city.strip(), "country": country.strip(),
                            "address": address.strip()})
        else:
            offices.append({"city": "", "country": "", "address": line})
    return offices


def office_for_city(text: str, city: str) -> str:
    """The address line for one city, or "" when the record doesn't say.

    A single freeform address (no city prefix) is returned as-is — one
    office means every visit goes there.
    """
    offices = parse_office_lines(text)
    if not offices:
        return ""
    for o in offices:
        if o["city"] and o["city"].casefold() == (city or "").casefold():
            return o["address"]
    if len(offices) == 1 and not offices[0]["city"]:
        return offices[0]["address"]
    return ""
