from __future__ import annotations
import time
import logging
import os
import json
from datetime import datetime
from typing import Any, List, Dict, Optional, Union
from .schemas import (
    Claim, Citation, Finding, TraceEvent, Decision,
    EvidenceStatus, ConditionType, Impact, ReviewActionType,
    ValidationIssueType, PolicyFinding, EvidenceAssessment,
    EvidenceConflict, MissingEvidenceDetail, DecisionExplanation,
    ConfidenceBreakdown, ValidationIssue, ValidationResult,
    AuditEvent, ReviewAction
)
from .llm.provider import LLMFactory
from .prompts import case_analysis, policy_analysis, decision, validation

logger = logging.getLogger(__name__)

def _elapsed(name, started, status, summary):
    return TraceEvent(agent=name, status=status, duration_ms=int((time.perf_counter()-started)*1000), summary=summary)

class CaseAnalysisAgent:
    def __init__(self):
        self.llm = LLMFactory.get_provider()

    def run(self, claim: Claim):
        started = time.perf_counter()

        system_prompt, user_prompt = case_analysis.get_case_analysis_prompt(claim)

        # Use a dedicated Pydantic model for structured output if available
        # For this agent, we expect a dict with specific keys
        try:
            resp_text = self.llm.generate(system_prompt, user_prompt)
            if isinstance(resp_text, str):
                resp = json.loads(resp_text)
            else:
                resp = resp_text.model_dump()

            state = {
                "facts": resp.get("facts", ""),
                "conflicts": [EvidenceConflict(**c) for c in resp.get("conflicts", [])],
                "missing_evidence": [MissingEvidenceDetail(**m) for m in resp.get("missing_evidence", [])],
                "investigation_questions": resp.get("investigation_questions", []),
            }
            return state, _elapsed("CaseAnalysisAgent", started, "PASS", f"Generated {len(state['investigation_questions'])} investigation questions")
        except Exception as e:
            logger.error(f"CaseAnalysisAgent failed: {e}")
            return {"facts": "", "conflicts": [], "missing_evidence": [], "investigation_questions": []}, _elapsed("CaseAnalysisAgent", started, "FAIL", str(e))

class PolicyEvidenceAgent:
    def __init__(self, retriever):
        self.retriever = retriever

    def run(self, state: dict):
        started = time.perf_counter()
        questions = state.get("investigation_questions", [])
        all_evidence = []

        for q in questions:
            all_evidence.extend(self.retriever.search(q))

        unique_evidence = {}
        for e in all_evidence:
            cid = e['chunk_id']
            if cid not in unique_evidence or e['rerank_score'] > unique_evidence[cid]['rerank_score']:
                unique_evidence[cid] = e

        evidence = sorted(unique_evidence.values(), key=lambda x: x['rerank_score'], reverse=True)
        return evidence, _elapsed("PolicyEvidenceAgent", started, "PASS", f"Retrieved {len(evidence)} unique chunks")

class CoverageExclusionAgent:
    def __init__(self):
        self.llm = LLMFactory.get_provider()

    def run(self, state: dict, evidence: list[dict]):
        started = time.perf_counter()
        evidence_text = "\n---\n".join([f"Chunk {e['chunk_id']} (Page {e['page']}): {e['text']}" for e in evidence])

        system_prompt, user_prompt = policy_analysis.get_policy_analysis_prompt(state.get("facts", ""), evidence_text)

        try:
            resp_text = self.llm.generate(system_prompt, user_prompt)
            if isinstance(resp_text, str):
                resp = json.loads(resp_text)
            else:
                resp = resp_text.model_dump()

            evidence_objs = [Citation(**e) for e in evidence]
            matrix = []
            for m in resp.get("evidence_matrix", []):
                cits = [c for c in evidence_objs if c.chunk_id in m.get('citation_ids', [])]
                matrix.append(EvidenceAssessment(
                    dimension=m['dimension'],
                    claim_fact=m.get('claim_fact'),
                    policy_requirement=m['policy_requirement'],
                    evidence=cits,
                    status=m['status'],
                    conclusion=m['conclusion'],
                    citation=cits[0] if cits else None
                ))

            findings = [PolicyFinding(**f) for f in resp.get("findings", [])]
            return matrix, findings, _elapsed("CoverageExclusionAgent", started, "PASS", f"Generated {len(matrix)} assessments and {len(findings)} findings")
        except Exception as e:
            logger.error(f"CoverageExclusionAgent failed: {e}")
            return [], [], _elapsed("CoverageExclusionAgent", started, "FAIL", str(e))

def calculate_confidence(res_decision: str, matrix: list[EvidenceAssessment], validation_status: str, retrieved_count: int) -> ConfidenceBreakdown:
    """Deterministic confidence calculation based on observable signals."""
    # 1. Evidence Coverage: % of dimensions that are NOT 'MISSING' or 'CONFLICTING'
    total_dims = len(matrix) or 1
    supported_dims = sum(1 for m in matrix if m.status in ['SUPPORTED', 'PARTIALLY_SUPPORTED'])
    coverage = supported_dims / total_dims

    # 2. Citation Coverage: % of dimensions with at least one citation
    cited_dims = sum(1 for m in matrix if m.citation is not None)
    citation_cov = cited_dims / total_dims

    # 3. Retrieval Quality: Based on count of unique chunks retrieved
    ret_quality = min(1.0, retrieved_count / 10.0)

    # 4. Penalties
    missing_penalty = sum(1 for m in matrix if m.status == 'MISSING') * 0.05
    conflict_penalty = sum(1 for m in matrix if m.status == 'CONFLICTING') * 0.2

    # Final Score
    base_score = (coverage * 0.4) + (citation_cov * 0.3) + (ret_quality * 0.3)
    final_score = max(0.0, min(1.0, base_score - missing_penalty - conflict_penalty))

    return ConfidenceBreakdown(
        score=round(final_score, 2),
        evidence_coverage=round(coverage, 2),
        citation_coverage=round(citation_cov, 2),
        retrieval_quality=round(ret_quality, 2),
        missing_evidence_penalty=round(missing_penalty, 2),
        conflict_penalty=round(conflict_penalty, 2),
        validation_status=validation_status
    )

