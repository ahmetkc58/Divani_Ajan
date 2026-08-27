# Şartname Karşılaştırması ve Kalan Eksikler

**Güncelleme tarihi:** 25 Ağustos 2026 (bkz. **Bölüm 0** — 27 Ağustos 2026 taze bulgularla güncellendi)

**İncelenen sürüm:** `main@93b3e08` (Bölüm 0, `main@6e2f306` üzerinde yeniden doğrulandı)

**Kaynaklar:** `project.md`, `openai.md`, 2026 TYDA Teknik Şartnamesi 1. Senaryo,
uygulama kodu, testler, veri manifestleri ve kayıtlı kabul raporları.

Bu belge yalnızca açık kalan işleri içerir. Kod ve testlerle mevcut olduğu
doğrulanan özellikler iş listesinden çıkarılmıştır. Bir özelliğin kaynak kodda
bulunması tek başına tamamlanma sayılmaz; kör ölçüm, insan onayı veya teslim
kanıtı gerekiyorsa ilgili kapı açık tutulur.

## 0. 27 Ağustos 2026 güncellemesi (HEAD@6e2f306)

25 Ağustos'tan bu yana üç yeni commit geldi (`b457fb7` kör değerlendirme +
teslim envanteri, `0c37b4a` UAB vektör indeksi verisi, `6e2f306` GPU'lu yerel
UAB retrieval runner). Aşağıdaki bölümler (1-7) büyük ölçüde geçerliliğini
koruyor; bu bölüm yalnız o tarihten beri **doğrulanan** değişiklikleri
özetler. Kaynak: şartname PDF'inin tam metin incelemesi + `git show --stat
93b3e08..HEAD` + tam pytest çalıştırması + canlı `/api/v1/system/readiness`
sorgusu.

### Kapanan veya belirgin ilerleyen maddeler

- **2.4 (şartname PDF'i) KAPANDI.** Çalışma ağacındaki her iki kök PDF kopyası
  da artık kanonik `c4e0dc804ea07d2783975cea2f45cf9ab833828181d1837ad64a67617ca17fdd`
  hash'iyle eşleşiyor; bozuk kopya sorunu kalmamış.
- **2.3 (veri/dağıtım kapsamı) belirgin ilerledi.** `data/manifests/delivery_policy.json`,
  `scripts/audit_delivery_inventory.py` ve makinece üretilen
  `reports/delivery_inventory.json` artık gerçekten var: 75 izlenen dosyanın
  tamamına (`unresolved: 0`) include/exclude/review_required kararı, sınıf,
  lisans ve hash atanmış (13 include, 61 exclude, 1 review_required — şartname
  PDF'inin kendisi). CI, `test-and-package` işinin son adımında bu denetimi
  zorunlu kılıyor. **Açık kalan:** bu kararların fiilen ayrı bir teslim
  dalı/paketinde uygulandığının (exclude edilenlerin fiziksel pakette
  bulunmadığının) ayrıca doğrulanması gerekiyor; audit script'i şu an yalnız
  "sınıflandırma eksiksiz mi" sorusunu cevaplıyor, "paket temiz mi" sorusunu
  değil.
- **3.1 (aktif korpüs) ölçek olarak büyüdü, onay durumu değişmedi.** UAB
  bakanlık arşivi artık 10.048 parça olarak `uab_ministry_archive_chunks_v1`
  koleksiyonuna indekslenmiş ve canlı sunucu (`/api/v1/system/readiness`)
  bunu `"ready": true, "Qdrant hazır: 10048/10048 uyumlu nokta"` diye
  doğruluyor. Ancak `currentness_verified` ve `legal_reliance_allowed` hâlâ
  `false`; insan onaylı/hukuken güvenilir parça sayısı hâlâ **0**. Madde 3.1
  tamamen açık kalmaya devam ediyor, yalnız hacim değişti.

### Yeni P0 bulgu — madde 2.1'in bağımsız kör ölçümü artık var ve SONUÇ ZAYIF

`data/evaluation/blind_documents_v1.json` (20 kayıt, geliştirme
fixture'larından bilinçli olarak bağımsız yazılmış) ve
`scripts/evaluate_blind_documents.py` artık gerçekten mevcut — madde 2.1'in
altyapı açığı kapandı. Ancak `reports/blind_evaluation_v1.json`'daki ilk
ölçüm sonucu **9/20 (%45) genel başarı**; kategori kırılımı:

| Kategori | Sonuç |
|---|---|
| `paraphrase_positive` (asıl "görülmemiş ifade" testi) | **1/7 (%14)** |
| `no_answer_offtopic` (uydurmama/abstention) | 1/4 |
| `near_miss_ambiguous` (insan incelemesine bırakma) | 4/5 |
| `ocr_noise_variant` (gürültüye dayanıklılık) | 3/4 |

**Kök neden:** `ClassificationAgent.LABEL_KEYWORDS` — sınıflandırma ve
yönlendirme tamamen anahtar-kelime kural motoruna dayanıyor; varsayılan
BM25/`trusted_synthetic` yolunda hiçbir LLM/semantik katman devrede değil.
Klasik ifadeler dışına çıkan gerçekçi bir cümle (`"zemin çöküntüsü"` yerine
`"çukur"`, `"yön gösterme direği"` yerine `"tabela"` gibi) çoğunlukla yanlış
türe veya genel havuz birimine (`ORKGM-EB-001`) düşüyor. Sistem en azından
**güvenli tarafta hata yapıyor** (yanlış tahminlerde bile çoğunlukla
`requires_human_review=true` işaretliyor, mevzuat uydurmuyor), ama şartname
madde 6.4.1'in "metni anlamlandırarak" ifadesi ve puanlama madde 9
"Uygulama" (35 puan, "sınıflandırma doğruluğu, yönlendirme başarımı")
kriteri için bu doğrudan risk. **Kapanış ölçütü güncellemesi:** madde 2.1'in
"Yapılacaklar" listesi artık "kör set oluştur" değil, "paraphrase
başarısını %45'ten kabul edilebilir bir eşiğe çıkar" olmalı — ya
anahtar-kelime listesini gerçekçi eşanlamlılarla genişletmek ya da
sınıflandırmaya bir LLM/embedding katmanı eklemek gerekiyor.

### Yeni P0 bulgu — CI'ın kendi "core acceptance tests" kapısı şu an KIRMIZI

`.github/workflows/ci.yml`'deki `test-and-package` işinin adı verilen tam
test listesini yerelde birebir çalıştırdım: **6 test başarısız** —
`test_extractor.py` (1) ve `test_graph_decision_support.py` (5). Bu, mevcut
HEAD push edilirse CI'ın kırmızı olacağı ve wheel paketleme/teslim envanteri
adımlarına hiç ulaşamayacağı anlamına geliyor.

- **Kök neden (graph, 5 test):** `data/synthetic_gold.json` düzenlendi ama
  kanıt grafının pinlenmiş girdi SHA-256'sı yenilenmedi —
  `GraphBuildError: Kanıt grafı girdisi SHA-256 ile uyuşmuyor:
  data\synthetic_gold.json`. Aynı kök neden canlı sunucunun kendi
  `/api/v1/system/readiness` yanıtında da görünüyor
  (`"evidence_graph_ready": false`). Ayrıca CI'a dahil olmayan
  `tests/test_orchestrator_llm_integration.py`'de 5 test daha aynı nedenle
  başarısız (LLM adım verisi beklenen `DataClassification.SYNTHETIC` yerine
  daha muhafazakâr `RESTRICTED` dönüyor — sistem güvenli tarafta hata yapıyor,
  ama sentetik demo yolu bu haliyle kırık). **Tek bir bayat pin, 10'dan
  fazla testi ve bir canlı API uyarısını aynı anda kırıyor; kapanışı tek
  komutla (grafı `data/synthetic_gold.json`'ın güncel hash'iyle yeniden
  üretmek) mümkün olmalı.**
- **Kök neden (extractor, 1 test):** `test_real_tesseract_scanned_pdf_extracts_sender_end_to_end`
  gerçek Tesseract çalıştırıyor; bu makinede Tesseract kurulu ama yalnız
  `eng`+`osd` dil verisi mevcut, **`tur.traineddata` yok**
  (`tesseract --list-langs` doğrulandı). Türkçe OCR bu geliştirme
  makinesinde şu an hiç çalışmıyor demektir — şartname 6.4.1 "Evrakı OCR ...
  okuyabilme" gerekliliği taranmış Türkçe evrak için fiilen test edilemez
  durumda. Düzeltme ucuz: Tesseract Türkçe dil paketinin kurulması.
- **CI'a dahil olmayan ama tam çalıştırmada görülen ek başarısızlıklar:**
  `test_resource_manifest.py` (bir dataset card dosyası yeniden kaydedilmiş,
  manifest'teki byte sayısı bayatlamış), `test_snapshot_relevance.py`
  (`competition_snapshot_relevance_v1.json`'ın pinlenmiş corpus hash'i güncel
  `competition_snapshot.json` ile uyuşmuyor — yani madde 3.3'teki "snapshot
  alaka seti" regresyon kapısı şu an güncel korpüsü doğrulamıyor),
  `test_snapshot_corpus.py` (2 — satır/chunk sayısı sabitleri veri
  değişince bayatlamış), `test_ocr_candidate_ingestion.py` (3 başarısız + 2
  hata). Bunların hepsi aynı örüntüyü gösteriyor: hızla değişen
  `data/processed/` çıktıları ile testlere gömülü sabit hash/sayı pinleri
  senkronize kalmıyor. **Öneri:** veri üreten her script, pin'i de aynı
  commit'te yeniden üretmeli; CI'a "pin güncel mi" kontrolü eklenebilir.

### Yeni bulgu — committed veride bir katkı sağlayanın yerel yol/kullanıcı adı sızıntısı

`data/processed/stage3_quarantine/{law-2918, law-4925,
uab-road-expropriation-regulation, uab-road-infrastructure-safety-regulation,
uab-road-traffic-regulation, uab-road-transport-regulation}.json` (6 dosya,
`3b82e13` ile commit'lenmiş, hâlâ git'te izleniyor) `source_file`/`source`
alanlarında şu mutlak Windows yolunu taşıyor:
`C:\Users\matri\OneDrive\Desktop\testing3\Divani_Ajan\Divani_Ajan\...` — bu
mevcut kullanıcının (`Ahmet`) değil, muhtemelen bir takım arkadaşının
makinesi. Etkisi iki yönlü:

1. Bu mutlak yol proje kökü dışında olduğu için, onu proje-köküne göre
   çözmeye çalışan doğrulama kodu (`karayol_agent.ingestion.snapshot`)
   `SnapshotBuildError` fırlatıyor — `test_snapshot_relevance.py`
   başarısızlığının bir parçası bu.
2. `delivery_inventory.json` bu 6 dosyayı zaten `exclude` olarak işaretlemiş,
   yani teslim paketine girmeyecek — ama geliştirme deposunun (ve `origin`
   git geçmişinin) içinde bir katkı sağlayanın yerel klasör adı ve kullanıcı
   adı kalıcı olarak duruyor; küçük ama gerçek bir bilgi sızıntısı.

**Kapanış:** bu dosyaları üreten alım adımı mutlak yol yerine proje-göreli
yol yazmalı (`scripts/build_uab_archive_snapshot.py`'deki `_portable()`
yardımcısı gibi); mevcut 6 dosya proje-göreli yola normalize edilip yeniden
commit'lenmeli.

## 1. İnceleme notu

Şartnamenin özellikle şu bölümleri esas alınmıştır:

- **6.3-6.4:** İki zorunlu görevin uçtan uca tamamlanması,
- **6.4.1:** OCR/metin okuma, anlamlandırma, sınıflandırma, bilgi ve eksik alan
  çıkarımı, mevzuat önerisi ve özet,
- **6.4.2:** Resmî yazı türü seçimi, resmî üslup, birim yönlendirme, kullanıcı
  bilgilendirmesi ve eksik bilgi talebi,
- **6.5:** Gerçek kamu evrakı/verisi kullanmama; kurgu evrak, yapay taslak,
  açık kaynak metin ve kamuya açık mevzuatla çalışma,
- **7:** Türkçe teknik rapor ve dokümantasyon, bilimsel atıf, açık kaynak depo,
  veri kümesi teslimi ve üçüncü taraf lisans uyumu,
- **8-9:** Uçtan uca Türkçe demo, veri kaynağı/hak açıklaması, internet
  kesintisine karşı önerilen yedek plan,
  sınıflandırma-yönlendirme-özet-taslak-eksik bilgi kalitesi ve gerçek zamana
  yakın çalışma,
- **13.1 ve 14:** Adillik, kapsayıcılık, yanıltıcı sonuç üretmeme, kişisel veri
  ve fikrî mülkiyet sorumluluğu.

Çalışma ağacındaki şartname PDF'i bozuk sıkıştırma akışları içeriyor ve 16
sayfayı boş render ediyor. İnceleme, yerel değişikliğe dokunulmadan Git'teki
sağlam `HEAD` kopyası üzerinden yapıldı. Sağlam kopyanın SHA-256 değeri
`c4e0dc804ea07d2783975cea2f45cf9ab833828181d1837ad64a67617ca17fdd`,
çalışma kopyasının değeri ise
`6aedc51aae3a0525eb0dccb44ac4b76e95f2038ebca4ea689668ffb06c4549d7`.

## 2. P0 - Şartname başarısını doğrudan etkileyen açıklar

### 2.1. Görülmemiş/paraphrase evrakı anlamlandırma

**Mevcut açık:** Kavram sinyalleri eklendikten sonra kayıtlı sekiz
`challenge_paraphrase` örneğinde sınıflandırma, yönlendirme ve şablon sonucu
**8/8** oldu. Ancak bu örnekler geliştirme deposunda görünür olduğundan sonuç
bağımsız kör genelleme kanıtı değildir. Yerel Ollama görülmemiş/kısıtlı girdiyi
cihaz dışına çıkarmadan işleyebilir; yine de 20-30 bağımsız örnek ve önceden
yazılmış kabul eşiği gereklidir.

**Yapılacaklar:**

1. Mevcut geliştirme fixture'larından bağımsız, en az 20-30 evraklık kör Türkçe
   paraphrase/near-miss seti hazırlamak ve hash ile dondurmak.
2. Yerel Ollama/kavram katmanının kör sette genellemesini ölçmek; örneğe özel
   yeni kelime kuralı eklememek.
3. Kör set açılmadan hedef eşikleri yazmak; test açıldıktan sonra örneğe özel
   kural eklememek.

**Kapanış ölçütü:** Kör sette sınıflandırma, yönlendirme top-1/top-3 ve şablon
başarımı pay/payda ile raporlanmalı; near-miss örneklerinde yanlış kesin karar
sayısı ayrıca gösterilmelidir.

**Uygulanan güvenlik düzeltmesi:** 16.07.2026 tarihli organizasyon şeması,
personel adları çıkarılarak sürümlü ve kapalı bir hedef kataloğuna aktarıldı.
Katalog dışı hedef üretimi engellendi; kanıtsız, düşük güvenli, yakın skorlu ve
yalnız merkez şehri bilinen taşra önerileri `needs_review` durumuna bağlandı.
Bu bölümde açık kalan iş, bağımsız uzman onaylı görev/yetki profili ve kör başarı
ölçümüdür.

### 2.2. Resmî yazışma biçim ve üslup kalite kapısı

**Mevcut açık:** İlgi, ek, dağıtım, iletişim, paraf/koordinasyon, elektronik
imza, belge üstverisi, makam ilişkisi ve tekil kapanış artık şema, dört LaTeX
şablonu ve uygunluk motorunda bulunuyor. Çelişkili makam-kapanış kararı ve
kanıtsız kaynak atfı onaya geçemiyor. Açık kalan bölüm, kuralların yetkili insan
tarafından doğrulanması ve en az 30 gold PDF'in taşma/yerleşim açısından görsel
kontrolüdür.

**Yapılacaklar:**

1. Resmî yazışma kılavuzundan insan doğrulamalı kural matrisi üretmek.
2. UI'da yeni alanlar için ayrı düzenleme kontrolleri ve açıklamalar eklemek.
3. Kapanış ifadesini gönderen-muhatap makam ilişkisine bağlamak; belirsizlikte
   insan incelemesini zorunlu tutmak.
4. Mevzuat atfının kabul edilmiş retrieval parçasında gerçekten bulunduğunu ve
   taslakta anlamı değiştirilmeden kullanıldığını doğrulamak.
5. En az 30 gold taslağı PDF'e render edip taşma, kesilme, Türkçe karakter,
   başlık, imza, ilgi, ek ve dağıtım yerleşimini görsel olarak kontrol etmek.

**Kapanış ölçütü:** Kritik alanı eksik, yanlış kapanışlı veya kanıtsız atıflı
taslak onaya/PDF'e geçmemeli; gold taslaklarda kritik biçim hatası kalmamalıdır.

### 2.3. Yarışma veri sınırı ve dağıtılacak depo içeriği

**Mevcut açık:** `delivery_policy.json` ve denetim betiği her izlenen veri
dosyasına include/exclude/review kararı, sınıf, lisans durumu ve hash atıyor;
gerçek kaynaklar varsayılan teslimden dışlanıyor. Buna rağmen depoda 37 adet izlenen `veri_kaynaklari/` dosyası,
DETSİS ham/temiz kayıtları, resmî HTML/PDF arşivleri, başka resmî PDF'ler ve
31 MB gömülü Qdrant `storage.sqlite` dosyası bulunuyor. DETSİS arşivinde 585
belge, 566 hizmet ve 501 mevzuat kaydı var. Bunlar uygulamanın kurgu birim
verisi değildir ve şartnamenin veri sınırı ile yeniden dağıtım hakları açısından
teslim öncesi açık karar gerektirir.

**Yapılacaklar:**

1. Yarışma deposunda kalacak dosyalar için veri-sınıfı ve dağıtım izin matrisi
   çıkarmak.
2. Gerçek DETSİS kurum/hizmet/belge kayıtlarını çalışma zamanından ve yarışma
   veri kümesinden kesin olarak ayırmak; gerekiyorsa teslim dalından çıkarmak.
3. Kamuya açık mevzuat PDF'lerinin yeniden dağıtım hakkını tek tek doğrulamak;
   izin belirsizse dosya yerine kaynak URL'si, hash ve üretim talimatı bırakmak.
4. Qdrant veritabanını yeniden üretilebilir artifact olarak değerlendirmek;
   kaynak depoda tutulacaksa lisans, boyut ve veri sınırı kararını açıkça
   belgelemek.
5. Politika sonucuna göre gerçek teslim dalı/paketi üretmek; exclude kararlarının
   fiziksel teslim paketinde bulunmadığını CI artifact'ında doğrulamak.

**Kapanış ölçütü:** Teslim manifestindeki her dosyanın veri sınıfı, kaynağı,
lisansı ve dağıtım kararı bulunmalı; kurgu yönlendirme verisine gerçek kurum
kaydı karışmamalıdır.

### 2.4. Şartname PDF'inin sağlam teslim kopyası

**Mevcut açık:** Çalışma ağacındaki değiştirilmiş şartname PDF'i bozuk; Poppler
metin çıkarımı boş, render çıktıları beyaz ve sıkıştırma akışı hatalıdır.

**Yapılacaklar:** Kanonik kaynaktan sağlam kopyayı doğrulamak, kullanıcı kararıyla
bozuk yerel değişikliği düzeltmek ve push öncesi hash/render kontrolü yapmak.

**Kapanış ölçütü:** PDF 16 sayfayı hatasız açmalı, metin veya görüntü içeriği
görünür olmalı ve doğrulanan hash teslim kaydına yazılmalıdır.

## 3. P1 - Uygulama puanı ve güvenilirlik için açıklar

### 3.1. Güncel ve insan onaylı aktif mevzuat korpüsü

**Mevcut açık:** Yarışma snapshot'ı 8 belge ve 2.603 parça içeriyor; ancak
`currentness_verified=false` ve `legal_reliance_allowed=false`. UAB manifestinde
501 kaydın tamamı `needs_human_review`, aktif RAG onaylı kayıt sayısı **0**.
Sistem güvenli biçimde uyarı/abstention üretiyor fakat güncel mevzuat önerisi
iddiası henüz yapılamaz.

**Yapılacaklar:**

1. Kapsamdaki mevzuatı alan/hukuk uzmanına kaynak, yürürlük, kapsam, hash, OCR
   ve sayfa iziyle onaylatmak.
2. Yalnız onaylı parçaları `verified_public` korpüsüne almak ve ayrı Qdrant
   koleksiyonuna indekslemek.
3. En az 30-50 bağımsız uzman etiketli sorguda Recall@5, MRR, citation
   precision ve abstention ölçmek; mümkünse 100 sorguya genişletmek.
4. Eski, hash'i değişmiş ve yanlış fingerprint'li koleksiyonların fail-closed
   kaldığını gerçek Qdrant sunucusunda doğrulamak.

**Kapanış ölçütü:** Aktif korpüsteki her parça insan onayı ve kaynak izi taşımalı;
ölçüm snapshot fixture'larından bağımsız olmalıdır.

### 3.2. Görsel belge alımı ve OCR kalite kanıtı

**Mevcut açık:** PDF yanında PNG/JPG/TIFF doğrudan alımı, magic-byte kontrolü,
sayfa/piksel/süre sınırları ve boş OCR sonucunda fail-closed davranış var. Açık kalanlar:

- OCR sayfa/alan güven skoru süreç kaydında tutulmuyor,
- döndürülmüş, düşük DPI, fotokopi/faks ve karma düzenler için insan etiketli
  kalite ölçümü yok,
- CER, WER ve kritik alan F1 raporu yok.

**Yapılacaklar:** Görsel formatları güvenli decoder ve piksel sınırlarıyla
eklemek; dosya içeriğini uzantıdan bağımsız doğrulamak; sayfa/alan güven izini
UI'a taşımak; bozulma dilimleri içeren sentetik test setinde CER/WER/alan F1
ölçmek.

**Kapanış ölçütü:** Desteklenen tüm biçimlerde pozitif/negatif yükleme testleri
ve insan doğrulamalı OCR kalite raporu bulunmalıdır.

### 3.3. Bağımsız kalite değerlendirmesi

**Mevcut açık:** 48 kayıtlık sentetik gold set geliştirme ile aynı depoda ve
mevcut kurallarla birlikte kullanılıyor. Snapshot alaka seti yalnız 4
cevaplanabilir + 4 no-answer mühendislik regresyonundan oluşuyor. Aşağıdaki
şartname puan alanları için bağımsız ölçüm yok:

- özet sadakati ve kısalık,
- bilgi çıkarımı alan precision/recall/F1'i,
- resmî yazı üslup ve şablon kalitesi için insan puanı,
- OCR CER/WER/alan F1'i,
- uçtan uca p50/p95 gecikme ve tekrarlı koşu güvenilirliği,
- farklı Türkçe ifade biçimleri için adillik/yanlılık dilimleri.

**Yapılacaklar:** Geliştirme, regresyon ve kör test kümelerini ayırmak; kör seti
bağımsız değerlendiriciye hazırlatmak; tek komutla tüm metrikleri, Git commit'ini,
veri/model sürümünü, hata sayısını ve süreleri üreten değerlendirme akışı
oluşturmak.

**Kapanış ölçütü:** Kör değerlendirme raporu pay/payda, güven aralığı veya örnek
sayısı, hata analizi ve bilinen sınırları açıkça göstermelidir.

### 3.4. Gerçek zamana yakın çalışma ve yedek demo

**Mevcut açık:** Deterministik BM25 akışında standart, paraphrase ve near-miss
senaryoları 20'şer kez çalıştırıldı; 60/60 başarılı ve p95 11-16 ms aralığında.
PDF-OCR, hibrit RAG, yerel Ollama ve PDF derleme için soğuk/sıcak p50/p95 ile
final kayıttan demo/yedek çalışma paketi henüz yok.

**Yapılacaklar:** Metin, PDF-OCR, hibrit RAG, LLM başarı/fallback ve PDF derleme
senaryolarında uçtan uca süre ölçmek; en az 20 tekrar yapmak; çevrimdışı demo
komutunu, önceden hazırlanmış model/veri durumunu ve yedek video akışını
doğrulamak.

**Kapanış ölçütü:** Final makinesinde tekrarlanabilir canlı demo ile internet
kesintisine dayanıklı yedek demo birlikte bulunmalıdır.

## 4. P1 - Teslim ve açık kaynak zorunlulukları

### 4.1. Teknik rapor, sunum ve veri teslimleri

**Mevcut açık:** Türkçe README ve mühendislik raporları var; ancak şartnamede
istenen nihai teknik rapor ve PDF+PPTX final sunumu depoda yok. İnternet
kesintisine karşı şartnamede tavsiye edilen yedek demo kaydı da hazırlanmamış.

**Yapılacaklar:** Kod freeze ve kör metriklerden sonra Türkçe teknik rapor,
bilimsel kaynakça, veri kartları, mimari/ajan akışı, hata analizi, lisans bölümü,
10 dakikalık sunumun PDF ve PPTX sürümleri ve yedek demo kaydı hazırlanmalıdır.

### 4.2. Türkiye Açık Kaynak Platformu depo teslimi

**Mevcut açık:** Mevcut `origin`, kişisel
`https://github.com/ahmetkc58/Divani_Ajan.git` deposudur. Şartnamenin Türkiye
Açık Kaynak Platformu GitHub hesabında erişim şartının hangi organizasyon,
transfer veya ayna yöntemiyle karşılanacağı kayıtlı değildir.

