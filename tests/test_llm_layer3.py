from __future__ import annotations

from pathlib import Path

import pytest

from karayol_agent.agents.llm_layer3 import (
    CUSTOM_RESPONSE_STRATEGY_OPTION_ID,
    LLMResponseStrategyAgent,
    LLMRoutingAgent,
    LLMTemplateFillAgent,
    LLMTemplateSelectionAgent,
    TemplateCatalog,
    TemplateCatalogEntry,
)
from karayol_agent.llm import (
    DataClassification,
    LLMCallResult,
    LLMConfig,
    LLMProviderName,
    LLMStatus,
    LLMTask,
)
from karayol_agent.schemas import (
    DocumentAnalysis,
    RoutingRecommendation,
    TemplateDecision,
    UnitRecord,
    VerifiedReference,
)


def _analysis(**overrides) -> DocumentAnalysis:
    base = dict(
        document_type="yol_bakim_talebi",
        general_document_type="talep",
        confidence=0.9,
        summary="Yol bakım talebi.",
        fields={},
        missing_fields=[],
        keywords=[],
    )
    base.update(overrides)
    return DocumentAnalysis(**base)


def _catalog() -> TemplateCatalog:
    return TemplateCatalog(
        [
            TemplateCatalogEntry(
                template_id="ust_yazi_v1",
                display_name="Üst Yazı",
                when_to_use="Kurum içi bildirim.",
            ),
            TemplateCatalogEntry(
                template_id="cevap_yazisi_v1",
                display_name="Cevap Yazısı",
                when_to_use="Dış başvuruya yanıt.",
            ),
        ]
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


def test_template_catalog_loads_the_real_catalog() -> None:
    catalog_path = Path(__file__).resolve().parents[1] / "templates" / "catalog.json"
    catalog = TemplateCatalog.load(catalog_path)
    ids = {entry.template_id for entry in catalog.entries}
    assert ids == {
        "ust_yazi_v1",
        "cevap_yazisi_v1",
        "bilgilendirme_yazisi_v1",
        "eksik_bilgi_talebi_v1",
    }


def test_llm_template_selection_agent_restricts_enum_to_allowed_ids() -> None:
    gateway = _FakeGateway(
        {
            "selected_template_id": "ust_yazi_v1",
            "confidence": 0.9,
            "rationale": "İçerik kurum içi bildirim niteliğinde.",
            "requires_human_review": False,
        }
    )
    agent = LLMTemplateSelectionAgent(gateway, _catalog())
    decision = TemplateDecision(
        document_type="ust_yazi",
        template_id="ust_yazi_v1",
        rationale="deterministik",
        confidence=0.7,
    )

    outcome = agent.run(
        analysis=_analysis(),
        deterministic_decision=decision,
        verified_references=[],
        allowed_template_ids=["ust_yazi_v1"],
        data_classification=DataClassification.SYNTHETIC,
    )

    assert outcome.selected_template_id == "ust_yazi_v1"
    request = gateway.requests[0]
    assert request.task is LLMTask.TEMPLATE_SELECTION
    assert request.output_schema["properties"]["selected_template_id"]["enum"] == [
        "ust_yazi_v1"
    ]
    # Only the allowed candidate's metadata should reach the prompt.
    assert [c["template_id"] for c in request.input_data["candidate_templates"]] == [
        "ust_yazi_v1"
    ]


def test_llm_template_selection_agent_requires_non_empty_allow_list() -> None:
    agent = LLMTemplateSelectionAgent(_FakeGateway(None), _catalog())
    with pytest.raises(ValueError):
        agent.run(
            analysis=_analysis(),
            deterministic_decision=TemplateDecision(
                document_type="x", template_id="x", rationale="", confidence=0.5
            ),
            verified_references=[],
            allowed_template_ids=[],
            data_classification=DataClassification.SYNTHETIC,
        )


def test_llm_template_fill_agent_constrains_closing_to_authority_relation() -> None:
    gateway = _FakeGateway(
        {
            "subject": "Yol bakım talebi",
            "paragraphs": ["Başvurunuz incelenmiştir.", "Gereğini rica ederim."],
            "closing": "Gereğini rica ederim.",
        }
    )
    agent = LLMTemplateFillAgent(gateway)

    outcome = agent.run(
        analysis=_analysis(),
        template_id="ust_yazi_v1",
        template_tex_reference="\\documentclass{article}",
        authority_relation="subordinate_internal",
        verified_references=[],
        response_strategy=None,
        response_custom_text="Kabul et.",
        data_classification=DataClassification.SYNTHETIC,
    )

    assert outcome.subject == "Yol bakım talebi"
    assert outcome.closing == "Gereğini rica ederim."
    request = gateway.requests[0]
    assert request.task is LLMTask.DRAFT_FIELDS
    assert request.output_schema["properties"]["closing"]["enum"] == [
        "Rica ederim.",
        "Gereğini rica ederim.",
    ]


def test_llm_template_fill_agent_omits_closing_for_unknown_authority_relation() -> None:
    gateway = _FakeGateway(
        {
            "subject": "Konu",
            "paragraphs": ["Metin."],
        }
    )
    agent = LLMTemplateFillAgent(gateway)

    outcome = agent.run(
        analysis=_analysis(),
        template_id="ust_yazi_v1",
        template_tex_reference="",
        authority_relation="unknown",
        verified_references=[],
        response_strategy=None,
        response_custom_text=None,
        data_classification=DataClassification.SYNTHETIC,
    )

    assert outcome.subject == "Konu"
    request = gateway.requests[0]
    assert "closing" not in request.output_schema["properties"]


def test_llm_routing_agent_reasons_over_unit_hierarchy() -> None:
    gateway = _FakeGateway(
        {
            "selected_unit_id": "ORKGM-YB-001",
            "traversal_path": ["Genel Müdürlük", "Yol Bakım Dairesi"],
            "confidence": 0.9,
            "rationale": "Sorumluluk alanı eşleşti.",
            "requires_human_review": False,
        }
    )
    agent = LLMRoutingAgent(gateway)
    units = [
        UnitRecord(
            unit_id="ORKGM-YB-001",
            unit_name="Yol Bakım Dairesi",
            hierarchy="Genel Müdürlük > Yol Bakım Dairesi",
            responsibilities=["yol bakımı"],
            keywords=["yol bakım"],
            parent_id=None,
        )
    ]

    outcome = agent.run(
        analysis=_analysis(),
        units=units,
        deterministic_routing=RoutingRecommendation(
            unit_id="ORKGM-YB-001",
            unit_name="Yol Bakım Dairesi",
            hierarchy="Genel Müdürlük > Yol Bakım Dairesi",
            rationale="deterministik",
            score=0.7,
        ),
        allowed_unit_ids=["ORKGM-YB-001"],
        data_classification=DataClassification.SYNTHETIC,
    )

    assert outcome.selected_unit_id == "ORKGM-YB-001"
    assert outcome.traversal_path == ("Genel Müdürlük", "Yol Bakım Dairesi")
    assert outcome.requires_human_review is False


def test_llm_routing_agent_defaults_to_review_required_on_failure() -> None:
    agent = LLMRoutingAgent(_FakeGateway(None, succeeded=False))
    units = [
        UnitRecord(
            unit_id="U1",
            unit_name="Birim",
            hierarchy="Birim",
            responsibilities=[],
            keywords=[],
        )
    ]

    outcome = agent.run(
        analysis=_analysis(),
        units=units,
        deterministic_routing=RoutingRecommendation(
            unit_id="U1", unit_name="Birim", hierarchy="Birim", rationale="x", score=0.5
        ),
        allowed_unit_ids=["U1"],
        data_classification=DataClassification.SYNTHETIC,
    )

    assert outcome.selected_unit_id is None
    assert outcome.requires_human_review is True


def test_llm_response_strategy_agent_appends_no_custom_option_itself() -> None:
    gateway = _FakeGateway(
        {
            "options": [
                {"option_id": "kabul", "label": "Kabul", "description": "..."},
                {"option_id": "red", "label": "Red", "description": "..."},
            ]
        }
    )
    agent = LLMResponseStrategyAgent(gateway)

    outcome = agent.run(
        analysis=_analysis(),
        verified_references=[],
        data_classification=DataClassification.SYNTHETIC,
    )

    option_ids = [option.option_id for option in outcome.options]
    assert option_ids == ["kabul", "red"]
    assert CUSTOM_RESPONSE_STRATEGY_OPTION_ID not in option_ids


def test_llm_response_strategy_agent_strips_llm_authored_custom_option() -> None:
    gateway = _FakeGateway(
        {
            "options": [
                {"option_id": "kabul", "label": "Kabul", "description": "..."},
                {
                    "option_id": CUSTOM_RESPONSE_STRATEGY_OPTION_ID,
                    "label": "Kendim yazarım",
                    "description": "...",
                },
            ]
        }
    )
    agent = LLMResponseStrategyAgent(gateway)

    outcome = agent.run(
        analysis=_analysis(),
        verified_references=[],
        data_classification=DataClassification.SYNTHETIC,
    )

    assert [option.option_id for option in outcome.options] == ["kabul"]


def test_llm_response_strategy_agent_falls_back_on_failure() -> None:
    agent = LLMResponseStrategyAgent(_FakeGateway(None, succeeded=False))

    outcome = agent.run(
        analysis=_analysis(),
        verified_references=[],
        data_classification=DataClassification.RESTRICTED,
    )

    assert len(outcome.options) >= 2
