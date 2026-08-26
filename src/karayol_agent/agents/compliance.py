from __future__ import annotations

from karayol_agent.retrieval.contracts import (
    COMPETITION_SNAPSHOT_NOTICE,
    CorpusMode,
)
from karayol_agent.official_writing_rules import (
    ALLOWED_CLOSINGS_BY_RELATION,
    REGULATION_ID,
    RULES,
    closing_matches_authority_relation,
    valid_official_date,
    valid_official_number,
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
        relation: candidates[0]
        for relation, candidates in ALLOWED_CLOSINGS_BY_RELATION.items()
    }

    def run(self, draft: DraftPayload, decision: TemplateDecision) -> ComplianceResult:
        errors: list[str] = []
        warnings: list[str] = []
        applied_rules: list[str] = []

        def apply(rule_id: str) -> None:
            if rule_id not in applied_rules:
                applied_rules.append(rule_id)

        def error(rule_id: str, message: str) -> None:
            apply(rule_id)
            errors.append(f"[{rule_id}] {message}")

        def warning(rule_id: str, message: str) -> None:
            apply(rule_id)
            warnings.append(f"[{rule_id}] {message}")

        if draft.template_id not in self.ALLOWED_TEMPLATES:
            errors.append("Şablon onaylı şablon listesinde değil.")
        if draft.template_id != decision.template_id:
            errors.append("Seçilen şablon ile taslak şablonu uyuşmuyor.")
        if not draft.institution_name.value:
            error("RY-10", "Belge başlığında kurum adı bulunmuyor.")
        else:
            apply("RY-10")
        if not draft.subject.value:
            error("RY-13", "Konu alanı bulunmuyor.")
        else:
            apply("RY-13")
        if not draft.recipient.value:
            error("RY-14", "Muhatap birim veya kişi bulunmuyor.")
        else:
            apply("RY-14")
        if not draft.date.value:
            warning("RY-12", "Tarih kullanıcı tarafından tamamlanmalıdır.")
        elif not valid_official_date(draft.date.value):
            error(
                "RY-12",
                "Tarih GG.AA.YYYY veya 'G Ay YYYY' biçiminde olmalıdır.",
            )
        else:
            apply("RY-12")
        if not draft.number.value:
            warning("RY-11", "Belge sayısı EBYS tarafından tamamlanmalıdır.")
        elif not valid_official_number(draft.number.value):
            error(
                "RY-11",
                "Sayı; ortam kodu-DETSİS-standart dosya planı-kayıt numarası "
                "yapısında olmalıdır (ör. E-67915368-903.07.02-4752).",
            )
        else:
            apply("RY-11")
        if not draft.paragraphs:
            errors.append("Taslak gövdesi boş.")
        if draft.authority_relation not in ALLOWED_CLOSINGS_BY_RELATION:
            error("RY-16", "Muhatap makam ilişkisi belirlenmemiş veya desteklenmiyor.")
        elif not closing_matches_authority_relation(
            draft.closing, draft.authority_relation
        ):
            error("RY-16", "Makam ilişkisi ile resmî kapanış ifadesi uyuşmuyor.")
        else:
            apply("RY-16")
        all_official_closings = {
            candidate
            for candidates in ALLOWED_CLOSINGS_BY_RELATION.values()
            for candidate in candidates
        }
        closing_occurrences = sum(
            paragraph.strip() in all_official_closings
            for paragraph in draft.paragraphs
        )
        if (
            closing_occurrences != 1
            or not draft.paragraphs
            or draft.paragraphs[-1] != draft.closing
        ):
            error("RY-16", "Taslak tam olarak bir resmî kapanışla bitmelidir.")
        for label, values in (
            ("ek", draft.attachments),
            ("dağıtım", draft.distribution),
            ("ilgi", draft.interest),
            ("iletişim", draft.contact_information),
            ("paraf", draft.initials),
        ):
            normalized = [value.strip().casefold() for value in values if value.strip()]
            if len(normalized) != len(values) or len(normalized) != len(set(normalized)):
                rule_id = {"ek": "RY-18", "dağıtım": "RY-19", "ilgi": "RY-15"}.get(
                    label, "RY-28"
                )
                error(
                    rule_id,
                    f"{label.capitalize()} listesinde boş veya yinelenen kayıt var.",
                )
            elif label in {"ek", "dağıtım", "ilgi"}:
                apply({"ek": "RY-18", "dağıtım": "RY-19", "ilgi": "RY-15"}[label])
        required_metadata = {
            "template_version",
            "data_class",
            "routing_unit_id",
            "official_writing_rules",
        }
        if not required_metadata.issubset(draft.document_metadata):
            error("RY-28", "Zorunlu belge üstverisi eksik.")
        elif draft.document_metadata["official_writing_rules"] != REGULATION_ID:
            error("RY-28", "Taslak farklı veya bilinmeyen bir kural sürümüne bağlı.")
        else:
            apply("RY-28")
        if not draft.references:
            warnings.append("Taslakta doğrulanmış mevzuat/kural kaynağı bulunmuyor.")
        elif any(not reference.verified for reference in draft.references):
            errors.append("Taslak yalnız doğrulanmış retrieval kanıtlarını taşımalıdır.")
        missing_signer_fields = []
        if not draft.signer.value:
            missing_signer_fields.append("imzalayan")
        if not draft.signer_title.value:
            missing_signer_fields.append("unvan")
        if missing_signer_fields:
            if set(missing_signer_fields).issubset(set(draft.missing_fields)):
                warning(
                    "RY-17",
                    "İmzalayan bilgileri kullanıcı tarafından tamamlanmalıdır: "
                    + ", ".join(missing_signer_fields),
                )
            else:
                error("RY-17", "İmzalayan adı veya unvanı eksik.")
        if not draft.electronic_signature.value:
            warning("RY-17", "Güvenli elektronik imza bilgisi henüz girilmedi.")
        else:
            apply("RY-17")
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
            applied_rule_ids=[rule_id for rule_id in RULES if rule_id in applied_rules],
            rule_source_id=REGULATION_ID,
        )