**Yapılacaklar:** Düzenleyiciden teslim deposu/organizasyon bilgisini doğrulamak;
gerekli erişim, transfer veya mirror işlemini son teslimden önce tamamlamak ve
depo URL'sini teknik rapora eklemek.

### 4.3. Tekrarlanabilir temiz kurulum ve paketleme

**Mevcut açık:** `uv.lock`, CycloneDX SBOM ve GitHub Actions çekirdek test/paket
kapısı eklendi. Wheel dört şablonu ve sentetik demo verisini içeriyor; kurulu
paket `sys.prefix/share/karayol-agent` fallback'ini kullanıyor. Açık kalan bölüm
CI'ın uzak depoda gerçekten çalıştırılması ve RAG/OCR optional profillerinin
ayrı temiz ortam matrisinde doğrulanmasıdır.

**Yapılacaklar:**

1. Python 3.11/3.12 CI matrisini uzak depoda çalıştırmak.
2. RAG/OCR optional profilleri için ayrı kurulum ve smoke işi eklemek.
3. Temiz klon → kurulum → test → indeks/readiness → demo zincirini CI
   tekrarlanabilir betikle doğrulamak.
4. Üretilen SBOM'a insan doğrulamalı lisans kararlarını bağlamak.

### 4.4. Lisans ve yeniden dağıtım kapanışı

