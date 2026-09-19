from __future__ import annotations
from typing import Protocol, Type, TypeVar, Optional, Any, Union
from pydantic import BaseModel
import os
import re
import json
import logging

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

class LLMProvider(Protocol):
    """Interface for LLM providers to ensure decoupling from specific implementations."""

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema: Optional[Type[BaseModel]] = None,
        temperature: float = 0.0
    ) -> Union[BaseModel, str]:
        ...

class MockLLMProvider:
    """Deterministic, policy-aware fallback provider for local development and
    testing without API keys.

    Instead of emitting a generic canned string, this provider inspects each
    agent's *system prompt* to identify which agent is calling, then parses the
    relevant content out of the *user prompt* (claim JSON, retrieved policy
    chunks, evidence matrix, etc.) to produce a structured JSON response that
    matches the schema each agent expects.  This lets the full multi-agent
    pipeline run end-to-end offline and return auditable, evidence-grounded
    decisions.
    """

    # Investigation questions whose keywords align with the policy document so
    # that the hybrid retriever returns relevant chunks.
    _QUESTIONS = [
        "What is the waiting period for pre-existing diseases and continuous coverage?",
        "What exclusions apply to this treatment and diagnosis?",
        "What are the sum insured limits and sub-limits for hospitalization?",
        "What are the hospital eligibility and accreditation requirements?",
        "What documents are required to submit this claim?",
    ]

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema: Optional[Type[BaseModel]] = None,
        temperature: float = 0.0
    ) -> Union[BaseModel, str]:
        if response_schema is not None:
            payload = self._schema_payload(response_schema)
            try:
                return response_schema(**payload)
            except Exception:
                return json.dumps(payload)
        return json.dumps(self._dispatch(system_prompt, user_prompt))

    # ------------------------------------------------------------------ #
    #  Routing
    # ------------------------------------------------------------------ #
    def _agent_kind(self, system_prompt: str) -> str:
        s = system_prompt.lower()
        if "claim analyst" in s and "triage" in s:
            return "case"
        if "policy interpretation" in s:
            return "coverage"
        if "senior claims adjuster" in s:
            return "decision"
        if "policy auditor" in s:
            return "validation"
        return "unknown"

    def _dispatch(self, system_prompt: str, user_prompt: str) -> dict:
        kind = self._agent_kind(system_prompt)
        try:
            if kind == "case":
                return self._case_analysis(user_prompt)
            if kind == "coverage":
                return self._coverage_exclusion(user_prompt)
            if kind == "decision":
                return self._decision(user_prompt)
            if kind == "validation":
                return self._validation(user_prompt)
        except Exception as exc:  # never break the pipeline
            logger.warning("MockLLMProvider.%s failed: %s", kind, exc)
        return {"response": "Mock LLM response: Unable to determine agent type."}

    # ------------------------------------------------------------------ #
    #  Prompt content extraction helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _extract_json_segment(text: str, start_marker: str, end_marker: str) -> str:
        """Return the substring of *text* between *start_marker* and *end_marker*."""
        start = text.find(start_marker)
        end = text.find(end_marker, start) if start != -1 else -1
        if start == -1 or end == -1:
            return ""
        return text[start + len(start_marker):end].strip()

    def _claim_from_prompt(self, user_prompt: str) -> dict:
        """CaseAnalysis prompt = 'Claim Data: <json>'."""
        seg = self._extract_json_segment(user_prompt, "Claim Data:", "") or user_prompt
        seg = seg.replace("Claim Data:", "", 1).strip()
        try:
            return json.loads(seg)
        except Exception:
            return {}

    def _facts_from_prompt(self, user_prompt: str) -> dict:
        """Coverage prompt = 'Claim Facts:\\n<facts-json>\\n\\nPolicy Evidence:'."""
        seg = self._extract_json_segment(user_prompt, "Claim Facts:", "\n\nPolicy Evidence:")
        if seg:
            try:
                return json.loads(seg)
            except Exception:
                return {}
        return {}

    def _chunk_ids_from_prompt(self, user_prompt: str) -> list[str]:
        """Extract chunk_ids embedded in evidence text: 'Chunk <id> (Page N):'."""
        return re.findall(r"Chunk\s+([^\s(]+)\s*\(Page\s+\d+\)", user_prompt)

    # ------------------------------------------------------------------ #
    #  Case Analysis Agent
    # ------------------------------------------------------------------ #
    def _case_analysis(self, user_prompt: str) -> dict:
        claim = self._claim_from_prompt(user_prompt)
        facts = json.dumps({
            "case_id": claim.get("case_id"),
            "treatment": claim.get("treatment"),
            "diagnosis": claim.get("diagnosis"),
            "admission_date": claim.get("admission_date"),
            "policy_start": claim.get("policy_start"),
            "continuity_months": claim.get("continuity_months"),
            "sum_insured": claim.get("sum_insured"),
            "claimed_amount": claim.get("claimed_amount"),
            "documents": claim.get("documents"),
            "hospital": claim.get("hospital"),
        })

        missing = []
        if claim.get("admission_date") is None and claim.get("continuity_months") is None:
            missing.append({
                "evidence": "Admission date or continuous-coverage proof",
                "why_it_matters": "Cannot verify waiting-period eligibility under the policy",
                "policy_condition": "Waiting Period",
                "recommended_evidence": "Hospital admission record and continuity-of-coverage proof",
                "impact": "LIMITING",
            })
        if claim.get("claimed_amount") is None:
            missing.append({
                "evidence": "Claimed amount",
                "why_it_matters": "Cannot verify whether the claim stays within the sum-insured limit",
                "policy_condition": "Sum Insured / Sub-limits",
                "recommended_evidence": "Itemised hospital bill detailing every expense",
                "impact": "INFORMATIONAL",
            })

        return {
            "facts": facts,
            "conflicts": [],
            "missing_evidence": missing,
            "investigation_questions": list(self._QUESTIONS),
        }

        # ------------------------------------------------------------------ #
    #  Coverage & Exclusion Agent
    # ------------------------------------------------------------------ #
    def _heuristic(self, facts: dict) -> tuple:
        """Rule-based reasoning over claim facts.

        Returns (decision_hint, matrix, findings).  The matrix *statuses* and
        the findings' *impacts* are parsed by the Decision agent, so they are
        kept consistent with the policy decision hierarchy.
        """
        continuity = facts.get("continuity_months")
        treatment_data = facts.get("treatment")
        if isinstance(treatment_data, dict):
            treatment = (treatment_data.get("diagnosis") or treatment_data.get("procedure") or "").lower()
        else:
            treatment = (treatment_data or "").lower()
        claimed = facts.get("claimed_amount")
        sum_insured = facts.get("sum_insured")

        matrix, findings = [], []

        # --- Missing critical data -> NEEDS_REVIEW ---
        if claimed is None or (facts.get("admission_date") is None and continuity is None):
            matrix.append({
                "dimension": "Claim Data Completeness",
                "claim_fact": "Incomplete claim documentation supplied",
                "policy_requirement": "Complete claim data (dates, coverage continuity, amount) is mandatory",
                "citation_ids": [],
                "status": "MISSING",
                "conclusion": "Critical claim data missing; cannot verify eligibility",
            })
            return "NEEDS_REVIEW", matrix, findings

        # --- Waiting-period / exclusion -> NOT_ADMISSIBLE ---
        if continuity is not None and continuity < 24 and "planned" in treatment:
            findings.append({
                "condition_type": "EXCLUSION",
                "finding": "Planned treatment availed within the 24-month waiting period is excluded from coverage",
                "supporting_citations": [],
                "status": "SUPPORTED",
                "impact": "BLOCKING",
            })
            matrix.append({
                "dimension": "Waiting Period",
                "claim_fact": f"Continuous coverage is {continuity} months",
                "policy_requirement": "24 months continuous coverage required before planned treatment",
                "citation_ids": [],
                "status": "SUPPORTED",
                "conclusion": "Treatment falls within the waiting-period exclusion",
            })
            return "NOT_ADMISSIBLE", matrix, findings

        if continuity is not None and continuity < 24:
            matrix.append({
                "dimension": "Waiting Period",
                "claim_fact": f"Continuous coverage is {continuity} months",
                "policy_requirement": "Continuous coverage requirement",
                "citation_ids": [],
                "status": "PARTIALLY_SUPPORTED",
                "conclusion": "Coverage continuity is below the preferred threshold",
            })

        # --- Sum-insured exceeded -> ADMISSIBLE_WITH_LIMITS ---
        if claimed is not None and sum_insured is not None and claimed > sum_insured:
            findings.append({
                "condition_type": "LIMIT",
                "finding": f"Claimed amount ({claimed}) exceeds the sum insured ({sum_insured})",
                "supporting_citations": [],
                "status": "SUPPORTED",
                "impact": "LIMITING",
            })
            matrix.append({
                "dimension": "Sum Insured Limits",
                "claim_fact": f"Claimed {claimed} exceeds sum insured {sum_insured}",
                "policy_requirement": "Claims payable up to the sum insured",
                "citation_ids": [],
                "status": "PARTIALLY_SUPPORTED",
                "conclusion": "Claim exceeds the sum-insured ceiling",
            })
            return "ADMISSIBLE_WITH_LIMITS", matrix, findings

        # --- Default -> ADMISSIBLE ---
        matrix.append({
            "dimension": "Waiting Period",
            "claim_fact": f"Continuous coverage is {continuity} months",
            "policy_requirement": "Continuous coverage requirement",
            "citation_ids": [],
            "status": "SUPPORTED",
            "conclusion": "Waiting-period and continuity requirements satisfied",
        })
        matrix.append({
            "dimension": "Exclusions",
            "claim_fact": treatment or "N/A",
            "policy_requirement": "No applicable exclusion",
            "citation_ids": [],
            "status": "SUPPORTED",
            "conclusion": "No blocking exclusion applies to this treatment",
        })
        return "ADMISSIBLE", matrix, findings

    def _coverage_exclusion(self, user_prompt: str) -> dict:
        facts = self._facts_from_prompt(user_prompt)
        chunk_ids = self._chunk_ids_from_prompt(user_prompt)
        _hint, matrix, findings = self._heuristic(facts)

        # Attach real, retrieved chunk_ids so citations resolve in the matrix.
        ci = iter(chunk_ids)
        for m in matrix:
            cid = next(ci, None)
            if cid:
                m["citation_ids"] = [cid]
        for fnd in findings:
            cid = next(ci, None)
            if cid:
                fnd["supporting_citations"] = [cid]

        return {"evidence_matrix": matrix, "findings": findings}

    # ------------------------------------------------------------------ #
    #  Decision Agent
    # ------------------------------------------------------------------ #
    def _decision(self, user_prompt: str) -> dict:
        # The decision prompt embeds the evidence-matrix + findings text.  Parse
        # the safety-hierarchy signals straight from that text.
        text = user_prompt
        has_missing = "MISSING" in text or "CONFLICTING" in text
        has_blocking = "BLOCKING" in text
        has_limiting = "LIMITING" in text
        has_partial = "PARTIALLY_SUPPORTED" in text

        if has_missing:
            decision, reason, next_action = "NEEDS_REVIEW", "Missing or conflicting evidence for one or more material dimensions.", "Review claim manually and request missing evidence."
        elif has_blocking:
            decision, reason, next_action = "NOT_ADMISSIBLE", "A blocking exclusion is verified by policy evidence.", "Deny the claim with an exclusion notice."
        elif has_limiting:
            decision, reason, next_action = "ADMISSIBLE_WITH_LIMITS", "Coverage applies but is subject to limiting sub-limits.", "Approve with applicable limits and inform the claimant."
        elif has_partial:
            decision, reason, next_action = "PARTIALLY_ADMISSIBLE", "Coverage is partially supported; some items require review.", "Review partially-admissible items manually."
        else:
            decision, reason, next_action = "ADMISSIBLE", "All material conditions are supported by policy evidence.", "Approve the claim."

        return {
            "decision": decision,
            "confidence": {
                "score": 0.85,
                "evidence_coverage": 0.90,
                "citation_coverage": 0.85,
                "retrieval_quality": 0.80,
                "conflict_penalty": 0.0,
                "missing_evidence_penalty": 0.0,
                "validation_status": "PASS",
            },
            "explanation": {
                "decision": decision,
                "reason": reason,
                "policy_basis": [],
                "missing_evidence": [],
                "next_action": next_action,
            },
            "applicable_limits": [],
            "key_findings": [],
            "next_action": next_action,
        }

    # ------------------------------------------------------------------ #
    #  Validation Agent
    # ------------------------------------------------------------------ #
    def _validation(self, user_prompt: str) -> dict:
        # If real policy chunks were retrieved, the decision is evidence-backed.
        has_evidence = bool(re.search(r"Chunk\s+policy_p\d+_", user_prompt))
        issues = []
        if not has_evidence:
            issues.append({
                "type": "MISSING_CITATION",
                "finding": "No policy evidence retrieved to support the decision",
                "reason": "Retrieval returned zero policy chunks for the investigation questions",
            })
        return {"status": "PASS" if has_evidence else "FAIL", "issues": issues}

    # ------------------------------------------------------------------ #
    #  Schema-based path (compatibility; agents currently parse JSON strings)
    # ------------------------------------------------------------------ #
    def _schema_payload(self, schema: Type[BaseModel]) -> dict:
        return {
            "facts": "Case facts extracted from claim data.",
            "conflicts": [],
            "missing_evidence": [],
            "investigation_questions": list(self._QUESTIONS),
            "evidence_matrix": [],
            "findings": [],
            "decision": "ADMISSIBLE",
            "confidence": {"score": 0.8, "validation_status": "PASS", "evidence_coverage": 0.9,
                           "citation_coverage": 0.85, "retrieval_quality": 0.8,
                           "conflict_penalty": 0.0, "missing_evidence_penalty": 0.0},
            "explanation": {"decision": "ADMISSIBLE", "reason": "Evidence supports admissibility.",
                            "policy_basis": [], "missing_evidence": [], "next_action": "Approve"},
            "applicable_limits": [],
            "key_findings": [],
            "next_action": "Approve the claim.",
            "status": "PASS",
            "issues": [],
            "unsupported_claims": [],
        }

