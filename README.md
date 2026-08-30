# Divan-ı Ajan

Divan-ı Ajan, **TEKNOFEST 2026 Yapay Zeka Dil Ajanları Yarışması** için
geliştirilen Türkçe kamu evrakı işleme ve resmî yazı hazırlama sistemidir.

## Takım

| Görev | Ad Soyad |
|---|---|
| Takım kaptanı | İsmail Özsoy |
| Geliştirici | Ahmet Koç |
| Geliştirici | Ceren Karabağ |
| Geliştirici | Sami Erdoğmuş |

## Problem

Kamu kurumlarına gelen evrakların okunması, sınıflandırılması, eksik
bilgilerinin belirlenmesi, ilgili mevzuatın bulunması, doğru birime
yönlendirilmesi ve resmî cevabın hazırlanması çok sayıda manuel adımdan oluşur.
Bu yapı işlem süresini uzatır, personel yükünü artırır ve farklı birimler
arasında standartlaşmayı zorlaştırır.

Divan-ı Ajan bu süreci tek bir denetlenebilir iş akışında birleştirir:

```text
Evrak alımı ve OCR
        -> sınıflandırma ve bilgi çıkarımı
        -> eksik alan denetimi
        -> mevzuat arama ve kaynak doğrulama
        -> birim ve resmî yazı türü seçimi
        -> taslak ve uygunluk kontrolü
        -> insan onayı ve PDF/LaTeX çıktı
```

Sistem kesin hukuki karar veren bir yapı değildir. Kaynakların güncellik ve
güven durumunu görünür tutan, kanıt yetersiz olduğunda çekimser kalan ve nihai
kararı kullanıcıya bırakan bir karar destek sistemidir.

## Proje mimarisi

### Katman 1 - Evrakı anlama

Katman 1 gelen belgeyi işler:

- TXT, MD, PDF ve görsel belgelerden metin çıkarır.
- Gerektiğinde OCR uygular ve sayfa/satır izlerini korur.
- Evrakın genel türünü ve operasyonel konusunu belirler.
- Gönderen, tarih, konu ve talep gibi önemli alanları çıkarır.
- Evrak türüne göre zorunlu alanları kontrol ederek eksikleri bildirir.
- Kısa ve yapılandırılmış bir özet üretir.

Başlıca dosyalar:

```text
src/karayol_agent/documents/extractor.py
src/karayol_agent/agents/classifier.py
src/karayol_agent/agents/analysis.py
src/karayol_agent/agents/llm_roles.py
src/karayol_agent/retrieval/requirement_rules.py
```

### Katman 2 - Kaynağa bağlı değerlendirme

Katman 2 evraktaki hukuki ve teknik meseleleri ayrı sorgulara dönüştürür.
UAB/karayolları korpusu ile geniş hukuk korpusunu ayrı kanallarda arar. Bulunan
hükmün gerçekten evraktaki iddia veya taleple ilişkili olup olmadığını kaynak
alıntısı ve belge kanıtıyla denetler.

Arama sonuçları doğrudan doğru kabul edilmez. Researcher adayları toplar,
Auditor kaynak ve ilişkiyi denetler, Adjudicator yalnız denetimden geçen
bulguları kullanıcıya sunar. Yeterli kanıt bulunamazsa sistem kaynak uydurmaz.

Başlıca dosyalar:

```text
src/karayol_agent/layer2_legal_reasoning.py
src/karayol_agent/agents/legislation.py
src/karayol_agent/retrieval/federated.py
src/karayol_agent/retrieval/hybrid.py
src/karayol_agent/retrieval/qdrant_store.py
```

### Katman 3 - Kurumsal işlem ve resmî yazı

Katman 3, doğrulanmış analiz ve kaynaklardan hareketle:

- uygun resmî yazı şablonunu seçer,
- sorumlu kurum birimini önerir,
- kullanıcıya cevap stratejileri sunar,
- seçilen hedef için resmî yazı taslağı oluşturur,
- taslağı resmî yazışma kurallarıyla denetler,
- insan onayından sonra LaTeX ve PDF çıktısı verir.

LLM doğrudan LaTeX üretmez. Yapılandırılmış alanları doldurur; güvenli kaçış ve
belge düzeni renderer tarafından uygulanır.

Başlıca dosyalar:

```text
src/karayol_agent/agents/llm_layer3.py
src/karayol_agent/agents/template_selection.py
src/karayol_agent/agents/routing.py
src/karayol_agent/agents/drafting.py
src/karayol_agent/agents/compliance.py
src/karayol_agent/latex/renderer.py
templates/
```

