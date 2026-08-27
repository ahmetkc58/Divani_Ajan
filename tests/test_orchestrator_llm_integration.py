from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

from karayol_agent.config import Settings
from karayol_agent.llm import (
    DataClassification,
    LLMCallResult,
    LLMConfig,
    LLMFailure,
    LLMProviderName,
    LLMStatus,
    LLMTask,
    StructuredLLMGateway,
)
from karayol_agent.orchestrator import EvrakOrchestrator


ROOT = Path(__file__).resolve().parents[1]

# Present verbatim in data/synthetic_gold.json's first record; used as LLM1's
# evidence_span so the classification agent's evidence-verbatim guard passes.
_GOLD_RECORD_0_EVIDENCE = (
    "Yol bakım ve onarım çalışması yapılmasını talep ediyorum."
)


class FakeSuccessfulGateway:
    """Configurable fake covering all 7 LLMTask branches of the new pipeline."""

    def __init__(
        self,
        *,
        classification_document_type: str = "talep",
        classification_confidence: float = 0.9,
        classification_evidence: str | None = _GOLD_RECORD_0_EVIDENCE,
        required_data_missing_points: list[dict] | None = None,
        required_data_confidence: float = 0.9,
        adjudication_confidence: float = 0.91,
        adjudication_requires_human_review: bool = False,
        adjudication_unsupported_claims: list[str] | None = None,
        adjudication_accepted_reference_ids: list[str] | None = None,
        template_selection_id: str = "ust_yazi_v1",
        template_selection_confidence: float = 0.91,
        template_selection_requires_human_review: bool = False,
        routing_unit_id: str = "ORKGM-YB-001",
        routing_confidence: float = 0.91,
        routing_requires_human_review: bool = False,
        response_strategy_options: list[dict] | None = None,
        draft_fields_subject: str = "Yol bakım talebi değerlendirmesi",
        draft_fields_paragraphs: list[str] | None = None,
        draft_fields_closing: str | None = None,
        understanding_fields: dict[str, dict[str, str | None]] | None = None,
    ) -> None:
        self.config = LLMConfig(
            provider=LLMProviderName.GROQ,
            model="openai/gpt-oss-120b",
            api_key="unit-test-key",
            base_url="https://api.groq.com/openai/v1",
        )
        self.requests: list = []
        self.classification_document_type = classification_document_type
        self.classification_confidence = classification_confidence
        self.classification_evidence = classification_evidence
        self.required_data_missing_points = required_data_missing_points or []
        self.required_data_confidence = required_data_confidence
        self.adjudication_confidence = adjudication_confidence
        self.adjudication_requires_human_review = adjudication_requires_human_review
        self.adjudication_unsupported_claims = adjudication_unsupported_claims or []
        self.adjudication_accepted_reference_ids = adjudication_accepted_reference_ids
        self.template_selection_id = template_selection_id
        self.template_selection_confidence = template_selection_confidence
        self.template_selection_requires_human_review = (
            template_selection_requires_human_review
        )
        self.routing_unit_id = routing_unit_id
        self.routing_confidence = routing_confidence
        self.routing_requires_human_review = routing_requires_human_review
        self.response_strategy_options = response_strategy_options or [
            {
                "option_id": "kabul",
                "label": "Kabul ve gereğini yerine getir",
                "description": "Başvuru kabul edilir ve gereği yerine getirilir.",
            },
            {
                "option_id": "ek_bilgi",
                "label": "Ek bilgi talep et",
                "description": "Başvurandan ek bilgi istenir.",
            },
        ]
        self.draft_fields_subject = draft_fields_subject
        self.draft_fields_paragraphs = draft_fields_paragraphs or [
            "Başvurunuz incelenmiştir.",
            "Gereği yerine getirilecektir.",
        ]
        self.draft_fields_closing = draft_fields_closing
        # Deprecated alias kept for tests that still reach into per-field LLM2
        # output; unused by the current EXTRACTION (LLM2) schema.
        self.understanding_fields = understanding_fields or {}

    def invoke(self, request):
        self.requests.append(request)
        if request.task is LLMTask.CLASSIFICATION:
            output = {
                "document_type": self.classification_document_type,
                "confidence": self.classification_confidence,
                "evidence_span": self.classification_evidence,
            }
        elif request.task is LLMTask.EXTRACTION:
            output = {
                "missing_data_points": self.required_data_missing_points,
                "confidence": self.required_data_confidence,
            }
        elif request.task is LLMTask.ADJUDICATION:
            verified_ids = list(request.input_data["auditor_verified_reference_ids"])
            accepted = (
                verified_ids
                if self.adjudication_accepted_reference_ids is None
                else self.adjudication_accepted_reference_ids
            )
            output = {
                "accepted_reference_ids": accepted,
                "confidence": self.adjudication_confidence,
                "rationale": "Doğrulanmış sentetik kural ve graf yolu tutarlı.",
                "requires_human_review": self.adjudication_requires_human_review,
                "unsupported_claims": self.adjudication_unsupported_claims,
            }
        elif request.task is LLMTask.TEMPLATE_SELECTION:
            output = {
                "selected_template_id": self.template_selection_id,
                "confidence": self.template_selection_confidence,
                "rationale": "Yazı türü içerikle tutarlı.",
                "requires_human_review": self.template_selection_requires_human_review,
            }
        elif request.task is LLMTask.ROUTING:
            output = {
                "selected_unit_id": self.routing_unit_id,
                "traversal_path": [self.routing_unit_id],
                "confidence": self.routing_confidence,
                "rationale": "Sorumluluk alanı eşleşti.",
                "requires_human_review": self.routing_requires_human_review,
            }
        elif request.task is LLMTask.SUMMARY:
            output = {"options": self.response_strategy_options}
        else:
            assert request.task is LLMTask.DRAFT_FIELDS
            output = {
                "subject": self.draft_fields_subject,
                "paragraphs": self.draft_fields_paragraphs,
            }
            if self.draft_fields_closing is not None:
                output["closing"] = self.draft_fields_closing
        return LLMCallResult(
            status=LLMStatus.SUCCESS,
            provider=self.config.provider,
            model=self.config.model,
            output=output,
            network_attempted=True,
        )


