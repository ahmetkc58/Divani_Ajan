from __future__ import annotations

import json
from dataclasses import replace
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
from karayol_agent.schemas import BoundingBox, DocumentLayout, DocumentLine


ROOT = Path(__file__).resolve().parents[1]


class FakeSuccessfulGateway:
    def __init__(
        self,
        *,
        adjudication_confidence: float = 0.91,
        requires_human_review: bool = False,
        unsupported_claims: list[str] | None = None,
        understanding_document_type: str = "talep",
        understanding_operational_category: str = "yol_bakim_talebi",
        understanding_confidence: float = 0.93,
        selected_template_id: str = "ust_yazi_v1",
        selected_unit_id: str = "ORKGM-YB-001",
        accepted_reference_ids: list[str] | None = None,
        understanding_reference_ids: list[str] | None = None,
        understanding_fields: dict[str, dict[str, str | None]] | None = None,
        audit_field: str = "gonderen",
        audit_status: str = "present",
        audit_missing_fields: list[str] | None = None,
    ) -> None:
        self.config = LLMConfig(
            provider=LLMProviderName.GROQ,
            model="openai/gpt-oss-120b",
            api_key="unit-test-key",
            base_url="https://api.groq.com/openai/v1",
        )
        self.requests = []
        self.adjudication_confidence = adjudication_confidence
        self.requires_human_review = requires_human_review
        self.unsupported_claims = unsupported_claims or []
        self.understanding_document_type = understanding_document_type
        self.understanding_operational_category = understanding_operational_category
        self.understanding_confidence = understanding_confidence
        self.selected_template_id = selected_template_id
        self.selected_unit_id = selected_unit_id
        self.accepted_reference_ids = (
            ["SENT-KRY-001"]
            if accepted_reference_ids is None
            else accepted_reference_ids
        )
        self.understanding_reference_ids = understanding_reference_ids or []
        self.understanding_fields = understanding_fields or {}
        self.audit_field = audit_field
        self.audit_status = audit_status
        self.audit_missing_fields = audit_missing_fields or []

    def invoke(self, request):
        self.requests.append(request)
        if request.task is LLMTask.EXTRACTION:
            output = {
                "document_type": self.understanding_document_type,
                "confidence": self.understanding_confidence,
                "general_document_type": self.understanding_document_type,
                "document_subtype": "yol_bakim_talebi",
                "operational_category": self.understanding_operational_category,
                "important_facts": ["Yol yüzeyinde bakım ihtiyacı bildiriliyor."],
                "rag_reference_ids": self.understanding_reference_ids,
                "summary": "Yol yüzeyindeki bozulma için bakım talep edilmektedir.",
                "fields": {
                    "gonderen": {
                        "value": "Ayşe Örnek",
                        "evidence": "Gönderen: Ayşe Örnek",
                    },
                    "konu": {
                        "value": "Asfalt kaplama bozukluğu",
                        "evidence": "Konu: Asfalt kaplama bozukluğu",
                    },
                    "konum": {
                        "value": "Örnek İl, Merkez, D-100 yolu 12. kilometre",
                        "evidence": "Konum: Örnek İl, Merkez, D-100 yolu 12. kilometre",
                    },
                    "tarih": {
                        "value": "01.08.2026",
                        "evidence": "Tarih: 01.08.2026",
                    },
                    "talep": {
                        "value": "Yol bakım ve onarım çalışması yapılmasını talep ediyorum.",
                        "evidence": "Yol bakım ve onarım çalışması yapılmasını talep ediyorum.",
                    },
                    "eposta": {"value": None, "evidence": None},
                    "telefon": {"value": None, "evidence": None},
                    "muhatap": {"value": None, "evidence": None},
                },
            }
            for name, candidate in self.understanding_fields.items():
                output["fields"][name] = candidate
        else:
            assert request.task is LLMTask.ADJUDICATION
            catalog = request.input_data.get("requirement_catalog", [])
            matching_rule = next(
                (
                    item
                    for item in catalog
                    if item.get("legal_reference_id")
                    in self.accepted_reference_ids
                ),
                catalog[0] if catalog else None,
            )
            legal_evidence = (
                str(matching_rule["rule_text"])[:240]
                if matching_rule
                else "Doğrulanmış mevzuat dayanağı bulunamadı."
            )
            output = {
                "selected_template_id": self.selected_template_id,
                "selected_unit_id": self.selected_unit_id,
                "accepted_reference_ids": self.accepted_reference_ids,
                "confidence": self.adjudication_confidence,
                "rationale": "Doğrulanmış sentetik kural ve graf yolu tutarlı.",
                "requires_human_review": self.requires_human_review,
                "unsupported_claims": self.unsupported_claims,
                "requirements": (
                    [
                        {
                            "field": self.audit_field,
                            "requirement": "Gönderen bilgisi belgede bulunmalıdır.",
                            "status": self.audit_status,
                            "document_evidence_ids": (
                                ["page-1-line-1"]
                                if self.audit_status == "present"
                                else []
                            ),
                            "legal_reference_ids": self.accepted_reference_ids,
                            "legal_evidence": legal_evidence,
                            "confidence": 0.93,
                        }
                    ]
                    if self.accepted_reference_ids
                    else []
                ),
                "missing_fields": self.audit_missing_fields,
                "format_violations": [],
                "important_results": ["Gönderen alanı tespit edildi."],
            }
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


