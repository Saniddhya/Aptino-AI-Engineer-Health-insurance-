from __future__ import annotations
from typing import Literal, List, Optional, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict, AliasChoices

Decision = Literal['ADMISSIBLE','ADMISSIBLE_WITH_LIMITS','PARTIALLY_ADMISSIBLE','NOT_ADMISSIBLE','NEEDS_REVIEW']
EvidenceStatus = Literal['SUPPORTED','PARTIALLY_SUPPORTED','MISSING','CONFLICTING','NOT_APPLICABLE']
ConditionType = Literal['DEFINITION','ELIGIBILITY','WAITING_PERIOD','EXCLUSION','LIMIT','SUB_LIMIT','CONDITION','PORTABILITY','DOCUMENT_REQUIREMENT','HOSPITAL_REQUIREMENT','MEDICAL_NECESSITY','OTHER']
Impact = Literal['BLOCKING','LIMITING','INFORMATIONAL']
ReviewActionType = Literal['APPROVE','SEND_TO_REVIEW','REQUEST_EVIDENCE','OVERRIDE']
ValidationIssueType = Literal['UNSUPPORTED_FACT','UNSUPPORTED_POLICY_CLAIM','MISSING_CITATION','INVALID_CITATION','CONFLICTING_EVIDENCE']

class Claim(BaseModel):
    model_config = ConfigDict(extra='allow')
    case_id: str
    policy_start: str | None = Field(default=None, validation_alias=AliasChoices('policy_start','policy_start_date'))
    admission_date: str | None = Field(default=None, validation_alias=AliasChoices('admission_date','claim_date'))
    treatment: object | None = None
    diagnosis: str | None = None
    claimed_amount: float | None = Field(default=None, ge=0)
    sum_insured: float | None = Field(default=None, ge=0, validation_alias=AliasChoices('sum_insured','sum_insured_inr'))
    documents: list[Any] = []
    hospital: object | None = None
    continuity_months: int | None = Field(default=None, ge=0, validation_alias=AliasChoices('continuity_months','continuous_coverage_months'))
    additional_evidence: dict = {}

class Citation(BaseModel):
    chunk_id: str; page: int; section: str; source: str; text: str
    dense_score: float = 0; bm25_score: float = 0; fusion_score: float = 0; rerank_score: float = 0

class Finding(BaseModel):
    dimension: str; conclusion: str; citation_ids: list[str] = []

class PolicyFinding(BaseModel):
    condition_type: ConditionType
    finding: str
    supporting_citations: list[str] = []
    status: EvidenceStatus
    impact: Impact

class EvidenceAssessment(BaseModel):
    dimension: str
    claim_fact: Optional[str] = None
    policy_requirement: str
    evidence: list[Citation] = []
    status: EvidenceStatus
    conclusion: str
    citation: Optional[Citation] = None

class EvidenceConflict(BaseModel):
    field: str
    values: list[str]
    sources: list[str]
    impact: str

class MissingEvidenceDetail(BaseModel):
    evidence: str
    why_it_matters: str
    policy_condition: str
    recommended_evidence: str
    impact: Impact

class DecisionExplanation(BaseModel):
    decision: Decision
    reason: str
    policy_basis: list[Citation] = []
    missing_evidence: list[str] = []
    next_action: str

class ConfidenceBreakdown(BaseModel):
    score: float = Field(ge=0, le=1)
    evidence_coverage: float = 0.0
    citation_coverage: float = 0.0
    retrieval_quality: float = 0.0
    conflict_penalty: float = 0.0
    missing_evidence_penalty: float = 0.0
    validation_status: str

class ValidationIssue(BaseModel):
    type: ValidationIssueType
    finding: str
    reason: str

class ValidationResult(BaseModel):
    status: Literal['PASS','FAIL']
    issues: list[ValidationIssue] = []

class TraceEvent(BaseModel):
    agent: str; status: Literal['PASS','WARN','FAIL']; duration_ms: int; summary: str

class AuditEvent(BaseModel):
    timestamp: datetime = Field(default_factory=datetime.now)
    event_type: str
    actor: str
    summary: str
    metadata: dict = {}

class ReviewAction(BaseModel):
    original_decision: Decision
    reviewer_decision: Decision
    reviewer_action: ReviewActionType
    reviewer_reason: str
    timestamp: datetime = Field(default_factory=datetime.now)

class DecisionResponse(BaseModel):
    case_id: str; decision: Decision; confidence: ConfidenceBreakdown
    key_findings: list[PolicyFinding]; applicable_limits: list[str] = []
    missing_evidence: list[MissingEvidenceDetail] = []
    next_action: str
    citations: list[Citation] = []
    validation: ValidationResult
    execution_trace: list[TraceEvent] = []
    evidence_matrix: list[EvidenceAssessment] = []
    conflicts: list[EvidenceConflict] = []
    explanation: DecisionExplanation
    audit_trail: list[AuditEvent] = []
    retrieval_diagnostics: list[dict] = []
