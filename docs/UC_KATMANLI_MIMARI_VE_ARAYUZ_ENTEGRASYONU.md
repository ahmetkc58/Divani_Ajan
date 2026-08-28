# Divan-ı Ajan: Üç Katmanlı Mimari ve Arayüz Entegrasyonu

Bu belge, `karayol-evrak-agent` uygulamasındaki üç katmanlı işlem mimarisini,
katmanlar arasındaki veri akışını ve bu backend üzerine yeni bir web arayüzü
yazılırken uyulması gereken REST sözleşmesini açıklar. Buradaki alan ve uç nokta
adları mevcut uygulama koduyla uyumludur.

## 1. Sistemin amacı

Sistem, kuruma gelen bir evrakı yalnızca özetleyen tek bir LLM çağrısı değildir.
Birbirinden farklı üç sorumluluğu ayrı katmanlarda işler:

1. **Katman 1 — Evrakı anlama ve şekli eksiklik denetimi:** Evrakın türünü kapalı
   altılı listeden seçer, önemli bilgileri çıkarır ve o evrak türünde bulunması
   gereken alanların mevcut olup olmadığını kaynaklara dayanarak denetler.
2. **Katman 2 — Kaynağa bağlı içerik değerlendirmesi:** Evraktaki iddia, talep,
   olay ve hukuki meseleleri ayırır; iki mevzuat korpusunda arar ve evrak içeriği
   ile bulunan hükümler arasındaki ilişkiyi değerlendirir.
3. **Katman 3 — Kurumsal işlem ve resmî cevap üretimi:** Şablon, sorumlu birim,
   cevap stratejisi ve gönderim hedefini belirler; kullanıcı seçimi sonrasında
   LaTeX/PDF resmî yazı taslağı üretir ve uygunluk kontrolü uygular.

Katmanlar birbirinin yerine geçmez. Örneğin Katman 1'de “imza alanı eksik”
tespiti yapılırken Katman 2'de “başvuranın talebi Madde 25 tarafından
destekleniyor/sınırlanıyor” gibi içerik ilişkileri kurulur. Katman 3 ise bu
sonuçları kurumsal cevaba dönüştürür.

## 2. Uçtan uca veri akışı

```text
TXT / MD / PDF / PNG / JPG / TIFF
              |
              v
Metin çıkarma + gerektiğinde OCR + satır/X-Y koordinatları
              |
              v
Katman 1: tür -> alanlar -> evrak şartları -> eksiklik bildirimi
              |
              v
Federated RAG: UAB/Karayolları korpusu + geniş dış hukuk korpusu
              |
              v
Katman 2: mesele ayrıştırma -> aşamalı arama -> Reason-in-Documents
          -> Auditor -> Adjudicator
              |
              v
Katman 3: şablon -> birim -> cevap stratejisi -> kullanıcı seçimi
          -> taslak doldurma -> resmî yazışma uygunluğu
              |
              v
LaTeX + PDF -> insan onayı -> tamamlandı
```

`EvrakOrchestrator`, bu akışın tek süreç yöneticisidir. Her işlem bir
`document_id` alır ve bütün ara/nihai sonuçlar `ProcessState` içinde saklanır.

## 3. Belge alımı, OCR ve koordinatlar

### 3.1 Desteklenen girdiler

- Düz metin: TXT ve MD
- Metin katmanlı veya taranmış PDF
- PNG, JPG/JPEG ve TIFF

Dosyanın uzantısına güvenilmez; içerik/magic-byte kontrolleri uygulanır. Boyut,
PDF sayfa sayısı, OCR piksel miktarı ve süre sınırları backend ayarlarıyla
kısıtlanır.

### 3.2 Yerleşim sözleşmesi

OCR veya metin çıkarımı sonucu `document_layout` alanında taşınır:

```json
{
  "page_count": 1,
  "coordinate_system": "normalized_page",
  "lines": [
    {
      "line_id": "page-1-line-8",
      "page": 1,
      "text": "Konu: K1 yetki belgesine kiralık kamyon eklenmesi",
      "bbox": {"x0": 0.08, "y0": 0.21, "x1": 0.82, "y1": 0.25},
      "confidence": 0.97,
      "source": "ocr"
    }
  ]
}
```

Koordinatlar sayfa genişliği/yüksekliğine göre `0..1` aralığında normalize
edilir. Düz metinde gerçek koordinat bulunamayacağı için
`coordinate_system="unavailable"` ve `bbox=null` olabilir.

LLM'ler koordinat üretmez veya değiştirmez. Yalnız güvenilir çıkarıcının verdiği
`line_id` değerlerine atıf yapar. İmza, tarih, başlık gibi konumsal kontrollerde
arayüz `document_evidence_ids` değerlerini `document_layout.lines` ile
eşleştirerek ilgili satırı vurgulayabilir.

## 4. Katman 1 — Evrakı anlama ve eksiklik denetimi

### 4.1 Görev

Katman 1'in çıktısı “bu evrak nedir ve biçimsel/operasyonel olarak neyi eksik?”
sorusuna cevap verir. Desteklenen kapalı evrak türleri şunlardır:

- `dilekce`
- `sikayet`
- `itiraz`
- `talep`
- `izin`
- `belge`

K1 yetki belgesi işlemi, yol bakım şikâyeti veya geçiş yolu ön izni gibi ayrıntı
evrak türü değildir; `operational_category` alanında tutulur.

### 4.2 LLM-1: Yapılandırılmış Anlama Ajanı

LLM-1 aşağıdaki girdileri kullanır:

- özgün evrak metni ve OCR satırları,
- deterministik sınıflandırma sonucu,
- kapalı evrak türü aday kataloğu,
- sınıflandırma için getirilen RAG kaynakları.

Kapalı JSON şemasıyla şunları önerir:

- `general_document_type` ve operasyonel kategori,
- evrak özeti,
- gönderen, adres, tarih, konu, talep gibi alanlar,
- önemli olay ve sonuçlar,
- kararında kullandığı kaynak kimlikleri.

Modelin önerisi doğrudan uygulanmaz. Türün izin verilen altılı listede olması,
kanıt kimlikleri, güven skoru ve sunucu kontrolleri geçildikten sonra kabul
edilir; aksi durumda deterministik sonuç korunur.

### 4.3 LLM-2: Karar/eksiklik ajanı

Bu ajan sınıflandırılmış evrak için seçilen incelenmiş gereksinim kurallarını,
doğrulanmış mevzuat parçalarını ve belge satırlarını karşılaştırır. Sonuç
`layer1_audit` alanındadır:

- `requirements`: her alan için `present`, `missing`, `ambiguous` veya
  `not_applicable`,
- `missing_fields`: kesin/şüpheli eksikliklerin listesi,
- `format_violations`: biçim ihlalleri,
- `important_results`: önemli neticeler,
- `accepted_reference_ids`: kullanılan dayanaklar,
- `validation_warnings` ve `requires_human_review`.

Her gereksinimde belge satırları (`document_evidence_ids`), mevzuat parçaları
(`legal_reference_ids`), mevzuat alıntısı ve ayrı skorlar bulunabilir. Fiziksel
ıslak imza, yalnızca metinde bir ad veya “İmza: ....” görülerek kesin biçimde
doğrulanmamalıdır.

Eksik alanlar gelen evrakın içine otomatik yazılmaz. Arayüz bunları **bildirim**
olarak gösterir. Katman 3'te kurumun üreteceği resmî yazının sayı, imzalayan ve
unvan gibi ayrı kurumsal alanları gerekiyorsa ayrıca girilebilir.

