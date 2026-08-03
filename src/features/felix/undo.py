"""Undo — restore from snapshots, never from display text, never over a
later human edit.

A change can be undone only while the affected value still equals what Felix
wrote. If it moved on, the undo is marked a conflict and nothing is touched.
A missing snapshot refuses with "manual restore required" rather than
reconstructing values from the (truncated, lossy) log strings.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from src.connectors.notion_client import plain_value
from src.features.felix import store


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _finish(change_id: str, status: str, result: str,
            base: Optional[Path]) -> dict:
    store.update_change(change_id, {"execution_status": status,
                                    "undo_result": result,
                                    "review_status": "Awaiting Review"}, base)
    return {"change_id": change_id, "status": status, "result": result}


def undo_change(notion, change_id: str, base: Optional[Path] = None) -> dict:
    change = store.find_change(change_id, base)
    if change is None:
        return {"change_id": change_id, "status": "error",
                "result": "no such change"}
    if change.change_type == "merge":
        return undo_merge(notion, change_id, base)
    if change.execution_status != "Applied":
        return {"change_id": change_id, "status": "error",
                "result": f"not undoable from status {change.execution_status!r}"}
    snap = store.load_snapshot(change_id, base)
    if snap is None:
        return _finish(change_id, "Applied",
                       "Snapshot missing — manual restore required", base)

    page = notion.get_page(change.record_id)
    planned = snap.get("planned", {})
    expect = snap.get("expect_prop", "")

    # The current value must still be Felix's value.
    if not page.get("mock"):
        if "archived" in planned:
            if bool(page.get("archived")) != bool(planned["archived"]):
                return _finish(change_id, "Applied",
                               "Conflict: archived state changed since Felix's edit",
                               base)
        elif expect and planned.get("properties"):
            _, want = plain_value(planned["properties"].get(expect, {}))
            _, got = plain_value((page.get("properties") or {})
                                 .get(expect, {}) or {})
            if got != want:
                return _finish(change_id, "Applied",
                               "Conflict: value changed since Felix's edit — "
                               "review manually", base)

    # Restore the raw previous payload.
    try:
        if "archived" in planned:
            notion.update_page(change.record_id,
                               archived=snap.get("before_archived", False))
        elif "icon" in planned:
            notion.update_page(change.record_id, icon=snap.get("before_icon"))
        elif expect:
            before = (snap.get("before_properties") or {}).get(expect)
            if before is None:
                return _finish(change_id, "Applied",
                               "Snapshot lacks the previous value — manual "
                               "restore required", base)
            payload = dict(before)
            payload.pop("id", None)
            payload.pop("type", None)
            payload.pop("has_more", None)
            notion.update_page(change.record_id, properties={expect: payload})
        else:
            return _finish(change_id, "Applied",
                           "Nothing restorable recorded for this change", base)
    except Exception as e:  # noqa: BLE001
        return _finish(change_id, "Applied", f"Undo failed: {e}", base)
    return _finish(change_id, "Undone", f"Undone at {_now()}", base)


def undo_merge(notion, parent_change_id: str,
               base: Optional[Path] = None) -> dict:
    parent = store.find_change(parent_change_id, base)
    if parent is None or parent.change_type != "merge":
        return {"change_id": parent_change_id, "status": "error",
                "result": "no such merge"}
    snap = store.load_snapshot(parent_change_id, base)
    if snap is None or snap.get("kind") != "merge":
        return _finish(parent_change_id, "Applied",
                       "Snapshot missing — manual restore required", base)

    loser = snap["loser"]
    survivor = snap["survivor"]
    conflicts = 0

    # 1. Bring the loser back with its original properties.
    try:
        notion.update_page(loser["id"], archived=False)
        restore = {}
        for name, payload in (loser.get("properties") or {}).items():
            p = dict(payload)
            ptype = p.pop("type", "")
            p.pop("id", None)
            p.pop("has_more", None)
            if ptype in ("formula", "rollup", "created_time",
                         "last_edited_time", "created_by", "last_edited_by",
                         "unique_id"):
                continue                     # computed — not writable
            restore[name] = p
        if restore:
            notion.update_page(loser["id"], properties=restore)
    except Exception as e:  # noqa: BLE001
        return _finish(parent_change_id, "Applied",
                       f"Could not restore the archived record: {e}", base)

    # 2. Revert the survivor's transferred properties and the repointed
    #    relations, child by child, with per-child conflict detection.
    children = [c for c in store.list_all_changes(base, run_id=parent.run_id,
                                                  limit=10000)
                if c.parent_change_id == parent_change_id]
    for child in children:
        if child.execution_status != "Applied":
            continue
        try:
            if child.change_type == "fix_relation":
                page = notion.get_page(child.record_id)
                if not page.get("mock"):
                    _, got = plain_value((page.get("properties") or {})
                                         .get(child.property_changed, {}) or {})
                    if sorted(got) != sorted(child.new_relation_ids):
                        conflicts += 1
                        store.update_change(child.change_id, {
                            "undo_result": "Conflict: relations changed since"},
                            base)
                        continue
                notion.update_page(child.record_id, properties={
                    child.property_changed: {
                        "relation": [{"id": i}
                                     for i in child.previous_relation_ids]}})
                store.update_change(child.change_id,
                                    {"execution_status": "Undone",
                                     "undo_result": f"Undone at {_now()}"}, base)
            elif child.change_type == "merge_transfer":
                before = (survivor.get("properties") or {}).get(
                    child.property_changed)
                if before is None:
                    conflicts += 1
                    continue
                p = dict(before)
                ptype = p.pop("type", "")
                p.pop("id", None)
                p.pop("has_more", None)
                if ptype in ("formula", "rollup"):
                    continue
                notion.update_page(survivor["id"],
                                   properties={child.property_changed: p})
                store.update_change(child.change_id,
                                    {"execution_status": "Undone",
                                     "undo_result": f"Undone at {_now()}"}, base)
            elif child.change_type == "archive":
                store.update_change(child.change_id,
                                    {"execution_status": "Undone",
                                     "undo_result": f"Undone at {_now()}"}, base)
        except Exception:  # noqa: BLE001
            conflicts += 1

    # 3. Remove Felix's pointer callout from the restored record.
    block_id = snap.get("pointer_block_id")
    if block_id:
        try:
            notion.set_block_archived(block_id, True)
        except Exception:  # noqa: BLE001
            pass

    result = (f"Undone at {_now()}" if not conflicts
              else f"Undone at {_now()} with {conflicts} conflict(s) needing review")
    return _finish(parent_change_id, "Undone", result, base)
