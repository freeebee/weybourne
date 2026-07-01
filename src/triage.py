"""Per-page triage: does this page have an extractable text layer, or is it scanned?"""
from dataclasses import dataclass
from pathlib import Path

import fitz  # pymupdf

from src.config import MIN_TEXT_LAYER_CHARS, PAGE_RENDER_ZOOM


@dataclass
class PageInfo:
    page_number: int  # 1-indexed
    is_text: bool
    text: str = ""


def triage_pages(pdf_path: Path) -> list[PageInfo]:
    pages: list[PageInfo] = []
    with fitz.open(pdf_path) as doc:
        for i, page in enumerate(doc):
            text = page.get_text().strip()
            is_text = len(text) >= MIN_TEXT_LAYER_CHARS
            pages.append(PageInfo(page_number=i + 1, is_text=is_text, text=text if is_text else ""))
    return pages


def render_page_png(pdf_path: Path, page_number: int, zoom: float = PAGE_RENDER_ZOOM) -> bytes:
    """Render a 1-indexed page to PNG bytes for vision OCR."""
    with fitz.open(pdf_path) as doc:
        page = doc[page_number - 1]
        matrix = fitz.Matrix(zoom, zoom)
        pixmap = page.get_pixmap(matrix=matrix)
        return pixmap.tobytes("png")
