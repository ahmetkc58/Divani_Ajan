# Divani Ajan — Yapılan Çalışmalar ve Kapanış Durumu

**Tarih:** 24 Ağustos 2026

**Geçerli Git deposu:** bu dosyanın bulunduğu proje kökü

**Son snapshot/GPU turu başlangıç commit'i:** `3b82e13`

**Commit durumu:** Son snapshot/GPU değişiklikleri henüz commit edilmedi; kullanıcı
incelemesi için çalışma ağacındadır.

Bu belge, ilk depo/commit incelemesinden sonra önerilen adımların uygulanmış son
özetidir. Ürün kullanımı için [`README.md`](README.md), mimari plan için
[`PROJE_PLANI.md`](PROJE_PLANI.md), ayrıntılı depo denetimi için
[`DEPO_INCELEME_RAPORU_2026-08-24.md`](DEPO_INCELEME_RAPORU_2026-08-24.md)
kullanılmalıdır.

## 1. Sonuç

Teknik olarak tamamlanan adımlar:

1. Metin katmanı yetersiz iki PDF için Türkçe OCR adayları ve kalite raporları.
2. Sekiz çekirdek kaynağın resmî kopya, kimlik, güncellik ve kapsam incelemesi.
3. Pinli Jina Embeddings v3 tarihsel CPU smoke testi ve sentetik yerel Qdrant
   indeksi.
4. Aynı dondurulmuş gold sette BM25 ile gerçek Jina/Qdrant hibrit ölçümü.
5. Ölçüm sonrası çok dilli reranker ablation'ı ve ölçüme dayalı kapatma kararı.
6. Yalnız sentetik veriden, gold kayıt kanıt izli küçük mevzuat-birim-şablon
   grafı.
7. CLI, yapılandırma, fail-closed kontroller, raporlar, dokümantasyon ve tam test
   paketi.
8. Altı metin-katmanı çıktısı ile iki OCR adayını birleştiren, public corpus'tan
   tamamen ayrı `competition_snapshot` sözleşmesi ve 8 belgeli/2.603 parçalı
   corpus.
9. RTX 3050 üzerinde Jina Embeddings v3 ile üretilmiş 2.603 adet 1024D vektör ve
   kalıcı gömülü Qdrant `competition_snapshot_chunks_v1` koleksiyonu.
10. Snapshot kaynaklarını güncel/yürürlükte hukuk kaynağı gibi göstermeyen API,
    atıf, taslak ve uygunluk uyarıları; public fail-closed yoluyla koleksiyon
    ayrımı.
11. Varsayılan olarak anahtarsız yerel Ollama + `qwen2.5:0.5b` kullanan, strict
    JSON Schema doğrulamalı ve hata/timeout/bozuk yanıtta deterministik kurallara
    dönen LLM sağlayıcı katmanı. Gemini/Groq adaptörleri isteğe bağlı korunur.
12. Researcher → Auditor → sentetik multi-hop graph → Adjudicator zinciri;
    şablon, birim ve kaynak kararlarında allowlist, SHA-256 provenance ve insan
    onayı kapıları.
13. Gürültülü OCR etiketleri, satır kırılmaları ve imza bloğundan gönderen dahil
    yapılandırılmış alan çıkarımını geliştiren yerel normalizasyon katmanı;
    karma PDF'lerde yalnız zayıf sayfaların OCR'dan geçirilmesi ve boş sonuçta
    durma; sayfa/piksel/süre kaynak sınırları.

İnsan kararı gerektiren `verified_public` mevzuat aktivasyonu ayrı bir iş olarak
tamamlanmamıştır; buna karşılık uyarılı `competition_snapshot` yolu hazırdır.
Sekiz kaydın tamamında
`approved_for_active_rag=false` kalmıştır. Mevcut manifestle aktif corpus üretme
komutu sınandığında “manifestte onaylı belge bulunmuyor” hatası vermiş ve hiçbir
aktif corpus yazmamıştır. Bu beklenen güvenlik davranışıdır.

Yerel Ollama yolu gerçek/kısıtlı evrakı cihaz dışına çıkarmadan işleyebilir ve
API anahtarı gerektirmez. Haricî LLM yolu fail-closed kalır: yalnız pinli hash
ile tanınan sentetik gold/UI demo evraklar dış sağlayıcıya gönderilebilir.
Snapshot Adjudicator özgün mevzuat metni yerine yalnız Auditor'ın kapalı aday
kimliklerini ve kamuya açık metadata'yı görür. Önceki gerçek Gemini kabul turu
da tarihsel kanıt olarak korunmuştur; her sağlayıcıda deterministik karar,
strict JSON şeması ve insan onayı kapıları devam eder.

