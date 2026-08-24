# Karayolu Evrak Akıllı Ajan Sistemi

Bu depo, `PROJE_PLANI.md` içindeki TEKNOFEST 2026 projesinin çalışan MVP
uygulamasıdır. Sistem sentetik karayolu evraklarını uçtan uca işler:

1. metin/PDF alımı ve OCR fallback,
2. evrak sınıflandırma ve önemli alan çıkarımı,
3. eksik bilgi tespiti,
4. bağlamsal BM25 veya Jina Embeddings v3 + Qdrant + RRF hibrit arama,
5. kullanıcı-niyeti + görünür metin alaka kapısı ve kaynak doğrulama,
6. resmî yazı türü ve LaTeX şablonu seçimi,
7. sentetik birime yönlendirme,
8. güvenli LaTeX taslağı oluşturma,
9. uygunluk kontrolü ve süreç bilgilendirmesi.

Çevrimdışı demo akışı varsayılan olarak kural tabanlı BM25 ile çalışır. İsteğe
bağlı RAG katmanı aynı sorguyu Jina Embeddings v3 (`retrieval.query`) ve
contextual BM25 kanallarına gönderir, Qdrant dense sonuçlarını klasik RRF ile
birleştirir ve dense kanal kullanılamazsa bunu süreç teşhisinde açıkça belirterek
BM25'e döner. Varsayılan BM25 demo verileri sentetiktir. İsteğe bağlı
`competition_snapshot` modu depodaki 8 sabit yerel belgeyi zorunlu
güncellik/hukuki görüş uyarısıyla kullanır; `verified_public` yolu ise insan
onayı olmadan hâlâ fail-closed kalır.

## Yapılandırılmış LLM, LegalGraph karar zinciri ve OCR alan çıkarımı

24 Ağustos 2026 geliştirme turunda proje planındaki açık LLM orkestrasyonu,
seçici graf karar desteği ve OCR'dan alan tanıma katmanı birbirine bağlandı:

```text
Yerel OCR/alan çıkarımı
  → Researcher: BM25 veya Jina/Qdrant/RRF adayları
  → Auditor: kaynak, alaka, güncellik ve kullanım kapıları
  → sentetik multi-hop graf: kural → evrak türü → birim/şablon/zorunlu alan
  → Adjudicator: yalnız doğrulanmış kanıt ve kapalı aday listesi
  → deterministik uygunluk denetimi → insan onayı
```

- Ücretsiz LLM seçimi Google AI Studio Free Tier üzerindeki
  `gemini-2.5-flash` modelidir.
  Sağlayıcı çağrıları SDK bağımlılığı olmadan, strict JSON Schema ile yapılır.
- `GEMINI_API_KEY` yoksa ağ çağrısı yapılmaz; mevcut deterministik akış devam
  eder. Timeout, kota, bozuk JSON veya şema ihlalinde de sonuç serbest metin
  olarak kabul edilmez.
- Harici ücretsiz LLM'e yalnız sabit SHA-256 ile tanınan sentetik gold/UI demo
  evrakları çıkabilir. Snapshot Adjudicator çağrısında özgün mevzuat paragrafı
  dışarı verilmez; yalnız Auditor'ın kapalı aday kimlikleri, başlık/madde/sayfa
  metadata'sı ve `currentness_verified=false` / `legal_reliance_allowed=false`
  bayrakları aktarılır. Gerçek/kısıtlı evrak, API anahtarı bulunsa bile ağdan
  önce engellenir. Bu sınır gönderen, iletişim ve hukuk belgesi verilerini
  korumak için bilinçlidir; Gemini Free Tier içerikleri sağlayıcının ürün
  geliştirme politikasına tabi olabilir.
- Graf girdilerinin SHA-256'ları çalışma anında doğrulanır ve graf aynı
  girdilerden yeniden üretilip semantik olarak karşılaştırılır. Mevcut graf
  yalnız sentetik benchmark içindir; `legal_reliance_allowed=false` kalır ve
  üretim mevzuatı sayılmaz.
- OCR sonrası alan çıkarımı artık `Gönderici`, `Gönderen`, `Başvuru Sahibi`,
  `Müracaatçı`, `G0NDEREN`, `K0NU`, `TARlH`, ayrı satırdaki değerler ve güvenli
  imza bloğu fallback'ini tanır. Kullanılan yöntem alanın `source` izinde
  saklanır; özgün retrieval kanıt metni değiştirilmez.