class NoNetworkTransport:
    def send(self, _request):
        raise AssertionError("Kısıtlı evrak için ağ çağrısı yapılmamalıydı.")


class EmptyRetriever:
    retrieval_mode = "bm25"

    def search(self, _query: str, top_k: int = 5):
        return []


class PolicyAwareFakeGateway(FakeSuccessfulGateway):
    def invoke(self, request):
        if request.data_classification is DataClassification.RESTRICTED:
            self.requests.append(request)
            return LLMCallResult(
                status=LLMStatus.POLICY_REJECTED,
                provider=LLMProviderName.GROQ,
                model=self.config.model,
                failure=LLMFailure(
                    code="external_data_policy_rejected",
                    message="Kısıtlı veri ağdan önce reddedildi.",
                ),
            )
        return super().invoke(request)


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        project_root=ROOT,
        data_dir=ROOT / "data",
        templates_dir=ROOT / "templates",
        output_dir=tmp_path / "output",
        runtime_dir=tmp_path / "runtime",
    )


_EXPECTED_TASK_SEQUENCE = [
    LLMTask.CLASSIFICATION,
    LLMTask.EXTRACTION,
    LLMTask.ADJUDICATION,
    LLMTask.TEMPLATE_SELECTION,
    LLMTask.ROUTING,
    LLMTask.SUMMARY,
]


def test_synthetic_fixture_runs_structured_llm_and_graph_adjudication(
    tmp_path: Path,
) -> None:
    gateway = FakeSuccessfulGateway()
    orchestrator = EvrakOrchestrator(_settings(tmp_path), llm_gateway=gateway)
    dataset = json.loads((ROOT / "data" / "synthetic_gold.json").read_text("utf-8"))

    state = orchestrator.process_text(dataset["data"][0]["text"])

    assert [request.task for request in gateway.requests] == _EXPECTED_TASK_SEQUENCE
    assert all(
        request.data_classification is DataClassification.SYNTHETIC
        for request in gateway.requests
    )
    assert state.llm_trace is not None
    assert state.llm_trace.used is True
    assert [step.status for step in state.llm_trace.steps] == ["success"] * len(
        _EXPECTED_TASK_SEQUENCE
    )
    assert state.analysis is not None
    assert not state.analysis.missing_fields
    assert state.analysis.general_document_type == "talep"
    assert state.graph_decision_trace is not None
    assert state.graph_decision_trace.applied is True
    assert state.template_decision is not None
    assert state.template_decision.template_id == "ust_yazi_v1"
    assert state.routing is not None
    assert state.routing.unit_id == "ORKGM-YB-001"
    # LLM6 proposed options but the user hasn't chosen one yet; LLM4 must not
    # have run. WAITING_FOR_INFO still takes priority on a first pass because
    # DraftingAgent always seeds sayı/imzalayan/unvan as missing regardless of
    # content completeness — the response-strategy prompt only takes over once
    # those bureaucratic fields are filled (see test below).
    assert state.response_strategy_options
    assert state.selected_response_strategy is None
    assert state.status.value == "eksik_bilgi_bekleniyor"


