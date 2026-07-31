"""Normalise fund track records (Excel / CSV / PDF) into one common format.

Track records arrive in whatever layout the manager happens to use — monthly
return grids, quarterly NAV tables, deal-by-deal private-market schedules — so
the shape cannot be hard-coded. The approach is:

    read the file "as text"  ->  Claude normalises it to the common schema
                             ->  pydantic validates  ->  SQLite / dashboard

**The common format** (deliberately covers both worlds, per the brief's
"private market" and "public market" track records):

  *Identity*     manager, fund, vehicle_type, sleeve, currency, inception
  *Periodic*     a row per period: period label, return %, NAV, and (private
                 markets) called / distributed / DPI / TVPI / net IRR
  *Summary*      headline stats the manager quotes, kept separate from the
                 periodic series so we never conflate the two

Two design choices worth noting:

- **Public and private records share one schema** rather than having two.
  ``PeriodicRecord`` carries optional private-market fields, so a monthly hedge
  fund series and a quarterly PE fund series land in the same table and can be
  compared. ``vehicle_type`` says which shape to expect.
- **Summary statistics are never recomputed silently.** What the manager claims
  is stored as ``reported`` in ``SummaryStat``; anything we derive ourselves is
  marked ``derived``, so a manager's headline IRR is never mistaken for our own.

Output formats are expected to be refined over time — the schema below is the
first cut and is versioned via ``SCHEMA_VERSION``.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field

from src.config import EXTRACTION_MODEL

SCHEMA_VERSION = "1.0"

VehicleType = Literal["private", "public", "unknown"]


# --------------------------------------------------------------------------- #
# Common format
# --------------------------------------------------------------------------- #

class PeriodicRecord(BaseModel):
    """One period of a track record. Private-market fields are optional."""
    period: str                              # e.g. '2024-Q1' or '2024-03'
    return_pct: Optional[float] = None       # net return for the period, %
    nav: Optional[float] = None
    called: Optional[float] = None           # private markets: capital called
    distributed: Optional[float] = None      # private markets: distributions
    dpi: Optional[float] = None
    tvpi: Optional[float] = None
    net_irr_pct: Optional[float] = None
    note: str = ""


class SummaryStat(BaseModel):
    """A headline statistic, tagged with whether the manager claimed it."""
    name: str                                # e.g. 'Net IRR since inception'
    value: float
    unit: str = ""                           # '%', 'x', 'USD m'
    basis: Literal["reported", "derived"] = "reported"
    note: str = ""


class TrackRecord(BaseModel):
    schema_version: str = SCHEMA_VERSION
    manager: str = ""
    fund: str = ""
    vehicle_type: VehicleType = "unknown"
    strategy: str = ""
    currency: str = ""
    inception: str = ""
    fee_basis: str = ""                      # gross/net and fee terms if stated
    benchmark: str = ""
    periods: list[PeriodicRecord] = Field(default_factory=list)
    summary_stats: list[SummaryStat] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    source_file: str = ""


NORMALISE_SCHEMA = {
    "type": "object",
    "properties": {
        "manager": {"type": "string"},
        "fund": {"type": "string"},
        "vehicle_type": {"type": "string", "enum": ["private", "public", "unknown"]},
        "strategy": {"type": "string"},
        "currency": {"type": "string"},
        "inception": {"type": "string"},
        "fee_basis": {"type": "string", "description": "Gross or net, and stated fee terms"},
        "benchmark": {"type": "string"},
        "periods": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "period": {"type": "string", "description": "YYYY-Qn or YYYY-MM"},
                    "return_pct": {"type": ["number", "null"]},
                    "nav": {"type": ["number", "null"]},
                    "called": {"type": ["number", "null"]},
                    "distributed": {"type": ["number", "null"]},
                    "dpi": {"type": ["number", "null"]},
                    "tvpi": {"type": ["number", "null"]},
                    "net_irr_pct": {"type": ["number", "null"]},
                    "note": {"type": "string"},
                },
                "required": ["period", "return_pct", "nav", "called", "distributed",
                             "dpi", "tvpi", "net_irr_pct", "note"],
                "additionalProperties": False,
            },
        },
        "summary_stats": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "value": {"type": "number"},
                    "unit": {"type": "string"},
                    "basis": {"type": "string", "enum": ["reported", "derived"]},
                    "note": {"type": "string"},
                },
                "required": ["name", "value", "unit", "basis", "note"],
                "additionalProperties": False,
            },
        },
        "caveats": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Anything that qualifies the numbers: simulated/backtested "
            "periods, gross vs net, survivorship, currency, restated figures",
        },
    },
    "required": ["manager", "fund", "vehicle_type", "strategy", "currency", "inception",
                 "fee_basis", "benchmark", "periods", "summary_stats", "caveats"],
    "additionalProperties": False,
}

NORMALISE_SYSTEM_PROMPT = """You normalise fund track records into a single common format.

The input is a spreadsheet or document dumped as text, in whatever layout the manager used. \
Work out what the table actually represents, then emit the periodic series and the headline \
statistics separately.

