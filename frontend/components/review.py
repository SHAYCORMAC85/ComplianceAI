"""
Human Officer Review Component
------------------------------
Enforces compliance governance:
Renders the review submission form where human officers approve or reject documents.
"""

import html
from typing import Any, Dict, Optional
import streamlit as st
from frontend.api.client import api_client, APIClientError
from frontend.utils.formatting import get_status_badge_html, format_timestamp


def render_review_panel(
    document_id: str,
    existing_decision: Optional[Dict[str, Any]] = None
):
    """
    Renders human decision interface or shows already recorded determination.
    """
    st.markdown("### ⚖️ Compliance Determination")

    session = st.session_state.get("officer_session")
    # If decision already recorded
    if existing_decision:
        dec = existing_decision.get("decision", "UNKNOWN")
        officer = existing_decision.get("officer_id", "Unknown")
        notes = existing_decision.get("notes")
        decided_at = format_timestamp(existing_decision.get("decided_at"))
        badge = get_status_badge_html(dec)

        with st.container(border=True):
            col_d1, col_d2 = st.columns([3, 1])
            with col_d1:
                st.markdown("#### ⚖️ Official Determination")
            with col_d2:
                st.markdown(badge, unsafe_allow_html=True)

            st.markdown(f"**Document ID:** `{html.escape(document_id)}`")
            st.markdown(f"**Reviewing Officer:** `{html.escape(officer)}`")
            st.markdown(f"**Timestamp:** `{html.escape(decided_at)}`")
            st.markdown("**Officer Notes & Findings Disposition:**")

            # Display notes strictly as plain text (never executable HTML)
            if notes and notes.strip():
                st.text_area(
                    "Officer Notes",
                    value=notes,
                    height=100,
                    disabled=True,
                    label_visibility="collapsed"
                )
            else:
                st.caption("No notes recorded by reviewing officer.")

        st.info("ℹ️ A formal review decision has already been submitted for this document.")
        return

    # No decision recorded yet -> Render submission form
    st.markdown("⚠️ **Action Required**: Only an authorized human compliance officer may approve or reject this document.")

    st.caption("Submitting records your signed-in identity and permanently closes this inspection for review.")
    with st.form("human_review_form"):
        decision = st.radio(
            "Compliance Determination *",
            options=["APPROVED", "REJECTED"],
            index=0,
            horizontal=True,
            help="Select APPROVED only if all regulatory risks have been cleared or mitigated."
        )

        notes = st.text_area(
            "Officer Review Notes & Rationale",
            placeholder="Document rationale, remediation requirements, or explanation of decision...",
            help="Record your reasoning for future review."
        ).strip()

        confirm_check = st.checkbox(
            "I certify that I have examined the AI-assisted findings and am submitting this official decision under supervisory authority.",
            value=False
        )

        submitted = st.form_submit_button("Submit Formal Decision", use_container_width=True)

        if submitted:
            if not confirm_check:
                st.error("❌ You must check the certification box to confirm your human review.")
                return

            try:
                with st.spinner("Submitting review decision to backend..."):
                    api_client.submit_review_decision(
                        document_id=document_id,
                        decision=decision,
                        notes=notes,
                        token=session["token"]
                    )
                st.success(f"✅ Decision **{decision}** recorded successfully!")
                st.rerun()
            except APIClientError as err:
                if err.status_code == 401:
                    st.session_state.pop("officer_session", None)
                    st.rerun()
                if err.status_code == 409:
                    st.rerun()
                st.error(err.message)