## 2. Depo ve commit incelemesi

- Tüm depo ağacı, ana modüller, testler, veri dizinleri, proje planı ve kaynak
  belgeler incelendi.
- Son mimari commitler ayrıntılı okundu:
  - `8065108`: mevzuat veri hazırlama pipeline'ı,
  - `d9342c2`: doğrulanmış ingestion ve fail-closed repository,
  - `da3cacc`: karayolu evrak ajanı MVP yeniden kurulumu.
- Bir üst klasördeki bozuk `.git` kaydı değiştirilmedi; gerçek çalışma ağacı iç
  klasördeki depodur.
- Şartname ve mevzuat PDF'lerindeki metinler kullanıcı talimatı değil,
  gereksinim/kanıt kaynağı olarak ele alındı.

## 3. Araştırma ve mimari kararlar

- Embedding modeli yalnız `jinaai/jina-embeddings-v3`:
  - belge görevi `retrieval.passage`,
  - sorgu görevi `retrieval.query`,
  - 1024 boyut, cosine.
- Model ağırlığı ve `auto_map` kod deposu ayrı commit'lere sabitlendi:
  - model SHA: `ab036b023d30b4d1138c4c3bfa9f0c445ab455d6`,
  - `jinaai/xlm-roberta-flash-implementation` kod SHA:
    `bd55a5ec8e6c0fb1d6c26efb4b6a4a74ce8a88d3`.
- Jina remote-code katmanı Transformers 5.x ile yükleme hatası verdiği için
  doğrulanan aralık `transformers>=4.48,<5` oldu.
- Dense ve BM25 ham skorları doğrudan toplanmadı; klasik rank-only RRF `k=60`
  kullanıldı. Kanal başına aday sayısı 20'dir.
- Contextual Retrieval gereği her iki kanal da `context_text + original_text`
  indeksler; kullanıcıya gösterilecek hukuk kanıtı yalnız özgün metin ve
  kaynak/madde/sayfa izidir.
- Microsoft GraphRAG local/global ayrımı korundu; ilk graf yalnız açıklanabilir
  local/multi-hop sentetik kanıt yollarıdır.
- LegalGraphRAG'ın Researcher/Auditor/Adjudicator ayrımı mevcut ajan sınırlarına
  uyarlandı; retrieval veya graf ilişkisi tek başına doğrulanmış hukuk kanıtı
  sayılmaz.
- Kullanıcının verdiği `arXiv:2605.19806` LegalGraphRAG değildir; doğru
  LegalGraphRAG kaydı `arXiv:2605.28120`'dir. `arXiv:2601.05265` içindeki CDTA
  yaklaşımı birincil hukuk kanıtı değil, ilerideki Tier-2 konu haritası deneyi
  olarak tutuldu.

## 4. Eklenen retrieval bileşenleri

- `retrieval/embeddings.py`: lazy, pinli Jina yükleme; passage/query ayrımı;
  boyut, sonlu değer ve L2 normalizasyon kontrolü. Remote-code içindeki
  tokenizer çağrıları da aynı model commit'ine ve local-only moduna zorlanır.
- `retrieval/qdrant_store.py`: cosine/1024 koleksiyon şeması, kararlı UUIDv5,
  payload indeksleri, model/kod/index metadata doğrulaması, corpus parmak izi,
  izinli chunk kimliği sınırı, ID başına kanonik içerik SHA-256 doğrulaması,
  güvenli upsert ve filtreli arama.
- `retrieval/hybrid.py`: BM25 + dense adayları, chunk kimliğiyle dedup,
  deterministik RRF, kanal katkıları ve açık fallback teşhisi.
- `retrieval/runtime.py`: analysis-aware sorgu, domain sınırı ve yapılandırma
  bağlama.
- `retrieval/relevance.py`: yol yüzeyi bakımı ve hasarlı trafik işareti için
  madde/chunk allowlist'i içermeyen özgün-girdi niyet denetimi, sorgu genişletme,
  concept-group rerank, `0.75` görünür metin kapısı ve fail-closed abstention.
  Expansion eşleşmeleri özgün kullanıcı lexical kanıtından ayrılır; aynı kapı
  snapshot'ın hibrit ve BM25 yollarında uygulanır.
