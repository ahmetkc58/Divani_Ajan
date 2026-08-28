from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from karayol_agent.documents.layout import plain_text_layout
from karayol_agent.layer2_legal_reasoning import Layer2LegalReasoning
from karayol_agent.llm.contracts import (
    DataClassification,
    FallbackAction,
    LLMCallResult,
    LLMProviderName,
    LLMStatus,
)
from karayol_agent.retrieval.requirement_rules import RequirementRuleRepository
from karayol_agent.schemas import (
    DocumentAnalysis,
    ExtractedField,
    FieldStatus,
    VerifiedReference,
)


ROOT = Path(__file__).resolve().parents[1]


class SequenceGateway:
    def __init__(self, outputs: list[dict]) -> None:
        self.outputs = list(outputs)
        self.requests = []
        self.config = SimpleNamespace(model="llm-large")

    def invoke(self, request):
        self.requests.append(request)
        output = self.outputs.pop(0)
        return LLMCallResult(
            status=LLMStatus.SUCCESS,
            provider=LLMProviderName.OPENAI_COMPATIBLE,
            model="llm-large",
            output=output,
            fallback_action=FallbackAction.NONE,
            network_attempted=True,
        )


TEXT = """GEÇİŞ YOLU ÖN İZİN BAŞVURUSU
Konu: Akaryakıt istasyonu için karayolu geçiş yolu ön izni
Belediye ve mücavir alan sınırları dışında kalan taşınmazım için geçiş yolu
ön izni verilmesini arz ederim. Herhangi bir ek belge sunulmamıştır.
"""


def _analysis() -> DocumentAnalysis:
    return DocumentAnalysis(
        document_type="izin",
        general_document_type="izin",
        document_subtype="karayolu geçiş yolu ön izni",
        operational_category="gecis_yolu_on_izin",
        confidence=0.95,
        summary="Geçiş yolu ön izin başvurusu.",
        retrieval_evidence_text=TEXT,
        fields={
            "konu": ExtractedField(
                value="Akaryakıt istasyonu için karayolu geçiş yolu ön izni",
                status=FieldStatus.FROM_SOURCE,
            )
        },
    )


LEGAL_ID = "LAW-GECIS-IZIN"
LEGAL_QUOTE = "Karayoluna bağlantı sağlayacak geçiş yolları için izin alınması zorunludur."


def _legal_reference() -> VerifiedReference:
    return VerifiedReference(
        chunk_id=LEGAL_ID,
        document_id="LAW-1",
        title="Karayolu Geçiş Yolları Yönetmeliği",
        article="Madde 8",
        source="Resmî kaynak",
        excerpt=LEGAL_QUOTE,
        score=1.0,
        verified=True,
        verification_note="Testte doğrulanmış resmî kaynak.",
        currentness_verified=True,
        legal_reliance_allowed=True,
    )


def _outputs() -> list[dict]:
    subject_line = "page-1-line-2"
    return [
        {
            "knowledge_gaps": ["Geçiş yolu talebinin izin rejimi"],
            "tool_calls": [
                {"tool": "search_curated_rules", "query": "biçim kontrolü", "reference_ids": [], "line_ids": []},
                {"tool": "finish_research", "query": "", "reference_ids": [], "line_ids": []},
            ],
        },
        {
            "refined_documents": [
                {"reference_id": LEGAL_ID, "focused_quote": LEGAL_QUOTE, "scope_note": "Geçiş yolu talebine doğrudan uygulanır", "document_evidence_ids": [subject_line], "keep": True},
            ]
        },
        {
            "audits": [
                {"reference_id": LEGAL_ID, "applicability": "applicable", "legal_relationship": "creates_obligation", "legal_quote": LEGAL_QUOTE, "applicability_evidence_ids": [subject_line], "issue": "Geçiş yolu için izin yükümlülüğü", "document_statement": "Başvuran karayoluna bağlanan geçiş yolu için ön izin istemektedir.", "legal_analysis": "Talep, hükümdeki karayoluna bağlantı sağlayan geçiş yolu kapsamındadır.", "practical_effect": "Geçiş yolu izin sürecine tabidir.", "risk_level": "medium", "confidence": 0.98},
            ]
        },
        {
            "summary": "Belgedeki geçiş yolu talebi izin yükümlülüğüyle ilişkilendirilmiştir.",
            "findings": [
                {"reference_id": LEGAL_ID, "applicability": "applicable", "legal_relationship": "creates_obligation", "issue": "Geçiş yolu için izin yükümlülüğü", "document_statement": "Başvuran geçiş yolu ön izni istemektedir.", "legal_assessment": "Belgedeki talep, kaynak hükmündeki izin rejimiyle doğrudan ilişkilidir.", "practical_effect": "Talep izin prosedürü kapsamında değerlendirilmelidir.", "risk_level": "medium", "document_evidence_ids": [subject_line], "confidence": 0.98},
            ],
            "important_results": ["Talep geçiş yolu izin rejimine tabidir."],
            "requires_human_review": True,
        },
    ]


