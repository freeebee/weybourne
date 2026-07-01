"""Vision OCR for scanned/image PDF pages, and per-document markdown assembly."""
import base64
from pathlib import Path

import anthropic

from src.config import VISION_MODEL
from src.triage import PageInfo, render_page_png

OCR_PROMPT = (
    "Transcribe this scanned document page to clean markdown. "
    "Preserve tables as markdown tables and preserve numeric figures exactly as shown. "
    "Output only the transcription, with no commentary or preamble."
)


def ocr_page(client: anthropic.Anthropic, pdf_path: Path, page_number: int) -> str:
    png_bytes = render_page_png(pdf_path, page_number)
    image_b64 = base64.standard_b64encode(png_bytes).decode("utf-8")
    response = client.messages.create(
        model=VISION_MODEL,
        max_tokens=4096,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": "image/png", "data": image_b64},
                    },
                    {"type": "text", "text": OCR_PROMPT},
                ],
            }
        ],
    )
    return "".join(block.text for block in response.content if block.type == "text").strip()


def assemble_document_markdown(client: anthropic.Anthropic, pdf_path: Path, pages: list[PageInfo]) -> str:
    """Combine text-layer pages and vision-OCR'd pages into one ordered markdown doc."""
    sections = []
    for page in pages:
        if page.is_text:
            content = page.text
        else:
            content = ocr_page(client, pdf_path, page.page_number)
        sections.append(f"<!-- page {page.page_number} -->\n{content}")
    return "\n\n".join(sections)
