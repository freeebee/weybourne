"""Feature modules for the Weybourne Investment Connector.

Each module implements one capability on top of the connectors + Claude:
  inbox_triage   — classify inbox mail for investment relevance, extract entities
  dedupe         — match entities against Contacts / Companies / Funds
  notion_sync    — turn a non-duplicate entity into a Notion page
  preferences    — screen an opportunity against the CHAO preference pages
  draft_reply    — generate selectable draft replies (pass / offer meeting)
  meeting_prep   — build a meeting preparation brief
  track_record   — normalise fund track records (Excel/PDF) to a common schema
  transcription  — live meeting transcript + on-the-fly questions (scaffold)
"""