- `retrieval/vector_indexing.py`: contextual batch embedding ve model/Qdrant
  çağrısından önce tüm corpus için fail-closed doğrulama; kanonik corpus
  SHA-256 kimliğini indeks ve rapora bağlama.
- `retrieval/contracts.py`: `verified_public`, sentetik benchmark ve
  `competition_snapshot` güven sınırlarını birbirinden ayıran sabit sözleşmeler.
- `ingestion/ocr_candidate.py` ve `ingestion/snapshot.py`: OCR adaylarını sayfa
  izli yapısal parçalara dönüştürme, kaynak/artifact hash kontrolü, güvenli yol
  doğrulaması ve 8 belgeli snapshot zarfı.
- `evaluation/hybrid_benchmark.py`: yalnız `benchmark_` koleksiyonu ve açıkça
  sentetik status/source kabul eden gerçek yerel Jina/Qdrant benchmark adapter'ı.
- `retrieval/reranker.py`: pinli çok dilli Jina reranker sağlayıcısı ve RRF aday
  yeniden sıralama katmanı. Ölçüm olumsuz olduğu için varsayılan değildir.
- `graph/evidence_graph.py`: küçük sentetik kanıt grafı, içerik-hash'li giriş
  provenance'ı, yeniden hesaplanan sayaç bütünlüğü ve iki-hop kural izi.
- CLI komutları: `index-vectors`, `build-competition-snapshot`,
  `index-snapshot-vectors`, `benchmark-retrieval`, `build-synthetic-graph`.

Kamu mevzuatı; insan onayı, yürürlük, OCR/metin, SHA-256, sayfa, domain,
madde/bağlam ve geçerli kaynak URL kapılarının yanı sıra aktif-corpus zarfı,
belge sayaçları, belge/chunk URL eşleşmesi ve
`reviewed_by`/`reviewed_at` izi geçmeden repository, Qdrant upsert veya Qdrant
sonuç okuma aşamalarında kabul edilmez. Qdrant sorgusu yalnız aynı kanonik corpus
parmak izini, izinli chunk kümesini ve her kimliğe bağlı tam içerik hash'ini kabul
eder. Dense kanal kullanılamazsa hata gizlenmez;
teşhise yazılıp BM25 fallback uygulanır. Public Qdrant sonucu sentetik BM25
korpusuyla karıştırılmaz.

Snapshot yolu ayrıca `approved_for_active_rag=false`,
`currentness_verified=false`, `legal_reliance_allowed=false` ve sabit kullanım
uyarısını zorunlu tutar. Public ve snapshot koleksiyon adları birbirinin yerine
kullanılamaz. Qdrant hem URL hem kalıcı gömülü dizin hedefini destekler; bu iki
hedef aynı anda yapılandırılamaz.

## 5. Jina/Qdrant ve retrieval ölçümü

Tarihsel sentetik CPU smoke sonucu:

- Jina passage/query çıktıları 1024D ve L2 normları `1,0`.
- Aynı metnin passage/query vektörleri görev gereği farklı.
- Eşleşen örnek cosine skorları `0,550065` ve `0,609037`; çapraz örnekler
  `-0,059888` ve `0,116792`.
- İlk model yükleme + iki passage: `4,757547 sn`; sıcak iki query:
  `0,799754 sn`.
- Yedi sentetik chunk yerel bellek içi Qdrant'a yazıldı; beklenen
  `SENT-KRY-001` RRF sonucunda birinci geldi.

Güncel 8-belgeli GPU snapshot sonucu:

- 2.606 kaynak satırından 3 tam tekrar konsolide edilerek 2.603 benzersiz parça
  üretildi; OCR katkısı 29 kılavuz + 170 yönetmelik parçasıdır.
- RTX 3050 `cuda:0`, batch 8 ile 326 batch'te 2.603 adet 1024D Jina passage
  vektörü kalıcı gömülü Qdrant'a yazıldı.
- Disk koleksiyonu kapatılıp yeniden açıldı; expected/total/compatible sayaçları
  2.603/2.603/2.603 ve exact corpus fingerprint eşleşmesi verdi.
