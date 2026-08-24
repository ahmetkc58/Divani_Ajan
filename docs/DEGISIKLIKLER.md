# Değişiklik Günlüğü

Proje tanımı kökteki `project.md`, ajan davranış sözleşmesi kökteki `openai.md`
dosyasındadır. Bu dosya uygulama değişikliklerini, doğrulamaları ve kalan
engelleri kaydeder.

## 25 Ağustos 2026 — Canlı Gemini ürün kabulü

- UI'daki üç demo metni ayrı `synthetic_ui_fixtures.json` sözleşmesine alındı;
  gold ve UI fixture dosyalarının SHA-256 değerleri kodda pinlendi. Tek karakter
  değişen girdi yeniden `restricted` olur ve ağ çağrısından önce reddedilir.
- Snapshot Adjudicator yükü kapalı allowlist'e indirildi: yalnız chunk kimliği,
  başlık, madde/sayfa, doğrulama ve güncellik/hukuki-kullanım bayrakları dışarı
  çıkabilir. Özgün mevzuat paragrafı, kaynak yolu ve belge gövdesi yerelde kalır.
- LLM adım izine gerçek ağ denemesi, hata kodu ve yeniden-denenebilirlik alanları
  eklendi. Web arayüzünün Akış sekmesi Document Understanding ve Adjudicator
  rollerini sağlayıcı/model, veri sınıfı ve güvenlik sonucuyla gösterir.
- Gerçek Gemini 2.5 Flash kabulünde iki rol de strict JSON şemasıyla `success`
  verdi (`synthetic` belge anlama, `public` kapalı metadata Adjudicator). Snapshot
  güncelliği doğrulanmadığından Adjudicator önerisi insan incelemesine bırakıldı;
  deterministik uygunluk ve kullanıcı onayı kapıları korunmuştur.
- `run_llm_live_acceptance.py`, geçici 429/5xx durumunda en fazla üç sınırlı yeni
  süreç dener; ayrıca değiştirilmiş fixture için iki rolün de
  `network_attempted=false` ile engellendiğini doğrular.
- LLM ürün yolu ve veri güvenliği hedef paketi **66/66 geçti**. Tam depo koşusu
  **421 testte 412 geçti, 1 atlandı, 6 başarısız, 2 hata** verdi; kalan sekiz
  sonuç daha önce kaydedilmiş OCR/snapshot provenance artifact
  uyuşmazlıklarıdır ve güven kayıtları otomatik olarak yeniden yazılmamıştır.

## 24 Ağustos 2026 — Güvenli LLM orkestrasyonu, sentetik LegalGraph ve OCR

### LLM ve çok ajanlı karar zinciri

- Ücretsiz varsayılan sağlayıcı Gemini, model `gemini-2.5-flash` seçildi.
- Provider-independent HTTPS katmanı, kapalı/strict JSON Schema doğrulaması,
  prompt-injection sınırı ve anahtarsız deterministik fallback eklendi.
- Planın Researcher → Auditor → Adjudicator ayrımı ana akışa bağlandı.
  Adjudicator yalnız doğrulanmış referans kimliklerini ve yerel kodun ürettiği
  kapalı şablon/birim allowlist'ini görebilir.
- Yalnız hash ile tanınan sentetik gold evraklar dış LLM'e gönderilebilir;
  gerçek/kısıtlı evrak çağrıları ağdan önce fail-closed reddedilir.
- Gemini Free Tier veri kullanım koşulu nedeniyle bu dışa aktarım sınırı
  gevşetilmedi; gerçek hukuk evrakı için ücretli/veri-koruma onaylı bir katman
  ayrıca değerlendirilmelidir.
- LLM/graf çıktısı uygunluk denetimini veya insan onayını atlayamaz. Çalışma
  durumu ve readiness uçları provider/model/fallback/graf izini saklar.

### Seçici sentetik kanıt grafı

- Dondurulmuş evidence graph yüklenirken şema, taşınabilir yollar ve üç girdinin
  SHA-256 değeri doğrulanır; graf girdilerden yeniden üretilerek düğüm/kenar
  semantiği de karşılaştırılır.
- Yalnız doğrulanmış sentetik chunk kimliklerinden başlayan iki adımlı yollarla
  birim, şablon ve zorunlu alan adayları çıkarılır.
- Public/snapshot korpusta veya eşleşen doğrulanmış kural yoksa graf abstain
  eder. Graf daima `legal_reliance_allowed=false` kalır.

### OCR ve gönderen alanı

- Unicode/görünmez karakter temizliği ve güvenli satır-sonu dehyphenation
  eklendi.
- Karma PDF'lerde kalite kararı sayfa bazında verilir; yalnız zayıf/boş
  sayfalar OCR'dan geçirilip özgün sayfa sırası korunur.
- Boş/okunamaz OCR sayfası belgeyi fail-closed durdurur. PDF sayfa, sayfa başı
  piksel, toplam OCR pikseli ve belge/sayfa süre sınırları eklendi; senkron OCR
  işi API event loop'undan threadpool'a taşındı ve motor stderr'i dışarı verilmez.