class RepairingGateway(FakeSuccessfulGateway):
    def invoke(self, request):
        result = super().invoke(request)
        if (
            request.task is LLMTask.ADJUDICATION
            and "repair_context" not in request.input_data
            and result.output is not None
        ):
            output = dict(result.output)
            output["requirements"] = [
                {
                    **dict(item),
                    "legal_reference_ids": [],
                    "legal_evidence": "",
                }
                for item in output["requirements"]
            ]
            return replace(result, output=output)
        return result


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        project_root=ROOT,
        data_dir=ROOT / "data",
        templates_dir=ROOT / "templates",
        output_dir=tmp_path / "output",
        runtime_dir=tmp_path / "runtime",
    )


def test_synthetic_fixture_runs_structured_llm_and_graph_adjudication(
    tmp_path: Path,
) -> None:
    gateway = FakeSuccessfulGateway()
    orchestrator = EvrakOrchestrator(_settings(tmp_path), llm_gateway=gateway)
    dataset = json.loads((ROOT / "data" / "synthetic_gold.json").read_text("utf-8"))

    state = orchestrator.process_text(dataset["data"][0]["text"])

    assert [request.task for request in gateway.requests] == [
        LLMTask.EXTRACTION,
        LLMTask.ADJUDICATION,
    ]
    assert gateway.requests[0].input_data["rag_candidates"]
    assert gateway.requests[0].input_data["document_type_candidates"]
    assert gateway.requests[0].output_schema["properties"]["document_type"]["enum"] == [
        "dilekce",
        "sikayet",
        "itiraz",
        "talep",
        "izin",
        "belge",
    ]
    assert gateway.requests[0].output_schema["properties"]["general_document_type"][
        "enum"
    ] == ["dilekce", "sikayet", "itiraz", "talep", "izin", "belge"]
    assert gateway.requests[0].input_data["document_lines"]
    assert gateway.requests[1].input_data["researcher_candidates"]
    assert gateway.requests[1].input_data["requirement_catalog"]
    assert gateway.requests[1].input_data["document_lines"]
    assert "bbox" in gateway.requests[1].input_data["document_lines"][0]
    assert "confidence" in gateway.requests[1].input_data["document_lines"][0]
    assert "source" in gateway.requests[1].input_data["document_lines"][0]
    assert all(
        request.data_classification is DataClassification.SYNTHETIC
        for request in gateway.requests
    )
    assert state.llm_trace is not None
    assert state.llm_trace.used is True
    assert state.llm_trace.deterministic_fallback_used is True
    assert [step.status for step in state.llm_trace.steps] == ["success", "success"]
    assert state.llm_trace.steps[-1].decision_applied is True
    assert state.llm_trace.steps[0].decision_applied is False
    assert state.llm_trace.steps[0].decision_summary is not None
    assert state.llm_trace.steps[0].decision_checks
    assert state.llm_trace.steps[0].findings[0].kind == "classification"
    assert state.llm_trace.steps[0].findings[0].confidence == 0.93
    assert state.llm_trace.steps[-1].decision_summary is not None
    assert state.llm_trace.steps[-1].decision_checks
    assert any(
        finding.kind == "requirement"
        and finding.confidence == 0.93
        and finding.legal_reference_ids == ["SENT-KRY-001"]
        for finding in state.llm_trace.steps[-1].findings
    )
    assert state.layer1_audit is not None
    assert state.layer1_audit.requirements[0].field == "gonderen"
    assert state.analysis is not None
    assert not state.analysis.summary.startswith("Yol yüzeyindeki")
    assert state.llm_trace.steps[0].candidate_summary is not None
    assert state.llm_trace.steps[0].candidate_summary.startswith("Yol yüzeyindeki")
    assert state.graph_decision_trace is not None
    assert state.graph_decision_trace.applied is True
    assert state.template_decision is not None
    assert state.template_decision.template_id == "ust_yazi_v1"
    assert state.routing is not None
    assert state.routing.unit_id == "ORKGM-YB-001"


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


