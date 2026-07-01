"""Folder scanning, file hashing, and manifest diffing.

Each pipeline run scans the watched PDF folder, hashes every file, and
compares against manifest_table to figure out which files are new or have
changed since the last run. Only those get (re)processed.
"""
import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from src.config import PDF_FOLDER
from src.db import get_manifest_entry

CHUNK_SIZE = 1024 * 1024


def hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK_SIZE), b""):
            h.update(chunk)
    return h.hexdigest()


def scan_pdfs(folder: Path = PDF_FOLDER) -> list[Path]:
    if not folder.exists():
        return []
    return sorted(p for p in folder.glob("*.pdf") if p.is_file())


@dataclass
class DiffResult:
    new_files: list[Path]
    changed_files: list[Path]
    unchanged_files: list[Path]

    @property
    def to_process(self) -> list[Path]:
        return self.new_files + self.changed_files


def diff_against_manifest(conn: sqlite3.Connection, files: list[Path]) -> DiffResult:
    new_files, changed_files, unchanged_files = [], [], []
    for path in files:
        file_hash = hash_file(path)
        entry = get_manifest_entry(conn, path.name)
        if entry is None:
            new_files.append(path)
        elif entry["file_hash"] != file_hash:
            changed_files.append(path)
        else:
            unchanged_files.append(path)
    return DiffResult(new_files=new_files, changed_files=changed_files, unchanged_files=unchanged_files)
