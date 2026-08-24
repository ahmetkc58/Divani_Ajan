# Proje Planı — Kamu Evrak ve Yazışma Süreçleri İçin Akıllı Agent Destek Sistemi
**TEKNOFEST 2026 — Yapay Zeka Dil Ajanları Yarışması (1. Senaryo)**

---

## ⚠️ 0. Kritik Zaman Durumu

| | |
|---|---|
| Plan başlangıcı | **19 Ağustos 2026** |
| Son uygulama denetimi | **24 Ağustos 2026** |
| Çevrimiçi süreç son tarihi | **26 Ağustos 2026** |
| Kalan süre | **~2 gün** |
| Final | Ağustos (tarih TEKNOFEST takviminde ilan edilecek) |

Bu plan, "ideal/kapsamlı mimari" değil, **7 gün içinde uçtan uca çalışan, demo edilebilir bir sistem** teslim etme gerçeğine göre kurgulanmıştır. Puanlamada Uygulama (35) + Demo (15) = **100 puanın yarısı çalışırlığa bağlı**; yarım kalmış ama "teorik olarak ileri" bir mimari, sade ama sağlam çalışan bir mimariden daha düşük puan alır. Bu nedenle aşağıdaki her bölüm **Tier 0 (zorunlu) / Tier 1 (zaman kalırsa) / Tier 2 (dokümante edilir, muhtemelen kodlanmaz)** şeklinde önceliklendirilmiştir.

---

## 1. Proje Özeti

- **Yarışma teması:** Kamu evrak ve yazışma süreçlerini destekleyen, Türkçe çalışan yapay zeka tabanlı akıllı agent sistemi.
- **Zorunlu iki görev** (ikisi de tamamlanmadan proje değerlendirmeye alınmaz):
  1. **Görev 1 — Evrak Sınıflandırma ve İçerik Analizi**
  2. **Görev 2 — Resmî Yazı Taslaklama ve Birim Yönlendirme**
- **Değerlendirme (100 puan):** Yöntem ve Teknik Yaklaşım (35) · Uygulama (35) · Demo (15) · Yenilikçilik/Ticarileşme (15)
- **Veri kısıtı:** Gerçek kamu verisi **kullanılamaz** (madde 6.5). Sentetik evrak, kurgu kurum/birim listesi ve kamuya açık mevzuat metinleri kullanılacak.
- **Teslim kısıtı:** Kod, açık kaynak lisansla (MIT/Apache/GNU) Türkiye Açık Kaynak Platformu GitHub'ında paylaşılmalı; tüm dokümantasyon Türkçe.

---

## 2. Proje Klasöründeki Referans Kaynaklar

| Dosya | İçerik | Rolü |
|---|---|---|
| `2026_TYDA_SARTNAME_...pdf` | Yarışma teknik şartnamesi | Gereksinim kaynağı (bu plan buradan türetildi) |
| `mevzuat-1.pdf` | **Resmî Yazışmalarda Uygulanacak Usul ve Esaslar Hakkında Yönetmelik** (49 sayfa) | Görev 2'nin "resmi üsluba uygunluk" ve format kurallarının **birincil kaynağı** |
| `mevzuat-kılavuz.pdf` | Aynı yönetmeliğin **Kılavuzu** (26 sayfa, örnek/şablon içerikli) | Taslak üretimi için örnek doküman kaynağı |

**Teknik not:** Bu iki mevzuat PDF'i, gömülü font kodlamasından dolayı `pdftotext`/`pypdf` ile metne çevrilince Türkçe'ye özgü harfler (ı, ş, ğ, ü, ö, ç) düşüyor. Sayfalar görsel olarak okunabilir; ancak makine OCR adaylarında karakter ve satır sırası hataları vardır ve **standart metin çıkarımı bu dosyalarda güvenilir değildir**. Bu, projenin kendi evrak-okuma modülü için de gerçek bir tasarım girdisi: OCR/görsel tabanlı çıkarım (veya en azından font/encoding doğrulama adımı), yalnızca "nice to have" değil, **gerçek bir ihtiyaç** olarak Tier 0'a alınmalı.

Yönetmelikten şimdiye kadar görsel olarak doğrulanan içerik: Amaç/Kapsam/Dayanak (Md 1-2), Tanımlar (Md 3 — aidiyet zinciri, arşiv imza, belge, **DETSİS**, EBYS, elektronik onay/ortam, e-Yazışma Teknik Rehberi, form/format, güvenli elektronik imza, standart dosya planı, üstveri, üst yazı, yetkili makam, zaman damgası, zorunlu hâl). Kalan maddeler (format kuralları, imza blokları, gizlilik dereceleri, ekler/dağıtım, arşivleme) ekip tarafından dosyadan görsel olarak çıkarılıp **doğrulanmalı** — bu plandaki format kuralı detayları varsayım değil, kaynağa referansla teyit edilmelidir.

---

## 3. Veri Stratejisi

Şartname madde 6.5 gerçek kamu verisini yasaklıyor. Buna göre:

1. **Sentetik evrak korpüsü:** En az 6-8 evrak türü (dilekçe, üst yazı, cevap yazısı, bilgi talebi, ihbar/şikayet, bilgilendirme yazısı, iç yazışma) × her türden 5-10 örnek → toplam ~40-60 kurgu evrak. LLM ile üretilip, biçimsel çeşitlilik (eksik alanlı, bozuk formatlı, taranmış görüntü kalitesinde) kasıtlı olarak eklenmeli ki sistemin "eksik bilgi tespiti" yeteneği gerçekten test edilsin.
2. **Mevzuat corpus:** `verified_public` hedefinde yalnız insan tarafından güncellik/yürürlük onayı verilen metinler; mevcut yarışma uygulamasında ise `mevzuat-1.pdf`, `mevzuat-kılavuz.pdf` ve altı çekirdek karayolu belgesinin sabitlenmiş kopyaları Bölüm → Madde → Fıkra → Bent yapısında kullanılır. Bu ikinci yol güncellik veya hukuki görüş iddiası taşımayan ayrı `competition_snapshot` corpusudur.
3. **Kurum/birim listesi (DETSİS esinli, sentetik):** Gerçek DETSİS kayıtları çekilmeyecek (hem erişim kısıtlı hem de "gerçek kamu verisi" riski var — bkz. önceki tartışma). Bunun yerine DETSİS'in **numaralandırma formatı ve hiyerarşi mantığı** referans alınarak kurgu bir kurum/birim ağacı (örn. "Örnek Bakanlık > Örnek Genel Müdürlük > Örnek Daire Başkanlığı") oluşturulacak. Bu liste, birim yönlendirme agent'ının hedef havuzu olacak.