- Karma PDF'lerde metin kalitesi sayfa bazında ölçülür; yalnız zayıf/boş
  sayfalar OCR'dan geçirilir ve özgün sayfa sırası korunur. Boş OCR sonucu
  belgeyi durdurur; PDF sayfa/piksel/süre sınırları ve API threadpool izolasyonu
  kaynak tüketimini sınırlar. Raster görüntülü sayfadaki kısa tarayıcı watermark'i
  text-layer sayılmaz; kısa imza OCR'ı yalnız yapısal ad/soyad kapısından geçer.

LLM'i sentetik demo/evaluasyon için etkinleştirmek üzere anahtarı yalnız çalışma
ortamında tanımlayın:

```powershell
$env:KARAYOL_LLM_PROVIDER="gemini"
$env:KARAYOL_LLM_MODEL="gemini-2.5-flash"
$env:GEMINI_API_KEY="<yerel-secret>"
```

Yerel `.env` dosyasını kullanarak güvenli demo yapılandırmasını tek komutla
başlatmak için `powershell -ExecutionPolicy Bypass -File
scripts/start_local_gemini.ps1` kullanılabilir. `.env` Git tarafından yok
sayılır ve depoya eklenmemelidir.

Çalışan serviste hem iki gerçek Gemini rolünü hem de değiştirilmiş fixture'ın
ağdan önce engellendiğini tekrar doğrulamak için:

```powershell
$env:PYTHONPATH="src"
python scripts/run_llm_live_acceptance.py
```

`/health`, `/ready` ve her `ProcessState`; LLM sağlayıcısı/modeli, fallback,
graf readiness'i, graf karar yolları ve rol bazlı LLM adımlarını anahtar
sızdırmadan açıklar. Ayrıntılı yapılandırma örneği `.env.example` içindedir.

Bu tur P4 OCR işinin tamamını kapatmaz: PNG/JPG/TIFF ana akışı ile bu formatların
magic-byte/piksel sınırları, sayfa bazlı OCR güven izi ve insan doğrulamalı
CER/WER-alan F1 ölçümü hâlâ ayrı kabul işleri olarak açıktır.

## Tamamlanan uygulama — 8 belgeli yarışma snapshot'ı

Bu geliştirme turunda yeni/güncel mevzuat kopyalarını edinme, proje planını
snapshot politikası için yeniden yazma ve mevcut aktivasyon kurallarını yeniden
tasarlama adımları **atlanmıştır**. Çalışma, depoda bulunan kaynakların güncel
hukuk metni olduğu iddia edilmeden mevcut proje snapshot'ı üzerinden devam
edecektir.

Bu teknik hedef **24 Ağustos 2026'da tamamlandı**:

- metin katmanı hazır 6 belge ile 2 OCR adayından gelen 2.606 kaynak satırı
  birleştirildi; 3 tam tekrar güvenli biçimde konsolide edilerek 8 belge ve
  **2.603 benzersiz yapısal parça** üretildi;
- 2.404 parça metin katmanından, 199 parça OCR adaylarından geldi; kaynak
  başlığı, madde/fıkra/bent, sayfa aralığı ve SHA-256 izi korundu;
- parçalar RTX 3050 üzerinde `jinaai/jina-embeddings-v3`
  (`retrieval.passage`, 1024D) ile gömülüp kalıcı gömülü Qdrant'taki ayrı
  `competition_snapshot_chunks_v1` koleksiyonuna yazıldı;
- indeks kapatılıp yeniden açıldıktan sonra **2.603/2.603** uyumlu nokta ve tam
  corpus parmak izi doğrulandı.
- Yol yüzeyi bakım talebi ve hasarlı trafik işareti için madde/ID allowlist'i
  kullanmayan iki denetlenebilir alaka profili eklendi. Önce özgün kullanıcı
  metninde olay kavramları doğrulanır; ardından RRF ile birleşen en fazla 40 aday
  görünür chunk metni üzerinden incelenir. Nesne ve görev/giderme kavramları
  birlikte bulunmazsa kaynak elenir, hiçbiri geçmezse yanlış atıf üretmek yerine
  abstain edilir. Expansion terimleri kullanıcı lexical kanıtı sayılmaz.

Bu yol, normal `verified_public` / `legal_chunks_v1` yolundan ayrıdır ve public
fail-closed kapısını gevşetmez. Snapshot parçaları hâlâ güncel/yürürlükte mevzuat
veya hukuki görüş olarak kullanılamaz; uygulama her atıfta sabit snapshot
uyarısını taşır.

## Kurulum

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

