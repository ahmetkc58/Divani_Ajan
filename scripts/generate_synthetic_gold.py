from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "synthetic_gold.json"

NAMES = (
    "Ayşe Örnek",
    "Mehmet Kurgu",
    "Elif Deneme",
    "Can Örneksoy",
    "Zeynep Kurgusal",
    "Mert Deneme",
    "Selin Örnek",
    "Burak Kurgu",
)
LOCATIONS = (
    "Örnek İl, Merkez, D-100 yolu 12. kilometre",
    "Kurgu İlçesi, devlet yolu 8. kilometre",
    "Deneme Beldesi, çevre yolu kuzey bağlantısı",
    "Örnek Köyü kavşağı, il yolu 4. kilometre",
    "Kurgu Mahallesi, otoyol bağlantı kolu",
    "Deneme İl, güney çevre yolu 21. kilometre",
    "Örnek İlçe, sanayi kavşağı yaklaşımı",
    "Kurgu İl, dağ yolu geçişi 3. kilometre",
)


def labeled_text(
    *,
    index: int,
    subject: str,
    body: str,
    include_sender: bool = True,
    location: str | None = None,
    include_date: bool = True,
) -> str:
    lines: list[str] = []
    if include_sender:
        lines.append(f"Gönderen: {NAMES[index % len(NAMES)]}")
    if include_date:
        lines.append(f"Tarih: {index + 1:02d}.08.2026")
    lines.append(f"Konu: {subject}")
    if location is not None:
        lines.append(f"Konum: {location}")
    lines.extend(["", body])
    return "\n".join(lines)


def make_domain_records(
    *,
    prefix: str,
    document_type: str,
    unit_id: str,
    reference_id: str,
    subjects: tuple[str, ...],
    descriptions: tuple[str, ...],
    request_sentence: str,
    request_sentences: tuple[str, ...] | None = None,
) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for index in range(8):
        missing_sender = index in {1, 4}
        missing_location = index in {2, 4}
        missing_request = index in {3, 6}
        missing: list[str] = []
        if missing_sender:
            missing.append("gonderen")
        if missing_location:
            missing.append("konum")
        if missing_request:
            missing.append("talep")
        body = descriptions[index]
        if not missing_request:
            body += " " + (
                request_sentences[index] if request_sentences else request_sentence
            )
        records.append(
            {
                "record_id": f"{prefix}-{index + 1:02d}",
                "text": labeled_text(
                    index=index,
                    subject=subjects[index],
                    body=body,
                    include_sender=not missing_sender,
                    location=None if missing_location else LOCATIONS[index],
                ),
                "expected_document_type": document_type,
                "expected_unit_id": unit_id,
                "expected_missing_fields": missing,
                "expected_reference_chunk_ids": [reference_id],
                "expected_template_id": (
                    "eksik_bilgi_talebi_v1" if missing else "ust_yazi_v1"
                ),
                "tags": [
                    "sentetik",
                    prefix.lower(),
                    *( ["challenge_paraphrase"] if index >= 6 else [] ),
                ],
            }
        )
    return records


