# Proje Planı — Kamu Evrak ve Yazışma Süreçleri İçin Akıllı Agent Destek Sistemi
**TEKNOFEST 2026 — Yapay Zeka Dil Ajanları Yarışması (1. Senaryo)**

---

## ⚠️ 0. Kritik Zaman Durumu

| | |
|---|---|
| Bugünün tarihi | **19 Ağustos 2026** |
| Çevrimiçi süreç son tarihi | **26 Ağustos 2026** |
| Kalan süre | **~7 gün** |
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
| `mevzuat-2-1.pdf` | Aynı yönetmeliğin **Kılavuzu** (26 sayfa, örnek/şablon içerikli) | Taslak üretimi için örnek doküman kaynağı |

**Teknik not:** Bu iki mevzuat PDF'i, gömülü font kodlamasından dolayı `pdftotext`/`pypdf` ile metne çevrilince Türkçe'ye özgü harfler (ı, ş, ğ, ü, ö, ç) düşüyor. Sayfaları görsel olarak render edip (PyMuPDF ile) doğruladık — içerik doğru ama **standart metin çıkarımı bu dosyalarda güvenilir değil**. Bu, projenin kendi evrak-okuma modülü için de gerçek bir tasarım girdisi: OCR/görsel tabanlı çıkarım (veya en azından font/encoding doğrulama adımı), yalnızca "nice to have" değil, **gerçek bir ihtiyaç** olarak Tier 0'a alınmalı.

Yönetmelikten şimdiye kadar görsel olarak doğrulanan içerik: Amaç/Kapsam/Dayanak (Md 1-2), Tanımlar (Md 3 — aidiyet zinciri, arşiv imza, belge, **DETSİS**, EBYS, elektronik onay/ortam, e-Yazışma Teknik Rehberi, form/format, güvenli elektronik imza, standart dosya planı, üstveri, üst yazı, yetkili makam, zaman damgası, zorunlu hâl). Kalan maddeler (format kuralları, imza blokları, gizlilik dereceleri, ekler/dağıtım, arşivleme) ekip tarafından dosyadan görsel olarak çıkarılıp **doğrulanmalı** — bu plandaki format kuralı detayları varsayım değil, kaynağa referansla teyit edilmelidir.

---

## 3. Veri Stratejisi

Şartname madde 6.5 gerçek kamu verisini yasaklıyor. Buna göre:

1. **Sentetik evrak korpüsü:** En az 6-8 evrak türü (dilekçe, üst yazı, cevap yazısı, bilgi talebi, ihbar/şikayet, bilgilendirme yazısı, iç yazışma) × her türden 5-10 örnek → toplam ~40-60 kurgu evrak. LLM ile üretilip, biçimsel çeşitlilik (eksik alanlı, bozuk formatlı, taranmış görüntü kalitesinde) kasıtlı olarak eklenmeli ki sistemin "eksik bilgi tespiti" yeteneği gerçekten test edilsin.
2. **Mevzuat corpus:** `mevzuat-1.pdf` + `mevzuat-2-1.pdf` madde bazlı chunk'lanarak RAG kaynağı yapılacak (kamuya açık, gerçek kamu verisi değil — yönetmelik metni).
3. **Kurum/birim listesi (DETSİS esinli, sentetik):** Gerçek DETSİS kayıtları çekilmeyecek (hem erişim kısıtlı hem de "gerçek kamu verisi" riski var — bkz. önceki tartışma). Bunun yerine DETSİS'in **numaralandırma formatı ve hiyerarşi mantığı** referans alınarak kurgu bir kurum/birim ağacı (örn. "Örnek Bakanlık > Örnek Genel Müdürlük > Örnek Daire Başkanlığı") oluşturulacak. Bu liste, birim yönlendirme agent'ının hedef havuzu olacak.

