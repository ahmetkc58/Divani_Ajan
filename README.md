# Karayolu Evrak Akıllı Ajan Sistemi

Bu depo, `PROJE_PLANI.md` içindeki TEKNOFEST 2026 projesinin çalışan MVP
uygulamasıdır. Sistem sentetik karayolu evraklarını uçtan uca işler:

1. metin/PDF alımı ve OCR fallback,
2. evrak sınıflandırma ve önemli alan çıkarımı,
3. eksik bilgi tespiti,
4. bağlamsal BM25 veya Jina Embeddings v3 + Qdrant + RRF hibrit arama,
5. kaynak doğrulama,
6. resmî yazı türü ve LaTeX şablonu seçimi,
7. sentetik birime yönlendirme,
8. güvenli LaTeX taslağı oluşturma,
9. uygunluk kontrolü ve süreç bilgilendirmesi.

Çevrimdışı demo akışı varsayılan olarak kural tabanlı BM25 ile çalışır. İsteğe
bağlı RAG katmanı aynı sorguyu Jina Embeddings v3 (`retrieval.query`) ve
contextual BM25 kanallarına gönderir, Qdrant dense sonuçlarını klasik RRF ile
birleştirir ve dense kanal kullanılamazsa bunu süreç teşhisinde açıkça belirterek
BM25'e döner. Demo verileri sentetiktir; `veri_kaynaklari/` altındaki gerçek ve
herkese açık kayıtlar insan onayı olmadan çalışma zamanında kullanılmaz.

## Geçici uygulama kararı — mevcut mevzuat snapshot'ı

Bu geliştirme turunda yeni/güncel mevzuat kopyalarını edinme, proje planını
snapshot politikası için yeniden yazma ve mevcut aktivasyon kurallarını yeniden
tasarlama adımları **atlanmıştır**. Çalışma, depoda bulunan kaynakların güncel
hukuk metni olduğu iddia edilmeden mevcut proje snapshot'ı üzerinden devam
edecektir.

Sıradaki teknik hedef, metin katmanı hazır olan 6 belgeden daha önce üretilen
2.407 yapısal parçaya mevcut iki OCR adayını sayfa izini koruyarak yapısal
chunk'lar halinde eklemek ve 8 belgelik birleşik snapshot'ı kalıcı Jina
Embeddings v3 + Qdrant indeksine almaktır. Kaynak başlığı, madde/fıkra/bent,
sayfa, URL ve SHA-256 izi korunacak; kullanıcıya sunulan atıflar bu sabit
snapshot'a ait olduğunu açıkça belirtecektir.

Bu karar mevcut fail-closed kodu kendiliğinden değiştirmez: karantina parçaları
halen `approved_for_active_rag=false` taşır ve normal `index-vectors` akışı
onaysız corpus'u reddeder. Dolayısıyla bu not, hukuki güncellik veya uzman onayı
iddiası değil, sonraki uygulama işinin kapsam ve öncelik kaydıdır.

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

Bu aşamada üretilen JSON dosyaları embedding değildir; Jina/Qdrant aşamasının
girdisidir. İnsan incelemesi tamamlanmayan parçalar karantinada tutulur ve
`approved_for_active_rag=false` olarak kalır.

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

24 Ağustos 2026 kapanış çalışmasında 8 kaynağın 6'sı 2.407 yapısal parçaya
ayrılmış, 2 kaynak OCR kuyruğuna alınmış ve hiçbir parçaya aktif-RAG onayı
verilmemiştir. `data/processed/` tekrar üretilebilir çalışma çıktısı olduğu için
Git'e eklenmez; kalıcı inceleme girdileri
`core_legislation_manifest.json` ve `core_legislation_manifest_review.csv`
dosyalarıdır.

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
otomatik aktif corpus hâlâ boş tutulmaktadır.

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
doğrulanmış hukuki kanıt sayılmaz. Düşük skor açık abstention üretir.
Mevcut çekirdek kamu kaynaklarının insan onayı henüz sıfır olduğu için bu depo
aktif public koleksiyonu kendiliğinden doldurmaz. Varsayılan `bm25` modu sentetik
demo akışını çevrimdışı tutar.

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
uvicorn karayol_agent.api:app --host 127.0.0.1 --port 8010
```

Tarayıcıdan `http://127.0.0.1:8010` adresini açın. Arayüz; hazır evrak
senaryolarını, TXT/MD/PDF yüklemeyi, sınıflandırma ve yönlendirme sonucunu,
doğrulanmış kaynakları, eksik bilgi tamamlama adımını, insan onayını ve LaTeX
çıktı indirmeyi tek ekranda sunar. Adım adım kabul testi için
[`MANUEL_TEST_SENARYOSU.md`](MANUEL_TEST_SENARYOSU.md) belgesini kullanın.

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
