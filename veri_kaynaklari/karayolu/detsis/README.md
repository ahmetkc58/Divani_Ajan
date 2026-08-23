# DETSİS 24325150 Veri Arşivi

Kaynak: `https://detsis.gov.tr/birim/24325150/24325150/2026-08-23`

Bu DETSİS numarası **Ulaştırma ve Altyapı Bakanlığı** ana kurumuna aittir;
Karayolları Genel Müdürlüğünün özel kaydı değildir.

## Tam veri kümeleri

- `belgeler.json` / `belgeler.csv`: 585 istenen veya düzenlenen belge türü.
- `hizmetler.json` / `hizmetler.csv`: 566 hizmet ve kurum hiyerarşisi.
- `mevzuatlar.json` / `mevzuatlar.csv`: 501 mevzuat kaydı.
- `kurum_kunyesi_temiz.json`: Kişi adı, özgeçmiş ve görsel içermeyen kurum künyesi.
- `*_raw.json`: DETSİS API yanıtlarının değiştirilmemiş hâli.

## Karayolu yardımcı kümeleri

- `karayolu_belgeleri.json`: 11 kayıt.
- `karayolu_hizmetleri.json`: 92 kayıt.
- `karayolu_mevzuatlari.json`: 33 kayıt.

Bu üç liste anahtar kelime eşleştirmesiyle üretilmiştir. Kesin alan sınıflandırması
değildir ve RAG veri tabanına alınmadan önce alan uzmanı tarafından incelenmelidir.

## Teknik not

DETSİS istemcisi aşağıdaki başlıklarla veri çağrısı yapmaktadır:

- `Accept-Version: v1`
- `Origin: https://detsis.gov.tr`
- `Referer: https://detsis.gov.tr/`

Mevzuat kayıtlarındaki `detail_url` alanları KAYSİS sayfalarına gider. Bu sayfalar
otomatik indirmede yönlendirme döngüsü oluşturduğu için yerel detay arşivi yoktur.
