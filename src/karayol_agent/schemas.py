from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal

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
    WAITING_FOR_RESPONSE_STRATEGY = "yanit_stratejisi_bekleniyor"
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
    # İki alan da yarışma sözleşmesindeki kapalı altılı evrak türünü taşır.
    # İnce konu/niyet ayrımı ``DocumentAnalysis.operational_category`` alanındadır.
    document_type: str
    general_document_type: str = "dilekce"
    confidence: float = Field(ge=0, le=1)
    matched_keywords: list[str] = Field(default_factory=list)


class DocumentAnalysis(BaseModel):
    document_type: str
    general_document_type: str = "dilekce"
    document_subtype: str | None = None
    operational_category: str | None = None
    confidence: float = Field(ge=0, le=1)
    summary: str
    # Retrieval safety checks need evidence from the submitted document, not
    # labels or expansion phrases produced later in the pipeline.
    retrieval_evidence_text: str | None = None
    fields: dict[str, ExtractedField]
    missing_fields: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    important_facts: list[str] = Field(default_factory=list)
    classification_reference_ids: list[str] = Field(default_factory=list)


class BoundingBox(BaseModel):
    """Normalized page coordinates produced by a trusted local extractor."""

    x0: float = Field(ge=0, le=1)
    y0: float = Field(ge=0, le=1)
    x1: float = Field(ge=0, le=1)
    y1: float = Field(ge=0, le=1)


class DocumentLine(BaseModel):
    line_id: str
    page: int = Field(ge=1)
    text: str
    bbox: BoundingBox | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    source: Literal["text_layer", "ocr", "plain_text"] = "plain_text"


class DocumentLayout(BaseModel):
    """Coordinate-aware document text. LLMs may cite IDs but never set bboxes."""

    lines: list[DocumentLine] = Field(default_factory=list)
    page_count: int = Field(default=1, ge=1)
    coordinate_system: Literal["normalized_page", "unavailable"] = "unavailable"


class Layer1Requirement(BaseModel):
    field: str
    requirement: str
    status: Literal["present", "missing", "ambiguous", "not_applicable"]
    document_evidence_ids: list[str] = Field(default_factory=list)
    legal_reference_ids: list[str] = Field(default_factory=list)
    legal_evidence: str | None = Field(default=None, max_length=500)
    confidence: float = Field(ge=0, le=1)
    legal_support_score: float | None = Field(default=None, ge=0, le=1)
    document_presence_score: float | None = Field(default=None, ge=0, le=1)
    coordinate_confidence: float | None = Field(default=None, ge=0, le=1)


class Layer1Audit(BaseModel):
    """RAG-grounded result of the second Layer-1 LLM."""

    document_type: str
    operational_category: str | None = None
    requirements: list[Layer1Requirement] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    format_violations: list[str] = Field(default_factory=list)
    important_results: list[str] = Field(default_factory=list)
    accepted_reference_ids: list[str] = Field(default_factory=list)
    validation_warnings: list[str] = Field(default_factory=list)
    requires_human_review: bool = False


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


class RetrievalChannelContribution(BaseModel):
    """Observable contribution of one ranked retrieval channel."""

    channel: str = Field(min_length=1)
    rank: int = Field(ge=1)
    raw_score: float
    rrf_contribution: float = Field(gt=0)


class SearchHit(BaseModel):
    chunk: LegislationChunk
    score: float
    matched_terms: list[str] = Field(default_factory=list)
    expansion_matched_terms: list[str] = Field(default_factory=list)
    fusion_method: str | None = None
    channel_contributions: list[RetrievalChannelContribution] = Field(
        default_factory=list
    )
    relevance_score: float | None = Field(default=None, ge=0, le=1)
    relevance_accepted: bool | None = None
    relevance_reasons: list[str] = Field(default_factory=list)
    relevance_profile: str | None = None
    relevance_basis: str | None = None


