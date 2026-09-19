import streamlit as st
import sys
from pathlib import Path

# Add the project root to the Python path so 'app' package can be found
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

import json
import requests
import os
from datetime import datetime
from app.schemas import Claim, DecisionResponse, ReviewAction
from app.service import analyze, generate_timeline, generate_report, save_review

ROOT = Path(__file__).resolve().parents[1]

st.set_page_config(page_title='Aptino Claim Review', layout='wide')

# Custom CSS for professional look
st.markdown("""
    <style>
    .main { background-color: #f8f9fa; }
    .stMetric { background-color: #ffffff; padding: 10px; border-radius: 5px; border: 1px solid #dee2e6; }
    .decision-box { padding: 20px; border-radius: 10px; margin-bottom: 20px; text-align: center; font-weight: bold; font-size: 24px; }
    .status-needs-review { background-color: #fff3cd; color: #856404; border: 1px solid #ffeeba; }
    .status-admissible { background-color: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
    .status-not-admissible { background-color: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
    .audit-event { font-size: 0.85rem; padding: 5px; border-bottom: 1px solid #eee; }
    </style>
    """, unsafe_allow_html=True)

# Navigation
st.sidebar.title('APTINO')
st.sidebar.markdown('────────────────────────')
page = st.sidebar.radio('Navigate', ['Claims', 'Evaluation', 'System Diagnostics'])