class OpenAIProvider:
    """Integration with OpenAI GPT models."""

    def __init__(self):
        from openai import OpenAI
        self.client = OpenAI(api_key=os.getenv('LLM_API_KEY'))
        self.model = os.getenv('LLM_MODEL', 'gpt-4o')

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema: Optional[Type[BaseModel]] = None,
        temperature: float = 0.0
    ) -> Union[BaseModel, str]:
        try:
            kwargs = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": temperature,
            }

            if response_schema:
                # Use JSON mode or Tool Use for structured output
                kwargs["response_format"] = {"type": "json_object"}
                # We add a instruction to the system prompt to ensure JSON output
                # (Usually handled by the prompt architecture)

            response = self.client.chat.completions.create(**kwargs)
            content = response.choices[0].message.content

            if response_schema:
                return response_schema.model_validate_json(content)

            return content
        except Exception as e:
            logger.error(f"OpenAIProvider error: {e}")
            raise e

class AnthropicProvider:
    """Integration with Anthropic Claude models."""

    def __init__(self):
        import anthropic
        self.client = anthropic.Anthropic(api_key=os.getenv('LLM_API_KEY'))
        self.model = os.getenv('LLM_MODEL', 'claude-3-5-sonnet-20240620')

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema: Optional[Type[BaseModel]] = None,
        temperature: float = 0.0
    ) -> Union[BaseModel, str]:
        try:
            # Claude takes system prompt as a separate parameter
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                temperature=temperature,
                system=system_prompt,
                messages=[
                    {"role": "user", "content": user_prompt},
                ],
            )
            content = response.content[0].text

            if response_schema:
                # Claude doesn't have a native JSON mode like OpenAI,
                # but we can use tool use or just assume JSON if prompted.
                return response_schema.model_validate_json(content)

            return content
        except Exception as e:
            logger.error(f"AnthropicProvider error: {e}")
            raise e