## 5. Retrieval ve iki vektör korpusu

Sistem iki farklı hukuk kaynağını federated retrieval ile birlikte kullanabilir:

1. **UAB/Karayolları korpusu:** Projeye özel, ulaşım ve karayolları alanında daha
   yoğun korpus.
2. **Geniş dış hukuk korpusu:** Uzak Qdrant'taki `legal_chunks_direct`
   koleksiyonu; daha geniş mevzuat kapsamı sağlar.

İki koleksiyonun embedding uzaylarının aynı olduğu varsayılmaz. Her korpus kendi
arama kanalında sıralanır; sonuçlar sıralama temelli RRF ile birleştirilir. Bu
nedenle iki veritabanının ham cosine skorlarını doğrudan birbirine eşitlemek
yanlıştır.

Arama hattında genel olarak şu bilgiler tutulur:

- `search_hits`: ham adaylar ve kanal katkıları,
- `retrieval_diagnostics`: dense/lexical aday sayıları, RRF/fallback durumu ve
  hata bilgisi,
- `verified_references`: kaynak izi ve sorgu ilişkisi kapısından geçen parçalar.

Uzak korpus geçici olarak erişilemezse `fallback_used=true` olur ve mümkünse UAB
sonuçlarıyla devam edilir. Arayüz bu durumu “hiç kaynak yok” diye gizlememeli,
teşhis uyarısı olarak göstermelidir.

## 6. Katman 2 — Evrak içeriğini mevzuatla bağlama

### 6.1 Katman 1'den farkı

Katman 2 eksik alan formu değildir. Aşağıdaki sorulara kaynakla cevap üretir:

- Evrakta hangi ayrı hukuki/teknik meseleler var?
- Her mesele için hangi hükümler bulundu?
- Evraktaki hangi cümle veya iddia bu hükümle ilişkilidir?
- Hüküm talebi destekliyor, sınırlıyor, usul belirliyor veya ilişki belirsiz mi?
- Pratik etkisi nedir?

### 6.2 Search-o1 benzeri sınırlı arama döngüsü

Researcher evrakı tek ve uzun bir sorgu olarak göndermek yerine meseleleri
ayrıştırır. En fazla `KARAYOL_LAYER2_MAX_SEARCH_ROUNDS` tur çalışır; yapılandırma
1–4 aralığını kabul eder. Her turda:

1. en az bir genel/usul meselesi ve farklı özel/teknik meseleler belirlenir,
2. `search_reliable_legislation`, `search_curated_rules` veya belge satırı aracı
   çağrılır,
3. sonuç yetersizse mevzuat terminolojisine yakın yeni sorgu üretilir,
4. yeterli ve farklı dayanaklar oluştuğunda erken durulur.

Terim genişletme bir sonucu hardcode etmek değildir. Örneğin belgede “kiralık
taşıt” geçerken mevzuatta “sözleşmeli taşıt” kullanılıyorsa arama sorgusuna iki
ifade de eklenir. Hangi maddenin uygulanacağına yine retrieval ve sonraki ajanlar
karar verir.

Aynı maddenin iki korpustaki kopyaları, jüriye daha fazla kaynak göstermek için
iki ayrı dayanak sayılmaz. Belge/madde düzeyinde tekrarlar birleştirilir; hedef
3–4 **farklı ve gerçekten ilgili** dayanak bulmaktır.

### 6.3 Reason-in-Documents

Bu aşama retrieval'dan ayrıdır. Retrieval “hangi parçalar aday?” sorusunu,
Reason-in-Documents ise “aday parçadaki hüküm evraktaki hangi ifadeyle nasıl
ilişkili?” sorusunu cevaplar. Her aday için:

- birebir kaynak alıntısı,
- evrak `line_id` değerleri,
- önerilen içerik ilişkisi,
- güven ve kaynak kimliği

kapalı JSON şemasında üretilir. Model önbilgisi kaynak yerine kullanılamaz.

### 6.4 Auditor

Auditor üçüncü bir arama motoru değildir. Reason-in-Documents çıktısını şu
açılardan denetler:

- alıntı gerçekten getirilen kaynakta var mı,
- belirtilen evrak satırı gerçekten belgede var mı,
- evrak–hüküm ilişkisi doğrudan mı, belirsiz mi,
- genel, sektörel ve teknik meselelerin her biri ayrı değerlendirilmiş mi.

Auditor'ın reddi, her zaman retrieval'ın alakasız olduğu anlamına gelmez. Kaynak
yakın bir konuda olsa bile iddia edilen hukuki bağ yeterince açık kurulmamışsa
reddedebilir veya `unclear` olarak işaretleyebilir.

### 6.5 Adjudicator

Adjudicator yalnız Auditor'dan geçen kayıtları nihai, kullanıcıya okunabilir
bulgulara dönüştürür. Yeni kaynak veya yeni hukuk bilgisi ekleyemez. Sentez
üretemese bile sunucunun birebir alıntı ve satır kapılarından geçmiş Auditor
bulguları korunabilir.

`layer2_assessment` içinde arayüz için önemli alanlar şunlardır:

- `status`, `summary`, `requires_human_review`,
- `findings`,
- `accepted_reference_ids`,
- `validation_warnings`,
- `tool_trace` ve `agent_trace`,
- `source_only_policy_applied` ve kullanılan model.

Bir bulgu; evraktaki iddia, kaynak alıntısı, hukuki bağlam açıklaması, pratik
etki, belge satırları, kaynak kimliği ve güven skoruyla birlikte gösterilmelidir.
Bulgu yoksa arayüz bunu başarı gibi göstermemeli; “yeterli kaynak/bağ
kurulamadığı için çekimser” açıklaması sunmalıdır.

## 7. Katman 3 — Kurumsal işlem ve resmî taslak

Katman 3, mümkünse yalnız Katman 2'nin kabul ettiği kaynakları kullanır. Katman 2
bir kaynak kümesi kabul etmediyse doğrulanmış genel kaynak kümesine kontrollü
fallback uygulanır.

### 7.1 LLM3 — Şablon Seçim Ajanı

Kapalı şablon kataloğundan uygun `template_id` değerini seçer. Katalog dışı
şablon uyduramaz. Deterministik seçimi ancak güven ve insan-inceleme kapılarını
geçerse değiştirebilir.

### 7.2 LLM5 — Birim Yönlendirme Ajanı

Kapalı organizasyon kataloğunda üstten alta gezinerek sorumlu birimi seçer.
Katalog dışı kurum/birim üretemez. `routing` alanında birim, hiyerarşi,
alternatifler, skor farkı, kanıt ve `requires_human_review` bulunur.

### 7.3 LLM6 — Yanıt Stratejisi Ajanı

Doğrulanmış kaynaklardan 2–4 farklı cevap yaklaşımı üretir. Her seçenek
`reference_ids` ile dayanaklarını taşır. Kaynak bulunmuyorsa strateji uydurmak
yerine çekimser kalır.

Akış bu noktada `yanit_stratejisi_bekleniyor` durumuna geçebilir. Kullanıcı:

- sunulan stratejilerden birini,
- serbest bir kurumsal cevap talimatını,
- gönderim hedefi olarak `citizen`, `internal_unit` veya `both`

seçer.

### 7.4 LLM4 — Şablon Doldurma Ajanı

Seçilen şablonun düz metin alanlarını doldurur. LLM doğrudan LaTeX kodu yazmaz;
konu, paragraflar ve izin verilen kapanış gibi yapılandırılmış alanları üretir.
Güvenli LaTeX kaçışını ve belge düzenini renderer uygular. Böylece modelin bozuk
veya zararlı LaTeX üretmesi engellenir.