- Üç ayrı domain dense sorgusu geçti; hibrit kontrolde dense kanal kullanıldı,
  fallback olmadı ve 5 snapshot referansı zorunlu uyarıyla kabul edildi.

48 sentetik kayıt, retrieval gold'u bulunan 36 örnek:

| Yöntem | Recall@5 | MRR | Parafraz Recall@5 |
|---|---:|---:|---:|
| BM25 | 0,8056 (29/36) | 0,8056 | 0,1250 (1/8) |
| Jina v3 + Qdrant + BM25 + RRF | **1,0000 (36/36)** | **0,9097** | **1,0000 (8/8)** |
| Hibrit + Jina reranker v2 | 0,9722 (35/36) | 0,8806 | 0,8750 (7/8) |

Hibrit yol BM25'e göre Recall@5'i `+0,1944`, MRR'ı `+0,1041` artırdı.
Reranker hibrite göre Recall@5'i `-0,0278`, MRR'ı `-0,0291` düşürdü; ayrıca
48 CPU skor çağrısında ortalama `3.724,107 ms/çağrı` sürdü. `HASAR-08` için
beklenen `SENT-KRY-003` parçasını ilk beş dışına itti. Bu nedenle reranker kodu
ablation için korunmuş, varsayılan akışta kapatılmıştır.

Bu metriklerin tamamı sentetik benchmark'tır; kamu mevzuatı veya gerçek saha
başarımı iddiası değildir.

Şema `1.2` koşusunda ana ve reranked dense geçişleri ayrı ayrı `48/48` başarılı,
`0` hata ve `0` fallback verdi. Herhangi bir fallback varsa benchmark artık
hiçbir rapor yazmaz. RRF sırası hukuki kanıt kabulü sayılmaz; dense-only kaynak
ham cosine `>= 0,20` eşiğini geçmezse ajan açıkça abstain eder. Değerlendirme
şemasına `challenge_no_answer` abstention dilimi eklendi.

## 6. Küçük sentetik kanıt grafı

Graf düğümleri:

- 7 `MevzuatKurali`,
- 7 `EvrakTuru`,
- 5 `Birim`,
- 4 `YaziSablonu`,
- 4 `ZorunluAlan`.

İlişkiler:

- 7 `APPLIES_TO`,
- 4 `ASSIGNED_TO`,
- 25 `SUPPORTS_TEMPLATE`,
- 16 `REQUIRES_FIELD`.

Her kenar dayandığı sentetik gold `record_id` listesini taşır. Örneğin
`rule:SENT-KRY-003`, iki-hop izinde `unit:ORKGM-AF-001` ve ilgili şablonlara
ulaşır; `HASAR-08` kanıt kaydı görünür. Builder sentetik işareti olmayan gold,
mevzuat veya birim girdisini reddeder. Çıktı sabit olarak
`benchmark_only=true`, `production_legal_evidence=false` değerlerini taşır.
Üç kaynak JSON'un proje-göreli yolu ve SHA-256 değeri grafın `inputs` alanında
saklanır; `node_counts` ve `edge_counts` okunurken yeniden hesaplanır.

## 7. OCR sonucu

EasyOCR `1.7.2`, Türkçe + İngilizce, 150 DPI ve CPU ile:

| Belge | Sayfa | Karakter | Ortalama OCR güveni | Boş sayfa |
|---|---:|---:|---:|---:|
| Resmî Yazışma Kılavuzu | 26/26 | 29.073 | 0,8062 | 0 |
| Resmî Yazışma Yönetmeliği + örnekler | 49/49 | 67.183 | 0,8361 | 0 |

İlk karma geçişte yerel metin katmanından alınan sekiz sayfanın görsel
karşılaştırmada eksik olduğu görüldü. Örneğin yönetmelik sayfa 11, yerel metinde
370 karakterken tam OCR'da 2.718 karakter verdi. Bu nedenle yönetmeliğin 49
sayfası tamamen yeniden OCR edildi.

OCR adayları public aktif corpus değildir. Birleşik kelime, Türkçe karakter,
satır sırası ve URL hataları gözlendiği için insan sayfa doğrulaması hâlâ
zorunludur. Bununla birlikte yarışma demosu için ayrı ve açıkça güncel-olmayan
`competition_snapshot` yoluna 199 yapısal OCR parçası olarak alınmıştır. Ayrıca
yerel kılavuz resmî 102 sayfalık aynanın yalnız 26 sayfalık kesik kopyasıdır;
ileride public corpus hazırlanırsa tam resmî baskıyla OCR tekrarlanmalıdır.