Jina v3 + Qdrant bileşenleri için isteğe bağlı RAG bağımlılıklarını da kurun:

```powershell
python -m pip install -e ".[dev,rag]"
```

Karantinadaki taranmış PDF'ler için Türkçe OCR inceleme aracını da kullanacaksanız:

```powershell
python -m pip install -e ".[dev,rag,ocr]"
```

Bu çalışma ortamında ana bağımlılıklar zaten kuruluysa kurulumsuz da
`$env:PYTHONPATH="src"` ile çalıştırılabilir.

## Komut satırı

```powershell
$env:PYTHONPATH="src"
python -m karayol_agent.cli process --file examples\yol_bakim_talebi.txt
```

Çıktılar varsayılan olarak `output/<evrak-id>/` altında saklanır. Sistemde
`xelatex`, `pdflatex` veya `tectonic` varsa PDF de derlenir; yoksa güvenli
`.tex` taslağı ve yapılandırılmış JSON çıktı üretilir.

Mevzuat PDF'sinin metin katmanını denetlemek ve Bölüm/Madde/Fıkra/Bent
yapısında karantina çıktısına parçalamak:

```powershell
python -m karayol_agent.cli ingest `
  --file mevzuat-1.pdf `
  --title "Resmî Yazışma Yönetmeliği" `
  --output data\processed\resmi_yazisma.json
```

Kalite eşiğini geçmeyen PDF indekslenmez ve OCR gerektiği raporlanır. Düşük
kaliteli metni zorla indekslemek yalnızca inceleme amacıyla
`--allow-low-quality` seçeneğiyle mümkündür. Bu seçenek aktif RAG onayı veremez.
Genel `ingest` komutu hiçbir kamu kaynağını doğrudan aktif korpusa alamaz.

### Yapısal mevzuat parçası sözleşmesi

Mevzuat metni öncelikle doğal hukuk hiyerarşisine göre **Bölüm → Madde →
Fıkra → Bent** sınırlarında parçalanır. Örneğin `MADDE 4- (1) ... a) ...`
yapısından aşağıdaki gibi bir parça üretilir:

```json
{
  "chunk_id": "MEV-3EE6799D5AA69232",
  "document_id": "uab-road-expropriation-regulation",
  "title": "Karayolu Yapımı Amaçlı Kamulaştırmalarda Hazine Taşınmazlarının Trampası Hakkında Yönetmelik",
  "section": "Birinci Bölüm — Amaç, Kapsam, Dayanak ve Tanımlar",
  "article": "Madde 4",
  "paragraph": "1",
  "clause": "a",
  "page": 1,
  "page_end": 1,
  "context_text": "... > Madde 4 > Fıkra 1 > Bent a > Yerel bağlam: Bu Yönetmelikte geçen;",
  "text": "a) Bakanlık: Maliye Bakanlığını,",
  "validity_status": "needs_verification",
  "approved_for_active_rag": false
}
```

- `text`, kullanıcıya gösterilebilecek asıl kaynak hükmüdür.
- `context_text`, parçanın belge içindeki yerini açıklayan yardımcı arama
  bağlamıdır; tek başına mevzuat hükmü veya alıntı olarak gösterilemez.
- Jina dense arama ve BM25 için indekslenecek içerik `context_text + text`
  olacaktır. Nihai atıf her zaman `text`, kaynak PDF, madde/fıkra/bent ve sayfa
  bilgisine döner.
- `page` ve `page_end`, hükmün PDF'de başladığı ve bittiği sayfaları korur.
- `chunk_id`; kararlı `document_id`, hukuk hiyerarşisi ve parça metninden
  SHA-256 tabanlı olarak türetilir. Kaynak dosya başka klasöre taşınsa bile
  kimlik değişmez.
- Bir doğal fıkra veya bent 1.800 karakteri aşarsa yalnız o parça cümle
  sınırlarında alt parçalara ayrılır; tüm alt parçalar aynı kaynak ve hiyerarşi
  metadata'sını taşır.

Bu paragraftaki JSON'lar karantina ara çıktılarıdır; tek başlarına embedding
değildir. İnsan incelemesi tamamlanmayan parçalar
`approved_for_active_rag=false` olarak kalır. Yarışma için birleşik
`competition_snapshot.json` ayrıca üretilmiş ve ayrı Qdrant koleksiyonuna
indekslenmiştir; bu işlem verified-public onayı vermez.

**Bilinen yapısal kalite notu:** 2918 sayılı Kanun gibi değişiklik dipnotları
içeren belgelerde “Birinci Bölüm başlığında...” ifadeleri bazı durumlarda gerçek
bölüm başlığı sanılabilir. Madde/fıkra/bent ve sayfa izi korunmasına rağmen
`section` alanı gürültülü olabilir. Aktif corpus onayından önce insan yapı
incelemesi veya bölüm başlığı normalizasyonu uygulanmalıdır.

## Mevzuat kapsam ayırma ve doğrulama manifesti

DETSİS mevzuat kayıtlarını fiziksel bir yerel PDF arşiviyle eşleştirmek, ulaşım
alanı adayı üretmek ve OCR kuyruğunu belirlemek için:

```powershell
$env:PYTHONPATH="src"
python -m karayol_agent.cli curate-legislation `
  --records veri_kaynaklari\karayolu\detsis\mevzuatlar.json `
  --archive "C:\veri\uab-mevzuat-pdf" `
  --output data\manifests\uab_legislation_manifest_v2.json `
  --review-csv data\manifests\uab_legislation_manifest_v2_review.csv `
  --inspect-pdfs
```

