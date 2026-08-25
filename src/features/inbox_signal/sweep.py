"""Read the sampled windows of the shared mailbox, once.

The word doing the work in that sentence is **once**. This runs automatically
whenever the app opens, and each new message costs a model call, so the sweep is
built around never repeating itself:

* the manifest records every message id it has handled, whatever the outcome,
  and those are skipped without so much as reading the body;
* a per-sweep cap bounds the very first run over a cold manifest, so a backfill
  spreads across a few launches rather than arriving as one large bill;
* the whole thing is a no-op when ``INBOX_SIGNAL_ENABLED`` is off.

Progress and cancellation come in as plain callables rather than a job object,
so ``src/`` keeps no dependency on the API layer and the sweep is testable with
no job machinery at all.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from src import config
from src.features import track_record_store
from src.features.inbox_signal import attachments as att_mod
from src.features.inbox_signal import manifest as mf
from src.features.inbox_signal import store
from src.features.inbox_signal.extract_letter import extract_letter
from src.features.inbox_signal.periods import PERIODS


def _noop(*_args, **_kwargs) -> None:
    return None


def _never(*_args, **_kwargs) -> bool:
    return False


def sweep(client, graph, *, base: Optional[Path] = None,
          voices_base: Optional[Path] = None,
          records_base: Optional[Path] = None,
          max_messages: Optional[int] = None,
          on_progress: Callable[[int, int, str], None] = _noop,
          check_cancel: Callable[[], bool] = _never) -> dict:
    """Extract new manager correspondence from the five sampled windows.

    Returns a summary dict — also stored on the manifest, so the dashboard can
    show what the last sweep cost without re-deriving it.
    """
    if not config.INBOX_SIGNAL_ENABLED:
        return {"skipped": True, "reason": "INBOX_SIGNAL_ENABLED is off"}

    cap = max_messages if max_messages is not None else config.INBOX_SIGNAL_MAX_MESSAGES_PER_SWEEP

    # Collect first, extract second. Listing is free and tells us the real
    # workload up front, which makes the progress bar honest and lets the cap
    # be applied to a known total rather than discovered mid-run.
    pending: list[tuple[str, object]] = []
    seen_total = 0
    with mf.Manifest(base) as m:
        for period in PERIODS:
            try:
                messages = graph.list_shared_inbox(top=500, start=period.start, end=period.end)
            except Exception as e:  # noqa: BLE001 — one bad window must not lose the rest
                on_progress(0, 0, f"{period.key}: could not list ({e})")
                continue
            for email in messages:
                seen_total += 1
                if not mf.seen(m.data, email.id):
                    pending.append((period.key, email))

    capped = len(pending) > cap
    todo = pending[:cap]
    total = len(todo)

    summary = {
        "messages_seen": seen_total,
        "already_known": seen_total - len(pending),
        "considered": total,
        "letters": 0,
        "not_letters": 0,
        "failed": 0,
        "quotes": 0,
        "quotes_dropped": 0,
        "returns": 0,
        "attachments_pending": 0,
        "attachments_parsed": 0,
        "capped": capped,
        "remaining": max(0, len(pending) - cap),
    }

    for i, (period_key, email) in enumerate(todo, start=1):
        if check_cancel():
            summary["cancelled_after"] = i - 1
            break
        on_progress(i, total, email.subject or email.sender_email or email.id)

        try:
            result = extract_letter(client, email)
        except Exception as e:  # noqa: BLE001 — record and move on
            summary["failed"] += 1
            with mf.Manifest(base) as m:
                mf.record_message(m.data, email.id, status=mf.FAILED,
                                  period=period_key, subject=email.subject or "",
                                  reason=str(e)[:200])
            continue

        if not result.get("is_manager_letter"):
            summary["not_letters"] += 1
            with mf.Manifest(base) as m:
                mf.record_message(m.data, email.id, status=mf.SKIPPED,
                                  period=period_key, subject=email.subject or "",
                                  reason=result.get("reason", ""))
            continue

        org = result["org"] or email.sender_name or "unattributed"
        letter = {k: v for k, v in result.items() if k != "is_manager_letter"}
        letter["period"] = period_key
        store.add_letter(org, letter, voices_base)

        summary["letters"] += 1
        summary["quotes"] += len(letter.get("quotes") or [])
        summary["quotes_dropped"] += letter.get("quotes_dropped") or 0
        summary["returns"] += len(letter.get("reported_returns") or [])

        att_states = _handle_attachments(client, graph, email, org, summary,
                                         records_base=records_base)

        with mf.Manifest(base) as m:
            mf.record_message(m.data, email.id, status=mf.DONE, period=period_key,
                              org=org, subject=email.subject or "",
                              attachments=att_states)

    with mf.Manifest(base) as m:
        mf.record_sweep(m.data, summary)

    return summary


def _handle_attachments(client, graph, email, org: str, summary: dict,
                        records_base: Optional[Path] = None) -> dict:
    """Parse track-record attachments where possible, queue them where not."""
    states: dict = {}
    for plan in att_mod.plan_for_message(email, graph):
        key = mf.attachment_key(plan["name"], plan["size"], plan["attachment_id"])
        if plan["action"] == "ignore":
            states[key] = {"status": mf.IGNORED, "name": plan["name"], "kind": plan["kind"]}
            continue
        if plan["action"] == "pending":
            states[key] = {"status": mf.PENDING, "name": plan["name"], "kind": plan["kind"],
                           "reason": "attachment bytes need live Graph access"}
            summary["attachments_pending"] += 1
            continue
        try:
            attachment = next(a for a in email.attachments
                              if mf.attachment_key(a.name, a.size, a.id) == key)
            record = att_mod.parse_track_record(client, graph, email.id, attachment)
            track_record_store.save(record, records_base)
            states[key] = {"status": mf.PARSED, "name": plan["name"],
                           "fund": track_record_store.record_key(record)}
            summary["attachments_parsed"] += 1
        except att_mod.AttachmentBytesUnavailable as e:
            states[key] = {"status": mf.PENDING, "name": plan["name"], "reason": str(e)}
            summary["attachments_pending"] += 1
        except Exception as e:  # noqa: BLE001 — a bad spreadsheet must not lose the letter
            states[key] = {"status": mf.PENDING, "name": plan["name"],
                           "reason": f"parse failed: {str(e)[:160]}"}
            summary["attachments_pending"] += 1
    return states