**Mevcut açık:** Apache-2.0 proje lisansı ve kaynak manifesti var; ancak Jina
modelleri `CC BY-NC 4.0`, EasyOCR CRAFT/Latin G2 ağırlıklarının lisansı belirsiz
ve resmî PDF/HTML arşivlerinin yeniden dağıtım kararı kapanmış değil. Bu durum
hem şartname uyumu hem ticarileşme puanı için risklidir.

**Yapılacaklar:** Kullanılan her kod, model, ağırlık, veri ve belgeyi fiilî
çalışma yolu ile eşleştiren lisans matrisi hazırlamak; belirsiz veya uyumsuz
bileşeni dağıtımdan çıkarmak ya da uygun alternatifle değiştirmek; bilimsel ve
lisans atıflarını teknik rapora taşımak.

## 5. P2 - Güvenlik, işletim ve ticarileşme açıkları

Bu bölümdeki işler iki zorunlu görevin çekirdeği değildir; ancak kişisel veri
sorumluluğu, gerçek dünya uygulanabilirliği, ölçeklenebilirlik ve
ticarileşme puanını doğrudan etkiler.

### 5.1. Süreç verisi yaşam döngüsü ve erişim kontrolü

**Mevcut açık:**

- API'de kimlik doğrulama, rol/yetki kontrolü ve oran sınırlama yok,
- süreç ve artifact'lar için TTL veya kullanıcı tetiklemeli silme ucu yok,
- süreç JSON'unda ham belge metni kalıcı tutuluyor,
- API modeli `tex_path`/`pdf_path` mutlak yerel yollarını döndürüyor,
- açık `reject`, `retry` ve denetlenebilir düzeltme geçmişi uçları yok.

