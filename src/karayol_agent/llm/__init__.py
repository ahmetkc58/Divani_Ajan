"""Controlled, provider-agnostic LLM boundary for Divani Ajan."""

from karayol_agent.llm.contracts import (
    DataClassification,
    FallbackAction,
    LegalAgentRole,
    LLMCallResult,
    LLMConfig,
    LLMFailure,
    LLMProviderName,
    LLMStatus,
    LLMTask,
    StructuredLLMRequest,
    default_fallback_for,
)
from karayol_agent.llm.gateway import StructuredLLMGateway, create_llm_gateway

__all__ = [
    "DataClassification",
    "FallbackAction",
    "LegalAgentRole",
    "LLMCallResult",
    "LLMConfig",
    "LLMFailure",
    "LLMProviderName",
    "LLMStatus",
    "LLMTask",
    "StructuredLLMGateway",
    "StructuredLLMRequest",
    "create_llm_gateway",
    "default_fallback_for",
]