def make_information_records() -> list[dict[str, object]]:
    subjects = (
        "Bakım programı hakkında bilgi edinme başvurusu",
        "Otoyol çalışmaları hakkında bilgi",
        "Köprü denetim kayıtları hakkında bilgi edinme",
        "Yol kapanış süreleri hakkında bilgi edinme",
        "Trafik sayım sonuçları hakkında bilgi edinme",
        "Kış bakım programı hakkında bilgi",
        "2026 kavşak çalışmaları kayıtları",
        "Yol ağına ilişkin yıllık istatistikler",
    )
    records: list[dict[str, object]] = []
    for index, subject in enumerate(subjects):
        missing_sender = index in {1, 4}
        missing_request = index in {3, 6}
        missing = ["gonderen"] if missing_sender else []
        if missing_request:
            missing.append("talep")
            body = "Başvurunun kapsamı 2026 yılı karayolu faaliyet kayıtlarıdır."
        else:
            body = (
                "Kayıtların tarafıma gönderilmesini istiyorum."
                if index == 7
                else "Bilgi edinme kapsamında ilgili kayıtların tarafıma verilmesini talep ediyorum."
            )
        records.append(
            {
                "record_id": f"BILGI-{index + 1:02d}",
                "text": labeled_text(
                    index=index,
                    subject=subject,
                    body=body,
                    include_sender=not missing_sender,
                ),
                "expected_document_type": "bilgi_talebi",
                "expected_unit_id": "ORKGM-BE-001",
                "expected_missing_fields": missing,
                "expected_reference_chunk_ids": ["SENT-KRY-004"],
                "expected_template_id": (
                    "eksik_bilgi_talebi_v1" if missing else "cevap_yazisi_v1"
                ),
                "tags": [
                    "sentetik",
                    "bilgi",
                    *( ["challenge_paraphrase"] if index >= 6 else [] ),
                ],
            }
        )
    return records


def make_general_records() -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for index in range(6):
        missing_sender = index in {1, 4}
        missing_request = index in {2, 4}
        missing = ["gonderen"] if missing_sender else []
        if missing_request:
            missing.append("talep")
        body = "Karayolu çevresindeki sürekli gürültü nedeniyle rahatsızlık yaşanmaktadır."
        if not missing_request:
            body += " Şikayetimin incelenmesini ve gereğinin yapılmasını istiyorum."
        records.append(
            {
                "record_id": f"SIKAYET-{index + 1:02d}",
                "text": labeled_text(
                    index=index,
                    subject="Karayolu çevresindeki gürültü hakkında şikayet",
                    body=body,
                    include_sender=not missing_sender,
                ),
                "expected_document_type": "sikayet",
                "expected_unit_id": "ORKGM-EB-001",
                "expected_missing_fields": missing,
                "expected_reference_chunk_ids": [],
                "expected_template_id": (
                    "eksik_bilgi_talebi_v1" if missing else "cevap_yazisi_v1"
                ),
                "tags": ["sentetik", "sikayet"],
            }
        )

    for index in range(6):
        missing_sender = index in {1, 5}
        missing_request = index in {2, 5}
        missing = ["gonderen"] if missing_sender else []
        if missing_request:
            missing.append("talep")
        body = "Bu dilekçe genel nitelikli bir başvuru kaydıdır."
        if not missing_request:
            body += " Başvurumun kayıt altına alınmasını talep ediyorum."
        records.append(
            {
                "record_id": f"DILEKCE-{index + 1:02d}",
                "text": labeled_text(
                    index=index,
                    subject="Genel dilekçe başvurusu",
                    body=body,
                    include_sender=not missing_sender,
                ),
                "expected_document_type": "dilekce",
                "expected_unit_id": "ORKGM-EB-001",
                "expected_missing_fields": missing,
                "expected_reference_chunk_ids": [],
                "expected_template_id": (
                    "eksik_bilgi_talebi_v1" if missing else "cevap_yazisi_v1"
                ),
                "tags": ["sentetik", "dilekce"],
            }
        )
    return records