**Yapılacaklar:** Yerel demo profilini üretim profilinden ayırmak; dışa açılan
profilde kimlik doğrulama/yetkilendirme, oran sınırı, saklama süresi, güvenli
silme, yol gizleme, redaksiyonlu log ve denetim izi eklemek.

### 5.2. Adillik, kapsayıcılık ve erişilebilirlik

**Mevcut açık:** Etik şartı adil/kapsayıcı Türkçe deneyimi bekliyor; buna karşılık
ağız, yazım bozukluğu, OCR hatası, kısa/uzun ifade, farklı kişi/kurum adı ve
engelli kullanıcı erişilebilirliği için tanımlı ölçüm bulunmuyor.

**Yapılacaklar:** Kimlik özelliği taşımayan kontrollü sentetik dil dilimleriyle
performans farkı ölçmek; hata mesajlarını sade Türkçe ve ekran okuyucu/klavye
kullanımıyla test etmek; WCAG odaklı temel UI kontrolü yapmak.

### 5.3. Ölçeklenebilirlik ve sürdürülebilir işletim kanıtı

**Mevcut açık:** Dosya tabanlı süreç deposu tek düğümlü MVP'dir; eşzamanlı
kullanım, iş kuyruğu, yatay ölçekleme, yedekleme/geri yükleme, gözlemlenebilirlik
ve maliyet modeli ölçülmemiştir.

