from __future__ import annotations
from typing import Protocol, Type, TypeVar, Optional, Any, Union
from pydantic import BaseModel
import os
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
    """Fallback provider for local development and testing without API keys."""

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema: Optional[Type[BaseModel]] = None,
        temperature: float = 0.0
    ) -> Union[BaseModel, str]:
        if response_schema:
            # Create a mock dictionary that matches the schema as best as possible
            # This is a simplification for the mock.
            mock_data = {
                "facts": "Mock facts",
                "conflicts": [],
                "missing_evidence": [],
                "investigation_questions": ["Mock question 1", "Mock question 2"],
                "evidence_matrix": [],
                "findings": [],
                "decision": "ADMISSIBLE",
                "confidence": {"score": 0.8, "validation_status": "PASS"},
                "explanation": {"decision": "ADMISSIBLE", "reason": "Mock reason", "next_action": "None"},
                "status": "PASS",
                "unsupported_claims": []
            }
            try:
                return response_schema(**mock_data)
            except Exception:
                # Fallback to returning a JSON string that the agent can parse
                return json.dumps(mock_data)

        return json.dumps({"response": "Mock LLM response: The claim is admissible."})

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

class LLMFactory:
    """Factory to instantiate the configured LLM provider."""

    @staticmethod
    def get_provider() -> LLMProvider:
        provider_type = os.getenv('LLM_PROVIDER', 'mock').lower()

        if provider_type == 'openai':
            if not os.getenv('LLM_API_KEY'):
                logger.warning("LLM_PROVIDER set to 'openai' but LLM_API_KEY is missing. Falling back to mock.")
                return MockLLMProvider()
            return OpenAIProvider()

        # Add other providers like 'ollama' or 'anthropic' here

        return MockLLMProvider()
