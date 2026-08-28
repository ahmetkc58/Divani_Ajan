"""Provider-independent contracts for controlled LLM calls.

The application deliberately treats an LLM as an optional, untrusted
component.  A call either produces locally validated structured data or a
deterministic fallback directive; provider text is never silently accepted.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping


class LLMProviderName(StrEnum):
    OLLAMA = "ollama"
    GROQ = "groq"
    GEMINI = "gemini"
    OPENAI_COMPATIBLE = "openai_compatible"


class LLMTask(StrEnum):
    CLASSIFICATION = "classification"
    EXTRACTION = "extraction"
    SUMMARY = "summary"
    ROUTING = "routing"
    TEMPLATE_SELECTION = "template_selection"
    DRAFT_FIELDS = "draft_fields"
    EVIDENCE_AUDIT = "evidence_audit"
    ADJUDICATION = "adjudication"


class LegalAgentRole(StrEnum):
    """Explicit roles adapted from the project's LegalGraphRAG plan."""

    RESEARCHER = "researcher"
    AUDITOR = "auditor"
    ADJUDICATOR = "adjudicator"
    TEMPLATE_SELECTOR = "template_selector"
    DRAFTER = "drafter"
    ROUTER = "router"
    RESPONSE_ADVISOR = "response_advisor"


class DataClassification(StrEnum):
    """Data classes allowed at the external-provider boundary."""

    SYNTHETIC = "synthetic"
    PUBLIC = "public"
    REDACTED = "redacted"
    RESTRICTED = "restricted"


class LLMStatus(StrEnum):
    SUCCESS = "success"
    DISABLED = "disabled"
    POLICY_REJECTED = "policy_rejected"
    INVALID_REQUEST = "invalid_request"
    TIMEOUT = "timeout"
    PROVIDER_ERROR = "provider_error"
    INVALID_RESPONSE = "invalid_response"
    SCHEMA_REJECTED = "schema_rejected"


class FallbackAction(StrEnum):
    NONE = "none"
    USE_DETERMINISTIC_RULES = "use_deterministic_rules"
    ABSTAIN = "abstain"


_ABSTAIN_TASKS = {LLMTask.EVIDENCE_AUDIT, LLMTask.ADJUDICATION}


def default_fallback_for(task: LLMTask) -> FallbackAction:
    if task in _ABSTAIN_TASKS:
        return FallbackAction.ABSTAIN
    return FallbackAction.USE_DETERMINISTIC_RULES


@dataclass(frozen=True, slots=True)
class LLMConfig:
    """Runtime configuration without a dependency on a provider SDK.

    Local Ollama is the default provider. External Gemini, Groq and
    OpenAI-compatible adapters remain optional and require an API key.
    """

    provider: LLMProviderName = LLMProviderName.OLLAMA
    model: str = "qwen2.5:0.5b"
    api_key: str | None = field(default=None, repr=False)
    base_url: str = "http://127.0.0.1:11434"
    timeout_seconds: float = 20.0
    max_output_tokens: int = 2048
    temperature: float = 0.0
    max_input_chars: int = 120_000
    runtime_enabled: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.provider, LLMProviderName):
            try:
                object.__setattr__(self, "provider", LLMProviderName(self.provider))
            except (TypeError, ValueError) as exc:
                raise ValueError("Desteklenmeyen LLM sağlayıcısı.") from exc
        if not isinstance(self.model, str) or not self.model or len(self.model) > 120:
            raise ValueError("LLM model adı 1-120 karakter arasında olmalıdır.")
        if not isinstance(self.base_url, str) or not self.base_url:
            raise ValueError("LLM base URL yapılandırılmalıdır.")
        if isinstance(self.timeout_seconds, bool) or not isinstance(
            self.timeout_seconds, (int, float)
        ) or not 0 < self.timeout_seconds <= 1800:
            raise ValueError("LLM timeout değeri 0-1800 saniye arasında olmalıdır.")
        if isinstance(self.max_output_tokens, bool) or not isinstance(
            self.max_output_tokens, int
        ) or not 32 <= self.max_output_tokens <= 8192:
            raise ValueError("LLM çıktı token sınırı 32-8192 arasında olmalıdır.")
        if isinstance(self.temperature, bool) or not isinstance(
            self.temperature, (int, float)
        ) or not 0 <= self.temperature <= 1:
            raise ValueError("LLM temperature değeri 0-1 arasında olmalıdır.")
        if isinstance(self.max_input_chars, bool) or not isinstance(
            self.max_input_chars, int
        ) or not 1_000 <= self.max_input_chars <= 500_000:
            raise ValueError("LLM girdi karakter sınırı 1000-500000 arasında olmalıdır.")
        if self.api_key is not None:
            if not isinstance(self.api_key, str):
                raise ValueError("LLM API anahtarı string olmalıdır.")
            stripped = self.api_key.strip()
            object.__setattr__(self, "api_key", stripped or None)

    @property
    def enabled(self) -> bool:
        return self.runtime_enabled and (self.is_local or self.api_key is not None)

    @property
    def is_local(self) -> bool:
        return self.provider is LLMProviderName.OLLAMA

    @classmethod
    def from_env(cls) -> "LLMConfig":
        provider_text = os.getenv("KARAYOL_LLM_PROVIDER", "ollama").strip().casefold()
        try:
            provider = LLMProviderName(provider_text)
        except ValueError as exc:
            raise ValueError("KARAYOL_LLM_PROVIDER desteklenmiyor.") from exc

        explicit_key = os.getenv("KARAYOL_LLM_API_KEY")
        if provider is LLMProviderName.OLLAMA:
            api_key = None
            default_model = "qwen2.5:0.5b"
            default_base_url = "http://127.0.0.1:11434"
        elif provider is LLMProviderName.GROQ:
            api_key = explicit_key or os.getenv("GROQ_API_KEY")
            default_model = "openai/gpt-oss-120b"
            default_base_url = "https://api.groq.com/openai/v1"
        elif provider is LLMProviderName.GEMINI:
            api_key = explicit_key or os.getenv("GEMINI_API_KEY") or os.getenv(
                "GOOGLE_API_KEY"
            )
            default_model = "gemini-2.5-flash"
            default_base_url = "https://generativelanguage.googleapis.com/v1beta"
        else:
            api_key = explicit_key or os.getenv("OPENAI_API_KEY")
            default_model = ""
            default_base_url = ""

        model = os.getenv("KARAYOL_LLM_MODEL", default_model).strip()
        base_url = os.getenv("KARAYOL_LLM_BASE_URL", default_base_url).strip()
        if not model:
            raise ValueError("KARAYOL_LLM_MODEL yapılandırılmalıdır.")
        if not base_url:
            raise ValueError("KARAYOL_LLM_BASE_URL yapılandırılmalıdır.")

        enabled_text = os.getenv("KARAYOL_LLM_ENABLED", "true").strip().casefold()
        if enabled_text not in {
            "1",
            "0",
            "true",
            "false",
            "yes",
            "no",
            "on",
            "off",
        }:
            raise ValueError("KARAYOL_LLM_ENABLED bir boolean değer olmalıdır.")

        return cls(
            provider=provider,
            model=model,
            api_key=api_key,
            base_url=base_url,
            timeout_seconds=float(os.getenv("KARAYOL_LLM_TIMEOUT_SECONDS", "20")),
            max_output_tokens=int(os.getenv("KARAYOL_LLM_MAX_OUTPUT_TOKENS", "2048")),
            temperature=float(os.getenv("KARAYOL_LLM_TEMPERATURE", "0")),
            max_input_chars=int(os.getenv("KARAYOL_LLM_MAX_INPUT_CHARS", "120000")),
            runtime_enabled=enabled_text in {"1", "true", "yes", "on"},
        )


