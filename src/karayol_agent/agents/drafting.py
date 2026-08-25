from __future__ import annotations

from karayol_agent.retrieval.contracts import (
    COMPETITION_SNAPSHOT_NOTICE,
    CorpusMode,
)
from karayol_agent.schemas import (
    DocumentAnalysis,
    DraftPayload,
    ExtractedField,
    FieldStatus,
    RoutingRecommendation,
    TemplateDecision,
    VerifiedReference,
)


class DraftingAgent:
    name = "Taslak Oluşturma Ajanı"

    def __init__(self, institution_name: str = "Örnek Karayolu Genel Müdürlüğü") -> None:
        self.institution_name = institution_name

    def run(
        self,
        analysis: DocumentAnalysis,
        decision: TemplateDecision,
        routing: RoutingRecommendation,
        references: list[VerifiedReference],
    ) -> DraftPayload:
        verified_references = [reference for reference in references if reference.verified]
        authority_relation, closing = self._official_closing(decision)
        paragraphs = self._paragraphs(
            analysis, decision, routing, verified_references, closing
        )
        missing = list(dict.fromkeys([*analysis.missing_fields, "sayi", "imzalayan", "unvan"]))
        contact_information = [
            field.value
            for name in ("eposta", "telefon")
            if (field := analysis.fields.get(name)) is not None and field.value
        ]
        return DraftPayload(
            template_id=decision.template_id,
            institution_name=ExtractedField(
                value=self.institution_name,
                status=FieldStatus.GENERATED,
                source="sentetik_demo_kurumu",
            ),
            date=self._copy_or_missing(analysis, "tarih"),
            number=ExtractedField(value=None, status=FieldStatus.USER_REQUIRED),
            subject=self._copy_or_missing(analysis, "konu"),
            recipient=ExtractedField(
                value=routing.unit_name,
                status=FieldStatus.GENERATED,
                source=f"birim_yonlendirme:{routing.unit_id}",
            ),
            paragraphs=paragraphs,
            signer=ExtractedField(value=None, status=FieldStatus.USER_REQUIRED),
            signer_title=ExtractedField(value=None, status=FieldStatus.USER_REQUIRED),
            contact_information=contact_information,
            document_metadata={
                "template_version": "1.0.0",
                "data_class": "sentetik_demo",
                "routing_unit_id": routing.unit_id,
            },
            authority_relation=authority_relation,
            closing=closing,
            references=verified_references,
            missing_fields=missing,
        )

    @staticmethod
    def _copy_or_missing(analysis: DocumentAnalysis, name: str) -> ExtractedField:
        field = analysis.fields.get(name)
        if field and field.value:
            return field.model_copy(deep=True)
        return ExtractedField(value=None, status=FieldStatus.USER_REQUIRED)

    @staticmethod
    def _paragraphs(
        analysis: DocumentAnalysis,
        decision: TemplateDecision,
        routing: RoutingRecommendation,
        references: list[VerifiedReference],
        closing: str,
    ) -> list[str]:
        request = analysis.fields.get("talep")
        request_text = request.value if request and request.value else analysis.summary
        if decision.document_type == "eksik_bilgi_talebi":
            missing = ", ".join(analysis.missing_fields)
            paragraphs = [
                "Başvurunuz ön incelemeye alınmıştır.",
                f"İşlemin sürdürülebilmesi için şu bilgilerin tamamlanması gerekmektedir: {missing}.",
                "Eksik bilgilerin iletilmesinin ardından başvurunuz yeniden değerlendirilecektir.",
            ]
            if any(
                reference.corpus_mode == CorpusMode.COMPETITION_SNAPSHOT.value
                for reference in references
            ):
                paragraphs.append(COMPETITION_SNAPSHOT_NOTICE)
            paragraphs.append(closing)
            return paragraphs

        paragraphs = [
            f"İlgili başvuruda belirtilen husus incelenmiştir: {request_text}",
            f"Başvurunun görev ve sorumluluk alanı bakımından {routing.unit_name} tarafından değerlendirilmesi uygun görülmüştür.",
        ]
        if any(
            reference.corpus_mode == CorpusMode.COMPETITION_SNAPSHOT.value
            for reference in references
        ):
            paragraphs.append(COMPETITION_SNAPSHOT_NOTICE)
        paragraphs.append(closing)
        return paragraphs

    @staticmethod
    def _official_closing(decision: TemplateDecision) -> tuple[str, str]:
        """Select one auditable closing from the demonstrated authority relation.

        The prototype routes an internally generated upper letter from the
        institution to its subordinate synthetic unit. Other templates address
        the applicant/external recipient. Unknown or mixed relations can still
        be supplied by the user and are rejected by ComplianceAgent unless the
        closing is updated consistently.
        """

        if decision.document_type == "ust_yazi":
            return "subordinate_internal", "Gereğini rica ederim."
        return "citizen_or_external", "Bilgilerinize sunulur."
