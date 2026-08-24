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
        paragraphs = self._paragraphs(analysis, decision, routing, verified_references)
        closing = self._closing(decision)
        missing = list(
            dict.fromkeys([*analysis.missing_fields, "tarih", "sayi", "imzalayan", "unvan"])
        )
        missing = [
            field
            for field in missing
            if not (
                field == "tarih"
                and analysis.fields.get("tarih")
                and analysis.fields["tarih"].value
            )
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
            closing=ExtractedField(
                value=closing,
                status=FieldStatus.GENERATED,
                source="makam_iliskisi_kurali",
            ),
            recipient_hierarchy=routing.hierarchy,
            references=verified_references,
            missing_fields=missing,
        )

    @staticmethod
    def _closing(decision: TemplateDecision) -> str:
        if decision.document_type == "ust_yazi":
            return "Gereğini rica ederim."
        if decision.document_type == "cevap_yazisi":
            return "Bilgilerinize arz ederim."
        if decision.document_type == "bilgilendirme_yazisi":
            return "Bilgilerinize arz ve rica ederim."
        return "Gereğini rica ederim."

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
    ) -> list[str]:
        request = analysis.fields.get("talep")
        request_text = request.value if request and request.value else analysis.summary
        if decision.document_type == "eksik_bilgi_talebi":
            missing = ", ".join(analysis.missing_fields)
            return [
                "Başvurunuz ön incelemeye alınmıştır.",
                f"İşlemin sürdürülebilmesi için şu bilgilerin tamamlanması gerekmektedir: {missing}.",
                "Eksik bilgilerin iletilmesinin ardından başvurunuz yeniden değerlendirilecektir.",
            ]

        paragraphs = [
            f"İlgili başvuruda belirtilen husus incelenmiştir: {request_text}",
            f"Başvurunun görev ve sorumluluk alanı bakımından {routing.unit_name} tarafından değerlendirilmesi uygun görülmüştür.",
        ]
        if references:
            source_names = ", ".join(
                dict.fromkeys(
                    f"{reference.title} {reference.article or ''}".strip()
                    for reference in references[:3]
                )
            )
            paragraphs.append(
                f"Taslak hazırlanırken doğrulanan şu kaynaklar dikkate alınmıştır: {source_names}."
            )
        return paragraphs
