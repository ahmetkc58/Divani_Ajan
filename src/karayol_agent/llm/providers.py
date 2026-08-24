"""Gemini and OpenAI-compatible structured-output adapters."""

from __future__ import annotations

import ipaddress
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping, Protocol
from urllib.parse import quote, urlsplit

from karayol_agent.llm.contracts import LLMConfig, LLMProviderName
from karayol_agent.llm.transport import HTTPRequest, HTTPTransport


class ProviderCallError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class ProviderCompletion:
    text: str
    finish_reason: str | None = None


class StructuredOutputProvider(Protocol):
    config: LLMConfig

    def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        output_schema: Mapping[str, Any],
    ) -> ProviderCompletion: ...


_MODEL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,119}$")


def _validated_base_url(value: str, *, provider: LLMProviderName) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("LLM base URL yalnız geçerli HTTPS adresi olabilir.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("LLM base URL kimlik bilgisi, query veya fragment içeremez.")
    hostname = parsed.hostname.casefold()
    if provider is LLMProviderName.GEMINI and hostname != "generativelanguage.googleapis.com":
        raise ValueError("Gemini sağlayıcısı yalnız resmî Google API alan adını kullanabilir.")
    if provider is LLMProviderName.GROQ and hostname != "api.groq.com":
        raise ValueError("Groq sağlayıcısı yalnız resmî Groq API alan adını kullanabilir.")
    normalized_path = parsed.path.rstrip("/")
    if provider is LLMProviderName.GEMINI and normalized_path != "/v1beta":
        raise ValueError("Gemini base URL yolu '/v1beta' olmalıdır.")
    if provider is LLMProviderName.GROQ and normalized_path != "/openai/v1":
        raise ValueError("Groq base URL yolu '/openai/v1' olmalıdır.")
    if provider in {LLMProviderName.GEMINI, LLMProviderName.GROQ} and parsed.port:
        raise ValueError("Resmî LLM sağlayıcı URL'si özel port içeremez.")
    if provider is LLMProviderName.OPENAI_COMPATIBLE:
        if hostname == "localhost" or hostname.endswith(".localhost"):
            raise ValueError("OpenAI-compatible base URL yerel ağ adresi olamaz.")
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            pass
        else:
            if not address.is_global:
                raise ValueError("OpenAI-compatible base URL özel/yerel IP olamaz.")
    return value.rstrip("/")


def _decode_provider_json(body: bytes) -> Mapping[str, Any]:
    try:
        result = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderCallError(
            "malformed_provider_response",
            "LLM sağlayıcısı geçerli JSON yanıtı döndürmedi.",
        ) from exc
    if not isinstance(result, dict):
        raise ProviderCallError(
            "malformed_provider_response",
            "LLM sağlayıcı yanıtının biçimi geçersiz.",
        )
    return result


def _http_error(status_code: int) -> ProviderCallError:
    if status_code in {408, 429} or status_code >= 500:
        return ProviderCallError(
            f"http_{status_code}",
            f"LLM sağlayıcısı geçici bir HTTP {status_code} hatası döndürdü.",
            retryable=True,
        )
    return ProviderCallError(
        f"http_{status_code}",
        f"LLM sağlayıcısı HTTP {status_code} hatası döndürdü.",
    )


class GeminiProvider:
    def __init__(self, config: LLMConfig, transport: HTTPTransport) -> None:
        if config.provider is not LLMProviderName.GEMINI:
            raise ValueError("GeminiProvider için provider='gemini' olmalıdır.")
        if not _MODEL_PATTERN.fullmatch(config.model):
            raise ValueError("Gemini model adı güvenli karakter kümesine uymuyor.")
        self.config = config
        self.transport = transport
        self.base_url = _validated_base_url(
            config.base_url, provider=LLMProviderName.GEMINI
        )

    def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        output_schema: Mapping[str, Any],
    ) -> ProviderCompletion:
        if not self.config.api_key:
            raise ProviderCallError("missing_api_key", "Gemini API anahtarı yapılandırılmamış.")
        model = quote(self.config.model, safe="")
        payload = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {
                "temperature": self.config.temperature,
                "maxOutputTokens": self.config.max_output_tokens,
                "responseMimeType": "application/json",
                "responseJsonSchema": output_schema,
            },
        }
        response = self.transport.send(
            HTTPRequest(
                url=f"{self.base_url}/models/{model}:generateContent",
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "Accept": "application/json",
                    "x-goog-api-key": self.config.api_key,
                },
                body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                timeout_seconds=self.config.timeout_seconds,
            )
        )
        if not 200 <= response.status_code < 300:
            raise _http_error(response.status_code)
        result = _decode_provider_json(response.body)
        candidates = result.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise ProviderCallError(
                "blocked_or_empty",
                "Gemini yanıtı güvenlik filtresince engellendi veya boş döndü.",
            )
        candidate = candidates[0]
        if not isinstance(candidate, dict):
            raise ProviderCallError(
                "malformed_provider_response", "Gemini aday yanıtı çözümlenemedi."
            )
        try:
            parts = candidate["content"]["parts"]
            text_parts = [
                part["text"]
                for part in parts
                if isinstance(part, dict) and isinstance(part.get("text"), str)
            ]
        except (KeyError, TypeError) as exc:
            raise ProviderCallError(
                "malformed_provider_response", "Gemini içerik yanıtı çözümlenemedi."
            ) from exc
        if not text_parts:
            raise ProviderCallError("blocked_or_empty", "Gemini metin yanıtı boş döndü.")
        finish_reason = candidate.get("finishReason")
        if finish_reason not in {None, "STOP"}:
            raise ProviderCallError(
                "incomplete_completion",
                "Gemini yanıtı tamamlanmadan sonlandırıldı.",
                retryable=finish_reason == "MAX_TOKENS",
            )
        return ProviderCompletion(text="".join(text_parts), finish_reason=finish_reason)


