from __future__ import annotations

from karayol_agent.schemas import ComplianceResult, DraftPayload, TemplateDecision


class ComplianceAgent:
    name = "Uygunluk Denetçisi"

    ALLOWED_TEMPLATES = {
        "ust_yazi_v1",
        "cevap_yazisi_v1",
        "bilgilendirme_yazisi_v1",
        "eksik_bilgi_talebi_v1",
    }

    def run(self, draft: DraftPayload, decision: TemplateDecision) -> ComplianceResult:
        errors: list[str] = []
        warnings: list[str] = []

        if draft.template_id not in self.ALLOWED_TEMPLATES:
            errors.append("Şablon onaylı şablon listesinde değil.")
        if draft.template_id != decision.template_id:
            errors.append("Seçilen şablon ile taslak şablonu uyuşmuyor.")
        if not draft.institution_name.value:
            errors.append("Kurum adı bulunmuyor.")
        if not draft.subject.value:
            errors.append("Konu alanı bulunmuyor.")
        if not draft.recipient.value:
            errors.append("Muhatap birim bulunmuyor.")
        if not draft.paragraphs:
            errors.append("Taslak gövdesi boş.")
        if len(" ".join(draft.paragraphs)) < 40:
            errors.append("Taslak gövdesi anlamlı bir resmî yazı için çok kısa.")
        if not draft.references:
            warnings.append("Taslakta doğrulanmış mevzuat/kural kaynağı bulunmuyor.")
        if draft.missing_fields:
            warnings.append(
                "Kullanıcı tarafından doldurulması gereken alanlar: "
                + ", ".join(draft.missing_fields)
            )

        total_checks = 7
        score = max(0.0, 1.0 - len(errors) / total_checks - len(warnings) * 0.04)
        return ComplianceResult(
            passed=not errors,
            score=round(score, 2),
            errors=errors,
            warnings=warnings,
        )

