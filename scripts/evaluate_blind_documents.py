"""Bağımsız kör evrak setiyle sınıflandırma/yönlendirme genellemesini ölçer.

Bu betik, ``docs/SARTNAME_EKSIKLERI_UYGULAMA_PLANI.md`` madde 2.1'de
("Görülmemiş/paraphrase evrakı anlamlandırma") tanımlanan açığı kapatmak
için yazılmıştır. ``data/evaluation/blind_documents_v1.json`` içindeki 20
kurgu belge, geliştirme fixture'larından (``examples/``,
``data/synthetic_gold.json``, ``tests/``) bağımsızdır ve sınıflandırma/
yönlendirme kural motorunun anahtar kelime listesine bakılarak
yazılmamıştır.

Bu, bağımsız bir dış değerlendirici tarafından yapılan kör test değildir;
bu depoyu geliştiren kişi tarafından, sistemin gerçek çıktısına bakılmadan
ÖNCE atanmış "gold" etiketlerle yapılan ilk mühendislik ölçümüdür. Sonuçlar
gerçek saha başarımı veya bağımsız akademik değerlendirme olarak
sunulmamalıdır; yalnızca 20 kayıtlık küçük ölçekli bir genelleme
regresyonudur.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from karayol_agent.config import Settings
from karayol_agent.orchestrator import EvrakOrchestrator


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "data" / "evaluation" / "blind_documents_v1.json"
DEFAULT_OUTPUT = ROOT / "reports" / "blind_evaluation_v1.json"

# Dosya sessizce düzenlendiğinde ölçümün fark edilmeden geçersizleşmemesi
# için sabitlenmiş SHA-256. Veri seti kasıtlı olarak değiştirildiğinde bu
# değer güncellenmeli ve neden değiştiği commit mesajında açıklanmalıdır.
BLIND_DATASET_SHA256 = (
    "57bfbc6c842a74c16bdf6ca8b7f3fbb07b98eb10c94b811dcbb66cb181a75beb"
)

GENERIC_UNIT_ID = "ORKGM-EB-001"


def _git_revision() -> dict[str, Any]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
    except (OSError, subprocess.CalledProcessError):
        return {"commit": None, "dirty": None}
    return {"commit": commit, "dirty": dirty}


def load_dataset(dataset_path: Path) -> dict[str, Any]:
    dataset_bytes = dataset_path.read_bytes()
    digest = hashlib.sha256(dataset_bytes).hexdigest()
    if digest != BLIND_DATASET_SHA256:
        raise ValueError(
            "Kör değerlendirme veri seti pinlenmiş SHA-256 ile uyuşmuyor "
            f"(beklenen {BLIND_DATASET_SHA256}, bulunan {digest}). Dosya "
            "kasıtlı olarak değiştirildiyse bu betikteki sabiti güncelleyin "
            "ve değişikliğin nedenini kaydedin; aksi hâlde ölçüm "
            "sonuçlarına güvenilmemelidir."
        )
    return json.loads(dataset_bytes.decode("utf-8"))


def _build_orchestrator(temp_root: Path) -> EvrakOrchestrator:
    return EvrakOrchestrator(
        Settings(
            project_root=ROOT,
            data_dir=ROOT / "data",
            templates_dir=ROOT / "templates",
            output_dir=temp_root / "output",
            runtime_dir=temp_root / "runtime",
        )
    )


def _evaluate_record(
    orchestrator: EvrakOrchestrator, record: dict[str, Any]
) -> dict[str, Any]:
    gold = record["gold"]
    state = orchestrator.process_text(record["text"], source_name=f"{record['id']}.txt")
    assert state.analysis is not None
    assert state.routing is not None

    predicted_type = state.analysis.document_type
    predicted_unit = state.routing.unit_id
    requires_review = bool(state.routing.requires_human_review)
    verified_count = sum(reference.verified for reference in state.verified_references)

    result: dict[str, Any] = {
        "id": record["id"],
        "category": record["category"],
        "predicted_document_type": predicted_type,
        "predicted_unit_id": predicted_unit,
        "predicted_confidence": round(state.analysis.confidence, 2),
        "requires_human_review": requires_review,
        "routing_status": state.routing.routing_status,
        "verified_reference_count": verified_count,
        "missing_fields": list(state.analysis.missing_fields),
    }

    category = record["category"]
    if category == "paraphrase_positive":
        type_correct = predicted_type == gold["document_type"]
        unit_correct = predicted_unit in gold["acceptable_unit_ids"]
        result["passed"] = bool(type_correct and unit_correct)
        result["type_correct"] = type_correct
        result["unit_correct"] = unit_correct
    elif category == "near_miss_ambiguous":
        type_acceptable = predicted_type in gold.get(
            "acceptable_document_types", []
        ) or predicted_unit in gold.get("acceptable_unit_ids", [])
        review_flagged = requires_review is True
        result["passed"] = bool(review_flagged)
        result["type_acceptable"] = type_acceptable
        result["review_flagged"] = review_flagged
    elif category == "no_answer_offtopic":
        no_confident_specific_unit = (
            predicted_unit == GENERIC_UNIT_ID or requires_review is True
        )
        no_fabricated_legislation = verified_count == 0
        result["passed"] = bool(no_confident_specific_unit and no_fabricated_legislation)
        result["no_confident_specific_unit"] = no_confident_specific_unit
        result["no_fabricated_legislation"] = no_fabricated_legislation
    elif category == "ocr_noise_variant":
        type_correct = predicted_type == gold["document_type"]
        unit_correct = predicted_unit in gold["acceptable_unit_ids"]
        result["passed"] = bool(type_correct)
        result["type_correct"] = type_correct
        result["unit_correct"] = unit_correct
    else:  # pragma: no cover - dataset contract guard
        raise ValueError(f"Bilinmeyen kategori: {category}")

    return result


def run(dataset_path: Path) -> dict[str, Any]:
    dataset = load_dataset(dataset_path)
    records: list[dict[str, Any]] = dataset["records"]

    with tempfile.TemporaryDirectory(prefix="karayol-blind-eval-") as temp_dir:
        orchestrator = _build_orchestrator(Path(temp_dir))
        results = [_evaluate_record(orchestrator, record) for record in records]

    by_category: dict[str, list[dict[str, Any]]] = {}
    for item in results:
        by_category.setdefault(item["category"], []).append(item)

    category_summary = {
        category: {
            "passed": sum(item["passed"] for item in items),
            "total": len(items),
            "ratio": f"{sum(item['passed'] for item in items)}/{len(items)}",
            "failed_ids": [item["id"] for item in items if not item["passed"]],
        }
        for category, items in sorted(by_category.items())
    }
    overall_passed = sum(item["passed"] for item in results)

    return {
        "schema_version": "1.0",
        "report_kind": "blind_generalization_measurement",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git": _git_revision(),
        "dataset": {
            "path": str(dataset_path.relative_to(ROOT)),
            "sha256": BLIND_DATASET_SHA256,
            "record_count": len(records),
        },
        "orchestrator_config": {
            "retrieval_mode": "bm25",
            "corpus_mode": "trusted_synthetic",
        },
        "category_summary": category_summary,
        "overall": {
            "passed": overall_passed,
            "total": len(results),
            "ratio": f"{overall_passed}/{len(results)}",
        },
        "records": results,
        "disclaimer": (
            "Bu ölçüm 20 kayıtlık küçük ölçekli bir mühendislik "
            "regresyonudur; gerçek saha başarımı, bağımsız akademik "
            "değerlendirme veya hukuki doğruluk iddiası taşımaz. 'Gold' "
            "etiketleri bu depoyu geliştiren kişi tarafından atanmıştır; "
            "tam bağımsızlık için ayrı bir değerlendiricinin dondurulmuş "
            "veri setini yeniden puanlaması önerilir."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    report = run(args.dataset)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(f"Genel sonuç: {report['overall']['ratio']}")
    for category, summary in report["category_summary"].items():
        print(f"  {category}: {summary['ratio']}", end="")
        if summary["failed_ids"]:
            print(f" (başarısız: {', '.join(summary['failed_ids'])})")
        else:
            print()
    print(f"Rapor yazıldı: {args.output}")


if __name__ == "__main__":
    main()
