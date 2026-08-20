from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class JobStatus(StrEnum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class DecisionLevel(StrEnum):
    high = "high"
    medium = "medium"
    low = "low"


class ModelInfo(BaseModel):
    name: str
    size: int | None = None
    digest: str | None = None
    modified_at: str | None = None


class ModelSelection(BaseModel):
    chat_model: str = Field(min_length=1)
    embedding_model: str = Field(min_length=1)


class ModelSettingsResponse(BaseModel):
    ollama_reachable: bool
    available_models: list[ModelInfo]
    selected: ModelSelection | None
    index_ready: bool
    index_reason: str | None = None


class JobResponse(BaseModel):
    id: str
    job_type: str
    document_id: str | None
    status: JobStatus
    progress: int
    stage: str
    error: str | None
    result_id: str | None
    created_at: str
    updated_at: str


class UploadResponse(BaseModel):
    document_id: str
    job_id: str


class DocumentResponse(BaseModel):
    id: str
    filename: str
    mime_type: str
    sha256: str
    page_count: int
    extraction_method: str | None
    original_text: str | None
    corrected_text: str | None
    text_quality: float
    status: str
    created_at: str
    updated_at: str


class CorrectTextRequest(BaseModel):
    text: str = Field(min_length=1, max_length=200_000)


class ExtractedField(BaseModel):
    name: str
    value: str | None = None
    source_span: str | None = None
    status: Literal["present", "missing", "uncertain"] = "present"


class AnalysisCore(BaseModel):
    document_type: str
    topic: str
    summary: str
    extracted_fields: list[ExtractedField]
    evidence: list[str] = []
    warnings: list[str] = []


class RegulationEvidence(BaseModel):
    source_id: str
    title: str
    article: str | None = None
    page: int | None = None
    quote: str
    retrieval_score: float
    verified: bool


class RouteCandidate(BaseModel):
    unit_id: str
    unit_name: str
    score: float
    rationale: str


class DocumentTypeDecision(BaseModel):
    label: str
    decision_level: DecisionLevel
    evidence: list[str]


class RoutingDecision(BaseModel):
    recommended_unit_id: str
    alternatives: list[RouteCandidate]
    rationale: str
    decision_level: DecisionLevel


class DocumentAnalysisV1(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    id: str
    document_id: str
    document_type: DocumentTypeDecision
    topic: str
    summary: str
    extracted_fields: list[ExtractedField]
    missing_fields: list[str]
    regulations: list[RegulationEvidence]
    routing: RoutingDecision
    warnings: list[str]
    requires_human_review: bool = True
    model_name: str
    prompt_version: str
    created_at: str


class DraftCreateRequest(BaseModel):
    unit_id: str | None = None


class DraftCore(BaseModel):
    letter_type: Literal["ust_yazi", "cevap_yazisi", "bilgilendirme", "eksik_bilgi_talebi"]
    subject: str
    body: str
    references: list[str] = []
    attachments: list[str] = []
    distribution: list[str] = []


class DraftValidation(BaseModel):
    rule_id: str
    label: str
    status: Literal["pass", "warning", "error"]
    message: str


class DraftV1(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    id: str
    analysis_id: str
    document_id: str
    institution_name: str = "Örnekşehir Belediyesi"
    recipient_unit_id: str
    recipient_unit_name: str
    letter_type: str
    number: str = "SENTETIK-0000"
    date: str
    subject: str
    body: str
    references: list[str]
    signatory: str = "SENTETİK YETKİLİ"
    attachments: list[str]
    distribution: list[str]
    validations: list[DraftValidation]
    status: Literal["draft", "approved"] = "draft"
    version: int = 1
    model_name: str
    created_at: str
    updated_at: str


class DraftUpdateRequest(BaseModel):
    subject: str | None = Field(default=None, min_length=1, max_length=500)
    body: str | None = Field(default=None, min_length=1, max_length=50_000)
    references: list[str] | None = None
    attachments: list[str] | None = None
    distribution: list[str] | None = None

    @field_validator("references", "attachments", "distribution")
    @classmethod
    def limit_list(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and len(value) > 30:
            raise ValueError("En fazla 30 kayıt eklenebilir.")
        return value


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    database: bool
    ollama: bool
    models_selected: bool
    index_ready: bool
    details: dict[str, Any]


class AuditEventResponse(BaseModel):
    id: int
    document_id: str
    event_type: str
    payload: dict[str, Any]
    created_at: str