class GeminiProvider:
    """Integration with Google Gemini models."""

    def __init__(self):
        import google.generativeai as genai
        genai.configure(api_key=os.getenv('LLM_API_KEY'))
        self.model_name = os.getenv('LLM_MODEL', 'gemini-1.5-pro')
        self.model = genai.GenerativeModel(self.model_name)

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema: Optional[Type[BaseModel]] = None,
        temperature: float = 0.0
    ) -> Union[BaseModel, str]:
        try:
            # Gemini handles system instructions during model initialization
            # or as part of the prompt. For simplicity here, we prepend it.
            full_prompt = f"System Instructions:\n{system_prompt}\n\nUser Request:\n{user_prompt}"

            response = self.model.generate_content(
                full_prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=temperature,
                ),
            )
            content = response.text

            if response_schema:
                return response_schema.model_validate_json(content)

            return content
        except Exception as e:
            logger.error(f"GeminiProvider error: {e}")
            raise e

class LLMFactory:
    """Factory to instantiate the configured LLM provider."""

    @staticmethod
    def get_provider() -> LLMProvider:
        provider_type = os.getenv('LLM_PROVIDER', 'mock').lower()

        if provider_type == 'openai':
            if not os.getenv('LLM_API_KEY'):
                raise RuntimeError("LLM_PROVIDER set to 'openai' but LLM_API_KEY is missing.")
            return OpenAIProvider()

        if provider_type == 'anthropic':
            if not os.getenv('LLM_API_KEY'):
                raise RuntimeError("LLM_PROVIDER set to 'anthropic' but LLM_API_KEY is missing.")
            return AnthropicProvider()

        if provider_type == 'gemini':
            if not os.getenv('LLM_API_KEY'):
                raise RuntimeError("LLM_PROVIDER set to 'gemini' but LLM_API_KEY is missing.")
            return GeminiProvider()

        if provider_type == 'mock':
            return MockLLMProvider()

        # Default fallback
        logger.warning(f"Unknown LLM_PROVIDER '{provider_type}'. Falling back to mock.")
        return MockLLMProvider()