Komut iki çıktı üretir:

- `data/manifests/uab_legislation_manifest.json`: Makine tarafından okunabilir
  ana manifest, PDF eşleşmeleri, kapsam önerileri ve metin kalite sonuçları.
- `data/manifests/uab_legislation_manifest_review.csv`: Alan uzmanının kapsam,
  yürürlük ve aktif RAG onayı vermesi için inceleme tablosu.

Otomatik sınıflandırma hiçbir kaydı kendiliğinden aktif RAG verisi yapmaz.
`approved_for_active_rag` alanı insan doğrulaması tamamlanana kadar `false`
kalır. Böylece denizcilik, havacılık ve demiryolu mevzuatının karayolu
cevaplarına yanlışlıkla karışması önlenir.

İnceleme CSV'sini güvenlik kapılarıyla doğrulayıp yeni manifeste uygulamak ve
yalnız onaylı kayıtları parçalamak için:

```powershell
python -m karayol_agent.cli apply-legislation-review `
  --manifest data\manifests\uab_legislation_manifest_v2.json `
  --review-csv data\manifests\uab_legislation_manifest_v2_review.csv `
  --output data\manifests\uab_legislation_reviewed.json

python -m karayol_agent.cli ingest-approved-manifest `
  --manifest data\manifests\uab_legislation_reviewed.json `
  --output-dir data\processed\active_legislation
```

Aktivasyon için tekil PDF, geçerli SHA-256, insan kapsam onayı, doğrulanmış
yürürlük, doğrulanmış metin/OCR, inceleyen kişi ve inceleme zamanı birlikte
zorunludur. Çalışma alanında gerçekten bulunan ilk sekiz aday kaynak
`data/manifests/core_legislation_sources.json` dosyasında kayıtlıdır. Eski 501
kayıtlık manifestin işaret ettiği PDF arşivi bu çalışma alanında bulunmadığından
o kayıtlar şu anda ingestion girdisi değildir.

Depodaki çekirdek envanteri gerçek dosya hash'leri ve metin kalite kontrolüyle
inceleme manifestine dönüştürmek, ardından onaysız karantina corpusunu üretmek:

```powershell
python -m karayol_agent.cli curate-core-inventory

python -m karayol_agent.cli ingest-manifest-quarantine `
  --manifest data\manifests\core_legislation_manifest.json `
  --output-dir data\processed\stage3_quarantine
```

24 Ağustos 2026 ilk Aşama 3 geçişinde 8 kaynağın 6'sı 2.407 yapısal parçaya
ayrılmış, 2 kaynak OCR kuyruğuna alınmış ve hiçbir parçaya public aktif-RAG onayı
verilmemiştir. Seçili 6 karantina JSON'u ve 3 OCR metin girdisi bilinçli olarak
Git'te sürümlenmiştir. Normalde yeniden üretilebilir sayılan birleşik
`data/processed/competition_snapshot.json`, iki yapısal OCR JSON'u, kalıcı
Qdrant verisi, süreç kaydı ve örnek LaTeX çıktısı da teslim bütünlüğü için
24 Ağustos 2026 artifact commit'ine açıkça dahil edilmiştir. Geçici kilit ve
Python/test cache dosyaları dahil edilmez.

Ardından yarışma snapshot'ı için iki OCR adayı da ayrı ingestion sözleşmesiyle
işlendi. Bu işlem public aktif-RAG onayı vermedi; yalnızca açık uyarı taşıyan
`competition_snapshot` modunda 199 OCR parçasını 2.404 metin-katmanı parçasıyla
birleştirdi.

İki zayıf metin katmanlı PDF için Türkçe/İngilizce OCR aday metni ve sayfa
bazlı güven raporu üretmek için:

```powershell
python -X utf8 scripts\ocr_review.py `
  --document "official-writing-guide=mevzuat-kılavuz.pdf" `
  --document "official-writing-regulation=mevzuat-1.pdf" `
  --output-dir data\processed\ocr_review `
  --report reports\ocr_review.json `
  --model-dir runtime\easyocr-models `
  --force-ocr-all `
  --allow-model-download
```

