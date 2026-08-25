"""Week in review — the weekly document over Notion notes, funds and contacts.

Four layers, deliberately kept apart: extraction owns facts, derive owns every
number (dedup, stats, window math — never the model), summarise owns every
judgment (one schema-constrained model call, zero arithmetic), and the
frontend component owns layout. A model asked to interpret *and* tally will
occasionally get the tally wrong, and a wrong headline number discredits an
otherwise correct page — so nothing in derive ever reaches the model, and
nothing the model returns is trusted without being checked against real data.

Package layout:
    extract      Notion reads — notes (with page bodies), funds touched,
                 contacts created in the window
    derive       pure functions: dedup, stats, declined funds, window labels
    summarise    the schema, the prompt, the one model call, post-processing
    build        orchestrator: extract -> derive -> summarise -> assemble
    store        data/week_in_review/ persistence, one file per week
"""
