"""
Review History & Audit Trail Page
---------------------------------
Provides document ID lookup for official review determinations and displays
persisted audit logs.
"""

import html
import streamlit as st
from frontend.api.client import api_client, APIClientError
from frontend.components.sidebar import render_sidebar
from frontend.config import APP_NAME
from frontend.utils.formatting import get_status_badge_html, format_timestamp

st.set_page_config(page_title=f"{APP_NAME} - Review History", page_icon="📜", layout="wide")
render_sidebar()

st.title("📜 Review History & Audit Trail")
st.caption("Inspect persisted human review decisions, timestamps, and compliance officer determinations.")

# Lookup by Document ID
st.markdown("### 🔎 Document Decision Lookup")
col1, col2 = st.columns([2, 1])

with col1:
    search_doc_id = st.text_input(
        "Enter Document ID to retrieve recorded determination",
        value=st.session_state.get("active_document_id", "") or "",
        placeholder="e.g. 968e665f-cfec-4079-b269-08b2f6453876"
    ).strip()

if search_doc_id:
    try:
        history = api_client.get_review_history(search_doc_id)
        if not history:
            st.info("This inspection has no recorded decision.")
        for decision in history:
            badge = get_status_badge_html(decision.get("decision", "UNKNOWN"))

            with st.container(border=True):
                col_h1, col_h2 = st.columns([3, 1])
                with col_h1:
                    st.markdown("#### ⚖️ Recorded Compliance Determination")
                with col_h2:
                    st.markdown(badge, unsafe_allow_html=True)

                st.markdown(f"**Document ID:** `{html.escape(search_doc_id)}`")
                st.markdown(f"**Reviewing Officer:** `{html.escape(str(decision.get('officer_id', 'Unknown')))}`")
                st.markdown(f"**Decision Timestamp:** `{html.escape(format_timestamp(decision.get('decided_at')))}`")
                st.markdown("**Officer Rationale & Notes:**")
                notes_val = decision.get("notes")
                if notes_val and notes_val.strip():
                    st.text_area(
                        "Officer Notes",
                        value=notes_val,
                        height=100,
                        disabled=True,
                        label_visibility="collapsed"
                    )
                else:
                    st.caption("No notes recorded by reviewing officer.")

    except APIClientError as err:
        st.error(f"Could not retrieve decision history. {err.message}")

st.divider()

# Batch Historical Overview (from tracked documents)
st.markdown("### 🗄️ Persisted Decisions Log")
st.caption("Final decisions are recorded with their officer and timestamp in the local SQLite inspection database.")

try:
    all_docs = api_client.list_documents()
    decided_docs = [d for d in all_docs if d.get("has_decision")]
except APIClientError as err:
    st.error(f"Could not load recorded decisions. {err.message}")
    st.stop()

if not decided_docs:
    st.info("No documents with completed review decisions are currently recorded.")
else:
    header = st.columns([2.5, 1.2, 1.2, 2, 1])
    header[0].markdown("**Document Name & ID**")
    header[1].markdown("**Format**")
    header[2].markdown("**Decision**")
    header[3].markdown("**Updated At**")
    header[4].markdown("**Action**")

    for d in decided_docs:
        d_id = str(d.get("document_id", ""))
        d_name = html.escape(str(d.get("filename", "Untitled")))
        d_format = str(d.get("file_type", "")).upper()
        d_decision = str(d.get("decision", "UNKNOWN"))
        d_updated = format_timestamp(d.get("updated_at"))

        cols = st.columns([2.5, 1.2, 1.2, 2, 1])
        cols[0].markdown(
            f"**{d_name}**<br><code style='font-size:0.8em; word-break:break-all;' title='{d_id}'>{d_id[:16]}...</code>",
            unsafe_allow_html=True
        )
        cols[1].text(d_format)
        cols[2].markdown(get_status_badge_html(d_decision), unsafe_allow_html=True)
        cols[3].caption(d_updated)
        with cols[4]:
            if st.button("Inspect", key=f"hist_btn_{d_id}"):
                st.session_state["active_document_id"] = d_id
                st.session_state["active_document_name"] = d.get("filename", "Untitled")
                st.switch_page("pages/3_Inspection_Findings.py")