**Yapılacaklar:** Hedef kullanım senaryosu ve kapasite varsayımı yazmak; hafif
eşzamanlı yük testi, hata bütçesi, log/metrik/trace planı, yedekleme ve yaklaşık
işlem maliyeti çıkarmak.

## 6. Uygulama sırası

| Sıra | İş | Bağımlılık | Tamamlanma kanıtı |
|---:|---|---|---|
| 1 | Paraphrase/genelleme açığını kapat | Kör set | Kör sınıflandırma-yönlendirme-şablon raporu |
| 2 | Resmî yazışma kalite kapısını tamamla | İnsan doğrulamalı kural matrisi | 30 gold render ve fail-closed testleri |
| 3 | Veri/dağıtım kapsamını temizle | Lisans ve kullanıcı kararı | Teslim dosya manifesti |
| 4 | Aktif mevzuatı uzman onayıyla oluştur | Alan/hukuk uzmanı | Onaylı korpüs ve bağımsız retrieval raporu |
| 5 | OCR/görsel giriş ve kalite ölçümünü tamamla | Görsel test seti | CER/WER/alan F1 ve yükleme testleri |
| 6 | Kör uçtan uca değerlendirme ve performans | 1-5 | Tek komutlu nihai metrik raporu |
| 7 | Temiz kurulum, paketleme ve lisans kapanışı | Kod freeze | CI/temiz klon, SBOM ve lisans matrisi |
| 8 | Teknik rapor, sunum ve yedek demo | Nihai metrikler | Türkçe rapor, PDF/PPTX ve demo paketi |
| 9 | TAKP GitHub teslimi | Düzenleyici depo bilgisi | Erişilebilir nihai depo URL'si |

