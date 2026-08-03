"""Felix — the autonomous Notion clean-up agent.

Scans Contacts, Companies, Funds and Notes for duplicates, missing
information, broken relations and formatting errors; executes reversible
High/Medium-confidence fixes automatically; records every individual change
(before/after, evidence, confidence) in a permanent local change log with
review and undo. Never deletes (archives instead), never guesses (every
LLM-proposed value must quote its evidence verbatim or it is downgraded to a
recommendation).

Package layout:
    models       pydantic records (RunOptions, ChangeRecord, RunRecord)
    store        data/felix/ persistence: runs, change log, snapshots, config
    detect       deterministic issue detection — pure functions, no network
    adjudicate   batched FAST_MODEL calls for fuzzy duplicates + evidence
    execute      apply / verify / merge machinery
    undo         change + merge reversal
    run          the pipeline the jobs framework executes
"""