Tüm katmanlar `src/karayol_agent/orchestrator.py` tarafından yönetilir. REST
uçları `src/karayol_agent/backend/routes.py`, kullanıcı arayüzü ise `frontend/`
altındadır.

## Mevzuat chunklama mimarisi

Mevzuat metinleri sabit uzunlukta rastgele parçalara ayrılmaz. Hukuki yapı
korunarak **parent/leaf** biçiminde chunklanır.

### 1. Parent oluşturma

- Güvenilir `MADDE` başlığı bulunan her madde bir parent kaydıdır.
- Parent; belge, bölüm, madde, sayfa aralığı ve kaynak izini taşır.
- Madde yapısı güvenilir biçimde bulunamayan genelge, tablo, ek veya OCR
  belgelerinde sayfa tabanlı parent fallback uygulanır.

### 2. Leaf oluşturma

Arama parent üzerinde değil, daha hassas leaf parçalarında yapılır:

```text
Belge
  -> Bölüm
      -> Madde (parent)
          -> Fıkra (leaf)
              -> Bent (leaf)
```

- Madde önce fıkralara, ardından bentlere ayrılır.
- Doğal hukuki alt yapı yoksa madde metni leaf olarak korunur.
- Bir leaf 1.800 karakteri aşarsa cümle sınırlarında kontrollü olarak bölünür.
- Her leaf kendi `parent_id`, madde, fıkra, bent ve sayfa bilgisini taşır.
- Kimlikler belge ve içerikten deterministik hash ile üretilir.

### 3. Contextual embedding metni

Her leaf için mevzuata yorum eklemeden hiyerarşik bir bağlam oluşturulur:

```text
Belge Başlığı > Bölüm > Madde > Fıkra > Bent
Leaf'in özgün metni
```

Bu birleşim `embedding_text` olarak hem dense hem sparse aramada kullanılır.
Kullanıcıya alıntı yapılırken bağlamsal başlık değil, leaf'in özgün metni ve
kaynak izi gösterilir.

### 4. Vektör ve sparse indeks

- Dense embedding: `jinaai/jina-embeddings-v3`, 1024 boyut
- Belge görevi: `retrieval.passage`
- Sorgu görevi: `retrieval.query`
- Sparse kanal: Türkçe metin üzerinde BM25
- Vektör veritabanı: Qdrant
- Birleştirme: Reciprocal Rank Fusion (RRF)

Dense cosine skorları farklı korpuslar arasında doğrudan karşılaştırılmaz. Her
korpus kendi içinde sıralanır; kanal sıraları RRF ile birleştirilir.

### Üretilen v2 korpus

501 belgenin çıkarılmış/OCR metinleri kullanılarak:

- **6.234 parent**,
- **30.972 leaf**,
- **1.819 doğrulama bekleyen atıf adayı**,
- **1.278 sayfa-fallback leaf**

üretilmiştir. Atıf regex'i yalnız aday kenar çıkarır; doğrulanmamış bir atıf
otomatik olarak hukuki kanıt sayılmaz.

Chunklama ve GPU indeksleme kodu:

```text
kaggle/kaggle_legal_rag_v2.py
kaggle/README_KAGGLE_LEGAL_RAG_V2.md
scripts/integrate_uab_legal_rag_v2.py
```

## Çalıştırma

Proje **`release/three-layer-competition` branch'i** üzerinden
çalıştırılmalıdır. `main` ve diğer geliştirme branch'leri doğrudan demo/teslim
ortamı olarak kullanılmamalıdır.

```powershell
git clone https://github.com/ahmetkc58/Divani_Ajan.git
cd Divani_Ajan
git switch release/three-layer-competition
git pull --ff-only origin release/three-layer-competition
```

### Kurulum

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

### Backend

```powershell
$env:PYTHONPATH="src"
python -m uvicorn karayol_agent.api:app --host 127.0.0.1 --port 8010
```

### Frontend

Başka bir terminalde:

```powershell
python -m http.server 3000 --directory frontend
```

- Arayüz: `http://127.0.0.1:3000`
- API dokümantasyonu: `http://127.0.0.1:8010/docs`

LLM, Qdrant ve uzak korpus ayarları `.env.example` dosyasında bulunur.

## Ayrıntılı dokümantasyon

- Üç katmanlı akış ve REST sözleşmesi:
  [`docs/UC_KATMANLI_MIMARI_VE_ARAYUZ_ENTEGRASYONU.md`](docs/UC_KATMANLI_MIMARI_VE_ARAYUZ_ENTEGRASYONU.md)
