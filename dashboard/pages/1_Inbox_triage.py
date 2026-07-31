"""Inbox triage → dedupe → Notion → CHAO-screened draft reply."""
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import get_graph, get_notion, page_setup, require_claude, run_ai  # noqa: E402

from src import llm  # noqa: E402
from src.features import notion_sync  # noqa: E402
from src.features.dedupe import dedupe_entity  # noqa: E402
from src.features.draft_reply import generate_draft_options  # noqa: E402
from src.features.inbox_triage import triage_email  # noqa: E402
from src.features.preferences import screen_opportunity  # noqa: E402

page_setup("Inbox triage", icon="📥")
st.title("📥 Inbox triage")
st.caption(
    "Flag investment-relevant mail, check it against Notion, screen it against our "
    "preferences, and draft a reply. Nothing is sent or written without your approval."
)

graph = get_graph()
notion = get_notion()
client = require_claude()

# --------------------------------------------------------------------------- #
# 1. Load the inbox
# --------------------------------------------------------------------------- #
left, right = st.columns([3, 1])
count = right.number_input("Messages", min_value=5, max_value=50, value=15, step=5)
if left.button("Scan inbox", type="primary", use_container_width=True):
    with st.spinner("Reading inbox…"):
        st.session_state.messages = graph.list_inbox(top=int(count))
    st.session_state.pop("triage", None)

messages = st.session_state.get("messages", [])
if not messages:
    st.info("Press **Scan inbox** to begin.")
    st.stop()

# --------------------------------------------------------------------------- #
# 2. Triage
# --------------------------------------------------------------------------- #
if client is not None and st.button(f"Triage {len(messages)} messages"):
    st.caption(
        "One call per message, so each is reasoned about in isolation. On the Claude "
        "account backend this takes a few seconds each and uses your usage limit."
    )
    results = {}
    progress = st.progress(0.0, "Triaging…")
    for i, msg in enumerate(messages):
        try:
            results[msg.id] = triage_email(client, msg)
        except (llm.ClaudeCodeAuthError, llm.ClaudeCodeRateLimited) as e:
            # A backend-level problem affects every remaining message - stop
            # rather than repeating the same failure once per email.
            st.error(f"**Stopped after {i} of {len(messages)}** — {e}")
            break
        except Exception as e:  # noqa: BLE001 - one bad message shouldn't stop the batch
            st.warning(f"Could not triage “{msg.subject}”: {e}")
        progress.progress((i + 1) / len(messages), f"Triaged {i + 1}/{len(messages)}")
    progress.empty()
    st.session_state.triage = results

triage = st.session_state.get("triage", {})
if triage:
    flagged = sum(1 for t in triage.values() if t.is_investment)
    a, b = st.columns(2)
    a.metric("Investment-relevant", flagged)
    b.metric("Not relevant", len(triage) - flagged)

st.divider()

