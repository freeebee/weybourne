from pathlib import Path

from src.db import init_db, get_connection, upsert_manifest_entry
from src.manifest import diff_against_manifest, hash_file, scan_pdfs


def make_pdf(path: Path, content: bytes) -> Path:
    path.write_bytes(content)
    return path


def test_hash_file_is_stable_and_content_sensitive(tmp_path):
    a = make_pdf(tmp_path / "a.pdf", b"hello world")
    b = make_pdf(tmp_path / "b.pdf", b"hello world")
    c = make_pdf(tmp_path / "c.pdf", b"different content")

    assert hash_file(a) == hash_file(b)
    assert hash_file(a) != hash_file(c)


def test_scan_pdfs_only_returns_pdf_files(tmp_path):
    make_pdf(tmp_path / "a.pdf", b"pdf-content")
    (tmp_path / "notes.txt").write_text("not a pdf")

    files = scan_pdfs(tmp_path)
    assert [f.name for f in files] == ["a.pdf"]


def test_scan_pdfs_missing_folder_returns_empty(tmp_path):
    assert scan_pdfs(tmp_path / "does-not-exist") == []


def test_diff_against_manifest_classifies_new_changed_unchanged(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)

    unchanged = make_pdf(tmp_path / "unchanged.pdf", b"same")
    changed = make_pdf(tmp_path / "changed.pdf", b"old-version")
    new = make_pdf(tmp_path / "new.pdf", b"brand-new")

    with get_connection(db_path) as conn:
        upsert_manifest_entry(conn, "unchanged.pdf", hash_file(unchanged), "2026-Q1", "2026-01-01T00:00:00")
        upsert_manifest_entry(conn, "changed.pdf", "stale-hash-value", "2026-Q1", "2026-01-01T00:00:00")

    # Simulate the file changing on disk after it was manifested.
    changed.write_bytes(b"new-version")

    with get_connection(db_path) as conn:
        result = diff_against_manifest(conn, [unchanged, changed, new])

    assert [p.name for p in result.unchanged_files] == ["unchanged.pdf"]
    assert [p.name for p in result.changed_files] == ["changed.pdf"]
    assert [p.name for p in result.new_files] == ["new.pdf"]
    assert sorted(p.name for p in result.to_process) == ["changed.pdf", "new.pdf"]