def make_official_letter_records() -> list[dict[str, object]]:
    cases = (
        ("Asfalt bakım çalışması", "Yol bakım programının uygulanması hususunda gereğini rica ederim.", "ORKGM-YB-001", "SENT-KRY-001"),
        ("Hasarlı bariyer", "Trafik güvenliği için bariyer yenilemesi hususunda gereğini rica ederim.", "ORKGM-TG-001", "SENT-KRY-002"),
        ("Heyelan hasarı", "Heyelan nedeniyle oluşan hasarın incelenmesi hususunda gereğini rica ederim.", "ORKGM-AF-001", "SENT-KRY-003"),
        ("Asfalt kaplama", "Asfalt kaplama onarımı hususunda gereğini rica ederim.", "ORKGM-YB-001", "SENT-KRY-001"),
    )
    records: list[dict[str, object]] = []
    for index, (subject, body, unit_id, reference_id) in enumerate(cases):
        missing_date = index == 3
        missing = ["tarih"] if missing_date else []
        text = labeled_text(
            index=index,
            subject=subject,
            body=f"İlgi: 2026/{index + 1}\nDağıtım: İlgili birimler\n{body}",
            include_date=not missing_date,
        )
        records.append(
            {
                "record_id": f"USTYAZI-{index + 1:02d}",
                "text": text,
                "expected_document_type": "ust_yazi",
                "expected_unit_id": unit_id,
                "expected_missing_fields": missing,
                "expected_reference_chunk_ids": [reference_id],
                "expected_template_id": (
                    "eksik_bilgi_talebi_v1"
                    if missing
                    else "bilgilendirme_yazisi_v1"
                ),
                "tags": ["sentetik", "ust_yazi"],
            }
        )
    return records