Araç kaynak ve model SHA-256 değerlerini, sayfa yöntemini, karakter sayısını,
OCR güvenini ve süreyi raporlar. Çıktıyı her zaman
`ocr_candidate_human_verification_required` ve
`approved_for_active_rag=false` olarak işaretler; OCR çalıştırmak insan onayı
yerine geçmez. 24 Ağustos incelemesinin kaynak/güncellik paketi
`reports/MEVZUAT_KAYNAK_INCELEME_2026-08-24.md` altındadır. Sekiz kaydın dördü
kesin eski, biri kesik kopya, biri kanonik olmayan OCR adayıdır; bu nedenle
otomatik `verified_public` corpus hâlâ boş tutulmaktadır.

İnsan kapsam, yürürlük ve OCR doğrulamasından sonra tekil çıktılarla beraber tek
aktif corpus dosyası üretmek için:

```powershell
python -m karayol_agent.cli ingest-approved-manifest `
  --manifest data\manifests\core_legislation_reviewed.json `
  --output-dir data\processed\active_legislation `
  --corpus-output data\processed\active_legislation.json
```

Kaynakların güncel sürümle değiştirilmesi ve hukuk uzmanı onayı Aşama 3'ün
teknik kapanışını engellemeyen, fakat gerçek kamu corpusunu aktive etmeden önce
zorunlu olan içerik doğrulama işidir.

## Jina Embeddings v3 ve Qdrant indeksi

### Sabit yarışma snapshot'ını GPU ile üretme

Depodaki 8 belgeyi güncel mevzuat iddiası olmadan yarışma demosuna hazırlamak ve
kalıcı Qdrant indeksini NVIDIA GPU'da oluşturmak için:

```powershell
$env:PYTHONPATH="src"
python -m karayol_agent.cli build-competition-snapshot `
  --acknowledge-not-current

python -m karayol_agent.cli index-snapshot-vectors `
  --acknowledge-not-current `
  --local-files-only `
  --device cuda:0 `
  --batch-size 8
```

Varsayılan kalıcı dizin `runtime/qdrant-competition-snapshot`, ayrı koleksiyon
`competition_snapshot_chunks_v1` olur. Yaklaşık 32,8 MB'lık kalıcı SQLite
deposu bu teslimde Git'e artifact olarak eklenmiştir. İndeks kanıtı
`reports/competition_snapshot_index_2026-08-24.json`, yeniden açma/readiness
kanıtı `reports/competition_snapshot_readiness_2026-08-24.json`, tüm teslim
dosyalarının boyut/hash listesi ise
`reports/competition_snapshot_artifact_manifest_2026-08-24.json` dosyasındadır.

Uygulamayı aynı snapshot ve hibrit retrieval ile çalıştırmak için:

```powershell
$env:KARAYOL_RETRIEVAL_MODE="hybrid"
$env:KARAYOL_CORPUS_MODE="competition_snapshot"
$env:KARAYOL_COMPETITION_SNAPSHOT_PATH="data/processed/competition_snapshot.json"
$env:KARAYOL_QDRANT_PATH="runtime/qdrant-competition-snapshot"
$env:KARAYOL_QDRANT_COLLECTION="competition_snapshot_chunks_v1"
$env:KARAYOL_EMBEDDING_LOCAL_FILES_ONLY="true"
$env:KARAYOL_EMBEDDING_DEVICE="cuda:0"
python -m karayol_agent.cli process --file examples\yol_bakim_talebi.txt
```

24 Ağustos 2026 gerçek koşusunda NVIDIA GeForce RTX 3050 Laptop GPU kullanıldı;
2.603 parça 326 batch'te indekslendi. Dense sorgu, BM25 ve RRF'nin aynı snapshot
üzerinde birlikte çalıştığı uçtan uca doğrulandı. GPU olmayan ortamda yalnız
`--device cpu` seçimi değiştirilir.

