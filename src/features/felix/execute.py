"""Apply / verify machinery — every write follows the same contract:

    freshness guard → local snapshot → Pending record → apply → re-read verify
    → Applied / Failed / Skipped.

The snapshot is written BEFORE the edit so the original state survives an
interrupted run. Dry-run short-circuits after planning: the change is recorded
as ``Planned (dry-run)`` and nothing touches Notion — the change log included,
because a log write is still a write.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from src.connectors.notion_client import plain_value, relation_has_more
from src.features.felix import store
from src.features.felix.models import ChangeRecord


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _recently_edited(page: dict, quiet_minutes: int) -> bool:
    edited = page.get("last_edited_time", "")
    if not edited:
        return False
    try:
        ts = datetime.fromisoformat(edited.replace("Z", "+00:00"))
    except ValueError:
        return False
    return datetime.now(timezone.utc) - ts < timedelta(minutes=quiet_minutes)


def apply_change(notion, change: ChangeRecord, payload: dict,
                 expect_prop: str = "", scanned_plain=None,
                 dry_run: bool = True, quiet_minutes: int = 10,
                 scanned_raw: Optional[dict] = None,
                 base: Optional[Path] = None) -> ChangeRecord:
    """Execute one planned change against Notion (or record it, in dry-run).

    ``payload`` is the update_page kwargs: {"properties": {...}} and/or
    {"icon": ...} / {"archived": ...}. ``expect_prop`` names the property whose
    post-apply value is verified; ``scanned_plain`` is the value seen at scan
    time — if the record moved on since, the change is Skipped, never forced.
    """
    if dry_run:
        change.execution_status = "Planned (dry-run)"
        change.timestamp = _now()
        # The plan itself is snapshotted so Approve in the review UI can
        # execute EXACTLY this payload later — the guard values travel too.
        store.save_snapshot(change.change_id, {
            "kind": "planned", "record_id": change.record_id,
            "database": change.database, "planned": payload,
            "expect_prop": expect_prop, "scanned_plain": scanned_plain,
            "scanned_raw": scanned_raw or {}}, base)
        store.append_change(change, base)
        return change

    # 1. Freshness guard — never race the user.
    try:
        current = notion.get_page(change.record_id)
    except Exception as e:  # noqa: BLE001
        change.execution_status = "Failed"
        change.reason = (change.reason + f" [pre-read failed: {e}]")[:900]
        store.append_change(change, base)
        return change
    if _recently_edited(current, quiet_minutes):
        change.execution_status = "Skipped"
        change.undo_result = "record edited in the last few minutes"
        store.append_change(change, base)
        return change
    if expect_prop and scanned_plain is not None and not current.get("mock"):
        _, live_now = plain_value(
            (current.get("properties") or {}).get(expect_prop, {}) or {})
        if live_now != scanned_plain:
            change.execution_status = "Skipped"
            change.undo_result = "value changed since the scan"
            store.append_change(change, base)
            return change

    # 2. Snapshot before touching anything. The scanned raw properties back
    #    up the re-read (the mock connector's get_page carries none).
    before_props = current.get("properties") or scanned_raw or {}
    store.save_snapshot(change.change_id, {
        "record_id": change.record_id,
        "database": change.database,
        "before_properties": before_props,
        "before_icon": current.get("icon"),
        "before_archived": bool(current.get("archived")),
        "planned": payload,
        "expect_prop": expect_prop,
    }, base)

    # 3. Pending on the log, then apply.
    change.execution_status = "Pending"
    change.timestamp = _now()
    store.append_change(change, base)
    try:
        notion.update_page(change.record_id,
                           properties=payload.get("properties"),
                           icon=payload.get("icon"),
                           archived=payload.get("archived"))
    except Exception as e:  # noqa: BLE001
        change.execution_status = "Failed"
        change.reason = (change.reason + f" [apply failed: {e}]")[:900]
        store.append_change(change, base)
        return change

    # 4. Verify by re-reading.
    ok = True
    try:
        after = notion.get_page(change.record_id)
        if not after.get("mock"):
            if "archived" in payload:
                ok = bool(after.get("archived")) == bool(payload["archived"])
            elif expect_prop and payload.get("properties"):
                _, want = plain_value(payload["properties"].get(expect_prop, {}))
                _, got = plain_value(
                    (after.get("properties") or {}).get(expect_prop, {}) or {})
                ok = got == want
    except Exception:  # noqa: BLE001 - unverifiable ≠ failed; keep Applied
        ok = True
    change.execution_status = "Applied" if ok else "Failed"
    if not ok:
        change.reason = (change.reason + " [verify: value did not stick]")[:900]
    store.append_change(change, base)
    return change


# --------------------------------------------------------------------------- #
# Merges — snapshot both records completely, transfer, repoint, archive.
# --------------------------------------------------------------------------- #

def execute_merge(notion, run_id: str, seq_start: int, survivor: dict,
                  loser: dict, transfers: dict, all_cards: list[dict],
                  schema_prop_ids: dict, confidence: str, source: str,
                  reason: str, dry_run: bool = True, quiet_minutes: int = 10,
                  base: Optional[Path] = None,
                  on_change=None) -> tuple[list[ChangeRecord], int]:
    """The full reversible consolidation. Returns (records, next_seq)."""
    seq = seq_start
    parent_id = store.change_id_for(run_id, seq)
    seq += 1

    # Reverse lookup from the scan: every page whose relations include the
    # loser. The scan is strict/complete, so this needs no extra queries —
    # except where Notion truncated a >25-id relation, fetched in full here.
    inbound = []
    for c in all_cards:
        for prop, ids in c["relations"].items():
            if loser["id"] in ids:
                full = ids
                if relation_has_more({"properties": c["raw"]}, prop):
                    pid = schema_prop_ids.get((c["db"], prop), "")
                    if pid:
                        try:
                            items = notion.page_property_items(c["id"], pid)
                            full = [i.get("relation", {}).get("id", "")
                                    for i in items if i.get("relation")]
                        except Exception:  # noqa: BLE001
                            pass
                inbound.append({"card": c, "property": prop, "ids": full})

    parent = ChangeRecord(
        change_id=parent_id, run_id=run_id, timestamp=_now(),
        database=loser["db"], record_name=loser["name"],
        record_id=loser["id"], record_url=loser["url"], change_type="merge",
        property_changed="(whole record)",
        previous_value=f"standalone record '{loser['name']}'",
        new_value=f"merged into '{survivor['name']}' ({survivor['id']})",
        source=source, reason=reason, confidence=confidence,
    )

    if dry_run:
        parent.execution_status = "Planned (dry-run)"
        store.append_change(parent, base)
        records = [parent]
        for t in transfers["transfers"]:
            seq_id = store.change_id_for(run_id, seq); seq += 1
            rec = ChangeRecord(
                change_id=seq_id, run_id=run_id, timestamp=_now(),
                database=survivor["db"], record_name=survivor["name"],
                record_id=survivor["id"], record_url=survivor["url"],
                change_type="merge_transfer", property_changed=t["property"],
                previous_value=str(survivor["plain"].get(t["property"], "")),
                new_value=str(t.get("value") or plain_value(t.get("payload", {}))[1]),
                parent_change_id=parent_id, confidence=confidence,
                source=source, reason="transferred from the duplicate",
                execution_status="Planned (dry-run)")
            store.append_change(rec, base)
            records.append(rec)
        for row in inbound:
            seq_id = store.change_id_for(run_id, seq); seq += 1
            rec = ChangeRecord(
                change_id=seq_id, run_id=run_id, timestamp=_now(),
                database=row["card"]["db"], record_name=row["card"]["name"],
                record_id=row["card"]["id"], record_url=row["card"]["url"],
                change_type="fix_relation", property_changed=row["property"],
                previous_relation_ids=row["ids"],
                new_relation_ids=[survivor["id"] if i == loser["id"] else i
                                  for i in row["ids"]],
                parent_change_id=parent_id, confidence=confidence,
                source=source, reason="repointed from the duplicate to the survivor",
                execution_status="Planned (dry-run)")
            store.append_change(rec, base)
            records.append(rec)
        if on_change:
            for r in records:
                on_change(r)
        return records, seq

    # ---- live merge ---- #
    snapshot = {
        "kind": "merge",
        "survivor": {"id": survivor["id"], "name": survivor["name"],
                     "properties": survivor["raw"]},
        "loser": {"id": loser["id"], "name": loser["name"],
                  "properties": loser["raw"], "icon": loser["icon"]},
        "inbound": [{"page_id": r["card"]["id"], "db": r["card"]["db"],
                     "property": r["property"], "ids": r["ids"]}
                    for r in inbound],
        "conflicts": transfers["conflicts"],
        "pointer_block_id": "",
    }
    store.save_snapshot(parent_id, snapshot, base)
    parent.execution_status = "Pending"
    store.append_change(parent, base)
    records = [parent]

    def _child(**kw) -> ChangeRecord:
        nonlocal seq
        cid = store.change_id_for(run_id, seq); seq += 1
        rec = ChangeRecord(change_id=cid, run_id=run_id, timestamp=_now(),
                           parent_change_id=parent_id, confidence=confidence,
                           source=source, **kw)
        records.append(rec)
        return rec

    failed = False
    # 1. Transfers into the survivor (one update, child records per property).
    prop_payload: dict = {}
    for t in transfers["transfers"]:
        if t["kind"] == "union":
            if t["ptype"] == "multi_select":
                prop_payload[t["property"]] = {
                    "multi_select": [{"name": n} for n in t["value"]]}
            else:
                prop_payload[t["property"]] = {
                    "relation": [{"id": i} for i in t["value"]]}
        else:
            payload = dict(t["payload"])
            payload.pop("id", None); payload.pop("type", None)
            prop_payload[t["property"]] = payload
        _child(database=survivor["db"], record_name=survivor["name"],
               record_id=survivor["id"], record_url=survivor["url"],
               change_type="merge_transfer", property_changed=t["property"],
               previous_value=str(survivor["plain"].get(t["property"], "")),
               new_value=str(t.get("value") or plain_value(t.get("payload", {}))[1]),
               reason="transferred from the duplicate")
    if prop_payload:
        try:
            notion.update_page(survivor["id"], properties=prop_payload)
        except Exception as e:  # noqa: BLE001
            failed = True
            for r in records[1:]:
                r.execution_status = "Failed"
                r.reason = (r.reason + f" [transfer failed: {e}]")[:900]
    for r in records[1:]:
        if r.execution_status == "Pending":
            r.execution_status = "Applied"
        store.append_change(r, base)

    # 2. Conflicts become recommendation children — logged, not overwritten.
    for cf in transfers["conflicts"]:
        rec = _child(database=survivor["db"], record_name=survivor["name"],
                     record_id=survivor["id"], record_url=survivor["url"],
                     change_type="recommendation",
                     property_changed=cf["property"],
                     previous_value=str(cf["survivor"]),
                     new_value=f"duplicate had: {cf['loser']}",
                     reason="both records held different values; kept the survivor's",
                     execution_status="Recommended")
        store.append_change(rec, base)

    # 3. Repoint inbound relations.
    for row in inbound:
        new_ids = []
        for i in row["ids"]:
            repl = survivor["id"] if i == loser["id"] else i
            if repl not in new_ids:
                new_ids.append(repl)
        rec = _child(database=row["card"]["db"], record_name=row["card"]["name"],
                     record_id=row["card"]["id"], record_url=row["card"]["url"],
                     change_type="fix_relation", property_changed=row["property"],
                     previous_relation_ids=row["ids"], new_relation_ids=new_ids,
                     reason="repointed from the duplicate to the survivor")
        try:
            notion.update_page(row["card"]["id"], properties={
                row["property"]: {"relation": [{"id": i} for i in new_ids]}})
            after = notion.get_page(row["card"]["id"])
            if not after.get("mock"):
                _, got = plain_value((after.get("properties") or {})
                                     .get(row["property"], {}) or {})
                rec.execution_status = ("Applied" if loser["id"] not in got
                                        else "Failed")
            else:
                rec.execution_status = "Applied"
        except Exception as e:  # noqa: BLE001
            rec.execution_status = "Failed"
            rec.reason = (rec.reason + f" [{e}]")[:900]
            failed = True
        store.append_change(rec, base)

    # 4. Pointer callout on the loser, then archive it.
    try:
        blocks = notion.append_blocks(loser["id"], [{
            "object": "block", "type": "callout",
            "callout": {"icon": {"type": "emoji", "emoji": "↪"},
                        "rich_text": [
                            {"text": {"content": "Merged into "}},
                            {"mention": {"page": {"id": survivor["id"]}},
                             "type": "mention"},
                        ]},
        }])
        snapshot["pointer_block_id"] = (blocks.get("results") or [{}])[0].get("id", "")
        store.save_snapshot(parent_id, snapshot, base)
    except Exception:  # noqa: BLE001 - the pointer is best-effort
        pass
    arch = _child(database=loser["db"], record_name=loser["name"],
                  record_id=loser["id"], record_url=loser["url"],
                  change_type="archive", property_changed="(page)",
                  previous_value="active", new_value="archived",
                  reason="duplicate consolidated into the survivor")
    try:
        notion.update_page(loser["id"], archived=True)
        arch.execution_status = "Applied"
    except Exception as e:  # noqa: BLE001
        arch.execution_status = "Failed"
        arch.reason = (arch.reason + f" [{e}]")[:900]
        failed = True
    store.append_change(arch, base)

    parent.execution_status = "Failed" if failed else "Applied"
    store.append_change(parent, base)
    if on_change:
        for r in records:
            on_change(r)
    return records, seq
