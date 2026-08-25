"""Inbox Signal — what the shared mailbox says, read as one body of evidence.

The Investments shared mailbox (``config.SHARED_MAILBOX``) receives manager
letters, performance estimates and administrative traffic continuously. This
package turns the manager correspondence in it into the three views of the
Inbox Signal dashboard:

* **Views from the street** — what the desk collectively believes right now,
  and how that has moved: themes, stance, reversals, disagreements, watchlist.
* **Manager performance** — reported figures and their correlation to market
  factors (see also ``src/features/factor_correlation.py``).
* **Correspondence** — the searchable log of what was actually said, quoted
  verbatim and attributed.

Two design commitments run through the whole package:

1. **Nothing is invented.** Every quote is verbatim from a real message, every
   figure is one a manager stated. Where evidence is too thin to support a
   number — most obviously a correlation over a handful of months — the answer
   is "not enough data", never a plausible-looking figure.
2. **Transport is not the feature's concern.** Mail arrives either from live
   Graph or from a snapshot written by Claude's Microsoft 365 connector (see
   ``scripts/refresh_shared_inbox_snapshot.py``). Everything here consumes
   ``EmailMessage`` objects and neither knows nor cares which one delivered
   them. The single exception is attachment *bytes*, which only live Graph can
   supply; ``attachments.py`` records those as pending rather than branching
   the pipeline.
"""
