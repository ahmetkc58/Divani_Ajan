from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from karayol_agent.schemas import TextQualityReport, utc_now


class CurationDomain(StrEnum):
    OFFICIAL_WRITING = "official_writing"
    GENERAL_APPLICATION = "general_application"
    KGM_INFRASTRUCTURE = "kgm_infrastructure"
    ROAD_TRANSPORT = "road_transport"
    MARITIME = "maritime"
    AVIATION = "aviation"
    RAILWAY = "railway"
    COMMUNICATIONS = "communications"
    INTERNAL_ADMINISTRATION = "internal_administration"
    UNKNOWN = "unknown"


class ScopeStatus(StrEnum):
    ACTIVE = "active"
    REVIEW_REQUIRED = "review_required"
    OUT_OF_SCOPE = "out_of_scope"


class ReviewStatus(StrEnum):
    NEEDS_HUMAN_REVIEW = "needs_human_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class ValidityStatus(StrEnum):
    NEEDS_VERIFICATION = "needs_verification"
    VERIFIED = "verified"
    REPEALED = "repealed"
    EXPIRED = "expired"


class PdfMatchStatus(StrEnum):
    MATCHED = "matched"
    MISSING = "missing"
    DUPLICATE = "duplicate"


class TextLayerStatus(StrEnum):
    NOT_INSPECTED = "not_inspected"
    AVAILABLE = "available"
    OCR_VERIFIED = "ocr_verified"
    OCR_REQUIRED = "ocr_required"
    READ_ERROR = "read_error"
    MISSING = "missing"


class LegislationManifestRecord(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    legislation_id: int
    document_id: str | None = Field(
        default=None,
        min_length=2,
        max_length=120,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]+$",
    )
    title: str
    document_type: str
    regulation_number: str | None = None
    official_gazette_number: str | None = None
    official_gazette_date: str | None = None
    source_url: str | None = None
    local_pdfs: list[str] = Field(default_factory=list)
    pdf_match_status: PdfMatchStatus

    domain: CurationDomain
    secondary_domains: list[CurationDomain] = Field(default_factory=list)
    subdomain: str
    classification_confidence: float = Field(ge=0, le=1)
    classification_reasons: list[str] = Field(default_factory=list)
    scope_status: ScopeStatus
    candidate_for_active_rag: bool = False

    review_status: ReviewStatus = ReviewStatus.NEEDS_HUMAN_REVIEW
    validity_status: ValidityStatus = ValidityStatus.NEEDS_VERIFICATION
    approved_for_active_rag: bool = False
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    review_notes: str | None = None

    source_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-fA-F]{64}$"
    )
    source_bytes: int | None = Field(default=None, ge=0)

    text_layer_status: TextLayerStatus = TextLayerStatus.NOT_INSPECTED
    text_quality: TextQualityReport | None = None
    ocr_required: bool | None = None
    text_inspection_error: str | None = None

    def activation_blockers(self) -> list[str]:
        blockers: list[str] = []
        if not self.document_id:
            blockers.append("document_id_missing")
        if self.review_status != ReviewStatus.APPROVED:
            blockers.append("human_review_not_approved")
        if self.scope_status != ScopeStatus.ACTIVE:
            blockers.append("scope_not_active")
        if self.validity_status != ValidityStatus.VERIFIED:
            blockers.append("validity_not_verified")
        if self.pdf_match_status != PdfMatchStatus.MATCHED or len(self.local_pdfs) != 1:
            blockers.append("single_source_pdf_not_matched")
        if self.text_layer_status not in {
            TextLayerStatus.AVAILABLE,
            TextLayerStatus.OCR_VERIFIED,
        }:
            blockers.append("text_or_ocr_not_verified")
        if self.ocr_required is not False:
            blockers.append("ocr_requirement_not_cleared")
        if not self.reviewed_by or not self.reviewed_by.strip():
            blockers.append("reviewer_missing")
        if self.reviewed_at is None:
            blockers.append("review_timestamp_missing")
        if not self.source_sha256 or not _is_sha256(self.source_sha256):
            blockers.append("source_sha256_missing_or_invalid")
        if self.domain not in {
            CurationDomain.OFFICIAL_WRITING,
            CurationDomain.GENERAL_APPLICATION,
            CurationDomain.KGM_INFRASTRUCTURE,
            CurationDomain.ROAD_TRANSPORT,
        }:
            blockers.append("domain_not_in_active_project_scope")
        return blockers

    @model_validator(mode="after")
    def validate_active_rag_approval(self) -> "LegislationManifestRecord":
        has_human_decision = (
            self.review_status != ReviewStatus.NEEDS_HUMAN_REVIEW
            or self.validity_status != ValidityStatus.NEEDS_VERIFICATION
        )
        if has_human_decision and (
            not self.reviewed_by
            or not self.reviewed_by.strip()
            or self.reviewed_at is None
        ):
            raise ValueError(
                "İnsan kapsam/yürürlük kararı reviewed_by ve reviewed_at "
                "alanlarını gerektirir."
            )
        if self.approved_for_active_rag:
            blockers = self.activation_blockers()
            if blockers:
                raise ValueError(
                    "Aktif RAG onayı güvenlik kapılarını karşılamıyor: "
                    + ", ".join(blockers)
                )
        return self


class ManifestSummary(BaseModel):
    source_record_count: int
    manifest_record_count: int
    matched_pdf_count: int
    missing_pdf_count: int
    duplicate_pdf_count: int
    unmatched_archive_pdf_count: int
    candidate_for_active_rag_count: int
    approved_for_active_rag_count: int
    review_required_count: int
    out_of_scope_count: int
    ocr_required_count: int
    text_read_error_count: int
    text_not_inspected_count: int
    domain_counts: dict[str, int] = Field(default_factory=dict)


class LegislationManifest(BaseModel):
    schema_version: str = "2.0"
    generated_at: datetime = Field(default_factory=utc_now)
    source_records: str
    archive_root: str
    policy: str = (
        "Otomatik sınıflandırma yalnızca aday üretir. İnsan kapsam ve yürürlük "
        "doğrulaması olmadan hiçbir kayıt aktif RAG koleksiyonuna alınmaz."
    )
    summary: ManifestSummary
    data: list[LegislationManifestRecord]


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(
        character in "0123456789abcdefABCDEF" for character in value
    )
