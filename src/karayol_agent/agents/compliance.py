from __future__ import annotations

from karayol_agent.retrieval.contracts import (
    COMPETITION_SNAPSHOT_NOTICE,
    CorpusMode,
)
from karayol_agent.schemas import ComplianceResult, DraftPayload, TemplateDecision


class ComplianceAgent:
    name = "Uygunluk Denetçisi"

    ALLOWED_TEMPLATES = {
        "ust_yazi_v1",
        "cevap_yazisi_v1",
        "bilgilendirme_yazisi_v1",
        "eksik_bilgi_talebi_v1",
    }
    OFFICIAL_CLOSINGS = {
        "superior": "Arz ederim.",
        "subordinate_internal": "Gereğini rica ederim.",
        "mixed": "Arz ve rica ederim.",
        "citizen_or_external": "Bilgilerinize sunulur.",
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
        expected_closing = self.OFFICIAL_CLOSINGS.get(draft.authority_relation)
        if expected_closing is None:
            errors.append("Muhatap makam ilişkisi belirlenmemiş veya desteklenmiyor.")
        elif draft.closing != expected_closing:
            errors.append("Makam ilişkisi ile resmî kapanış ifadesi uyuşmuyor.")
        closing_occurrences = sum(
            paragraph.strip() in self.OFFICIAL_CLOSINGS.values()
            for paragraph in draft.paragraphs
        )
        if closing_occurrences != 1 or not draft.paragraphs or draft.paragraphs[-1] != draft.closing:
            errors.append("Taslak tam olarak bir resmî kapanışla bitmelidir.")
        for label, values in (
            ("ek", draft.attachments),
            ("dağıtım", draft.distribution),
            ("ilgi", draft.interest),
            ("iletişim", draft.contact_information),
            ("paraf", draft.initials),
        ):
            normalized = [value.strip().casefold() for value in values if value.strip()]
            if len(normalized) != len(values) or len(normalized) != len(set(normalized)):
                errors.append(f"{label.capitalize()} listesinde boş veya yinelenen kayıt var.")
        required_metadata = {"template_version", "data_class", "routing_unit_id"}
        if not required_metadata.issubset(draft.document_metadata):
            errors.append("Zorunlu belge üstverisi eksik.")
        if not draft.references:
            warnings.append("Taslakta doğrulanmış mevzuat/kural kaynağı bulunmuyor.")
        elif any(not reference.verified for reference in draft.references):
            errors.append("Taslak yalnız doğrulanmış retrieval kanıtlarını taşımalıdır.")
        if not draft.electronic_signature.value:
            warnings.append("Güvenli elektronik imza bilgisi henüz girilmedi.")
        snapshot_references = [
            reference
            for reference in draft.references
            if reference.corpus_mode == CorpusMode.COMPETITION_SNAPSHOT.value
        ]
        if snapshot_references:
            if COMPETITION_SNAPSHOT_NOTICE not in draft.paragraphs:
                errors.append(
                    "Yarışma veri kümesi kaynakları kullanıldığı halde zorunlu "
                    "güncellik/yürürlük uyarısı taslakta bulunmuyor."
                )
            if any(
                reference.currentness_verified
                or reference.legal_reliance_allowed
                or reference.usage_notice != COMPETITION_SNAPSHOT_NOTICE
                for reference in snapshot_references
            ):
                errors.append(
                    "Yarışma veri kümesi referansı güncel mevzuat veya hukuki "
                    "dayanak olarak işaretlenemez."
                )
            warnings.append(COMPETITION_SNAPSHOT_NOTICE)
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
