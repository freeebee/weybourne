"""Charlotte's Web — a fund-centered reference graph over the Notion CRM.

crawl.py builds a point-in-time snapshot of nodes and typed edges from a
raw crawl of the four databases; graph.py and lp.py are pure functions over
that snapshot (ego networks, LP reference candidates); store.py owns the
snapshot files and the in-memory memo. Nothing in this package writes to
Notion.
"""