def test_adjudicator_does_not_mutate_decisions_when_review_is_required(
    tmp_path: Path,
) -> None:
    gateway = FakeSuccessfulGateway(
        adjudication_confidence=0.20,
        requires_human_review=True,
        unsupported_claims=["Kanıtlanmamış aday"],
    )
    orchestrator = EvrakOrchestrator(_settings(tmp_path), llm_gateway=gateway)
    dataset = json.loads((ROOT / "data" / "synthetic_gold.json").read_text("utf-8"))

    state = orchestrator.process_text(dataset["data"][0]["text"])

    assert state.template_decision is not None
    assert state.template_decision.template_id == "ust_yazi_v1"
    assert state.template_decision.confidence != 0.20
    assert state.template_decision.user_approval_required is True
    assert state.routing is not None
    assert "uygulanmadı" in state.routing.rationale
    assert state.llm_trace is not None
    assert state.llm_trace.steps[-1].human_review_required is True
    assert state.llm_trace.steps[-1].decision_applied is False
    assert state.llm_trace.deterministic_fallback_used is True


def test_layer1_rag_missing_requirement_switches_to_information_request(
    tmp_path: Path,
) -> None:
    gateway = FakeSuccessfulGateway(
        selected_template_id="eksik_bilgi_talebi_v1",
        accepted_reference_ids=["REQ-3071-M4-IMZA"],
        audit_field="imza",
        audit_status="missing",
        audit_missing_fields=["imza"],
    )
    orchestrator = EvrakOrchestrator(_settings(tmp_path), llm_gateway=gateway)
    dataset = json.loads((ROOT / "data" / "synthetic_gold.json").read_text("utf-8"))

    state = orchestrator.process_text(dataset["data"][0]["text"])

    assert state.layer1_audit is not None
    assert "imza" in state.layer1_audit.missing_fields
    assert state.analysis is not None
    assert "imza" in state.analysis.missing_fields
    assert state.template_decision is not None
    assert state.template_decision.template_id == "eksik_bilgi_talebi_v1"


def test_adjudicator_repairs_invalid_requirement_grounding_once(
    tmp_path: Path,
) -> None:
    gateway = RepairingGateway()
    orchestrator = EvrakOrchestrator(_settings(tmp_path), llm_gateway=gateway)
    dataset = json.loads((ROOT / "data" / "synthetic_gold.json").read_text("utf-8"))

    state = orchestrator.process_text(dataset["data"][0]["text"])

    assert [request.task for request in gateway.requests] == [
        LLMTask.EXTRACTION,
        LLMTask.ADJUDICATION,
        LLMTask.ADJUDICATION,
    ]
    repair_request = gateway.requests[-1]
    assert repair_request.input_data["repair_context"]["server_validation_errors"]
    assert state.llm_trace is not None
    step = state.llm_trace.steps[-1]
    assert step.repair_attempted is True
    assert step.repair_succeeded is True
    assert step.repair_status == "success"
    assert state.layer1_audit is not None
    assert state.layer1_audit.validation_warnings == []
    requirement = state.layer1_audit.requirements[0]
    assert requirement.legal_evidence
    assert requirement.legal_support_score == 1.0
    assert requirement.document_presence_score == 1.0