def test_layer2_uses_large_model_and_only_source_grounded_findings() -> None:
    gateway = SequenceGateway(_outputs())
    layer = Layer2LegalReasoning(
        gateway,
        RequirementRuleRepository(ROOT / "data" / "legal_requirements" / "catalog.json"),
        max_search_rounds=1,
    )

    result = layer.run(
        analysis=_analysis(),
        text=TEXT,
        layout=plain_text_layout(TEXT),
        references=[_legal_reference()],
        data_classification=DataClassification.SYNTHETIC,
    )

    assert result.status == "completed"
    assert result.model == "llm-large"
    assert [finding.issue for finding in result.findings] == [
        "Geçiş yolu için izin yükümlülüğü"
    ]
    assert result.findings[0].legal_relationship == "creates_obligation"
    assert not hasattr(result.findings[0], "status")
    assert result.tool_trace[0].executed_tool == "search_reliable_legislation"
    assert all(finding.source_only_validated for finding in result.findings)
    assert all(step.model == "llm-large" for step in result.agent_trace)
    assert all("bbox" not in line for line in gateway.requests[2].input_data["document_lines"])


def test_layer2_abstains_without_legally_reliable_sources(tmp_path: Path) -> None:
    gateway = SequenceGateway([])
    layer = Layer2LegalReasoning(
        gateway,
        RequirementRuleRepository(tmp_path / "missing.json"),
    )

    result = layer.run(
        analysis=_analysis(),
        text=TEXT,
        layout=plain_text_layout(TEXT),
        references=[],
        data_classification=DataClassification.SYNTHETIC,
    )

    assert result.status == "abstained"
    assert result.findings == []
    assert "önbilgisi" in result.validation_warnings[0]
    assert gateway.requests == []


def test_layer2_exposes_retrieved_context_when_auditor_cannot_decide() -> None:
    outputs = _outputs()
    outputs[2] = {"audits": []}
    outputs[3] = {
        "summary": "",
        "findings": [],
        "important_results": [],
        "requires_human_review": True,
    }
    gateway = SequenceGateway(outputs)
    layer = Layer2LegalReasoning(
        gateway,
        RequirementRuleRepository(ROOT / "data" / "legal_requirements" / "catalog.json"),
        max_search_rounds=1,
    )

    result = layer.run(
        analysis=_analysis(),
        text=TEXT,
        layout=plain_text_layout(TEXT),
        references=[_legal_reference()],
        data_classification=DataClassification.SYNTHETIC,
    )

    assert result.status == "completed"
    assert result.findings
    assert result.findings[0].applicability == "uncertain"
    assert result.findings[0].legal_relationship == "unclear"
    assert result.findings[0].legal_quote == LEGAL_QUOTE


def test_content_query_starts_after_spaced_subject_marker() -> None:
    # analysis.retrieval_evidence_text wins in normal operation; exercise the
    # spaced marker directly with a copy that does not carry cached evidence.
    analysis = _analysis().model_copy(update={"retrieval_evidence_text": ""})
    query = Layer2LegalReasoning._content_search_query(
        analysis,
        "Talep Sahibi: Kişi KONU : Kamulaştırma bedeli ve plan örneği talebidir.",
    )
    assert "Talep Sahibi" not in query
    assert "Kamulaştırma bedeli" in query


def test_issue_plan_requires_diverse_general_and_sector_queries() -> None:
    plan, errors = Layer2LegalReasoning._issue_plan(
        [
            {
                "issue": "Başvuru usulü",
                "query": "yetkili makama yazılı başvuru ve cevap usulü",
                "document_basis": "Başvurumun incelenmesini istiyorum.",
                "scope": "general_procedure",
            },
            {
                "issue": "Terminal dışı yolcu",
                "query": "şehirlerarası otobüs terminal dışında yolcu alma",
                "document_basis": "Otobüs terminal dışında yolcu aldı.",
                "scope": "sector_specific",
            },
            {
                "issue": "Sürüş süresi",
                "query": "otobüs sürücüsü sürüş ve dinlenme süreleri",
                "document_basis": "Sürücü yedi saat aralıksız araç kullandı.",
                "scope": "technical",
            },
        ]
    )

    assert errors == []
    assert [item["scope"] for item in plan] == [
        "general_procedure",
        "sector_specific",
        "technical",
    ]


def test_cross_corpus_copies_of_same_article_are_deduplicated() -> None:
    first = _legal_reference().model_copy(update={"chunk_id": "MEV-SAME"})
    second = _legal_reference().model_copy(update={"chunk_id": "leaf-same"})
    layer = Layer2LegalReasoning(
        SequenceGateway([]),
        RequirementRuleRepository(ROOT / "data" / "legal_requirements" / "catalog.json"),
    )
    candidates = layer._build_candidates([], [first, second])

    deduplicated, groups = layer._deduplicate_candidates(candidates)

    assert list(deduplicated) == ["MEV-SAME"]
    assert groups == {"MEV-SAME": ["MEV-SAME", "leaf-same"]}
