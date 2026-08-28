# Divani Ajan dokümantasyon indeksi

Bu dizin, projede yapılan çalışmaların konu bazında ayrılmış teknik kaydıdır.
`DEGISIKLIKLER.md` kronolojik günlüktür; aşağıdaki belgeler ise bir özelliğin
bugünkü mimarisini, çalışma biçimini, doğrulamasını ve sınırlarını açıklar.

| Konu | Belge | Kapsam |
|---|---|---|
| Şartname | [01_SARTNAME_ANALIZI.md](01_SARTNAME_ANALIZI.md) | İstenen görevler, uygulananlar ve açık kapılar |
| Yerel LLM | [02_YEREL_OLLAMA.md](02_YEREL_OLLAMA.md) | Gemini yerine Ollama, güvenlik ve ayarlar |
| Belge alımı | [03_BELGE_ALIMI_VE_OCR.md](03_BELGE_ALIMI_VE_OCR.md) | TXT/MD/PDF/görsel okuma ve sınırlar |
| Çıktı | [04_LATEX_VE_PDF_CIKTISI.md](04_LATEX_VE_PDF_CIKTISI.md) | Temiz şablon, PDF üretimi ve indirme |
| Mimari | [05_FRONTEND_BACKEND_REST.md](05_FRONTEND_BACKEND_REST.md) | Ayrık servisler, REST köprüsü ve CORS |
| API teslimi | [06_SWAGGER_OPENAPI.md](06_SWAGGER_OPENAPI.md) | Frontend ekibine verilecek sözleşme |
| Organizasyon | [07_ORGANIZASYON_SEMASI.md](07_ORGANIZASYON_SEMASI.md) | Görsel şemanın aktarımı ve veri sınırı |
| Yönlendirme | [08_GUVENLI_BIRIM_YONLENDIRME.md](08_GUVENLI_BIRIM_YONLENDIRME.md) | Kapalı katalog, puanlama ve insan incelemesi |
| Test ve işletim | [09_TEST_VE_CALISTIRMA.md](09_TEST_VE_CALISTIRMA.md) | Servisleri başlatma, test PDF'leri ve sonuçlar |

## Genel belgeler

- [MIMARI.md](MIMARI.md): kısa mimari özeti.
- [SARTNAME_EKSIKLERI_UYGULAMA_PLANI.md](SARTNAME_EKSIKLERI_UYGULAMA_PLANI.md): yalnız açık kalan işler.
- [DEGISIKLIKLER.md](DEGISIKLIKLER.md): kronolojik değişiklik günlüğü.
- [GUNLUK_DURUM_2026-08-24.md](GUNLUK_DURUM_2026-08-24.md): önceki günlük durum kaydı.

## Dokümantasyon ilkesi

Bir özellik yalnız kodda bulunmasına göre tamamlandı sayılmaz. Her konu
belgesinde ilgili kaynak dosyalar, test kanıtı, yapılandırma ve bilinen sınırlar
birlikte belirtilir. Gerçek kurum verisi, güncel mevzuat veya saha başarısı
ölçülmemişse sentetik sonuçlar bunların yerine geçirilmez.
