"""Correlate stored manager return series against real market factors.

Five factors, all monthly, three from Polygon (ETF total returns) and two from
FRED (macro series). Each manager's stored track record is correlated against
each factor over the months the two genuinely share.

Three decisions worth stating, because each one trades completeness for honesty:

**No demo mode.** Every other connector in this app degrades to sample data when
its credentials are missing. This one raises. A fabricated inbox is obviously a
fabricated inbox; a fabricated correlation coefficient is a plausible number
with nothing on screen to mark it as fiction.

**Aligned by month key, not by position.** The original dashboard assumed all 52
managers shared one fixed twelve-month window, so a positional array worked.
Real track records start and end wherever the manager's history does, so
alignment happens on ``YYYY-MM`` keys. Getting this wrong would not produce an
error — it would produce confident numbers correlating one manager's July
against a factor's March.

**Silence below the minimum.** A Pearson coefficient over four months is noise
that renders exactly like a real result. Under ``FACTOR_MIN_OVERLAP_MONTHS`` the
answer is ``None``, which the page shows as "not enough data" alongside the
actual overlap count.
"""
from __future__ import annotations

import datetime as dt
import math
import threading
import time
from typing import Optional

from src import config
from src.features import track_record_store


class FactorDataUnavailable(RuntimeError):
    """Factor data cannot be fetched. The message becomes the HTTP detail."""


FACTORS = [
    {"id": "ai", "name": "AI / momentum (SOXX)", "ticker": "SOXX", "source": "polygon",
     "description": "iShares Semiconductor ETF, monthly total return. Proxy for the AI capex trade."},
    {"id": "china", "name": "China / reflation (MCHI)", "ticker": "MCHI", "source": "polygon",
     "description": "iShares MSCI China ETF, monthly total return. Broad China equity proxy."},
    {"id": "rates", "name": "Rates & duration (TLT)", "ticker": "TLT", "source": "polygon",
     "description": "iShares 20+ Year Treasury Bond ETF, monthly total return. Rises when long "
                    "yields fall, so a positive reading means a manager does well when rates fall."},
    {"id": "crude", "name": "Crude & energy (WTI)", "ticker": "DCOILWTICO", "source": "fred",
     "description": "WTI spot price, month-end to month-end % change."},
    {"id": "vol", "name": "Index volatility (VIX)", "ticker": "VIXCLS", "source": "fred",
     "description": "CBOE VIX close, month-end to month-end % change."},
]

_CACHE_TTL_SECONDS = 24 * 60 * 60
_cache: dict = {"at": 0.0, "data": None}
_lock = threading.Lock()


def _window() -> tuple[str, str]:
    """Fetch range: one extra month at the front so the first return computes."""
    today = dt.date.today()
    start = today.replace(year=today.year - int(config.FACTOR_HISTORY_YEARS), day=1)
    start = (start - dt.timedelta(days=1)).replace(day=1)
    return start.isoformat(), today.isoformat()


