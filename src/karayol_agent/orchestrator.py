from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import replace
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
from karayol_agent.agents.layout import LayoutGapDetector
from karayol_agent.agents.legislation import RankedRetriever
from karayol_agent.agents.llm_layer2 import (
    SearchO1AdjudicatorAgent,
    SearchO1AuditorAgent,
    SearchO1ResearchAgent,
)
from karayol_agent.agents.llm_layer1 import (
    ClassificationOutcome,
    DocumentTypeCatalog,
    LLMClassificationAgent,
    LLMRequiredDataAgent,
    RequiredDataOutcome,
)
from karayol_agent.agents.llm_layer3 import (
    CUSTOM_RESPONSE_STRATEGY_OPTION_ID,
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
from karayol_agent.agents.llm_roles import (
    AdjudicationOutcome,
    LLMAdjudicatorAgent,
    StructuredGateway,
)
from karayol_agent.config import Settings, settings
from karayol_agent.documents import DocumentExtractor, OcrWord
from karayol_agent.graph import EvidenceGraphAdvisor, GraphBuildError
from karayol_agent.llm import (
    DataClassification,
    LLMConfig,
    LLMProviderName,
    StructuredLLMGateway,
)
from karayol_agent.llm.agentic_gateway import AgenticGatewayError, AgenticToolLLMGateway
from karayol_agent.latex import LatexRenderer
from karayol_agent.official_writing_rules import closing_matches_authority_relation
from karayol_agent.retrieval import (
    AnalysisAwareDeterministicReranker,
    AnalysisAwareTextRetrieverAdapter,
    BM25Index,
    LegislationRepository,
)
from karayol_agent.retrieval.article_context import build_article_index
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
    LLMRunTrace,
    LLMStepTrace,
    ProcessState,
    ProcessStatus,
    ResponseStrategyOption,
    RoutingRecommendation,
    TemplateDecision,
    VerifiedReference,
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
        self.llm_gateway = llm_gateway or StructuredLLMGateway(LLMConfig.from_env())
        self.document_type_catalog = DocumentTypeCatalog.load(
            app_settings.document_type_catalog_path
        )
        self.llm_classifier = LLMClassificationAgent(
            self.llm_gateway, self.document_type_catalog
        )
        self.llm_required_data = LLMRequiredDataAgent(self.llm_gateway)
        self.layout_gap_detector = LayoutGapDetector()
        self.llm_adjudicator = LLMAdjudicatorAgent(self.llm_gateway)
        self.synthetic_document_fingerprints = self._load_synthetic_fingerprints()
        self.researcher = LegislationResearchAgent(
            self.retriever, top_k=app_settings.retrieval_top_k
        )
        self.verifier = SourceVerificationAgent(
            min_retrieval_score=app_settings.min_retrieval_score,
            article_index=build_article_index(
                document.chunk for document in self.index.documents
            ),
        )
        (
            self.search_o1_researcher,
            self.search_o1_auditor,
            self.search_o1_adjudicator,
        ) = self._build_search_o1_agents(
            app_settings, caller_supplied_gateway=llm_gateway is not None
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
        organization_units_path = (
            app_settings.organization_units_path
            or app_settings.data_dir
            / "organization"
            / "kgm_units_2026-07-16.json"
        )
        self.router = RoutingAgent(organization_units_path)
        self.template_catalog = TemplateCatalog.load(app_settings.template_catalog_path)
        self.llm_template_selector = LLMTemplateSelectionAgent(
            self.llm_gateway, self.template_catalog
        )
        self.llm_router = LLMRoutingAgent(self.llm_gateway)
        self.llm_response_strategy = LLMResponseStrategyAgent(self.llm_gateway)
        self.llm_template_filler = LLMTemplateFillAgent(self.llm_gateway)
        self.drafter = DraftingAgent()
        self.compliance = ComplianceAgent()
        self.renderer = LatexRenderer(
            app_settings.templates_dir,
            app_settings.output_dir,
            timeout=app_settings.latex_timeout_seconds,
        )
        self.store = FileProcessStore(app_settings.runtime_dir / "processes")

    def _build_search_o1_agents(
        self, app_settings: Settings, *, caller_supplied_gateway: bool
    ) -> tuple[
        SearchO1ResearchAgent | None,
        SearchO1AuditorAgent | None,
        SearchO1AdjudicatorAgent | None,
    ]:
        """Build KATMAN 2's Search-o1 agents, or (None, None, None).

        Native tool-calling only works against the OpenAI-compatible wire
        format, and only makes sense once a real API key is configured. Any
        other provider (e.g. the local Ollama default used by most tests and
        offline dev) silently falls back to the existing deterministic
        Researcher/Auditor + single-shot Adjudicator — no behavior change for
        those environments.

        Also skipped whenever the caller explicitly injected their own
        ``llm_gateway`` (e.g. every test's fake/no-network gateway double) —
        that always means "I am taking full control of LLM behaviour for
        this orchestrator instance", so a second, independent, real-network
        gateway must never be spun up on the side just because the fake's
        ``.config`` happens to duck-type as OpenAI-compatible.
        """

        if not app_settings.search_o1_enabled or caller_supplied_gateway:
            return None, None, None
        base_config = self.llm_gateway.config
        if (
            base_config.provider
            not in {LLMProviderName.OPENAI_COMPATIBLE, LLMProviderName.GROQ}
            or not base_config.api_key
        ):
            return None, None, None
        try:
            katman2_config = LLMConfig(
                provider=base_config.provider,
                model=app_settings.search_o1_model,
                api_key=base_config.api_key,
                base_url=base_config.base_url,
                timeout_seconds=base_config.timeout_seconds,
                max_output_tokens=base_config.max_output_tokens,
                temperature=base_config.temperature,
                max_input_chars=base_config.max_input_chars,
                runtime_enabled=base_config.runtime_enabled,
                allow_restricted_external=base_config.allow_restricted_external,
            )
            katman2_gateway = AgenticToolLLMGateway(katman2_config)
        except (ValueError, AgenticGatewayError):
            return None, None, None
        return (
            SearchO1ResearchAgent(
                katman2_gateway,
                self.researcher,
                self.verifier,
                max_turns=app_settings.search_o1_researcher_max_turns,
            ),
            SearchO1AuditorAgent(
                katman2_gateway,
                self.researcher,
                self.verifier,
                max_turns=app_settings.search_o1_auditor_max_turns,
            ),
            SearchO1AdjudicatorAgent(
                katman2_gateway,
                self.researcher,
                self.verifier,
                max_turns=app_settings.search_o1_adjudicator_max_turns,
            ),
        )

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
                "explicit_restricted_external_opt_in"
                if getattr(self.llm_gateway.config, "allow_restricted_external", False)
                else "pinned_synthetic_input_closed_public_metadata"
            ),
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
        extracted = self.extractor.extract_with_layout(path)
        return self.process_text(
            extracted.text,
            source_name=path.name,
            compile_pdf=compile_pdf,
            layout_words=extracted.words,
        )

    def process_text(
        self,
        text: str,
        *,
        source_name: str = "kullanici_metni.txt",
        compile_pdf: bool = False,
        layout_words: Sequence[OcrWord] = (),
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

            classification_outcome = self.llm_classifier.run(
                text=state.raw_text or "",
                deterministic_classification=classification,
                data_classification=data_classification,
            )
            self._record_llm_step(
                state,
                role="llm1_classification",
                outcome=classification_outcome.call,
                confidence=classification_outcome.confidence,
                candidate_document_type=classification_outcome.document_type,
                data_classification=data_classification,
            )
            self._apply_llm_classification(state, classification_outcome)

            requirement_references = self._requirement_references(state)
            layout_gap_candidates = self.layout_gap_detector.detect(layout_words)
            required_data_outcome = self.llm_required_data.run(
                text=state.raw_text or "",
                document_type=state.analysis.general_document_type,
                static_missing_fields=state.analysis.missing_fields,
                requirement_references=requirement_references,
                layout_gap_candidates=layout_gap_candidates,
                data_classification=data_classification,
            )
            self._record_llm_step(
                state,
                role="llm2_required_data",
                outcome=required_data_outcome.call,
                confidence=required_data_outcome.confidence,
                data_classification=data_classification,
            )
            self._apply_llm_required_data(state, required_data_outcome)

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

    def choose_response_strategy(
        self,
        document_id: str,
        *,
        option_id: str | None = None,
        custom_text: str | None = None,
        compile_pdf: bool = False,
    ) -> ProcessState:
        state = self._require_state(document_id)
        if state.status == ProcessStatus.COMPLETED:
            raise ProcessValidationError(
                "Tamamlanmış evrak değiştirilemez; değişiklik için yeni bir "
                "revizyon oluşturulmalıdır."
            )
        if not state.response_strategy_options:
            raise ProcessValidationError(
                "Süreçte seçilebilir bir yanıt stratejisi bulunmuyor."
            )
        clean_option_id = (option_id or "").strip() or None
        clean_custom_text = (custom_text or "").strip() or None
        if clean_option_id == CUSTOM_RESPONSE_STRATEGY_OPTION_ID:
            if not clean_custom_text:
                raise ProcessValidationError(
                    "'"
                    + CUSTOM_RESPONSE_STRATEGY_OPTION_ID
                    + "' seçeneği için custom_text zorunludur."
                )
            state.selected_response_strategy = None
            state.selected_response_custom_text = clean_custom_text
        elif clean_option_id:
            matched = next(
                (
                    option
                    for option in state.response_strategy_options
                    if option.option_id == clean_option_id
                ),
                None,
            )
            if matched is None:
                raise ProcessValidationError(
                    "Bilinmeyen yanıt stratejisi seçeneği: " + clean_option_id
                )
            state.selected_response_strategy = matched
            state.selected_response_custom_text = None
        elif clean_custom_text:
            state.selected_response_strategy = None
            state.selected_response_custom_text = clean_custom_text
        else:
            raise ProcessValidationError(
                "option_id veya custom_text alanlarından biri sağlanmalıdır."
            )
        state.add_event(
            ProcessStatus.DRAFTING,
            "Kullanıcı yanıt stratejisini belirledi; taslak yeniden hazırlanıyor.",
            "Kullanıcı Bilgilendirme Ajanı",
        )
        self.store.save(state)
        return self._continue_pipeline(
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
        if not state.compliance.passed:
            raise ProcessValidationError("Uygunluk denetimini geçmeyen taslak onaylanamaz.")
        if (
            state.response_strategy_options
            and state.selected_response_strategy is None
            and not state.selected_response_custom_text
        ):
            raise ProcessValidationError(
                "Yanıt stratejisi seçilmeden taslak onaylanamaz."
            )
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
        if state.llm_trace is None:
            state.llm_trace = self._new_llm_trace(
                self._llm_data_classification(state.raw_text or "")
            )
        base_classification = self._llm_data_classification(state.raw_text or "")

        self._transition(
            state,
            ProcessStatus.SEARCHING,
            "İlgili mevzuat ve iş akışı kuralları aranıyor.",
            self.researcher.name,
        )
        if self.search_o1_researcher is not None:
            research_outcome = self.search_o1_researcher.run(
                state.analysis, data_classification=base_classification
            )
            retrieval_hits = research_outcome.hits
            retrieval_diagnostics = research_outcome.diagnostics
            self._record_llm_step(
                state,
                role="katman2_researcher_search_o1",
                outcome=research_outcome.call,
                data_classification=base_classification,
            )
        else:
            retrieval = self.researcher.run_with_diagnostics(state.analysis)
            retrieval_hits = retrieval.hits
            retrieval_diagnostics = retrieval.diagnostics
        state.search_hits = retrieval_hits
        diagnostics = retrieval_diagnostics
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
        auditor_requires_review = False
        if self.search_o1_auditor is not None:
            audit_outcome = self.search_o1_auditor.run(
                state.search_hits, state.analysis, data_classification=base_classification
            )
            state.verified_references = audit_outcome.references
            auditor_requires_review = audit_outcome.requires_human_review
            self._record_llm_step(
                state,
                role="katman2_auditor_search_o1",
                outcome=audit_outcome.call,
                human_review_required=audit_outcome.requires_human_review,
                data_classification=base_classification,
            )
            if audit_outcome.concern_notes:
                self._complete(
                    state,
                    "Search-o1 Auditor ek inceleme notu: " + audit_outcome.concern_notes,
                )
        else:
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

        adjudication_classification = self._llm_adjudication_data_classification(
            state
        )

        self._transition(
            state,
            ProcessStatus.VERIFYING,
            "Yalnız doğrulanmış kanıtlarla kanıt kümesi değerlendiriliyor.",
            self.llm_adjudicator.name,
        )
        if self.search_o1_adjudicator is not None:
            adjudication = self.search_o1_adjudicator.run(
                analysis=state.analysis,
                references=state.verified_references,
                data_classification=adjudication_classification,
            )
        else:
            adjudication = self.llm_adjudicator.run(
                analysis=state.analysis,
                references=state.verified_references,
                data_classification=adjudication_classification,
            )
        if auditor_requires_review:
            adjudication = replace(adjudication, requires_human_review=True)
        adjudication_applied = self._apply_llm_evidence_synthesis(state, adjudication)
        self._record_llm_step(
            state,
            role="adjudicator",
            outcome=adjudication.call,
            confidence=adjudication.confidence,
            accepted_reference_ids=list(adjudication.accepted_reference_ids),
            human_review_required=(
                adjudication.requires_human_review
                or bool(adjudication.unsupported_claims)
                or not adjudication_applied
            ),
            decision_applied=adjudication_applied,
            data_classification=adjudication_classification,
        )
        self._complete(
            state,
            "Adjudicator kanıt kümesini onayladı."
            if adjudication_applied
            else "Adjudicator kararı uygulanmadı; denetlenebilir kanıt sırası korundu.",
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
        template_selection = self.llm_template_selector.run(
            analysis=state.analysis,
            deterministic_decision=state.template_decision,
            verified_references=state.verified_references,
            allowed_template_ids=self._allowed_template_ids(state),
            data_classification=adjudication_classification,
        )
        template_applied = self._apply_llm_template_selection(state, template_selection)
        self._record_llm_step(
            state,
            role="llm3_template_selection",
            outcome=template_selection.call,
            confidence=template_selection.confidence,
            selected_template_id=template_selection.selected_template_id,
            human_review_required=(
                template_selection.requires_human_review or not template_applied
            ),
            decision_applied=template_applied,
            data_classification=adjudication_classification,
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
        )
        self._complete(state, f"Önerilen birim: {state.routing.unit_name}.")

        if not state.analysis.missing_fields and not state.response_strategy_options:
            strategy_proposal = self.llm_response_strategy.run(
                analysis=state.analysis,
                verified_references=state.verified_references,
                data_classification=adjudication_classification,
            )
            self._apply_response_strategy_options(state, strategy_proposal)
            self._record_llm_step(
                state,
                role="llm6_response_strategy",
                outcome=strategy_proposal.call,
                data_classification=adjudication_classification,
            )

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
        if (
            state.selected_response_strategy is not None
            or state.selected_response_custom_text
        ):
            fill_outcome = self.llm_template_filler.run(
                analysis=state.analysis,
                template_id=state.template_decision.template_id,
                template_tex_reference=self._template_tex_reference(
                    state.template_decision.template_id
                ),
                authority_relation=state.draft.authority_relation,
                verified_references=state.verified_references,
                response_strategy=state.selected_response_strategy,
                response_custom_text=state.selected_response_custom_text,
                data_classification=adjudication_classification,
            )
            fill_applied = self._apply_llm_template_fill(state, fill_outcome)
            self._record_llm_step(
                state,
                role="llm4_template_fill",
                outcome=fill_outcome.call,
                decision_applied=fill_applied,
                data_classification=adjudication_classification,
            )
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
        local_execution = bool(getattr(config, "is_local", False))
        restricted_external_allowed = bool(
            getattr(config, "allow_restricted_external", False)
        )
        network_allowed = (
            classification is not DataClassification.RESTRICTED
            or restricted_external_allowed
        )
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
                not local_execution and network_allowed
            ),
            local_execution=local_execution,
            warning=(
                "Yerel Ollama kullanılıyor; evrak verisi cihaz dışına gönderilmez."
                if local_execution
                else None
                if network_allowed
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
    ) -> None:
        assert state.llm_trace is not None
        local_execution = bool(
            getattr(self.llm_gateway.config, "is_local", False)
        )
        restricted_external_allowed = bool(
            getattr(
                self.llm_gateway.config,
                "allow_restricted_external",
                False,
            )
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
                    and (
                        data_classification is not DataClassification.RESTRICTED
                        or restricted_external_allowed
                    )
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
            and not restricted_external_allowed
            and state.llm_trace.warning is None
        ):
            state.llm_trace.warning = (
                "En kısıtlı veri/provenance sınıfı nedeniyle ilgili LLM aşaması "
                "ağdan önce engellendi."
            )

    def _apply_llm_classification(
        self,
        state: ProcessState,
        outcome: ClassificationOutcome,
    ) -> None:
        if (
            not outcome.call.succeeded
            or state.analysis is None
            or outcome.document_type is None
            or not outcome.evidence_span
        ):
            return
        normalized_source = normalize_for_search(state.raw_text or "")
        normalized_evidence = normalize_for_search(outcome.evidence_span)
        if not normalized_evidence or normalized_evidence not in normalized_source:
            return
        # LLM1 yalnız kullanıcıya gösterilen genel evrak türünü (kullanıcının
        # ileride sağlayacağı gerçek katalogla değişecek) günceller. İç
        # operasyonel profil (document_type) — REQUIRED_FIELDS/şablon eşlemesi
        # bunun üzerinden çalıştığı için — deterministik sınıflandırıcının
        # çıktısı olarak kalır.
        state.analysis.general_document_type = outcome.document_type

    def _requirement_references(self, state: ProcessState) -> list[VerifiedReference]:
        """LLM2 için "bu evrak türünde ne gerekir" sorgusuyla ayrı bir tur.

        Ana ``SEARCHING``/``VERIFYING`` aşamalarından bağımsız, aynı
        Researcher/Auditor makinesini farklı bir sorguyla çalıştırır.
        """

        assert state.analysis is not None
        query = (
            f"{state.analysis.general_document_type} başvurusu için gerekli "
            "belgeler, zorunlu bilgiler ve ekler"
        )
        search = self.researcher.run_with_query(query, state.analysis)
        return self.verifier.run(search.hits, state.analysis)

    def _apply_llm_required_data(
        self,
        state: ProcessState,
        outcome: RequiredDataOutcome,
    ) -> None:
        if not outcome.call.succeeded or state.analysis is None:
            return
        for description in outcome.missing_data_points:
            if description not in state.analysis.missing_fields:
                state.analysis.missing_fields.append(description)

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

    def _apply_llm_evidence_synthesis(
        self,
        state: ProcessState,
        outcome: AdjudicationOutcome,
    ) -> bool:
        """KATMAN 2 Adjudicator: saf kanıt sentezi, şablon/birim seçmez."""

        verified_ids = {
            reference.chunk_id
            for reference in state.verified_references
            if reference.verified
        }
        safe_to_apply = (
            outcome.call.succeeded
            and outcome.confidence is not None
            and outcome.confidence >= self.LLM_ADJUDICATION_MIN_CONFIDENCE
            and not outcome.requires_human_review
            and not outcome.unsupported_claims
            and bool(outcome.accepted_reference_ids)
            and set(outcome.accepted_reference_ids) <= verified_ids
        )
        if not safe_to_apply:
            return False
        accepted = set(outcome.accepted_reference_ids)
        state.verified_references.sort(
            key=lambda reference: (
                reference.chunk_id not in accepted,
                -reference.score,
                reference.chunk_id,
            )
        )
        return True

    def _apply_llm_template_selection(
        self,
        state: ProcessState,
        outcome: TemplateSelectionOutcome,
    ) -> bool:
        assert state.template_decision is not None
        graph_trace = state.graph_decision_trace
        graph_supported = (
            not graph_trace
            or not graph_trace.applied
            or not graph_trace.candidate_template_ids
            or outcome.selected_template_id in graph_trace.candidate_template_ids
        )
        allowed_template_ids = set(self._allowed_template_ids(state))
        safe_to_apply = (
            outcome.call.succeeded
            and outcome.confidence is not None
            and outcome.confidence >= self.LLM_ADJUDICATION_MIN_CONFIDENCE
            and not outcome.requires_human_review
            and outcome.selected_template_id in allowed_template_ids
            and graph_supported
        )
        if not safe_to_apply:
            state.template_decision.user_approval_required = True
            state.template_decision.rationale += (
                " LLM3 şablon önerisi güven/kanıt kapısını geçmedi; "
                "deterministik seçim korundu ve insan incelemesi zorunlu kaldı."
            )
            return False
        previous = state.template_decision
        confidence = (
            outcome.confidence
            if outcome.confidence is not None
            else previous.confidence
        )
        state.template_decision = TemplateDecision(
            document_type=self.template_selector._document_type_for(
                outcome.selected_template_id
            ),
            template_id=outcome.selected_template_id,
            rationale=(
                previous.rationale
                + " Yapılandırılmış LLM3 değerlendirmesi: "
                + (outcome.rationale or "gerekçe sağlanmadı")
            ),
            confidence=round(confidence, 2),
            user_approval_required=(
                previous.user_approval_required
                or outcome.requires_human_review
                or confidence < self.settings.low_confidence_threshold
            ),
            alternatives=previous.alternatives,
        )
        return True

    def _apply_llm_routing(
        self,
        state: ProcessState,
        outcome: RoutingOutcome,
    ) -> bool:
        assert state.routing is not None
        graph_trace = state.graph_decision_trace
        graph_supported = (
            not graph_trace
            or not graph_trace.applied
            or not graph_trace.candidate_unit_ids
            or outcome.selected_unit_id in graph_trace.candidate_unit_ids
        )
        allowed_unit_ids = set(self._allowed_unit_ids(state))
        safe_to_apply = (
            outcome.call.succeeded
            and outcome.confidence is not None
            and outcome.confidence >= self.LLM_ADJUDICATION_MIN_CONFIDENCE
            and not outcome.requires_human_review
            and outcome.selected_unit_id in allowed_unit_ids
            and graph_supported
        )
        if not safe_to_apply:
            state.routing.rationale += (
                " LLM5 yönlendirme önerisi uygulanmadı; deterministik birim "
                "önerisi korundu."
            )
            return False
        unit = next(
            unit
            for unit in self.router.units
            if unit.unit_id == outcome.selected_unit_id
        )
        previous = state.routing
        confidence = (
            outcome.confidence if outcome.confidence is not None else previous.score
        )
        state.routing = previous.model_copy(
            update={
                "unit_id": unit.unit_id,
                "unit_name": unit.unit_name,
                "hierarchy": unit.hierarchy,
                "rationale": (
                    previous.rationale
                    + " Yapılandırılmış LLM5 değerlendirmesi: "
                    + (outcome.rationale or "gerekçe sağlanmadı")
                ),
                "score": round(confidence, 2),
            }
        )
        return True

    def _apply_response_strategy_options(
        self,
        state: ProcessState,
        outcome: ResponseStrategyProposalOutcome,
    ) -> None:
        options = list(outcome.options)
        options.append(
            ResponseStrategyOption(
                option_id=CUSTOM_RESPONSE_STRATEGY_OPTION_ID,
                label="Kendim yazacağım",
                description=(
                    "Sunulan seçeneklerin hiçbiri uygun değilse, yanıtın nasıl "
                    "olması gerektiğini kendi cümlelerinizle yazabilirsiniz."
                ),
            )
        )
        state.response_strategy_options = options

    def _template_tex_reference(self, template_id: str) -> str:
        tex_path = self.settings.templates_dir / template_id / "template.tex"
        try:
            return tex_path.read_text(encoding="utf-8")
        except OSError:
            return ""

    def _apply_llm_template_fill(
        self,
        state: ProcessState,
        outcome: TemplateFillOutcome,
    ) -> bool:
        assert state.draft is not None
        if not outcome.call.succeeded or not outcome.subject or not outcome.paragraphs:
            return False
        if outcome.closing is not None and not closing_matches_authority_relation(
            outcome.closing, state.draft.authority_relation
        ):
            return False
        state.draft.subject = ExtractedField(
            value=outcome.subject,
            status=FieldStatus.GENERATED,
            source="llm4_template_fill",
        )
        state.draft.paragraphs = list(outcome.paragraphs)
        if outcome.closing is not None:
            state.draft.closing = outcome.closing
            if state.draft.paragraphs:
                state.draft.paragraphs[-1] = outcome.closing
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
            # A structurally broken draft must be fixed before asking the user
            # anything about tone/strategy — that choice would apply to a
            # draft that can't be sent as-is anyway.
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
        elif (
            state.response_strategy_options
            and state.selected_response_strategy is None
            and not state.selected_response_custom_text
        ):
            option_labels = ", ".join(
                option.label for option in state.response_strategy_options
            )
            state.pending_actions = [
                "Yanıt stratejisi seçin: " + option_labels,
                "Seçeneklerden biri uygun değilse kendi metninizi yazabilirsiniz.",
            ]
            state.next_step = (
                "Taslağın nasıl bir yanıt vereceğini belirlemek için bir "
                "strateji seçiniz veya kendi metninizi giriniz."
            )
            state.possible_actions = ["yanit_stratejisi_sec"]
            state.add_event(
                ProcessStatus.WAITING_FOR_RESPONSE_STRATEGY,
                "İçerik eksiksiz; taslak hazırlanmadan önce yanıt stratejisi "
                "bekleniyor.",
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
