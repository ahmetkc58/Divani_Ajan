from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
SOURCE_URL = "https://detsis.gov.tr/birim/24325150/24325150/2026-08-23"

ROAD_TERMS = (
    "karayolu",
    "kara yolu",
    "otoyol",
    "yolcu taşı",
    "eşya taşı",
    "yük taşı",
    "taşıt",
    "araç muayene",
    "takograf",
    "trafik",
    "ulaştırma hizmetleri",
    "ulaşım hizmetleri",
    "özel yük",
)


def load_data(name: str) -> Any:
    payload = json.loads((ROOT / f"{name}_raw.json").read_text(encoding="utf-8"))
    if "data" not in payload:
        raise ValueError(f"{name}_raw.json içinde data alanı yok")
    return payload["data"]


def road_match(text: str) -> list[str]:
    normalized = text.casefold()
    return [term for term in ROAD_TERMS if term in normalized]


def write_json(name: str, data: Any, **metadata: Any) -> None:
    payload = {
        "source_url": SOURCE_URL,
        "retrieved_at": datetime.now().astimezone().isoformat(),
        **metadata,
        "data": data,
    }
    (ROOT / name).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def write_csv(name: str, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with (ROOT / name).open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    documents: list[dict[str, Any]] = load_data("belgeler")
    services: list[dict[str, Any]] = load_data("hizmetler")
    legislation: list[dict[str, Any]] = load_data("mevzuatlar")
    profile: dict[str, Any] = load_data("kunye")

    clean_profile_fields = (
        "id",
        "detsisNo",
        "birimAdi",
        "ingilizceAdi",
        "kurumHiyerarsi",
        "kurumHiyerarsiList",
        "bagliOlduguKurumId",
        "bagliOlduguKurum",
        "anaKurumMu",
        "tuzelKisilik",
        "butceTuru",
        "kategori",
        "statu",
        "internetAdresi",
        "eposta",
        "telefon",
        "telefonDahiliNumara",
        "belgegecer",
        "acikAdres",
        "kep",
        "faaliyetDurumuId",
        "kurulusMevzuatlari",
    )
    clean_profile = {field: profile.get(field) for field in clean_profile_fields}

    services = [
        {
            **row,
            "detail_url": (
                "https://envanter.kaysis.gov.tr/HizmetDetay.aspx?ID="
                f"{row.get('hizmetId')}"
            ),
        }
        for row in services
    ]
    legislation = [
        {
            **row,
            "detail_url": (
                "https://kms.kaysis.gov.tr/Home/Goster/"
                f"{row.get('mevzuatId')}"
            ),
            "local_archive": None,
        }
        for row in legislation
    ]

    road_documents = []
    for row in documents:
        reasons = road_match(f"{row.get('belgeBeyanAdi', '')} {row.get('belgeTur', '')}")
        if reasons:
            road_documents.append({**row, "filter_matches": reasons})

    road_services = []
    for row in services:
        reasons = road_match(f"{row.get('hizmetAd', '')} {row.get('kurumHiyerarsik', '')}")
        if reasons:
            road_services.append({**row, "filter_matches": reasons})

    road_legislation = []
    for row in legislation:
        reasons = road_match(f"{row.get('ad', '')} {row.get('tur', '')}")
        if reasons:
            road_legislation.append({**row, "filter_matches": reasons})

    write_json("kurum_kunyesi_temiz.json", clean_profile, record_count=1)
    write_json("belgeler.json", documents, record_count=len(documents))
    write_json("hizmetler.json", services, record_count=len(services))
    write_json("mevzuatlar.json", legislation, record_count=len(legislation))
    write_json(
        "karayolu_belgeleri.json",
        road_documents,
        record_count=len(road_documents),
        filter_terms=list(ROAD_TERMS),
        filter_note="Anahtar kelime filtresidir; kullanımdan önce insan doğrulaması gerekir.",
    )
    write_json(
        "karayolu_hizmetleri.json",
        road_services,
        record_count=len(road_services),
        filter_terms=list(ROAD_TERMS),
        filter_note="Anahtar kelime filtresidir; kullanımdan önce insan doğrulaması gerekir.",
    )
    write_json(
        "karayolu_mevzuatlari.json",
        road_legislation,
        record_count=len(road_legislation),
        filter_terms=list(ROAD_TERMS),
        filter_note="Anahtar kelime filtresidir; kullanımdan önce insan doğrulaması gerekir.",
    )

    write_csv(
        "belgeler.csv",
        documents,
        ["belgeBeyanID", "belgeBeyanAdi", "belgeTur", "istenenmi"],
    )
    write_csv(
        "hizmetler.csv",
        services,
        ["hizmetId", "hizmetAd", "kurumHiyerarsik", "detail_url"],
    )
    write_csv(
        "mevzuatlar.csv",
        legislation,
        [
            "mevzuatId",
            "turId",
            "sayi",
            "ad",
            "rgSayi",
            "rgTarih",
            "tur",
            "detail_url",
            "local_archive",
        ],
    )

    summary = {
        "institution": clean_profile.get("birimAdi"),
        "detsis_id": clean_profile.get("detsisNo"),
        "all_documents": len(documents),
        "all_services": len(services),
        "all_legislation": len(legislation),
        "road_documents_keyword_filtered": len(road_documents),
        "road_services_keyword_filtered": len(road_services),
        "road_legislation_keyword_filtered": len(road_legislation),
        "legislation_detail_archive_status": "kaysis_redirect_loop",
    }
    (ROOT / "ozet.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
