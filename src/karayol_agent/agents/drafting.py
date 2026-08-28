from __future__ import annotations

from karayol_agent.schemas import (
    DocumentAnalysis,
    DraftPayload,
    ExtractedField,
    FieldStatus,
    RoutingRecommendation,
    TemplateDecision,
    VerifiedReference,
)
from karayol_agent.official_writing_rules import (
    UAB_DETSIS_NUMBER,
    UAB_OFFICIAL_NUMBER_PLACEHOLDER,
)


class DraftingAgent:
    name = "Taslak Oluşturma Ajanı"

    def __init__(
        self,
        institution_name: str = (
            "T.C. ULAŞTIRMA VE ALTYAPI BAKANLIĞI\n"
            "KARAYOLLARI GENEL MÜDÜRLÜĞÜ"
        ),
    ) -> None:
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
        # Gelen evraktaki eksikler Katman 1 bulgusu olarak raporlanır; kullanıcı
        # girdisiyle evrakın kendisi değiştirilmez. Burada yalnız üretilecek resmî
        # yazının kurumsal üstveri/imza alanları kullanıcı girdisi bekler.
        missing = ["sayi", "imzalayan", "unvan"]
        if not analysis.fields.get("tarih") or not analysis.fields["tarih"].value:
            missing.append("tarih")
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
            number=ExtractedField(
                value=UAB_OFFICIAL_NUMBER_PLACEHOLDER,
                status=FieldStatus.USER_REQUIRED,
                source="uab_detsis_dogrulandi_sdp_ve_ebys_bekleniyor",
            ),
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
                "official_writing_rules": "2646-RG-2020-31151",
                "detsis_number": UAB_DETSIS_NUMBER,
                "official_number_status": "placeholder_sdp_and_ebys_required",
                "detsis_source": (
                    "veri_kaynaklari/karayolu/detsis/README.md"
                ),
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
            paragraphs.append(closing)
            return paragraphs

        paragraphs = [
            f"İlgili başvuruda belirtilen husus incelenmiştir: {request_text}",
            f"Başvurunun görev ve sorumluluk alanı bakımından {routing.unit_name} tarafından değerlendirilmesi uygun görülmüştür.",
        ]
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