## 8. Resmî kaynak/güncellik incelemesi

- 8/8 yerel PDF, manifest SHA-256/byte/sayfa değerleriyle eşleşti.
- URL'si bulunan altı UAB PDF'sinin 24.08.2026 indirmesi yerel dosyayla birebir
  byte/SHA eşleşti.
- Buna rağmen dört kaynak kesin eskidir:
  - 2918 sayılı Kanun,
  - 4925 sayılı Kanun,
  - Karayolları Trafik Yönetmeliği,
  - Karayolu Taşıma Yönetmeliği.
- Resmî Yazışma Kılavuzu yerel 26 sayfa, resmî kamu aynası 102 sayfadır.
- Resmî Yazışma Yönetmeliği yerel kopyası kanonik kaynak URL/hash zincirine
  bağlı değildir.
- Trampa ve Karayolu Altyapısı Güvenlik yönetmelikleri karar anında yeniden
  yürürlük/yayım kontrolü gerektirir.
- Otomatik aktif-RAG önerisi: `0/8`; manifestte onay değişikliği: `0`.

İnsan hukuk/kapsam uzmanı için Markdown, JSON ve CSV inceleme paketi üretildi.
CSV; blocker, kapsam, çıkarım notu/güveni, kaynak kanıtı ve önerilen uzman
aksiyonlarını taşır.

## 9. Önemli raporlar

- [`MEVZUAT_KAYNAK_INCELEME_2026-08-24.md`](reports/MEVZUAT_KAYNAK_INCELEME_2026-08-24.md)
- [`OCR_INCELEME_2026-08-24.md`](reports/OCR_INCELEME_2026-08-24.md)
- [`RETRIEVAL_ABLATION_2026-08-24.md`](reports/RETRIEVAL_ABLATION_2026-08-24.md)
- [`evaluation_retrieval_comparison_2026-08-24.json`](reports/evaluation_retrieval_comparison_2026-08-24.json)
- [`jina_qdrant_smoke_2026-08-24.json`](reports/jina_qdrant_smoke_2026-08-24.json)
- [`competition_snapshot_index_2026-08-24.json`](reports/competition_snapshot_index_2026-08-24.json)
- [`competition_snapshot_readiness_2026-08-24.json`](reports/competition_snapshot_readiness_2026-08-24.json)
- [`competition_snapshot_artifact_manifest_2026-08-24.json`](reports/competition_snapshot_artifact_manifest_2026-08-24.json)
- [`synthetic_evidence_graph_2026-08-24.json`](reports/synthetic_evidence_graph_2026-08-24.json)
- [`PRODUCTION_DEMO_ACCEPTANCE_2026-08-24.md`](reports/PRODUCTION_DEMO_ACCEPTANCE_2026-08-24.md)
- [`production_demo_acceptance_2026-08-24.json`](reports/production_demo_acceptance_2026-08-24.json)
- [`SNAPSHOT_RELEVANCE_EVALUATION_2026-08-24.md`](reports/SNAPSHOT_RELEVANCE_EVALUATION_2026-08-24.md)
- [`snapshot_relevance_baseline_2026-08-24.json`](reports/snapshot_relevance_baseline_2026-08-24.json)
- [`snapshot_relevance_candidate_2026-08-24.json`](reports/snapshot_relevance_candidate_2026-08-24.json)
- [`snapshot_relevance_candidate_v2_2026-08-24.json`](reports/snapshot_relevance_candidate_v2_2026-08-24.json)
- [`production_demo_acceptance_live_v2_2026-08-24.json`](reports/production_demo_acceptance_live_v2_2026-08-24.json)

OCR aday metinleri `data/processed/ocr_review/`, yapısal OCR parçaları
`data/processed/stage3_quarantine/` ve birleşik corpus
`data/processed/competition_snapshot.json` altındadır. Seçili 6 karantina JSON'u
ile 3 OCR metin girdisine ek olarak, kullanıcı talebiyle türetilmiş birleşik
snapshot, iki yapısal OCR JSON'u, kalıcı Qdrant SQLite deposu, süreç kaydı ve
örnek LaTeX çıktısı da artifact commit'ine alınmıştır. Dosyaların boyut ve
SHA-256 değerleri artifact manifestinde kayıtlıdır. Yalnız `.lock`, Python cache
ve test cache gibi taşınabilir olmayan geçici çalışma artıkları dışarıda kalır.

