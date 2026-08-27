from __future__ import annotations

from pathlib import Path

import pytest

from karayol_agent.agents.llm_layer1 import (
    DocumentTypeCatalog,
    DocumentTypeEntry,
    LayoutGapCandidate,
    LLMClassificationAgent,
    LLMRequiredDataAgent,
)
from karayol_agent.llm import (
    DataClassification,
    LLMCallResult,
    LLMConfig,
    LLMProviderName,
    LLMStatus,
    LLMTask,
)
from karayol_agent.schemas import ClassificationResult, VerifiedReference


def _catalog() -> DocumentTypeCatalog:
    return DocumentTypeCatalog(
        [
            DocumentTypeEntry(
                type_id="talep",
                display_name="Talep",
                definition="Bir işlemin yapılmasını isteyen başvuru.",
                example_phrases=("talep ediyorum",),
            ),
            DocumentTypeEntry(
                type_id="sikayet",
                display_name="Şikâyet",
                definition="Bir mağduriyetin bildirildiği başvuru.",
                example_phrases=("şikayet", "mağduriyet"),
            ),
        ]
    )


def _reference(
    chunk_id: str = "MEV-0001",
    *,
    verified: bool = True,
) -> VerifiedReference:
    return VerifiedReference(
        chunk_id=chunk_id,
        title="Karayolları Trafik Yönetmeliği",
        article="12",
        source="mevzuat/karayollari-trafik-yonetmeligi.txt",
        excerpt="Başvuru sahibi kimlik belgesi sunmak zorundadır.",
        score=0.8,
        verified=verified,
        verification_note="test",
    )


class _FakeGateway:
    def __init__(self, output: dict | None, *, succeeded: bool = True) -> None:
        self.config = LLMConfig(
            provider=LLMProviderName.GROQ,
            model="test-model",
            api_key="k",
            base_url="https://api.groq.com/openai/v1",
        )
        self.output = output
        self.succeeded = succeeded
        self.requests: list = []

    def invoke(self, request):
        self.requests.append(request)
        if not self.succeeded:
            return LLMCallResult(
                status=LLMStatus.PROVIDER_ERROR,
                provider=self.config.provider,
                model=self.config.model,
            )
        return LLMCallResult(
            status=LLMStatus.SUCCESS,
            provider=self.config.provider,
            model=self.config.model,
            output=self.output,
            network_attempted=True,
        )


def test_document_type_catalog_rejects_empty_and_duplicate_entries() -> None:
    with pytest.raises(ValueError):
        DocumentTypeCatalog([])
    with pytest.raises(ValueError):
        DocumentTypeCatalog(
            [
                DocumentTypeEntry("a", "A", "..."),
                DocumentTypeEntry("a", "A2", "..."),
            ]
        )


def test_document_type_catalog_loads_the_real_placeholder_catalog() -> None:
    catalog_path = (
        Path(__file__).resolve().parents[1]
        / "data"
        / "document_types"
        / "document_type_catalog.json"
    )
    catalog = DocumentTypeCatalog.load(catalog_path)
    assert "genel_basvuru" in catalog.type_ids
    assert len(catalog.type_ids) == len(set(catalog.type_ids))


def test_document_type_catalog_ranks_by_lexical_overlap() -> None:
    catalog = _catalog()
    ranked = catalog.ranked_for("Bu bir şikayet ve mağduriyet dilekçesidir.")
    assert ranked[0].type_id == "sikayet"


def test_llm_classification_agent_builds_closed_enum_schema_and_maps_output() -> None:
    gateway = _FakeGateway(
        {
            "document_type": "talep",
            "confidence": 0.8,
            "evidence_span": "talep ediyorum",
        }
    )
    agent = LLMClassificationAgent(gateway, _catalog())
    deterministic = ClassificationResult(document_type="talep", confidence=0.5)

    outcome = agent.run(
        text="Yol bakımı talep ediyorum.",
        deterministic_classification=deterministic,
        data_classification=DataClassification.SYNTHETIC,
    )

    assert outcome.call.succeeded
    assert outcome.document_type == "talep"
    assert outcome.confidence == 0.8
    assert outcome.evidence_span == "talep ediyorum"
    request = gateway.requests[0]
    assert request.task is LLMTask.CLASSIFICATION
    assert request.output_schema["properties"]["document_type"]["enum"] == [
        "talep",
        "sikayet",
    ]


def test_llm_classification_agent_returns_none_fields_on_failure() -> None:
    gateway = _FakeGateway(None, succeeded=False)
    agent = LLMClassificationAgent(gateway, _catalog())
    deterministic = ClassificationResult(document_type="talep", confidence=0.5)

    outcome = agent.run(
        text="metin",
        deterministic_classification=deterministic,
        data_classification=DataClassification.RESTRICTED,
    )

    assert not outcome.call.succeeded
    assert outcome.document_type is None


def test_llm_required_data_agent_drops_unverified_evidence_reference() -> None:
    gateway = _FakeGateway(
        {
            "missing_data_points": [
                {
                    "description": "Kimlik fotokopisi",
                    "evidence_chunk_id": "MEV-0001",
                    "layout_candidate_id": None,
                },
                {
                    "description": "Uydurma gereklilik",
                    "evidence_chunk_id": "MEV-UYDURMA",
                    "layout_candidate_id": None,
                },
            ],
            "confidence": 0.7,
        }
    )
    agent = LLMRequiredDataAgent(gateway)

    outcome = agent.run(
        text="metin",
        document_type="talep",
        static_missing_fields=[],
        requirement_references=[_reference("MEV-0001", verified=True)],
        data_classification=DataClassification.SYNTHETIC,
    )

    assert outcome.missing_data_points == ("Kimlik fotokopisi",)


def test_llm_required_data_agent_drops_unknown_layout_candidate() -> None:
    gateway = _FakeGateway(
        {
            "missing_data_points": [
                {
                    "description": "İmza",
                    "evidence_chunk_id": None,
                    "layout_candidate_id": "layout-1-1",
                },
                {
                    "description": "Bilinmeyen aday",
                    "evidence_chunk_id": None,
                    "layout_candidate_id": "layout-does-not-exist",
                },
            ],
            "confidence": 0.6,
        }
    )
    agent = LLMRequiredDataAgent(gateway)
    candidate = LayoutGapCandidate(
        candidate_id="layout-1-1",
        nearby_label="İmza:",
        region_description="Sayfa 1, 'İmza:' etiketinin sağında içerik yok.",
    )

    outcome = agent.run(
        text="metin",
        document_type="talep",
        static_missing_fields=[],
        requirement_references=[],
        layout_gap_candidates=[candidate],
        data_classification=DataClassification.SYNTHETIC,
    )

    assert outcome.missing_data_points == ("İmza",)


def test_llm_required_data_agent_deduplicates_descriptions() -> None:
    gateway = _FakeGateway(
        {
            "missing_data_points": [
                {
                    "description": "İmza",
                    "evidence_chunk_id": None,
                    "layout_candidate_id": None,
                },
                {
                    "description": "İmza",
                    "evidence_chunk_id": None,
                    "layout_candidate_id": None,
                },
            ],
            "confidence": 0.6,
        }
    )
    agent = LLMRequiredDataAgent(gateway)

    outcome = agent.run(
        text="metin",
        document_type="talep",
        static_missing_fields=[],
        requirement_references=[],
        data_classification=DataClassification.SYNTHETIC,
    )

    assert outcome.missing_data_points == ("İmza",)
