from __future__ import annotations

from karayol_agent.schemas import DocumentAnalysis, TemplateDecision, VerifiedReference


class TemplateSelectionAgent:
    name = "Yazı Türü ve Şablon Seçimi Ajanı"

    DOCUMENT_TO_TEMPLATE = {
        "bilgi_talebi": "cevap_yazisi_v1",
        "dilekce": "cevap_yazisi_v1",
        "sikayet": "cevap_yazisi_v1",
        "yol_bakim_talebi": "ust_yazi_v1",
        "trafik_guvenligi_bildirimi": "ust_yazi_v1",
        "hasar_bildirimi": "ust_yazi_v1",
        "ust_yazi": "bilgilendirme_yazisi_v1",
        "genel_basvuru": "cevap_yazisi_v1",
    }

    def __init__(self, low_confidence_threshold: float = 0.60) -> None:
        self.low_confidence_threshold = low_confidence_threshold

    def run(
        self,
        analysis: DocumentAnalysis,
        references: list[VerifiedReference],
    ) -> TemplateDecision:
        if analysis.missing_fields:
            template_id = "eksik_bilgi_talebi_v1"
            rationale = (
                "Taslak için zorunlu bilgiler eksik olduğundan önce eksik bilgi talebi "
                "hazırlanmalıdır."
            )
            confidence = 0.95
            alternatives = [
                {
                    "document_type": self._document_type_for(
                        self.DOCUMENT_TO_TEMPLATE.get(analysis.document_type, "cevap_yazisi_v1")
                    ),
                    "template_id": self.DOCUMENT_TO_TEMPLATE.get(
                        analysis.document_type, "cevap_yazisi_v1"
                    ),
                    "score": round(analysis.confidence, 2),
                }
            ]
        else:
            template_id = self.DOCUMENT_TO_TEMPLATE.get(
                analysis.document_type, "cevap_yazisi_v1"
            )
            confidence = analysis.confidence
            verified_count = sum(reference.verified for reference in references)
            if verified_count:
                confidence = min(confidence + 0.04, 0.99)
            rationale = (
                f"Evrak '{analysis.document_type}' olarak sınıflandırıldığı ve "
                f"{verified_count} kaynak doğrulandığı için bu yazı türü seçildi."
            )
            alternatives = []

        return TemplateDecision(
            document_type=self._document_type_for(template_id),
            template_id=template_id,
            rationale=rationale,
            confidence=round(confidence, 2),
            user_approval_required=confidence < self.low_confidence_threshold,
            alternatives=alternatives,
        )

    @staticmethod
    def _document_type_for(template_id: str) -> str:
        return template_id.removesuffix("_v1")