### İnsan onaylı public mevzuat indeksi

Önce `.env.example` içindeki değişkenleri ortamınıza aktarın ve Qdrant'ı
çalıştırın. İnsan doğrulamasından geçmiş aktif corpusu sürümlü
`legal_chunks_v1` koleksiyonuna yazmak için:

```powershell
$env:QDRANT_URL="http://localhost:6333"
$env:PYTHONPATH="src"
python -m karayol_agent.cli index-vectors `
  --corpus data\processed\active_legislation.json `
  --collection legal_chunks_v1
```

İndeksleme sözleşmesi:

- model: `jinaai/jina-embeddings-v3`, 1024 boyut, cosine;
- belge görevi: `retrieval.passage`, sorgu görevi: `retrieval.query`;
- indeks metni: `context_text + "\n\n" + text`;
- kullanıcıya gösterilen kanıt: yalnız orijinal `text` ile belge/madde/sayfa izi;
- model ağırlığı ile ayrı `auto_map` remote-code deposu kendi doğrulanmış
  commit'lerine pinlenir;
- Jina remote-code uyumu için `transformers` 4.x ile sınırlandırılır;
- payload model/kod revizyonu ile indeks sürümünü taşır;
- aktif corpusun kanonik SHA-256 parmak izi ve her `chunk_id` için tam kanonik
  içerik SHA-256 değeri payload ile yerel sonuç doğrulamasına bağlanır; önceki,
  başka korpusa ait veya aynı kimlikle değiştirilmiş noktalar BM25 korpusuna
  karışamaz;
- kamu kaynağı yalnız onay, yürürlük, OCR/metin, SHA-256, sayfa, alan,
  madde/bağlam ve geçerli HTTP(S) kaynak URL kapılarının tamamını geçerse yazılır;
  ayrıca `schema_version=2.0` aktif-corpus zarfı, belge sayaçları,
  belge/chunk URL eşleşmesi ve `reviewed_by`/`reviewed_at` izi zorunludur. Kısmi
  batch yazımından önce tüm kayıtlar doğrulanır.

Hibrit çalışma zamanını etkinleştirmek için:

```powershell
$env:KARAYOL_RETRIEVAL_MODE="hybrid"
$env:QDRANT_URL="http://localhost:6333"
python -m karayol_agent.cli process --file examples\yol_bakim_talebi.txt
```

Her kanal varsayılan olarak 20 aday üretir; ham BM25 ve cosine skorları birbirine
eklenmez, sıralar `k=60` klasik Reciprocal Rank Fusion ile birleştirilir. Kanal
sıraları, ham skorlar, RRF katkıları ve fallback durumu süreç JSON'unda korunur.
RRF skoru yalnız sıralamadır: lexical kanıt yoksa dense-only kaynak, ham Jina
cosine skoru `KARAYOL_MIN_RETRIEVAL_SCORE` (varsayılan `0.20`) eşiğini geçmeden
doğrulanmış hukuki kanıt sayılmaz. `competition_snapshot` yolundaki incelenmiş
iki profilde hem `hybrid` hem `bm25` modunda ayrıca
`KARAYOL_MIN_RELEVANCE_SCORE` (varsayılan `0.75`) uygulanır. Sonuç JSON'unda
alaka profili, özgün-sorgu desteği, skor, kabul gerekçeleri,
incelenen/reddedilen aday sayısı ve abstention kararı ayrı alanlarda saklanır.
İncelenmemiş snapshot evrak türleri pass-through edilmez; fail-closed boş sonuç
üretir.
Mevcut çekirdek kamu kaynaklarının insan onayı henüz sıfır olduğu için bu depo
aktif public koleksiyonu kendiliğinden doldurmaz. Varsayılan `bm25` modu sentetik
demo akışını çevrimdışı tutar; açıkça seçilen `competition_snapshot` + `hybrid`
modu ise yukarıdaki ayrı kalıcı GPU indeksini kullanır.

**Lisans notu:** Jina Embeddings v3, ayrı remote-code uygulaması ve Jina
Reranker v2 `CC BY-NC 4.0`; EasyOCR 1.7.2 kodu `Apache-2.0` kapsamındadır.
EasyOCR CRAFT ve Latin G2 ağırlıkları için ayrı lisans beyanı doğrulanamadığı
için bunlar depoda dağıtılmaz. Yarışma/demodan ticari ürüne geçmeden önce model
lisans uygunluğu ayrıca değerlendirilmelidir. Sabit revizyon ve hash kayıtları
`resources/manifests/sources.json` içindedir.

