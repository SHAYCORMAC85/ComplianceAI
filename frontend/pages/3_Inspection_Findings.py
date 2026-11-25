"""
Inspection Findings Page
------------------------
Allows compliance officers to review verified violation findings and inspect
color-coded character offset highlights on the original extracted text.
"""

import importlib
import streamlit as st
import frontend.components.document_viewer
import frontend.components.findings
import frontend.utils.highlighting

# Force reload of components and highlighting utilities to prevent stale bytecode
importlib.reload(frontend.utils.highlighting)
importlib.reload(frontend.components.document_viewer)
importlib.reload(frontend.components.findings)

from frontend.api.client import api_client, APIClientError
from frontend.components.document_viewer import render_document_viewer
from frontend.components.findings import render_findings_list
from frontend.components.sidebar import render_sidebar
from frontend.config import APP_NAME

st.set_page_config(page_title=f"{APP_NAME} - Inspection Findings", page_icon="🔍", layout="wide")
render_sidebar()

st.title("🔍 Inspection Findings & Verification")
st.caption("Inspect strictly validated compliance findings and view highlighted passages on the source text.")

# Document Selection: Dropdown or Manual Input
try:
    doc_list = api_client.list_documents()
except APIClientError:
    doc_list = []

doc_options = {d["document_id"]: f"{d.get('filename', 'Untitled')} ({d['document_id'][:8]}...)" for d in doc_list}

selected_doc_id = st.session_state.get("active_document_id")

col1, col2 = st.columns([2, 1])
with col1:
    if doc_options:
        doc_ids = list(doc_options.keys())
        default_index = doc_ids.index(selected_doc_id) if selected_doc_id in doc_ids else 0
        chosen_id = st.selectbox(
            "Select Tracked Document",
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
        manual_id = st.text_input("Enter Document ID (UUID)", value=selected_doc_id or "").strip()
        if manual_id:
            selected_doc_id = manual_id
            st.session_state["active_document_id"] = manual_id

if not selected_doc_id:
    st.info("👈 Please select or enter a document ID to inspect compliance findings.")
    st.stop()

# Load Findings and Document Text from backend
findings = []
raw_text = ""
filename = st.session_state.get("active_document_name", "document")

try:
    with st.spinner("Fetching verified findings and document text..."):
        status = api_client.get_document_status(selected_doc_id)
        if status["status"] != "COMPLETED":
            st.info(f"Inspection is {status['status']}. Results are available after completion.")
            st.stop()
        if status.get("skipped"):
            st.warning(f"{status['skipped']} sections received no model assessment.")
        findings_resp = api_client.get_document_findings(selected_doc_id)
        findings = findings_resp.get("findings", [])

        text_resp = api_client.get_document_text(selected_doc_id)
        raw_text = text_resp.get("raw_text", "")
        filename = text_resp.get("filename", filename)

except APIClientError as err:
    st.error(f"❌ Could not retrieve findings: {err.message}")
    st.stop()

# Two-column layout: Findings Cards on Left, Document Viewer on Right
left_col, right_col = st.columns([1.1, 1.2])

with left_col:
    render_findings_list(findings)
    st.markdown("<div style='height: 16px;'></div>", unsafe_allow_html=True)
    if st.button("⚖️ Proceed to Human Officer Review", type="primary", use_container_width=True):
        st.switch_page("pages/4_Human_Review.py")

with right_col:
    render_document_viewer(raw_text=raw_text, findings=findings, filename=filename)