**Uygulama durumu — 23 Ağustos 2026:** Kamuya açık DETSİS/UAB kayıtları yalnızca
kaynak araştırması ve kapsam doğrulaması için ayrı arşivde tutulmaktadır; çalışma
zamanındaki kurum/birim havuzu hâlâ sentetiktir. 501 mevzuat kaydı 501 PDF ile
eşleştirilmiş, tüm sayfaların metin kalitesi denetlenmiş ve
`data/manifests/uab_legislation_manifest.json` oluşturulmuştur. Otomatik sistem
50 karayolu/genel kaynak adayı ve 58 OCR gerektiren PDF belirlemiştir. İnsan
kapsam ve yürürlük doğrulaması yapılmadığı için aktif RAG onayı verilen gerçek
kayıt sayısı sıfırdır. İnceleme kararları
`data/manifests/uab_legislation_manifest_review.csv` üzerinde tutulacaktır.

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
| Mevzuat eşleştirme | Klasik vektör RAG: yönetmelik+kılavuz chunk'ları → embedding → benzerlik araması |
| Özet | LLM ile kısa özet üretimi |
| Eksik bilgi tespiti | Evrak türüne göre zorunlu alan listesi + LLM kontrolü |
| Taslak oluşturma | Sürümlü ve onaylı LaTeX şablonu + LLM'in şemaya uygun JSON alanları üretmesi + güvenli PDF derleme |
| Birim yönlendirme | Sentetik birim ağacı üzerinde LLM/embedding ile en uygun birim seçimi |
| Orkestrasyon | Ortak durum kaydı üzerinden çalışan açık rollü çok ajanlı sistem: Alım/OCR, Sınıflandırma, Mevzuat Araştırma, Kaynak Doğrulama, Yazı Türü Karar ve Şablon Seçimi, Taslak Oluşturma, Birim Yönlendirme, Uygunluk Denetimi ve Kullanıcı Bilgilendirme ajanları |

### Tier 1 — Zaman kalırsa eklenecek (Gün 5-6)
| Teknik | Neden bu sırada |
|---|---|
| **Late Chunking** | Uygulaması ucuz (uzun bağlamlı embedding modeli + sonradan chunk'lama), mevzuat maddelerinin başlık/bağlam bütünlüğünü korur → düşük risk, gerçek getiri |
| **CRAG** (Self-RAG değil) | Hazır modelle çalışır, fine-tuning gerektirmez (şartname "model eğitmek zorunlu değil" diyor); yanlış/alakasız mevzuat eşleşmesini yakalayıp düzeltir |

### Tier 2 — Dokümante edilecek, muhtemelen kodlanmayacak (vizyon/gelecek iş)
> Bu teknikler jüriye "biz bu alanı araştırdık" göstermek için **Yöntem ve Teknik Yaklaşım** bölümünde mimari vizyon olarak anlatılabilir, ama 7 günlük takvimde tam entegrasyonu riskli:
- **HippoRAG** — mevzuat madde ↔ şablon çok-adımlı (multi-hop) bağlantı grafiği
- **Search-o1 tarzı agentic sorgu** — taslak üretimi sırasında anlık mevzuat sorgusu (basit tool-calling ile kısmen zaten Tier 0'da örtük var, "Search-o1" markasıyla ayrı bir sistem kurmaya gerek yok)
- **A-MEM** — geçmiş yönlendirme kararlarının kalıcı/ilişkisel hafızası
- **ColPali** — evrakı görüntü olarak embed etme (OCR yerine). Test evrakları temiz/taranmış kalitede kalacaksa gereksiz risk; gerçekten karmaşık layout (damga, tablo, logo) demo'da öne çıkacaksa değerlendirilebilir.

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

*Bu plan, şartname (2026_TYDA_SARTNAME_Birinci_Senaryo) ve proje klasöründeki mevzuat kaynaklarına dayanılarak hazırlanmıştır. Yönetmelik'in görsel olarak henüz doğrulanmamış maddeleri (format ölçüleri, imza/ek/dağıtım kuralları) ekip tarafından `mevzuat-1.pdf` üzerinden teyit edilmelidir.*
