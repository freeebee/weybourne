"""Google and Amadeus adapters with honest, deterministic demo data."""
from __future__ import annotations

import hashlib
import math
import time
from datetime import datetime, timezone
from urllib.parse import quote_plus

import requests

from src import config
from .models import HotelOption, OfficeResolution, TravelSettings


CITY_COORDS = {
    "london": (51.5074, -0.1278), "new york": (40.7128, -74.0060),
    "hong kong": (22.3193, 114.1694), "singapore": (1.3521, 103.8198),
    "paris": (48.8566, 2.3522), "san francisco": (37.7749, -122.4194),
    "boston": (42.3601, -71.0589), "chicago": (41.8781, -87.6298),
}
CITY_TIMEZONES = {
    "london": "Europe/London", "new york": "America/New_York",
    "hong kong": "Asia/Hong_Kong", "singapore": "Asia/Singapore",
    "paris": "Europe/Paris", "san francisco": "America/Los_Angeles",
    "boston": "America/New_York", "chicago": "America/Chicago",
    "edinburgh": "Europe/London",
}


def _stable_offset(text: str) -> tuple[float, float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return ((digest[0] / 255 - .5) * .08, (digest[1] / 255 - .5) * .08)


def city_coordinates(city: str, country: str = "") -> tuple[float, float]:
    base = CITY_COORDS.get((city or "").strip().lower())
    if base:
        return base
    off = _stable_offset(f"{city}|{country}")
    # A neutral demo position is preferable to pretending an unknown city is
    # precisely geocoded. The UI labels demo pins explicitly.
    return 20 + off[0] * 100, off[1] * 100


def _check(resp) -> None:
    """raise_for_status without discarding Google's actual reason.

    A bare "403 Forbidden" from places.googleapis.com sent the user hunting
    through key guesswork (18 Aug 2026); the response body carries the real
    story — typically that Places API (New), Routes API or Time Zone API is
    not enabled for the key's project."""
    if resp.ok:
        return
    try:
        reason = (resp.json().get("error") or {}).get("message", "")
    except Exception:  # noqa: BLE001 - non-JSON error body
        reason = (resp.text or "")[:200]
    raise requests.HTTPError(
        f"{resp.status_code} from {resp.url.split('?')[0]}: {reason or resp.reason}",
        response=resp)


class GoogleTravelConnector:
    def __init__(self):
        self.key = config.GOOGLE_MAPS_SERVER_KEY
        self.live = bool(self.key)

    def resolve_office(self, company: str, city: str, country: str,
                       address: str = "") -> OfficeResolution:
        query = ", ".join(x for x in (address or company, city, country) if x)
        if not self.live:
            lat, lng = city_coordinates(city, country)
            a, b = _stable_offset(company)
            result = {
                "place_id": f"demo-{hashlib.sha1(query.encode()).hexdigest()[:10]}",
                "name": company, "address": address or f"{company}, {city}, {country}",
                "latitude": lat + a, "longitude": lng + b,
            }
            return OfficeResolution(
                query=query, place_id=result["place_id"], address=result["address"],
                latitude=result["latitude"], longitude=result["longitude"],
                confidence=.92, confirmed=False, candidates=[result],
            )
        resp = requests.post(
            "https://places.googleapis.com/v1/places:searchText",
            headers={
                "X-Goog-Api-Key": self.key,
                "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress,places.location",
            },
            json={"textQuery": query, "maxResultCount": 5}, timeout=25,
        )
        _check(resp)
        choices = []
        for p in resp.json().get("places", []):
            loc = p.get("location") or {}
            choices.append({
                "place_id": p.get("id", ""),
                "name": (p.get("displayName") or {}).get("text", company),
                "address": p.get("formattedAddress", ""),
                "latitude": loc.get("latitude"), "longitude": loc.get("longitude"),
            })
        if not choices:
            return OfficeResolution(query=query)
        top = choices[0]
        confidence = .96 if address and address.lower() in top["address"].lower() else (.86 if city.lower() in top["address"].lower() else .55)
        return OfficeResolution(query=query, confidence=confidence, confirmed=False,
                                candidates=choices, **{k: top[k] for k in (
                                    "place_id", "address", "latitude", "longitude")})

    def route_minutes(self, origins: list[tuple[float, float]],
                      destinations: list[tuple[float, float]],
                      mode: str = "DRIVE") -> list[list[float]]:
        if not origins or not destinations:
            return []
        if not self.live:
            return [[max(5, haversine_km(a, b) / (25 if mode == "DRIVE" else 4.5) * 60)
                     for b in destinations] for a in origins]
        payload = {
            "origins": [{"waypoint": {"location": {"latLng": {
                "latitude": p[0], "longitude": p[1]}}}} for p in origins],
            "destinations": [{"waypoint": {"location": {"latLng": {
                "latitude": p[0], "longitude": p[1]}}}} for p in destinations],
            "travelMode": mode,
            **({"routingPreference": "TRAFFIC_UNAWARE"} if mode == "DRIVE" else {}),
        }
        resp = requests.post(
            "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix",
            headers={"X-Goog-Api-Key": self.key,
                     "X-Goog-FieldMask": "originIndex,destinationIndex,duration,status"},
            json=payload, timeout=30,
        )
        _check(resp)
        matrix = [[9999.0 for _ in destinations] for _ in origins]
        for item in resp.json():
            duration = str(item.get("duration", "0s")).removesuffix("s")
            matrix[item.get("originIndex", 0)][item.get("destinationIndex", 0)] = float(duration or 0) / 60
        return matrix

    def timezone_at(self, latitude: float, longitude: float, city: str = "") -> str:
        if not self.live:
            return CITY_TIMEZONES.get(city.casefold(), "UTC")
        resp = requests.get("https://maps.googleapis.com/maps/api/timezone/json", params={
            "location": f"{latitude},{longitude}", "timestamp": int(time.time()), "key": self.key,
        }, timeout=20)
        _check(resp)
        return resp.json().get("timeZoneId") or CITY_TIMEZONES.get(city.casefold(), "UTC")

    def enrich_hotels(self, hotels: list[HotelOption], city: str) -> list[HotelOption]:
        if not self.live:
            return hotels
        for hotel in hotels:
            try:
                resp = requests.post(
                    "https://places.googleapis.com/v1/places:searchText",
                    headers={"X-Goog-Api-Key": self.key,
                             "X-Goog-FieldMask": "places.id,places.formattedAddress,places.location,places.rating,places.userRatingCount,places.googleMapsUri"},
                    json={"textQuery": f"{hotel.name}, {city}", "maxResultCount": 1}, timeout=20,
                )
                resp.raise_for_status()
                place = (resp.json().get("places") or [{}])[0]
                loc = place.get("location") or {}
                hotel.address = place.get("formattedAddress") or hotel.address
                hotel.latitude = loc.get("latitude", hotel.latitude)
                hotel.longitude = loc.get("longitude", hotel.longitude)
                hotel.rating = place.get("rating")
                hotel.review_count = place.get("userRatingCount")
                hotel.booking_url = place.get("googleMapsUri") or hotel.booking_url
            except Exception:
                # A missing quality lookup must not discard a real live price.
                continue
        return hotels


class AmadeusHotelConnector:
    def __init__(self):
        self.client_id = config.AMADEUS_CLIENT_ID
        self.secret = config.AMADEUS_CLIENT_SECRET
        self.base = config.AMADEUS_BASE_URL.rstrip("/")
        self.live = bool(self.client_id and self.secret)
        self._token = ""
        self._expires = 0.0

    def _access_token(self) -> str:
        if self._token and time.time() < self._expires - 30:
            return self._token
        resp = requests.post(
            f"{self.base}/v1/security/oauth2/token",
            data={"grant_type": "client_credentials", "client_id": self.client_id,
                  "client_secret": self.secret}, timeout=20,
        )
        resp.raise_for_status()
        body = resp.json()
        self._token = body["access_token"]
        self._expires = time.time() + int(body.get("expires_in", 1200))
        return self._token

    def _get(self, path: str, params: dict) -> dict:
        resp = requests.get(f"{self.base}{path}", params=params,
                            headers={"Authorization": f"Bearer {self._access_token()}"},
                            timeout=30)
        resp.raise_for_status()
        return resp.json()

    def search(self, city_id: str, city: str, country: str, check_in: str,
               check_out: str, budget_gbp: float,
               centre: tuple[float, float]) -> list[HotelOption]:
        if not self.live:
            return self._demo(city_id, city, country, check_in, check_out,
                              budget_gbp, centre)
        hotels = self._get("/v1/reference-data/locations/hotels/by-geocode", {
            "latitude": centre[0], "longitude": centre[1], "radius": 12,
            "radiusUnit": "KM", "hotelSource": "ALL",
        }).get("data", [])[:30]
        ids = [h.get("hotelId") for h in hotels if h.get("hotelId")]
        if not ids:
            return []
        offers = self._get("/v3/shopping/hotel-offers", {
            "hotelIds": ",".join(ids), "adults": 1, "roomQuantity": 1,
            "checkInDate": check_in, "checkOutDate": check_out,
            "currency": "GBP", "bestRateOnly": "true",
        }).get("data", [])
        now = datetime.now(timezone.utc).isoformat()
        out = []
        by_id = {h.get("hotelId"): h for h in hotels}
        nights = max(1, (datetime.fromisoformat(check_out) - datetime.fromisoformat(check_in)).days)
        for row in offers:
            offer = (row.get("offers") or [{}])[0]
            price = offer.get("price") or {}
            total = float(price.get("total") or 0)
            nightly = total / nights
            if nightly <= 0 or nightly > budget_gbp:
                continue
            meta = row.get("hotel") or by_id.get(row.get("hotelId"), {})
            geo = meta.get("geoCode") or {}
            name = meta.get("name") or row.get("hotelId", "Hotel")
            out.append(HotelOption(
                id=f"amadeus-{row.get('hotelId')}", provider_hotel_id=row.get("hotelId", ""),
                city_id=city_id, name=name, nightly_gbp=round(nightly, 2),
                total_gbp=round(total, 2), latitude=geo.get("latitude"),
                longitude=geo.get("longitude"), stars=float(meta.get("rating") or 0) or None,
                cancellation=str((offer.get("policies") or {}).get("cancellations") or ""),
                booking_url=f"https://www.google.com/maps/search/?api=1&query={quote_plus(name+' '+city)}",
                quoted_at=now,
            ))
        return out

    def _demo(self, city_id: str, city: str, country: str, check_in: str,
              check_out: str, budget: float, centre: tuple[float, float]) -> list[HotelOption]:
        now = datetime.now(timezone.utc).isoformat()
        nights = max(1, (datetime.fromisoformat(check_out) - datetime.fromisoformat(check_in)).days)
        templates = [
            ("Exchange House", .62, 4.3, 612, 4),
            ("The Meridian", .79, 4.6, 1288, 5),
            ("City Rooms", .43, 4.0, 284, 3),
            ("Grand Central", 1.08, 4.8, 2101, 5),
        ]
        result = []
        for i, (name, factor, rating, reviews, stars) in enumerate(templates):
            nightly = round(max(75, budget * factor), 2)
            if nightly > budget:
                continue
            a, b = _stable_offset(f"{city}-{name}")
            result.append(HotelOption(
                id=f"demo-hotel-{city_id}-{i}", provider_hotel_id=f"DEMO{i}", city_id=city_id,
                name=f"{name} {city}", address=f"Central {city}, {country}",
                latitude=centre[0] + a, longitude=centre[1] + b,
                nightly_gbp=nightly, total_gbp=round(nightly * nights, 2),
                taxes_gbp=round(nightly * nights * .08, 2), rating=rating,
                review_count=reviews, stars=stars, cancellation="Free cancellation until 48 hours before arrival",
                booking_url=f"https://www.google.com/maps/search/?api=1&query={quote_plus(name+' '+city)}",
                quoted_at=now,
            ))
        return result


def rank_hotels(hotels: list[HotelOption], meeting_points: list[tuple[float, float]],
                google: GoogleTravelConnector, settings: TravelSettings) -> list[HotelOption]:
    eligible = [h for h in hotels if h.nightly_gbp <= settings.nightly_budget_gbp]
    if not eligible:
        return []
    located = [(i, (h.latitude, h.longitude)) for i, h in enumerate(eligible)
               if h.latitude is not None and h.longitude is not None]
    matrix = google.route_minutes([p for _, p in located], meeting_points, settings.travel_mode) if meeting_points and located else []
    by_index = {hotel_index: matrix[row_index] for row_index, (hotel_index, _p) in enumerate(located)} if matrix else {}
    for i, hotel in enumerate(eligible):
        routes = by_index.get(i, [])
        hotel.aggregate_travel_minutes = round(sum(routes) / len(routes), 1) if routes else 0
    prices = [h.nightly_gbp for h in eligible]
    travels = [h.aggregate_travel_minutes or 0 for h in eligible]
    qualities = [((h.rating or 3) / 5) * .8 + min(1, math.log10(max(1, h.review_count or 1)) / 4) * .2 for h in eligible]

    def inverse(value, values):
        lo, hi = min(values), max(values)
        return 1 if hi == lo else 1 - (value - lo) / (hi - lo)

    for h, quality in zip(eligible, qualities):
        h.score = round(100 * (
            settings.hotel_price_weight * inverse(h.nightly_gbp, prices)
            + settings.hotel_travel_weight * inverse(h.aggregate_travel_minutes or 0, travels)
            + settings.hotel_quality_weight * quality), 1)
    return sorted(eligible, key=lambda h: (-h.score, h.nightly_gbp, h.name))


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    r = 6371
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = math.radians(b[0] - a[0]), math.radians(b[1] - a[1])
    x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(x))
