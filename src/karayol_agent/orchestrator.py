from __future__ import annotations

import json
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from karayol_agent.agents import (
    ClassificationAgent,
    ComplianceAgent,
    ContentAnalysisAgent,
    DraftingAgent,
    LegislationResearchAgent,
    RoutingAgent,
    SourceVerificationAgent,
    TemplateSelectionAgent,
)
from karayol_agent.agents.legislation import RankedRetriever
from karayol_agent.agents.llm_roles import (
    AdjudicationOutcome,
    LLMAdjudicatorAgent,
    LLMDocumentUnderstandingAgent,
    StructuredGateway,
    UnderstandingOutcome,
)
from karayol_agent.config import Settings, settings
from karayol_agent.documents import DocumentExtractor
from karayol_agent.graph import EvidenceGraphAdvisor, GraphBuildError
from karayol_agent.llm import DataClassification, LLMConfig, StructuredLLMGateway
from karayol_agent.latex import LatexRenderer
from karayol_agent.retrieval import (
    AnalysisAwareDeterministicReranker,
    AnalysisAwareTextRetrieverAdapter,
    BM25Index,
    LegislationRepository,
)
from karayol_agent.retrieval.contracts import (
    COMPETITION_SNAPSHOT_NOTICE,
    CorpusMode,
    competition_snapshot_chunk_blockers,
)
from karayol_agent.retrieval.hybrid import HybridRetriever
from karayol_agent.retrieval.qdrant_store import QdrantUnavailable, SchemaMismatch
from karayol_agent.retrieval.runtime import build_retrieval_runtime
from karayol_agent.schemas import (
    ExtractedField,
    FieldStatus,
    GraphDecisionTrace,
    LLMRunTrace,
    LLMStepTrace,
    ProcessState,
    ProcessStatus,
    RoutingRecommendation,
    TemplateDecision,
)
from karayol_agent.state_store import FileProcessStore
from karayol_agent.text_utils import normalize_for_search, normalize_whitespace


class ProcessNotFoundError(KeyError):
    pass


class ProcessValidationError(ValueError):
    pass