Taslakta ajan adı, şablon türü, retrieval skoru veya sistem içi doğrulama notu
yer almaz; çıktı doğrudan muhataba gönderilecek resmî yazı metni olarak
hazırlanır.

### 7.5 Uygunluk, çıktı ve onay

Resmî Yazışmalarda Uygulanacak Usul ve Esaslar Hakkında Yönetmelik temelindeki
deterministik kontroller sayı, tarih, konu, muhatap, ilgi, kapanış, imza, ek,
dağıtım ve üstveri alanlarını denetler. Sonuç `compliance` içindedir.

Her gönderim hedefi için `layer3_outputs` kaydı oluşur:

```text
target = citizen       -> vatandaşa cevap
target = internal_unit -> alt birime üst yazı/havale
target = both          -> iki ayrı Layer3DraftOutput
```

Her çıktı `draft`, `artifact` ve `compliance` taşır. LaTeX her zaman temel
artifact'tır; sistemde XeLaTeX, pdfLaTeX veya Tectonic varsa PDF derlenir, yoksa
taşınabilir PDF fallback'i kullanılabilir. Uygunluk kapısını geçmeyen veya
zorunlu kurumsal alanı eksik taslak onaylanamaz.

## 8. Süreç durumları ve canlı ilerleme

Yeni bir arayüz uzun senkron isteği bekletmek yerine `/start` uçlarını ve polling
kullanmalıdır. Temel durum sırası şöyledir:

| Durum | Arayüzde anlamı |
|---|---|
| `alindi` | Evrak ve süreç kimliği oluşturuldu |
| `okunuyor` | Metin/OCR çıktısı okunuyor |
| `siniflandiriliyor` | Katman 1 tür ve alan analizi |
| `mevzuat_araniyor` | RAG kaynak araması |
| `kaynak_dogrulaniyor` | Kaynak kapıları ve Katman 2 ajanları |
| `yazi_turu_seciliyor` | Katman 3 şablon seçimi |
| `birim_yonlendiriliyor` | Katman 3 birim seçimi |
| `yanit_stratejisi_bekleniyor` | Kullanıcı seçimi zorunlu |
| `taslak_hazirlaniyor` | LLM4 ve renderer çalışıyor |
| `uygunluk_kontrolunde` | Resmî yazışma denetimi |
| `kullanici_onayi_bekleniyor` | Taslak hazır, insan onayı bekliyor |
| `tamamlandi` | Onaylandı ve süreç kapandı |
| `hata` | İşlem başarısız; `events` ve `next_step` gösterilmeli |

Backend her aşamada `events` listesine `status`, `agent`, `message` ve
`timestamp` ekler. Bu kayıtlar canlı ilerleme göstermek içindir. Arayüz son olayı
veya yeni eklenen olayları zaman çizelgesine eklemeli; LLM çağrısı sürerken
sayfayı donmuş göstermemelidir.

Bu sistem gizli chain-of-thought yayımlamaz. `llm_trace.steps`, `agent_trace`,
`decision_summary`, `decision_checks`, `findings`, skorlar ve kaynak kimlikleri
denetlenebilir karar izidir; bunlar kullanıcıya gösterilebilir.

## 9. REST API ile arayüz bağlantısı

### 9.1 Başlamadan önce

Arayüz önce şu uçları kontrol etmelidir:

```http
GET /api/v1/system/health
GET /api/v1/system/readiness
```

`health` servis, retrieval modu, korpus ve LLM/Katman 2–3 yapılandırmasını
gösterir. `readiness` 503 döndürüyorsa yeni işlem başlatılmamalı; dönen bileşen
hatası kullanıcıya sade biçimde açıklanmalıdır.

### 9.2 Metin işlemini asenkron başlatma

```http
POST /api/v1/processes/text/start
Content-Type: application/json

{
  "text": "Evrak metni...",
  "source_name": "basvuru.txt",
  "compile_pdf": true
}
```

Yanıt `202 Accepted`:

```json
{
  "document_id": "EVR-20260828-ABCDEF12",
  "status": "alindi",
  "poll_url": "/api/v1/processes/EVR-20260828-ABCDEF12"
}
```

### 9.3 Dosya işlemini asenkron başlatma

```http
POST /api/v1/processes/file/start?compile_pdf=true
Content-Type: multipart/form-data

file=<binary>
```

Arayüz kabul edilen dosya tipini ve boyut sınırını yüklemeden önce açıklamalı,
ancak backend kontrollerini hiçbir zaman istemciye bırakmamalıdır.

### 9.4 Polling

```http
GET /api/v1/processes/{document_id}
```

Önerilen istemci davranışı:

- aktif durumda yaklaşık 1–2 saniyede bir sorgula,
- `updated_at` veya `events.length` değişince görünümü güncelle,
- sekme arka plandaysa aralığı artır,
- `yanit_stratejisi_bekleniyor`, `kullanici_onayi_bekleniyor`, `tamamlandi` veya
  `hata` durumlarında sürekli polling'i durdur,
- geçici ağ hatasında sınırlı exponential backoff uygula,
- aynı işlemi yeniden POST ederek çift süreç üretme.

### 9.5 Yanıt stratejisi ve gönderim hedefi

Arayüz `response_strategy_options` değerlerini radyo kartları olarak göstermeli;
ayrıca serbest metin seçeneği sunabilir:

```http
POST /api/v1/processes/{document_id}/response-strategy
Content-Type: application/json

{
  "option_id": "source_based_acceptance",
  "custom_text": null,
  "delivery_target": "both",
  "compile_pdf": true
}
```

Serbest cevapta `option_id="custom"` ve dolu `custom_text` gönderilir. Gönderim
hedefi seçimi arayüzde görünür olmalıdır; sistemin sessizce vatandaşı veya alt
birimi seçmesine izin verilmemelidir.

### 9.6 Kurumsal taslak alanları

Mevcut `/information` ucu gelen evraktaki eksikleri doldurmak için
kullanılmamalıdır. Yalnız kurumun üreteceği taslağa ait izin verilen alanlar
(örneğin sayı, imzalayan, imzalayan unvanı ve resmî yazı üstverisi) gerektiğinde
gönderilmelidir:

```http
POST /api/v1/processes/{document_id}/information
Content-Type: application/json

{
  "fields": {
    "sayi": "E-12345678-...",
    "imzalayan": "Yetkili Adı",
    "unvan": "Şube Müdürü"
  },
  "compile_pdf": true
}
```

Backend bilinmeyen alanları 422 ile reddeder. Arayüz alan listesini kendi içinde
çoğaltmak yerine mümkünse OpenAPI şeması ve backend hata ayrıntısını esas
almalıdır.

### 9.7 Onay

```http
POST /api/v1/processes/{document_id}/approval
Content-Type: application/json

{"approved_by": "Yetkili kullanıcı"}
```

Onay düğmesi yalnız taslak hazır, strateji seçilmiş, zorunlu kurumsal alanlar
tam ve `compliance.passed=true` olduğunda etkinleştirilmelidir. Backend yine de
bu koşulları tekrar doğrular.

### 9.8 Artifact indirme

Varsayılan çıktı:

```http
GET /api/v1/processes/{document_id}/artifacts/tex
GET /api/v1/processes/{document_id}/artifacts/pdf
```

Katman 3 hedefe özel çıktı:

```http
GET /api/v1/processes/{document_id}/artifacts/citizen/tex
GET /api/v1/processes/{document_id}/artifacts/citizen/pdf
GET /api/v1/processes/{document_id}/artifacts/internal_unit/tex
GET /api/v1/processes/{document_id}/artifacts/internal_unit/pdf
```

Arayüz yerel `tex_path`/`pdf_path` dosya yollarını kullanmamalı;
`tex_download_url` ve `pdf_download_url` veya yukarıdaki REST yollarını
kullanmalıdır. PDF URL'si `null` ise “PDF hazırlanamadı” gösterilmeli, bozuk bir
indirme bağlantısı üretilmemelidir.

## 10. Yeni arayüz hangi veriyi nerede göstermeli?

Önerilen ekran düzeni:

### Genel

- `document_id`, `status`, `next_step`
- `analysis.general_document_type`, `operational_category`, `summary`
- `routing` ve insan inceleme durumu

### Alanlar / Katman 1

- çıkarılan alan değeri, durumu ve kaynağı
- `layer1_audit.requirements`
- eksik ve belirsiz alanlar ayrı rozetlerle
- satır kimliğine tıklanınca belge önizlemesinde koordinat vurgusu

### Kaynaklar

- başlık, madde, alıntı ve korpus
- retrieval skoru ile hukuki bağ/güven skorunu birbirine karıştırmadan
- kanal katkıları ve fallback uyarısı tercihen gelişmiş ayrıntıda

### Katman 2

- `summary` ve çekimserlik/insan inceleme bilgisi
- her bulgu için evraktaki iddia, kaynak alıntısı, ilişki, pratik etki, satır ve
  kaynak kimliği
- arama turu/araç izi ve ajan başarı/başarısızlıkları
- kullanıcıya ham chain-of-thought değil karar özeti ve doğrulama kapıları

### Strateji ve hedef seçimi

- 2–4 cevap stratejisi ve her birinin kaynakları
- “vatandaşa”, “alt birime” veya “ikisine de” seçimi
- serbest kurumsal talimat seçeneği

### Taslak

- `layer3_outputs` içindeki her hedefi ayrı sekme/kart olarak
- resmî yazının kullanıcıya gönderilecek görünümü
- uygunluk skoru, hata ve uyarılar belge metninin dışında
- LaTeX ve PDF indirme düğmeleri
- insan onayı düğmesi

### Akış

- `events` zaman çizelgesi
- `llm_trace.steps` ajan çağrıları
- sağlayıcı/model, ağ çağrısı, maskeleme ve hata kodu
- kararın uygulanıp uygulanmadığı ve kısa gerekçe

### Yapılacak: Jüri Gösterim Modu / Ajan Karar Günlüğü

Yeni arayüze açılıp kapatılabilen bir **Jüri Gösterim Modu** eklenmelidir. Bu
ekran işlem devam ederken aşağıdaki denetlenebilir bilgileri canlı göstermelidir:

- çalışan ajanın adı, görevi ve mevcut aşaması,
- ele alınan hukuki veya teknik mesele,
- arama sorguları, arama turu ve iki korpustan bulunan kaynak sayıları,
- kullanılan kaynak kimlikleri ve kısa alıntılar,
- adayların kabul/red durumu ve kısa doğrulama gerekçesi,
- güven, kaynak desteği ve belge eşleşme skorları,
- kullanılan belge satırları ve varsa X/Y koordinat vurgusu,
- yapılandırılmış karar özeti ve sonraki işlem adımı.

Görünüm `events`, `layer2_assessment.tool_trace`, `agent_trace`,
`llm_trace.steps`, `decision_summary`, `decision_checks` ve `findings`
alanlarından beslenmelidir. Ham chain-of-thought/gizli düşünce zinciri
gösterilmemeli veya loglanmamalıdır. Bunun yerine kaynaklı ve doğrulanabilir
karar izi sunulmalıdır. Arayüz gerçekleşmemiş ajan adımlarını canlandırmamalı,
skorları veya kaynak sayısını yapay biçimde artırmamalı ve aynı maddenin iki
korpustaki kopyasını iki ayrı dayanak gibi göstermemelidir.

## 11. Frontend güvenliği ve sağlamlık kuralları

1. Backend'den gelen evrak metni, LLM özeti, kaynak alıntısı ve hata mesajlarını
   güvenilmeyen metin kabul edin; HTML escape uygulayın, `innerHTML` ile doğrudan
   basmayın.
2. API anahtarlarını frontend'e, JavaScript bundle'a veya tarayıcı storage'a
   koymayın. Evren LLM/Qdrant anahtarları yalnız backend `.env` dosyasındadır.
3. Artifact bağlantılarında yalnız beklenen `/api/v1/processes/.../artifacts/...`
   yollarını kabul edin; sunucunun yerel dosya yolunu açmayın.
4. CORS için frontend origin'i hem `frontend/config.js` içinde backend adresi
   olarak hem backend `KARAYOL_CORS_ALLOWED_ORIGINS` listesinde açıkça tanımlayın.
   Joker origin kullanmayın.
5. `422`, `413`, `415`, `404`, `503` ve ağ zaman aşımını ayrı kullanıcı
   mesajlarına dönüştürün. Hata olduğunda daha önce alınmış `document_id` ve
   olayları kaybetmeyin.
6. Skorları yüzdeye çevirirken alanın gerçekten `0..1` sözleşmesinde olduğunu
   kontrol edin. RRF, cosine, relevance ve LLM güven skorlarını aynı ölçü gibi
   sunmayın.
7. `requires_human_review=true` sonucunu yeşil “otomatik onay” görünümünde
   göstermeyin.
8. Katman 2'de bulgu sayısını yapay olarak artırmayın; aynı maddenin farklı
   koleksiyon kopyalarını tek hukuki dayanak olarak gösterin.
9. Tamamlanmış süreç değiştirilemez. Revizyon gerekiyorsa yeni süreç başlatın.
10. `raw_text` ve OCR satırları kişisel veri içerebilir; production arayüzünde
    erişim kontrolü, ekran loglarında maskeleme ve kısa saklama politikası
    uygulanmalıdır.

## 12. Odak manuel test evrakları

Projede iki ayrı sentetik TXT test seti vardır. Bu dosyalar mevzuat korpusuna
eklenmez; kullanıcıdan gelen evrakı ve beklenen sistem davranışını temsil eder.
Adlar, şirketler, adresler, numaralar ve olaylar gerçek değildir.

### 12.1 Katman 1: altı tür ve bilinçli eksiklik testleri

Konum: `data/manual_tests/six_document_types/`

Bu set, LLM-1'in yalnız kapalı altı evrak türünden birini seçmesini ve LLM-2'nin
gelen evraktaki eksikleri ilgili gereksinim kurallarına göre bildirmesini sınar:

| Dosya | Beklenen tür | Odak ve bilinçli eksiklik |
|---|---|---|
| `01_dilekce_eksik.txt` | `dilekce` | Erişilebilirlik gözlemi; açık talep, adres ve imza eksikliği |
| `02_sikayet_eksik.txt` | `sikayet` | Gece yol çalışması/gürültü; gönderen, adres ve imza eksikliği |
| `03_itiraz_eksik.txt` | `itiraz` | Geçiş ihlali/ceza; beklenen sonuç ve imza eksikliği |
| `04_talep_eksik.txt` | `talep` | Levha/yol çizgisi yenileme; adres ve imza eksikliği |
| `05_izin_eksik.txt` | `izin` | Geçiş yolu ön izni; sahiplik belgesi ve vaziyet planı eksikliği, koşullu belediye yazısı |
| `06_belge_eksik.txt` | `belge` | Bilgi-belge başvurusu; imza ve yeterince açık talep eksikliği |

