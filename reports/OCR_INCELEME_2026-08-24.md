# OCR İnceleme Raporu — 24 Ağustos 2026

## Sonuç ve kullanım sınırı

İki zayıf metin katmanlı PDF için CPU üzerinde EasyOCR `1.7.2`, Türkçe +
İngilizce tanıma ve 150 DPI render ile sayfa bazlı aday metin üretildi. Her iki
çıktıda da boş sayfa kalmadı. Bunlar **makine OCR adaylarıdır**; insanın sayfa
bazlı karşılaştırması tamamlanmadan aktif RAG kanıtı veya üretim kuralı değildir.

`approved_for_active_rag=false` ve `production_legal_evidence=false` korunmuştur.

## Nihai aday çıktılar

| Belge | Sayfa | OCR sayfası | Karakter | Ortalama sayfa güveni | Süre |
|---|---:|---:|---:|---:|---:|
| Resmî Yazışma Kılavuzu | 26 | 26 | 29.073 | 0,8062 | 193,988 sn |
| Resmî Yazışma Yönetmeliği + örnekler | 49 | 49 | 67.183 | 0,8361 | 383,700 sn |

- Kılavuz aday metni:
  `data/processed/ocr_review/official-writing-guide.ocr-candidate.txt`
- Yönetmelik tam-OCR aday metni:
  `data/processed/ocr_review/full_ocr/official-writing-regulation.ocr-candidate.txt`
- İlk sayfa bazlı karşılaştırma raporu: `reports/ocr_review_2026-08-24.json`
- Yönetmelik tam-OCR raporu:
  `reports/ocr_review_regulation_full_2026-08-24.json`

Model denetim izi de rapora yazıldı:

- `craft_mlt_25k.pth`: 83.152.330 byte, SHA-256
  `4a5efbfb48b4081100544e75e1e2b57f8de3d84f213004b14b85fd4b3748db17`
- `latin_g2.pth`: 15.406.141 byte, SHA-256
  `aaa95be1c4a9cb3496879bed7c520886ce1164f89e026f0c54488394e74e8c55`

## Neden tam OCR kullanıldı?

İlk geçiş boş/düşük karakterli sayfaları OCR, 250 ve üzeri karakterli sekiz
sayfayı yerel metin katmanından aldı. Görsel karşılaştırma, bu eşik üstündeki
metnin de eksik olduğunu gösterdi:

| Yönetmelik sayfası | Yerel metin katmanı | Tam OCR |
|---:|---:|---:|
| 11 | 370 karakter | 2.718 karakter |
| 14 | 291 karakter | 2.796 karakter |
| 24 | 378 karakter | 1.162 karakter |
| 45 | 543 karakter | 1.279 karakter |

Bu nedenle 49 sayfalık yönetmelik paketinin tamamı ikinci geçişte OCR ile
yeniden üretildi. Karma geçiş 59.183 karakter, tam geçiş 67.183 karakter verdi.

## Görsel ve metinsel QA

Görsel olarak kılavuzun 1, 3 ve 26'ncı sayfaları; yönetmelik paketinin 1, 11,
14, 16, 17, 24, 26, 30, 33, 40 ve 45'inci sayfaları incelendi. Başlık, içindekiler,
`10. KONU`, `MADDE 39`, yürütme hükmü, muhatap örnekleri ve belge doğrulama
örnekleri OCR metninde bulunabildi.

Tanıma kusurları sürmektedir. Örneğin kılavuzun ikinci sayfasında birleşik
kelime ve yıl hataları; bazı yönetmelik sayfalarında `resmî/resmi`,
`yazışma/yazısma`, URL ayraçları ve satır sıralaması hataları görülmüştür.
Ortalama güven skoru bu nedenle insan doğrulamasını kaldırmaz. Yapısal
chunking'den önce en az şu kontroller yapılmalıdır:

1. Her sayfa render ile aday metin yan yana karşılaştırılmalı.
2. Madde/fıkra/bent numaraları, tarih/sayı, URL ve özel adlar düzeltilmeli.
3. Kılavuzun yerel 26 sayfalık kesik kopyası kullanılmamalı; tam 102 sayfalık
   resmî sürüm alınarak aynı OCR ve bütünlük QA'sı tekrarlanmalı.
4. Yönetmelik için kanonik MBS/TCCB kopyası ve ek seti bağlanmalı.
5. Yalnız uzman imzalı inceleme CSV'sinden sonra manifestte aktif onay verilmeli.

## Tekrarlama

OCR aracı `scripts/ocr_review.py` dosyasındadır. `.[ocr]` optional dependency
grubu sürüm uyumlu CPU paketlerini kurar. Araç kaynak PDF ve OCR model hash'ini,
her sayfanın yöntemi, karakter sayısı, güveni ve süresini JSON rapora kaydeder;
hiçbir koşulda kendiliğinden aktif RAG onayı üretmez.
