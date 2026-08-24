from __future__ import annotations

import re

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
        elif not self._recipient_is_addressed(draft.recipient.value):
            errors.append("Muhatap makam/birim adı resmî hitap biçiminde değil.")
        if not draft.date.value:
            errors.append("Tarih alanı zorunludur.")
        elif not self._valid_date(draft.date.value):
            errors.append("Tarih alanı GG.AA.YYYY veya YYYY-AA-GG biçiminde olmalıdır.")
        if not draft.number.value:
            errors.append("Sayı alanı zorunludur.")
        elif not re.fullmatch(
            r"[A-Za-zÇĞİÖŞÜçğıöşü0-9]+(?:[./-][A-Za-zÇĞİÖŞÜçğıöşü0-9]+)*",
            draft.number.value,
        ):
            errors.append("Sayı alanı geçerli bir kurum sayı biçiminde değil.")
        if not draft.closing.value:
            errors.append("Arz/rica kapanış ifadesi bulunmuyor.")
        elif not self._closing_matches(draft.closing.value, decision.document_type):
            errors.append("Arz/rica kapanış ifadesi yazı türü ve makam ilişkisiyle uyumsuz.")
        if not draft.paragraphs:
            errors.append("Taslak gövdesi boş.")
        if len(" ".join(draft.paragraphs)) < 40:
            errors.append("Taslak gövdesi anlamlı bir resmî yazı için çok kısa.")
        if not draft.references:
            warnings.append("Taslakta doğrulanmış mevzuat/kural kaynağı bulunmuyor.")
        if draft.references_section and not draft.references:
            errors.append("İlgi bölümü doğrulanmış kaynak içermiyor.")
        if any(not item.strip() for item in draft.attachments):
            errors.append("Ek listesinde boş veya geçersiz öğe bulunuyor.")
        if any(not item.strip() for item in draft.distribution):
            errors.append("Dağıtım listesinde boş veya geçersiz öğe bulunuyor.")
        if draft.distribution and not draft.recipient.value:
            errors.append("Dağıtım listesi için muhatap zorunludur.")
        if not draft.signer.value:
            errors.append("İmzalayan bilgisi zorunludur.")
        if not draft.signer_title.value:
            errors.append("İmzalayan unvanı zorunludur.")
        if draft.missing_fields:
            warnings.append(
                "Kullanıcı tarafından doldurulması gereken alanlar: "
                + ", ".join(draft.missing_fields)
            )

        total_checks = 15
        score = max(0.0, 1.0 - len(errors) / total_checks - len(warnings) * 0.04)
        return ComplianceResult(
            passed=not errors,
            score=round(score, 2),
            errors=errors,
            warnings=warnings,
        )

    @staticmethod
    def _valid_date(value: str) -> bool:
        return bool(
            re.fullmatch(r"(?:\d{2}\.\d{2}\.\d{4}|\d{4}-\d{2}-\d{2})", value.strip())
        )

    @staticmethod
    def _recipient_is_addressed(value: str) -> bool:
        normalized = value.strip().casefold()
        return normalized.endswith(("e", "a", "ne", "na"))

    @staticmethod
    def _closing_matches(closing: str, document_type: str) -> bool:
        normalized = " ".join(closing.casefold().split())
        if document_type == "ust_yazi":
            return normalized == "gereğini rica ederim."
        if document_type == "cevap_yazisi":
            return normalized == "bilgilerinize arz ederim."
        if document_type == "bilgilendirme_yazisi":
            return normalized == "bilgilerinize arz ve rica ederim."
        return normalized in {"gereğini rica ederim.", "bilgilerinize arz ederim."}

