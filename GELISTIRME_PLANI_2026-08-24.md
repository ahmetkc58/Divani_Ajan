# Divani Ajan — Kod Kapanış Planı

Bu plan rapor ve sunumdan önce kodu, veri akışını, vektör veritabanını,
şartname eksiklerini ve teknik dokümantasyonu kapatmak için kullanılır.

Durum etiketleri: **Kapandı**, **Kısmi**, **Açık**, **Dış kapı**.

## P0 — Çalışma ağacı ve güvenli teslim

**Durum: Kısmi**

- Doğru proje kökü tek çalışma alanı olarak kullanılmalı.
- Mevcut kirli çalışma ağacı korunmalı; ilgisiz değişiklik geri alınmamalı.
- PDF, arşiv, gerçek kişi verisi, API anahtarı, model cache'i ve Qdrant storage
  GitHub'a gönderilmemeli.
- Push yalnız kullanıcı onayı ve gönderilecek dosya denetiminden sonra yapılmalı.

Kapanış: `git status`, ignore kuralları, secret/PII/lisans incelemesi ve kullanıcı
onayı birlikte tamamlanır.

## P1 — Uçtan uca zorunlu görevler

**Durum: Kısmi**

Bu turda kapanan alt işler:

- Ücretsiz Gemini 2.5 Flash için strict JSON Schema kullanan opsiyonel LLM sınırı;
  anahtarsız, kısıtlı veri ve sağlayıcı hatalarında deterministik fallback.
- Researcher/Auditor/Adjudicator ayrımı ile sentetik multi-hop kanıt grafının
  şablon ve birim kararına allowlist olarak bağlanması.
- LLM/graf kararından sonra deterministik uygunluk ve insan onayı kapılarının
  korunması.

- Metin/PDF alımı, sınıflandırma, alan çıkarımı, mevzuat arama, şablon seçimi,
  kurgu birim yönlendirme ve taslak akışı tek demo senaryosunda doğrulanmalı.
- Eksik bilgi, düşük güven, alakasız belge ve uygunluk hatası akışı otomasyonu
  güvenli biçimde durdurmalı.
- Ana akış 20 tekrarlı çalıştırmada kalıcı süreç çakışması üretmemeli.

Kapanış: pozitif, negatif, abstention ve insan onayı testleri ile kayıtlı demo
smoke sonucu.

## P2 — Aktif mevzuat veri akışı

**Durum: Dış kapı**

- Kanonik kaynak, SHA-256, byte/sayfa, yürürlük, kapsam, OCR/metin kalitesi,
  madde/sayfa izi ve inceleyen kişi kaydı tamamlanmalı.
- Aktif corpus yalnız yazılı uzman kararıyla üretilmeli.
- Değişen veya eski kaynak indekslenmemeli; eski indeks hazır sayılmamalı.

Kapanış: en az 3–4 güncel belge, tüm aktif chunk'larda tam provenance ve en az
100 uzman etiketli gerçek-corpus sorgusu. Otomatik/sahte onay kabul edilmez.

## P3 — Qdrant ve hibrit retrieval

**Durum: Kısmi**

Kapandı:

- Passage/query görev ayrımı, vektör boyutu ve model/kod revision metadata'sı.
- Aynı corpus üzerinde contextual BM25 + dense + RRF.
- Corpus/chunk fingerprint ve fail-closed sonuç doğrulaması.
- Read-only `/ready`: şema, payload indeksleri, toplam/uyumlu nokta sayısı,
  embedding sözleşmesi ve corpus fingerprint kontrolü.
- Sorgu sırasında eksik koleksiyon oluşturulmaması.

Açık:

- Versiyonlu koleksiyon ve atomik alias geçişi.
- Gerçek Qdrant sunucusunda boş/eski/fingerprint'i yanlış koleksiyon smoke testi.
- Operasyonel Qdrant healthcheck ve uygulama başlatma bağımlılığı.
- Gerçek corpus kabul ölçümü: Recall@5, MRR, citation precision, abstention ve
  sıcak p95.

## P4 — Belge/OCR dayanımı

**Durum: Kısmi**

Bu turda kapanan alt işler:

- OCR gürültüsünde Unicode/görünmez karakter ve güvenli satır-sonu düzeltmesi.
- Gönderen/başvuran etiket varyantları, OCR-glif bozulmaları, ayrı/yapışık
  alanlar, devam satırları ve kontrollü imza bloğu fallback'i.
- Geçersiz tarih ve düz metin false-positive kapıları; alan çıkarım yönteminin
  `source` izinde saklanması.
- PDF için sayfa bazlı metin kalite kararı; yalnız zayıf/boş sayfaların OCR'dan
  geçirilmesi ve sayfa sırasının korunması.
- OCR boş sonucunda fail-closed durma; PDF sayfa, piksel ve toplam/sayfa süre
  sınırları; API event loop'undan threadpool izolasyonu.

Açık:

- PNG/JPG/TIFF yükleme ile bu formatlarda magic-byte ve piksel sınırı.
- OCR alanlarına sayfa/güven izi ve kullanıcı düzeltme akışı.
- İnsan doğrulamalı taranmış sayfa setinde CER/WER ve alan F1 ölçümü.

## P5 — Resmî yazı kalite kapısı

**Durum: Kısmi**

- Dört sürümlü şablon, şemalı alanlar ve LaTeX kaçışı korunmalı.
- İlgi, ek, dağıtım, muhatap, imza/unvan ve arz/rica kuralları test edilmeli.
- Eksik kritik alan veya uygunluk hatası onayı engellemeli.
- En az 30 gold yazıda kritik biçim hatası ve görsel PDF taşması ölçülmeli.

## P6 — Güvenlik, saklama ve paketleme

**Durum: Açık**

- Süreç/artifact TTL ve kullanıcı tetiklemeli silme.
- Dış API yanıtında mutlak yerel yol sızıntısının engellenmesi.
- Loopback varsayılanı; haricî açılım varsa kimlik doğrulama.
- Kilit dosyası, temiz kurulum, wheel smoke, bağımlılık audit'i ve SBOM.
- Jina `CC BY-NC 4.0`, PDF/OCR araçları ve veri yeniden dağıtım kararları.

## P7 — Bağımsız değerlendirme ve kod freeze

**Durum: Açık**

- Geliştirme, regresyon ve kör setler ayrılmalı; hash ile dondurulmalı.
- Sonuçlarda veri sürümü, commit, kirli ağaç durumu ve pay/payda bulunmalı.
- Kod freeze sonrasında nihai kör koşu bir kez yapılmalı; sonuç görülerek koda
  benchmark'a özel ayar yapılmamalı.

## P8 — Rapor, sunum ve video

**Durum: Ertelendi**

Başlama koşulu: P0–P7 içindeki zorunlu kapılar kapanmış, kod dondurulmuş ve
nihai ölçümler kaydedilmiş olmalıdır. O zamana kadar öncelik kod, veri akışı,
Qdrant, şartname eksikleri ve dokümantasyondur.
