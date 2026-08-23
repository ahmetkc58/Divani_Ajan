from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ProcessStatus(StrEnum):
    RECEIVED = "alindi"
    READING = "okunuyor"
    CLASSIFYING = "siniflandiriliyor"
    SEARCHING = "mevzuat_araniyor"
    VERIFYING = "kaynak_dogrulaniyor"
    WAITING_FOR_INFO = "eksik_bilgi_bekleniyor"
    SELECTING_TEMPLATE = "yazi_turu_seciliyor"
    ROUTING = "birim_yonlendiriliyor"
    DRAFTING = "taslak_hazirlaniyor"
    COMPLIANCE = "uygunluk_kontrolunde"
    WAITING_FOR_APPROVAL = "kullanici_onayi_bekleniyor"
    COMPLETED = "tamamlandi"
    ERROR = "hata"


class FieldStatus(StrEnum):
    FROM_SOURCE = "kaynaktan_alindi"
    INFERRED = "metinden_cikarildi"
    GENERATED = "yonlendirmeden_uretildi"
    USER_REQUIRED = "kullanici_girdisi_gerekli"


class ExtractedField(BaseModel):
    value: str | None = None
    status: FieldStatus
    source: str | None = None


class ClassificationResult(BaseModel):
    document_type: str
    confidence: float = Field(ge=0, le=1)
    matched_keywords: list[str] = Field(default_factory=list)


class DocumentAnalysis(BaseModel):
    document_type: str
    confidence: float = Field(ge=0, le=1)
    summary: str
    fields: dict[str, ExtractedField]
    missing_fields: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)


class LegislationChunk(BaseModel):
    chunk_id: str
    document_id: str | None = Field(
        default=None,
        min_length=2,
        max_length=120,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]+$",
    )
    title: str
    section: str
    article: str | None = None
    paragraph: str | None = None
    clause: str | None = None
    text: str
    source: str
    source_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-fA-F]{64}$"
    )
    # Eski/sentetik kayıtların yanlışlıkla kamu mevzuatı sayılmaması için
    # varsayılan değer bilinçli olarak fail-closed tutulur.
    source_kind: str = "unknown"
    page: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    source_url: str | None = None
    document_type: str = "unknown"
    domain: str = "unknown"
    subdomain: str = "unknown"
    validity_status: str = "needs_verification"
    approved_for_active_rag: bool = False
    ocr_status: str = "not_inspected"
    context_text: str | None = None
    status: str = "unknown"
    tags: list[str] = Field(default_factory=list)


class TextQualityReport(BaseModel):
    character_count: int
    page_count: int
    average_characters_per_page: float
    readable_page_ratio: float
    quality: str
    requires_ocr: bool
    reasons: list[str] = Field(default_factory=list)


class IngestionReport(BaseModel):
    document_id: str | None = None
    source_file: str
    title: str
    source_status: str
    quality: TextQualityReport
    chunk_count: int
    output_file: str | None = None
    approved_for_active_rag: bool = False
    activation_blockers: list[str] = Field(default_factory=list)


class SearchHit(BaseModel):
    chunk: LegislationChunk
    score: float
    matched_terms: list[str] = Field(default_factory=list)


class VerifiedReference(BaseModel):
    chunk_id: str
    title: str
    article: str | None = None
    source: str
    page: int | None = None
    excerpt: str
    score: float
    verified: bool
    verification_note: str


class TemplateDecision(BaseModel):
    document_type: str
    template_id: str
    rationale: str
    confidence: float = Field(ge=0, le=1)
    user_approval_required: bool = True
    alternatives: list[dict[str, Any]] = Field(default_factory=list)


class RoutingRecommendation(BaseModel):
    unit_id: str
    unit_name: str
    hierarchy: str
    rationale: str
    score: float = Field(ge=0, le=1)
    alternatives: list[dict[str, Any]] = Field(default_factory=list)


class UnitRecord(BaseModel):
    unit_id: str
    unit_name: str
    hierarchy: str
    responsibilities: list[str]
    keywords: list[str]


class DraftPayload(BaseModel):
    template_id: str
    institution_name: ExtractedField
    date: ExtractedField
    number: ExtractedField
    subject: ExtractedField
    recipient: ExtractedField
    paragraphs: list[str]
    signer: ExtractedField
    signer_title: ExtractedField
    attachments: list[str] = Field(default_factory=list)
    references: list[VerifiedReference] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)


class ArtifactResult(BaseModel):
    tex_path: str
    pdf_path: str | None = None
    tex_download_url: str | None = None
    pdf_download_url: str | None = None
    compiled: bool = False
    compiler: str | None = None
    warnings: list[str] = Field(default_factory=list)


class ComplianceResult(BaseModel):
    passed: bool
    score: float = Field(ge=0, le=1)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ProcessEvent(BaseModel):
    status: ProcessStatus
    message: str
    agent: str
    timestamp: datetime = Field(default_factory=utc_now)


class ProcessState(BaseModel):
    document_id: str
    status: ProcessStatus = ProcessStatus.RECEIVED
    current_stage: str = "evrak_alimi"
    completed_steps: list[str] = Field(default_factory=list)
    pending_actions: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    next_step: str = "Evrakın işlenmesini başlatınız."
    possible_actions: list[str] = Field(default_factory=lambda: ["isle"])
    provided_information: dict[str, str] = Field(default_factory=dict)
    source_name: str | None = None
    raw_text: str | None = None
    analysis: DocumentAnalysis | None = None
    search_hits: list[SearchHit] = Field(default_factory=list)
    verified_references: list[VerifiedReference] = Field(default_factory=list)
    template_decision: TemplateDecision | None = None
    routing: RoutingRecommendation | None = None
    draft: DraftPayload | None = None
    artifact: ArtifactResult | None = None
    compliance: ComplianceResult | None = None
    events: list[ProcessEvent] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    def add_event(self, status: ProcessStatus, message: str, agent: str) -> None:
        self.status = status
        self.current_stage = status.value
        self.updated_at = utc_now()
        self.events.append(ProcessEvent(status=status, message=message, agent=agent))


class TextProcessRequest(BaseModel):
    text: str = Field(min_length=1, max_length=200_000)
    source_name: str = "kullanici_metni.txt"
    compile_pdf: bool = False


class InformationUpdateRequest(BaseModel):
    fields: dict[str, str] = Field(min_length=1)
    compile_pdf: bool = False


class ApprovalRequest(BaseModel):
    approved_by: str = Field(min_length=2, max_length=120)