class OpenAICompatibleProvider:
    def __init__(self, config: LLMConfig, transport: HTTPTransport) -> None:
        if config.provider not in {
            LLMProviderName.GROQ,
            LLMProviderName.OPENAI_COMPATIBLE,
        }:
            raise ValueError(
                "OpenAICompatibleProvider için provider='groq' veya "
                "'openai_compatible' olmalıdır."
            )
        if not _MODEL_PATTERN.fullmatch(config.model):
            raise ValueError("LLM model adı güvenli karakter kümesine uymuyor.")
        self.config = config
        self.transport = transport
        self.base_url = _validated_base_url(config.base_url, provider=config.provider)

    def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        output_schema: Mapping[str, Any],
    ) -> ProviderCompletion:
        if not self.config.api_key:
            raise ProviderCallError("missing_api_key", "LLM API anahtarı yapılandırılmamış.")
        payload = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.config.temperature,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "divani_agent_output",
                    "strict": True,
                    "schema": output_schema,
                },
            },
        }
        token_field = (
            "max_completion_tokens"
            if self.config.provider is LLMProviderName.GROQ
            else "max_tokens"
        )
        payload[token_field] = self.config.max_output_tokens
        response = self.transport.send(
            HTTPRequest(
                url=f"{self.base_url}/chat/completions",
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "Accept": "application/json",
                    "Authorization": f"Bearer {self.config.api_key}",
                },
                body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                timeout_seconds=self.config.timeout_seconds,
            )
        )
        if not 200 <= response.status_code < 300:
            raise _http_error(response.status_code)
        result = _decode_provider_json(response.body)
        choices = result.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ProviderCallError("blocked_or_empty", "LLM yanıtı boş döndü.")
        choice = choices[0]
        if not isinstance(choice, dict):
            raise ProviderCallError(
                "malformed_provider_response", "LLM aday yanıtı çözümlenemedi."
            )
        try:
            text = choice["message"]["content"]
        except (KeyError, TypeError) as exc:
            raise ProviderCallError(
                "malformed_provider_response", "LLM içerik yanıtı çözümlenemedi."
            ) from exc
        if not isinstance(text, str) or not text.strip():
            raise ProviderCallError("blocked_or_empty", "LLM metin yanıtı boş döndü.")
        finish_reason = choice.get("finish_reason")
        if finish_reason not in {None, "stop"}:
            raise ProviderCallError(
                "incomplete_completion",
                "LLM yanıtı tamamlanmadan sonlandırıldı.",
                retryable=finish_reason == "length",
            )
        return ProviderCompletion(text=text, finish_reason=finish_reason)


def create_provider(config: LLMConfig, transport: HTTPTransport) -> StructuredOutputProvider:
    if config.provider is LLMProviderName.GEMINI:
        return GeminiProvider(config, transport)
    return OpenAICompatibleProvider(config, transport)