def _fetch_polygon(ticker: str) -> list[tuple[str, float]]:
    import requests

    start, end = _window()
    url = (f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/month/{start}/{end}")
    try:
        resp = requests.get(url, params={"adjusted": "true", "sort": "asc",
                                         "apiKey": config.POLYGON_API_KEY}, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
    except requests.RequestException as e:
        raise FactorDataUnavailable(f"Polygon {ticker} fetch failed: {e}") from e

    out = []
    for bar in payload.get("results") or []:
        stamp = bar.get("t")
        close = bar.get("c")
        if stamp is None or close is None:
            continue
        month = dt.datetime.fromtimestamp(stamp / 1000, dt.timezone.utc).strftime("%Y-%m")
        out.append((month, float(close)))
    return out


def _fetch_fred(series_id: str) -> list[tuple[str, float]]:
    import requests

    start, end = _window()
    try:
        resp = requests.get(
            "https://api.stlouisfed.org/fred/series/observations",
            params={"series_id": series_id, "api_key": config.FRED_API_KEY,
                    "file_type": "json", "observation_start": start,
                    "observation_end": end, "frequency": "m",
                    "aggregation_method": "eop"},
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()
    except requests.RequestException as e:
        raise FactorDataUnavailable(f"FRED {series_id} fetch failed: {e}") from e

    out = []
    for obs in payload.get("observations") or []:
        value = obs.get("value")
        date = obs.get("date") or ""
        if not value or value == "." or len(date) < 7:
            continue
        try:
            out.append((date[:7], float(value)))
        except ValueError:
            continue
    return out


def _monthly_returns(closes: list[tuple[str, float]]) -> dict[str, float]:
    """Month-over-month % change, keyed ``YYYY-MM``.

    The first month is consumed as the base and does not appear in the output —
    which is why the fetch window reaches one month further back than the data
    actually needed.
    """
    closes = sorted(closes, key=lambda c: c[0])
    out: dict[str, float] = {}
    for (_, prev), (month, curr) in zip(closes, closes[1:]):
        if prev:
            out[month] = round((curr - prev) / prev * 100, 2)
    return out


def get_factor_series(force_refresh: bool = False) -> dict[str, dict[str, float]]:
    """``{factor_id: {"YYYY-MM": pct}}`` for all five factors.

    Cached for 24h: the series are monthly and historical, so refetching more
    often spends API quota to learn nothing.
    """
    if not config.factors_configured():
        raise FactorDataUnavailable(
            "FRED_API_KEY and POLYGON_API_KEY are not set. Add them to .env "
            "(see .env.example). There is deliberately no demo mode — a "
            "correlation against fabricated factor data would look exactly like "
            "a real one."
        )

    now = time.time()
    if not force_refresh and _cache["data"] and now - _cache["at"] < _CACHE_TTL_SECONDS:
        return _cache["data"]

    with _lock:
        now = time.time()
        if not force_refresh and _cache["data"] and now - _cache["at"] < _CACHE_TTL_SECONDS:
            return _cache["data"]

        series: dict[str, dict[str, float]] = {}
        for factor in FACTORS:
            closes = (_fetch_polygon(factor["ticker"]) if factor["source"] == "polygon"
                      else _fetch_fred(factor["ticker"]))
            series[factor["id"]] = _monthly_returns(closes)

        _cache["data"] = series
        _cache["at"] = time.time()
        return series


def pearson(xs: list[float], ys: list[float]) -> Optional[float]:
    """Pearson correlation, or None when either series is flat.

    A flat series has no defined correlation. Returning None rather than 0.0
    keeps "no relationship" distinguishable from "not answerable".
    """
    n = len(xs)
    if n < 2 or n != len(ys):
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    cov = vx = vy = 0.0
    for x, y in zip(xs, ys):
        dx, dy = x - mx, y - my
        cov += dx * dy
        vx += dx * dx
        vy += dy * dy
    if vx <= 0 or vy <= 0:
        return None
    return round(cov / math.sqrt(vx * vy), 3)


def correlate(manager_months: dict[str, float], factor_months: dict[str, float],
              minimum: Optional[int] = None) -> dict:
    """Correlate one manager against one factor over their shared months."""
    floor = config.FACTOR_MIN_OVERLAP_MONTHS if minimum is None else minimum
    shared = sorted(set(manager_months) & set(factor_months))
    if len(shared) < floor:
        return {"r": None, "n": len(shared), "reason": "not enough overlapping months"}
    xs = [manager_months[m] for m in shared]
    ys = [factor_months[m] for m in shared]
    r = pearson(xs, ys)
    return {"r": r, "n": len(shared),
            "reason": "" if r is not None else "no variance in one series",
            "from": shared[0], "to": shared[-1]}


def build_matrix(records_base=None) -> dict:
    """Every stored track record against every factor.

    Managers whose records carry no monthly returns are reported in
    ``excluded`` with the reason, rather than dropped silently — a manager
    missing from the table for an unstated reason reads as a manager with no
    relationship to any factor.
    """
    factor_series = get_factor_series()
    records = track_record_store.list_all(records_base)

    rows, excluded = [], []
    for record in records:
        name = track_record_store.display_name(record)
        months = track_record_store.monthly_series(record)
        if not months:
            excluded.append({
                "org": name,
                "reason": ("reports quarterly periods only — the five factors are monthly, "
                           "and resampling one to the other would invent detail")
                if track_record_store.quarterly_only(record)
                else "no monthly return figures in the record",
            })
            continue

        by_factor = {f["id"]: correlate(months, factor_series.get(f["id"], {}))
                     for f in FACTORS}
        ordered = sorted(months)
        rows.append({
            "org": name,
            "manager": record.get("manager", ""),
            "strategy": record.get("strategy", ""),
            "vehicle_type": record.get("vehicle_type", "unknown"),
            "currency": record.get("currency", ""),
            "months": len(months),
            "window": {"from": ordered[0], "to": ordered[-1]},
            "caveats": record.get("caveats") or [],
            "by_factor": by_factor,
        })

    rows.sort(key=lambda r: r["org"].lower())
    qualifying = sum(1 for r in rows
                     if any(c["r"] is not None for c in r["by_factor"].values()))
    return {
        "factors": FACTORS,
        "managers": rows,
        "excluded": excluded,
        "minimum_months": config.FACTOR_MIN_OVERLAP_MONTHS,
        "counts": {
            "records_held": len(records),
            "with_monthly_returns": len(rows),
            "qualifying": qualifying,
            "excluded": len(excluded),
        },
    }
