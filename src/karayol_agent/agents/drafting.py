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
        paragraphs = self._paragraphs(analysis, decision, routing, verified_references)
        missing = list(dict.fromkeys([*analysis.missing_fields, "sayi", "imzalayan", "unvan"]))
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
            public_references = [
                reference
                for reference in references
                if reference.corpus_mode == CorpusMode.VERIFIED_PUBLIC.value
            ]
            snapshot_references = [
                reference
                for reference in references
                if reference.corpus_mode == CorpusMode.COMPETITION_SNAPSHOT.value
            ]
            synthetic_references = [
                reference
                for reference in references
                if reference.corpus_mode == CorpusMode.TRUSTED_SYNTHETIC.value
            ]

            if public_references:
                paragraphs.append(
                    "Taslak hazırlanırken kaynak sözleşmesini geçen şu kamu "
                    "mevzuatı parçaları dikkate alınmıştır: "
                    + DraftingAgent._source_names(public_references)
                    + "."
                )
            if snapshot_references:
                paragraphs.extend(
                    [
                        "Taslak hazırlanırken yarışma veri kümesindeki şu sabit "
                        "kaynak parçaları yalnız retrieval ve kaynak izi açısından "
                        "eşleştirilmiştir: "
                        + DraftingAgent._source_names(snapshot_references)
                        + ".",
                        COMPETITION_SNAPSHOT_NOTICE,
                    ]
                )
            if synthetic_references:
                paragraphs.append(
                    "Taslak hazırlanırken yalnız demo amacı taşıyan şu sentetik "
                    "kurallar dikkate alınmıştır: "
                    + DraftingAgent._source_names(synthetic_references)
                    + "."
                )
            known_reference_ids = {
                reference.chunk_id
                for reference in [
                    *public_references,
                    *snapshot_references,
                    *synthetic_references,
                ]
            }
            other_references = [
                reference
                for reference in references
                if reference.chunk_id not in known_reference_ids
            ]
            if other_references:
                paragraphs.append(
                    "Taslak hazırlanırken kabul edilen diğer kaynak parçaları: "
                    + DraftingAgent._source_names(other_references)
                    + "."
                )
        if decision.document_type == "ust_yazi":
            paragraphs.append("Gereğini rica ederim.")
        else:
            paragraphs.append("Bilgilerinize sunulur.")
        return paragraphs

    @staticmethod
    def _source_names(references: list[VerifiedReference]) -> str:
        return ", ".join(
            dict.fromkeys(
                f"{reference.title} {reference.article or ''}".strip()
                for reference in references[:3]
            )
        )