Rules:
- Emit one `periods` entry per reporting period. Use YYYY-Qn for quarterly data and YYYY-MM \
for monthly data. Leave a field null rather than guessing it.
- Returns go in `return_pct` as percentages (7.4 means +7.4%, -3.1 means -3.1%). If the source \
gives decimals (0.074), convert. Never mix the two conventions.
- `summary_stats` are figures the manager states (since-inception IRR, TVPI, annualised return, \
Sharpe). Set basis to "reported" for anything taken from the document. Only use "derived" for \
a figure you computed yourself, and say so in the note.
- Do NOT compute or infer statistics that are not in the source. An absent figure is null.
- Put every qualification in `caveats`: simulated or backtested periods, gross vs net of fees, \
pro-forma or restated numbers, currency, partial periods. This matters more than completeness.
- vehicle_type: "private" for drawdown funds (called/distributed/DPI/TVPI/IRR), "public" for \
periodic NAV/return series (hedge funds, long-only)."""


# --------------------------------------------------------------------------- #
# Readers — file to text
# --------------------------------------------------------------------------- #

def read_spreadsheet(path: Path, max_rows_per_sheet: int = 400) -> str:
    """Render every sheet of an Excel/CSV file as pipe-delimited text."""
    import pandas as pd

    suffix = path.suffix.lower()
    if suffix in (".csv", ".tsv"):
        sep = "\t" if suffix == ".tsv" else ","
        frames = {"data": pd.read_csv(path, sep=sep, header=None, dtype=str)}
    else:
        frames = pd.read_excel(path, sheet_name=None, header=None, dtype=str)

    blocks = []
    for name, df in frames.items():
        df = df.head(max_rows_per_sheet).fillna("")
        rows = [" | ".join(str(v) for v in row) for row in df.itertuples(index=False)]
        blocks.append(f"=== SHEET: {name} ===\n" + "\n".join(rows))
    return "\n\n".join(blocks)


def read_document(path: Path) -> str:
    """Read a track record from a spreadsheet or a PDF."""
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xlsm", ".xls", ".csv", ".tsv"):
        return read_spreadsheet(path)
    if suffix == ".pdf":
        from src.features.meeting_prep import extract_pdf_text

        return extract_pdf_text(path, max_pages=30)
    raise ValueError(f"unsupported track-record file type: {suffix}")


# --------------------------------------------------------------------------- #
# Normalisation
# --------------------------------------------------------------------------- #

def normalise_track_record(client, content: str, source_file: str = "") -> TrackRecord:
    """Normalise raw track-record text into the common format."""
    response = client.messages.create(
        model=EXTRACTION_MODEL,
        max_tokens=8192,
        system=NORMALISE_SYSTEM_PROMPT,
        output_config={"format": {"type": "json_schema", "schema": NORMALISE_SCHEMA}},
        messages=[{"role": "user", "content": f"Source file: {source_file}\n\n{content}"}],
    )
    raw = next((b.text for b in response.content if getattr(b, "type", None) == "text"), "")
    parsed = json.loads(raw)
    record = TrackRecord.model_validate({**parsed, "source_file": source_file})
    return record


def analyse_file(client, path: Path) -> TrackRecord:
    """Read a track-record file and normalise it end to end."""
    return normalise_track_record(client, read_document(path), source_file=path.name)


# --------------------------------------------------------------------------- #
# Derived analytics (computed by us, clearly separated from reported figures)
# --------------------------------------------------------------------------- #

def cumulative_return_pct(periods: list[PeriodicRecord]) -> Optional[float]:
    """Compound the periodic returns. Returns None if no returns are present."""
    returns = [p.return_pct for p in periods if p.return_pct is not None]
    if not returns:
        return None
    growth = 1.0
    for r in returns:
        growth *= 1 + r / 100.0
    return round((growth - 1) * 100, 2)


def best_worst_period(periods: list[PeriodicRecord]) -> tuple[Optional[PeriodicRecord], Optional[PeriodicRecord]]:
    scored = [p for p in periods if p.return_pct is not None]
    if not scored:
        return None, None
    return max(scored, key=lambda p: p.return_pct), min(scored, key=lambda p: p.return_pct)


def max_drawdown_pct(periods: list[PeriodicRecord]) -> Optional[float]:
    """Peak-to-trough drawdown of the compounded return series, as a negative %."""
    returns = [p.return_pct for p in periods if p.return_pct is not None]
    if not returns:
        return None
    level, peak, worst = 1.0, 1.0, 0.0
    for r in returns:
        level *= 1 + r / 100.0
        peak = max(peak, level)
        worst = min(worst, level / peak - 1)
    return round(worst * 100, 2)


def to_fact_rows(record: TrackRecord) -> list[dict]:
    """Flatten a track record into fact_table-shaped rows for the dashboard DB."""
    fund_id = record.fund or record.manager or record.source_file
    rows: list[dict] = []
    numeric_fields = (
        ("return_pct", "%"), ("nav", record.currency or "USD"),
        ("called", record.currency or "USD"), ("distributed", record.currency or "USD"),
        ("dpi", "x"), ("tvpi", "x"), ("net_irr_pct", "%"),
    )
    for p in record.periods:
        for field, unit in numeric_fields:
            value = getattr(p, field)
            if value is None:
                continue
            rows.append({
                "fund_id": fund_id,
                "metric_name": field,
                "value": float(value),
                "unit": unit,
                "period": p.period,
                "source_doc": record.source_file,
            })
    return rows
