"""Felix's persisted shapes. Everything else in the package passes plain
dicts; only what lands on disk (and crosses the API) is modelled."""
from __future__ import annotations

import os

from pydantic import BaseModel, Field


class RunOptions(BaseModel):
    dry_run: bool = True
    max_writes: int = int(os.environ.get("FELIX_MAX_WRITES", "50"))
    max_merges: int = int(os.environ.get("FELIX_MAX_MERGES", "5"))
    max_llm_calls: int = int(os.environ.get("FELIX_MAX_LLM_CALLS", "30"))
    # Web-search escalations per run (unsure duplicates + fund field lookups).
    max_research: int = int(os.environ.get("FELIX_MAX_RESEARCH", "10"))
    quiet_minutes: int = int(os.environ.get("FELIX_QUIET_MINUTES", "10"))
    databases: list[str] = Field(
        default_factory=lambda: ["contacts", "companies", "funds", "notes"])


class ChangeRecord(BaseModel):
    """One individual change — the spec's change-log entry, stored locally.

    The raw Notion payloads needed for a byte-accurate undo live in the
    snapshot file (store.save_snapshot); this record carries the human-readable
    account. A Notion change-log mirror can be generated from these later.
    """
    change_id: str
    run_id: str
    timestamp: str
    database: str                    # contacts / companies / funds / notes
    record_name: str = ""
    record_id: str = ""
    record_url: str = ""
    change_type: str = ""            # fill_missing / fix_formatting / fix_icon /
                                     # fix_relation / merge / merge_transfer /
                                     # archive / new_record / recommendation
    property_changed: str = ""
    previous_value: str = ""
    new_value: str = ""
    previous_relation_ids: list[str] = Field(default_factory=list)
    new_relation_ids: list[str] = Field(default_factory=list)
    source: str = ""                 # the evidence pointer
    reason: str = ""
    confidence: str = ""             # High / Medium / Low
    execution_status: str = "Pending"  # Pending / Planned (dry-run) / Applied /
                                       # Failed / Skipped / Undone /
                                       # Proposed (approve applies it) /
                                       # Recommended (informational only)
    review_status: str = "Awaiting Review"  # / Approved / Undo Requested
    undo_result: str = ""
    parent_change_id: str = ""
    # Structured extras for the review UI (JSON string). Merges store the
    # side-by-side record comparison here so an approve decision needs no
    # digging.
    detail: str = ""


class RunRecord(BaseModel):
    run_id: str
    started: str
    finished: str = ""
    status: str = "running"          # running / done / failed / cancelled
    dry_run: bool = True
    databases: list[str] = Field(default_factory=list)
    counts: dict = Field(default_factory=dict)
    deferred: int = 0
    error: str = ""