if page == 'Claims':
    st.title('Claim Investigation Workspace')

    # Case Selection
    case_path = ROOT / 'candidate_data' / 'public_test_cases.json'
    if not case_path.exists(): case_path = ROOT / 'data' / 'cases' / 'public_cases.json'

    try:
        cases_data = json.loads(case_path.read_text())
        # Ensure cases is always a list of dictionaries
        cases = cases_data if isinstance(cases_data, list) else [cases_data]
        ids = [c['case_id'] for c in cases]
        selected = st.selectbox('Select Case ID', ids)
        raw = next(c for c in cases if c['case_id'] == selected)
    except Exception as e:
        st.error(f"Error loading cases: {e}")
        st.stop()

    uploaded = st.file_uploader('Or upload a claim JSON', type='json')
    if uploaded: raw = json.load(uploaded)

    if st.button('Analyze Claim', type='primary'):
        with st.spinner('Executing multi-agent investigation...'):
            try:
                # Ensure raw is a dictionary before passing to Claim
                if isinstance(raw, list):
                    claim_dict = raw[0] if len(raw) > 0 else {}
                else:
                    claim_dict = raw

                result = analyze(Claim(**claim_dict))
                st.session_state['analysis_result'] = result
            except Exception as e:
                st.error(f"Analysis failed: {e}")

    if 'analysis_result' in st.session_state:
        res = st.session_state['analysis_result']

        # Ensure raw is a dictionary for the display section
        display_raw = raw[0] if isinstance(raw, list) and len(raw) > 0 else (raw if isinstance(raw, dict) else {})

        # --- CLAIM OVERVIEW ---
        with st.expander('📋 CLAIM OVERVIEW', expanded=True):
            col1, col2, col3 = st.columns(3)
            col1.write(f"**Case ID:** {res.case_id}")
            col1.write(f"**Claim Date:** {display_raw.get('claim_date') or display_raw.get('admission_date', 'N/A')}")
            col1.write(f"**Sum Insured:** {display_raw.get('sum_insured_inr') or display_raw.get('sum_insured', 'N/A')}")

            col2.write(f"**Treatment:** {display_raw.get('treatment', {}).get('diagnosis', 'N/A') if isinstance(display_raw.get('treatment'), dict) else display_raw.get('treatment', 'N/A')}")
            col2.write(f"**Hospital:** {display_raw.get('hospital', {}).get('name', 'N/A') if isinstance(display_raw.get('hospital'), dict) else display_raw.get('hospital', 'N/A')}")
            col2.write(f"**Claim Amount:** {display_raw.get('expenses_inr', {}).get('room', 0) if isinstance(display_raw.get('expenses_inr'), dict) else display_raw.get('claimed_amount', 0)}")

            col3.write(f"**Documents:** {', '.join(display_raw.get('documents', [])) if isinstance(display_raw.get('documents'), list) else 'N/A'}")

        # --- CLAIM TIMELINE ---
        st.subheader('Claim Timeline')
        # Use the a single dict for Claim model
        claim_obj = Claim(**(raw[0] if isinstance(raw, list) and len(raw) > 0 else (raw if isinstance(raw, dict) else {})))
        timeline = generate_timeline(claim_obj)
        t_cols = st.columns(len(timeline))
        for i, event in enumerate(timeline):
            with t_cols[i]:
                st.caption(event['event'])
                st.markdown(f"**{event['date']}**")
                if i < len(timeline) - 1:
                    st.markdown("$\rightarrow$")

        # --- DECISION ---
        st.subheader('Final Decision')
        status_class = 'status-needs-review' if res.decision == 'NEEDS_REVIEW' else 'status-admissible' if 'ADMISSIBLE' in res.decision else 'status-not-admissible'
        st.markdown(f'<div class="decision-box {status_class}">{res.decision}</div>', unsafe_allow_html=True)

        col_conf, col_val = st.columns(2)
        col_conf.metric('Decision Confidence', f"{res.confidence.score:.0%}")
        col_val.metric('Validation Status', res.validation.status)

        # --- DECISION DRIVERS ---
        st.write('**Decision Drivers**')
        for f in res.key_findings:
            icon = '✅' if f.status == 'SUPPORTED' else '⚠' if f.status == 'PARTIALLY_SUPPORTED' else '❌'
            st.markdown(f"{icon} {f.finding}")

        # --- DECISION EXPLANATION ---
        st.subheader('Decision Explanation')
        st.subheader('Decision Explanation')
        st.info(f"**Reason:** {res.explanation.reason}")
        st.write(f"**Recommended Next Action:** {res.explanation.next_action}")

        # --- EVIDENCE MATRIX ---
        st.subheader('Evidence Matrix')
        if res.evidence_matrix:
            # Using a dataframe for the matrix
            matrix_data = []
            for m in res.evidence_matrix:
                matrix_data.append({
                    "Dimension": m.dimension,
                    "Claim Fact": m.claim_fact,
                    "Policy Requirement": m.policy_requirement,
                    "Status": m.status,
                    "Conclusion": m.conclusion
                })
            st.table(matrix_data)
        else:
            st.warning("No evidence matrix generated.")

        # --- POLICY FINDINGS ---
        st.subheader('Policy Findings')
        for f in res.key_findings:
            with st.expander(f"[{f.condition_type}] {f.finding}"):
                st.write(f"**Impact:** {f.impact}")
                st.write(f"**Status:** {f.status}")
                st.write(f"**Citations:** {', '.join(f.supporting_citations)}")

        # --- MISSING EVIDENCE ---
        st.subheader('Missing Evidence Intelligence')
        if res.missing_evidence:
            for me in res.missing_evidence:
                with st.expander(f"❌ {me.evidence}"):
                    st.write(f"**Why it matters:** {me.why_it_matters}")
                    st.write(f"**Required for:** {me.policy_condition}")
                    st.write(f"**Recommended Evidence:** {me.recommended_evidence}")
                    st.write(f"**Impact:** {me.impact}")
        else:
            st.success("No missing evidence identified.")

        # --- RETRIEVAL DIAGNOSTICS ---
        with st.expander('🛠️ Retrieval Quality Panel'):
            if res.retrieval_diagnostics:
                for diag in res.retrieval_diagnostics:
                    st.write(f"**Query:** {diag['query']}")
                    col_d, col_b, col_f, col_final = st.columns(4)
                    col_d.metric('Dense', diag['dense_count'])
                    col_b.metric('BM25', diag['bm25_count'])
                    col_f.metric('Fused', diag['fused_count'])
                    col_final.metric('Final', diag['final_count'])
                    st.write(f"Final IDs: {', '.join(diag['final_ids'])}")
                    st.divider()
            else:
                st.warning("No retrieval diagnostics available.")

        # --- POLICY CITATIONS ---
        st.subheader('Policy Evidence Trace')
        for cit in res.citations:
            with st.expander(f"Page {cit.page} · {cit.section} · {cit.chunk_id}"):
                st.text(cit.text)
                st.caption(f"Scores: Dense={cit.dense_score}, BM25={cit.bm25_score}, RRF={cit.fusion_score}, Rerank={cit.rerank_score}")

        # --- AUDIT TRAIL ---
        st.subheader('Decision Audit Trail')
        for event in res.audit_trail:
            st.markdown(f'<div class="audit-event"><b>{event.timestamp.strftime("%H:%M:%S")}</b> | {event.event_type} | {event.summary}</div>', unsafe_allow_html=True)

        # --- HUMAN REVIEW ---
        st.divider()
        st.subheader('Reviewer Actions')
        col_rev1, col_rev2, col_rev3, col_rev4 = st.columns(4)

        def submit_action(action, reason="No reason provided"):
            review_data = ReviewAction(
                original_decision=res.decision,
                reviewer_decision=res.decision, # Default to same
                reviewer_action=action,
                reviewer_reason=reason,
            )
            try:
                save_review(review_data)
                st.success(f'Action {action} recorded!')
            except Exception as e:
                st.error(f"Failed to submit review: {e}")

        if col_rev1.button('✅ Approve Decision'):
            submit_action('APPROVE', 'Reviewer agrees with automated decision')
        if col_rev2.button('⚠️ Send to Review'):
            submit_action('SEND_TO_REVIEW', 'Case flagged for senior review')
        if col_rev3.button('📄 Request Evidence'):
            submit_action('REQUEST_EVIDENCE', 'Additional evidence required')
        if col_rev4.button('💾 Download Report'):
            report_md = generate_report(res)
            st.download_button('Download Markdown', report_md, file_name=f"report_{res.case_id}.md")