**Veri denetimi — 24 Ağustos 2026:** Kamuya açık DETSİS/UAB kayıtları yalnızca
kaynak araştırması ve kapsam doğrulaması için ayrı tutulmaktadır; çalışma
zamanındaki kurum/birim havuzu hâlâ sentetiktir. Eski
`data/manifests/uab_legislation_manifest.json`, 501 PDF eşleşmesi kaydetmektedir;
ancak bu yolların bağlı olduğu arşiv çalışma alanında yoktur ve mevcut dosya
sayısı **0/501**'dir. Bu manifest fiziksel arşiv geri gelmeden indeks kaynağı
değildir. Depoda gerçekten bulunan sekiz çekirdek kaynak, boyut ve SHA-256
değerleriyle `data/manifests/core_legislation_sources.json` içinde ayrı
envantere alınmıştır. İnsan kapsam/yürürlük/OCR doğrulaması tamamlanmadığı için
aktif RAG onayı verilen gerçek kayıt sayısı sıfırdır.

**Aşama 3 teknik kapanış — 24 Ağustos 2026:** Sayfa izini koruyan Bölüm → Madde
→ Fıkra → Bent chunker'ı, uzun hüküm bölme, kararlı `document_id` tabanlı chunk
kimliği, kaynak SHA-256 kontrolü, çekirdek envanterden inceleme manifesti üretimi,
review CSV geri-alımı, karantina toplu ingestion, onaylı manifestten ingestion,
tek aktif-corpus çıktısı ve public korpus için fail-closed aktif-RAG filtresi
tamamlanmıştır. Sekiz çekirdek kaynak gerçek pipeline'dan geçirilmiş; metin
katmanı uygun altı belge **2.407 parçaya** ayrılmış, sayfa metadata kaybı `0` ve
yanlış aktif onay sayısı `0` olarak doğrulanmıştır. Kalan iki belge otomatik
olarak OCR kuyruğuna alınmıştır.

Bu kapanış **teknik veri hazırlama aşamasının** tamamlandığını ifade eder. Kaynak
metinlerin en güncel sürümle değiştirilmesi, yürürlük/hukuk uzmanı kontrolü, iki
belgenin OCR + görsel doğrulaması ve insanın `approved_for_active_rag=true`
kararı ayrı bir **Aşama 3 sonrası içerik doğrulama işi** olarak ertelenmiştir.
Bu işler tamamlanmadan gerçek kamu mevzuatı aktif indekse alınmayacaktır.
Varsayılan sentetik BM25 fallback korunurken, aşağıdaki ayrı ve uyarılı yarışma
snapshot'ı hibrit demo yolunu sağlar.

**Aşama 3 yarışma-snapshot uygulaması — 24 Ağustos 2026:** Kullanıcı kararıyla
güncel mevzuat edinme ve public aktivasyonun ilk iki işi bu turda atlanmış;
eldeki 8 belge, güncellik/yürürlük iddiası taşımayan ayrı
`competition_snapshot` sözleşmesiyle işlenmiştir. Altı metin-katmanı çıktısı ile
iki OCR adayından gelen 2.606 satırdaki 3 tam tekrar konsolide edilmiş ve 2.603
benzersiz parça (2.404 metin-katmanı + 199 OCR) üretilmiştir. Tüm parçalar RTX
3050 üzerinde Jina Embeddings v3 `retrieval.passage`, 1024D ve `cuda:0` ile
vektörleştirilerek kalıcı gömülü Qdrant
`competition_snapshot_chunks_v1` koleksiyonuna yazılmıştır. Yeniden açma
kontrolünde 2.603/2.603 uyumlu nokta ve corpus parmak izi doğrulanmıştır.

Bu uygulama `legal_chunks_v1` public kapısını değiştirmez: snapshot atıfları
zorunlu güncellik/hukuki kullanım uyarısı taşır, `currentness_verified=false` ve
`legal_reliance_allowed=false` kalır. Sıradaki teknik iş, bu hazır hibrit yolu
manuel uçtan uca kabul senaryolarında atıf, taslak, yönlendirme, uyarı ve
abstention davranışlarıyla doğrulamaktır.

---

## 4. Sistem Mimarisi

```
                        ┌───────────────────────────┐
                        │        ORKESTRATÖR         │
                        │  (görev akışını yönetir)   │
                        └─────────────┬─────────────┘
                                      │
      ┌───────────────┬──────────────┼──────────────┬───────────────┐
      ▼               ▼              ▼              ▼               ▼
┌───────────┐  ┌──────────────┐ ┌───────────┐ ┌─────────────┐ ┌──────────────┐
│ Alım /    │  │ Sınıflandırma│ │ Mevzuat   │ │ Eksik Bilgi │ │ Özetleme     │
│ OCR-Metin │─▶│ & İçerik     │▶│ Eşleştirme│▶│ Tespiti     │▶│              │
│ Çıkarımı  │  │ Analizi      │ │ (RAG)     │ │             │ │              │
└───────────┘  └──────────────┘ └───────────┘ └─────────────┘ └──────────────┘
      GÖREV 1 — Evrak Sınıflandırma ve İçerik Analizi (çıktı: yapılandırılmış evrak özeti)
                                      │
                                      ▼
                        ┌───────────────────────────┐
                        │   Taslak Oluşturma Agent'ı │  ← Yönetmelik format kuralları
                        │   (üst yazı/cevap/bilgi.)  │     + Kılavuz örnekleri
                        └─────────────┬─────────────┘
                                      ▼
                        ┌───────────────────────────┐
                        │  Birim Yönlendirme Agent'ı │  ← Sentetik DETSİS-esinli birim ağacı
                        └─────────────┬─────────────┘
                                      ▼
                        ┌───────────────────────────┐
                        │  Kullanıcı Bilgilendirme / │
                        │  Eksik Bilgi Talebi        │
                        └───────────────────────────┘
      GÖREV 2 — Resmî Yazı Taslaklama ve Birim Yönlendirme
```

---

## 5. Teknik Yaklaşım — Önceliklendirilmiş Katmanlar

### Tier 0 — Zorunlu MVP (Gün 1-4, uçtan uca çalışmalı)
| Bileşen | Yaklaşım |
|---|---|
| Metin çıkarımı | OCR (Tesseract/EasyOCR) + doğrudan metin fallback; encoding doğrulama adımı |
| Sınıflandırma | LLM ile zero/few-shot evrak türü sınıflandırma (kapalı etiket seti) |
| İçerik analizi | LLM ile yapılandırılmış bilgi çıkarımı (JSON: gönderen, konu, tarih, talep vb.) |
| Mevzuat eşleştirme | Hibrit RAG: mevzuat yapısına göre parçalama → bağlamsallaştırma → `jina-embeddings-v3` + BM25 → Qdrant/RRF → kaynak doğrulama |
| Özet | LLM ile kısa özet üretimi |
| Eksik bilgi tespiti | Evrak türüne göre zorunlu alan listesi + LLM kontrolü |
| Taslak oluşturma | Sürümlü ve onaylı LaTeX şablonu + LLM'in şemaya uygun JSON alanları üretmesi + güvenli PDF derleme |
| Birim yönlendirme | Sentetik birim ağacı üzerinde LLM/embedding ile en uygun birim seçimi |
| Orkestrasyon | Ortak durum kaydı üzerinden çalışan açık rollü çok ajanlı sistem: Alım/OCR, Sınıflandırma, Mevzuat Araştırma, Kaynak Doğrulama, Yazı Türü Karar ve Şablon Seçimi, Taslak Oluşturma, Birim Yönlendirme, Uygunluk Denetimi ve Kullanıcı Bilgilendirme ajanları |