class DecisionAgent:
    def __init__(self):
        self.llm = LLMFactory.get_provider()

    def run(self, state: dict, matrix: list[EvidenceAssessment], findings: list[PolicyFinding], evidence: list[dict]):
        started = time.perf_counter()
        matrix_text = "\n".join([f"{m.dimension}: {m.status} - {m.conclusion}" for m in matrix])
        findings_text = "\n".join([f"{f.condition_type}: {f.finding} ({f.impact})" for f in findings])

        system_prompt, user_prompt = decision.get_decision_prompt(matrix_text, findings_text, state.get("missing_evidence", []))

        try:
            resp_text = self.llm.generate(system_prompt, user_prompt)
            if isinstance(resp_text, str):
                resp = json.loads(resp_text)
            else:
                resp = resp_text.model_dump()

            proposed_decision = resp.get("decision", "NEEDS_REVIEW")

            # --- DETERMINISTIC DECISION GUARD ---
            # Override LLM if evidence is clearly missing or conflicting for material dimensions
            final_decision = proposed_decision
            if any(m.status == 'MISSING' or m.status == 'CONFLICTING' for m in matrix):
                final_decision = "NEEDS_REVIEW"

            # Ensure BLOCKING exclusions trigger NOT_ADMISSIBLE
            if any(f.impact == 'BLOCKING' and f.status == 'SUPPORTED' for f in findings):
                final_decision = "NOT_ADMISSIBLE"

            # Confidence is calculated deterministically, not via LLM
            # (We'll call this from the service layer or here if we have retrieval count)
            # For now, we'll use a dummy retrieval count or pass it in.
            conf_obj = ConfidenceBreakdown(score=0.0, validation_status="PENDING") # Updated in service.py

            result = {
                "decision": final_decision,
                "confidence": conf_obj,
                "explanation": DecisionExplanation(**resp.get("explanation", {
                    "decision": final_decision,
                    "reason": "Unable to determine decision",
                    "next_action": "Manual review required"
                })),
                "applicable_limits": resp.get("applicable_limits", []),
                "key_findings": resp.get("key_findings", []),
                "next_action": resp.get("explanation", {}).get("next_action", "Review claim manually"),
            }
            return result, _elapsed("DecisionAgent", started, "PASS", f"Proposed decision: {result['decision']}")
        except Exception as e:
            logger.error(f"DecisionAgent failed: {e}")
            return {"decision": "NEEDS_REVIEW", "confidence": ConfidenceBreakdown(score=0.0, validation_status="FAIL"), "explanation": DecisionExplanation(decision="NEEDS_REVIEW", reason=str(e), next_action="Check LLM"), "applicable_limits": [], "key_findings": [], "next_action": "Manual review"}, _elapsed("DecisionAgent", started, "FAIL", str(e))

class ValidationAgent:
    def __init__(self):
        self.llm = LLMFactory.get_provider()

    def run(self, result: dict, matrix: list[EvidenceAssessment], findings: list[PolicyFinding], evidence: list[dict]):
        started = time.perf_counter()
        evidence_text = "\n---\n".join([f"Chunk {e['chunk_id']} (Page {e['page']}): {e['text']}" for e in evidence])

        system_prompt, user_prompt = validation.get_validation_prompt(
            result['explanation'].reason,
            "\n".join([f"{m.dimension}: {m.status}" for m in matrix]),
            evidence_text
        )

        try:
            resp_text = self.llm.generate(system_prompt, user_prompt)
            if isinstance(resp_text, str):
                resp = json.loads(resp_text)
            else:
                resp = resp_text.model_dump()

            issues = [ValidationIssue(**i) for i in resp.get("issues", [])]
            passed = resp.get("status") == "PASS"

            # Basic deterministic fallback: check for empty evidence when not NEEDS_REVIEW
            if result['decision'] != 'NEEDS_REVIEW' and not evidence:
                passed = False
                issues.append(ValidationIssue(type="UNSUPPORTED_POLICY_CLAIM", finding="Decision not supported", reason="No evidence retrieved"))

            # ADDITIONAL SAFETY: If decision is NEEDS_REVIEW, it's effectively a 'PASS' for validation
            # because the system has correctly abstained.
            if result['decision'] == 'NEEDS_REVIEW':
                passed = True

            return ValidationResult(status="PASS" if passed else "FAIL", issues=issues), _elapsed("ValidationAgent", started, "PASS" if passed else "FAIL", f"Found {len(issues)} validation issues")
        except Exception as e:
            logger.error(f"ValidationAgent failed: {e}")
            return ValidationResult(status="FAIL", issues=[ValidationIssue(type="UNSUPPORTED_POLICY_CLAIM", finding="System Error", reason=str(e))]), _elapsed("ValidationAgent", started, "FAIL", str(e))
