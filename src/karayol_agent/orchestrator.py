from __future__ import annotations

from datetime import datetime
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
from karayol_agent.config import Settings, settings
from karayol_agent.documents import DocumentExtractor
from karayol_agent.latex import LatexRenderer
from karayol_agent.retrieval import BM25Index, LegislationRepository
from karayol_agent.schemas import (
    ExtractedField,
    FieldStatus,
    ProcessState,
    ProcessStatus,
)
from karayol_agent.state_store import FileProcessStore


class ProcessNotFoundError(KeyError):
    pass


class ProcessValidationError(ValueError):
    pass


class EvrakOrchestrator:
    name = "Orkestratör"

    DRAFT_FIELD_MAP = {
        "tarih": "date",
        "sayi": "number",
        "konu": "subject",
        "muhatap": "recipient",
        "imzalayan": "signer",
        "unvan": "signer_title",
    }

    def __init__(self, app_settings: Settings = settings) -> None:
        self.settings = app_settings
        app_settings.ensure_runtime_dirs()
        chunks = LegislationRepository(
            app_settings.data_dir / "synthetic_legislation.json",
            trusted_synthetic=True,
        ).load()
        self.index = BM25Index(chunks)
        self.extractor = DocumentExtractor(max_chars=app_settings.max_text_chars)
        self.classifier = ClassificationAgent()
        self.analyzer = ContentAnalysisAgent()
        self.researcher = LegislationResearchAgent(
            self.index, top_k=app_settings.retrieval_top_k
        )
        self.verifier = SourceVerificationAgent()
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
        state.search_hits = self.researcher.run(state.analysis)
        self._complete(state, f"{len(state.search_hits)} kaynak adayı bulundu.")

        self._transition(
            state,
            ProcessStatus.VERIFYING,
            "Kaynak adaylarının sorguyla ilişkisi doğrulanıyor.",
            self.verifier.name,
        )
        state.verified_references = self.verifier.run(state.search_hits, state.analysis)
        verified_count = sum(reference.verified for reference in state.verified_references)
        self._complete(state, f"{verified_count} kaynak doğrulandı.")

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