- Raster görüntülü sayfada kısa watermark metni OCR'ı atlatamaz; kısa imza
  çıktısı yalnız yapısal ad + büyük harfli soyad ve watermark denylist kapısıyla
  kabul edilir. Metin karakter sınırı sessiz kesme yerine fail-closed çalışır.
- Normal, OCR-bozulmuş, ayrı satıra düşmüş ve aynı satıra yapışmış alan
  etiketleri; kurum/ad-soyad devamları ve kontrollü imza bloğu fallback'i
  desteklendi.
- Geçersiz tarih, placeholder, talep cümlesi ve düz metin false-positive
  kapıları eklendi. OCR düzeltmesi sınıflandırma güvenini artırmaz ve özgün
  retrieval kanıt metnini değiştirmez.

### Doğrulama

- Yeni LLM, graf, OCR, API ve orkestrasyon hedef paketi: **110 geçti, 1 gerçek
  Tesseract testi ortamda ikili bulunmadığı için atlandı**.
- Tüm depo paketi: **407 geçti, 1 atlandı, 6 başarısız, 2 collection error**.
  Aynı 8 sorun bu turdan önce de bulunan veri-artifact tutarsızlıklarıdır: iki
  OCR aday hash'i,
  karantina JSON'larındaki başka makineye ait mutlak yollar ve snapshot gold
  dosya hash'i. Bu turda public/snapshot provenance'i sahte biçimde yeniden
  yazılmadı.
- Gerçek Gemini çağrısı güvenli çalışma ortamında anahtar bulunmadığı için
  yapılmadı; anahtarsız ve kısıtlı
  veri yollarının hiç ağ çağrısı yapmadığı sahte transport ile doğrulandı.

### Açık kalanlar

- Gemini Free Tier veri kullanım koşullarının operasyonel olarak izlenmesi ve
  bağımsız Türkçe
  hukuk/OCR kör değerlendirmesi.
- PNG/JPG/TIFF yükleme ve bu formatlarda magic-byte/piksel sınırı, sayfa bazlı
  OCR güven izi ve insan doğrulamalı CER/WER-alan F1 ölçümü.
- İnsan onaylı güncel kamu mevzuatı grafı; mevcut graf yalnız sentetik testtir.

## 24 Ağustos 2026 — Yanlış çalışma klasöründen seçici aktarım

### İnceleme

- Doğru çalışma kökü `pwd` ile doğrulandı.
- Doğru projedeki mevcut ve izlenmeyen değişiklikler korunarak `git status`
  kaydedildi.
- `<yanlis-calisma-klasoru>` bir Git deposu olmadığı için dosya
  bazlı karşılaştırıldı; klasör silinmedi veya değiştirilmedi.
- Sanal ortam, pytest/ruff cache'i, bytecode ve toplu kaynak kopyaları kapsam
  dışı bırakıldı.

### Belgeler

- `project.md` ve `openai.md` doğru proje köküne uyarlandı.
- Şartname kapanış sırası `GELISTIRME_PLANI_2026-08-24.md` içinde kod ve veri
  odaklı olarak düzenlendi; rapor/sunum kod freeze sonrasına bırakıldı.
- Yanlış klasörde tamamlanmış gösterilen fakat doğru projede bulunmayan Docker,
  TTL, görsel API yükleme ve benzeri özellikler tamamlandı diye taşınmadı.

### Qdrant readiness

- `QdrantReadinessReport` ve salt okunur koleksiyon doğrulaması eklendi.
- Readiness; vektör şeması, zorunlu payload indeksleri, toplam nokta sayısı,
  corpus fingerprint, embedding model/boyut/görev ve indeks sürümünü denetler.
- Hibrit retrieval için `/ready` başarılı durumda 200, eksik/uyumsuz bağımlılıkta
  açıklamalı 503 döndürür. `/health` liveness ucu olarak ayrı kaldı.
- Sorgu yolu artık eksik Qdrant koleksiyonu oluşturmaz veya indeks onarmaz.
- İndeksleme yolu koleksiyonu oluşturabilmeye devam eder; yanlış klasördeki
  indekslemeyi bozan `require_collection()` değişikliği taşınmadı.

### Doğrulama

- `tests/test_qdrant_store.py` + `tests/test_api.py`: **26/26 geçti**.
- Tüm pytest paketi: **215/215 geçti** (Python 3.12).
- Ruff tam kural seti, taşınan davranışla ilişkili olmayan mevcut B008,
  RUF012, DTZ005, TRY004, import sırası ve satır uzunluğu borçlarını raporladı;
  bu seçici aktarımda ilgisiz kod yeniden biçimlendirilmedi.

### Kalan dış kapılar

- İnsan onaylı güncel kamu mevzuatı corpus'u.
- Gerçek Qdrant sunucusunda aktif-corpus readiness smoke testi.
- OCR/görsel belge ana akışı, paketleme/CI ve lisans kararları.
- Push öncesi PDF, kişisel veri, secret ve yeniden dağıtım hakkı incelemesi.
