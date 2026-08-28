"""Run the production-demo acceptance contract against a live local API.

The script deliberately exercises the public HTTP surface instead of importing
the orchestrator.  Start the application with the competition snapshot and run:

    python -X utf8 scripts/run_production_demo_acceptance.py

It prints a machine-readable JSON report and exits non-zero when a required
check fails.  Inputs are synthetic; the fixed competition snapshot is never
presented as current law.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


SCENARIO_A = """Gönderen: Ayşe Örnek
Tarih: 23.08.2026
Konu: D-100 bağlantı yolundaki asfalt bozulması
Konum: Örnek İl, Örnek İlçe, D-100 bağlantı yolu 12. kilometre
Telefon: 0555 111 22 33

Belirtilen konumda yol yüzeyinde geniş çukurlar ve asfalt bozulmaları oluşmuştur.
Trafik güvenliği açısından gerekli yol bakım ve onarım çalışmasının yapılmasını talep ediyorum.
"""

SCENARIO_B = """Konu: Hasarlı trafik işaret levhası

Bölgemizde bulunan trafik işaret levhası devrilmiştir. Trafik güvenliği açısından gereğinin yapılmasını talep ediyorum.
"""

SCENARIO_C = """Gönderen: Selin Örnek
Tarih: 23.08.2026
Konu: Sürüş yüzeyindeki derin oyuklar
Konum: Örnek İlçe, sanayi kavşağı yaklaşımı

Araç tekerlerinin içine girdiği derin oyuklar oluşmuştur. Bu bölümün düzeltilmesini istiyorum.
"""

SCENARIO_D = """Konu: Yol bakım ve asfalt çukuru
Konum: Örnek ilçe

Yoldaki çukura girince aracımın jantı kırıldı. Belediyeden tazminat ve değer kaybı almak istiyorum.
"""

SCENARIO_E = """Konu: Trafik güvenliği ve işaret levhası cezası