def test_adjudicator_receives_coordinates_and_scores_ocr_evidence(
    tmp_path: Path,
) -> None:
    gateway = FakeSuccessfulGateway()
    orchestrator = EvrakOrchestrator(_settings(tmp_path), llm_gateway=gateway)
    dataset = json.loads((ROOT / "data" / "synthetic_gold.json").read_text("utf-8"))
    text = dataset["data"][0]["text"]
    layout = DocumentLayout(
        lines=[
            DocumentLine(
                line_id="page-1-line-1",
                page=1,
                text="Gönderen: Ayşe Örnek",
                bbox=BoundingBox(x0=0.1, y0=0.2, x1=0.6, y1=0.25),
                confidence=0.88,
                source="ocr",
            )
        ],
        page_count=1,
        coordinate_system="normalized_page",
    )

    state = orchestrator.process_text(text, document_layout=layout)

    line = gateway.requests[1].input_data["document_lines"][0]
    assert line["bbox"] == {"x0": 0.1, "y0": 0.2, "x1": 0.6, "y1": 0.25}
    assert line["confidence"] == 0.88
    assert line["source"] == "ocr"
    assert state.layer1_audit is not None
    requirement = state.layer1_audit.requirements[0]
    assert requirement.document_presence_score == 0.88
    assert requirement.coordinate_confidence == 0.88


def test_below_threshold_adjudication_is_traced_as_local_fallback(
    tmp_path: Path,
) -> None:
    gateway = FakeSuccessfulGateway(adjudication_confidence=0.79)
    orchestrator = EvrakOrchestrator(_settings(tmp_path), llm_gateway=gateway)
    dataset = json.loads((ROOT / "data" / "synthetic_gold.json").read_text("utf-8"))

    state = orchestrator.process_text(dataset["data"][0]["text"])

    assert state.llm_trace is not None
    assert state.llm_trace.used is True
    assert state.llm_trace.deterministic_fallback_used is True
    assert state.llm_trace.steps[-1].decision_applied is False
    assert state.llm_trace.steps[-1].human_review_required is True
    assert state.template_decision is not None
    assert state.template_decision.user_approval_required is True


def test_llm_field_merge_reuses_local_semantic_validators(tmp_path: Path) -> None:
    invalid_sender = "Yol bakımının yapılmasını talep ediyorum."
    text = (
        "Konu: Asfalt bozulması\n"
        "Konum: Ankara\n"
        "Tarih: 99.99.2026\n"
        f"{invalid_sender}"
    )
    gateway = FakeSuccessfulGateway(
        understanding_fields={
            "gonderen": {
                "value": invalid_sender,
                "evidence": invalid_sender,
            },
            "tarih": {
                "value": "99.99.2026",
                "evidence": "Tarih: 99.99.2026",
            },
        }
    )
    orchestrator = EvrakOrchestrator(_settings(tmp_path), llm_gateway=gateway)
    orchestrator.synthetic_document_fingerprints.add(
        orchestrator._text_fingerprint(text)
    )

    state = orchestrator.process_text(text)

    assert state.analysis is not None
    assert state.analysis.fields["gonderen"].value is None
    assert state.analysis.fields["tarih"].value is None
    assert "gonderen" in state.analysis.missing_fields


def test_document_type_candidate_is_advisory_without_source_evidence(
    tmp_path: Path,
) -> None:
    gateway = FakeSuccessfulGateway(
        understanding_document_type="sikayet",
        understanding_confidence=0.99,
    )
    orchestrator = EvrakOrchestrator(_settings(tmp_path), llm_gateway=gateway)
    dataset = json.loads((ROOT / "data" / "synthetic_gold.json").read_text("utf-8"))

    state = orchestrator.process_text(dataset["data"][0]["text"])

    assert state.analysis is not None
    assert state.analysis.document_type == "talep"
    assert state.llm_trace is not None
    assert state.llm_trace.steps[0].candidate_document_type == "sikayet"


