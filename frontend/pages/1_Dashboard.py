"""
Dashboard Page
--------------
Executive overview of document compliance statuses, verified findings,
and pending human officer review queues.
"""

import streamlit as st
from frontend.api.client import api_client, APIClientError
from frontend.components.metrics import render_dashboard_metrics
from frontend.components.sidebar import render_sidebar
from frontend.config import APP_NAME
from frontend.utils.formatting import get_status_badge_html, format_timestamp

st.set_page_config(page_title=f"{APP_NAME} - Dashboard", page_icon="📊", layout="wide")
render_sidebar()

st.title("📊 Compliance Overview Dashboard")
st.caption("Real-time summary of financial document inspections, verified regulatory flags, and officer decisions.")

# Fetch real documents from backend
try:
    documents = api_client.list_documents()
except APIClientError as err:
    st.error(f"⚠️ Could not retrieve document statistics: {err.message}")
    documents = []

# Render KPI metric cards
render_dashboard_metrics(documents)

st.divider()

st.markdown("### 📑 Tracked Documents Queue")
if not documents:
    st.info("No documents are currently tracked in the system. Use the **Upload Document** page to submit documents for inspection.")
else:
    # Table header
    header_cols = st.columns([2.5, 1, 1, 1, 1.2, 1.5, 1.2])
    header_cols[0].markdown("**Document Name / ID**")
    header_cols[1].markdown("**Format**")
    header_cols[2].markdown("**Status**")
    header_cols[3].markdown("**Flags**")
    header_cols[4].markdown("**Decision**")
    header_cols[5].markdown("**Updated**")
    header_cols[6].markdown("**Actions**")

    for doc in documents:
        doc_id = doc.get("document_id", "")
        name = doc.get("filename", "Untitled")
        ftype = doc.get("file_type", "").upper()
        status_str = doc.get("status", "UNKNOWN")
        findings_count = doc.get("findings_count", 0)
        decision_val = doc.get("decision") or "PENDING"
        updated = format_timestamp(doc.get("updated_at"))

        cols = st.columns([2.5, 1, 1, 1, 1.2, 1.5, 1.2])
        cols[0].markdown(f"**{name}**<br><code style='font-size:0.75em;'>{doc_id[:12]}...</code>", unsafe_allow_html=True)
        cols[1].text(ftype)
        cols[2].markdown(get_status_badge_html(status_str), unsafe_allow_html=True)
        cols[3].markdown(f"**{findings_count}** flags")
        cols[4].markdown(get_status_badge_html(decision_val), unsafe_allow_html=True)
        cols[5].caption(updated)

        with cols[6]:
            if st.button("Inspect", key=f"btn_inspect_{doc_id}", use_container_width=True):
                st.session_state["active_document_id"] = doc_id
                st.session_state["active_document_name"] = name
                st.switch_page("pages/3_Inspection_Findings.py")