class RetrievalDiagnostics(BaseModel):
    """Persistable retrieval health information for one process run."""

    mode: str = "bm25"
    dense_status: str = "not_requested"
    fallback_used: bool = False
    warning: str | None = None
    dense_error_type: str | None = None
    lexical_candidate_count: int = Field(default=0, ge=0)
    dense_candidate_count: int = Field(default=0, ge=0)
    fused_candidate_count: int = Field(default=0, ge=0)
    channel_top_n: int | None = Field(default=None, ge=1)
    rrf_k: int | None = Field(default=None, ge=0)
    relevance_strategy: str = "not_applied"
    relevance_profile: str | None = None
    relevance_candidate_top_k: int | None = Field(default=None, ge=1)
    relevance_candidate_count: int = Field(default=0, ge=0)
    relevance_accepted_count: int = Field(default=0, ge=0)
    relevance_rejected_count: int = Field(default=0, ge=0)
    relevance_threshold: float | None = Field(default=None, ge=0, le=1)
    relevance_abstained: bool = False
    relevance_query_expansion: list[str] = Field(default_factory=list)
    relevance_query_supported: bool | None = None
    relevance_query_score: float | None = Field(default=None, ge=0, le=1)
    relevance_query_concepts: list[str] = Field(default_factory=list)
    relevance_query_reasons: list[str] = Field(default_factory=list)
    relevance_query_evidence_basis: str | None = None


class GraphDecisionTrace(BaseModel):
    """Auditable, non-authoritative evidence-graph advice for one run."""

    strategy: str = "not_applied"
    graph_id: str | None = None
    applied: bool = False
    matched_rule_ids: list[str] = Field(default_factory=list)
    candidate_template_ids: list[str] = Field(default_factory=list)
    candidate_unit_ids: list[str] = Field(default_factory=list)
    required_fields: list[str] = Field(default_factory=list)
    paths: list[list[str]] = Field(default_factory=list)
    evidence_record_ids: list[str] = Field(default_factory=list)
    legal_reliance_allowed: bool = False
    warning: str | None = None


class LLMStepTrace(BaseModel):
    """Persistable outcome of a guarded LLM role invocation."""

    role: str
    status: str
    provider: str | None = None
    model: str | None = None
    detail: str | None = None
    data_classification: str | None = None
    external_data_allowed: bool = False
    local_execution: bool = False
    network_attempted: bool = False
    redacted: bool = False
    redaction_count: int = Field(default=0, ge=0)
    failure_code: str | None = None
    retryable: bool = False
    confidence: float | None = Field(default=None, ge=0, le=1)
    candidate_document_type: str | None = None
    candidate_summary: str | None = Field(default=None, max_length=500)
    selected_template_id: str | None = None
    selected_unit_id: str | None = None
    accepted_reference_ids: list[str] = Field(default_factory=list)
    human_review_required: bool = False
    decision_applied: bool | None = None
    decision_summary: str | None = Field(default=None, max_length=1200)
    decision_checks: list["LLMDecisionCheck"] = Field(default_factory=list)
    findings: list["LLMFindingTrace"] = Field(default_factory=list)
    repair_attempted: bool = False
    repair_succeeded: bool = False
    repair_status: str | None = None
    repair_detail: str | None = Field(default=None, max_length=500)


class LLMDecisionCheck(BaseModel):
    """One explicit server-side gate used to accept or reject an LLM proposal."""

    name: str = Field(max_length=120)
    passed: bool
    detail: str = Field(max_length=500)
    observed_score: float | None = Field(default=None, ge=0, le=1)
    required_score: float | None = Field(default=None, ge=0, le=1)


class LLMFindingTrace(BaseModel):
    """Auditable finding summary; never a hidden chain-of-thought transcript."""

    kind: Literal[
        "classification",
        "fact",
        "requirement",
        "result",
        "validation_warning",
    ]
    label: str = Field(max_length=160)
    finding: str = Field(max_length=700)
    confidence: float | None = Field(default=None, ge=0, le=1)
    score_basis: Literal[
        "agent_overall_confidence",
        "finding_confidence",
        "server_validation",
    ]
    status: Literal["accepted", "rejected", "informational"]
    document_evidence_ids: list[str] = Field(default_factory=list)
    legal_reference_ids: list[str] = Field(default_factory=list)
    legal_evidence: str | None = Field(default=None, max_length=500)
    legal_support_score: float | None = Field(default=None, ge=0, le=1)
    document_presence_score: float | None = Field(default=None, ge=0, le=1)
    coordinate_confidence: float | None = Field(default=None, ge=0, le=1)


class LLMRunTrace(BaseModel):
    """Run-level disclosure for optional external LLM assistance."""

    mode: str = "disabled"
    enabled: bool = False
    provider: str | None = None
    model: str | None = None
    used: bool = False
    deterministic_fallback_used: bool = True
    external_data_allowed: bool = False
    local_execution: bool = False
    steps: list[LLMStepTrace] = Field(default_factory=list)
    warning: str | None = None


