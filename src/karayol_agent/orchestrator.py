from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from karayol_agent.agents import (
    ClassificationAgent,
    ComplianceAgent,
    ContentAnalysisAgent,
    DocumentTypeCatalog,
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
from karayol_agent.agents.llm_layer3 import (
    LLMResponseStrategyAgent,
    LLMRoutingAgent,
    LLMTemplateFillAgent,
    LLMTemplateSelectionAgent,
    ResponseStrategyProposalOutcome,
    RoutingOutcome,
    TemplateCatalog,
    TemplateFillOutcome,
    TemplateSelectionOutcome,
)
from karayol_agent.config import Settings, settings
from karayol_agent.documents import DocumentExtractor, plain_text_layout
from karayol_agent.document_types import COMPETITION_DOCUMENT_TYPES
from karayol_agent.graph import EvidenceGraphAdvisor, GraphBuildError
from karayol_agent.llm import DataClassification, LLMConfig, StructuredLLMGateway
from karayol_agent.latex import LatexRenderer
from karayol_agent.layer2_legal_reasoning import Layer2LegalReasoning
from karayol_agent.official_writing_rules import closing_matches_authority_relation
from karayol_agent.retrieval import (
    AnalysisAwareDeterministicReranker,
    AnalysisAwareTextRetrieverAdapter,
    BM25Index,
    LegislationRepository,
    RequirementRuleRepository,
)
from karayol_agent.retrieval.contracts import (
    COMPETITION_SNAPSHOT_NOTICE,
    CorpusMode,
    competition_snapshot_chunk_blockers,
)
from karayol_agent.retrieval.hybrid import HybridRetriever
from karayol_agent.retrieval.federated import (
    EvrenQueryEmbeddingClient,
    FederatedAnalysisRetriever,
    RemoteExternalDenseRetriever,
)
from karayol_agent.retrieval.qdrant_store import QdrantUnavailable, SchemaMismatch
from karayol_agent.retrieval.runtime import (
    ArchiveWideDomainResolver,
    build_retrieval_runtime,
)
from karayol_agent.schemas import (
    ExtractedField,
    FieldStatus,
    GraphDecisionTrace,
    DocumentLayout,
    Layer1Audit,
    Layer3DraftOutput,
    LLMDecisionCheck,
    LLMFindingTrace,
    LLMRunTrace,
    LLMStepTrace,
    ProcessState,
    ProcessStatus,
    ResponseStrategyOption,
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
        "elektronik_imza": "electronic_signature",
    }
    DRAFT_LIST_FIELD_MAP = {
        "ilgi": "interest",
        "ekler": "attachments",
        "dagitim": "distribution",
        "iletisim": "contact_information",
        "paraf": "initials",
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
        detsis_dir = app_settings.project_root / "veri_kaynaklari" / "karayolu" / "detsis"
        self.document_type_catalog = DocumentTypeCatalog(
            [
                detsis_dir / "belgeler.json",
                detsis_dir / "karayolu_belgeleri.json",
            ]
        )
        self.llm_gateway = llm_gateway or StructuredLLMGateway(LLMConfig.from_env())
        self.llm_understanding = LLMDocumentUnderstandingAgent(self.llm_gateway)
        self.llm_adjudicator = LLMAdjudicatorAgent(self.llm_gateway)
        self.synthetic_document_fingerprints = self._load_synthetic_fingerprints()
        self.researcher = LegislationResearchAgent(
            self.retriever, top_k=app_settings.retrieval_top_k
        )
        self.requirement_rules = RequirementRuleRepository(
            app_settings.data_dir / "legal_requirements" / "catalog.json"
        )
        self.verifier = SourceVerificationAgent(
            min_retrieval_score=app_settings.min_retrieval_score
        )
        if app_settings.layer2_enabled and llm_gateway is None:
            layer2_gateway: StructuredGateway = StructuredLLMGateway(
                replace(
                    self.llm_gateway.config,
                    model=app_settings.layer2_llm_model,
                    temperature=0.0,
                )
            )
        else:
            layer2_gateway = self.llm_gateway
        self.layer2 = Layer2LegalReasoning(
            layer2_gateway,
            self.requirement_rules,
            enabled=app_settings.layer2_enabled,
            max_search_rounds=app_settings.layer2_max_search_rounds,
            legal_search=lambda query, analysis: self.verifier.run(
                self.researcher.search_query_with_diagnostics(query, analysis).hits,
                analysis,
            ),
        )
        if app_settings.layer3_enabled and llm_gateway is None:
            layer3_gateway: StructuredGateway = StructuredLLMGateway(
                replace(
                    self.llm_gateway.config,
                    model=app_settings.layer3_llm_model,
                    temperature=0.0,
                )
            )
            layer3_reasoning_gateway: StructuredGateway = StructuredLLMGateway(
                replace(
                    self.llm_gateway.config,
                    model=app_settings.layer3_reasoning_llm_model,
                    temperature=0.0,
                )
            )
        else:
            layer3_gateway = self.llm_gateway
            layer3_reasoning_gateway = self.llm_gateway
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
        organization_units_path = (
            app_settings.organization_units_path
            or app_settings.data_dir
            / "organization"
            / "kgm_units_2026-07-16.json"
        )
        self.router = RoutingAgent(organization_units_path)
        self.template_catalog = TemplateCatalog.load(
            app_settings.template_catalog_path
        )
        self.llm_template_selector = LLMTemplateSelectionAgent(
            layer3_gateway, self.template_catalog
        )
        self.llm_router = LLMRoutingAgent(layer3_gateway)
        self.llm_response_strategy = LLMResponseStrategyAgent(
            layer3_reasoning_gateway
        )
        self.llm_template_filler = LLMTemplateFillAgent(layer3_gateway)
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
            domain_resolver=(
                ArchiveWideDomainResolver()
                if self.settings.snapshot_relevance_policy == "lexical_overlap"
                else None
            ),
        )
        base_retriever = runtime.hybrid_for(
            self.index,
            channel_top_n=self.settings.hybrid_candidate_top_k,
            rrf_k=self.settings.rrf_k,
        )
        if corpus_mode == CorpusMode.COMPETITION_SNAPSHOT:
            if self.settings.external_retrieval_enabled:
                external = RemoteExternalDenseRetriever(
                    embedding_client=EvrenQueryEmbeddingClient(
                        base_url=str(self.settings.external_embedding_base_url),
                        api_key=str(self.settings.external_embedding_api_key),
                        model=self.settings.external_embedding_model,
                    ),
                    qdrant_url=self.settings.external_qdrant_url,
                    qdrant_prefix=str(self.settings.external_qdrant_prefix),
                    qdrant_api_key=str(self.settings.external_qdrant_api_key),
                    corpus_fingerprint=str(
                        self.settings.external_corpus_fingerprint
                    ),
                    collection_name=self.settings.external_qdrant_collection,
                    timeout=max(self.settings.qdrant_timeout_seconds, 60.0),
                )
                base_retriever = FederatedAnalysisRetriever(
                    base_retriever,
                    external,
                    channel_top_n=max(
                        self.settings.hybrid_candidate_top_k,
                        self.settings.relevance_candidate_top_k,
                    ),
                    rrf_k=self.settings.rrf_k,
                )
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
            fallback_policy=self.settings.snapshot_relevance_policy,
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

        federated_readiness = getattr(
            self.retriever, "federated_readiness", None
        )
        if callable(federated_readiness):
            try:
                report = federated_readiness()
            except (QdrantUnavailable, SchemaMismatch, OSError, ValueError) as exc:
                return {
                    "ready": False,
                    "retrieval_mode": "hybrid_federated",
                    "detail": str(exc),
                    **disclosure,
                    **decision_disclosure,
                }
            return {**report, **disclosure, **decision_disclosure}

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
            "llm_data_policy": (
                "external_redacted_input_explicit_opt_in"
                if self.settings.external_llm_redacted_input_enabled
                else "pinned_synthetic_input_closed_public_metadata"
            ),
            "llm_deterministic_fallback": True,
            "layer2_enabled": self.settings.layer2_enabled,
            "layer2_model": self.settings.layer2_llm_model,
            "layer2_source_only": True,
            "layer2_max_search_rounds": self.settings.layer2_max_search_rounds,
            "layer3_enabled": self.settings.layer3_enabled,
            "layer3_model": self.settings.layer3_llm_model,
            "layer3_reasoning_model": self.settings.layer3_reasoning_llm_model,
            "layer3_source_only": True,
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
        text, layout = self.extractor.extract_with_layout(path)
        return self.process_text(
            text,
            source_name=path.name,
            compile_pdf=compile_pdf,
            document_layout=layout,
        )

    def process_text(
        self,
        text: str,
        *,
        source_name: str = "kullanici_metni.txt",
        compile_pdf: bool = False,
        document_layout: DocumentLayout | None = None,
        document_id: str | None = None,
    ) -> ProcessState:
        if document_id is not None:
            state = self._require_state(document_id)
            return self._process_reserved_text(state, compile_pdf=compile_pdf)
        state = self.reserve_text_process(
            text,
            source_name=source_name,
            document_layout=document_layout,
        )
        return self._process_reserved_text(state, compile_pdf=compile_pdf)

    def reserve_text_process(
        self,
        text: str,
        *,
        source_name: str = "kullanici_metni.txt",
        document_layout: DocumentLayout | None = None,
    ) -> ProcessState:
        """Persist an initial process so clients can poll live progress."""

        document_id = self._new_document_id()
        state = ProcessState(
            document_id=document_id,
            source_name=source_name,
            raw_text=text[: self.settings.max_text_chars],
            document_layout=document_layout or plain_text_layout(text),
        )
        state.add_event(ProcessStatus.RECEIVED, "Evrak sisteme alındı.", "Alım Ajanı")
        self.store.save(state)
        return state

    def _process_reserved_text(
        self,
        state: ProcessState,
        *,
        compile_pdf: bool,
    ) -> ProcessState:
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
            state.analysis.operational_category = state.analysis.document_type
            state.analysis.document_type = state.analysis.general_document_type
            type_candidates = self.document_type_catalog.search(state.raw_text or "")
            classification_retrieval = self.researcher.run_with_diagnostics(state.analysis)
            classification_references = self.verifier.run(
                classification_retrieval.hits,
                state.analysis,
            )
            data_classification = self._llm_data_classification(state.raw_text or "")
            state.llm_trace = self._new_llm_trace(data_classification)
            understanding = self.llm_understanding.run(
                text=state.raw_text or "",
                deterministic_analysis=state.analysis,
                references=classification_references,
                document_type_candidates=[
                    candidate.as_prompt_data() for candidate in type_candidates
                ],
                document_layout=state.document_layout,
                data_classification=data_classification,
            )
            understanding_applied, understanding_checks = self._apply_llm_understanding(
                state,
                understanding,
                classification_references,
                {
                    candidate.candidate_id: candidate.document_type
                    for candidate in type_candidates
                },
            )
            self._record_llm_step(
                state,
                role="document_understanding",
                outcome=understanding.call,
                confidence=understanding.confidence,
                candidate_document_type=understanding.document_type,
                candidate_summary=understanding.summary,
                accepted_reference_ids=list(understanding.rag_reference_ids),
                data_classification=data_classification,
                decision_applied=understanding_applied,
                decision_summary=self._understanding_decision_summary(
                    understanding, understanding_applied
                ),
                decision_checks=understanding_checks,
                findings=self._understanding_findings(
                    understanding, understanding_applied
                ),
            )
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
            set(self.DRAFT_FIELD_MAP)
            | set(self.DRAFT_LIST_FIELD_MAP)
            | {"makam_iliskisi", "kapanis"}
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

        state.add_event(
            ProcessStatus.SEARCHING,
            "Resmî yazı için sağlanan kurumsal bilgiler eklendi; taslak yenileniyor.",
            "Kullanıcı Bilgilendirme Ajanı",
        )
        self.store.save(state)
        return self._continue_pipeline(
            state,
            compile_pdf=compile_pdf,
            supplied_fields=state.provided_information,
        )

    def choose_response_strategy(
        self,
        document_id: str,
        *,
        option_id: str | None = None,
        custom_text: str | None = None,
        delivery_target: str = "citizen",
        compile_pdf: bool = False,
    ) -> ProcessState:
        state = self._require_state(document_id)
        if state.status == ProcessStatus.COMPLETED:
            raise ProcessValidationError("Tamamlanmış evrak değiştirilemez.")
        if not state.analysis or not state.template_decision or not state.routing:
            raise ProcessValidationError("Katman 3 için önceki kararlar hazır değil.")
        clean_option_id = (option_id or "").strip() or None
        clean_custom_text = (custom_text or "").strip() or None
        if delivery_target not in {"citizen", "internal_unit", "both"}:
            raise ProcessValidationError("Geçersiz taslak gönderim yönü.")
        state.selected_delivery_target = delivery_target
        if clean_option_id == "custom":
            if not clean_custom_text:
                raise ProcessValidationError(
                    "Kendi yanıt stratejiniz seçildiğinde metin zorunludur."
                )
            state.selected_response_strategy = None
            state.selected_response_custom_text = clean_custom_text
        elif clean_option_id:
            selected = next(
                (
                    option
                    for option in state.response_strategy_options
                    if option.option_id == clean_option_id
                ),
                None,
            )
            if selected is None:
                raise ProcessValidationError(
                    "Bilinmeyen yanıt stratejisi: " + clean_option_id
                )
            state.selected_response_strategy = selected
            state.selected_response_custom_text = None
        elif clean_custom_text:
            state.selected_response_strategy = None
            state.selected_response_custom_text = clean_custom_text
        else:
            raise ProcessValidationError("Bir yanıt stratejisi seçilmelidir.")
        state.add_event(
            ProcessStatus.DRAFTING,
            "Yanıt stratejisi seçildi; kaynak-bağlı taslak hazırlanıyor.",
            "Katman 3",
        )
        self.store.save(state)
        return self._build_draft_and_finalize(
            state,
            compile_pdf=compile_pdf,
            supplied_fields=state.provided_information or None,
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
        output_missing = sorted(
            {
                field_name
                for output in state.layer3_outputs
                for field_name in output.draft.missing_fields
            }
        )
        if output_missing:
            raise ProcessValidationError(
                "Katman 3 taslakları tamamlanmadan onaylanamaz: "
                + ", ".join(output_missing)
            )
        if any(not output.compliance.passed for output in state.layer3_outputs):
            raise ProcessValidationError(
                "Uygunluk denetimini geçmeyen Katman 3 taslağı onaylanamaz."
            )
        if not state.compliance.passed:
            raise ProcessValidationError("Uygunluk denetimini geçmeyen taslak onaylanamaz.")
        state.completed_steps.append(f"Taslak {approved_by} tarafından onaylandı.")
        if (
            state.response_strategy_options
            and state.selected_response_strategy is None
            and not state.selected_response_custom_text
        ):
            raise ProcessValidationError("Yanıt stratejisi seçilmeden taslak onaylanamaz.")
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
        retrieval = self.researcher.run_requirements_with_diagnostics(state.analysis)
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
        curated_rules = self.requirement_rules.select(state.analysis)
        curated_references = self.requirement_rules.verified_references(curated_rules)
        known_reference_ids = {
            reference.chunk_id for reference in state.verified_references
        }
        state.verified_references.extend(
            reference
            for reference in curated_references
            if reference.chunk_id not in known_reference_ids
        )
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
        if curated_rules:
            self._complete(
                state,
                f"{len(curated_rules)} denetlenmiş evrak gereksinimi LLM-2 için seçildi.",
            )
        elif self.requirement_rules.warning:
            self._complete(state, self.requirement_rules.warning)

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
            "Evrak için organizasyon kataloğundaki sorumlu birim belirleniyor.",
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
            document_layout=state.document_layout,
            data_classification=adjudication_classification,
            curated_requirement_rules=self.requirement_rules.payload(curated_rules),
        )
        rag_missing = set(adjudication.missing_fields)
        rag_missing.update(
            {
                requirement.field
                for requirement in adjudication.requirements
                if requirement.status in {"missing", "ambiguous"}
            }
        )
        if rag_missing:
            state.analysis.missing_fields = sorted(
                set(state.analysis.missing_fields) | rag_missing
            )
            state.template_decision = self.template_selector.run(
                state.analysis,
                state.verified_references,
            )
        adjudication_checks = self._adjudication_decision_checks(
            state, adjudication
        )
        adjudication_applied = self._apply_llm_adjudication(
            state, adjudication, decision_checks=adjudication_checks
        )
        state.layer1_audit = Layer1Audit(
            document_type=state.analysis.general_document_type,
            operational_category=state.analysis.operational_category,
            requirements=list(adjudication.requirements),
            missing_fields=sorted(rag_missing),
            format_violations=list(adjudication.format_violations),
            important_results=list(adjudication.important_results),
            accepted_reference_ids=list(adjudication.accepted_reference_ids),
            validation_warnings=list(adjudication.unsupported_claims),
            requires_human_review=(
                adjudication.requires_human_review
                or bool(adjudication.unsupported_claims)
                or not adjudication_applied
            ),
        )
        def publish_layer2_progress(agent: str, message: str) -> None:
            state.add_event(ProcessStatus.VERIFYING, message, agent)
            self.store.save(state)

        publish_layer2_progress(
            "Katman 2",
            "Kaynağa bağlı içerik değerlendirmesi başlatıldı.",
        )
        state.layer2_assessment = self.layer2.run(
            analysis=state.analysis,
            text=state.raw_text or "",
            layout=state.document_layout,
            references=state.verified_references,
            data_classification=adjudication_classification,
            progress=publish_layer2_progress,
        ).model_dump(mode="json")
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
            decision_summary=self._adjudication_decision_summary(
                adjudication, adjudication_applied
            ),
            decision_checks=adjudication_checks,
            findings=self._adjudication_findings(adjudication),
            repair_attempted=adjudication.repair_attempted,
            repair_succeeded=adjudication.repair_succeeded,
            repair_status=(
                getattr(getattr(adjudication.repair_call, "status", None), "value", None)
                if adjudication.repair_call is not None
                else None
            ),
            repair_detail=(
                getattr(getattr(adjudication.repair_call, "failure", None), "message", None)
                if adjudication.repair_call is not None
                else None
            ),
        )
        layer3_references = self._layer3_references(state)
        if self.settings.layer3_enabled:
            self._transition(
                state,
                ProcessStatus.SELECTING_TEMPLATE,
                "Katman 3, kapalı katalogdan resmî yazı şablonunu değerlendiriyor.",
                self.llm_template_selector.name,
            )
            template_outcome = self.llm_template_selector.run(
                analysis=state.analysis,
                deterministic_decision=state.template_decision,
                verified_references=layer3_references,
                allowed_template_ids=self._allowed_template_ids(state),
                data_classification=adjudication_classification,
            )
            template_applied = self._apply_llm_template_selection(
                state, template_outcome
            )
            self._record_llm_step(
                state,
                role="llm3_template_selection",
                outcome=template_outcome.call,
                confidence=template_outcome.confidence,
                selected_template_id=template_outcome.selected_template_id,
                human_review_required=(
                    template_outcome.requires_human_review or not template_applied
                ),
                decision_applied=template_applied,
                data_classification=adjudication_classification,
                decision_summary=template_outcome.rationale,
            )

            self._transition(
                state,
                ProcessStatus.ROUTING,
                "Katman 3, kapalı organizasyon grafında sorumlu birimi değerlendiriyor.",
                self.llm_router.name,
            )
            routing_outcome = self.llm_router.run(
                analysis=state.analysis,
                units=self.router.units,
                deterministic_routing=state.routing,
                allowed_unit_ids=self._allowed_unit_ids(state),
                data_classification=adjudication_classification,
            )
            routing_applied = self._apply_llm_routing(state, routing_outcome)
            self._record_llm_step(
                state,
                role="llm5_routing",
                outcome=routing_outcome.call,
                confidence=routing_outcome.confidence,
                selected_unit_id=routing_outcome.selected_unit_id,
                human_review_required=(
                    routing_outcome.requires_human_review or not routing_applied
                ),
                decision_applied=routing_applied,
                data_classification=adjudication_classification,
                decision_summary=routing_outcome.rationale,
            )

            if (
                not state.response_strategy_options
                and state.selected_response_strategy is None
                and not state.selected_response_custom_text
            ):
                self._transition(
                    state,
                    ProcessStatus.DRAFTING,
                    "Katman 3, doğrulanmış kaynaklardan yanıt stratejileri üretiyor.",
                    self.llm_response_strategy.name,
                )
                strategy_outcome = self.llm_response_strategy.run(
                    analysis=state.analysis,
                    verified_references=layer3_references,
                    data_classification=adjudication_classification,
                )
                self._apply_response_strategy_options(state, strategy_outcome)
                self._record_llm_step(
                    state,
                    role="llm6_response_strategy",
                    outcome=strategy_outcome.call,
                    accepted_reference_ids=sorted(
                        {
                            reference_id
                            for option in strategy_outcome.options
                            for reference_id in option.reference_ids
                        }
                    ),
                    data_classification=adjudication_classification,
                )
            if (
                state.response_strategy_options
                and state.selected_response_strategy is None
                and not state.selected_response_custom_text
            ):
                self._wait_for_response_strategy(state)
                self.store.save(state)
                return state
        self._complete(state, f"Önerilen birim: {state.routing.unit_name}.")
        return self._build_draft_and_finalize(
            state,
            compile_pdf=compile_pdf,
            supplied_fields=supplied_fields,
        )

    def _layer3_references(self, state: ProcessState) -> list:
        """Katman 3'e mümkünse yalnız Katman 2'nin kabul ettiği kaynakları geçir."""

        verified = [
            reference for reference in state.verified_references if reference.verified
        ]
        assessment = state.layer2_assessment or {}
        accepted_ids = {
            str(reference_id)
            for reference_id in assessment.get("accepted_reference_ids", [])
        }
        if accepted_ids:
            selected = [
                reference
                for reference in verified
                if reference.chunk_id in accepted_ids
            ]
            if selected:
                return selected
        return verified

    def _apply_llm_template_selection(
        self,
        state: ProcessState,
        outcome: TemplateSelectionOutcome,
    ) -> bool:
        assert state.template_decision is not None
        allowed = set(self._allowed_template_ids(state))
        if (
            not outcome.call.succeeded
            or outcome.selected_template_id not in allowed
            or outcome.confidence is None
            or outcome.confidence < self.LLM_ADJUDICATION_MIN_CONFIDENCE
            or outcome.requires_human_review
        ):
            state.template_decision.user_approval_required = True
            return False
        previous = state.template_decision
        state.template_decision = TemplateDecision(
            document_type=self.template_selector._document_type_for(
                outcome.selected_template_id
            ),
            template_id=outcome.selected_template_id,
            rationale=(
                previous.rationale
                + " Katman 3 kaynak/katalog değerlendirmesi: "
                + (outcome.rationale or "gerekçe sağlanmadı")
            ),
            confidence=round(outcome.confidence, 2),
            user_approval_required=previous.user_approval_required,
            alternatives=previous.alternatives,
        )
        return True

    def _apply_llm_routing(
        self,
        state: ProcessState,
        outcome: RoutingOutcome,
    ) -> bool:
        assert state.routing is not None
        allowed = set(self._allowed_unit_ids(state))
        if (
            not outcome.call.succeeded
            or outcome.selected_unit_id not in allowed
            or outcome.confidence is None
            or outcome.confidence < self.LLM_ADJUDICATION_MIN_CONFIDENCE
            or outcome.requires_human_review
        ):
            state.routing.requires_human_review = True
            state.routing.routing_status = "needs_review"
            return False
        unit = next(
            item for item in self.router.units if item.unit_id == outcome.selected_unit_id
        )
        previous = state.routing
        state.routing = previous.model_copy(
            update={
                "unit_id": unit.unit_id,
                "unit_name": unit.unit_name,
                "hierarchy": unit.hierarchy,
                "rationale": (
                    previous.rationale
                    + " Katman 3 organizasyon grafı değerlendirmesi: "
                    + (outcome.rationale or "gerekçe sağlanmadı")
                ),
                "score": round(outcome.confidence, 2),
                "requires_human_review": previous.requires_human_review,
                "routing_status": (
                    "needs_review" if previous.requires_human_review else "proposed"
                ),
                "decision_basis": [
                    *previous.decision_basis,
                    "Katman 3 kapalı organizasyon grafı",
                    *outcome.traversal_path,
                ],
            }
        )
        return True

    @staticmethod
    def _apply_response_strategy_options(
        state: ProcessState,
        outcome: ResponseStrategyProposalOutcome,
    ) -> None:
        options = list(outcome.options)
        if options:
            options.append(
                ResponseStrategyOption(
                    option_id="custom",
                    label="Kendim belirleyeceğim",
                    description=(
                        "Sunulan kaynak-bağlı seçenekler uygun değilse yanıt "
                        "duruşunu kendi cümlelerinizle belirtin."
                    ),
                )
            )
        state.response_strategy_options = options

    @staticmethod
    def _wait_for_response_strategy(state: ProcessState) -> None:
        state.pending_actions = [
            "Kaynaklara dayalı yanıt stratejilerinden birini seçin.",
            "Gerekirse kendi yanıt talimatınızı yazın.",
        ]
        state.missing_information = []
        state.next_step = (
            "Gelen evraktaki eksikler bilgi amaçlı gösterilir; Katman 3 yanıt "
            "stratejisini seçebilirsiniz."
        )
        state.possible_actions = ["yanit_stratejisi_sec"]
        state.add_event(
            ProcessStatus.WAITING_FOR_RESPONSE_STRATEGY,
            "Katman 3, taslak öncesinde kullanıcı yanıt stratejisini bekliyor.",
            "Katman 3",
        )

    def _template_structure(self, template_id: str) -> dict:
        path = self.settings.templates_dir / template_id / "schema.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"template_id": template_id, "required": []}
        return payload if isinstance(payload, dict) else {"template_id": template_id}

    def _apply_llm_template_fill(
        self,
        state: ProcessState,
        outcome: TemplateFillOutcome,
    ) -> bool:
        assert state.draft is not None
        if not outcome.call.succeeded or not outcome.subject or not outcome.paragraphs:
            return False
        closing = outcome.closing or state.draft.closing
        if not closing_matches_authority_relation(
            closing, state.draft.authority_relation
        ):
            return False
        # Kaynak güveni ve güncellik uyarıları denetim izinde kalır. Bunlar
        # kurumdan gönderilecek resmî yazının gövdesinin parçası değildir.
        outgoing_paragraphs = [
            paragraph
            for paragraph in outcome.paragraphs
            if paragraph.strip() != closing.strip()
            and not self._is_internal_draft_note(paragraph)
        ]
        if not outgoing_paragraphs:
            return False
        state.draft.subject = ExtractedField(
            value=outcome.subject,
            status=FieldStatus.GENERATED,
            source="llm4:kaynak_bagli_sablon_doldurma",
        )
        state.draft.closing = closing
        state.draft.paragraphs = [
            *outgoing_paragraphs,
            closing,
        ]
        return True

    @staticmethod
    def _is_internal_draft_note(paragraph: str) -> bool:
        normalized = normalize_for_search(paragraph)
        internal_markers = (
            "yarısma snapshot",
            "yarışma snapshot",
            "mevzuatın guncelligi yururlugu dogrulanmamıstır",
            "hukuki dayanak kullanılamaz",
            "model onbilgisi",
            "kaynak yetersiz",
        )
        return paragraph == COMPETITION_SNAPSHOT_NOTICE or any(
            marker in normalized for marker in internal_markers
        )

    def _build_draft_and_finalize(
        self,
        state: ProcessState,
        *,
        compile_pdf: bool,
        supplied_fields: dict[str, str] | None,
    ) -> ProcessState:
        assert state.analysis is not None
        assert state.template_decision is not None
        assert state.routing is not None
        self._transition(
            state,
            ProcessStatus.DRAFTING,
            "Yapılandırılmış resmî yazı taslağı hazırlanıyor.",
            self.drafter.name,
        )
        references = self._layer3_references(state)
        target = state.selected_delivery_target
        targets = (
            ["citizen", "internal_unit"]
            if target == "both"
            else [target]
            if target in {"citizen", "internal_unit"}
            else [None]
        )
        outputs: list[Layer3DraftOutput] = []
        primary_decision = state.template_decision
        for output_target in targets:
            if output_target == "citizen":
                template_id = (
                    "eksik_bilgi_talebi_v1"
                    if state.analysis.missing_fields
                    else "cevap_yazisi_v1"
                )
                decision = state.template_decision.model_copy(
                    update={
                        "document_type": self.template_selector._document_type_for(
                            template_id
                        ),
                        "template_id": template_id,
                        "rationale": (
                            state.template_decision.rationale
                            + " Kullanıcı vatandaşa/dış başvuru sahibine cevap seçti."
                        ),
                    }
                )
                label = "Vatandaşa cevap"
            elif output_target == "internal_unit":
                decision = state.template_decision.model_copy(
                    update={
                        "document_type": self.template_selector._document_type_for(
                            "ust_yazi_v1"
                        ),
                        "template_id": "ust_yazi_v1",
                        "rationale": (
                            state.template_decision.rationale
                            + " Kullanıcı alt birime havale/üst yazı seçti."
                        ),
                    }
                )
                label = "Alt birime üst yazı"
            else:
                decision = state.template_decision
                label = "Resmî yazı taslağı"

            state.template_decision = decision
            state.draft = self.drafter.run(
                state.analysis,
                decision,
                state.routing,
                references,
            )
            if output_target == "citizen":
                applicant = state.analysis.fields.get("gonderen")
                if applicant is not None and applicant.value:
                    state.draft.recipient = applicant.model_copy(deep=True)
            elif output_target == "internal_unit":
                state.draft.interest = [
                    f"{state.document_id} kimlikli gelen başvuru"
                ]
                if state.source_name:
                    state.draft.attachments = [state.source_name]
            if supplied_fields:
                self._apply_draft_fields(state, supplied_fields)

            if self.settings.layer3_enabled and (
                state.selected_response_strategy is not None
                or state.selected_response_custom_text
            ):
                if state.selected_response_strategy is not None:
                    selected_ids = set(
                        state.selected_response_strategy.reference_ids
                    )
                    strategy_references = [
                        reference
                        for reference in references
                        if not selected_ids or reference.chunk_id in selected_ids
                    ]
                else:
                    strategy_references = references
                fill_outcome = self.llm_template_filler.run(
                    analysis=state.analysis,
                    template_id=decision.template_id,
                    template_structure=self._template_structure(
                        decision.template_id
                    ),
                    authority_relation=state.draft.authority_relation,
                    verified_references=strategy_references,
                    response_strategy=state.selected_response_strategy,
                    response_custom_text=state.selected_response_custom_text,
                    data_classification=self._llm_adjudication_data_classification(
                        state
                    ),
                )
                fill_applied = self._apply_llm_template_fill(state, fill_outcome)
                self._record_llm_step(
                    state,
                    role="llm4_template_fill",
                    outcome=fill_outcome.call,
                    selected_template_id=decision.template_id,
                    accepted_reference_ids=[
                        reference.chunk_id for reference in strategy_references
                    ],
                    decision_applied=fill_applied,
                    data_classification=self._llm_adjudication_data_classification(
                        state
                    ),
                    decision_summary=label,
                )

            output_key = output_target or "default"
            artifact = self.renderer.render(
                f"{state.document_id}-{output_key}",
                state.draft,
                compile_pdf=compile_pdf,
            )
            artifact.tex_download_url = (
                f"/api/v1/processes/{state.document_id}/artifacts/"
                f"{output_key}/tex"
            )
            if artifact.pdf_path:
                artifact.pdf_download_url = (
                    f"/api/v1/processes/{state.document_id}/artifacts/"
                    f"{output_key}/pdf"
                )
            compliance = self.compliance.run(state.draft, decision)
            outputs.append(
                Layer3DraftOutput(
                    target=(
                        output_target
                        if output_target in {"citizen", "internal_unit"}
                        else "citizen"
                    ),
                    label=label,
                    template_id=decision.template_id,
                    draft=state.draft.model_copy(deep=True),
                    artifact=artifact,
                    compliance=compliance,
                )
            )
            if len(outputs) == 1:
                primary_decision = decision

        state.layer3_outputs = outputs
        state.template_decision = primary_decision
        state.draft = outputs[0].draft
        state.artifact = outputs[0].artifact
        state.compliance = outputs[0].compliance
        self._complete(
            state,
            f"{len(outputs)} güvenli LaTeX taslağı üretildi.",
        )
        self._transition(
            state,
            ProcessStatus.COMPLIANCE,
            "Tüm taslaklar biçim, kaynak ve zorunlu alan kurallarına göre denetlendi.",
            self.compliance.name,
        )
        self._complete(
            state,
            "Taslak uygunluk skorları: "
            + ", ".join(
                f"{output.label}={output.compliance.score:.2f}"
                for output in outputs
            ),
        )
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
        if self.settings.external_llm_redacted_input_enabled:
            return DataClassification.REDACTED
        return DataClassification.RESTRICTED

    def _llm_adjudication_data_classification(
        self,
        state: ProcessState,
    ) -> DataClassification:
        input_classification = self._llm_data_classification(state.raw_text or "")
        if input_classification is DataClassification.RESTRICTED:
            return DataClassification.RESTRICTED
        disclosure = self.corpus_disclosure()
        verified = [
            reference for reference in state.verified_references if reference.verified
        ]
        if not verified or disclosure.get("corpus_contract_valid") is not True:
            return DataClassification.RESTRICTED
        corpus_mode = disclosure.get("corpus_mode")
        if corpus_mode == CorpusMode.TRUSTED_SYNTHETIC.value and all(
            reference.source_kind in {"synthetic", "curated_requirement_rule"}
            for reference in verified
        ):
            return DataClassification.SYNTHETIC
        if corpus_mode == CorpusMode.COMPETITION_SNAPSHOT.value and all(
            reference.source_kind == "curated_requirement_rule"
            or (
                reference.source_kind == CorpusMode.COMPETITION_SNAPSHOT.value
                and reference.currentness_verified is False
                and reference.legal_reliance_allowed is False
            )
            for reference in verified
        ):
            # Snapshot excerpts are public corpus material but are explicitly
            # marked as not currentness-verified; real document lines remain redacted.
            return (
                DataClassification.PUBLIC
                if input_classification is DataClassification.SYNTHETIC
                else DataClassification.REDACTED
            )
        return DataClassification.RESTRICTED

    def _new_llm_trace(self, classification: DataClassification) -> LLMRunTrace:
        config = self.llm_gateway.config
        local_execution = bool(getattr(config, "is_local", False))
        return LLMRunTrace(
            mode=(
                "guarded_structured_local"
                if local_execution
                else "guarded_structured_external"
            ),
            enabled=bool(config.enabled),
            provider=str(config.provider.value),
            model=config.model,
            external_data_allowed=(
                not local_execution
                and classification is not DataClassification.RESTRICTED
            ),
            local_execution=local_execution,
            warning=(
                "Yerel Ollama kullanılıyor; evrak verisi cihaz dışına gönderilmez."
                if local_execution
                else None
                if classification in {
                    DataClassification.SYNTHETIC,
                    DataClassification.PUBLIC,
                    DataClassification.REDACTED,
                }
                else (
                    "Gerçek/kısıtlı evrak harici ücretsiz LLM API'sine gönderilmedi; "
                    "yerel deterministik akış kullanıldı."
                )
            ),
        )

    def _record_llm_step(
        self,
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
        decision_summary: str | None = None,
        decision_checks: list[LLMDecisionCheck] | None = None,
        findings: list[LLMFindingTrace] | None = None,
        repair_attempted: bool = False,
        repair_succeeded: bool = False,
        repair_status: str | None = None,
        repair_detail: str | None = None,
    ) -> None:
        assert state.llm_trace is not None
        local_execution = bool(
            getattr(self.llm_gateway.config, "is_local", False)
        )
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
                    not local_execution
                    and data_classification is not DataClassification.RESTRICTED
                ),
                local_execution=local_execution,
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
                decision_summary=decision_summary,
                decision_checks=decision_checks or [],
                findings=findings or [],
                repair_attempted=repair_attempted,
                repair_succeeded=repair_succeeded,
                repair_status=repair_status,
                repair_detail=repair_detail,
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
            and not local_execution
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
        classification_references: list,
        document_type_candidates: dict[str, str],
    ) -> tuple[bool, list[LLMDecisionCheck]]:
        checks = self._understanding_decision_checks(
            state,
            outcome,
            classification_references,
            document_type_candidates,
        )
        if not outcome.call.succeeded or state.analysis is None:
            return False, checks
        source_text = state.raw_text or ""
        normalized_source = normalize_for_search(source_text)
        cited_ids = set(outcome.rag_reference_ids)
        classification_grounded = all(check.passed for check in checks)
        if classification_grounded:
            state.analysis.document_type = outcome.document_type
            if outcome.general_document_type:
                state.analysis.general_document_type = outcome.general_document_type
            state.analysis.document_subtype = outcome.document_subtype
            state.analysis.operational_category = (
                outcome.operational_category or outcome.document_type
            )
            state.analysis.confidence = outcome.confidence
            state.analysis.classification_reference_ids = sorted(cited_ids)
            state.analysis.important_facts = list(outcome.important_facts)
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
        return classification_grounded, checks

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
        candidates.add("eksik_bilgi_talebi_v1")
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

    def _understanding_decision_checks(
        self,
        state: ProcessState,
        outcome: UnderstandingOutcome,
        classification_references: list,
        document_type_candidates: dict[str, str],
    ) -> list[LLMDecisionCheck]:
        verified_ids = {
            reference.chunk_id
            for reference in classification_references
            if reference.verified
        }
        candidate_ids = set(document_type_candidates)
        cited_ids = set(outcome.rag_reference_ids)
        allowed_reference_ids = verified_ids | candidate_ids
        allowed_general_types = set(COMPETITION_DOCUMENT_TYPES)
        confidence_passed = (
            outcome.confidence is not None and outcome.confidence >= 0.75
        )
        return [
            LLMDecisionCheck(
                name="structured_response",
                passed=outcome.call.succeeded,
                detail=(
                    "Kapalı JSON şeması doğrulandı."
                    if outcome.call.succeeded
                    else "Geçerli yapılandırılmış LLM yanıtı alınamadı."
                ),
            ),
            LLMDecisionCheck(
                name="classification_confidence",
                passed=confidence_passed,
                detail="Sınıflandırma güveni en az %75 olmalıdır.",
                observed_score=outcome.confidence,
                required_score=0.75,
            ),
            LLMDecisionCheck(
                name="reference_allowlist",
                passed=bool(cited_ids) and cited_ids <= allowed_reference_ids,
                detail=(
                    f"{len(cited_ids)} atıfın tamamı sunucu aday kümesinde olmalıdır."
                ),
            ),
            LLMDecisionCheck(
                name="verified_legal_evidence",
                passed=bool(cited_ids & verified_ids),
                detail=(
                    f"En az bir doğrulanmış mevzuat kaynağı gerekir; "
                    f"eşleşen kaynak: {len(cited_ids & verified_ids)}."
                ),
            ),
            LLMDecisionCheck(
                name="document_type_allowlist",
                passed=outcome.document_type in allowed_general_types,
                detail="Evrak türü altılı kapalı yarışma sınıfından seçilmelidir.",
            ),
            LLMDecisionCheck(
                name="general_type_allowlist",
                passed=(
                    outcome.general_document_type in allowed_general_types
                    and outcome.general_document_type == outcome.document_type
                ),
                detail="Genel ve ana evrak türü aynı altılı kapalı sınıfta olmalıdır.",
            ),
        ]

    @staticmethod
    def _understanding_decision_summary(
        outcome: UnderstandingOutcome, applied: bool
    ) -> str | None:
        if not outcome.call.succeeded:
            return None
        proposed = " / ".join(
            item
            for item in (outcome.general_document_type, outcome.document_type)
            if item
        ) or "belirsiz sınıf"
        result = "uygulandı" if applied else "reddedildi; deterministik sınıf korundu"
        return f"LLM {proposed} sınıfını önerdi; sunucu doğrulaması sonucunda öneri {result}."

    @staticmethod
    def _understanding_findings(
        outcome: UnderstandingOutcome, applied: bool
    ) -> list[LLMFindingTrace]:
        if not outcome.call.succeeded:
            return []
        reference_ids = list(outcome.rag_reference_ids)
        status = "accepted" if applied else "rejected"
        findings = [
            LLMFindingTrace(
                kind="classification",
                label="Evrak sınıflandırması",
                finding=" / ".join(
                    item
                    for item in (
                        outcome.general_document_type,
                        outcome.document_type,
                    )
                    if item
                ),
                confidence=outcome.confidence,
                score_basis="agent_overall_confidence",
                status=status,
                legal_reference_ids=reference_ids,
            )
        ]
        findings.extend(
            LLMFindingTrace(
                kind="fact",
                label="Önemli olgu",
                finding=fact,
                confidence=outcome.confidence,
                score_basis="agent_overall_confidence",
                status=status,
                legal_reference_ids=reference_ids,
            )
            for fact in outcome.important_facts
        )
        return findings

    def _adjudication_decision_checks(
        self,
        state: ProcessState,
        outcome: AdjudicationOutcome,
    ) -> list[LLMDecisionCheck]:
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
        accepted_ids = set(outcome.accepted_reference_ids)
        return [
            LLMDecisionCheck(
                name="structured_response",
                passed=outcome.call.succeeded,
                detail="Kapalı JSON şeması doğrulaması tamamlanmalıdır.",
            ),
            LLMDecisionCheck(
                name="adjudication_confidence",
                passed=(
                    outcome.confidence is not None
                    and outcome.confidence >= self.LLM_ADJUDICATION_MIN_CONFIDENCE
                ),
                detail="Karar güveni otomatik uygulama eşiğini geçmelidir.",
                observed_score=outcome.confidence,
                required_score=self.LLM_ADJUDICATION_MIN_CONFIDENCE,
            ),
            LLMDecisionCheck(
                name="human_review",
                passed=not outcome.requires_human_review,
                detail="LLM açıkça insan incelemesi istememelidir.",
            ),
            LLMDecisionCheck(
                name="claim_validation",
                passed=not outcome.unsupported_claims,
                detail=f"Desteksiz iddia sayısı: {len(outcome.unsupported_claims)}.",
            ),
            LLMDecisionCheck(
                name="verified_references",
                passed=bool(accepted_ids) and accepted_ids <= verified_ids,
                detail=(
                    f"Kabul edilen {len(accepted_ids)} kaynak Auditor kümesinin "
                    "boş olmayan bir alt kümesi olmalıdır."
                ),
            ),
            LLMDecisionCheck(
                name="template_allowlist",
                passed=outcome.selected_template_id in self._allowed_template_ids(state),
                detail="Şablon sunucu allowlist kümesinde bulunmalıdır.",
            ),
            LLMDecisionCheck(
                name="unit_allowlist",
                passed=outcome.selected_unit_id in self._allowed_unit_ids(state),
                detail="Birim sunucu allowlist kümesinde bulunmalıdır.",
            ),
            LLMDecisionCheck(
                name="graph_template_support",
                passed=graph_template_supported,
                detail="Şablon etkin kanıt grafı adaylarıyla çelişmemelidir.",
            ),
            LLMDecisionCheck(
                name="graph_unit_support",
                passed=graph_unit_supported,
                detail="Birim etkin kanıt grafı adaylarıyla çelişmemelidir.",
            ),
        ]

    @staticmethod
    def _adjudication_decision_summary(
        outcome: AdjudicationOutcome, applied: bool
    ) -> str | None:
        if not outcome.call.succeeded:
            return None
        server_result = (
            "Öneri uygulandı."
            if applied
            else "Öneri uygulanmadı; deterministik karar korundu."
        )
        rationale = normalize_whitespace(outcome.rationale or "")
        repair_result = ""
        if outcome.repair_attempted:
            repair_result = (
                " Kanıt düzeltme turu başarılı oldu."
                if outcome.repair_succeeded
                else " Kanıt düzeltme turu yapıldı ancak doğrulama hataları giderilemedi."
            )
        return f"{rationale} {server_result}{repair_result}".strip()

    @staticmethod
    def _adjudication_findings(
        outcome: AdjudicationOutcome,
    ) -> list[LLMFindingTrace]:
        findings = [
            LLMFindingTrace(
                kind="requirement",
                label=requirement.field,
                finding=requirement.requirement,
                confidence=requirement.confidence,
                score_basis="finding_confidence",
                status="accepted",
                document_evidence_ids=list(requirement.document_evidence_ids),
                legal_reference_ids=list(requirement.legal_reference_ids),
                legal_evidence=requirement.legal_evidence,
                legal_support_score=requirement.legal_support_score,
                document_presence_score=requirement.document_presence_score,
                coordinate_confidence=requirement.coordinate_confidence,
            )
            for requirement in outcome.requirements
        ]
        findings.extend(
            LLMFindingTrace(
                kind="result",
                label="Önemli sonuç",
                finding=result,
                confidence=outcome.confidence,
                score_basis="agent_overall_confidence",
                status="informational",
                legal_reference_ids=list(outcome.accepted_reference_ids),
            )
            for result in outcome.important_results
        )
        findings.extend(
            LLMFindingTrace(
                kind="validation_warning",
                label="Sunucu doğrulaması",
                finding=warning,
                confidence=0.0,
                score_basis="server_validation",
                status="rejected",
            )
            for warning in outcome.unsupported_claims
        )
        return findings

    def _apply_llm_adjudication(
        self,
        state: ProcessState,
        outcome: AdjudicationOutcome,
        *,
        decision_checks: list[LLMDecisionCheck] | None = None,
    ) -> bool:
        assert state.template_decision is not None
        assert state.routing is not None
        allowed_template_ids = set(self._allowed_template_ids(state))
        allowed_unit_ids = set(self._allowed_unit_ids(state))
        checks = decision_checks or self._adjudication_decision_checks(state, outcome)
        safe_to_apply = all(check.passed for check in checks)
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
            state.routing = previous_routing.model_copy(
                update={
                    "unit_id": unit.unit_id,
                    "unit_name": unit.unit_name,
                    "hierarchy": unit.hierarchy,
                    "rationale": (
                        previous_routing.rationale
                        + " Yapılandırılmış Adjudicator değerlendirmesi: "
                        + (outcome.rationale or "gerekçe sağlanmadı")
                    ),
                    "score": round(routing_confidence, 2),
                    "requires_human_review": (
                        previous_routing.requires_human_review
                        or outcome.requires_human_review
                    ),
                    "routing_status": (
                        "needs_review"
                        if previous_routing.requires_human_review
                        or outcome.requires_human_review
                        else "proposed"
                    ),
                }
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
            document_type=(
                state.analysis.operational_category or state.analysis.document_type
            ),
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
        for external_name, attribute_name in self.DRAFT_LIST_FIELD_MAP.items():
            value = fields.get(external_name)
            if value:
                setattr(
                    state.draft,
                    attribute_name,
                    [item.strip() for item in value.split(";") if item.strip()],
                )
        if fields.get("makam_iliskisi"):
            state.draft.authority_relation = fields["makam_iliskisi"]
        if fields.get("kapanis"):
            previous = state.draft.closing
            state.draft.closing = fields["kapanis"]
            if state.draft.paragraphs and state.draft.paragraphs[-1] == previous:
                state.draft.paragraphs[-1] = state.draft.closing
        state.draft.missing_fields = [
            name for name in state.draft.missing_fields if name not in fields
        ]

    def _finalize_user_message(self, state: ProcessState) -> None:
        assert state.draft is not None
        assert state.compliance is not None
        missing = list(
            dict.fromkeys(
                [
                    *state.draft.missing_fields,
                    *[
                        field_name
                        for output in state.layer3_outputs
                        for field_name in output.draft.missing_fields
                    ],
                ]
            )
        )
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
        elif not state.compliance.passed or any(
            not output.compliance.passed for output in state.layer3_outputs
        ):
            compliance_errors = [
                error
                for output in state.layer3_outputs
                for error in output.compliance.errors
            ] or state.compliance.errors or [
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
