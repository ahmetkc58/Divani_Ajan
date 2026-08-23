from __future__ import annotations

import csv
import html
import json
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parent
UAB_HTML = ROOT / "uab_karayolu_mevzuat_page4.html"
DETSIS_HTML = ROOT / "detsis_24325150.html"

UAB_SOURCE_URL = (
    "https://www.uab.gov.tr/bilgi-merkezi/mevzuat/"
    "?legislation_topic=Karayolu&page=4"
)
DETSIS_SOURCE_URL = (
    "https://detsis.gov.tr/birim/24325150/24325150/2026-08-23"
)


def classify_scope(title: str) -> str:
    normalized = title.casefold()
    if "hava trafik" in normalized or "hava araç" in normalized:
        return "kapsam_disi_havacilik"
    if any(
        term in normalized
        for term in (
            "taşıma kanunu",
            "taşıma yönetmeliği",
            "takograf",
            "araç muayene",
        )
    ):
        return "karayolu_tasimaciligi"
    return "kgm_karayolu_altyapisi_ve_trafik"


def extract_uab() -> list[dict[str, object]]:
    soup = BeautifulSoup(UAB_HTML.read_text(encoding="utf-8"), "html.parser")
    result_list = soup.select_one("ul.pdf-list")
    if result_list is None:
        raise RuntimeError("UAB sonuç listesi bulunamadı")

    records: list[dict[str, object]] = []
    for index, item in enumerate(result_list.select(":scope > li"), start=1):
        title_element = item.select_one("div.left span")
        pdf_link = item.select_one("div.right a[href]")
        if title_element is None or pdf_link is None:
            continue

        title = html.unescape(title_element.get_text(" ", strip=True))
        pdf_url = urljoin(UAB_SOURCE_URL, html.unescape(pdf_link["href"]))
        records.append(
            {
                "record_order": index,
                "title": title,
                "pdf_url": pdf_url,
                "local_file": f"uab_pdf/{index:02d}_uab_mevzuat.pdf",
                "source_page": 4,
                "source_filter": "Karayolu",
                "scope_assessment": classify_scope(title),
            }
        )

    payload = {
        "source_url": UAB_SOURCE_URL,
        "retrieved_at": datetime.now().astimezone().isoformat(),
        "record_count": len(records),
        "records": records,
        "notes": [
            "Kayıtlar kaynak sayfada göründüğü sırayla korunmuştur.",
            "Sayfada Karayolu filtresine rağmen havacılık kayıtları bulunmaktadır.",
            "scope_assessment kaynak verisi değil, proje kapsamı için yerel etikettir.",
        ],
    }
    (ROOT / "uab_karayolu_mevzuat_page4.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    with (ROOT / "uab_karayolu_mevzuat_page4.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=list(records[0].keys()))
        writer.writeheader()
        writer.writerows(records)
    return records


def extract_detsis_metadata() -> None:
    soup = BeautifulSoup(DETSIS_HTML.read_text(encoding="utf-8"), "html.parser")
    next_data_element = soup.select_one("script#__NEXT_DATA__")
    next_data = json.loads(next_data_element.get_text()) if next_data_element else {}
    query = next_data.get("query", {})

    payload = {
        "source_url": DETSIS_SOURCE_URL,
        "retrieved_at": datetime.now().astimezone().isoformat(),
        "requested_detsis_id": query.get("id", "24325150"),
        "requested_unit_id": query.get("birim", "24325150"),
        "requested_snapshot_date": query.get("date", "2026-08-23"),
        "page_title": soup.title.get_text(strip=True) if soup.title else None,
        "data_status": "dynamic_api_unavailable",
        "verified_fields": {},
        "public_endpoints_discovered": {
            "services": (
                "https://yetkiliapi.detsis.gov.tr/api/backoffice/"
                "unauthorizedintegration/kunye/hizmetler"
            ),
            "legislation": (
                "https://yetkiliapi.detsis.gov.tr/api/backoffice/"
                "unauthorizedintegration/kunye/mevzuatlar"
            ),
            "unit_profile": (
                "https://yetkiliapi.detsis.gov.tr/api/backoffice/"
                "unauthorizedaccessdata/birimkunye"
            ),
        },
        "api_attempt": {
            "result": "timeout",
            "timeout_seconds_per_request": 60,
            "attempted_sections": ["services", "legislation", "unit_profile"],
        },
        "notes": [
            "DETSİS sayfası verileri istemci tarafında API üzerinden yüklemektedir.",
            "İndirilen HTML veri yüklenmeden önce boş alanlar içermektedir.",
            "API yanıt vermediği için kurum, hizmet veya mevzuat değerleri üretilmemiştir.",
            "Ham HTML ve istemci JavaScript dosyaları denetlenebilir kaynak olarak saklanmıştır.",
        ],
    }
    (ROOT / "detsis_24325150_metadata.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    extracted_records = extract_uab()
    extract_detsis_metadata()
    print(json.dumps({"uab_records": len(extracted_records)}, ensure_ascii=False))