class VerifiedReference(BaseModel):
    """A retrieval/provenance decision and its legal-reliance disclosure.

    ``verified`` means that the reference passed the applicable source contract
    and retrieval evidence checks.  It does not, by itself, promise that a
    source is current law; callers must also inspect the explicit disclosure
    fields below.
    """

    chunk_id: str
    document_id: str | None = None
    title: str
    article: str | None = None
    paragraph: str | None = None
    clause: str | None = None
    source: str
    page: int | None = None
    page_end: int | None = None
    source_url: str | None = None
    source_kind: str = "unknown"
    corpus_mode: str = "unknown"
    currentness_verified: bool = False
    legal_reliance_allowed: bool = False
    usage_notice: str | None = None
    domain: str = "unknown"
    excerpt: str
    score: float
    verified: bool
    verification_note: str
    evidence_channels: list[str] = Field(default_factory=list)
    channel_contributions: list[RetrievalChannelContribution] = Field(
        default_factory=list
    )
    relevance_score: float | None = Field(default=None, ge=0, le=1)
    relevance_accepted: bool | None = None
    relevance_reasons: list[str] = Field(default_factory=list)
    relevance_profile: str | None = None
    relevance_basis: str | None = None


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
    routing_status: Literal["proposed", "needs_review"] = "proposed"
    requires_human_review: bool = False
    evidence: list[str] = Field(default_factory=list)
    decision_basis: list[str] = Field(default_factory=list)
    organization_version: str | None = None
    target_level: str | None = None
    score_margin: float | None = Field(default=None, ge=0, le=1)


class UnitRecord(BaseModel):
    unit_id: str
    unit_name: str
    hierarchy: str
    responsibilities: list[str]
    keywords: list[str]
    parent_id: str | None = None
    unit_type: str = "unit"
    active_from: str | None = None
    accepts_external_documents: bool = True
    profile_status: str = "synthetic_draft"
    jurisdictions: list[str] = Field(default_factory=list)


class ResponseStrategyOption(BaseModel):
    """Taslak yazılmadan önce kullanıcıya sunulan kaynak-bağlı yanıt duruşu."""

    option_id: str = Field(min_length=1, max_length=40)
    label: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=600)
    reference_ids: list[str] = Field(default_factory=list)


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
    interest: list[str] = Field(default_factory=list)
    attachments: list[str] = Field(default_factory=list)
    distribution: list[str] = Field(default_factory=list)
    contact_information: list[str] = Field(default_factory=list)
    initials: list[str] = Field(default_factory=list)
    electronic_signature: ExtractedField = Field(
        default_factory=lambda: ExtractedField(
            value=None, status=FieldStatus.USER_REQUIRED
        )
    )
    document_metadata: dict[str, str] = Field(default_factory=dict)
    authority_relation: str = "unknown"
    closing: str = ""
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
    applied_rule_ids: list[str] = Field(default_factory=list)
    rule_source_id: str | None = None


class Layer3DraftOutput(BaseModel):
    target: Literal["citizen", "internal_unit"]
    label: str
    template_id: str
    draft: DraftPayload
    artifact: ArtifactResult
    compliance: ComplianceResult


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
    document_layout: DocumentLayout | None = None
    analysis: DocumentAnalysis | None = None
    layer1_audit: Layer1Audit | None = None
    # Katman-2 kendi kapalı sözleşmesini bağımsız modülde doğrular. API modeli
    # burada yalnız serileştirilmiş, geriye uyumlu sonucu taşır.
    layer2_assessment: dict[str, Any] | None = None
    search_hits: list[SearchHit] = Field(default_factory=list)
    retrieval_diagnostics: RetrievalDiagnostics | None = None
    graph_decision_trace: GraphDecisionTrace | None = None
    llm_trace: LLMRunTrace | None = None
    verified_references: list[VerifiedReference] = Field(default_factory=list)
    template_decision: TemplateDecision | None = None
    routing: RoutingRecommendation | None = None
    response_strategy_options: list[ResponseStrategyOption] = Field(
        default_factory=list
    )
    selected_delivery_target: Literal["citizen", "internal_unit", "both"] | None = None
    selected_response_strategy: ResponseStrategyOption | None = None
    selected_response_custom_text: str | None = None
    layer3_outputs: list[Layer3DraftOutput] = Field(default_factory=list)
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


class ResponseStrategyRequest(BaseModel):
    option_id: str | None = Field(default=None, max_length=40)
    custom_text: str | None = Field(default=None, max_length=4000)
    delivery_target: Literal["citizen", "internal_unit", "both"] = "citizen"
    compile_pdf: bool = False
