from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

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


class PdfMatchStatus(StrEnum):
    MATCHED = "matched"
    MISSING = "missing"
    DUPLICATE = "duplicate"


class TextLayerStatus(StrEnum):
    NOT_INSPECTED = "not_inspected"
    AVAILABLE = "available"
    OCR_REQUIRED = "ocr_required"
    READ_ERROR = "read_error"
    MISSING = "missing"


class LegislationManifestRecord(BaseModel):
    legislation_id: int
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
    validity_status: str = "needs_verification"
    approved_for_active_rag: bool = False
    reviewed_by: str | None = None
    review_notes: str | None = None

    text_layer_status: TextLayerStatus = TextLayerStatus.NOT_INSPECTED
    text_quality: TextQualityReport | None = None
    ocr_required: bool | None = None
    text_inspection_error: str | None = None


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
    schema_version: str = "1.0"
    generated_at: datetime = Field(default_factory=utc_now)
    source_records: str
    archive_root: str
    policy: str = (
        "Otomatik sınıflandırma yalnızca aday üretir. İnsan kapsam ve yürürlük "
        "doğrulaması olmadan hiçbir kayıt aktif RAG koleksiyonuna alınmaz."
    )
    summary: ManifestSummary
    data: list[LegislationManifestRecord]