### Tier 1 — Zaman kalırsa eklenecek (Gün 5-6)
| Teknik | Neden bu sırada |
|---|---|
| **Contextual Retrieval** | Her yapısal parçaya belge içindeki yerini açıklayan kısa bağlam eklenir; aynı bağlamsal metin hem Jina embedding hem BM25 indeksine verilir. Hukuk metninin Bölüm/Madde/Fıkra/Bent yapısı birincil sınır olarak korunur. |
| **CRAG** (Self-RAG değil) | Hazır modelle çalışır, fine-tuning gerektirmez (şartname "model eğitmek zorunlu değil" diyor); yanlış/alakasız mevzuat eşleşmesini yakalayıp düzeltir |
| **Reranker** | Hibrit aramanın geniş aday kümesini sorguya göre yeniden sıralar; yalnızca doğrulanacak en güçlü parçaların ajanlara aktarılmasını sağlar. |

### Tier 2 — Dokümante edilecek, muhtemelen kodlanmayacak (vizyon/gelecek iş)
> Bu teknikler jüriye "biz bu alanı araştırdık" göstermek için **Yöntem ve Teknik Yaklaşım** bölümünde mimari vizyon olarak anlatılabilir, ama 7 günlük takvimde tam entegrasyonu riskli:
- **HippoRAG** — mevzuat madde ↔ şablon çok-adımlı (multi-hop) bağlantı grafiği
- **Search-o1 tarzı agentic sorgu** — taslak üretimi sırasında anlık mevzuat sorgusu (basit tool-calling ile kısmen zaten Tier 0'da örtük var, "Search-o1" markasıyla ayrı bir sistem kurmaya gerek yok)
- **A-MEM** — geçmiş yönlendirme kararlarının kalıcı/ilişkisel hafızası
- **ColPali** — evrakı görüntü olarak embed etme (OCR yerine). Test evrakları temiz/taranmış kalitede kalacaksa gereksiz risk; gerçekten karmaşık layout (damga, tablo, logo) demo'da öne çıkacaksa değerlendirilebilir.

### 5.1. Kesinleşen Embedding, Hibrit RAG ve GraphRAG Mimarisi

**Mimari karar — 24 Ağustos 2026:** Mevzuat ve kurum/birim semantik aramasında
`jinaai/jina-embeddings-v3` kullanılacaktır. Vektör veritabanı olarak Qdrant,
kelime-temelli arama için mevcut BM25 katmanı korunacaktır. Dense ve lexical
sonuçlar ham skorları doğrudan toplanarak değil, başlangıçta Reciprocal Rank
Fusion (RRF) ile birleştirilecektir. Bu katman mevcut kural tabanlı MVP'yi
kaldırmayacak; çevrimdışı ve açıklanabilir fallback olarak koruyacaktır.

#### Jina embedding sözleşmesi

| Ayar | Karar |
|---|---|
| Model | `jinaai/jina-embeddings-v3` |
| Belge/chunk görevi | `retrieval.passage` |
| Kullanıcı sorgusu görevi | `retrieval.query` |
| Başlangıç vektör boyutu | `1024` |
| Benzerlik metriği | Cosine |
| Yarışma snapshot yürütme aygıtı | NVIDIA GPU, `cuda:0` (gerçek koşu: RTX 3050) |
| Azami model bağlamı | 8192 token; ancak retrieval chunk'ları hukuk yapısına göre daha küçük tutulur |
| Sürümleme | Model adı, boyut, görev adaptörü ve indeks sürümü her kaydın metadata'sında tutulur |

Model Matryoshka Representation Learning ile daha düşük boyutlarda çıktı
üretebilse de boyut azaltma ancak proje gold setinde `Recall@5`, MRR, depolama
ve gecikme birlikte ölçüldükten sonra yapılacaktır. İndeks oluştururken
`retrieval.passage`, çalışma zamanında sorgu vektörü üretirken
`retrieval.query` kullanılmaması bir yapılandırma hatası sayılacaktır.

**Lisans notu:** Model kartında yerel model ağırlıkları CC BY-NC 4.0 olarak
belirtilmektedir. Yarışma kullanımı, depoda model ağırlığı paylaşımı ve gelecekteki
ticari kullanım ayrı ayrı değerlendirilecek; model dosyası depoya eklenmeyecek,
sürüm, erişim bağlantısı ve lisans bilgisi dokümante edilecektir.

#### Yapısal ve bağlamsal parçalama

Hukuk metni için birincil sınırlar sabit token pencereleri değil, metnin kendi
yapısıdır:

```text
Mevzuat
  → Bölüm
    → Madde
      → Fıkra
        → Bent
```

Bir fıkra model/indeks sınırını aşıyorsa yalnızca o fıkra cümle sınırlarında alt
parçalara ayrılır; her alt parça üst `mevzuat_id`, bölüm, madde, fıkra, bent,
sayfa ve yürürlük metadata'sını taşır. `arXiv:2605.19806` çalışmasının hukuk
metninin doğal section/subsection yapısını koruyan daha basit parçalamanın daha
karmaşık stratejilerden daha başarılı olabildiği bulgusu bu kararın deneysel
dayanağıdır.

Her orijinal parçaya, bütün belge içindeki konumunu açıklayan yaklaşık 50-100
tokenlık kısa bir `context_text` üretilecektir. İndekslenecek metin
`context_text + original_text` olur; aynı metin hem Jina embedding'e hem BM25'e
verilir. `context_text` yardımcı ve sentetik açıklamadır; kullanıcıya mevzuat
hükmü olarak gösterilemez. Nihai atıf her zaman `original_text`, kaynak PDF,
madde/fıkra ve mümkünse sayfaya döner.

#### Qdrant koleksiyonları ve payload

Üretim mimarisinde üç fiziksel koleksiyon korunacaktır. Güncelliği doğrulanmamış
yarışma snapshot'ı bunlara karışmayan dördüncü, açıkça ayrı bir demo koleksiyonu
kullanır:

```text
legal_chunks_v1        # Mevzuat ve resmî yazışma kuralları
organization_units_v1  # Sentetik kurum/birim görevleri
graph_nodes_v1         # Graf düğümü açıklamaları ve topluluk özetleri
competition_snapshot_chunks_v1  # Güncellik iddiası taşımayan sabit yarışma snapshot'ı
```

`legal_chunks_v1` içindeki her nokta en az şu payload alanlarını taşır:

```json
{
  "chunk_id": "MEV-...",
  "document_id": "...",
  "title": "...",
  "domain": "kgm_infrastructure",
  "subdomain": "traffic_safety",
  "document_type": "yonetmelik",
  "article": "MADDE 7",
  "paragraph": "2",
  "clause": "a",
  "page": 14,
  "page_end": 14,
  "source_path": "...",
  "source_url": "...",
  "source_sha256": "...",
  "source_kind": "public_legislation",
  "validity_status": "verified",
  "approved_for_active_rag": true,
  "ocr_status": "text_layer_available",
  "context_text": "...",
  "original_text": "...",
  "embedding_model": "jinaai/jina-embeddings-v3",
  "embedding_dimension": 1024,
  "embedding_task": "retrieval.passage",
  "embedding_model_revision": "ab036b...",
  "embedding_code_revision": "bd55a5e...",
  "index_version": "1.0"
}
```

`embedding_code_revision`, modelin `auto_map` ile kullandığı ayrı
`jinaai/xlm-roberta-flash-implementation` deposunun commit'idir. Model ağırlığı
commit'i bu ayrı kod deposunda bulunmadığından iki revision bilinçli olarak
farklı ve ayrı ayrı sabitlenir.

`domain`, `subdomain`, `validity_status`, `approved_for_active_rag`,
`document_type`, `document_id`, `corpus_mode`, `source_kind`, `status`,
`currentness_verified` ve `legal_reliance_allowed` alanları Qdrant payload
indeksi alacaktır.
Üretim aramasında `approved_for_active_rag=true` ve
`validity_status=verified` zorunlu filtredir. Alan sınıflandırma ajanı ayrıca
`domain` filtresini belirler; karayolu sorgusuna denizcilik/havacılık kaynağı
karışması bu katmanda engellenir.

`competition_snapshot_chunks_v1` aynı embedding ve parmak izi bütünlüğünü
uygular; fakat `corpus_mode=competition_snapshot`,
`currentness_verified=false`, `legal_reliance_allowed=false` ve sabit kullanım
uyarısı zorunludur. Snapshot koleksiyonu `legal_chunks_v1` adıyla oluşturulamaz,
public sonuç filtresinden geçirilemez ve kullanıcı arayüzünde doğrulanmış güncel
mevzuat olarak etiketlenemez. Uzak Qdrant sunucusunda payload indeksleri zorunlu
olarak doğrulanır. Gömülü yerel Qdrant payload indeks API'sini desteklemediği için
kalıcı snapshot modunda aynı filtre metadata'sı readiness sayımı ve tam corpus
parmak iziyle doğrulanır; bu sınırlama raporda açıkça gösterilir.

#### Hibrit retrieval akışı

```text
Kullanıcı evrakı/sorgusu
      ↓
Alan ve sorgu türü sınıflandırması
      ↓
Sorgu zenginleştirme (evrak türü + konu + talep + anahtar kavramlar)
      ↓
┌─────────────────────────┬──────────────────────────┐
│ Jina retrieval.query    │ Contextual BM25          │
│ Qdrant dense top-N      │ lexical top-N            │
└─────────────┬───────────┴─────────────┬────────────┘
              └───────────RRF───────────┘
                           ↓
                    Reranker top-K
                           ↓
                 Güven sözleşmesi doğrulaması
                           ↓
       ┌───────────────────┴────────────────────┐
       │ verified_public: doğrulanmış kanıt     │
       │ competition_snapshot: provenance +     │
       │ zorunlu güncellik/hukuki görüş uyarısı │
       └────────────────────────────────────────┘
```

İlk sürümde her kanal `top-N=20` aday üretecek, RRF sonrası reranker'a en fazla
30 benzersiz aday verilecek ve üretim ajanlarına en fazla 5-10 doğrulanmış
parça aktarılacaktır. Bu sayılar sabit ürün gerçeği değil, gold set üzerinde
ayarlanacak başlangıç değerleridir. Ham cosine ve BM25 skorları farklı
ölçeklerde olduğundan normalizasyon olmadan `alpha * dense + beta * bm25`
uygulanmayacaktır.

#### GraphRAG ve LegalGraphRAG uyarlaması

Microsoft GraphRAG'ın tüm paketini doğrudan kurmak yerine sorgu türüne göre
seçici bir graf katmanı geliştirilecektir:

- **Local/hybrid arama:** Belirli evrak, madde, kurum veya birim soruları için
  varsayılan yoldur; doğrulanmış kaynak parçalarını getirir.
- **Global arama:** Bütün korpustaki ortak temalar, yükümlülükler ve etkiler gibi
  topluluk özeti gerektiren sorular için kullanılır.
- **Multi-hop graf araması:** Mevzuat → görev → birim → şablon gibi birden çok
  ilişki üzerinden cevap gerektiren sorgularda kullanılır.

İlk graf düğümleri `Mevzuat`, `Madde`, `Fıkra`, `Bent`, `Kurum`, `Birim`,
`Görev`, `Süreç`, `EvrakTürü`, `YazıŞablonu`, `ZorunluAlan` ve `Konu` olacaktır.
İlişki türleri başlangıçta `CONTAINS`, `CITES`, `AMENDS`, `REPEALS`,
`APPLIES_TO`, `ASSIGNED_TO`, `RESPONSIBLE_FOR`, `REQUIRES_FIELD`,
`SUPPORTS_TEMPLATE`, `SUPERSEDES` ve `RELATED_TO` ile sınırlandırılır.

LegalGraphRAG'daki üç rol mevcut sisteme şu şekilde uyarlanacaktır:

1. **Researcher / Mevzuat Araştırma Ajanı:** Dense, BM25 ve gerektiğinde graf
   üzerinden aday kanıtları getirir.
2. **Auditor / Kaynak Doğrulama Ajanı:** Her adayın kaynak metnini, atfını,
   yürürlük ve kapsam durumunu doğrular; doğrulanmayan parçayı eler.
3. **Adjudicator / Karar ve Taslak Ajanı:** Yalnızca doğrulanmış kanıt paketini
   kullanarak yazı türü, yönlendirme ve taslak kararını gerekçelendirir.

Uygunluk Denetçisi, Adjudicator çıktısını resmî yazışma kuralları ve kaynak
sadakati açısından ikinci kez kontrol eder. Böylece graf ilişkisi veya LLM
çıktısı tek başına kesin mevzuat kanıtı sayılmaz.

#### Cross-Document Topic-Aligned Chunking sınırı

`arXiv:2601.05265` içindeki Cross-Document Topic-Aligned (CDTA) yaklaşımı,
birden fazla belgede dağılmış aynı konuya ait bilgileri corpus seviyesinde
birleştirmeyi önermektedir. Bu projede CDTA yalnızca deneysel olarak sorgu
genişletme, konu haritası ve graf topluluk özeti üretiminde kullanılabilir.
LLM tarafından sentezlenmiş CDTA parçası mevzuat hükmü veya birincil kanıt
olarak sunulamaz; cevap üretmeden önce ilişkili orijinal maddelere geri dönmek
zorunludur.

#### Aşamalı uygulama ve kabul ölçütleri

1. **Tamamlandı (24 Ağustos):** Bölüm/Madde/Fıkra/Bent chunker'ını sayfa, kaynak hash'i, onay metadata'sı ve uzun fıkra bölme desteğiyle tamamla.
2. **Tamamlandı (24 Ağustos):** Jina v3 passage/query sağlayıcı arayüzünü,
   ağırlık/kod revision pinlerini ve açık BM25 fallback sözleşmesini ekle.
3. **Tamamlandı (24 Ağustos):** Qdrant `legal_chunks_v1` cosine/1024 şemasını,
   payload indekslerini, fail-closed public kaynak kapılarını, insan-onay zarfını,
   exact-corpus SHA-256 fingerprint/allow-list bağını, kimlik başına kanonik tam
   içerik SHA-256 doğrulamasını ve `index-vectors` komutunu ekle. Eski, başka
   korpusa ait veya aynı kimlikle değiştirilmiş noktalar sorgu sonucuna giremez.
4. **Tamamlandı (24 Ağustos):** Contextual BM25 ile Jina/Qdrant sonuçlarını
   kanal başına top-20 ve klasik `k=60` RRF üzerinden birleştir; kanal izi ile
   çalışma zamanı teşhisini süreç kaydında sakla. RRF yalnız sıralamadır;
   dense-only hukuki kanıt ham cosine `>= 0,20` mutlak eşiğini geçmelidir.
5. **Tamamlandı (24 Ağustos):** Aynı sabit sentetik gold set üzerinde BM25-only,
   gerçek ve sabit revizyonlu Jina-v3/Qdrant hybrid ve reranked koşularını ayrı
   raporla. Hybrid Recall@5 `%100`, MRR `%90,97`; BM25'e göre Recall@5 artışı
   `+%19,44` olarak ölçüldü. Onaylı public korpus oluştuğunda aynı protokol tekrar
   çalıştırılacak.
6. **Tamamlandı (24 Ağustos):** Sabit revizyonlu çok dilli reranker eklendi ve
   ablation ölçüldü. Recall@5 `%97,22`'ye gerilediği ve belirgin ek gecikme
   getirdiği için varsayılan olarak kapalı bırakıldı.
7. **Researcher/Auditor sözleşmesi tamamlandı (24 Ağustos):** Dense-only kanıtı
   yalnız tam public kaynak kapılarıyla kabul et; sentetik demo kuralını public
   mevzuat gibi göstermeden ayrı doğrula; snapshot atfını ise yalnız
   `currentness_verified=false`, `legal_reliance_allowed=false` ve sabit uyarıyla
   kabul et.
8. **Tamamlandı (24 Ağustos):** Küçük, elle doğrulanabilir sentetik
   mevzuat-birim-şablon grafı; üç girdinin SHA-256 kimliği, veri seti/sürümü ve
   yeniden hesaplanan düğüm/kenar sayaçlarıyla üretildi.
9. **Tamamlandı (24 Ağustos):** Sekiz belgeli `competition_snapshot` corpusunu
   2.603 benzersiz parçayla üret; GPU'da Jina v3 ile kalıcı ve ayrı Qdrant
   koleksiyonuna indeksle; yeniden açma/readiness, hibrit BM25+dense+RRF ve
   kullanıcı uyarısı sözleşmesini doğrula.
10. Yalnızca multi-hop/global sorgularda graf yolunu etkinleştir.
11. CDTA/topluluk özetlerini Tier 2 deneyi olarak değerlendir.

Kabul ölçütleri:

- Karayolu retrieval gold setinde `Recall@5 >= %90` hedefi.
- Trust modu açıklanmayan mevzuat iddiası sayısı `0`: public kanıt
  `approved_for_active_rag=true`/`verified` olmalı; snapshot atfı ise
  `currentness_verified=false`, `legal_reliance_allowed=false` ve sabit kullanım
  uyarısını taşımalıdır.
- Paraphrase challenge retrieval sonucunun BM25 baseline `%12,5` değerinin
  üzerine çıkması; iyileşmenin aynı sabit veri setinde raporlanması.
- Her sonuçta chunk kimliği, belge, madde/fıkra, sayfa, skor kanalları ve
  doğrulama kararının izlenebilir olması.
- Jina/Qdrant kullanılamadığında mevcut BM25 tabanlı demo akışının açık bir
  uyarıyla çalışmaya devam etmesi.
- Hibrit benchmark'ta her sorgunun `dense_status=used`, `fallback_used=false`
  olması; aksi durumda BM25 sonucunun hibrit etiketiyle raporlanmaması.
- `challenge_no_answer` diliminde düşük benzerlikli dense-only sonuç için açık
  hukuki kanıt abstention kararının ölçülmesi.

#### Bilimsel ve teknik kaynaklar

1. Sturua, S. ve diğerleri (2024), *jina-embeddings-v3: Multilingual
   Embeddings With Task LoRA*, arXiv:2409.10173 —
   <https://arxiv.org/abs/2409.10173>
2. Edge, D. ve diğerleri (2024), *From Local to Global: A Graph RAG Approach
   to Query-Focused Summarization*, arXiv:2404.16130 —
   <https://arxiv.org/abs/2404.16130>
3. Chen, Z. ve diğerleri (2026), *LegalGraphRAG: Multi-Agent Graph
   Retrieval-Augmented Generation for Reliable Legal Reasoning*,
   arXiv:**2605.28120** — <https://arxiv.org/abs/2605.28120> ve resmî kod:
   <https://github.com/XMUDeepLIT/LegalGraphRAG>
4. Prior, M., Milanova, N. ve Schultz, A. (2026), *Chunking German Legal
   Code*, arXiv:2605.19806 — <https://arxiv.org/abs/2605.19806>
5. Stankovic, M. (2026), *Cross-Document Topic-Aligned Chunking for
   Retrieval-Augmented Generation*, arXiv:2601.05265 —
   <https://arxiv.org/abs/2601.05265>
6. Anthropic (2024), *Introducing Contextual Retrieval* —
   <https://www.anthropic.com/engineering/contextual-retrieval>
7. Qdrant, *Hybrid and Multi-Stage Queries* —
   <https://qdrant.tech/documentation/search/hybrid-queries/>

Not: Daha önce LegalGraphRAG için verilen `arXiv:2605.19806` kimliği doğru
değildir; bu kimlik *Chunking German Legal Code* çalışmasına aittir.
LegalGraphRAG'ın doğru kimliği `arXiv:2605.28120`'dir.

---

## 6. Görev Bazlı Detay Plan

### Görev 1 — Evrak Sınıflandırma ve İçerik Analizi
Beklenen yetenekler (şartname 6.4.1): OCR/metin okuma, tür belirleme, bilgi çıkarımı, eksik bilgi tespiti, mevzuat/yönetmelik önerisi, özet.
**Çıktı formatı (öneri):**
```json
{
  "evrak_turu": "...",
  "ozet": "...",
  "cikarilan_bilgiler": {"gonderen": "...", "konu": "...", "tarih": "...", "talep": "..."},
  "eksik_alanlar": ["..."],
  "onerilen_mevzuat": [{"madde": "...", "kaynak": "mevzuat-1.pdf", "aciklama": "..."}]
}
```

### Görev 2 — Resmî Yazı Taslaklama ve Birim Yönlendirme
Beklenen yetenekler (şartname 6.4.2): taslak oluşturma (üst yazı/cevap/bilgilendirme), resmi üsluba uygunluk, birim yönlendirme önerisi, süreç bilgilendirmesi, gerektiğinde eksik bilgi talebi.
**Kritik:** Taslağın "resmi üsluba uygunluğu", Yönetmelik'teki format kurallarına (kurum adı, sayı/tarih alanı, hitap, imza bloğu, ek/dağıtım) göre **otomatik kontrol edilmeli** — bu bir doğrulama katmanı (kural motoru) olarak Tier 0'a dahil edilmeli, sadece LLM'in "iyi niyetine" bırakılmamalı.

#### Yazı Türü Karar ve Şablon Seçimi Ajanı

LaTeX bileşeni seçilen şablonu güvenli biçimde doldurup PDF üretir; hangi resmî yazı türünün hazırlanacağına ise bundan önce çalışan **Yazı Türü Karar ve Şablon Seçimi Ajanı** karar verir. Ajan, gelen evrakın türü, amacı, talebi, muhatabı, eksik alanları ve doğrulanmış mevzuat sonuçlarını değerlendirerek `üst_yazı`, `cevap_yazısı`, `bilgilendirme_yazısı` veya `eksik_bilgi_talebi` seçeneklerinden birini seçer. Seçim gerekçesi ve güven skoru kullanıcıya gösterilir; düşük güven durumunda otomatik üretim yerine kullanıcı onayı istenir.

```json
{
  "onerilen_yazi_turu": "cevap_yazisi",
  "template_id": "cevap_yazisi_v1",
  "karar_gerekcesi": "Gelen evrak kurumdan bilgi ve işlem sonucu talep etmektedir.",
  "guven_skoru": 0.91,
  "kullanici_onayi_gerekli": false,
  "alternatifler": [
    {"yazi_turu": "bilgilendirme_yazisi", "uygunluk_skoru": 0.31}
  ]
}
```

Bu karar çıktısı LaTeX üretim modülünün girdisi olacaktır. Böylece sistem yalnızca bir şablonu doldurmayacak, şartnamenin istediği şekilde hazırlanması gereken resmî yazı türüne de gerekçeli olarak karar verecektir.

#### LaTeX Tabanlı Güvenli Evrak Üretim Mimarisi

Evrak üretiminde modelden her istek için sıfırdan ve serbest biçimde LaTeX kodu yazması istenmeyecektir. Örnek resmî evraklar bir defaya mahsus analiz edilerek onaylı, sürümlü ve salt okunur LaTeX şablonlarına dönüştürülecek; model yalnızca gelen evraktan ve doğrulanmış mevzuat sonuçlarından elde edilen değişken alanları yapılandırılmış JSON olarak üretecektir. Uygulama bu alanları şablona güvenli biçimde yerleştirip PDF çıktısını oluşturacaktır.

**Şablon dizin yapısı (öneri):**

```text
templates/
├── resmi_yazi/
│   ├── template.tex
│   ├── schema.json
│   ├── rules.yaml
│   └── metadata.json
├── ust_yazi/
├── cevap_yazisi/
├── bilgilendirme_yazisi/
└── eksik_bilgi_talebi/
```

- `template.tex`: Logo, kenar boşlukları, başlık, sayı/tarih, imza, ek ve dağıtım gibi değişmemesi gereken düzeni içerir.
- `schema.json`: Modelin üretmesine izin verilen alanları, veri tiplerini ve zorunlu alanları tanımlar.
- `rules.yaml`: Belge türüne özgü biçim, üslup ve mevzuat kurallarını içerir.
- `metadata.json`: Şablon kimliği, sürümü, onay durumu, kaynak örnek ve geçerlilik tarihini tutar.

**Üretim akışı:**

```text
Gelen PDF/görsel
      ↓
OCR ve yapılandırılmış bilgi çıkarımı
      ↓
İlgili mevzuatın RAG ile bulunması
      ↓
Kaynak ve mevzuat doğrulaması
      ↓
Yazı Türü Karar ve Şablon Seçimi Ajanı
      ↓
Modelin şemaya uygun JSON içerik üretmesi
      ↓
Kaynak, zorunlu alan ve mevzuat doğrulaması
      ↓
Alanların onaylı LaTeX şablonuna yerleştirilmesi
      ↓
İzole ve güvenli LaTeX derleme
      ↓
PDF görsel düzen ve içerik kontrolü
      ↓
Kullanıcı önizlemesi ve nihai onay
```

**Model çıktı sözleşmesi (özet örnek):**

```json
{
  "template_id": "ust_yazi_v1",
  "kurum_adi": {"deger": "Örnek Genel Müdürlük", "durum": "kaynaktan_alindi"},
  "tarih": {"deger": null, "durum": "kullanici_girdisi_gerekli"},
  "sayi": {"deger": null, "durum": "kullanici_girdisi_gerekli"},
  "konu": {"deger": "Yol bakım çalışması", "durum": "kaynaktan_alindi"},
  "muhatap": {"deger": "Örnek Bölge Müdürlüğüne", "durum": "yonlendirmeden_uretildi"},
  "paragraflar": ["...", "..."],
  "dayanaklar": [
    {"mevzuat": "...", "madde": "...", "kaynak": "...", "sayfa": 0}
  ],
  "eksik_alanlar": ["tarih", "sayi", "imzalayan"]
}
```

Model; evrak sayısı, tarih, makam, imzalayan, unvan veya mevzuat maddesi gibi kritik bilgileri tahmin ederek doldurmayacaktır. Kaynakta bulunmayan bilgiler `null` ve `kullanici_girdisi_gerekli` durumuyla işaretlenecek, taslakta `[DOLDURULACAK]` olarak gösterilecektir. Her mevzuat iddiası kaynak belge, madde ve mümkünse sayfa bilgisiyle izlenebilir olacaktır.

**LaTeX güvenlik kuralları:**

- Kullanıcı ve OCR metni doğrudan LaTeX'e eklenmeden önce `\`, `{`, `}`, `$`, `&`, `#`, `%`, `_`, `~` ve `^` karakterleri kaçış işleminden geçirilir.
- Modelin `\input`, `\include`, `\write18`, `\openin`, `\openout` ve `\usepackage` gibi dosya/sistem erişimi sağlayabilecek komutlar üretmesine izin verilmez.
- Derleme geçici bir çalışma klasöründe; ağ erişimi, shell escape ve dış dosya erişimi kapalı; zaman, bellek ve çıktı boyutu sınırlı olarak yürütülür.
- Şablon dosyaları çalışma sırasında model tarafından değiştirilemez; yalnızca onaylı alanlar doldurulur.

**Otomatik doğrulama:**

PDF derlenmeden önce JSON şema uygunluğu, zorunlu alanlar, kurum/birim uyumu, mevzuat atıfları ve kaynakta bulunmayan bilgi eklenip eklenmediği kontrol edilir. Derlemeden sonra sayfa taşması, kesilen metin, Türkçe karakterler, logo/başlık konumu, imza alanı, ekler ve dağıtım bölümü görsel olarak denetlenir. Kritik hata varsa belge yayımlanmaz; kullanıcıya düzeltme veya eksik bilgi talebi gösterilir.

Yeni bir evrak örneğinden model yardımıyla LaTeX şablonu üretmek ayrı bir **şablon geliştirme modu** olacaktır. Bu modun çıktısı insan tarafından karşılaştırılıp onaylanmadan günlük evrak üretim havuzuna alınmayacaktır. Böylece model yeni şablonların hazırlanmasını hızlandırırken üretim aşamasında resmî biçim bütünlüğü korunacaktır.

#### Süreç Durumu ve Kullanıcı Bilgilendirme Ajanı

Orkestratör, her evrak için kalıcı bir `process_state` kaydı tutacaktır. Her ajan göreve başladığında ve görevi bitirdiğinde bu kaydı güncelleyecek; Kullanıcı Bilgilendirme Ajanı teknik ajan günlüklerini göstermek yerine bu durumu sade Türkçe ile kullanıcıya açıklayacaktır. Böylece kullanıcı evrakın hangi aşamada olduğunu, hangi işlemlerin tamamlandığını, hangi bilgilerin eksik olduğunu ve sıradaki adımı görebilecektir.

```json
{
  "evrak_id": "EVR-00042",
  "genel_durum": "kullanici_onayi_bekleniyor",
  "mevcut_asama": "taslak_onizleme",
  "tamamlanan_adimlar": [
    "Evrak okundu ve sınıflandırıldı",
    "İlgili mevzuat maddeleri doğrulandı",
    "Cevap yazısı şablonu seçildi",
    "İlgili birim önerildi",
    "LaTeX taslağı oluşturuldu"
  ],
  "bekleyen_islemler": [
    "Evrak sayısının kullanıcı tarafından girilmesi",
    "Taslağın yetkili kullanıcı tarafından onaylanması"
  ],
  "eksik_bilgiler": ["evrak_sayisi"],
  "sonraki_adim": "Evrak sayısını girerek PDF taslağını onaylayınız.",
  "olasi_eylemler": ["bilgi_gir", "taslagi_duzenle", "onayla", "reddet"]
}
```

Önerilen süreç durumları şunlardır: `alindi`, `okunuyor`, `siniflandiriliyor`, `mevzuat_araniyor`, `kaynak_dogrulaniyor`, `eksik_bilgi_bekleniyor`, `yazi_turu_seciliyor`, `taslak_hazirlaniyor`, `uygunluk_kontrolunde`, `kullanici_onayi_bekleniyor`, `tamamlandi` ve `hata`. Bir ajan hata verdiğinde süreç kaybolmayacak; hata durumu, tekrar deneme seçeneği ve kullanıcıdan beklenen işlem açıkça gösterilecektir.

Kullanıcı arayüzünde en az bir ilerleme göstergesi, mevcut aşama, tamamlanan adımlar, eksik bilgiler, önerilen birim, seçilen yazı türü, kaynaklar ve birincil sonraki işlem düğmesi bulunacaktır. Süreç bilgilendirme başarısı demo sırasında ayrı bir gözlemlenebilir çıktı olarak gösterilecektir.

---

## 7. Demo Senaryosu Planı

1. Kurgu bir evrak (PDF/görsel) sisteme yüklenir.
2. Görev 1 çıktısı canlı gösterilir: tür, özet, eksik alan uyarısı, mevzuat önerisi.
3. Görev 2 çıktısı: resmi yazı taslağı + önerilen birim + (varsa) eksik bilgi talebi.
4. **Gerçek zamanlı çalıştırma tercih edilmeli** (şartname bunu avantaj sayıyor); kayıttan sunum seçilirse jürinin canlı çalıştırma talebine anında yanıt verilebilmeli.
5. **İnternet kesintisi yedek planı:** Yerel/offline çalışabilen bir fallback (örn. önceden çalıştırılmış kayıt + yerel model) hazır tutulmalı.

---

## 8. Test / Değerlendirme Planı

- En az 15-20 sentetik evrak içeren gizli bir test seti (gold-label: doğru tür, doğru birim, gerekli mevzuat).
- Ölçütler: sınıflandırma doğruluğu, yönlendirme başarımı (top-1/top-3), eksik bilgi tespit recall'ü, taslak formatının Yönetmelik kurallarına uyum yüzdesi.
- Bu sonuçlar teknik raporda ve sunumda **sayısal olarak** gösterilmeli (jüri "Uygulama" kriterinde performans ölçütlerini açıkça arıyor — madde 9).

**Uygulama durumu — 23 Ağustos 2026:** `data/synthetic_gold.json` içinde 48
tamamen kurgusal ve gold-label'lı evrak oluşturuldu. Bunların 40'ı standart, 8'i
anahtar kelimeyi doğrudan kullanmayan paraphrase challenge örneğidir. Tek komutla
tekrarlanabilir değerlendirme `karayol-agent evaluate` üzerinden çalışmaktadır.
Başlangıç kural tabanlı sürümün genel sonuçları: sınıflandırma `%83,33`, birim
yönlendirme top-1 `%85,42`, top-3 `%93,75`, eksik alan exact-match `%100`, şablon
seçimi `%93,75`, mevzuat `Recall@5` `%80,56` ve MRR `%80,56`. Standart 40 kayıtta
temel metrikler `%100`; challenge diliminde sınıflandırma `%0`, yönlendirme top-1
`%12,5` ve retrieval `Recall@5` `%12,5` olduğundan bu dilim embedding/LLM
entegrasyonu için dürüst başlangıç hedefi olarak korunacaktır. Bu sentetik baseline
gerçek saha başarımı iddiası değildir.

**Uygulama durumu — 24 Ağustos 2026, gerçek Jina/Qdrant ablation'ı:** Pinli
`jinaai/jina-embeddings-v3` modeli CPU'da `retrieval.passage` ve
`retrieval.query` görevleriyle çalıştırıldı; 1024 boyutlu vektörler yerel Qdrant
koleksiyonuna yazıldı. Aynı 48 kayıtlık dondurulmuş sette hibrit
BM25+dense+RRF yolu Recall@5'i `%80,56`dan `%100`e, MRR'ı `%80,56`dan `%90,97`ye
çıkardı. Paraphrase challenge Recall@5 `%12,5`ten `%100`e yükseldi. Bu deney
yalnız sentetik veridir ve kamu mevzuatı başarımı değildir.

Ölçümden sonra çok dilli Jina reranker ayrıca denendi. Recall@5 `%97,22`, MRR
`%88,06` değerine düştüğü ve CPU'da skor çağrısı başına ortalama yaklaşık 3,7
saniye eklediği için entegrasyon ablation olarak korunmuş, varsayılan akışta
etkinleştirilmemiştir. Bu karar hedef metrik yerine ölçülen sonuçla verilmiştir.

GraphRAG planının ilk dar dilimi de sentetik gold ilişkilerinden üretildi:
`MevzuatKurali`, `EvrakTuru`, `Birim`, `YaziSablonu` ve `ZorunluAlan`
düğümleri; `APPLIES_TO`, `ASSIGNED_TO`, `SUPPORTS_TEMPLATE` ve
`REQUIRES_FIELD` ilişkileri. Her kenar dayandığı gold kayıt kimliklerini taşır.
Builder yalnız sentetik işaretli girdiyi kabul eder; gerçek kamu grafı sekiz
kaynağın insan hukuk/kapsam onayı tamamlanana kadar boş kalır.

Sekiz çekirdek kamu kaynağı için ayrıca resmî kaynak/güncellik paketi üretildi:
dört dosya kesin eski, kılavuz yerel kopyası eksik ve yönetmelik kopyası kanonik
değildir. İki zayıf metin katmanlı PDF'nin Türkçe OCR aday metinleri üretilmiş
olsa da `approved_for_active_rag=false` korunmuştur. İnsan hukuk uzmanının
`approve`, `reject` veya `needs_replacement` kararı, gerçek aktif corpus ve kamu
Qdrant indeksi için hâlâ zorunlu dış kapıdır.

Yarışma demosu için bu public aktivasyon işi ertelenerek ayrı snapshot yolu
tamamlandı: 8 belge/2.603 parça, RTX 3050 `cuda:0`, Jina v3 1024D ve kalıcı
`competition_snapshot_chunks_v1`. İndeks yeniden açıldığında 2.603/2.603 kayıt
ve exact corpus fingerprint eşleşti; üç örnek dense sorgu ile tam hibrit ajan
akışı BM25+dense+RRF kanallarını fallback olmadan kullandı. Bu sonuç teknik
production-demo hazırlığıdır, güncel mevzuat veya hukuki doğruluk iddiası
değildir.

---

## 9. Zaman Çizelgesi (19-26 Ağustos)

| Gün | Tarih | Odak |
|---|---|---|
| 1 | 19 Ağu | Sentetik veri seti + kurum/birim listesi taslağı; mevzuat corpus'un chunk'lanması |
| 2 | 20 Ağu | Görev 1 iskeleti: metin çıkarımı + sınıflandırma + içerik analizi |
| 3 | 21 Ağu | Görev 1 tamamlama: mevzuat RAG + eksik bilgi tespiti + özet; ilk uçtan uca test |
| 4 | 22 Ağu | Görev 2 iskeleti: taslak oluşturma + format doğrulama katmanı |
| 5 | 23 Ağu | Görev 2 tamamlama: birim yönlendirme + eksik bilgi talebi; Tier 1 (Late Chunking/CRAG) varsa entegre |
| 6 | 24 Ağu | Uçtan uca entegrasyon, test seti üzerinde ölçüm, hata düzeltme |
| 7 | 25 Ağu | Demo senaryosu prova, sunum/rapor son hâli, GitHub + açık kaynak lisans + dokümantasyon |
| — | 26 Ağu | **Son teslim** |

---

## 10. Teslim ve Lisans Gereklilikleri

- [ ] Kod, veri seti ve dokümantasyon Türkiye Açık Kaynak Platformu GitHub'ında **açık kaynak lisansla** (MIT/Apache/GNU) paylaşılacak
- [ ] Kullanılan üçüncü taraf modeller açık ağırlıklı/uygun lisanslı değilse, model dosyası değil **erişim linki + lisans + sürüm bilgisi** dokümante edilecek
- [ ] Tüm belgeler Türkçe, kaynaklar bilimsel atıf kurallarına uygun
- [ ] Kullanılan veri setlerinin kaynağı ve kullanım hakları demo/dokümanda açıkça belirtilecek

---

## 11. Riskler ve Azaltım

| Risk | Etki | Azaltım |
|---|---|---|
| 7 günlük süre yetersizliği | Yüksek | Tier 0 dışına hiçbir şey harcanmaz; Tier 2 sadece raporda "gelecek vizyon" olarak yazılır |
| Yönetmelik PDF'lerinde Türkçe karakter/encoding kaybı | Orta | Görsel render + OCR doğrulama; bu bulgunun kendisi projenin OCR modülü tasarımına girdi olarak kullanılır |
| Gerçek kamu verisi kullanma riski (DETSİS vb.) | Yüksek (diskalifiye riski) | Tüm kurum/birim/evrak verisi sentetik; gerçek API'lerden veri çekilmez |
| Demo sırasında internet kesintisi | Orta | Yerel fallback + kayıttan yedek demo |
| Kapsam şişmesi (6 farklı RAG tekniği) | Yüksek | Tier disiplini; her yeni teknik önce Tier 0'ın çalıştığından sonra değerlendirilir |

---

## 12. Ekip Rolleri (doldurulacak)

Şartname madde 5: takımlar 4 kişiden oluşmalı, bir takım kaptanı zorunlu.

| Rol | Kişi | Sorumluluk |
|---|---|---|
| Takım Kaptanı | _ | Koordinasyon, sunum, teslim takibi |
| LLM/NLP Mühendisi | _ | Sınıflandırma, RAG, taslak üretimi |
| Backend/Orkestrasyon | _ | Pipeline, entegrasyon, demo altyapısı |
| Veri/Mevzuat Sorumlusu | _ | Sentetik veri seti, mevzuat corpus, format doğrulama kuralları |

---

*Bu plan, şartname (2026_TYDA_SARTNAME_Birinci_Senaryo) ve proje klasöründeki mevzuat kaynaklarına dayanılarak hazırlanmıştır. Yönetmelik ve kılavuz için makine OCR çıktısı ile örnek sayfa render kontrolleri tamamlanmıştır; format ölçüleri, imza/ek/dağıtım kuralları yine de yetkili insan tarafından sayfa bazında teyit edilmeden üretim kuralı veya aktif hukuk kanıtı sayılmamalıdır.*
