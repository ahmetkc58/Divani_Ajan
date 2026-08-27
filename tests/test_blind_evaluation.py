"""Kör değerlendirme setinin bütünlüğünü ve genelleme tabanını korur.

Bu test dosyası ``scripts/evaluate_blind_documents.py`` içindeki ölçümü
çalıştırır. Amaç yüksek bir başarı iddiası değil; ilk bağımsız kör ölçümde
kaydedilen genelleme tabanının (bkz. ``reports/blind_evaluation_v1.json``)
sessizce daha da kötüleşmediğini denetlemektir. Eşik, önceden yazılmış
iddialı bir hedef değil, ölçülen ilk sonuçtan (9/20) çıkarılan muhafazakâr
bir regresyon tabanıdır; bkz. ``docs/SARTNAME_EKSIKLERI_UYGULAMA_PLANI.md``
madde 2.1.
"""

from __future__ import annotations

import json

from scripts.evaluate_blind_documents import (
    BLIND_DATASET_SHA256,
    DEFAULT_DATASET,
    load_dataset,
    run,
)

EXPECTED_CATEGORIES = {
    "paraphrase_positive",
    "near_miss_ambiguous",
    "no_answer_offtopic",
    "ocr_noise_variant",
}

# İlk kör ölçümde kaydedilen taban (bkz. reports/blind_evaluation_v1.json).
# Bu bir hedef değil, aşağı yönlü sessiz regresyona karşı bir tabandır.
RECORDED_BASELINE_PASSED = 9
RECORDED_BASELINE_TOTAL = 20


def test_blind_dataset_is_pinned_and_well_formed() -> None:
    dataset = load_dataset(DEFAULT_DATASET)
    dataset_bytes = DEFAULT_DATASET.read_bytes()
    import hashlib

    assert hashlib.sha256(dataset_bytes).hexdigest() == BLIND_DATASET_SHA256

    records = dataset["records"]
    assert len(records) == RECORDED_BASELINE_TOTAL
    seen_ids = [record["id"] for record in records]
    assert len(seen_ids) == len(set(seen_ids)), "Yinelenen kayıt kimliği var"
    categories = {record["category"] for record in records}
    assert categories == EXPECTED_CATEGORIES
    for record in records:
        assert record["text"].strip()
        assert "gold" in record and record["gold"]


def test_blind_evaluation_does_not_regress_below_recorded_baseline() -> None:
    report = run(DEFAULT_DATASET)

    assert report["overall"]["total"] == RECORDED_BASELINE_TOTAL
    assert set(report["category_summary"]) == EXPECTED_CATEGORIES
    assert report["overall"]["passed"] >= RECORDED_BASELINE_PASSED, (
        "Kör genelleme başarımı kaydedilen tabanın altına düştü: "
        f"{report['overall']['ratio']}"
    )

    # Rapor JSON'a serileştirilebilir olmalı (teslim raporlarıyla aynı sözleşme).
    json.dumps(report, ensure_ascii=False)