### Sentetik retrieval karşılaştırması ve reranker kararı

Dondurulmuş sentetik sette gerçek yerel Jina modeli ve Qdrant istemcisiyle
BM25/hibrit karşılaştırmasını tekrarlamak için:

```powershell
python -m karayol_agent.cli benchmark-retrieval `
  --local-files-only `
  --summary-output reports\evaluation_retrieval_comparison.json
```

24 Ağustos 2026 CPU ölçümünde BM25 Recall@5 `0,8056`, MRR `0,8056`; Jina v3 +
Qdrant + BM25 + RRF Recall@5 `1,0000`, MRR `0,9097` verdi. Parafraz diliminde
Recall@5 `0,1250` değerinden `1,0000` değerine çıktı. Bunlar yalnız 48 sentetik
kayıt üzerindeki benchmark sonuçlarıdır; kamu mevzuatı veya saha başarımı
değildir.

Şema `1.2` benchmark'ı her iki dense geçişte de `48/48` başarı ve `0` fallback
doğrulamıştır. Tek bir dense hata, boş sonuç veya fallback halinde BM25 sonucu
hibrit etiketiyle yazılmaz ve tüm benchmark raporları fail-closed durur.

`--with-reranker` ile ölçülen `jina-reranker-v2-base-multilingual` Recall@5'i
`0,9722`, MRR'ı `0,8806` değerine düşürdü ve CPU'da skor çağrısı başına ortalama
yaklaşık `3,7 sn` ekledi. Entegrasyon ablation için korunur, fakat varsayılan
akışta kapalıdır. Ayrıntı `reports/RETRIEVAL_ABLATION_2026-08-24.md`
dosyasındadır.

### Snapshot sorgu alakası ölçümü

İki ana sorgu, iki olumlu paraphrase ve dört no-answer/near-miss kaydından oluşan
sekiz mühendislik fixture'ı korpus fingerprint'ine bağlı setle ayrıca ölçülür:

```powershell
python -X utf8 scripts\evaluate_snapshot_relevance.py `
  --variant intent-profile-gate-v2 `
  --output reports\snapshot_relevance_candidate_v2_2026-08-24.json
```

Eski hibrit RRF ilk 5'i ilk iki ana fixture'da yol bakımında `0/5`, hasarlı
levhada `2/5` strict ilgili metinsel aday döndürüyordu. V2 canlı turunda dört
cevaplanabilir fixture'ın her biri `5/5`; `Precision@5`, `Recall@5`, `nDCG@5`
ve hüküm ailesi recall'ü `%100`, hard-negative sayısı `0` oldu. Dört no-answer
fixture'ın tamamında sistem abstain etti; yanlış cevap ve yanlış abstention `0`.
Bu set kurallar geliştirilirken kullanılmış küçük bir regresyondur; bağımsız
test, hukuk doğruluğu veya genel saha başarımı değildir. Baseline ve raporlar
[`snapshot_relevance_baseline_2026-08-24.json`](reports/snapshot_relevance_baseline_2026-08-24.json)
ile tarihsel v1
[`snapshot_relevance_candidate_2026-08-24.json`](reports/snapshot_relevance_candidate_2026-08-24.json)
ve güncel v2
[`snapshot_relevance_candidate_v2_2026-08-24.json`](reports/snapshot_relevance_candidate_v2_2026-08-24.json)
dosyalarındadır.

### Küçük sentetik kanıt grafı

Ölçümden sonra eklenen denetlenebilir grafı üretmek için:

```powershell
python -m karayol_agent.cli build-synthetic-graph `
  --output reports\synthetic_evidence_graph.json
```

Graf; sentetik kural, evrak türü, birim, şablon ve zorunlu alan düğümlerini
`APPLIES_TO`, `ASSIGNED_TO`, `SUPPORTS_TEMPLATE` ve `REQUIRES_FIELD`
ilişkileriyle bağlar. Her ilişki gold kayıt kimliklerini kanıt izi olarak taşır.
Builder sentetik olarak işaretlenmemiş girdiyi reddeder; çıktı
`benchmark_only=true` ve `production_legal_evidence=false` olarak sabittir.
Graf ayrıca üç giriş dosyasının proje-göreli yolunu ve SHA-256 değerini taşır;
özet düğüm/kenar sayaçları dosya okunurken yeniden hesaplanır.

## API

```powershell
$env:PYTHONPATH="src"
uvicorn karayol_agent.api:app --reload
```

- `GET /health`
- `GET /ready`
- `POST /v1/process/text`
- `POST /v1/process/file`
- `GET /v1/process/{evrak_id}`
- `POST /v1/process/{evrak_id}/information`
- `POST /v1/process/{evrak_id}/approve`
- `GET /v1/process/{evrak_id}/artifacts/tex`
- `GET /v1/process/{evrak_id}/artifacts/pdf`

Swagger arayüzü: `http://127.0.0.1:8000/docs`