def main() -> None:
    records: list[dict[str, object]] = []
    records.extend(
        make_domain_records(
            prefix="BAKIM",
            document_type="yol_bakim_talebi",
            unit_id="ORKGM-YB-001",
            reference_id="SENT-KRY-001",
            subjects=(
                "Asfalt kaplama bozukluğu",
                "Yol yüzeyindeki çukurlar",
                "Bozuk yol kaplaması",
                "Asfalt yüzey onarımı",
                "Çukur ve kaplama problemi",
                "Yol bakım ihtiyacı",
                "Sürüş yüzeyindeki derin oyuklar",
                "Güzergâh yüzeyindeki dalgalanma",
            ),
            descriptions=(
                "Yol yüzeyinde geniş çukurlar ve asfalt bozulması bulunmaktadır.",
                "Devlet yolunda oluşan çukurlar araç geçişini zorlaştırmaktadır.",
                "Bozuk yol kaplaması sürüş konforunu azaltmaktadır.",
                "Asfalt yüzeyde derin çatlaklar oluşmuştur.",
                "Çukur ve kaplama kaybı yol yüzeyinde yayılmıştır.",
                "Belirtilen kesimde yol bakım ihtiyacı gözlenmiştir.",
                "Araç tekerlerinin içine girdiği derin oyuklar oluşmuştur.",
                "Tekerlek izleri boyunca yüzeyde belirgin dalgalanma vardır.",
            ),
            request_sentence="Yol bakım ve onarım çalışması yapılmasını talep ediyorum.",
            request_sentences=(
                "Yol bakım ve onarım çalışması yapılmasını talep ediyorum.",
                "Yol bakım ve onarım çalışması yapılmasını talep ediyorum.",
                "Yol bakım ve onarım çalışması yapılmasını talep ediyorum.",
                "Yol bakım ve onarım çalışması yapılmasını talep ediyorum.",
                "Yol bakım ve onarım çalışması yapılmasını talep ediyorum.",
                "Yol bakım ve onarım çalışması yapılmasını talep ediyorum.",
                "Bu bölümün düzeltilmesini istiyorum.",
                "Sürüş yüzeyinin yenilenmesini istiyorum.",
            ),
        )
    )
    records.extend(
        make_domain_records(
            prefix="TRAFIK",
            document_type="trafik_guvenligi_bildirimi",
            unit_id="ORKGM-TG-001",
            reference_id="SENT-KRY-002",
            subjects=(
                "Hasarlı trafik işaret levhası",
                "Eksik bariyer",
                "Sinyalizasyon arızası",
                "Yaya geçidi güvenliği",
                "Kaza riski oluşturan levha",
                "Trafik güvenliği problemi",
                "Yönlendirme tabelası yere düşmüş",
                "Kavşak ışıkları düzensiz yanıyor",
            ),
            descriptions=(
                "Trafik işaret levhası devrilmiş durumdadır.",
                "Yol kenarındaki bariyerin bir bölümü eksiktir.",
                "Kavşaktaki sinyalizasyon sistemi çalışmamaktadır.",
                "Yaya geçidinde görünür işaretleme bulunmamaktadır.",
                "Hasarlı levha sürücüler için kaza riski oluşturmaktadır.",
                "Belirtilen noktada trafik güvenliği sorunu vardır.",
                "Yön gösteren tabela taşıtların geçtiği alana düşmüştür.",
                "Kırmızı ve yeşil ışıklar doğru sırayla yanmamaktadır.",
            ),
            request_sentence="Trafik güvenliği tedbirlerinin alınmasını talep ediyorum.",
            request_sentences=(
                "Trafik güvenliği tedbirlerinin alınmasını talep ediyorum.",
                "Trafik güvenliği tedbirlerinin alınmasını talep ediyorum.",
                "Trafik güvenliği tedbirlerinin alınmasını talep ediyorum.",
                "Trafik güvenliği tedbirlerinin alınmasını talep ediyorum.",
                "Trafik güvenliği tedbirlerinin alınmasını talep ediyorum.",
                "Trafik güvenliği tedbirlerinin alınmasını talep ediyorum.",
                "Tehlikeli durumun giderilmesini istiyorum.",
                "Işık düzeninin düzeltilmesini istiyorum.",
            ),
        )
    )
    records.extend(
        make_domain_records(
            prefix="HASAR",
            document_type="hasar_bildirimi",
            unit_id="ORKGM-AF-001",
            reference_id="SENT-KRY-003",
            subjects=(
                "Heyelan kaynaklı yol hasarı",
                "İstinat duvarında hasar",
                "Köprü yaklaşımında çökme",
                "Sel sonrası yol hasarı",
                "Yamaçta heyelan",
                "Köprü korkuluğu hasarı",
                "Şevden kaya parçaları düşmesi",
                "Destek duvarının dışa eğilmesi",
            ),
            descriptions=(
                "Heyelan nedeniyle yol platformunda hasar oluşmuştur.",
                "İstinat duvarında geniş çatlak ve hasar görülmektedir.",
                "Köprü yaklaşım dolgusunda çökme oluşmuştur.",
                "Sel sonrasında yol gövdesi zarar görmüştür.",
                "Yamaçtan kopan malzeme heyelan riski oluşturmaktadır.",
                "Köprü korkuluklarında belirgin hasar vardır.",
                "Yamaçtan kopan büyük kaya parçaları geçiş alanına düşmüştür.",
                "Yol kenarındaki destek duvarı dışa doğru eğilmiştir.",
            ),
            request_sentence="Acil inceleme ve gerekli müdahalenin yapılmasını talep ediyorum.",
            request_sentences=(
                "Acil inceleme ve gerekli müdahalenin yapılmasını talep ediyorum.",
                "Acil inceleme ve gerekli müdahalenin yapılmasını talep ediyorum.",
                "Acil inceleme ve gerekli müdahalenin yapılmasını talep ediyorum.",
                "Acil inceleme ve gerekli müdahalenin yapılmasını talep ediyorum.",
                "Acil inceleme ve gerekli müdahalenin yapılmasını talep ediyorum.",
                "Acil inceleme ve gerekli müdahalenin yapılmasını talep ediyorum.",
                "Geçiş güvenliği için bölgenin incelenmesini istiyorum.",
                "Duvarın kontrol edilmesini istiyorum.",
            ),
        )
    )
    records.extend(make_information_records())
    records.extend(make_general_records())
    records.extend(make_official_letter_records())
    assert len(records) == 48
    payload = {
        "dataset_name": "Sentetik Karayolu Evrak Gold Değerlendirme Seti",
        "version": "1.0.0",
        "usage": "Yalnızca prototip, test ve yarışma demosu; tüm kişi ve yerler kurgusaldır.",
        "data": records,
    }
    OUTPUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"{len(records)} kayıt yazıldı: {OUTPUT}")


if __name__ == "__main__":
    main()