def test_adjudicator_uses_curated_rules_when_broad_retrieval_is_empty(
    tmp_path: Path,
) -> None:
    gateway = FakeSuccessfulGateway(accepted_reference_ids=[])
    orchestrator = EvrakOrchestrator(
        _settings(tmp_path),
        retriever=EmptyRetriever(),
        llm_gateway=gateway,
    )
    dataset = json.loads((ROOT / "data" / "synthetic_gold.json").read_text("utf-8"))

    state = orchestrator.process_text(dataset["data"][0]["text"])

    assert gateway.requests[-1].data_classification is DataClassification.SYNTHETIC
    assert state.verified_references
    assert all(
        reference.source_kind == "curated_requirement_rule"
        for reference in state.verified_references
    )
    assert state.template_decision is not None
    assert state.template_decision.user_approval_required is True


def test_adjudicator_cannot_override_graph_candidates(
    tmp_path: Path,
) -> None:
    gateway = FakeSuccessfulGateway(
        selected_template_id="cevap_yazisi_v1",
        selected_unit_id="ORKGM-EB-001",
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


def test_unknown_adjudicator_reference_forces_review(tmp_path: Path) -> None:
    gateway = FakeSuccessfulGateway(
        accepted_reference_ids=["UYDURMA-CHUNK"],
    )
    orchestrator = EvrakOrchestrator(_settings(tmp_path), llm_gateway=gateway)
    dataset = json.loads((ROOT / "data" / "synthetic_gold.json").read_text("utf-8"))

    state = orchestrator.process_text(dataset["data"][0]["text"])

    assert state.template_decision is not None
    assert state.template_decision.user_approval_required is True
    assert state.llm_trace is not None
    assert state.llm_trace.steps[-1].human_review_required is True
    assert state.llm_trace.steps[-1].accepted_reference_ids == []
    assert state.routing is not None
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

    assert gateway.requests[0].data_classification is DataClassification.SYNTHETIC
    assert gateway.requests[1].data_classification is DataClassification.PUBLIC
    candidates = gateway.requests[1].input_data["researcher_candidates"]
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
            "excerpt",
        }
        for candidate in candidates
    )
    snapshot_candidates = [
        candidate for candidate in candidates if not candidate["chunk_id"].startswith("REQ-")
    ]
    curated_candidates = [
        candidate for candidate in candidates if candidate["chunk_id"].startswith("REQ-")
    ]
    assert snapshot_candidates
    assert curated_candidates
    assert all(
        candidate["currentness_verified"] is False
        for candidate in snapshot_candidates
    )
    assert all(
        candidate["legal_reliance_allowed"] is False
        for candidate in snapshot_candidates
    )
    assert all(
        candidate["currentness_verified"] is True
        for candidate in curated_candidates
    )
    assert all(candidate["excerpt"] for candidate in candidates)
    assert state.llm_trace is not None
    assert state.llm_trace.steps[-1].status == "success"
    assert state.llm_trace.external_data_allowed is True
    assert state.llm_trace.steps[-1].data_classification == "public"
    assert state.template_decision is not None
    assert state.template_decision.user_approval_required is True


def test_trusted_ui_fixture_enables_llm_without_trusting_arbitrary_text(
    tmp_path: Path,
) -> None:
    gateway = PolicyAwareFakeGateway(
        accepted_reference_ids=["MEV-B4102E4DDE97752F"],
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

    assert [request.data_classification for request in gateway.requests] == [
        DataClassification.SYNTHETIC,
        DataClassification.PUBLIC,
    ]
    assert state.llm_trace is not None
    assert state.llm_trace.enabled is True
    assert state.llm_trace.used is True
    assert [step.status for step in state.llm_trace.steps] == ["success", "success"]
    assert all(step.network_attempted for step in state.llm_trace.steps)
    assert state.llm_trace.steps[-1].decision_applied is True
    assert state.llm_trace.deterministic_fallback_used is True

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
