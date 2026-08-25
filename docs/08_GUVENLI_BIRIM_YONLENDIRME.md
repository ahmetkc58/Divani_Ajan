# Organizasyon şeması tabanlı güvenli birim yönlendirme

## Amaç

Dışarıdan gelen evrakın içeriğini organizasyon şemasındaki uygun birime
eşlemek; yeterli kanıt yokken kesin havale üretmemek ve sistemin şemada olmayan
birim uydurmasını engellemektir.

## Kapalı hedef listesi

`RoutingAgent` yalnız `data/organization/kgm_units_2026-07-16.json` içinde
`accepts_external_documents=true` olan kayıtları aday yapar. LLM kullanılsa
bile yeni birim adı veya kimliği üretemez; yalnız deterministik aday listesinden
seçim yapabilir.

Eski `data/synthetic_units.json` değerlendirme ve geriye uyumluluk senaryoları
için korunmuştur; ana çalışma zamanı kataloğu değildir.

## Kullanılan sinyaller

Yönlendirme sorgusu şu alanlardan oluşturulur:

- Evrak türü
- Özet
- Özgün retrieval kanıt metni
- Analiz anahtar kelimeleri
- Çıkarılmış alanların dolu değerleri, özellikle konu ve konum

Her aday için:

- Tam anahtar ifade eşleşmesi: ağırlık 4
- Sorumluluk token örtüşmesi: ağırlık 1
- Yetki/konum eşleşmesi: ağırlık 6

Kanıtlar `anahtar:`, `sorumluluk:` ve `yer:` önekleriyle REST sonucunda
saklanır. İlk üç alternatif birim, hiyerarşi, normalize skor ve kendi kanıtları
ile döner.

## İnsan inceleme kapıları

Aşağıdaki koşullardan biri varsa `routing_status=needs_review` ve
`requires_human_review=true` üretilir:

- En iyi adayın ham kanıt puanı 4'ün altındaysa.
- İkinci aday varsa normalize skor farkı %20'nin altındaysa.
- Belge sınıflandırma güveni %60'ın altındaysa.
- Seçilen profil `chart_only` statüsündeyse.

Kanıt bulunamadığında hedef `GENEL MÜDÜRLÜK` olur; bu bir kesin havale değil,
ön inceleme önerisidir.

## REST sonucu

Örnek karar alanları:

```json
{
  "unit_id": "ORKGM-YB-001",
  "unit_name": "YOL BAKIM VE ONARIM ŞUBE MÜDÜRLÜĞÜ",
  "routing_status": "needs_review",
  "requires_human_review": true,
  "organization_version": "2026-07-16",
  "score_margin": 0.18,
  "evidence": ["anahtar:yol bakım", "anahtar:asfalt"]
}
```

## Arayüz

Özet ekranı önerilen birimle birlikte şunları gösterir:

- İnsan incelemesi gerekli / otomatik öneri hazır durumu
- Tam organizasyon hiyerarşisi
- Katalog sürümü
- Skor farkı
- Eşleşme kanıtları

## Test edilen senaryolar

- Asfalt/çukur -> Yol Bakım ve Onarım
- Levha/bariyer -> Trafik Güvenliği İşaret
- Köprü hasarı -> Köprü Bakım ve Onarım
- Kamulaştırma -> Kamulaştırma
- Personel atama -> Personel ve Atama
- Yazılım/API -> Yazılım Geliştirme
- Kanıtsız genel belge -> Genel Müdürlük + insan incelemesi
- İstanbul konum eşleşmesi -> Bölge adayı + zorunlu insan incelemesi
- Yol bakım ve trafik işaretleri birlikte -> yakın skor + insan incelemesi

## Canlı belirsizlik testi

`divani_ajan_test_belirsiz_yonlendirme.pdf` yüklemesinde sistem Yol Bakım ve
Onarım birimini ilk, Trafik Güvenliği İşaret birimini alternatif seçti. Skor
farkı `0.18` olduğu için sonuç `needs_review` olarak döndü. Bu test sırasında
ham puan farkı ile normalize fark arasındaki tutarsızlık tespit edilerek eşik
API'de gösterilen normalize skorla aynı ölçüte bağlandı.

## İlgili dosyalar

- `src/karayol_agent/agents/routing.py`
- `src/karayol_agent/schemas.py`
- `src/karayol_agent/orchestrator.py`
- `frontend/static/app.js`
- `tests/test_organization_routing.py`