class EvrakOrchestrator:
    name = "Orkestratör"
    LLM_ADJUDICATION_MIN_CONFIDENCE = 0.80
    SYNTHETIC_GOLD_SHA256 = (
        "90d1206c4e150e6e3ba779c0e404005fcd258c96a960e02c2565913f2c8905e5"
    )
    SYNTHETIC_UI_FIXTURES_SHA256 = (
        "30e982e4b25b82be88c1c2526323d17adfa595db91de6ec518c40ed463dba15d"
    )

    DRAFT_FIELD_MAP = {
        "tarih": "date",
        "sayi": "number",
        "konu": "subject",
        "muhatap": "recipient",
        "imzalayan": "signer",
        "unvan": "signer_title",
    }

    def __init__(
        self,
        app_settings: Settings = settings,
        *,
        retriever: RankedRetriever | None = None,
        llm_gateway: StructuredGateway | None = None,
    ) -> None:
        self.settings = app_settings
        app_settings.ensure_runtime_dirs()
        if app_settings.corpus_mode == CorpusMode.COMPETITION_SNAPSHOT.value:
            chunks = LegislationRepository(
                app_settings.competition_snapshot_path,
                corpus_mode=CorpusMode.COMPETITION_SNAPSHOT,
            ).load()
        else:
            chunks = LegislationRepository(
                app_settings.data_dir / "synthetic_legislation.json",
                trusted_synthetic=True,
            ).load()
        self.index = BM25Index(chunks)
        self.retrieval_setup_warning: str | None = None
        self.graph_setup_warning: str | None = None
        self.retriever = (
            retriever if retriever is not None else self._build_retriever()
        )
        self.extractor = DocumentExtractor(
            max_chars=app_settings.max_text_chars,
            max_pdf_pages=app_settings.max_pdf_pages,
            max_ocr_pixels_per_page=app_settings.max_ocr_pixels_per_page,
            max_ocr_total_pixels=app_settings.max_ocr_total_pixels,
            ocr_document_timeout_seconds=app_settings.ocr_document_timeout_seconds,
            ocr_page_timeout_seconds=app_settings.ocr_page_timeout_seconds,
        )
        self.classifier = ClassificationAgent()
        self.analyzer = ContentAnalysisAgent()
        self.llm_gateway = llm_gateway or StructuredLLMGateway(LLMConfig.from_env())
        self.llm_understanding = LLMDocumentUnderstandingAgent(self.llm_gateway)
        self.llm_adjudicator = LLMAdjudicatorAgent(self.llm_gateway)
        self.synthetic_document_fingerprints = self._load_synthetic_fingerprints()
        self.researcher = LegislationResearchAgent(
            self.retriever, top_k=app_settings.retrieval_top_k
        )
        self.verifier = SourceVerificationAgent(
            min_retrieval_score=app_settings.min_retrieval_score
        )
        self.graph_advisor: EvidenceGraphAdvisor | None = None
        if app_settings.evidence_graph_enabled:
            try:
                self.graph_advisor = EvidenceGraphAdvisor.load(
                    app_settings.evidence_graph_path,
                    project_root=app_settings.project_root,
                )
            except GraphBuildError as exc:
                self.graph_setup_warning = str(exc)
        self.template_selector = TemplateSelectionAgent(
            app_settings.low_confidence_threshold
        )
        self.router = RoutingAgent(app_settings.data_dir / "synthetic_units.json")
        self.drafter = DraftingAgent()
        self.compliance = ComplianceAgent()
        self.renderer = LatexRenderer(
            app_settings.templates_dir,
            app_settings.output_dir,
            timeout=app_settings.latex_timeout_seconds,
        )
        self.store = FileProcessStore(app_settings.runtime_dir / "processes")

    def _build_retriever(self) -> RankedRetriever:
        if self.settings.retrieval_mode.casefold() == "bm25":
            if (
                self.settings.corpus_mode
                == CorpusMode.COMPETITION_SNAPSHOT.value
            ):
                return self._apply_snapshot_relevance(
                    AnalysisAwareTextRetrieverAdapter(self.index, mode="bm25")
                )
            return self.index

        try:
            corpus_mode = CorpusMode(self.settings.corpus_mode)
            corpus_path = self.settings.retrieval_corpus_path
            active_chunks, corpus_binding = LegislationRepository(
                corpus_path,
                corpus_mode=corpus_mode,
            ).load_with_binding()
            if not active_chunks:
                raise ValueError(f"{corpus_mode.value} korpusu boş.")
        except (OSError, ValueError) as exc:
            corpus_label = (
                "Yarışma snapshot"
                if self.settings.corpus_mode
                == CorpusMode.COMPETITION_SNAPSHOT.value
                else "Aktif kamu mevzuatı"
            )
            self.retrieval_setup_warning = (
                f"{corpus_label} korpusu kullanılamadı "
                f"({type(exc).__name__}); sentetik BM25 fallback etkin."
            )
            fallback = HybridRetriever(
                self.index,
                dense_retriever=None,
                channel_top_n=self.settings.hybrid_candidate_top_k,
                rrf_k=self.settings.rrf_k,
            )
            if (
                self.settings.corpus_mode
                == CorpusMode.COMPETITION_SNAPSHOT.value
            ):
                return self._apply_snapshot_relevance(
                    AnalysisAwareTextRetrieverAdapter(fallback, mode="hybrid")
                )
            return fallback

        # In hybrid mode both lexical and dense channels must represent the
        # same strict corpus contract. Never fuse synthetic BM25 with a public
        # or competition-snapshot Qdrant collection.
        self.index = BM25Index(active_chunks)
        runtime = build_retrieval_runtime(
            self.settings,
            corpus_binding=corpus_binding,
        )
        base_retriever = runtime.hybrid_for(
            self.index,
            channel_top_n=self.settings.hybrid_candidate_top_k,
            rrf_k=self.settings.rrf_k,
        )
        if corpus_mode == CorpusMode.COMPETITION_SNAPSHOT:
            return self._apply_snapshot_relevance(base_retriever)
        return base_retriever

    def _apply_snapshot_relevance(
        self,
        base_retriever: object,
    ) -> AnalysisAwareDeterministicReranker:
        return AnalysisAwareDeterministicReranker(
            base_retriever,
            candidate_top_k=self.settings.relevance_candidate_top_k,
            threshold=self.settings.min_relevance_score,
        )

    def readiness(self) -> dict[str, object]:
        """Report retrieval readiness without creating or repairing resources."""

        mode = self.settings.retrieval_mode.casefold()
        disclosure = self.corpus_disclosure()
        decision_disclosure = self.decision_disclosure()
        if mode == "bm25":
            return {
                "ready": True,
                "retrieval_mode": mode,
                "detail": (
                    f"{disclosure['data_mode']} BM25 corpus hazır: "
                    f"{len(self.index.documents)} parça."
                ),
                **disclosure,
                **decision_disclosure,
            }
        if self.retrieval_setup_warning:
            return {
                "ready": False,
                "retrieval_mode": mode,
                "detail": self.retrieval_setup_warning,
                **disclosure,
                **decision_disclosure,
            }

        vector_store = getattr(self.retriever, "vector_store", None)
        if vector_store is None or not hasattr(vector_store, "validate_readiness"):
            return {
                "ready": False,
                "retrieval_mode": mode,
                "detail": "Hibrit retriever Qdrant readiness sözleşmesi taşımıyor.",
                **disclosure,
                **decision_disclosure,
            }
        try:
            report = vector_store.validate_readiness()
        except (QdrantUnavailable, SchemaMismatch, OSError, ValueError) as exc:
            return {
                "ready": False,
                "retrieval_mode": mode,
                "detail": str(exc),
                **disclosure,
                **decision_disclosure,
            }
        return {
            "ready": True,
            "retrieval_mode": mode,
            "detail": (
                f"Qdrant hazır: {report.compatible_point_count}/"
                f"{report.expected_point_count} uyumlu nokta."
            ),
            "collection": report.collection_name,
            "corpus_fingerprint": report.corpus_fingerprint,
            "embedding_model": report.embedding_model,
            "embedding_dimension": report.embedding_dimension,
            "index_version": report.index_version,
            "qdrant_storage_mode": report.storage_mode,
            "payload_indexes_enforced": report.payload_indexes_enforced,
            "payload_index_detail": report.payload_index_detail,
            **disclosure,
            **decision_disclosure,
        }

    def decision_disclosure(self) -> dict[str, object]:
        config = self.llm_gateway.config
        return {
            "llm_enabled": bool(config.enabled),
            "llm_provider": str(config.provider.value),
            "llm_model": config.model,
            "llm_data_policy": "pinned_synthetic_input_closed_public_metadata",
            "llm_deterministic_fallback": True,
            "evidence_graph_enabled": self.settings.evidence_graph_enabled,
            "evidence_graph_ready": self.graph_advisor is not None,
            "evidence_graph_warning": self.graph_setup_warning,
            "evidence_graph_legal_reliance_allowed": False,
        }

    def corpus_disclosure(self) -> dict[str, object]:
        """Describe what the in-memory lexical corpus may safely claim."""

        chunks = [document.chunk for document in self.index.documents]
        source_kinds = {chunk.source_kind for chunk in chunks}

        if chunks and source_kinds == {"public_legislation"}:
            contract_valid = all(
                not LegislationRepository.public_chunk_blockers(chunk)
                for chunk in chunks
            )
            return {
                "data_mode": (
                    "verified_public_legislation"
                    if contract_valid
                    else "unverified_public_legislation"
                ),
                "corpus_mode": CorpusMode.VERIFIED_PUBLIC.value,
                "corpus_contract_valid": contract_valid,
                "currentness_verified": contract_valid,
                "legal_reliance_allowed": contract_valid,
                "usage_notice": None,
            }

        if chunks and source_kinds == {CorpusMode.COMPETITION_SNAPSHOT.value}:
            contract_valid = all(
                not competition_snapshot_chunk_blockers(chunk) for chunk in chunks
            )
            return {
                "data_mode": (
                    "competition_snapshot"
                    if contract_valid
                    else "competition_snapshot_invalid"
                ),
                "corpus_mode": CorpusMode.COMPETITION_SNAPSHOT.value,
                "corpus_contract_valid": contract_valid,
                "currentness_verified": False,
                "legal_reliance_allowed": False,
                "usage_notice": COMPETITION_SNAPSHOT_NOTICE,
            }

        if chunks and source_kinds == {"synthetic"}:
            contract_valid = all(
                chunk.status == "sentetik_demo_kurali" for chunk in chunks
            )
            return {
                "data_mode": (
                    "sentetik_demo" if contract_valid else "sentetik_veri_gecersiz"
                ),
                "corpus_mode": CorpusMode.TRUSTED_SYNTHETIC.value,
                "corpus_contract_valid": contract_valid,
                "currentness_verified": False,
                "legal_reliance_allowed": False,
                "usage_notice": None,
            }

        has_snapshot = CorpusMode.COMPETITION_SNAPSHOT.value in source_kinds
        return {
            "data_mode": "mixed_or_unknown",
            "corpus_mode": "mixed_or_unknown",
            "corpus_contract_valid": False,
            "currentness_verified": False,
            "legal_reliance_allowed": False,
            "usage_notice": COMPETITION_SNAPSHOT_NOTICE if has_snapshot else None,
        }

    def process_file(self, path: Path, *, compile_pdf: bool = False) -> ProcessState:
        text = self.extractor.extract(path)
        return self.process_text(text, source_name=path.name, compile_pdf=compile_pdf)

    def process_text(
        self,
        text: str,
        *,
        source_name: str = "kullanici_metni.txt",
        compile_pdf: bool = False,
    ) -> ProcessState:
        document_id = self._new_document_id()
        state = ProcessState(
            document_id=document_id,
            source_name=source_name,
            raw_text=text[: self.settings.max_text_chars],
        )
        state.add_event(ProcessStatus.RECEIVED, "Evrak sisteme alındı.", "Alım Ajanı")
        self.store.save(state)
        try:
            self._transition(state, ProcessStatus.READING, "Evrak metni okundu.", "Alım Ajanı")
            self._transition(
                state,
                ProcessStatus.CLASSIFYING,
                "Evrak türü ve içerik alanları analiz ediliyor.",
                self.classifier.name,
            )
            classification = self.classifier.run(state.raw_text or "")
            state.analysis = self.analyzer.run(state.raw_text or "", classification)
            data_classification = self._llm_data_classification(state.raw_text or "")
            state.llm_trace = self._new_llm_trace(data_classification)
            understanding = self.llm_understanding.run(
                text=state.raw_text or "",
                deterministic_analysis=state.analysis,
                data_classification=data_classification,
            )
            self._record_llm_step(
                state,
                role="document_understanding",
                outcome=understanding.call,
                confidence=understanding.confidence,
                candidate_document_type=understanding.document_type,
                candidate_summary=understanding.summary,
                data_classification=data_classification,
            )
            self._apply_llm_understanding(state, understanding)
            self._complete(state, "Evrak sınıflandırıldı ve önemli bilgiler çıkarıldı.")
            return self._continue_pipeline(state, compile_pdf=compile_pdf)
        except Exception as exc:
            state.pending_actions = ["Hata ayrıntısını inceleyin", "İşlemi tekrar deneyin"]
            state.next_step = "Belgeyi veya sistem yapılandırmasını kontrol ederek tekrar deneyiniz."
            state.possible_actions = ["tekrar_dene"]
            state.add_event(ProcessStatus.ERROR, str(exc), self.name)
            self.store.save(state)
            raise

    def provide_information(
        self,
        document_id: str,
        fields: dict[str, str],
        *,
        compile_pdf: bool = False,
    ) -> ProcessState:
        state = self._require_state(document_id)
        if state.status == ProcessStatus.COMPLETED:
            raise ProcessValidationError(
                "Tamamlanmış evrak değiştirilemez; değişiklik için yeni bir revizyon oluşturulmalıdır."
            )
        if not state.analysis:
            raise ProcessValidationError("Süreçte güncellenebilir bir analiz bulunmuyor.")
        clean_fields = {
            key.strip(): value.strip()
            for key, value in fields.items()
            if key.strip() and value and value.strip()
        }
        if not clean_fields:
            raise ProcessValidationError("En az bir dolu alan gönderilmelidir.")

        allowed_fields = (
            set(state.analysis.fields)
            | set(state.analysis.missing_fields)
            | set(self.DRAFT_FIELD_MAP)
        )
        unknown_fields = sorted(set(clean_fields) - allowed_fields)
        if unknown_fields:
            raise ProcessValidationError(
                "Bilinmeyen alanlar: "
                + ", ".join(unknown_fields)
                + ". İzin verilen alanlar: "
                + ", ".join(sorted(allowed_fields))
            )

        state.provided_information.update(clean_fields)

        for key, value in state.provided_information.items():
            if key in state.analysis.fields or key in state.analysis.missing_fields:
                state.analysis.fields[key] = ExtractedField(
                    value=value,
                    status=FieldStatus.FROM_SOURCE,
                    source="kullanici_girdisi",
                )
        state.analysis.missing_fields = [
            name
            for name in state.analysis.missing_fields
            if name not in state.provided_information
        ]
        state.add_event(
            ProcessStatus.SEARCHING,
            "Kullanıcının sağladığı bilgiler sürece eklendi; sonuçlar yenileniyor.",
            "Kullanıcı Bilgilendirme Ajanı",
        )
        self.store.save(state)
        return self._continue_pipeline(
            state,
            compile_pdf=compile_pdf,
            supplied_fields=state.provided_information,
        )

    def approve(self, document_id: str, approved_by: str) -> ProcessState:
        state = self._require_state(document_id)
        if state.status == ProcessStatus.COMPLETED:
            raise ProcessValidationError("Evrak daha önce onaylanarak tamamlanmış.")
        if not state.draft or not state.compliance:
            raise ProcessValidationError("Onaylanabilir bir taslak bulunmuyor.")
        if state.draft.missing_fields:
            raise ProcessValidationError(
                "Eksik alanlar tamamlanmadan taslak onaylanamaz: "
                + ", ".join(state.draft.missing_fields)
            )
        if not state.compliance.passed:
            raise ProcessValidationError("Uygunluk denetimini geçmeyen taslak onaylanamaz.")
        state.completed_steps.append(f"Taslak {approved_by} tarafından onaylandı.")
        state.pending_actions = []
        state.missing_information = []
        state.next_step = "Süreç tamamlandı; çıktı arşivlenebilir."
        state.possible_actions = ["indir", "arsivle"]
        state.add_event(
            ProcessStatus.COMPLETED,
            f"Taslak yetkili kullanıcı tarafından onaylandı: {approved_by}",
            "Kullanıcı Bilgilendirme Ajanı",
        )
        self.store.save(state)
        return state

    def get(self, document_id: str) -> ProcessState:
        return self._require_state(document_id)

    def _continue_pipeline(
        self,
        state: ProcessState,
        *,
        compile_pdf: bool,
        supplied_fields: dict[str, str] | None = None,
    ) -> ProcessState:
        assert state.analysis is not None
        self._transition(
            state,
            ProcessStatus.SEARCHING,
            "İlgili mevzuat ve iş akışı kuralları aranıyor.",
            self.researcher.name,
        )
        retrieval = self.researcher.run_with_diagnostics(state.analysis)
        state.search_hits = retrieval.hits
        diagnostics = retrieval.diagnostics
        if self.retrieval_setup_warning:
            diagnostics = diagnostics.model_copy(
                update={
                    "fallback_used": True,
                    "warning": self.retrieval_setup_warning,
                }
            )
        state.retrieval_diagnostics = diagnostics
        snapshot_candidates_present = any(
            hit.chunk.source_kind == CorpusMode.COMPETITION_SNAPSHOT.value
            for hit in state.search_hits
        )
        if snapshot_candidates_present:
            existing_warning = diagnostics.warning
            warning = (
                f"{existing_warning} {COMPETITION_SNAPSHOT_NOTICE}"
                if existing_warning
                else COMPETITION_SNAPSHOT_NOTICE
            )
            diagnostics = diagnostics.model_copy(update={"warning": warning})
            state.retrieval_diagnostics = diagnostics
        retrieval_message = f"{len(state.search_hits)} kaynak adayı bulundu."
        if diagnostics.warning:
            retrieval_message += f" Retrieval uyarısı: {diagnostics.warning}"
        self._complete(state, retrieval_message)

        self._transition(
            state,
            ProcessStatus.VERIFYING,
            "Kaynak adaylarının sorguyla ilişkisi doğrulanıyor.",
            self.verifier.name,
        )
        state.verified_references = self.verifier.run(state.search_hits, state.analysis)
        verified_count = sum(reference.verified for reference in state.verified_references)
        snapshot_count = sum(
            reference.verified
            and reference.corpus_mode == CorpusMode.COMPETITION_SNAPSHOT.value
            for reference in state.verified_references
        )
        if snapshot_count:
            self._complete(
                state,
                f"{snapshot_count} yarışma snapshot kaynağı retrieval/kaynak izi "
                f"açısından kabul edildi. {COMPETITION_SNAPSHOT_NOTICE}",
            )
        else:
            self._complete(state, f"{verified_count} kaynak doğrulandı.")

        state.graph_decision_trace = self._graph_advice(state)
        if state.graph_decision_trace.applied:
            self._complete(
                state,
                "Sentetik kanıt grafında doğrulanmış kaynaklardan seçici çok-adımlı "
                "karar izi üretildi; bu iz hukuk kanıtı değildir.",
            )

        self._transition(
            state,
            ProcessStatus.SELECTING_TEMPLATE,
            "Uygun resmî yazı türü ve şablon seçiliyor.",
            self.template_selector.name,
        )
        state.template_decision = self.template_selector.run(
            state.analysis, state.verified_references
        )
        self._complete(
            state,
            f"{state.template_decision.document_type} yazı türü seçildi.",
        )

        self._transition(
            state,
            ProcessStatus.ROUTING,
            "Evrak için sorumlu sentetik birim belirleniyor.",
            self.router.name,
        )
        state.routing = self.router.run(state.analysis)
        self._apply_graph_guardrails(state)
        if state.llm_trace is None:
            state.llm_trace = self._new_llm_trace(
                self._llm_data_classification(state.raw_text or "")
            )
        adjudication_classification = self._llm_adjudication_data_classification(
            state
        )
        adjudication = self.llm_adjudicator.run(
            analysis=state.analysis,
            references=state.verified_references,
            template_decision=state.template_decision,
            routing=state.routing,
            graph_trace=state.graph_decision_trace,
            allowed_template_ids=self._allowed_template_ids(state),
            allowed_unit_ids=self._allowed_unit_ids(state),
            data_classification=adjudication_classification,
        )
        adjudication_applied = self._apply_llm_adjudication(state, adjudication)
        self._record_llm_step(
            state,
            role="adjudicator",
            outcome=adjudication.call,
            confidence=adjudication.confidence,
            selected_template_id=adjudication.selected_template_id,
            selected_unit_id=adjudication.selected_unit_id,
            accepted_reference_ids=list(adjudication.accepted_reference_ids),
            human_review_required=(
                adjudication.requires_human_review
                or bool(adjudication.unsupported_claims)
                or not adjudication_applied
                or state.template_decision.user_approval_required
            ),
            decision_applied=adjudication_applied,
            data_classification=adjudication_classification,
        )
        self._complete(state, f"Önerilen birim: {state.routing.unit_name}.")

        self._transition(
            state,
            ProcessStatus.DRAFTING,
            "Yapılandırılmış resmî yazı taslağı hazırlanıyor.",
            self.drafter.name,
        )
        state.draft = self.drafter.run(
            state.analysis,
            state.template_decision,
            state.routing,
            state.verified_references,
        )
        if supplied_fields:
            self._apply_draft_fields(state, supplied_fields)
        state.artifact = self.renderer.render(
            state.document_id, state.draft, compile_pdf=compile_pdf
        )
        self._complete(state, "LaTeX taslağı güvenli şablondan üretildi.")

        self._transition(
            state,
            ProcessStatus.COMPLIANCE,
            "Taslak biçim, kaynak ve zorunlu alan kurallarına göre denetleniyor.",
            self.compliance.name,
        )
        state.compliance = self.compliance.run(state.draft, state.template_decision)
        self._complete(state, f"Uygunluk skoru: {state.compliance.score:.2f}.")
        self._finalize_user_message(state)
        self.store.save(state)
        return state

    def _load_synthetic_fingerprints(self) -> set[str]:
        dataset_path = self.settings.data_dir / "synthetic_gold.json"
        try:
            dataset_bytes = dataset_path.read_bytes()
            if sha256(dataset_bytes).hexdigest() != self.SYNTHETIC_GOLD_SHA256:
                return set()
            payload = json.loads(dataset_bytes.decode("utf-8"))
            records = payload.get("data", [])
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            return set()
        fingerprints: set[str] = set()
        for record in records:
            if not isinstance(record, dict) or not isinstance(record.get("text"), str):
                continue
            tags = {str(tag).casefold() for tag in record.get("tags", [])}
            if "sentetik" not in tags:
                continue
            fingerprints.add(self._text_fingerprint(record["text"]))
        demo_path = self.settings.data_dir / "synthetic_ui_fixtures.json"
        try:
            demo_bytes = demo_path.read_bytes()
            if sha256(demo_bytes).hexdigest() != self.SYNTHETIC_UI_FIXTURES_SHA256:
                return fingerprints
            demo_payload = json.loads(demo_bytes.decode("utf-8"))
            demo_records = demo_payload.get("records", [])
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            return fingerprints
        demo_contract_valid = (
            demo_payload.get("schema_version") == "1.0"
            and demo_payload.get("dataset_name")
            == "divani_agent_trusted_ui_demo_inputs"
            and demo_payload.get("usage") == "engineering_demo_only"
            and demo_payload.get("data_classification") == "synthetic"
            and isinstance(demo_records, list)
        )
        if not demo_contract_valid:
            return fingerprints
        for record in demo_records:
            if not isinstance(record, dict) or not isinstance(record.get("text"), str):
                continue
            tags = {str(tag).casefold() for tag in record.get("tags", [])}
            if not {"sentetik", "ui_demo"} <= tags:
                continue
            fingerprints.add(self._text_fingerprint(record["text"]))
        return fingerprints

    @staticmethod
    def _text_fingerprint(text: str) -> str:
        canonical = normalize_whitespace(text).casefold().encode("utf-8")
        return sha256(canonical).hexdigest()

    def _llm_data_classification(self, text: str) -> DataClassification:
        if self._text_fingerprint(text) in self.synthetic_document_fingerprints:
            return DataClassification.SYNTHETIC
        return DataClassification.RESTRICTED

    def _llm_adjudication_data_classification(
        self,
        state: ProcessState,
    ) -> DataClassification:
        if (
            self._llm_data_classification(state.raw_text or "")
            is not DataClassification.SYNTHETIC
        ):
            return DataClassification.RESTRICTED
        disclosure = self.corpus_disclosure()
        verified = [
            reference for reference in state.verified_references if reference.verified
        ]
        if not verified or disclosure.get("corpus_contract_valid") is not True:
            return DataClassification.RESTRICTED
        corpus_mode = disclosure.get("corpus_mode")
        if corpus_mode == CorpusMode.TRUSTED_SYNTHETIC.value and all(
            reference.source_kind == "synthetic" for reference in verified
        ):
            return DataClassification.SYNTHETIC
        if corpus_mode == CorpusMode.COMPETITION_SNAPSHOT.value and all(
            reference.source_kind == CorpusMode.COMPETITION_SNAPSHOT.value
            and reference.currentness_verified is False
            and reference.legal_reliance_allowed is False
            for reference in verified
        ):
            # Only the closed, non-sensitive candidate metadata is allowed out;
            # snapshot legal excerpts remain local and are never sent to Free Tier.
            return DataClassification.PUBLIC
        return DataClassification.RESTRICTED

    def _new_llm_trace(self, classification: DataClassification) -> LLMRunTrace:
        config = self.llm_gateway.config
        return LLMRunTrace(
            mode="guarded_structured_external",
            enabled=bool(config.enabled),
            provider=str(config.provider.value),
            model=config.model,
            external_data_allowed=classification is not DataClassification.RESTRICTED,
            warning=(
                None
                if classification is DataClassification.SYNTHETIC
                else (
                    "Gerçek/kısıtlı evrak harici ücretsiz LLM API'sine gönderilmedi; "
                    "yerel deterministik akış kullanıldı."
                )
            ),
        )

    @staticmethod
    def _record_llm_step(
        state: ProcessState,
        *,
        role: str,
        outcome: object,
        confidence: float | None = None,
        candidate_document_type: str | None = None,
        candidate_summary: str | None = None,
        data_classification: DataClassification | None = None,
        selected_template_id: str | None = None,
        selected_unit_id: str | None = None,
        accepted_reference_ids: list[str] | None = None,
        human_review_required: bool = False,
        decision_applied: bool | None = None,
    ) -> None:
        assert state.llm_trace is not None
        failure = getattr(outcome, "failure", None)
        status = getattr(getattr(outcome, "status", None), "value", "unknown")
        state.llm_trace.steps.append(
            LLMStepTrace(
                role=role,
                status=status,
                provider=getattr(getattr(outcome, "provider", None), "value", None),
                model=getattr(outcome, "model", None),
                detail=getattr(failure, "message", None),
                data_classification=(
                    data_classification.value if data_classification else None
                ),
                external_data_allowed=(
                    data_classification is not DataClassification.RESTRICTED
                ),
                network_attempted=bool(getattr(outcome, "network_attempted", False)),
                redacted=bool(getattr(outcome, "redacted", False)),
                redaction_count=int(getattr(outcome, "redaction_count", 0)),
                failure_code=getattr(failure, "code", None),
                retryable=bool(getattr(failure, "retryable", False)),
                confidence=confidence,
                candidate_document_type=candidate_document_type,
                candidate_summary=candidate_summary,
                selected_template_id=selected_template_id,
                selected_unit_id=selected_unit_id,
                accepted_reference_ids=accepted_reference_ids or [],
                human_review_required=human_review_required,
                decision_applied=decision_applied,
            )
        )
        state.llm_trace.used = any(
            step.status == "success" for step in state.llm_trace.steps
        )
        state.llm_trace.deterministic_fallback_used = any(
            step.status != "success" or step.decision_applied is False
            for step in state.llm_trace.steps
        )
        state.llm_trace.external_data_allowed = all(
            step.external_data_allowed for step in state.llm_trace.steps
        )
        if (
            data_classification is DataClassification.RESTRICTED
            and state.llm_trace.warning is None
        ):
            state.llm_trace.warning = (
                "En kısıtlı veri/provenance sınıfı nedeniyle ilgili LLM aşaması "
                "ağdan önce engellendi."
            )

    def _apply_llm_understanding(
        self,
        state: ProcessState,
        outcome: UnderstandingOutcome,
    ) -> None:
        if not outcome.call.succeeded or state.analysis is None:
            return
        source_text = state.raw_text or ""
        normalized_source = normalize_for_search(source_text)
        for name, candidate in outcome.fields.items():
            if not candidate.value or not candidate.evidence:
                continue
            normalized_evidence = normalize_for_search(candidate.evidence)
            normalized_value = normalize_for_search(candidate.value)
            if (
                not normalized_evidence
                or normalized_evidence not in normalized_source
                or normalized_value not in normalized_evidence
            ):
                continue
            validated_value = self.analyzer.validate_external_candidate(
                name, candidate.value
            )
            if validated_value is None:
                continue
            current = state.analysis.fields.get(name)
            if current is not None and current.value:
                continue
            state.analysis.fields[name] = ExtractedField(
                value=validated_value,
                status=FieldStatus.INFERRED,
                source="llm:birebir_metin_kaniti",
            )

        required = self.analyzer.REQUIRED_FIELDS.get(
            state.analysis.document_type,
            self.analyzer.REQUIRED_FIELDS["genel_basvuru"],
        )
        state.analysis.missing_fields = [
            name
            for name in required
            if not state.analysis.fields.get(name)
            or not state.analysis.fields[name].value
        ]

    def _allowed_template_ids(self, state: ProcessState) -> list[str]:
        assert state.analysis is not None
        assert state.template_decision is not None
        if state.analysis.missing_fields:
            return ["eksik_bilgi_talebi_v1"]
        candidates = {state.template_decision.template_id}
        candidates.update(
            str(item.get("template_id"))
            for item in state.template_decision.alternatives
            if item.get("template_id")
        )
        if state.graph_decision_trace and state.graph_decision_trace.applied:
            graph_candidates = set(
                state.graph_decision_trace.candidate_template_ids
            )
            if graph_candidates:
                candidates.intersection_update(graph_candidates)
        candidates.discard("eksik_bilgi_talebi_v1")
        known_templates = {
            *self.template_selector.DOCUMENT_TO_TEMPLATE.values(),
            "eksik_bilgi_talebi_v1",
        }
        return sorted(candidates & known_templates) or [state.template_decision.template_id]

    def _allowed_unit_ids(self, state: ProcessState) -> list[str]:
        assert state.routing is not None
        candidates = {state.routing.unit_id}
        candidates.update(
            str(item.get("unit_id"))
            for item in state.routing.alternatives
            if item.get("unit_id")
        )
        if state.graph_decision_trace and state.graph_decision_trace.applied:
            graph_candidates = set(state.graph_decision_trace.candidate_unit_ids)
            if graph_candidates:
                candidates.intersection_update(graph_candidates)
        known_units = {unit.unit_id for unit in self.router.units}
        return sorted(candidates & known_units) or [state.routing.unit_id]

    def _apply_llm_adjudication(
        self,
        state: ProcessState,
        outcome: AdjudicationOutcome,
    ) -> bool:
        assert state.template_decision is not None
        assert state.routing is not None
        verified_ids = {
            reference.chunk_id
            for reference in state.verified_references
            if reference.verified
        }
        graph_trace = state.graph_decision_trace
        graph_template_supported = (
            not graph_trace
            or not graph_trace.applied
            or not graph_trace.candidate_template_ids
            or outcome.selected_template_id in graph_trace.candidate_template_ids
        )
        graph_unit_supported = (
            not graph_trace
            or not graph_trace.applied
            or not graph_trace.candidate_unit_ids
            or outcome.selected_unit_id in graph_trace.candidate_unit_ids
        )
        allowed_template_ids = set(self._allowed_template_ids(state))
        allowed_unit_ids = set(self._allowed_unit_ids(state))
        safe_to_apply = (
            outcome.call.succeeded
            and outcome.confidence is not None
            and outcome.confidence >= self.LLM_ADJUDICATION_MIN_CONFIDENCE
            and not outcome.requires_human_review
            and not outcome.unsupported_claims
            and bool(outcome.accepted_reference_ids)
            and set(outcome.accepted_reference_ids) <= verified_ids
            and graph_template_supported
            and graph_unit_supported
            and outcome.selected_template_id in allowed_template_ids
            and outcome.selected_unit_id in allowed_unit_ids
        )
        if not safe_to_apply:
            state.template_decision.user_approval_required = True
            state.template_decision.rationale += (
                " LLM Adjudicator kararı güven/kanıt kapısını geçmedi; "
                "deterministik seçim korundu ve insan incelemesi zorunlu kaldı."
            )
            state.routing.rationale += (
                " LLM Adjudicator önerisi uygulanmadı; deterministik birim "
                "önerisi korundu."
            )
            return False
        if outcome.selected_template_id in allowed_template_ids:
            previous_template = state.template_decision
            adjudication_confidence = (
                outcome.confidence
                if outcome.confidence is not None
                else previous_template.confidence
            )
            state.template_decision = TemplateDecision(
                document_type=self.template_selector._document_type_for(
                    outcome.selected_template_id
                ),
                template_id=outcome.selected_template_id,
                rationale=(
                    previous_template.rationale
                    + " Yapılandırılmış Adjudicator değerlendirmesi: "
                    + (outcome.rationale or "gerekçe sağlanmadı")
                ),
                confidence=round(adjudication_confidence, 2),
                user_approval_required=(
                    previous_template.user_approval_required
                    or outcome.requires_human_review
                    or bool(outcome.unsupported_claims)
                    or adjudication_confidence < self.settings.low_confidence_threshold
                ),
                alternatives=previous_template.alternatives,
            )
        if outcome.selected_unit_id in allowed_unit_ids:
            unit = next(
                unit for unit in self.router.units if unit.unit_id == outcome.selected_unit_id
            )
            previous_routing = state.routing
            routing_confidence = (
                outcome.confidence
                if outcome.confidence is not None
                else previous_routing.score
            )
            state.routing = RoutingRecommendation(
                unit_id=unit.unit_id,
                unit_name=unit.unit_name,
                hierarchy=unit.hierarchy,
                rationale=(
                    previous_routing.rationale
                    + " Yapılandırılmış Adjudicator değerlendirmesi: "
                    + (outcome.rationale or "gerekçe sağlanmadı")
                ),
                score=round(routing_confidence, 2),
                alternatives=previous_routing.alternatives,
            )
        if outcome.accepted_reference_ids:
            accepted = set(outcome.accepted_reference_ids)
            state.verified_references.sort(
                key=lambda reference: (
                    reference.chunk_id not in accepted,
                    -reference.score,
                    reference.chunk_id,
                )
            )
        return True

    def _graph_advice(self, state: ProcessState) -> GraphDecisionTrace:
        if self.graph_advisor is None:
            return GraphDecisionTrace(
                strategy=(
                    "unavailable" if self.settings.evidence_graph_enabled else "disabled"
                ),
                warning=self.graph_setup_warning,
            )
        disclosure = self.corpus_disclosure()
        return self.graph_advisor.advise(
            document_type=state.analysis.document_type,
            references=state.verified_references,
            synthetic_corpus_allowed=(
                disclosure.get("corpus_mode") == CorpusMode.TRUSTED_SYNTHETIC.value
                and disclosure.get("corpus_contract_valid") is True
            ),
        )

    @staticmethod
    def _apply_graph_guardrails(state: ProcessState) -> None:
        trace = state.graph_decision_trace
        if not trace or not trace.applied:
            return
        assert state.template_decision is not None
        assert state.routing is not None

        template_supported = (
            not trace.candidate_template_ids
            or state.template_decision.template_id in trace.candidate_template_ids
        )
        unit_supported = (
            not trace.candidate_unit_ids
            or state.routing.unit_id in trace.candidate_unit_ids
        )
        if template_supported:
            state.template_decision.rationale += (
                " Dondurulmuş sentetik kanıt grafı adayıyla tutarlıdır."
            )
        else:
            state.template_decision.user_approval_required = True
            state.template_decision.rationale += (
                " Sentetik kanıt grafı bu şablonu desteklemedi; deterministik karar "
                "korundu ve insan incelemesi zorunlu tutuldu."
            )
        if unit_supported:
            state.routing.rationale += (
                " Dondurulmuş sentetik kanıt grafı birim adayıyla tutarlıdır."
            )
        else:
            state.routing.rationale += (
                " Sentetik kanıt grafı bu birimi desteklemedi; öneri değiştirilmeden "
                "insan incelemesine bırakıldı."
            )

    def _apply_draft_fields(self, state: ProcessState, fields: dict[str, str]) -> None:
        assert state.draft is not None
        for external_name, attribute_name in self.DRAFT_FIELD_MAP.items():
            value = fields.get(external_name)
            if not value:
                continue
            setattr(
                state.draft,
                attribute_name,
                ExtractedField(
                    value=value,
                    status=FieldStatus.FROM_SOURCE,
                    source="kullanici_girdisi",
                ),
            )
        state.draft.missing_fields = [
            name for name in state.draft.missing_fields if name not in fields
        ]

    def _finalize_user_message(self, state: ProcessState) -> None:
        assert state.draft is not None
        assert state.compliance is not None
        missing = list(dict.fromkeys(state.draft.missing_fields))
        state.missing_information = missing
        if missing:
            state.pending_actions = [
                "Eksik alanları doldurun: " + ", ".join(missing),
                "Güncellenen taslağı tekrar kontrol edin.",
            ]
            state.next_step = "Eksik bilgileri girerek taslağı yeniden oluşturunuz."
            state.possible_actions = ["bilgi_gir", "taslagi_goruntule"]
            state.add_event(
                ProcessStatus.WAITING_FOR_INFO,
                "Taslak üretildi; zorunlu kullanıcı bilgileri bekleniyor.",
                "Kullanıcı Bilgilendirme Ajanı",
            )
        elif not state.compliance.passed:
            compliance_errors = state.compliance.errors or [
                "Uygunluk denetimi başarısız oldu."
            ]
            state.pending_actions = [
                "Uygunluk hatalarını giderin: " + "; ".join(compliance_errors),
                "Güncellenen taslağı yeniden uygunluk denetimine gönderin.",
            ]
            state.next_step = (
                "Uygunluk hatalarını gidererek taslağı yeniden oluşturunuz; "
                "mevcut taslak onaylanamaz."
            )
            state.possible_actions = ["taslagi_duzenle", "reddet"]
            state.add_event(
                ProcessStatus.ERROR,
                "Taslak uygunluk denetimini geçemedi ve kullanıcı onayına sunulmadı.",
                "Kullanıcı Bilgilendirme Ajanı",
            )
        else:
            state.pending_actions = ["Taslağı inceleyin ve yetkili kullanıcı olarak onaylayın."]
            state.next_step = "LaTeX/PDF taslağını inceleyerek onaylayınız."
            state.possible_actions = ["taslagi_duzenle", "onayla", "reddet"]
            state.add_event(
                ProcessStatus.WAITING_FOR_APPROVAL,
                "Taslak uygunluk denetiminden geçti ve kullanıcı onayı bekliyor.",
                "Kullanıcı Bilgilendirme Ajanı",
            )

    def _transition(
        self, state: ProcessState, status: ProcessStatus, message: str, agent: str
    ) -> None:
        state.add_event(status, message, agent)
        self.store.save(state)

    def _complete(self, state: ProcessState, message: str) -> None:
        state.completed_steps.append(message)
        self.store.save(state)

    def _require_state(self, document_id: str) -> ProcessState:
        state = self.store.get(document_id)
        if state is None:
            raise ProcessNotFoundError(document_id)
        return state

    @staticmethod
    def _new_document_id() -> str:
        return f"EVR-{datetime.now():%Y%m%d}-{uuid4().hex[:8].upper()}"


def build_orchestrator(app_settings: Settings = settings) -> EvrakOrchestrator:
    return EvrakOrchestrator(app_settings)