def test_choosing_response_strategy_runs_llm4_and_completes_draft(
    tmp_path: Path,
) -> None:
    gateway = FakeSuccessfulGateway()
    orchestrator = EvrakOrchestrator(_settings(tmp_path), llm_gateway=gateway)
    dataset = json.loads((ROOT / "data" / "synthetic_gold.json").read_text("utf-8"))

    state = orchestrator.process_text(dataset["data"][0]["text"])
    assert state.response_strategy_options
    chosen_option = state.response_strategy_options[0]

    state = orchestrator.choose_response_strategy(
        state.document_id, option_id=chosen_option.option_id
    )

    # Re-entry via choose_response_strategy() skips CLASSIFICATION/EXTRACTION
    # (analysis is already computed) and skips SUMMARY a second time (options
    # are already set), but now runs DRAFT_FIELDS since a strategy is chosen.
    assert [request.task for request in gateway.requests] == [
        *_EXPECTED_TASK_SEQUENCE,
        LLMTask.ADJUDICATION,
        LLMTask.TEMPLATE_SELECTION,
        LLMTask.ROUTING,
        LLMTask.DRAFT_FIELDS,
    ]
    assert state.selected_response_strategy == chosen_option
    assert state.draft is not None
    assert state.draft.subject.value == "Yol bakım talebi değerlendirmesi"
    assert state.draft.paragraphs == [
        "Başvurunuz incelenmiştir.",
        "Gereği yerine getirilecektir.",
    ]


def test_custom_response_strategy_text_is_accepted(tmp_path: Path) -> None:
    gateway = FakeSuccessfulGateway()
    orchestrator = EvrakOrchestrator(_settings(tmp_path), llm_gateway=gateway)
    dataset = json.loads((ROOT / "data" / "synthetic_gold.json").read_text("utf-8"))
    state = orchestrator.process_text(dataset["data"][0]["text"])

    state = orchestrator.choose_response_strategy(
        state.document_id,
        option_id="custom",
        custom_text="Talebi kısmen kabul ederek yanıt ver.",
    )

    assert state.selected_response_strategy is None
    assert state.selected_response_custom_text == "Talebi kısmen kabul ederek yanıt ver."
    assert state.draft is not None


def test_real_document_is_rejected_before_external_network_and_falls_back(
    tmp_path: Path,
) -> None:
    gateway = StructuredLLMGateway(
        LLMConfig(
            provider=LLMProviderName.GEMINI,
            model="gemini-2.5-flash",
            api_key="unit-test-key",
            base_url="https://generativelanguage.googleapis.com/v1beta",
        ),
        transport=NoNetworkTransport(),
    )
    orchestrator = EvrakOrchestrator(_settings(tmp_path), llm_gateway=gateway)

    state = orchestrator.process_text(
        "Gönderen: Gerçek Kişi\nKonu: Yol çukuru\nKonum: Ankara\n"
        "Yol bakım çalışması yapılmasını talep ediyorum."
    )

    assert state.llm_trace is not None
    assert state.llm_trace.used is False
    assert state.llm_trace.deterministic_fallback_used is True
    assert state.llm_trace.external_data_allowed is False
    assert {step.status for step in state.llm_trace.steps} == {"policy_rejected"}
    assert "gönderilmedi" in (state.llm_trace.warning or "")
    assert state.analysis is not None
    assert state.analysis.fields["gonderen"].value == "Gerçek Kişi"


