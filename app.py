"""
Sentinel review dashboard — the approval-gated layer, not just a display.

Nothing generated here is "the analysis" until a human approves it (with
or without edits) or rejects it. Following the same pattern as Zyntask
Engage's magic review link: AI drafts, human decides, only approved
output is final.

Run with: streamlit run app.py
Requires ANTHROPIC_API_KEY in your environment (or .env) to generate new
drafts — reading existing reviews and running the anomaly pipeline itself
needs no API key.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import streamlit as st  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from sentinel.anomaly import run_all_checks  # noqa: E402
from sentinel.engine import build_peer_table  # noqa: E402
from sentinel.ingestion import load_all, load_company_config, load_sector_config  # noqa: E402
from sentinel.narrative import generate_narrative, group_flags_by_company  # noqa: E402
from sentinel.review import (  # noqa: E402
    ReviewStatus,
    approve_review,
    create_pending_review,
    list_reviews,
    load_review,
    reject_review,
    save_review,
)

st.set_page_config(page_title="Sentinel — Review Queue", layout="wide")


@st.cache_data
def load_pipeline():
    company_config = load_company_config()
    sector_config = load_sector_config(company_config["sector"])
    statements = load_all()
    fy_statements = [s for s in statements if s.period_label == "FY26"]
    peer_df = build_peer_table(statements, sector_config, company_config, period_type="FY")
    flags = run_all_checks(fy_statements, peer_df, sector_config)
    groups = group_flags_by_company(flags)
    return statements, peer_df, sector_config, groups


statements, peer_df, sector_config, groups = load_pipeline()

st.title("Sentinel — Review Queue")
st.caption(f"{sector_config['display_name']} peer set — FY26 — nothing below is final until you approve it")

existing_by_company = {r.company_id: r for r in list_reviews()}

not_generated = sum(1 for g in groups if g[0].company_id not in existing_by_company)
pending = sum(1 for r in existing_by_company.values() if r.status == ReviewStatus.PENDING)
approved = sum(1 for r in existing_by_company.values() if r.is_final)
rejected = sum(1 for r in existing_by_company.values() if r.status == ReviewStatus.REJECTED)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Not generated", not_generated)
c2.metric("Pending review", pending)
c3.metric("Approved", approved)
c4.metric("Rejected", rejected)

st.divider()

for group in groups:
    company_id = group[0].company_id
    company_name = group[0].company_name
    period_label = group[0].period_label
    existing = existing_by_company.get(company_id)

    default_open = existing is None or existing.status == ReviewStatus.PENDING
    with st.expander(f"{company_name} — {len(group)} flag(s)", expanded=default_open):
        for f in group:
            st.markdown(f"- **{f.flag_type}**: {f.description}")

        if existing is None:
            st.info("No draft generated yet.")
            if st.button("Generate draft narrative (2 API calls)", key=f"gen_{company_id}"):
                with st.spinner("Calling Claude — hypothesis, then peer check..."):
                    try:
                        result = generate_narrative(group, statements, peer_df, sector_config)
                        record = create_pending_review(result)
                        save_review(record)
                        st.rerun()
                    except RuntimeError as e:
                        st.error(str(e))

        elif existing.status == ReviewStatus.PENDING:
            st.markdown("**AI hypothesis (turn 1, from the company's own data):**")
            st.write(existing.initial_hypothesis)
            st.markdown("**AI draft narrative (turn 2, checked against peers):**")
            st.write(existing.ai_narrative)

            edited_text = st.text_area(
                "Edit before approving (leave unchanged to approve as-is)",
                value=existing.ai_narrative,
                key=f"edit_{company_id}",
                height=150,
            )
            notes = st.text_input("Reviewer notes (optional)", key=f"notes_{company_id}")

            b1, b2, b3 = st.columns(3)
            if b1.button("Approve", key=f"approve_{company_id}"):
                updated = approve_review(existing, edited_text=edited_text, notes=notes or None)
                save_review(updated)
                st.rerun()
            if b2.button("Reject", key=f"reject_{company_id}"):
                updated = reject_review(existing, notes=notes or None)
                save_review(updated)
                st.rerun()
            if b3.button("Regenerate draft", key=f"regen_{company_id}"):
                with st.spinner("Calling Claude again..."):
                    try:
                        result = generate_narrative(group, statements, peer_df, sector_config)
                        record = create_pending_review(result)
                        save_review(record)
                        st.rerun()
                    except RuntimeError as e:
                        st.error(str(e))

        else:
            status_label = {"approved": "✅ Approved", "edited": "✏️ Approved (edited)", "rejected": "❌ Rejected"}
            st.markdown(f"**Status: {status_label.get(existing.status.value, existing.status.value)}**")
            if existing.status == ReviewStatus.REJECTED:
                st.write(existing.reviewer_notes or "_No notes given._")
            else:
                st.write(existing.final_narrative)
                if existing.reviewer_notes:
                    st.caption(f"Reviewer notes: {existing.reviewer_notes}")
            if st.button("Re-open for review", key=f"reopen_{company_id}"):
                reopened = existing.model_copy(
                    update={"status": ReviewStatus.PENDING, "final_narrative": None}
                )
                save_review(reopened)
                st.rerun()

st.divider()
st.header("Final report — approved narratives only")

approved_records = [r for r in list_reviews() if r.is_final]
if not approved_records:
    st.caption("Nothing approved yet. Generate and approve narratives above to build the report.")
else:
    for r in approved_records:
        st.subheader(r.company_name)
        st.write(r.final_narrative)
