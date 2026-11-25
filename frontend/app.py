"""
ComplianceAI - Main Streamlit Application Entrypoint
----------------------------------------------------
AI-Powered Financial Document Inspection Platform with Strict Human-in-the-Loop Governance.
"""

import streamlit as st
from frontend.components.sidebar import render_sidebar
from frontend.config import APP_NAME, APP_SUBTITLE, APP_ICON

st.set_page_config(
    page_title=f"{APP_NAME} - Home",
    page_icon=APP_ICON,
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize Session State Variables
if "active_document_id" not in st.session_state:
    st.session_state["active_document_id"] = None
if "active_document_name" not in st.session_state:
    st.session_state["active_document_name"] = None

render_sidebar()

st.title(f"{APP_ICON} {APP_NAME}")
st.subheader(APP_SUBTITLE)

st.markdown(
    """
    **ComplianceAI** empowers financial compliance teams to automatically scan, analyze,
    and verify high-risk text across prospectuses, customer agreements, and marketing materials.
    
    ### Key Platform Capabilities
    - 📄 **Multi-Format Extraction**: Native text extraction for **TXT**, **PDF**, and **DOCX** files.
    - 🔍 **Rules Engine**: Automated matching against active financial rules (FINRA 2111, 2210, SEC 10b-5, CFPB UDAAP, BSA/AML, SOX 404).
    - 🛡️ **Three-Stage Verbatim Validation**: Checks that each highlighted quotation occurs exactly in its source section.
    - 📍 **Character Offset Highlighting**: Precise character start & end coordinates to highlight flagged clauses.
    - ⚖️ **Human-in-the-Loop Governance**: AI never approves or rejects documents. Supervisory authority is strictly reserved for human compliance officers.
    """
)

st.divider()

st.markdown("### 🧭 Quick Navigation")
col1, col2, col3, col4, col5 = st.columns(5)

with col1:
    if st.button("📊 Dashboard", use_container_width=True):
        st.switch_page("pages/1_Dashboard.py")
    st.caption("View queue metrics and document statuses.")

with col2:
    if st.button("📤 Upload Doc", use_container_width=True):
        st.switch_page("pages/2_Upload_Document.py")
    st.caption("Upload TXT, PDF, or DOCX files.")

with col3:
    if st.button("🔍 Findings", use_container_width=True):
        st.switch_page("pages/3_Inspection_Findings.py")
    st.caption("View verified flags & highlighted text.")

with col4:
    if st.button("⚖️ Human Review", use_container_width=True):
        st.switch_page("pages/4_Human_Review.py")
    st.caption("Record a final decision using your signed-in session.")

with col5:
    if st.button("📜 Audit History", use_container_width=True):
        st.switch_page("pages/5_Review_History.py")
    st.caption("Search past review determinations.")