## Manuel test arayüzü

Yerel web arayüzünü örnek senaryolarla çalıştırmak için:

```powershell
$env:PYTHONPATH="src"
$env:KARAYOL_RETRIEVAL_MODE="hybrid"
$env:KARAYOL_CORPUS_MODE="competition_snapshot"
$env:KARAYOL_COMPETITION_SNAPSHOT_PATH="data/processed/competition_snapshot.json"
$env:KARAYOL_QDRANT_PATH="runtime/qdrant-competition-snapshot"
$env:KARAYOL_QDRANT_COLLECTION="competition_snapshot_chunks_v1"
$env:KARAYOL_EMBEDDING_LOCAL_FILES_ONLY="true"
$env:KARAYOL_EMBEDDING_DEVICE="cuda:0"
Remove-Item Env:QDRANT_URL -ErrorAction SilentlyContinue
python -m uvicorn karayol_agent.api:app --host 127.0.0.1 --port 8010
```

Tarayıcıdan `http://127.0.0.1:8010` adresini açın. Arayüz; hazır evrak
senaryolarını, TXT/MD/PDF yüklemeyi, sınıflandırma ve yönlendirme sonucunu,
kaynak sözleşmesi ve güncellik/hukuki-dayanak açıklamalarını, eksik bilgi
tamamlama adımını, insan onayını ve LaTeX çıktı indirmeyi tek ekranda sunar.
Önce `/ready` yanıtında 2.603/2.603 vektörün uyumlu olduğunu doğrulayın. Adım
adım kabul testi için [`MANUEL_TEST_SENARYOSU.md`](MANUEL_TEST_SENARYOSU.md),
otomatik canlı tur için şu komutu kullanın:

```powershell
python -X utf8 scripts\run_production_demo_acceptance.py
```

24 Ağustos kabul sonucu, olumlu alaka ve near-miss abstention kapılarıyla
**23/23** zorunlu kontrol geçti:
[`PRODUCTION_DEMO_ACCEPTANCE_2026-08-24.md`](reports/PRODUCTION_DEMO_ACCEPTANCE_2026-08-24.md).

## Test

```powershell
$env:PYTHONPATH="src"
pytest
```

## Sayısal gold-set değerlendirmesi

48 kurgusal evraktan oluşan sabit veri setinde sınıflandırma, yönlendirme,
eksik alan, şablon seçimi ve mevzuat retrieval ölçümü yapmak için:

```powershell
$env:PYTHONPATH="src"
python -m karayol_agent.cli evaluate
```

Rapor `reports/evaluation_baseline.json` dosyasına yazılır. Veri setindeki 40
standart örnek ile doğrudan anahtar kelime kullanmayan 8 paraphrase challenge
örneği ayrı dilimler hâlinde raporlanır. Mevcut kural tabanlı başlangıç sürümü
standart dilimde başarılıdır; challenge dilimindeki düşük sonuçlar embedding,
reranker ve LLM entegrasyonunun ölçülebilir geliştirme hedefidir. Bu sonuçlar
gerçek saha başarımı olarak yorumlanmamalıdır. Yeni rapor şeması retrieval
modunu, fallback teşhisini ve her sonuç için kanal/sıra/ham skor/RRF katkısını
saklar. Gerçek Jina/Qdrant sentetik benchmark raporu ayrıca üretilmiştir;
onaysız kamu korpusu bu ölçüme veya aktif indekse karıştırılmamıştır.

## Güvenlik ve veri sınırı

- Model/kural motoru kaynakta bulunmayan kritik alanları uydurmaz.
- Eksik alanlar `kullanici_girdisi_gerekli` olarak işaretlenir.
- LaTeX özel karakterleri kaçış işleminden geçirilir.
- Şablonlar çalışma sırasında değiştirilemez.
- Shell escape kullanılmaz; derleme zaman aşımıyla sınırlandırılır.
- Gerçek vatandaş evrakı veya kapalı kamu verisi demo veri setine eklenmez.