def test_real_document_can_use_local_ollama_without_external_data_permission(
    tmp_path: Path,
) -> None:
    gateway = FakeSuccessfulGateway()
    gateway.config = LLMConfig()
    orchestrator = EvrakOrchestrator(_settings(tmp_path), llm_gateway=gateway)

    state = orchestrator.process_text(
        "Gönderen: Yerel Kullanıcı\nKonu: Yol çukuru\nKonum: Ankara\n"
        "Yol bakım çalışması yapılmasını talep ediyorum."
    )

    assert state.llm_trace is not None
    assert state.llm_trace.mode == "guarded_structured_local"
    assert state.llm_trace.local_execution is True
    assert state.llm_trace.external_data_allowed is False
    assert "cihaz dışına gönderilmez" in (state.llm_trace.warning or "")
    assert state.llm_trace.steps
    assert all(step.local_execution for step in state.llm_trace.steps)
    assert all(step.status == "success" for step in state.llm_trace.steps)


def test_adjudicator_evidence_synthesis_not_applied_when_review_is_required(
    tmp_path: Path,
) -> None:
    gateway = FakeSuccessfulGateway(
        adjudication_confidence=0.20,
        adjudication_requires_human_review=True,
        adjudication_unsupported_claims=["Kanıtlanmamış aday"],
    )
    orchestrator = EvrakOrchestrator(_settings(tmp_path), llm_gateway=gateway)
    dataset = json.loads((ROOT / "data" / "synthetic_gold.json").read_text("utf-8"))

    state = orchestrator.process_text(dataset["data"][0]["text"])

    assert state.llm_trace is not None
    adjudicator_step = next(
        step for step in state.llm_trace.steps if step.role == "adjudicator"
    )
    assert adjudicator_step.decision_applied is False
    assert adjudicator_step.human_review_required is True
    assert state.llm_trace.deterministic_fallback_used is True
    # A low-confidence Adjudicator no longer forces template/routing review by
    # itself — those are now independently gated by LLM3/LLM5 (deliberate
    # decoupling, see docs/plan for rationale).
    assert state.template_decision is not None
    assert state.template_decision.template_id == "ust_yazi_v1"


def test_template_selection_independent_of_adjudicator_outcome(
    tmp_path: Path,
) -> None:
    """LLM3 can still apply confidently even when the Adjudicator abstains."""

    gateway = FakeSuccessfulGateway(
        adjudication_confidence=0.20,
        adjudication_requires_human_review=True,
        template_selection_id="cevap_yazisi_v1",
        template_selection_confidence=0.95,
    )
    orchestrator = EvrakOrchestrator(_settings(tmp_path), llm_gateway=gateway)
    dataset = json.loads((ROOT / "data" / "synthetic_gold.json").read_text("utf-8"))

    state = orchestrator.process_text(dataset["data"][0]["text"])

    assert state.template_decision is not None
    # cevap_yazisi_v1 is not a template TemplateSelectionAgent would pick for
    # this document_type nor a listed alternative/graph candidate, so it must
    # fall outside the allow-list and therefore NOT be applied even though
    # LLM3 itself reported high confidence.
    assert state.template_decision.template_id == "ust_yazi_v1"
    assert state.template_decision.user_approval_required is True


def test_below_threshold_template_selection_is_traced_as_local_fallback(
    tmp_path: Path,
) -> None:
    gateway = FakeSuccessfulGateway(template_selection_confidence=0.79)
    orchestrator = EvrakOrchestrator(_settings(tmp_path), llm_gateway=gateway)
    dataset = json.loads((ROOT / "data" / "synthetic_gold.json").read_text("utf-8"))

    state = orchestrator.process_text(dataset["data"][0]["text"])

    assert state.llm_trace is not None
    template_step = next(
        step
        for step in state.llm_trace.steps
        if step.role == "llm3_template_selection"
    )
    assert template_step.decision_applied is False
    assert template_step.human_review_required is True
    assert state.template_decision is not None
    assert state.template_decision.user_approval_required is True


def test_below_threshold_routing_is_traced_as_local_fallback(tmp_path: Path) -> None:
    gateway = FakeSuccessfulGateway(routing_confidence=0.5)
    orchestrator = EvrakOrchestrator(_settings(tmp_path), llm_gateway=gateway)
    dataset = json.loads((ROOT / "data" / "synthetic_gold.json").read_text("utf-8"))

    state = orchestrator.process_text(dataset["data"][0]["text"])

    assert state.llm_trace is not None
    routing_step = next(
        step for step in state.llm_trace.steps if step.role == "llm5_routing"
    )
    assert routing_step.decision_applied is False
    assert routing_step.human_review_required is True
    assert state.routing is not None
    assert "uygulanmadı" in state.routing.rationale