# --------------------------------------------------------------------------- #
# 3. Per-message workflow
# --------------------------------------------------------------------------- #
for msg in messages:
    result = triage.get(msg.id)
    is_investment = result.is_investment if result else None
    badge = "🟢" if is_investment else ("⚪" if is_investment is False else "•")
    header = f"{badge}  {msg.subject}  —  *{msg.sender_name}*"

    with st.expander(header, expanded=bool(is_investment)):
        st.caption(f"{msg.sender_email} · {msg.received}")
        st.write(msg.body_preview or msg.body[:400])

        if result is None:
            st.info("Not yet triaged.")
            continue

        st.markdown(
            f"**{result.category}** · confidence {result.confidence:.0%}  \n{result.rationale}"
        )
        if not result.is_investment:
            continue

        entity = result.entity
        if result.key_facts:
            st.markdown("**Key facts**")
            st.markdown("\n".join(f"- {f}" for f in result.key_facts))

        # -- Dedupe against the main databases ----------------------------- #
        st.markdown("#### 1. Check against Notion")
        with st.spinner("Checking Contacts, Companies and Funds…"):
            decisions = dedupe_entity(
                entity, notion.list_contacts(), notion.list_companies(), notion.list_funds()
            )
        if not decisions:
            st.caption("Nothing identifiable to match on.")
        for kind, decision in decisions.items():
            match = decision.best_match
            if decision.recommended_action == "link_existing":
                st.success(
                    f"**{kind.title()}** — already in Notion as “{match.matched_name}” "
                    f"({match.reason}). Will not create a duplicate."
                )
            elif decision.recommended_action == "review":
                st.warning(
                    f"**{kind.title()}** — “{decision.name}” looks similar to "
                    f"“{match.matched_name}” ({match.score:.0%}). Needs your call."
                )
            else:
                st.info(f"**{kind.title()}** — “{decision.name}” appears to be new.")

        # -- Create the non-duplicate entries ------------------------------ #
        proposals = notion_sync.plan_creations(entity, decisions, comments=result.rationale)
        if proposals:
            st.markdown("**Proposed new Notion entries**")
            approved = set()
            for p in proposals:
                default = not p.needs_review
                label = f"Create {p.kind}: {p.title}"
                if p.needs_review:
                    label += f"  ⚠️ {p.review_reason}"
                if st.checkbox(label, value=default, key=f"approve-{msg.id}-{p.kind}"):
                    approved.add(p.kind)
            if st.button("Create in Notion", key=f"create-{msg.id}", disabled=not approved):
                res = notion_sync.apply_plan(proposals, notion, approved_kinds=approved)
                for kind, ref in res.created:
                    st.success(f"Created {kind}: {ref}")
                for kind, reason in res.skipped:
                    st.caption(f"Skipped {kind} — {reason}")
                for kind, err in res.errors:
                    st.error(f"Failed to create {kind}: {err}")
                if not notion.live:
                    st.caption("Demo mode — nothing was actually written to Notion.")
        else:
            st.caption("No new entries needed.")

        # -- Screen against CHAO preferences ------------------------------- #
        st.markdown("#### 2. Screen against our preferences")
        screen_key = f"screen-{msg.id}"
        if client is not None and st.button("Run preference screen", key=f"btn-{screen_key}"):
            with st.spinner("Screening against the CHAO preference pages…"):
                st.session_state[screen_key] = run_ai(
                    screen_opportunity, client, entity, result.key_facts, notion
                )
        screen = st.session_state.get(screen_key)
        if screen:
            tone = {"Fit": "success", "Partial": "warning",
                    "Non-fit": "error", "Unclear": "info"}[screen.overall_fit]
            getattr(st, tone)(f"**{screen.overall_fit}** · {screen.sleeve} — {screen.summary}")
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**Fits**")
                st.markdown("\n".join(f"- {p}" for p in screen.fit_points) or "_none_")
            with c2:
                st.markdown("**Non-fits**")
                st.markdown("\n".join(f"- {p}" for p in screen.non_fit_points) or "_none_")
            if screen.open_questions:
                st.markdown("**Open questions**")
                st.markdown("\n".join(f"- {q}" for q in screen.open_questions))

            # -- Draft the reply ------------------------------------------- #
            st.markdown("#### 3. Draft a reply")
            offer = st.checkbox("Offer meeting times from my calendar",
                                value=True, key=f"offer-{msg.id}")
            draft_key = f"drafts-{msg.id}"
            if st.button("Generate reply options", key=f"btn-{draft_key}"):
                slots = graph.find_free_slots(max_slots=4) if offer else []
                with st.spinner("Drafting…"):
                    st.session_state[draft_key] = run_ai(
                        generate_draft_options, client, msg, entity, screen, slots
                    )
            options = st.session_state.get(draft_key)
            if options:
                labels = [o.label for o in options]
                chosen = st.radio("Choose a reply", labels, key=f"pick-{msg.id}",
                                  horizontal=True)
                option = next(o for o in options if o.label == chosen)
                edited = st.text_area("Draft", option.body, height=260,
                                      key=f"body-{msg.id}")
                if st.button("Save as draft in Outlook", key=f"save-{msg.id}"):
                    try:
                        graph.create_reply_draft(msg.id, edited)
                        st.success("Draft saved to Outlook — review and send it there.")
                        if not graph.live:
                            st.caption("Demo mode — no draft was actually created.")
                    except Exception as e:  # noqa: BLE001
                        st.error(f"Could not create the draft: {e}")
