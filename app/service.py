from __future__ import annotations
import os
import json
import time
from functools import lru_cache
from pathlib import Path
from datetime import datetime
from .schemas import Claim, Citation, DecisionResponse, AuditEvent, ReviewAction, TraceEvent
from .retrieval import HybridRetriever, load_policy, tokens
from .agents import CaseAnalysisAgent, PolicyEvidenceAgent, CoverageExclusionAgent, DecisionAgent, ValidationAgent, calculate_confidence

ROOT = Path(__file__).resolve().parents[1]
REVIEWS_FILE = ROOT / 'data' / 'reviews.json'

def policy_path() -> Path:
    supplied = ROOT / 'policy' / 'USGIC-CSCIndividualHealthInsurance_2017-2018.pdf'
    return Path(os.getenv('POLICY_PATH', str(supplied if supplied.exists() else ROOT / 'data' / 'policy' / 'demo_policy.json')))

@lru_cache
def engine():
    return HybridRetriever(load_policy(policy_path()), int(os.getenv('RRF_K', '60')))

def known_case(case_id: str) -> Claim | None:
    locations = [ROOT / 'candidate_data' / 'public_test_cases.json', ROOT / 'data' / 'cases' / 'public_cases.json']
    for path in locations:
        if path.exists():
            records = json.loads(path.read_text(encoding='utf8'))
            for record in records:
                if record.get('case_id') == case_id: return Claim(**record)
    return None

def save_review(review: ReviewAction):
    reviews = []
    if REVIEWS_FILE.exists():
        reviews = json.loads(REVIEWS_FILE.read_text())
    reviews.append(review.model_dump(mode='json'))
    REVIEWS_FILE.write_text(json.dumps(reviews, indent=2))

def get_reviews(case_id: str) -> list[ReviewAction]:
    if not REVIEWS_FILE.exists(): return []
    reviews = json.loads(REVIEWS_FILE.read_text())
    return [ReviewAction(**r) for r in reviews if r.get('case_id') == case_id]

def generate_timeline(claim: Claim) -> list[dict]:
    timeline = []
    if claim.policy_start:
        timeline.append({'event': 'Policy Start', 'date': claim.policy_start})
    if claim.continuity_months:
        timeline.append({'event': 'Coverage Continuity', 'date': f'{claim.continuity_months} months'})
    if claim.admission_date:
        timeline.append({'event': 'Hospital Admission', 'date': claim.admission_date})
    if claim.treatment:
        timeline.append({'event': 'Treatment', 'date': 'During admission'})
    if claim.admission_date: # Using admission date as a proxy for claim date if not separate
        timeline.append({'event': 'Claim Date', 'date': claim.admission_date})
    timeline.append({'event': 'Investigation', 'date': 'Current'})
    timeline.append({'event': 'Decision', 'date': 'Pending'})
    return timeline

def generate_report(res: DecisionResponse) -> str:
    report = [
        "# APTINO CLAIM INVESTIGATION REPORT",
        f"**Case ID:** {res.case_id}",
        f"**Decision:** {res.decision}",
        f"**Confidence:** {res.confidence.score:.0%}",
        "",
        "## Investigation Questions",
        *[f"- {q}" for q in res.execution_trace[0].summary.split(',') if q], # Simplified
        "",
        "## Evidence Matrix",
        "| Dimension | Status | Conclusion |",
        "| --- | --- | --- |",
        *[f"| {m.dimension} | {m.status} | {m.conclusion} |" for m in res.evidence_matrix],
        "",
        "## Policy Findings",
        *[f"- **{f.condition_type}**: {f.finding} (Impact: {f.impact})" for f in res.key_findings],
        "",
        "## Missing Evidence",
        *[f"- {me.evidence}: {me.why_it_matters}" for me in res.missing_evidence],
        "",
        "## Policy Citations",
        *[f"- Page {c.page} ({c.section}): {c.text}" for c in res.citations],
        "",
        "## Validation",
        f"Status: {res.validation.status}",
        *[f"- {issue.type}: {issue.reason}" for issue in res.validation.issues],
        "",
        "## Audit Trail",
        *[f"- {event.timestamp.strftime('%Y-%m-%d %H:%M:%S')} | {event.event_type} | {event.summary}" for event in res.audit_trail]
    ]
    return "\n".join(report)

