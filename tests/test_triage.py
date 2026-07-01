import fitz

from src.triage import render_page_png, triage_pages


def make_text_pdf(path, text="This page has a real extractable text layer."):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    doc.save(path)
    doc.close()
    return path


def make_blank_pdf(path):
    doc = fitz.open()
    doc.new_page()  # no text inserted -> no text layer, like a scanned page
    doc.save(path)
    doc.close()
    return path


def test_triage_classifies_text_page(tmp_path):
    pdf_path = make_text_pdf(tmp_path / "text.pdf")
    pages = triage_pages(pdf_path)

    assert len(pages) == 1
    assert pages[0].is_text is True
    assert "extractable text layer" in pages[0].text


def test_triage_classifies_scanned_page(tmp_path):
    pdf_path = make_blank_pdf(tmp_path / "blank.pdf")
    pages = triage_pages(pdf_path)

    assert len(pages) == 1
    assert pages[0].is_text is False
    assert pages[0].text == ""


def test_render_page_png_returns_bytes(tmp_path):
    pdf_path = make_blank_pdf(tmp_path / "blank.pdf")
    png_bytes = render_page_png(pdf_path, 1)

    assert png_bytes.startswith(b"\x89PNG")