@dataclass(frozen=True, slots=True)
class StructuredLLMRequest:
    task: LLMTask
    role: LegalAgentRole
    input_data: Mapping[str, Any]
    output_schema: Mapping[str, Any]
    # The caller must explicitly attest synthetic/public/redacted data before
    # an external free-tier provider can be used.
    data_classification: DataClassification = DataClassification.RESTRICTED
    trusted_instructions: str = ""
    allow_automatic_redaction: bool = True
    fallback_action: FallbackAction | None = None

    def __post_init__(self) -> None:
        for field_name, enum_type in (
            ("task", LLMTask),
            ("role", LegalAgentRole),
            ("data_classification", DataClassification),
        ):
            value = getattr(self, field_name)
            if not isinstance(value, enum_type):
                try:
                    object.__setattr__(self, field_name, enum_type(value))
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"Geçersiz LLM istek alanı: {field_name}") from exc
        if self.fallback_action is not None and not isinstance(
            self.fallback_action, FallbackAction
        ):
            try:
                object.__setattr__(
                    self, "fallback_action", FallbackAction(self.fallback_action)
                )
            except (TypeError, ValueError) as exc:
                raise ValueError("Geçersiz LLM fallback_action.") from exc
        if self.fallback_action is FallbackAction.NONE:
            raise ValueError(
                "İstek fallback_action olarak 'none' kullanamaz; hata yolu açık olmalıdır."
            )
        if not isinstance(self.input_data, Mapping):
            raise ValueError("LLM input_data bir mapping olmalıdır.")
        if not isinstance(self.output_schema, Mapping):
            raise ValueError("LLM output_schema bir mapping olmalıdır.")
        if not isinstance(self.trusted_instructions, str):
            raise ValueError("LLM trusted_instructions string olmalıdır.")
        if not isinstance(self.allow_automatic_redaction, bool):
            raise ValueError("allow_automatic_redaction boolean olmalıdır.")

    @property
    def effective_fallback(self) -> FallbackAction:
        return self.fallback_action or default_fallback_for(self.task)


@dataclass(frozen=True, slots=True)
class LLMFailure:
    code: str
    message: str
    retryable: bool = False


@dataclass(frozen=True, slots=True)
class LLMCallResult:
    status: LLMStatus
    provider: LLMProviderName
    model: str
    output: Mapping[str, Any] | None = None
    fallback_action: FallbackAction = FallbackAction.NONE
    failure: LLMFailure | None = None
    network_attempted: bool = False
    redacted: bool = False
    redaction_count: int = 0
    finish_reason: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.status is LLMStatus.SUCCESS