## 10. Kurulum ve komutlar

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,rag,ocr]"
Copy-Item .env.example .env
```

Sentetik benchmark ve graf:

```powershell
python -m karayol_agent.cli benchmark-retrieval --local-files-only
python -m karayol_agent.cli build-synthetic-graph
```

OCR:

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

Gerçek kamu indeksi yalnız insan onaylı corpus hazırlandıktan sonra:

```powershell
python -m karayol_agent.cli index-vectors `
  --corpus data\processed\active_legislation.json `
  --qdrant-url http://localhost:6333 `
  --collection legal_chunks_v1
```

Mevcut 8 belgeli yarışma snapshot'ını üretmek ve GPU'da kalıcı indekslemek:

```powershell
$env:PYTHONPATH="src"
python -m karayol_agent.cli build-competition-snapshot `
  --acknowledge-not-current

python -m karayol_agent.cli index-snapshot-vectors `
  --acknowledge-not-current `
  --local-files-only `
  --qdrant-path runtime\qdrant-competition-snapshot `
  --collection competition_snapshot_chunks_v1 `
  --device cuda:0 `
  --batch-size 8
```

`QDRANT_URL` ile `KARAYOL_QDRANT_PATH` aynı anda verilmez.

Kalıcı snapshot ile arayüzü açmak:

```powershell
$env:PYTHONPATH="src"
$env:KARAYOL_RETRIEVAL_MODE="hybrid"
$env:KARAYOL_CORPUS_MODE="competition_snapshot"
$env:KARAYOL_COMPETITION_SNAPSHOT_PATH="data/processed/competition_snapshot.json"
$env:KARAYOL_QDRANT_PATH="runtime/qdrant-competition-snapshot"
$env:KARAYOL_QDRANT_COLLECTION="competition_snapshot_chunks_v1"
$env:KARAYOL_EMBEDDING_LOCAL_FILES_ONLY="true"
$env:KARAYOL_EMBEDDING_DEVICE="cpu"
Remove-Item Env:QDRANT_URL -ErrorAction SilentlyContinue
python -m uvicorn karayol_agent.api:app --host 127.0.0.1 --port 8010
```

Bu çalışma ortamındaki PyTorch CPU derlemesidir; `cuda:0` yalnız
`torch.cuda.is_available()` sonucu doğru olan CUDA kurulumunda seçilmelidir.

Sunucu açıkken tekrar edilebilir production-demo kabul turu:

```powershell
python -X utf8 scripts\run_production_demo_acceptance.py
```

## 11. Doğrulama

- Güncel koleksiyon: **421 test**. Yeni LLM/graf/OCR/API/orkestrasyon hedef
  paketinde **111 geçti, 1 gerçek Tesseract entegrasyonu ikili kurulu olmadığı
  için atlandı**.
- Canlı LLM ürün yolu ve güvenlik sözleşmesi hedef paketi: **66/66 geçti**.
- Tam koşu: **412 geçti, 1 atlandı, 6 başarısız, 2 hata**. Sekiz
  sorun yeni koddan önce de bulunan artifact tutarsızlıklarıdır: iki OCR aday metninin
  pinli SHA-256 değerleri, karantina JSON'larındaki başka bilgisayara ait mutlak
  yollar ve snapshot relevance gold dosya hash'i. Güven kapılarını atlamak için
  bu provenance kayıtları otomatik değiştirilmedi.
- Proje Python `>=3.11` ister; güncel koşu bu sözleşmeyi karşılayan izole çalışma
  ortamıyla yapıldı.
- Python `compileall`: başarılı.
- `pyproject.toml` ayrıştırma: başarılı.
- Mevcut global Python 3.10 ortamında `pip check`, projeden bağımsız kurulmuş
  paketler arasında sürüm çakışmaları raporluyor. Teslim çalıştırması proje
  sözleşmesine uygun Python `>=3.11` izole sanal ortamında yapılmalıdır.