Trafik levhasına uymadığım için cezaya itiraz etmek istiyorum. İtiraz süresi kaç gündür?
"""

FIELD_VALUES = {
    "gonderen": "Ayşe Örnek",
    "konum": "Örnek İl, Örnek İlçe",
    # Must satisfy the RY-11 official-number shape check
    # (official_writing_rules.valid_official_number): ortam kodu (E/Z/O) -
    # DETSİS numarası - standart dosya planı kodu - kayıt numarası.
    "sayi": "E-24325150-903.07.02-4752",
    "imzalayan": "Mehmet Demir",
    "unvan": "Şube Müdürü",
    "tarih": "23.08.2026",
    "konu": "D-100 bağlantı yolundaki asfalt bozulması",
    "talep": "Gerekli bakım ve onarım çalışmasının yapılması",
    "muhatap": "Örnek Bölge Müdürlüğü",
    "telefon": "0555 111 22 33",
    "eposta": "ayse.ornek@example.test",
}


class AcceptanceRunner:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.checks: list[dict[str, Any]] = []

    def check(
        self,
        scenario: str,
        name: str,
        condition: bool,
        *,
        expected: Any,
        actual: Any,
        required: bool = True,
    ) -> None:
        self.checks.append(
            {
                "scenario": scenario,
                "name": name,
                "required": required,
                "passed": bool(condition),
                "expected": expected,
                "actual": actual,
            }
        )

    def get_json(self, path: str) -> dict[str, Any]:
        with urllib.request.urlopen(f"{self.base_url}{path}", timeout=60) as response:
            return json.load(response)

    def post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=600) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"POST {path}: HTTP {error.code}: {body}") from error

    def post_file(self, path: Path) -> dict[str, Any]:
        boundary = f"----karayol-agent-{uuid4().hex}"
        content = path.read_bytes()
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
            "Content-Type: text/plain; charset=utf-8\r\n\r\n"
        ).encode("utf-8") + content + f"\r\n--{boundary}--\r\n".encode("ascii")
        request = urllib.request.Request(
            f"{self.base_url}/v1/process/file?compile_pdf=false",
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=600) as response:
            return json.load(response)

    def download(self, path: str) -> tuple[bytes, str]:
        with urllib.request.urlopen(f"{self.base_url}{path}", timeout=60) as response:
            return response.read(), response.headers.get_content_type()

    @staticmethod
    def state_summary(state: dict[str, Any]) -> dict[str, Any]:
        analysis = state.get("analysis") or {}
        routing = state.get("routing") or {}
        template = state.get("template_decision") or {}
        diagnostics = state.get("retrieval_diagnostics") or {}
        compliance = state.get("compliance") or {}
        references = state.get("verified_references") or []
        return {
            "document_id": state.get("document_id"),
            "status": state.get("status"),
            "document_type": analysis.get("document_type"),
            "operational_category": analysis.get("operational_category"),
            "analysis_missing_fields": analysis.get("missing_fields"),
            "missing_information": state.get("missing_information"),
            "unit_id": routing.get("unit_id"),
            "template_id": template.get("template_id"),
            "retrieval_mode": diagnostics.get("mode"),
            "dense_status": diagnostics.get("dense_status"),
            "fallback_used": diagnostics.get("fallback_used"),
            "reference_count": len(references),
            "verified_reference_count": sum(
                1 for reference in references if reference.get("verified")
            ),
            "compliance_passed": compliance.get("passed"),
            "compliance_score": compliance.get("score"),
            "event_count": len(state.get("events") or []),
        }

    def process_text(self, text: str, source_name: str) -> dict[str, Any]:
        return self.post_json(
            "/v1/process/text",
            {"text": text, "source_name": source_name, "compile_pdf": False},
        )

    def verify_snapshot_disclosure(
        self, scenario: str, state: dict[str, Any]
    ) -> None:
        # `curated_requirement_rule` references come from the small,
        # separately human-reviewed procedural-rule catalog
        # (data/legal_requirements/catalog.json), not the frozen competition
        # snapshot corpus. They may legitimately carry
        # currentness_verified=True / legal_reliance_allowed=True because a
        # human actually verified those specific real, current laws. Only
        # snapshot-sourced references are required to carry the mandatory
        # non-current/non-reliance disclosure.
        verified = [
            reference
            for reference in state.get("verified_references") or []
            if reference.get("verified")
        ]
        snapshot_verified = [
            reference
            for reference in verified
            if reference.get("corpus_mode") == "competition_snapshot"
        ]
        safe = bool(snapshot_verified) and all(
            reference.get("currentness_verified") is False
            and reference.get("legal_reliance_allowed") is False
            and bool(reference.get("usage_notice"))
            for reference in snapshot_verified
        )
        self.check(
            scenario,
            "snapshot disclosure",
            safe,
            expected="all snapshot-sourced verified references are explicitly non-current/non-reliance",
            actual={
                "verified_count": len(verified),
                "snapshot_verified_count": len(snapshot_verified),
                "safe_count": sum(
                    1
                    for reference in snapshot_verified
                    if reference.get("currentness_verified") is False
                    and reference.get("legal_reliance_allowed") is False
                    and bool(reference.get("usage_notice"))
                ),
            },
        )

    def verify_query_relevance(
        self,
        scenario: str,
        state: dict[str, Any],
        *,
        profile: str | None,
        expected_ids: set[str],
        forbidden_ids: set[str],
    ) -> None:
        hits = state.get("search_hits") or []
        hit_ids = [hit["chunk"]["chunk_id"] for hit in hits]
        diagnostics = state.get("retrieval_diagnostics") or {}
        relevance_fields_valid = bool(hits) and all(
            hit.get("relevance_accepted") is True
            and isinstance(hit.get("relevance_score"), (int, float))
            and hit["relevance_score"] >= 0.75
            and hit.get("relevance_profile") == profile
            for hit in hits
        )
        self.check(
            scenario,
            "intent-and-text legal candidate relevance",
            set(hit_ids) == expected_ids
            and not set(hit_ids).intersection(forbidden_ids)
            and relevance_fields_valid
            and diagnostics.get("relevance_strategy")
            == "intent_profile_concept_gate_v2"
            and diagnostics.get("relevance_profile") == profile
            and diagnostics.get("relevance_abstained") is False
            and diagnostics.get("relevance_query_supported") is True,
            expected={
                "profile": profile,
                "chunk_ids": sorted(expected_ids),
                "forbidden_absent": sorted(forbidden_ids),
                "all_scores_at_least": 0.75,
            },
            actual={
                "profile": diagnostics.get("relevance_profile"),
                "strategy": diagnostics.get("relevance_strategy"),
                "chunk_ids": hit_ids,
                "scores": [hit.get("relevance_score") for hit in hits],
                "rejected_candidates": diagnostics.get(
                    "relevance_rejected_count"
                ),
                "abstained": diagnostics.get("relevance_abstained"),
            },
        )

    def verify_snapshot_abstention(
        self,
        scenario: str,
        state: dict[str, Any],
        *,
        profile: str,
    ) -> None:
        diagnostics = state.get("retrieval_diagnostics") or {}
        # Curated requirement-rule references (data/legal_requirements) are
        # attached by document type/subtype, independent of the content-based
        # legislation relevance gate this check verifies. Their presence must
        # not mask a genuine abstention on the main retrieval channel.
        verified = [
            item
            for item in state.get("verified_references") or []
            if item.get("verified")
            and item.get("source_kind") != "curated_requirement_rule"
        ]
        self.check(
            scenario,
            "near-miss abstention",
            not (state.get("search_hits") or [])
            and not verified
            and diagnostics.get("relevance_strategy")
            == "intent_profile_concept_gate_v2"
            and diagnostics.get("relevance_profile") == profile
            and diagnostics.get("relevance_query_supported") is False
            and diagnostics.get("relevance_abstained") is True,
            expected={
                "profile": profile,
                "query_supported": False,
                "abstained": True,
                "verified_reference_count": 0,
            },
            actual={
                "profile": diagnostics.get("relevance_profile"),
                "query_supported": diagnostics.get(
                    "relevance_query_supported"
                ),
                "abstained": diagnostics.get("relevance_abstained"),
                "hit_count": len(state.get("search_hits") or []),
                "verified_reference_count": len(verified),
                "warning": diagnostics.get("warning"),
            },
        )

    def complete_and_approve(
        self, scenario: str, state: dict[str, Any]
    ) -> dict[str, Any]:
        missing = list(state.get("missing_information") or [])
        unknown = [field for field in missing if field not in FIELD_VALUES]
        self.check(
            scenario,
            "all requested fields have safe fixture values",
            not unknown,
            expected=[],
            actual=unknown,
        )
        fields = {field: FIELD_VALUES[field] for field in missing if field in FIELD_VALUES}
        updated = self.post_json(
            f"/v1/process/{state['document_id']}/information",
            {"fields": fields, "compile_pdf": False},
        )
        self.check(
            scenario,
            "information transition",
            updated.get("status") == "kullanici_onayi_bekleniyor"
            and not updated.get("missing_information"),
            expected="kullanici_onayi_bekleniyor with no missing fields",
            actual={
                "status": updated.get("status"),
                "missing_information": updated.get("missing_information"),
            },
        )
        compliance = updated.get("compliance") or {}
        self.check(
            scenario,
            "compliance gate",
            compliance.get("passed") is True,
            expected=True,
            actual=compliance,
        )
        artifact = updated.get("artifact") or {}
        tex_path = artifact.get("tex_download_url")
        if isinstance(tex_path, str) and tex_path:
            tex, content_type = self.download(tex_path)
        else:
            tex, content_type = b"", "missing"
        tex_text = tex.decode("utf-8", errors="replace")
        # The rendered official letter deliberately no longer embeds a
        # technical "verified sources" appendix in the document body shown
        # to the recipient (source/citation provenance stays in the process
        # record and UI instead, per README's official-writing draft schema
        # notes). Only check the artifact is a real, non-trivial LaTeX file.
        self.check(
            scenario,
            "LaTeX artifact",
            content_type == "application/x-tex"
            and len(tex) > 200
            and "\\begin{document}" in tex_text
            and "\\end{document}" in tex_text,
            expected="downloadable application/x-tex with a rendered document body",
            actual={"content_type": content_type, "size_bytes": len(tex)},
        )

        can_approve = (
            updated.get("status") == "kullanici_onayi_bekleniyor"
            and compliance.get("passed") is True
            and not updated.get("missing_information")
        )
        if can_approve:
            approved = self.post_json(
                f"/v1/process/{state['document_id']}/approve",
                {"approved_by": "Yetkili Demo Kullanıcısı"},
            )
        else:
            approved = updated
        self.check(
            scenario,
            "human approval",
            approved.get("status") == "tamamlandi",
            expected="tamamlandi",
            actual=approved.get("status"),
        )
        return approved

    def run(self, txt_fixture: Path) -> dict[str, Any]:
        readiness = self.get_json("/ready")
        self.check(
            "readiness",
            "exact vector readiness",
            readiness.get("ready") is True
            and readiness.get("retrieval_mode") == "hybrid"
            and readiness.get("detail") == "Qdrant hazır: 2603/2603 uyumlu nokta.",
            expected="hybrid and 2603/2603 compatible points",
            actual={
                "ready": readiness.get("ready"),
                "retrieval_mode": readiness.get("retrieval_mode"),
                "detail": readiness.get("detail"),
            },
        )

        scenario_a = self.process_text(SCENARIO_A, "acceptance_scenario_a.txt")
        summary_a = self.state_summary(scenario_a)
        self.check(
            "A",
            "classification and routing",
            summary_a["operational_category"] == "yol_bakim_talebi"
            and summary_a["unit_id"] == "ORKGM-YB-001"
            and summary_a["template_id"] == "ust_yazi_v1",
            expected=["yol_bakim_talebi", "ORKGM-YB-001", "ust_yazi_v1"],
            actual=[
                summary_a["operational_category"],
                summary_a["unit_id"],
                summary_a["template_id"],
            ],
        )
        self.check(
            "A",
            "hybrid retrieval",
            summary_a["retrieval_mode"] == "hybrid"
            and summary_a["dense_status"] == "used"
            and summary_a["fallback_used"] is False
            and summary_a["verified_reference_count"] >= 1,
            expected="hybrid dense used without fallback and verified evidence",
            actual=summary_a,
        )
        self.check(
            "A",
            "missing draft fields",
            set(summary_a["missing_information"] or [])
            == {"sayi", "imzalayan", "unvan"},
            expected=["sayi", "imzalayan", "unvan"],
            actual=summary_a["missing_information"],
        )
        self.verify_snapshot_disclosure("A", scenario_a)
        self.verify_query_relevance(
            "A",
            scenario_a,
            profile="road_surface_maintenance_v1",
            expected_ids={
                "MEV-B4102E4DDE97752F",
                "MEV-F3938057B283C03C",
                "MEV-09E4E088C59D4D13",
                "MEV-D1B127E868E39891",
                "MEV-94ECA73AA07B2D39",
            },
            forbidden_ids={
                "MEV-56214B1A9589A5DA",
                "MEV-9DFE7B7E895F4F01",
                "MEV-311383AB24A5855D",
            },
        )
        final_a = self.complete_and_approve("A", scenario_a)

        scenario_b = self.process_text(SCENARIO_B, "acceptance_scenario_b.txt")
        summary_b = self.state_summary(scenario_b)
        self.check(
            "B",
            "missing-information classification and template",
            summary_b["operational_category"] == "trafik_guvenligi_bildirimi"
            and summary_b["unit_id"] == "ORKGM-TG-001"
            and summary_b["template_id"] == "eksik_bilgi_talebi_v1"
            and summary_b["compliance_passed"] is True
            # "gonderen"/"konum" are content facts tracked separately in
            # analysis_missing_fields (they drove the eksik_bilgi_talebi_v1
            # template choice); missing_information is the draft's own
            # admin/signing fields the office user must still fill in.
            and set(summary_b["analysis_missing_fields"] or [])
            == {"gonderen", "konum"}
            and set(summary_b["missing_information"] or [])
            == {"sayi", "imzalayan", "unvan", "tarih"},
            expected={
                "operational_category": "trafik_guvenligi_bildirimi",
                "unit_id": "ORKGM-TG-001",
                "template_id": "eksik_bilgi_talebi_v1",
                "compliance_passed": True,
                "analysis_missing_fields": ["gonderen", "konum"],
                "missing_information": ["sayi", "imzalayan", "unvan", "tarih"],
            },
            actual=summary_b,
        )
        self.verify_snapshot_disclosure("B", scenario_b)
        self.verify_query_relevance(
            "B",
            scenario_b,
            profile="traffic_sign_damage_v1",
            expected_ids={
                "MEV-F3938057B283C03C",
                "MEV-B4102E4DDE97752F",
                "MEV-557C8DA8A10F2BA5",
                "MEV-06B1C9050FB89590",
                "MEV-E65ACF3F7612C808",
            },
            forbidden_ids={
                "MEV-097A621442A40371",
                "MEV-031D0A3918F5F30E",
                "MEV-9C1D2E3C962F54A1",
            },
        )
        final_b = self.complete_and_approve("B", scenario_b)

        scenario_c = self.process_text(SCENARIO_C, "acceptance_scenario_c.txt")
        summary_c = self.state_summary(scenario_c)
        # This scenario documents a previously-known MVP limitation: a
        # paraphrase of a road-maintenance complaint that the deterministic
        # keyword classifier used to miss (falling back to genel_basvuru /
        # ORKGM-EB-001, abstaining on retrieval). It is kept non-required
        # (informational) because it tracks a soft, wording-sensitive
        # heuristic rather than a hard contract.
        self.check(
            "C",
            "documented rule-based classification boundary",
            summary_c["operational_category"] == "yol_bakim_talebi"
            and summary_c["unit_id"] == "ORKGM-YB-001",
            expected=["yol_bakim_talebi", "ORKGM-YB-001"],
            actual=[summary_c["operational_category"], summary_c["unit_id"]],
            required=False,
        )
        diagnostics_c = scenario_c.get("retrieval_diagnostics") or {}
        verified_c = [
            item
            for item in scenario_c.get("verified_references") or []
            if item.get("verified")
        ]
        self.check(
            "C",
            "paraphrase boundary now resolved with supported answer",
            diagnostics_c.get("relevance_profile") == "road_surface_maintenance_v1"
            and diagnostics_c.get("relevance_query_supported") is True
            and diagnostics_c.get("relevance_abstained") is False
            and bool(verified_c),
            expected={
                "profile": "road_surface_maintenance_v1",
                "query_supported": True,
                "abstained": False,
            },
            actual={
                "profile": diagnostics_c.get("relevance_profile"),
                "query_supported": diagnostics_c.get("relevance_query_supported"),
                "abstained": diagnostics_c.get("relevance_abstained"),
                "verified_reference_count": len(verified_c),
            },
            required=False,
        )

        scenario_d = self.process_text(SCENARIO_D, "acceptance_noanswer_road.txt")
        self.verify_snapshot_abstention(
            "D",
            scenario_d,
            profile="road_surface_maintenance_v1",
        )

        scenario_e = self.process_text(SCENARIO_E, "acceptance_noanswer_sign.txt")
        self.verify_snapshot_abstention(
            "E",
            scenario_e,
            profile="traffic_sign_damage_v1",
        )

        file_state = self.post_file(txt_fixture)
        file_summary = self.state_summary(file_state)
        self.check(
            "TXT",
            "multipart upload",
            file_state.get("source_name") == txt_fixture.name
            and file_summary["operational_category"] == "yol_bakim_talebi"
            and file_summary["unit_id"] == "ORKGM-YB-001",
            expected=[txt_fixture.name, "yol_bakim_talebi", "ORKGM-YB-001"],
            actual=[
                file_state.get("source_name"),
                file_summary["operational_category"],
                file_summary["unit_id"],
            ],
        )

        required_failures = [
            check
            for check in self.checks
            if check["required"] and not check["passed"]
        ]
        return {
            "schema_version": "1.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "base_url": self.base_url,
            "passed": not required_failures,
            "required_check_count": sum(
                1 for check in self.checks if check["required"]
            ),
            "required_pass_count": sum(
                1
                for check in self.checks
                if check["required"] and check["passed"]
            ),
            "required_failures": required_failures,
            "readiness": readiness,
            "scenarios": {
                "A": {
                    "initial": summary_a,
                    "final": self.state_summary(final_a),
                },
                "B": {
                    "initial": summary_b,
                    "final": self.state_summary(final_b),
                },
                "C_known_boundary": summary_c,
                "D_road_no_answer": self.state_summary(scenario_d),
                "E_sign_no_answer": self.state_summary(scenario_e),
                "TXT": file_summary,
            },
            "checks": self.checks,
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Çalışan yerel API üzerinde production-demo kabul turu."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8010")
    parser.add_argument(
        "--txt-fixture",
        type=Path,
        default=Path(__file__).resolve().parents[1]
        / "examples"
        / "manuel_test_yol_bakim_talebi.txt",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Ayrıntılı JSON raporunu isteğe bağlı olarak bu yola yaz.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    runner = AcceptanceRunner(args.base_url)
    try:
        report = runner.run(args.txt_fixture.resolve())
    except Exception as exc:  # pragma: no cover - live operational boundary
        report = {
            "schema_version": "1.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "base_url": args.base_url,
            "passed": False,
            "fatal_error": f"{type(exc).__name__}: {exc}",
            "checks": runner.checks,
        }
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        output = args.output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report.get("passed") is True else 1


if __name__ == "__main__":
    sys.exit(main())