def test_llm1_classification_ignored_without_verbatim_evidence(
    tmp_path: Path,
) -> None:
    gateway = FakeSuccessfulGateway(
        classification_document_type="sikayet",
        classification_evidence="bu metinde hiç geçmeyen bir kanıt cümlesi",
    )
    orchestrator = EvrakOrchestrator(_settings(tmp_path), llm_gateway=gateway)
    dataset = json.loads((ROOT / "data" / "synthetic_gold.json").read_text("utf-8"))

    state = orchestrator.process_text(dataset["data"][0]["text"])

    assert state.analysis is not None
    # Unsupported candidate must not overwrite the deterministic general type.
    assert state.analysis.general_document_type != "sikayet"


def test_llm2_required_data_merges_into_missing_fields(tmp_path: Path) -> None:
    gateway = FakeSuccessfulGateway(
        required_data_missing_points=[
            {
                "description": "İkametgah belgesi fotokopisi",
                "evidence_chunk_id": None,
                "layout_candidate_id": None,
            }
        ]
    )
    orchestrator = EvrakOrchestrator(_settings(tmp_path), llm_gateway=gateway)
    dataset = json.loads((ROOT / "data" / "synthetic_gold.json").read_text("utf-8"))

    state = orchestrator.process_text(dataset["data"][0]["text"])

    assert state.analysis is not None
    assert "İkametgah belgesi fotokopisi" in state.analysis.missing_fields
    # A non-empty analysis.missing_fields must block LLM6 from proposing
    # response-strategy options on this pass.
    assert state.response_strategy_options == []


def test_adjudicator_cannot_apply_without_verified_evidence(tmp_path: Path) -> None:
    gateway = FakeSuccessfulGateway(adjudication_accepted_reference_ids=[])
    orchestrator = EvrakOrchestrator(
        _settings(tmp_path),
        retriever=EmptyRetriever(),
        llm_gateway=gateway,
    )
    dataset = json.loads((ROOT / "data" / "synthetic_gold.json").read_text("utf-8"))

    state = orchestrator.process_text(dataset["data"][0]["text"])

    # Text-fingerprint classification (LLM1/LLM2) is unaffected by retrieval,
    # so it stays SYNTHETIC for this pinned fixture; but the adjudication
    # stage additionally requires non-empty verified evidence before it may
    # trust the SYNTHETIC/PUBLIC classification, so it falls back to
    # RESTRICTED once EmptyRetriever yields nothing to verify.
    assert gateway.requests[0].task is LLMTask.CLASSIFICATION
    assert gateway.requests[0].data_classification is DataClassification.SYNTHETIC
    adjudication_request = next(
        request for request in gateway.requests if request.task is LLMTask.ADJUDICATION
    )
    assert adjudication_request.data_classification is DataClassification.RESTRICTED
    assert state.verified_references == []
    assert state.llm_trace is not None
    adjudicator_step = next(
        step for step in state.llm_trace.steps if step.role == "adjudicator"
    )
    assert adjudicator_step.decision_applied is False


def test_template_and_routing_cannot_override_graph_candidates(
    tmp_path: Path,
) -> None:
    gateway = FakeSuccessfulGateway(
        template_selection_id="cevap_yazisi_v1",
        routing_unit_id="ORKGM-EB-001",
    )
    orchestrator = EvrakOrchestrator(_settings(tmp_path), llm_gateway=gateway)
    dataset = json.loads((ROOT / "data" / "synthetic_gold.json").read_text("utf-8"))

    state = orchestrator.process_text(dataset["data"][0]["text"])

    assert state.graph_decision_trace is not None
    assert state.graph_decision_trace.applied is True
    assert state.template_decision is not None
    assert state.template_decision.template_id == "ust_yazi_v1"
    assert state.routing is not None
    assert state.routing.unit_id == "ORKGM-YB-001"
    assert "uygulanmadı" in state.routing.rationale


