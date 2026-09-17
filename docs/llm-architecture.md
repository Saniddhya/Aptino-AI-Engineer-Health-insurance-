# LLM Architecture & Integration

Aptino uses a decoupled LLM architecture to ensure that reasoning is flexible, auditable, and independent of any specific provider.

## 1. Provider Abstraction Layer
The system defines an `LLMProvider` protocol. Agents do not call APIs directly; instead, they use a provider instance.

**Hierarchy**: `Agent` $\to$ `LLMProvider` $\to$ `Provider Implementation (OpenAI/Mock/etc.)`

This allows the system to:
- Switch models without changing agent logic.
- Run in a fully deterministic "Mock" mode for testing.
- Integrate local models (e.g., via Ollama) for privacy/cost.

## 2. Structured Output (JSON Mode)
To prevent the "chatbot" effect, Aptino enforces structured output using Pydantic.
- Agents request specific schemas (e.g., `EvidenceAssessment`, `PolicyFinding`).
- The provider ensures the LLM returns valid JSON.
- The system validates the JSON against the schema before passing it to the next agent.
- **Failure Handling**: If the LLM returns malformed JSON, the system attempts one retry; otherwise, it fails closed to `NEEDS_REVIEW`.

## 3. Prompt Engineering Strategy
Prompts are stored in `app/prompts/` and follow a strict template:
- **Role**: Explicitly defines the agent's persona (e.g., "Senior Claims Adjuster").
- **Allowed Knowledge**: Strictly limits the LLM to the provided claim facts and retrieved policy chunks.
- **Constraints**: Explicitly forbids the use of general insurance knowledge or hallucinated provisions.
- **Output Schema**: Defines the exact JSON structure required.

## 4. Context Management
To avoid "lost in the middle" and token waste, the LLM context is strictly curated:
- Only the results of the `CaseAnalysisAgent`'s investigation questions are retrieved.
- Only the retrieved chunks are sent to the analysis agents.
- The entire PDF is never sent to the LLM.

## 5. Hallucination Defense
The architecture implements a "Reasoning $\to$ Validation" loop:
1. **LLM Proposes**: The LLM suggests a decision and provides citations.
2. **Deterministic Guard**: The system checks the Evidence Matrix for missing/conflicting material facts.
3. **Citation Validator**: The `ValidationAgent` verifies that every cited `chunk_id` exists in the retrieved set and that the text actually supports the claim.
