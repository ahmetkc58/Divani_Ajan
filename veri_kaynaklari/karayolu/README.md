# Karayolu Kaynak Verileri

Bu klasör, aşağıdaki iki resmî bağlantıdan 23 Ağustos 2026 tarihinde alınan
herkese açık kaynakları içerir:

- UAB Karayolu mevzuatı, sayfa 4:
  `https://www.uab.gov.tr/bilgi-merkezi/mevzuat/?legislation_topic=Karayolu&page=4`
- DETSİS, 24325150 numaralı birim:
  `https://detsis.gov.tr/birim/24325150/24325150/2026-08-23`

## Dosyalar

- `uab_karayolu_mevzuat_page4.html`: UAB kaynak sayfasının ham HTML'i.
- `uab_karayolu_mevzuat_page4.json`: Sayfadaki kayıtların yapılandırılmış hâli.
- `uab_karayolu_mevzuat_page4.csv`: Aynı kayıtların Excel uyumlu CSV hâli.
- `uab_pdf/`: Sayfada bağlantısı verilen 10 PDF.
- `detsis_24325150.html`: DETSİS kaynak sayfasının ham HTML'i.
- `detsis_24325150_metadata.json`: Doğrulanabilen istek bilgileri, tespit edilen
  veri uçları ve erişim durumu.
- `detsis/`: DETSİS'ten alınan ham ve temiz kurum, belge, hizmet ve mevzuat
  veri kümeleri ile CSV dışa aktarımları.
- `detsis_chunk_618.js`, `detsis_birim_page.js`: DETSİS istemci kodunun veri
  uçlarını doğrulamak için arşivlenen parçaları.
- `extract_sources.py`: HTML kaynaklarını tekrar JSON/CSV'ye dönüştüren betik.

## Veri kalitesi notları

- UAB sayfa 4, `Karayolu` filtresine rağmen iki havacılık kaydı döndürmektedir.
  Kayıtlar kaynakla birebir uyum için silinmemiş, `scope_assessment` alanında
  kapsam dışı olarak işaretlenmiştir.
- DETSİS sayfası verileri JavaScript ile API'den yüklemektedir. Sayfanın kullandığı
  `Accept-Version: v1`, `Origin` ve `Referer` başlıkları doğrulandıktan sonra veri
  başarıyla alınmıştır: 585 belge, 566 hizmet ve 501 mevzuat kaydı.
- DETSİS numarası `24325150`, Karayolları Genel Müdürlüğüne değil Ulaştırma ve
  Altyapı Bakanlığı ana kurumuna aittir. Bu nedenle sonuçlar tüm ulaştırma
  alanlarını içerir. `detsis/karayolu_*.json` dosyaları anahtar kelimeyle
  daraltılmış yardımcı listelerdir ve insan doğrulaması gerektirir.
- DETSİS mevzuat kayıtlarının KAYSİS detay bağlantıları da veri kümelerine
  eklenmiştir. KAYSİS sayfaları otomatik indirmede yönlendirme döngüsüne girdiği
  için detay HTML'leri kaydedilmemiş, `local_archive` alanı `null` bırakılmıştır.
- Bu klasörde vatandaş evrakı, kişisel işlem kaydı veya kapalı kamu verisi yoktur.
