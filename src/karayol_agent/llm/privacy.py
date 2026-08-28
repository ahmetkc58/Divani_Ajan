"""Data-loss prevention at the external LLM boundary."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from karayol_agent.llm.contracts import DataClassification


class DataPolicyError(ValueError):
    """Raised before networking when an input is not allowed to leave the app."""


@dataclass(frozen=True, slots=True)
class PrivacyFinding:
    kind: str
    masked_sample: str


@dataclass(frozen=True, slots=True)
class GuardedPayload:
    payload: Mapping[str, Any]
    findings: tuple[PrivacyFinding, ...]

    @property
    def redacted(self) -> bool:
        return bool(self.findings)


_PERSONAL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("IBAN", re.compile(r"\bTR\s*\d{2}(?:\s*\d){22}\b", re.IGNORECASE)),
    (
        "EMAIL",
        re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+(?![\w.-])", re.IGNORECASE),
    ),
    (
        "PHONE",
        re.compile(r"(?<!\d)(?:\+?90\s*)?0?5\d{2}(?:[\s().-]*\d){7}(?!\d)"),
    ),
)

_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "API_TOKEN",
        re.compile(
            r"\b(?:AIza[0-9A-Za-z_-]{20,}|sk-[0-9A-Za-z_-]{16,}|gh[pousr]_[0-9A-Za-z]{20,}|Bearer\s+[0-9A-Za-z._~-]{16,})\b",
            re.IGNORECASE,
        ),
    ),
)

_SECRET_FIELD_NAMES = {
    "apikey",
    "authorization",
    "accesstoken",
    "refreshtoken",
    "password",
    "parola",
    "secret",
    "token",
}

_TCKN_PATTERN = re.compile(r"(?<!\d)[1-9]\d{10}(?!\d)")


def _valid_tckn(value: str) -> bool:
    digits = [int(character) for character in value]
    tenth = ((sum(digits[0:9:2]) * 7) - sum(digits[1:8:2])) % 10
    eleventh = sum(digits[:10]) % 10
    return digits[9] == tenth and digits[10] == eleventh


def _masked(value: str) -> str:
    if len(value) <= 4:
        return "*" * len(value)
    return f"{value[:2]}***{value[-2:]}"


def _redact_text(
    text: str, *, redact_personal_identifiers: bool
) -> tuple[str, list[PrivacyFinding]]:
    findings: list[PrivacyFinding] = []
    result = text

    def replace_tckn(match: re.Match[str]) -> str:
        value = match.group(0)
        if not _valid_tckn(value):
            return value
        findings.append(PrivacyFinding("TCKN", _masked(value)))
        return "[KİŞİSEL_VERİ:TCKN]"

    if redact_personal_identifiers:
        result = _TCKN_PATTERN.sub(replace_tckn, result)
    patterns = _SECRET_PATTERNS + (
        _PERSONAL_PATTERNS if redact_personal_identifiers else ()
    )
    for kind, pattern in patterns:
        def replace(match: re.Match[str], *, finding_kind: str = kind) -> str:
            value = match.group(0)
            findings.append(PrivacyFinding(finding_kind, _masked(value)))
            label = "GİZLİ" if finding_kind == "API_TOKEN" else "KİŞİSEL_VERİ"
            return f"[{label}:{finding_kind}]"

        result = pattern.sub(replace, result)
    return result, findings


def _walk(
    value: Any,
    findings: list[PrivacyFinding],
    *,
    redact_personal_identifiers: bool,
) -> Any:
    if isinstance(value, str):
        redacted, local_findings = _redact_text(
            value,
            redact_personal_identifiers=redact_personal_identifiers,
        )
        findings.extend(local_findings)
        return redacted
    if isinstance(value, Mapping):
        guarded_mapping: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise DataPolicyError("LLM JSON nesnesi alan adları string olmalıdır.")
            guarded_key, key_findings = _redact_text(
                key,
                redact_personal_identifiers=redact_personal_identifiers,
            )
            findings.extend(key_findings)
            if guarded_key in guarded_mapping:
                raise DataPolicyError("Redaksiyon sonrasında çakışan JSON alan adı oluştu.")
            normalized_key = re.sub(r"[^a-z0-9]", "", key.casefold())
            if normalized_key in _SECRET_FIELD_NAMES and isinstance(item, str) and item:
                findings.append(PrivacyFinding("SECRET_FIELD", _masked(item)))
                guarded_mapping[guarded_key] = "[GİZLİ:SECRET_FIELD]"
            else:
                guarded_mapping[guarded_key] = _walk(
                    item,
                    findings,
                    redact_personal_identifiers=redact_personal_identifiers,
                )
        return guarded_mapping
    if isinstance(value, list):
        return [
            _walk(
                item,
                findings,
                redact_personal_identifiers=redact_personal_identifiers,
            )
            for item in value
        ]
    if isinstance(value, tuple):
        return [
            _walk(
                item,
                findings,
                redact_personal_identifiers=redact_personal_identifiers,
            )
            for item in value
        ]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    raise DataPolicyError("LLM girdisi yalnız JSON-uyumlu değerler içerebilir.")


class ExternalDataGuard:
    """Fail-closed policy for external APIs and secret filtering for local LLMs."""

    def prepare(
        self,
        payload: Mapping[str, Any],
        *,
        classification: DataClassification,
        allow_automatic_redaction: bool,
        allow_restricted_local: bool = False,
    ) -> GuardedPayload:
        if classification is DataClassification.RESTRICTED and not allow_restricted_local:
            raise DataPolicyError(
                "Kısıtlı/gerçek evrak verisi harici LLM sağlayıcısına gönderilemez."
            )
        if not isinstance(payload, Mapping):
            raise DataPolicyError("LLM girdisinin üst seviyesi bir JSON nesnesi olmalıdır.")

        findings: list[PrivacyFinding] = []
        guarded = _walk(
            payload,
            findings,
            # SYNTHETIC is an explicit caller attestation. This lets curated
            # fixtures retain fake phone/e-mail fields needed by extraction
            # tests; secrets are still always removed.
            redact_personal_identifiers=(
                classification not in {
                    DataClassification.SYNTHETIC,
                    DataClassification.RESTRICTED,
                }
            ),
        )
        if findings and not allow_automatic_redaction:
            raise DataPolicyError(
                "Girdi kişisel veri veya gizli anahtar içeriyor; ağ çağrısı engellendi."
            )
        return GuardedPayload(payload=guarded, findings=tuple(findings))
