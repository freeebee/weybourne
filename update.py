#!/usr/bin/env python3
"""Incremental ingestion run: scan the PDF folder, process new/changed files.

Usage:
    python update.py                      # process everything new since last run
    python update.py --limit 10           # process at most 10 new files (test batch)
    python update.py --dry-run            # show what would be processed, do nothing
    python update.py --period 2026-Q2     # fallback period for docs with no
                                           # detectable period in filename/content
    python update.py --folder ./data/pdfs # override the watched folder
"""
import argparse
import sys
from pathlib import Path

from src.pipeline import run
from src.schemas import PERIOD_RE


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--folder", type=Path, default=None, help="Override the watched PDF folder")
    parser.add_argument("--period", type=str, default=None, help="Fallback period, e.g. 2026-Q2")
    parser.add_argument("--limit", type=int, default=None, help="Process at most N new/changed files")
    parser.add_argument("--dry-run", action="store_true", help="List files that would be processed; don't run")
    args = parser.parse_args()

    if args.period and not PERIOD_RE.match(args.period):
        parser.error(f"--period must look like YYYY-Qn, got {args.period!r}")

    kwargs = {"default_period": args.period, "limit": args.limit, "dry_run": args.dry_run}
    if args.folder:
        kwargs["folder"] = args.folder

    summary = run(**kwargs)

    print(f"Unchanged (skipped): {len(summary.skipped)}")
    if args.dry_run:
        print(f"Would process: {len(summary.processed)}")
        for name in summary.processed:
            print(f"  - {name}")
        return 0

    print(f"Processed: {len(summary.processed)}")
    print(f"  metrics written: {summary.metrics_written}")
    print(f"  notes written:   {summary.notes_written}")
    print(f"  flagged records: {summary.flags_written}")
    if summary.failed:
        print(f"Failed: {len(summary.failed)}")
        for name, err in summary.failed:
            print(f"  - {name}: {err}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