## 7. Nihai açık kontrol listesi

- [ ] Görülmemiş Türkçe/paraphrase evraklarda kör sınıflandırma ve yönlendirme
  ölçümü kabul eşiğini karşılıyor.
- [ ] Resmî yazışmanın ilgi, ek, dağıtım, imza/üstveri ve makam kapanışı kuralları
  kod ve render testleriyle doğrulanıyor.
- [ ] Teslim deposunda gerçek DETSİS verisi, kamu PDF'leri ve Qdrant artifact'ları
  için açık veri/lisans/dağıtım kararı var.
- [ ] Şartname PDF'inin sağlam kanonik kopyası doğrulandı.
- [ ] Güncel mevzuat korpüsü insan onaylı; bağımsız retrieval ölçümü tamamlandı.
- [ ] Görsel belge biçimleri ile OCR güven/kalite ölçümü tamamlandı.
- [ ] Özet, bilgi çıkarımı, taslak, OCR ve uçtan uca gecikme bağımsız olarak
  ölçüldü.
- [ ] En az 20 tekrarlı canlı/çevrimdışı demo ve yedek kayıt hazır.
- [ ] Python 3.11+ temiz klon kurulumu, paketleme, test ve demo zinciri geçti.
- [ ] SBOM, lisans matrisi, veri kartları ve atıflar tamamlandı.
- [ ] Türkçe teknik rapor ile final sunumunun PDF ve PPTX sürümleri hazır.
- [ ] Türkiye Açık Kaynak Platformu GitHub teslim yolu doğrulandı.
- [ ] Üretim profili için erişim, saklama, silme ve yerel yol gizleme politikası
  uygulandı veya demo-sınırı olarak açıkça belgelendi.
- [ ] Adillik/kapsayıcılık ve temel erişilebilirlik kontrolleri raporlandı.
