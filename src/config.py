"""Central configuration for the PDF extraction pipeline."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Where source PDFs live (the "watched folder"). New quarterly drops go here.
PDF_FOLDER = Path(os.environ.get("PDF_FOLDER", BASE_DIR / "data" / "pdfs"))

# SQLite database file backing both the pipeline and the Streamlit dashboard.
DB_PATH = Path(os.environ.get("DB_PATH", BASE_DIR / "data" / "dashboard.db"))

# Claude models used for OCR (vision) and structured extraction.
# Override via env if a different model should be used.
VISION_MODEL = os.environ.get("CLAUDE_VISION_MODEL", "claude-opus-4-8")
EXTRACTION_MODEL = os.environ.get("CLAUDE_EXTRACTION_MODEL", "claude-opus-4-8")

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

# Page render resolution for scanned pages sent to vision OCR.
PAGE_RENDER_ZOOM = float(os.environ.get("PAGE_RENDER_ZOOM", "2.0"))

# If a document's assembled markdown exceeds this many characters, split it
# into per-page-range sections and run extraction per section instead of
# a single call (Claude API call per doc "or per section", per project brief).
MAX_DOC_CHARS_PER_CALL = int(os.environ.get("MAX_DOC_CHARS_PER_CALL", "40000"))

# Minimum characters of text on a page before it's considered a "text" page
# rather than a scanned/image page needing OCR.
MIN_TEXT_LAYER_CHARS = int(os.environ.get("MIN_TEXT_LAYER_CHARS", "20"))