Kesin beklenen davranışlar ve kural kimlikleri
`data/manual_tests/six_document_types/BEKLENEN_SONUCLAR.md` dosyasındadır. Bu
testlerde amaç fazla mevzuat bulmak değil; doğru türü ve gerçekten eksik alanları
bulmaktır. Gelen TXT'nin eksik kısmı otomatik tamamlanmamalı, yalnız kullanıcıya
bildirilmelidir.

### 12.2 Katman 2: çift korpus ve çok mesele testleri

Konum: `data/manual_tests/six_document_types_layer2/`

Bu evraklar özellikle Katman 2 için hazırlanmıştır. Her biri doğal kullanıcı
diliyle yazılmış 3–4 bağımsız genel, sektörel veya teknik mesele içerir. Hedef,
yaklaşık 30 bin parçalık UAB/Karayolları korpusu ile yaklaşık 300 bin parçalık
genel mevzuat korpusunun birlikte aranmasıdır.

| Dosya | Tür | Aranması beklenen mesele aileleri |
|---|---|---|
| `01_dilekce_k1_filo_islemleri.txt` | `dilekce` | K1, kiralık/sözleşmeli ve özmal taşıt, taşıt kartı, araç muayenesi, takograf, SRC4 ve psikoteknik |
| `02_sikayet_sehirlerarasi_otobus.txt` | `sikayet` | Bilet/yolcu listesi/terminal, sürüş-dinlenme, takograf, emniyet kemeri ve araç muayenesi |
| `03_itiraz_arac_muayene_agir_kusur.txt` | `itiraz` | Muayene usulü, fren/far ağır kusuru, teknik şartlar ve takograf mührü |
| `04_talep_tehlikeli_madde_filo_islemleri.txt` | `talep` | Tehlikeli madde taşımacılığı, tanker teknik incelemesi, TMGD, SRC5, ekipman ve işaretleme |
| `05_izin_ubak_soguk_zincir.txt` | `izin` | UBAK/geçiş belgesi, C2, soğuk zincir ekipmanı, sürücü yeterliliği ve takograf |
| `06_belge_yol_kenari_denetim_kayitlari.txt` | `belge` | Bilgi edinme, yetki belgesi/taşıt kartı denetimi, takograf, ceza, ağırlık ölçümü ve muayene kaydı |

Özellikle açık olan `01_dilekce_k1_filo_islemleri.txt`, sorgu ayrıştırma için ana
kontrol evraklarından biridir. Tek bir genel “K1 başvurusu” sorgusu yeterli
değildir. Sistem en az şu meseleleri ayrı aramalıdır:

1. K1 belgesinin taşıt ve kapasite şartları,
2. kiralık ifadesinin mevzuattaki `sözleşmeli taşıt` karşılığı ve özmal sınırı,
3. taşıtın yetki belgesi eki taşıt belgesine kaydı ve taşıt kartı,
4. muayene, takograf, SRC4 ve psikoteknik teknik koşulları.

Başarı hedefi mümkünse 3–4 farklı ve gerçekten uygulanabilir hükümdür. Bu sayı
zorla doldurulmaz: her bulgu evraktaki bir iddia/taleple, birebir kaynak
alıntısıyla ve belge satırıyla bağlanmalıdır. Aynı maddenin iki korpustaki
kopyaları tek dayanak sayılır. Sonuçlarda hem `leaf-*` hem `MEV-*` kimliklerinin
bulunması iki korpusun katkısını gösterir; ancak alakasız kaynak sırf iki taraf da
görünsün diye kabul edilmez.

#### Mevcut Katman 2 durumu ve gözlenen sorun

K1 filo dilekçesiyle yapılan manuel çalıştırmalarda iki korpus da aranmış ve
birden fazla aday parça bulunmuştur. Ancak sonuçların önemli bir bölümü aynı
`Karayolu Taşıma Yönetmeliği Madde 14` hükmünün iki korpustaki kopyaları olduğu
için tekrar birleştirme sonrasında arayüzde tek farklı dayanak kalmıştır. Bu,
veritabanlarının bağlı olmadığı anlamına gelmez; iki kaydın tek hukuki hüküm
olması nedeniyle doğru biçimde tekilleştirilmesidir.

İkinci sorun terim farkıdır: test evrakı `kiralık taşıt` derken ilgili mevzuat
`sözleşmeli taşıt` ifadesini kullanmaktadır. Bu nedenle arama başlangıçta Madde
14 çevresinde yoğunlaşmış; özmal/sözleşmeli kayıt, sözleşme koşulları ve taşıt
kartıyla ilgili farklı hükümler üst sıralara yeterince taşınamamıştır. Katman 2
aramasına mesele ayrıştırma, `kiralık -> sözleşmeli taşıt` terminoloji
genişletmesi, daha geniş aday kapsaması ve her adayın Reason-in-Documents ile
Auditor'a taşınması eklenmiştir.

Beklenen davranış, sırf jüri görünümü için bulgu sayısını artırmak değildir.
Arama farklı maddeleri aday göstermeli; Reason-in-Documents evrak–hüküm bağını
kurmalı; Auditor yalnız birebir alıntısı ve belge satırı doğrulananları kabul
etmelidir. Sonuç hâlâ tek maddeyse arayüz bunu açıkça göstermeli, aynı hükmün
kopyalarını birden fazla dayanak gibi sunmamalıdır.

#### Neden jüri demosunda birden fazla farklı mevzuat maddesi hedefleniyor?

Jüri sunumunda 3–4 farklı dayanak göstermeye çalışmamızın amacı yalnız ekranı
daha kalabalık veya sonucu yapay biçimde daha başarılı göstermeye çalışmak
değildir. Göstermek istediğimiz teknik kabiliyet şudur: sistem tek bir benzer
paragraf bulup özetlemek yerine, aynı evrak içindeki birden fazla bağımsız
hukuki ve teknik meseleyi fark edebiliyor; her mesele için iki farklı korpusta
araştırma yapabiliyor ve sonuçları tek bir kaynaklı değerlendirmede
birleştirebiliyor.

Tek dayanaklı bir çıktı jüri açısından RAG sisteminin basit bir semantik arama
kutusu gibi görünmesine neden olabilir. Bir genel usul hükmü ile farklı
sektörel/teknik hükümleri birlikte ve doğru şekilde göstermek ise şu özellikleri
görünür kılar:

- evrakın tek konu etiketi yerine alt meselelere ayrıştırılması,
- yaklaşık 30 bin parçalık sektörel korpus ile yaklaşık 300 bin parçalık genel
  mevzuat korpusunun birlikte kullanılması,
- genel başvuru usulü ile özel taşıma/araç/sürücü kurallarının ayrılması,
- her iddia için farklı kaynak ve belge satırı bağının kurulması,
- tekrarların elenmesi ve yalnız gerçekten farklı hükümlerin korunması,
- LLM önerilerinin Auditor ve sunucu doğrulama kapılarından geçirilmesi.

Dolayısıyla jüriye yönelik “şov” unsuru kaynak sayısını sahte biçimde artırmak
değil, sistemin araştırma derinliğini canlı ve denetlenebilir biçimde görünür
kılmaktır. Gerçek evrak yalnız bir uygulanabilir hüküm içeriyorsa sistem yine tek
hüküm göstermeli veya çekimser kalmalıdır.

