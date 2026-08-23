from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from karayol_agent.schemas import utc_now


class GoldRecord(BaseModel):
    record_id: str
    text: str = Field(min_length=1)
    expected_document_type: str
    expected_unit_id: str
    expected_missing_fields: list[str] = Field(default_factory=list)
    expected_reference_chunk_ids: list[str] = Field(default_factory=list)
    expected_template_id: str
    tags: list[str] = Field(default_factory=list)


class GoldDataset(BaseModel):
    dataset_name: str
    version: str
    usage: str
    data: list[GoldRecord] = Field(min_length=1)


class EvaluationMetric(BaseModel):
    value: float = Field(ge=0, le=1)
    numerator: int
    denominator: int


class EvaluationRecordResult(BaseModel):
    record_id: str
    tags: list[str] = Field(default_factory=list)
    expected_document_type: str
    actual_document_type: str
    expected_unit_id: str
    actual_unit_id: str
    actual_top3_unit_ids: list[str]
    expected_missing_fields: list[str]
    actual_missing_fields: list[str]
    expected_template_id: str
    actual_template_id: str
    retrieved_chunk_ids: list[str]
    classification_correct: bool
    routing_top1_correct: bool
    routing_top3_correct: bool
    missing_fields_exact: bool
    template_correct: bool
    retrieval_hit: bool | None = None


class EvaluationReport(BaseModel):
    schema_version: str = "1.0"
    generated_at: datetime = Field(default_factory=utc_now)
    dataset_name: str
    dataset_version: str
    total_records: int
    successful_records: int
    metrics: dict[str, EvaluationMetric]
    slices: dict[str, dict[str, EvaluationMetric]] = Field(default_factory=dict)
    missing_field_precision: float = Field(ge=0, le=1)
    missing_field_recall: float = Field(ge=0, le=1)
    missing_field_f1: float = Field(ge=0, le=1)
    retrieval_mrr: float = Field(ge=0, le=1)
    classification_confusion: dict[str, dict[str, int]]
    results: list[EvaluationRecordResult]
