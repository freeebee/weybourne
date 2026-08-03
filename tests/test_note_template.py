"""The saved note must follow the workspace's Notion template: H3 sections
with a divider beneath, **Keyword** - description bullets in real bold, title
and note type kept out of the body (they live in the page properties)."""
from src.features.notion_sync import markdown_children
from src.features.transcription import note_to_markdown

MD = """# Call with Axiom Asia
*GP Meeting*

### Meeting Overview
---
- **Summary** - A short recap of the call.

### Q&A
---
**Q**: What is the fund cap?
**A** - The answer remains outstanding."""


def test_headings_get_dividers_and_title_stays_out_of_body():
    blocks = markdown_children(MD)
    kinds = [b["type"] for b in blocks]
    assert kinds == ["heading_3", "divider", "bulleted_list_item",
                     "heading_3", "divider", "paragraph", "paragraph"]
    h3 = blocks[0]["heading_3"]["rich_text"]
    assert h3[0]["text"]["content"] == "Meeting Overview"
    # No block carries the page title or the italic type line.
    all_text = str(blocks)
    assert "Call with Axiom Asia" not in all_text
    assert "GP Meeting" not in all_text


def test_bold_keyword_renders_as_real_bold():
    [bullet] = [b for b in markdown_children(MD) if b["type"] == "bulleted_list_item"]
    rich = bullet["bulleted_list_item"]["rich_text"]
    assert rich[0]["text"]["content"] == "Summary"
    assert rich[0]["annotations"] == {"bold": True}
    assert rich[1]["text"]["content"] == " - A short recap of the call."
    assert "annotations" not in rich[1]


def test_note_to_markdown_includes_summary_bullet():
    md = note_to_markdown({
        "title": "T", "note_type": "GP Meeting", "summary": "One paragraph.",
        "overall_impression": "Solid.", "next_stage": "Data room.",
        "sections": [], "qa": [],
    })
    assert "- **Summary** - One paragraph." in md
    assert md.index("**Summary**") < md.index("**Overall Impression**")