#### Teknik olarak neden tek maddeye düşüyordu ve nasıl çoğul dayanak aranıyor?

İlk sürümde evrakın tamamından üretilen uzun sorgular birbirine çok benziyordu.
K1, taşıt ve taşıt kartı ifadeleri bütün sorgularda tekrarlandığı için retrieval
her turda aynı yüksek benzerlikli Madde 14 parçalarını üst sıraya getiriyordu.
Üstelik aynı hüküm hem `leaf-*` hem `MEV-*` kaydı olarak iki korpusta bulunduğu
için ham aday sayısı yüksek görünse de belge/madde tekilleştirmesinden sonra tek
benzersiz hukuki dayanak kalıyordu.

Geliştirilmiş akışta çoğul dayanak şu şekilde aranır:

1. **Mesele çıkarımı:** Evrak; genel başvuru usulü, yetki belgesi koşulu,
   özmal/sözleşmeli taşıt kaydı, taşıt kartı ve teknik sürücü/araç şartları gibi
   bağımsız araştırma meselelerine ayrılır.
2. **Farklı sorgular:** Her mesele kendi çekirdek terimleriyle aranır. Bir
   sorgunun diğer meselelerin baskın terimlerini sürekli tekrar etmemesine dikkat
   edilir.
3. **Mevzuat terminolojisi genişletmesi:** Kullanıcı dilindeki `kiralık taşıt`
   gibi ifadeler, sonucu hardcode etmeden `sözleşmeli taşıt` gibi mevzuattaki
   karşılıklarıyla genişletilir.
4. **Çift korpus araması:** Her sorgu sektörel UAB/Karayolları ve geniş genel
   hukuk korpusuna gönderilir. Ham vektör skorları karıştırılmaz; korpus içi
   sıralamalar RRF ile birleştirilir.
5. **Çeşitlilik ve tekilleştirme:** Aynı belge/madde/kaynak alıntısının kopyaları
   birleştirilir. Kalan adaylarda farklı hukuki mesele ve farklı madde kapsamı
   korunmaya çalışılır.
6. **Reason-in-Documents:** Her aday için evraktaki iddia, belge satırı, birebir
   mevzuat alıntısı ve önerilen hukuki ilişki ayrı kayıt hâline getirilir.
7. **Auditor kapısı:** Yalnız kelime benzerliği olan veya alıntısı/satırı
   doğrulanamayan adaylar reddedilir. Bir mesele için geçerli hüküm yoksa o
   bölüm boş kalabilir.
8. **Adjudicator sentezi:** Kabul edilen farklı hükümler, yeni bilgi eklenmeden
   nihai içerik değerlendirmesine dönüştürülür.

K1 filo örneğinde amaç; mümkünse K1'in genel koşulu, özmal/sözleşmeli taşıt
kaydı, taşıt kartı ve muayene/takograf/SRC4 gibi teknik koşullardan farklı
dayanaklar bulmaktır. Ancak bunların yalnız evrakta geçen iddia veya taleple
doğrudan ilişkili olanları nihai ekrana taşınır. Böylece “3–4 madde hedefi” bir
kabul kotası değil, retrieval kapsamı ve jüri demosu için ölçülebilir bir
araştırma hedefidir.

Ayrıntılı beklentiler
`data/manual_tests/six_document_types_layer2/BEKLENEN_SONUCLAR.md`
dosyasındadır. Bunlar kelimesi kelimesine beklenen LLM cevapları değil,
değerlendirme sözleşmesidir.

### 12.3 Manuel arayüz test akışı

1. Seçilen TXT içeriğini `/api/v1/processes/text/start` ucuna gönderin.
2. `events` ve Jüri Gösterim Modu üzerinden sorguların farklı meseleleri kapsayıp
   kapsamadığını izleyin.
3. Katman 1 ekranında türü ve eksiklikleri beklenen sonuç dosyasıyla karşılaştırın.
4. Katman 2 ekranında her bulgunun farklı madde, birebir alıntı ve evrak satırı
   taşıdığını kontrol edin.
5. `retrieval_diagnostics` ve araç izinde iki korpusun durumunu kontrol edin.
6. Katman 3'te cevap stratejisi ve gönderim hedefini seçip hedefe özel LaTeX/PDF
   çıktısını inceleyin.

## 13. LaTeX resmî yazı taslakları

Katman 3'ün kapalı şablon kataloğu `templates/catalog.json` dosyasındadır.
Mevcut dört şablon şunlardır:

Taslakların `Sayı` alanında şimdilik geçici olarak
`E-24325150-XXX-XXX` gösterilir. `24325150`, projedeki DETSİS arşivinde
doğrulanmış Ulaştırma ve Altyapı Bakanlığı ana kurum numarasıdır. İlk `XXX`
standart dosya planı kodunu, ikinci `XXX` ise EBYS kayıt numarasını temsil eder.
Bu değer nihai resmî evrak numarası değildir; uygunluk denetimi iki alan
kurumsal sistem tarafından tamamlanana kadar `RY-11` uyarısı üretir.

| Şablon kimliği | Kullanım amacı |
|---|---|
| `cevap_yazisi_v1` | Vatandaşın/dış başvuranın dilekçe, şikâyet, itiraz, talep veya bilgi başvurusuna cevap |
| `ust_yazi_v1` | Bağlı/alt birime bildirim, inceleme, havale, talimat veya görevlendirme |
| `bilgilendirme_yazisi_v1` | Doğrudan talep içermeyen kurumsal bilgilendirme |
| `eksik_bilgi_talebi_v1` | Başvurunun işleme alınması için zorunlu bilgi veya belgenin başvurandan istenmesi |

Her şablonun kendi dizininde şu dosyalar bulunur:

- `template.tex`: resmî yazının LaTeX yerleşimi,
- `schema.json`: doldurulabilir alan sözleşmesi,
- `rules.yaml`: şablona özgü doğrulama kuralları,
- `metadata.json`: şablon kimliği ve açıklayıcı üstveri.

LLM4, `template.tex` dosyasını serbestçe yeniden yazmaz ve LaTeX kodu üretmez.
Yalnız konu, paragraflar ve makam ilişkisine uygun kapanış gibi kapalı JSON
alanlarını doldurur. `src/karayol_agent/latex/renderer.py` bu değerleri güvenli
biçimde escape ederek şablona yerleştirir. Bu ayrım hem biçimi sabit tutar hem de
LaTeX enjeksiyonu/derleme hatası riskini azaltır.

Vatandaşa ve alt birime gönderilecek yazılar aynı içerik değildir:

- `citizen` çıktısı, başvurana doğrudan ve anlaşılır resmî cevap üretir;
- `internal_unit` çıktısı, sorumlu birime inceleme/havale amaçlı üst yazı üretir;
- `both` seçilirse iki bağımsız `Layer3DraftOutput` ve iki ayrı artifact oluşur.

Üretilen metinde “taslak türü”, ajan/model adı, retrieval skoru, yarışma
snapshot uyarısı veya sistem içi doğrulama mesajı bulunmamalıdır. Uygunluk
skorları ve teknik uyarılar arayüzde belge görünümünün dışında gösterilir.
Gelen evraktaki eksikler bu taslağın içine uydurularak doldurulmaz; gerekiyorsa
başvurana eksik bilgi/belgeyi bildiren ayrı bir resmî cevap hazırlanır.

Arayüz, `layer3_outputs` içindeki `target`, `label`, `draft`, `compliance` ve
`artifact` alanlarını kullanmalıdır. LaTeX kaynak dosyası ve PDF hedefe özel
artifact uçlarından indirilmelidir. İnsan onayı verilmeden çıktı “gönderildi”
olarak gösterilmemelidir.