def test_snapshot_adjudication_uses_public_metadata_only_for_attested_synthetic_doc(
    tmp_path: Path,
) -> None:
    gateway = PolicyAwareFakeGateway()
    app_settings = Settings(
        project_root=ROOT,
        data_dir=ROOT / "data",
        templates_dir=ROOT / "templates",
        output_dir=tmp_path / "output",
        runtime_dir=tmp_path / "runtime",
        retrieval_mode="bm25",
        corpus_mode="competition_snapshot",
        competition_snapshot_path=(
            ROOT / "data" / "processed" / "competition_snapshot.json"
        ),
    )
    orchestrator = EvrakOrchestrator(app_settings, llm_gateway=gateway)
    dataset = json.loads((ROOT / "data" / "synthetic_gold.json").read_text("utf-8"))

    state = orchestrator.process_text(dataset["data"][0]["text"])

    classifications = [request.data_classification for request in gateway.requests]
    assert classifications[0] is DataClassification.SYNTHETIC
    assert classifications[1] is DataClassification.SYNTHETIC
    adjudication_requests = [
        request
        for request in gateway.requests
        if request.task is LLMTask.ADJUDICATION
    ]
    assert adjudication_requests
    assert adjudication_requests[0].data_classification is DataClassification.PUBLIC
    candidates = adjudication_requests[0].input_data["researcher_candidates"]
    assert candidates
    assert all(
        set(candidate) == {
            "chunk_id",
            "title",
            "article",
            "page",
            "verified",
            "currentness_verified",
            "legal_reliance_allowed",
        }
        for candidate in candidates
    )
    assert all(candidate["currentness_verified"] is False for candidate in candidates)
    assert all(candidate["legal_reliance_allowed"] is False for candidate in candidates)
    serialized_request = json.dumps(
        adjudication_requests[0].input_data,
        ensure_ascii=False,
        sort_keys=True,
    )
    assert all(
        reference.excerpt not in serialized_request
        for reference in state.verified_references
        if reference.verified
    )
    assert state.llm_trace is not None
    adjudicator_step = next(
        step for step in state.llm_trace.steps if step.role == "adjudicator"
    )
    assert adjudicator_step.status == "success"
    assert state.llm_trace.external_data_allowed is True


def test_trusted_ui_fixture_enables_llm_without_trusting_arbitrary_text(
    tmp_path: Path,
) -> None:
    gateway = PolicyAwareFakeGateway(
        adjudication_accepted_reference_ids=["MEV-B4102E4DDE97752F"],
    )
    app_settings = Settings(
        project_root=ROOT,
        data_dir=ROOT / "data",
        templates_dir=ROOT / "templates",
        output_dir=tmp_path / "output",
        runtime_dir=tmp_path / "runtime",
        retrieval_mode="bm25",
        corpus_mode="competition_snapshot",
        competition_snapshot_path=(
            ROOT / "data" / "processed" / "competition_snapshot.json"
        ),
    )
    orchestrator = EvrakOrchestrator(app_settings, llm_gateway=gateway)
    demo_dataset = json.loads(
        (ROOT / "data" / "synthetic_ui_fixtures.json").read_text("utf-8")
    )
    demo_text = demo_dataset["records"][0]["text"]

    state = orchestrator.process_text(demo_text)

    classifications = [request.data_classification for request in gateway.requests]
    assert classifications[0] is DataClassification.SYNTHETIC
    assert classifications[1] is DataClassification.SYNTHETIC
    assert state.llm_trace is not None
    assert state.llm_trace.enabled is True
    assert state.llm_trace.used is True
    assert all(step.network_attempted for step in state.llm_trace.steps)

    arbitrary_text = demo_text + "\nBu satır kullanıcı tarafından eklendi."
    assert (
        orchestrator._llm_data_classification(arbitrary_text)
        is DataClassification.RESTRICTED
    )


def test_synthetic_llm_fixture_files_are_bound_to_pinned_hashes(tmp_path: Path) -> None:
    orchestrator = EvrakOrchestrator(
        _settings(tmp_path),
        llm_gateway=PolicyAwareFakeGateway(),
    )

    assert sha256((ROOT / "data" / "synthetic_gold.json").read_bytes()).hexdigest() == (
        orchestrator.SYNTHETIC_GOLD_SHA256
    )
    assert sha256(
        (ROOT / "data" / "synthetic_ui_fixtures.json").read_bytes()
    ).hexdigest() == orchestrator.SYNTHETIC_UI_FIXTURES_SHA256
