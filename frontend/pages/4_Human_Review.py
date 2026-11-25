"""
Human Officer Review Page
-------------------------
Enforces Human-in-the-Loop compliance governance:
Only an authorized human compliance officer can approve or reject inspected documents.
AI models never make, submit, or override review decisions.
"""

import html
import importlib
import streamlit as st
import frontend.components.review

importlib.reload(frontend.components.review)

from frontend.api.client import api_client, APIClientError
from frontend.components.review import render_review_panel
from frontend.components.sidebar import render_sidebar
from frontend.config import APP_NAME
from frontend.utils.formatting import get_severity_badge_html

st.set_page_config(page_title=f"{APP_NAME} - Human Review", page_icon="⚖️", layout="wide")
render_sidebar()

st.title("⚖️ Human Compliance Officer Review")
st.caption("Perform supervisory sign-off. Review verified flags and submit formal document approval or rejection.")

# Select Document
try:
    doc_list = api_client.list_documents()
except APIClientError:
    doc_list = []

doc_options = {d["document_id"]: f"{d.get('filename', 'Untitled')} ({d['document_id'][:8]}...)" for d in doc_list}
selected_doc_id = st.session_state.get("active_document_id")

if doc_options:
    doc_ids = list(doc_options.keys())
    default_index = doc_ids.index(selected_doc_id) if selected_doc_id in doc_ids else 0
    chosen_id = st.selectbox(
        "Select Document to Review",
        options=doc_ids,
        format_func=lambda x: doc_options[x],
        index=default_index
    )
    if chosen_id != selected_doc_id:
        st.session_state["active_document_id"] = chosen_id
        st.session_state["active_document_name"] = doc_options[chosen_id].split(" (")[0]
        selected_doc_id = chosen_id
        st.rerun()
else:
    selected_doc_id = st.text_input("Enter Document ID (UUID)", value=selected_doc_id or "").strip()

if not selected_doc_id:
    st.info("👈 Please select a document to conduct review.")
    st.stop()

try:
    inspection = api_client.get_document_status(selected_doc_id)
except APIClientError as err:
    st.error(err.message)
    st.stop()
if inspection["status"] != "COMPLETED":
    st.info(f"Inspection status is {inspection['status']}. Review opens after completion.")
    st.stop()

if inspection.get("skipped"):
    st.warning(f"{inspection['skipped']} sections received no model assessment. Review them manually.")

# Fetch Existing Decision and Findings
existing_decision = None
try:
    existing_decision = api_client.get_review_decision(selected_doc_id)
except APIClientError as err:
    if err.status_code != 404:
        st.error(err.message)
        st.stop()

findings = []
try:
    findings_resp = api_client.get_document_findings(selected_doc_id)
    findings = findings_resp.get("findings", [])
except APIClientError as err:
    st.error(err.message)
    st.stop()

col1, col2 = st.columns([1.2, 1])

with col1:
    st.markdown("### 🔍 Summary of Flags Requiring Review")
    if not findings:
        st.info("No validated findings. Review the source before recording a decision.")
    else:
        st.warning(f"⚠️ **{len(findings)} potential compliance violations flagged by AI inspection.**")
        for idx, f in enumerate(findings, start=1):
            badge = get_severity_badge_html(f.get("severity", "MEDIUM"))
            with st.expander(f"Flag #{idx}: {f.get('rule_id')} - {f.get('passage')[:45]}...", expanded=(idx == 1)):
                st.markdown(f"**Severity:** {badge}", unsafe_allow_html=True)
                st.markdown(f"**Passage:** *\"{html.escape(f.get('passage', ''))}\"*")
                st.text(f"Reason: {f.get('reason', '')}")

with col2:
    render_review_panel(
        document_id=selected_doc_id,
        existing_decision=existing_decision
    )