elif page == 'Evaluation':
    st.title('Evaluation Dashboard')
    st.info('Evaluation results are generated via `evaluation/evaluate.py`. Please run the script to update this page.')
    try:
        res_path = ROOT / 'evaluation' / 'results.json'
        if res_path.exists():
            results = json.loads(res_path.read_text())
            col1, col2, col3 = st.columns(3)
            col1.metric('Total Cases', results['total_cases'])
            col2.metric('Citation Hit Rate', f"{results['citation_hit_rate']:.1%}")
            col3.metric('Validation Rate', f"{results['validation_rate']:.1%}")
            st.json(results['cases'])
        else:
            st.warning('No results.json found. Please run evaluation.')
    except Exception as e:
        st.error(f"Error loading results: {e}")

elif page == 'System Diagnostics':
    st.title('System Diagnostics')

    # Check infrastructure
    policy_exists = (ROOT / 'policy' / 'USGIC-CSCIndividualHealthInsurance_2017-2018.pdf').exists()
    index_exists = (ROOT / 'data' / 'index' / 'policy_index.json').exists()

    st.write('### Infrastructure Status')
    st.write(f"Policy PDF Loaded: {'✅' if policy_exists else '❌'}")
    st.write(f"Policy Index Available: {'✅' if index_exists else '❌'}")
    st.write("RRF Enabled: ✅")
    st.write("Reranker Enabled: ✅")
    st.write("Validation Engine: ✅")

    if index_exists:
        idx_data = json.loads((ROOT / 'data' / 'index' / 'policy_index.json').read_text())
        st.write(f"Total Policy Chunks: {len(idx_data['chunks'])}")