## 14. Yerel çalıştırma ve bağlantı

Backend'i proje ayarlarını yükleyen başlatıcıyla çalıştırmak önerilir:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start_local_uab.ps1 `
  -PythonPath .venv\Scripts\python.exe `
  -EmbeddingDevice cpu
```

Frontend:

```powershell
python -m http.server 3000 --directory frontend
```

`frontend/config.js`:

```js
window.KARAYOL_CONFIG = Object.freeze({
  apiBaseUrl: "http://127.0.0.1:8010"
});
```

Yeni bir frontend geliştirilirken canlı ve makinece okunabilir sözleşme için
FastAPI OpenAPI çıktısı esas alınmalıdır. Mevcut örnek istemci
`frontend/static/app.js`, polling, güvenli artifact URL kontrolü, katman
sekmeleri ve ajan zaman çizelgesi için referans uygulamadır.

## 15. İlgili kod ve belgeler

- Orkestrasyon: `src/karayol_agent/orchestrator.py`
- API modelleri: `src/karayol_agent/schemas.py`
- REST rotaları: `src/karayol_agent/backend/routes.py`
- Katman 2: `src/karayol_agent/layer2_legal_reasoning.py`
- Katman 1 LLM rolleri: `src/karayol_agent/agents/llm_roles.py`
- Katman 3 LLM rolleri: `src/karayol_agent/agents/llm_layer3.py`
- Federated retrieval: `src/karayol_agent/retrieval/federated.py`
- LaTeX/PDF renderer: `src/karayol_agent/latex/renderer.py`
- Mevcut frontend örneği: `frontend/static/app.js`
- Resmî yazışma kuralları: `docs/RESMI_YAZISMA_UYGUNLUK_KURALLARI.md`
- Frontend/backend ayrımı: `docs/05_FRONTEND_BACKEND_REST.md`
- Katman 1 test beklentileri: `data/manual_tests/six_document_types/BEKLENEN_SONUCLAR.md`
- Katman 2 test beklentileri: `data/manual_tests/six_document_types_layer2/BEKLENEN_SONUCLAR.md`
- LaTeX şablon kataloğu: `templates/catalog.json`

### 15.1 Tam dosya yolu envanteri

Aşağıdaki envanter üç katmanlı mimarinin kaynak kodu, API/frontend bağlantısı,
OCR ve retrieval altyapısı, LLM rolleri, kurallar, LaTeX şablonları, manuel test
evrakları, veri hazırlama scriptleri ve doğrulama testleri için başvurulacak
dosya yollarını tek yerde toplar.

`.env` bu listeye bilinçli olarak alınmamıştır; API ve Qdrant anahtarları
dokümana veya kaynak kontrolüne yazılmamalıdır. `runtime/`, `output/` ve
`qdrant_db_tamamlandi/` altındaki büyük/üretilmiş içeriklerin yalnız mimariyle
doğrudan ilgili kök veya ana artifact yolları gösterilmiştir.

