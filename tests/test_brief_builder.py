"""Rendering tests for the DD briefing against the user's brief kit (no model calls)."""
from src.features.brief_builder import render_briefing


def _base(**over):
    data = {
        "entity": "Axiom Asia",
        "descriptor": "Pan-Asian private equity fund of funds",
        "is_manager": True,
        "relationship": "Existing relationship since 2019",
        "vehicle": "Fund VII, 2026 vintage, raising",
        "meeting_details": "GP meeting · 2026-08-04 10:00",
        "meetings": [{
            "date": "2025-11-04", "title": "Call with Axiom Asia",
            "attendees": "J. Chen; L. Tan (Axiom)", "format": "Video call",
            "summary": "Discussed Fund VII pacing. Follow-up on co-invest terms outstanding.",
            "source": "Notion · Notes",
        }],
        "no_meetings_text": "",
        "other_mentions": [{
            "source": "Outlook", "date": "2026-01-12", "context": "Pipeline email",
            "text": "Fund VII data room access shared ahead of the meeting.",
        }],
        "landscape_md": "Asian PE fundraising remains slow.\n\n- Dry powder at record highs\n- Exits constrained",
        "manager_bg_md": "No leadership changes since Fund VI (as at Jan 2026).",
        "red_flags_md": "Nothing concerning found on the firm or key GPs.",
        "strategy_md": "Primary fund commitments with **selective co-investment**.",
        "questions_a": [{"q": "Does the sourcing edge survive larger cheques?", "src": "Deck p.8 vs Preqin 2025"}],
        "questions_b": [{"q": "What are the fee offsets on co-invest?", "src": "LPA summary p.3"}],
        "deals_omit_text": "",
        "ledger": [{
            "company": "MedTech Co", "fund_sector": "Fund VI · Healthcare", "entry": "2021-06",
            "cost": "$25m", "ownership": "12%", "moic": "3.1x", "irr": "38%",
            "description": "Hospital software", "hot": True,
        }],
        "deal_cards": [{
            "name": "MedTech Co", "figs": "$25m cost · 12% · 3.1x · 38% IRR",
            "business": "Hospital scheduling software.",
            "actions": "Board seat; new CEO in 2022.",
            "newsflow": "Raised a Series D in 2025 at a higher mark.",
            "questions": [{"q": "How much of the 3.1x is the Series D mark?", "src": "Deck p.14"}],
            "key_flag": "Single position drives most of Fund VI performance.",
        }],
        "standouts_md": "MedTech Co drives the fund's reported multiple.",
        "sources": [{"kind": "Notion", "text": "Funds: Axiom Asia"},
                    {"kind": "Deck", "text": "Fund VII overview"}],
    }
    data.update(over)
    return data


def test_manager_briefing_fills_every_region():
    out = render_briefing(_base())
    for expected in ("Axiom Asia", "Historical meeting context", "MedTech Co",
                     "Key flag", "Single position drives", "Deck p.8 vs Preqin 2025",
                     "Standouts", "Funds: Axiom Asia", "Fund VII, 2026 vintage"):
        assert expected in out
    assert "<!-- FILL" not in out            # every region replaced
    assert "__ENTITY__" not in out and "__DATE__" not in out
    assert 'class="is-flagged"' in out       # shaded ledger row
    assert "page--ink" in out                # kit's cover page intact
    assert "@import url" in out              # style block untouched


def test_non_manager_deletes_deal_pages():
    out = render_briefing(_base(
        is_manager=False, ledger=[], deal_cards=[],
        deals_omit_text="Omitted: the relationship is not an investment manager or fund.",
    ))
    assert "Omitted: the relationship is not an investment manager" in out
    assert "Deal summary" not in out         # both deal pages removed
    assert "deal-by-deal" not in out.lower()
    assert "<!-- FILL" not in out


def test_no_deck_swaps_anchor_for_note():
    out = render_briefing(_base())
    assert "__PDF__" not in out
    assert "No source deck was provided" in out


def test_deck_embeds_as_base64():
    out = render_briefing(_base(), pdf_bytes=b"%PDF-1.4 fake", deck_name="fund-vii.pdf")
    assert "data:application/pdf;base64," in out
    assert "fund-vii.pdf" in out
    assert "No source deck was provided" not in out


def test_no_meetings_path():
    out = render_briefing(_base(
        meetings=[],
        no_meetings_text="No prior meetings on record; built around the introduction thread.",
    ))
    assert "No prior meetings on record" in out


def test_html_escaping():
    out = render_briefing(_base(entity='Fund <"X"> & Co'))
    assert "Fund &lt;&quot;X&quot;&gt; &amp; Co" in out
