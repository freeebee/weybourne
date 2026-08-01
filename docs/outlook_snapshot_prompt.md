# Getting real Outlook data into the app (no IT approval needed)

The app reads three snapshot files if they exist, in preference to sample data:

- `data/inbox_snapshot.json` — your top-level Inbox
- `data/calendar_snapshot.json` — your upcoming calendar
- `data/shared_inbox_snapshot.json` — the wbinvestments@weybourne.co.uk shared mailbox

Claude (claude.ai or the desktop app) with the **Microsoft 365 connector** enabled
can produce them. Paste the prompt below into a Claude chat, then save each JSON
block it returns into the matching file in this repo's `data/` folder. Refresh
whenever you want newer data — the app picks the files up on the next page load.

---

## Prompt to paste into Claude (M365 connector on)

> Using the Microsoft 365 connector, produce three JSON documents and nothing
> else, each in its own fenced code block labelled with its filename.
>
> **1. `inbox_snapshot.json`** — my top-level Inbox (Focused and Other, nothing
> from subfolders), the 40 most recent messages from the last 7 days. A JSON
> array where each item has exactly these fields:
> `{"id": str, "subject": str, "sender_name": str, "sender_email": str,
> "received": ISO-8601 str, "body_preview": str (first ~200 chars),
> "body": str (plain text, max ~2000 chars), "has_attachments": bool,
> "folder": "Inbox"}`
>
> **2. `calendar_snapshot.json`** — my calendar events for the next 21 days.
> A JSON array where each item has exactly:
> `{"id": str, "subject": str, "start": ISO-8601 str, "end": ISO-8601 str,
> "location": str, "organizer": {"name": str, "email": str},
> "attendees": [{"name": str, "email": str}], "is_online": bool,
> "body_preview": str}`
>
> **3. `shared_inbox_snapshot.json`** — the Inbox of the shared mailbox
> wbinvestments@weybourne.co.uk, the 40 most recent messages from the last
> 7 days, same fields as document 1. If you cannot access the shared mailbox,
> say so and skip it.
>
> Use empty strings for anything unavailable. Do not invent any content.

---

## Alternative routes

- **Fully live (unattended)**: an Entra ID app registration with Mail.Read /
  Calendars.Read (usually needs IT consent) — set `MS_TENANT_ID`,
  `MS_CLIENT_ID`, `MS_CLIENT_SECRET` in `.env`. The shared mailbox then needs
  Mail.Read on that mailbox too.
- **Claude Code MCP**: run `claude mcp add --transport http m365
  https://microsoft365.mcp.claude.com/mcp` and authenticate via `/mcp` in
  Claude Code; future Claude Code sessions can then refresh the snapshots for
  you on request.

Validate a saved snapshot with:

```bash
python scripts/refresh_outlook_snapshot.py --validate
```