- `git diff --check`: temiz.
- `git fsck --full`: temiz.
- `reports/` altındaki JSON raporları yeniden ayrıştırıldı.
- Manifestte `approved_for_active_rag=true`: **0**.
- Mevcut onaysız manifestten aktif corpus yazımı: beklenen şekilde reddedildi.
- Snapshot corpus: **8 belge, 2.606 kaynak satırı, 3 tam tekrar konsolidasyonu,
  2.603 benzersiz parça**.
- Kalıcı Qdrant yeniden açma kontrolü: **2.603/2.603 uyumlu vektör**, tam corpus
  parmak izi eşleşmesi.
- Gerçek HTTP/UI production-demo kabul turu: **23/23 zorunlu kontrol geçti**.
  Yol bakım ve eksik trafik akışları LaTeX indirme ve insan onayıyla tamamlandı;
  iki ana akışın 5/5 ilgili metinsel adayı, sıfır hard-negative sonucu, üç ayrı
  fail-closed abstention ve TXT multipart yükleme ayrıca kaydedildi.
- UI artık gerçek `/ready` kapısını kullanıyor; sayı/imzalayan/unvan alanları ve
  snapshot güncellik/hukuki-dayanak açıklamaları görünür durumda. Uygunluk
  başarısızsa süreç fail-closed çalışıyor ve onay eylemi sunmuyor.

Tam testte Windows/Starlette `.js` statik dosyasını geçerli modern MIME türü
`text/javascript` ile döndürdü; test yalnız `application/javascript` kabul
ediyordu. Test iki standart JavaScript MIME türünü platformdan bağımsız kabul
edecek şekilde düzeltildi ve tüm paket yeniden geçirildi.

## 12. Sıradaki teknik adım ve ertelenen hukuk işleri

Kullanıcı kararıyla güncel mevzuat edinme ve insan hukuk onayı bu turda
ertelendi. `competition_snapshot` + GPU/Qdrant hibrit akışının production-demo
kabul turu ile dört cevaplanabilir ve dört no-answer kaydından oluşan ilk
niyet/alaka regresyonu tamamlandı. Sıradaki zorunlu iş; bu geliştirme fixture'ından
ayrı 15-20 kör sorguluk test seti hazırlamak, jüri demosunu baştan sona prova etmek, ekran
görüntüsü/yedek demo kaydını hazırlamak ve teslim lisans/dokümantasyon
kontrol listesini kapatmaktır. RAG'da bulunan özgün mevzuat metnine
chunk/madde/sayfa kanıtıyla bağlı dinamik zorunlu alan çıkarımı yalnız zaman
kalırsa **opsiyonel Tier 1** olarak değerlendirilebilir; yapılmaması MVP'yi veya
teslimi engellemez. Uygulanırsa statik alanlar güvenlik tabanı olarak korunacak
ve snapshot adayları güncel hukuk zorunluluğu gibi gösterilmeyecektir.
Sentetik ve SHA-doğrulamalı multi-hop GraphRAG karar yolu bu turda bağlandı;
public mevzuat grafı ve korpus-geneli global özet yolu ayrı geliştirmelerdir.

İleride gerçek public corpus hedeflendiğinde eski dört dosyanın güncel kanonik
kopyaları, tam 102 sayfalık kılavuz, kanonik yönetmelik kaynağı ve yetkili kişinin
`approve`/`reject`/`needs_replacement` kararı yine zorunludur. Bu yapılana kadar
`legal_chunks_v1` boş ve fail-closed kalır; yarışma snapshot'ı ayrı uyarıyla
çalışır.
# Legal RAG v2 entegrasyonu

Kaggle'da Jina Embeddings v3 ile üretilen 30.972 hiyerarşik leaf vektörü,
`uab_legal_leaf_v2` adlı Qdrant koleksiyonu olarak uygulamaya bağlandı. Uygulama
named vector olarak `dense` alanını kullanır; corpus ve Qdrant payload'ları aynı
fingerprint sözleşmesine bağlanmıştır. Hazır vektörler tekrar embed edilmez.

Backend'i GPU ile başlatmak için:

```powershell
.\scripts\start_local_uab.ps1 -EmbeddingDevice cuda:0
```

Frontend ayrı terminalde başlatılır:

```powershell
python -m http.server 3000 --directory frontend
```

Arayüz: `http://127.0.0.1:3000`. CPU üzerinde Jina modeli bu 16 GB RAM'li
geliştirme makinesinde güvenli boş bellek bırakmadığı için manuel test GPU'lu
ortamda yapılmalıdır.