```text
.env.example
data/legal_requirements/catalog.json
data/legal_requirements/README.md
data/manual_tests/six_document_types_layer2/01_dilekce_k1_filo_islemleri.txt
data/manual_tests/six_document_types_layer2/02_sikayet_sehirlerarasi_otobus.txt
data/manual_tests/six_document_types_layer2/03_itiraz_arac_muayene_agir_kusur.txt
data/manual_tests/six_document_types_layer2/04_talep_tehlikeli_madde_filo_islemleri.txt
data/manual_tests/six_document_types_layer2/05_izin_ubak_soguk_zincir.txt
data/manual_tests/six_document_types_layer2/06_belge_yol_kenari_denetim_kayitlari.txt
data/manual_tests/six_document_types_layer2/BEKLENEN_SONUCLAR.md
data/manual_tests/six_document_types/01_dilekce_eksik.txt
data/manual_tests/six_document_types/02_sikayet_eksik.txt
data/manual_tests/six_document_types/03_itiraz_eksik.txt
data/manual_tests/six_document_types/04_talep_eksik.txt
data/manual_tests/six_document_types/05_izin_eksik.txt
data/manual_tests/six_document_types/06_belge_eksik.txt
data/manual_tests/six_document_types/BEKLENEN_SONUCLAR.md
data/organization/kgm_units_2026-07-16.json
data/processed/competition_snapshot.json
data/processed/external_legal_corpus.chunk_order.jsonl
data/processed/external_legal_corpus.json
data/processed/uab_legal_rag_v2_snapshot.json
data/processed/uab_ministry_archive_snapshot.json
data/synthetic_gold.json
data/synthetic_legislation.json
data/synthetic_ui_fixtures.json
data/synthetic_units.json
docs/01_SARTNAME_ANALIZI.md
docs/02_YEREL_OLLAMA.md
docs/03_BELGE_ALIMI_VE_OCR.md
docs/04_LATEX_VE_PDF_CIKTISI.md
docs/05_FRONTEND_BACKEND_REST.md
docs/06_SWAGGER_OPENAPI.md
docs/07_ORGANIZASYON_SEMASI.md
docs/08_GUVENLI_BIRIM_YONLENDIRME.md
docs/09_TEST_VE_CALISTIRMA.md
docs/DEGISIKLIKLER.md
docs/GUNLUK_DURUM_2026-08-24.md
docs/MIMARI.md
docs/README.md
docs/RESMI_YAZISMA_UYGUNLUK_KURALLARI.md
docs/SARTNAME_EKSIKLERI_UYGULAMA_PLANI.md
docs/swagger.json
docs/UC_KATMANLI_MIMARI_VE_ARAYUZ_ENTEGRASYONU.md
frontend/config.js
frontend/index.html
frontend/README.md
frontend/static/app.css
frontend/static/app.js
kaggle/__init__.py
kaggle/kaggle_legal_rag_v2.py
kaggle/README_KAGGLE_LEGAL_RAG_V2.md
pyproject.toml
qdrant_db_tamamlandi/collection/legal_chunks_direct/storage.sqlite
README.md
reports/MEVZUAT_KAYNAK_INCELEME_2026-08-24.md
reports/OCR_INCELEME_2026-08-24.md
reports/PRODUCTION_DEMO_ACCEPTANCE_2026-08-24.md
reports/RETRIEVAL_ABLATION_2026-08-24.md
reports/SNAPSHOT_RELEVANCE_EVALUATION_2026-08-24.md
reports/synthetic_evidence_graph_2026-08-24.json
runtime/qdrant-competition-snapshot/
runtime/qdrant-uab-ministry-archive/
runtime/uab-legal-rag-v2/
scripts/__init__.py
scripts/audit_delivery_inventory.py
scripts/build_uab_archive_snapshot.py
scripts/evaluate_blind_documents.py
scripts/evaluate_snapshot_relevance.py
scripts/generate_synthetic_gold.py
scripts/generate_synthetic_pdfs.py
scripts/integrate_external_legal_corpus.py
scripts/integrate_uab_legal_rag_v2.py
scripts/ocr_review.py
scripts/reindex_external_legal_corpus.py
scripts/run_acceptance_metrics.py
scripts/run_llm_live_acceptance.py
scripts/run_production_demo_acceptance.py
scripts/start_local_gemini.ps1
scripts/start_local_ollama.ps1
scripts/start_local_uab.ps1
scripts/transform_remote_collection_inplace.py
scripts/upload_qdrant_db.py
src/karayol_agent/__init__.py
src/karayol_agent/agents/__init__.py
src/karayol_agent/agents/analysis.py
src/karayol_agent/agents/classifier.py
src/karayol_agent/agents/compliance.py
src/karayol_agent/agents/document_type_catalog.py
src/karayol_agent/agents/drafting.py
src/karayol_agent/agents/legislation.py
src/karayol_agent/agents/llm_layer3.py
src/karayol_agent/agents/llm_roles.py
src/karayol_agent/agents/routing.py
src/karayol_agent/agents/template_selection.py
src/karayol_agent/api.py
src/karayol_agent/backend/__init__.py
src/karayol_agent/backend/routes.py
src/karayol_agent/cli.py
src/karayol_agent/config.py
src/karayol_agent/curation/__init__.py
src/karayol_agent/curation/classifier.py
src/karayol_agent/curation/models.py
src/karayol_agent/curation/service.py
src/karayol_agent/document_types.py
src/karayol_agent/documents/__init__.py
src/karayol_agent/documents/extractor.py
src/karayol_agent/documents/layout.py
src/karayol_agent/documents/text_normalization.py
src/karayol_agent/evaluation/__init__.py
src/karayol_agent/evaluation/hybrid_benchmark.py
src/karayol_agent/evaluation/models.py
src/karayol_agent/evaluation/service.py
src/karayol_agent/graph/__init__.py
src/karayol_agent/graph/decision_support.py
src/karayol_agent/graph/evidence_graph.py
src/karayol_agent/ingestion/__init__.py
src/karayol_agent/ingestion/chunker.py
src/karayol_agent/ingestion/ocr_candidate.py
src/karayol_agent/ingestion/quality.py
src/karayol_agent/ingestion/service.py
src/karayol_agent/ingestion/snapshot.py
src/karayol_agent/latex/__init__.py
src/karayol_agent/latex/renderer.py
src/karayol_agent/layer2_legal_reasoning.py
src/karayol_agent/llm/__init__.py
src/karayol_agent/llm/contracts.py
src/karayol_agent/llm/gateway.py
src/karayol_agent/llm/privacy.py
src/karayol_agent/llm/providers.py
src/karayol_agent/llm/schema.py
src/karayol_agent/llm/transport.py
src/karayol_agent/official_writing_rules.py
src/karayol_agent/orchestrator.py
src/karayol_agent/retrieval/__init__.py
src/karayol_agent/retrieval/bm25.py
src/karayol_agent/retrieval/contracts.py
src/karayol_agent/retrieval/corpus.py
src/karayol_agent/retrieval/embeddings.py
src/karayol_agent/retrieval/federated.py
src/karayol_agent/retrieval/hf_loading.py
src/karayol_agent/retrieval/hybrid.py
src/karayol_agent/retrieval/qdrant_store.py
src/karayol_agent/retrieval/relevance.py
src/karayol_agent/retrieval/repository.py
src/karayol_agent/retrieval/requirement_rules.py
src/karayol_agent/retrieval/reranker.py
src/karayol_agent/retrieval/runtime.py
src/karayol_agent/retrieval/vector_indexing.py
src/karayol_agent/revision_pins.py
src/karayol_agent/schemas.py
src/karayol_agent/state_store.py
src/karayol_agent/text_utils.py
templates/bilgilendirme_yazisi_v1/metadata.json
templates/bilgilendirme_yazisi_v1/rules.yaml
templates/bilgilendirme_yazisi_v1/schema.json
templates/bilgilendirme_yazisi_v1/template.tex
templates/catalog.json
templates/cevap_yazisi_v1/metadata.json
templates/cevap_yazisi_v1/rules.yaml
templates/cevap_yazisi_v1/schema.json
templates/cevap_yazisi_v1/template.tex
templates/eksik_bilgi_talebi_v1/metadata.json
templates/eksik_bilgi_talebi_v1/rules.yaml
templates/eksik_bilgi_talebi_v1/schema.json
templates/eksik_bilgi_talebi_v1/template.tex
templates/ust_yazi_v1/metadata.json
templates/ust_yazi_v1/rules.yaml
templates/ust_yazi_v1/schema.json
templates/ust_yazi_v1/template.tex
tests/test_acceptance_metrics.py
tests/test_analysis_ocr_fields.py
tests/test_api_invalid_upload_regression_1.py
tests/test_api.py
tests/test_artifact_download_regression_1.py
tests/test_blind_evaluation.py
tests/test_cli_error_regression_1.py
tests/test_completed_process_immutable_regression_1.py
tests/test_config_qdrant.py
tests/test_config_revision_pins.py
tests/test_curation.py
tests/test_delivery_inventory.py
tests/test_document_type_catalog.py
tests/test_embeddings.py
tests/test_evaluation.py
tests/test_evidence_graph.py
tests/test_extractor.py
tests/test_federated_retrieval.py
tests/test_frontend_backend_separation.py
tests/test_general_document_types.py
tests/test_graph_decision_support.py
tests/test_hybrid_benchmark.py
tests/test_hybrid_retrieval.py
tests/test_information_validation_regression_1.py
tests/test_ingestion.py
tests/test_kaggle_legal_rag_v2.py
tests/test_layer2_legal_reasoning.py
tests/test_legislation_hybrid_integration.py
tests/test_llm_gateway.py
tests/test_llm_schema_privacy.py
tests/test_manual_ui.py
tests/test_ocr_candidate_ingestion.py
tests/test_ocr_review_script.py
tests/test_official_closing_regression_1.py
tests/test_official_writing_rules.py
tests/test_orchestrator_llm_integration.py
tests/test_orchestrator.py
tests/test_organization_routing.py
tests/test_process_id_traversal_regression_1.py
tests/test_qdrant_store.py
tests/test_rag_cli.py
tests/test_requirement_rules.py
tests/test_reranker.py
tests/test_resource_manifest.py
tests/test_retrieval_runtime.py
tests/test_retrieval.py
tests/test_sartname_compliance.py
tests/test_short_pdf_regression_1.py
tests/test_snapshot_application_disclosure.py
tests/test_snapshot_corpus.py
tests/test_snapshot_relevance.py
tests/test_vector_indexing.py
uv.lock
veri_kaynaklari/karayolu/detsis/belgeler_raw.json
veri_kaynaklari/karayolu/detsis/belgeler.csv
veri_kaynaklari/karayolu/detsis/belgeler.json
veri_kaynaklari/karayolu/detsis/hizmetler_raw.json
veri_kaynaklari/karayolu/detsis/hizmetler.csv
veri_kaynaklari/karayolu/detsis/hizmetler.json
veri_kaynaklari/karayolu/detsis/karayolu_belgeleri.json
veri_kaynaklari/karayolu/detsis/karayolu_hizmetleri.json
veri_kaynaklari/karayolu/detsis/karayolu_mevzuatlari.json
veri_kaynaklari/karayolu/detsis/kunye_header_raw.json
veri_kaynaklari/karayolu/detsis/kunye_raw.json
veri_kaynaklari/karayolu/detsis/kurum_kunyesi_temiz.json
veri_kaynaklari/karayolu/detsis/mevzuatlar_raw.json
veri_kaynaklari/karayolu/detsis/mevzuatlar.csv
veri_kaynaklari/karayolu/detsis/mevzuatlar.json
veri_kaynaklari/karayolu/detsis/normalize_detsis.py
veri_kaynaklari/karayolu/detsis/ozet.json
veri_kaynaklari/karayolu/detsis/README.md
```