def analyze(claim: Claim) -> DecisionResponse:
    traces = []
    audit_trail = []
    retrieval_diagnostics = []

    def log_event(event_type, summary, metadata=None):
        event = AuditEvent(event_type=event_type, actor='System', summary=summary, metadata=metadata or {})
        audit_trail.append(event)

    log_event('CLAIM_RECEIVED', f'Started analysis for case {claim.case_id}', {'case_id': claim.case_id})

    state, tr = CaseAnalysisAgent().run(claim)
    traces.append(tr)
    log_event('INVESTIGATION_CREATED', f'Generated {len(state["investigation_questions"])} questions')

    questions = state.get("investigation_questions", [])
    all_evidence = []

    for q in questions:
        retriever = engine()
        bm = retriever.bm25(q)
        de = retriever.dense(q)
        br = sorted(range(len(retriever.chunks)), key=lambda i: bm[i], reverse=True)[:10]
        dr = sorted(range(len(retriever.chunks)), key=lambda i: de[i], reverse=True)[:10]
        fused = {}
        for ranking in (br, dr):
            for rank, i in enumerate(ranking, 1):
                fused[i] = fused.get(i, 0) + 1 / (retriever.rrf_k + rank)
        qset = set(tokens(q))
        candidates = []
        for i, f in fused.items():
            overlap = len(qset & set(retriever.docs[i])) / max(1, len(qset))
            rerank = .70 * f * 100 + .30 * overlap
            candidates.append((rerank, i, f))
        final_ids = [i for r, i, f in sorted(candidates, reverse=True)[:5]]
        retrieval_diagnostics.append({
            "query": q, "dense_count": len(dr), "bm25_count": len(br),
            "fused_count": len(fused), "final_count": len(final_ids), "final_ids": final_ids
        })
        all_evidence.extend(retriever.search(q))

    unique_evidence = {}
    for e in all_evidence:
        cid = e['chunk_id']
        if cid not in unique_evidence or e['rerank_score'] > unique_evidence[cid]['rerank_score']:
            unique_evidence[cid] = e
    evidence = sorted(unique_evidence.values(), key=lambda x: x['rerank_score'], reverse=True)

    traces.append(TraceEvent(agent="PolicyEvidenceAgent", status="PASS", duration_ms=0, summary=f"Retrieved {len(evidence)} unique chunks"))
    log_event('POLICY_RETRIEVED', f'Retrieved {len(evidence)} policy chunks')

    matrix, findings, tr = CoverageExclusionAgent().run(state, evidence)
    traces.append(tr)
    log_event('EVIDENCE_ASSESSED', f'Analyzed {len(matrix)} decision dimensions')

    result, tr = DecisionAgent().run(state, matrix, findings, evidence)
    traces.append(tr)
    log_event('DECISION_PROPOSED', f'Proposed decision: {result["decision"]}')

    validation, tr = ValidationAgent().run(result, matrix, findings, evidence)
    traces.append(tr)
    log_event('VALIDATION_COMPLETED', f'Validation status: {validation.status}')

    # Final Deterministic Confidence Calculation
    result['confidence'] = calculate_confidence(
        res_decision=result['decision'],
        matrix=matrix,
        validation_status=validation.status,
        retrieved_count=len(evidence)
    )

    citations = [Citation(**e) for e in evidence]

    return DecisionResponse(
        case_id=claim.case_id,
        citations=citations,
        validation=validation,
        execution_trace=traces,
        evidence_matrix=matrix,
        conflicts=state.get('conflicts', []),
        audit_trail=audit_trail,
        retrieval_diagnostics=retrieval_diagnostics,
        **result
    )
