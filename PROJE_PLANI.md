# Proje Planı — Kamu Evrak ve Yazışma Süreçleri İçin Akıllı Agent Destek Sistemi
**TEKNOFEST 2026 — Yapay Zeka Dil Ajanları Yarışması (1. Senaryo)**

---

## ⚠️ 0. Kritik Zaman Durumu

| | |
|---|---|
| Bugünün tarihi | **20 Ağustos 2026** |
| Çevrimiçi süreç son tarihi | **26 Ağustos 2026** |
| Kalan süre | **6 geliştirme günü + teslim günü** |
| Final | Ağustos (tarih TEKNOFEST takviminde ilan edilecek) |

Bu plan, "ideal/kapsamlı mimari" değil, **teslim tarihine kadar uçtan uca çalışan, demo edilebilir bir sistem** teslim etme gerçeğine göre kurgulanmıştır. Puanlamada Uygulama (35) + Demo (15) = **100 puanın yarısı çalışırlığa bağlı**; yarım kalmış ama "teorik olarak ileri" bir mimari, sade ama sağlam çalışan bir mimariden daha düşük puan alır. Bu nedenle aşağıdaki her bölüm **Tier 0 (zorunlu) / Tier 1 (zaman kalırsa) / Tier 2 (dokümante edilir, muhtemelen kodlanmaz)** şeklinde önceliklendirilmiştir.

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

**Teknik not:** Bu iki mevzuat PDF'i, gömülü font kodlamasından dolayı `pdftotext`/`pypdf` ile metne çevrilince Türkçe'ye özgü harfler (ı, ş, ğ, ü, ö, ç) düşüyor. Sayfaları görsel olarak render edip (PyMuPDF ile) doğruladık — içerik doğru ama **standart metin çıkarımı bu dosyalarda güvenilir değil**. Bu, projenin kendi evrak-okuma modülü için de gerçek bir tasarım girdisi: OCR/görsel tabanlı çıkarım (veya en azından font/encoding doğrulama adımı), yalnızca "nice to have" değil, **gerçek bir ihtiyaç** olarak Tier 0'a alınmalı.

Yönetmelikten şimdiye kadar görsel olarak doğrulanan içerik: Amaç/Kapsam/Dayanak (Md 1-2), Tanımlar (Md 3 — aidiyet zinciri, arşiv imza, belge, **DETSİS**, EBYS, elektronik onay/ortam, e-Yazışma Teknik Rehberi, form/format, güvenli elektronik imza, standart dosya planı, üstveri, üst yazı, yetkili makam, zaman damgası, zorunlu hâl). Kalan maddeler (format kuralları, imza blokları, gizlilik dereceleri, ekler/dağıtım, arşivleme) ekip tarafından dosyadan görsel olarak çıkarılıp **doğrulanmalı** — bu plandaki format kuralı detayları varsayım değil, kaynağa referansla teyit edilmelidir.

---

## 3. Veri Stratejisi

Şartname madde 6.5 gerçek kamu verisini yasaklıyor. Buna göre:

1. **Sentetik evrak korpüsü:** 8-12 evrak türü (dilekçe, üst yazı, cevap yazısı, bilgi talebi, ihbar/şikayet, bilgilendirme yazısı, iç yazışma vb.) × her türden 30-50 örnek → toplam **300-500 temiz kurgu evrak** hedeflenir. Bunların en az 80 adedi ekip tarafından alan alan gözden geçirilmiş "gold" veri olur. Temiz belgeler farklı şablonlarla PDF/görsele dönüştürülür; seçili örnekler tarama, fotokopi, dönme, bulanıklık ve sıkıştırma bozulmalarıyla çoğaltılarak **1.000-2.000 OCR görüntüsü** elde edilir. Hacimden önce gold setin doğruluğu tamamlanır.
2. **Mevzuat corpus:** `mevzuat-1.pdf` + `mevzuat-kılavuz.pdf` madde bazlı chunk'lanarak RAG kaynağı yapılacak (kamuya açık, gerçek kamu verisi değil — yönetmelik metni).
3. **Kurum/birim listesi (DETSİS esinli, sentetik):** Gerçek DETSİS kayıtları çekilmeyecek (hem erişim kısıtlı hem de "gerçek kamu verisi" riski var — bkz. önceki tartışma). Bunun yerine DETSİS'in **numaralandırma formatı ve hiyerarşi mantığı** referans alınarak kurgu bir kurum/birim ağacı (örn. "Örnek Bakanlık > Örnek Genel Müdürlük > Örnek Daire Başkanlığı") oluşturulacak. Bu liste, birim yönlendirme agent'ının hedef havuzu olacak.
4. **Veri bölme kuralı:** Train/dev/test ayrımı belge şablonu ve senaryo ailesi bazında yapılır. Aynı şablonun yalnızca alan değerleri değiştirilmiş kopyaları farklı bölümlere dağıtılmaz. En az 30-40 belge gizli test setinde tutulur.
5. **Veri manifestosu:** Her kaynak ve üretilen dosya için `source`, `license`, `synthetic`, `generator`, `seed`, `template_id`, `split` ve `review_status` alanları kaydedilir. Gerçek ad, TCKN, adres, imza, telefon, sicil veya evrak numarası kullanılmaz; test değerleri açıkça `SENTETIK` olarak işaretlenir.

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
| Taslak oluşturma | Şablon (Yönetmelik'e uygun format) + LLM ile doldurma |
| Birim yönlendirme | Sentetik birim ağacı üzerinde LLM/embedding ile en uygun birim seçimi |
| Orkestrasyon | Basit sıralı pipeline (tek agent zinciri yeterli, karmaşık multi-agent framework şart değil) |

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

---

## 7. Demo Senaryosu Planı

1. Kurgu bir evrak (PDF/görsel) sisteme yüklenir.
2. Görev 1 çıktısı canlı gösterilir: tür, özet, eksik alan uyarısı, mevzuat önerisi.
3. Görev 2 çıktısı: resmi yazı taslağı + önerilen birim + (varsa) eksik bilgi talebi.
4. **Gerçek zamanlı çalıştırma tercih edilmeli** (şartname bunu avantaj sayıyor); kayıttan sunum seçilirse jürinin canlı çalıştırma talebine anında yanıt verilebilmeli.
5. **İnternet kesintisi yedek planı:** Yerel/offline çalışabilen bir fallback (örn. önceden çalıştırılmış kayıt + yerel model) hazır tutulmalı.

---

## 8. Test / Değerlendirme Planı

- En az 30-40 sentetik evrak içeren, şablon/senaryo sızıntısından arındırılmış gizli test seti (gold-label: doğru tür, alanlar, eksik bilgiler, doğru birim ve gerekli mevzuat).
- Ölçütler: sınıflandırma doğruluğu, yönlendirme başarımı (top-1/top-3), eksik bilgi tespit recall'ü, taslak formatının Yönetmelik kurallarına uyum yüzdesi.
- Bu sonuçlar teknik raporda ve sunumda **sayısal olarak** gösterilmeli (jüri "Uygulama" kriterinde performans ölçütlerini açıkça arıyor — madde 9).

---

## 9. Zaman Çizelgesi (20-26 Ağustos)

| Gün | Tarih | Odak |
|---|---|---|
| 1 | 20 Ağu | Teknik yığını kesinleştirme; sentetik veri ve birim listesi; mevzuat corpus |
| 2 | 21 Ağu | Görev 1: metin/OCR, sınıflandırma ve yapılandırılmış bilgi çıkarımı |
| 3 | 22 Ağu | Görev 1: mevzuat RAG, madde atfı, eksik bilgi tespiti ve ilk uçtan uca test |
| 4 | 23 Ağu | Görev 2: birim yönlendirme, taslak üretimi ve format doğrulama |
| 5 | 24 Ağu | Entegrasyon, insan onayı akışı, hata durumları ve test seti ölçümleri |
| 6 | 25 Ağu | Hata düzeltme, Docker, README, rapor, sunum, demo videosu ve prova |
| 7 | 26 Ağu | Son smoke test, lisans/kaynak kontrolü, GitHub ve **son teslim** |

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
| Sürenin yetersiz kalması | Yüksek | Tier 0 dışına zaman harcanmaz; Tier 2 sadece raporda "gelecek vizyon" olarak yazılır |
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

## 13. MVP Kabul Kriterleri (Definition of Done)

Tier 0, ancak aşağıdaki maddelerin tamamı doğrulandığında bitmiş sayılır:

- [x] PDF, görsel ve düz metin girdisi kabul ediliyor.
- [x] OCR sonucu orijinal belgeyle birlikte görüntülenebiliyor ve kullanıcı tarafından düzeltilebiliyor.
- [x] Analiz sonucu tanımlı ve sürümlenmiş JSON şemasına uyuyor.
- [x] Evrak türü, özet, çıkarılan bilgiler ve eksik alanlar gösteriliyor.
- [x] Her mevzuat önerisi kaynak belge, sayfa/madde ipucu ve dayanak metni içeriyor.
- [x] Birim önerisi gerekçe ve benzerlik skoruyla sunuluyor.
- [x] Resmî yazı taslağı kullanıcı tarafından düzenlenebiliyor.
- [x] Kullanıcı onayı olmadan yazı kesinleştirilmiyor, imzalanmıyor, gönderilmiyor veya dışa aktarılamıyor.
- [x] Okunamayan, kapsam dışı veya düşük güvenli belgelerde sistem açık uyarı veriyor.
- [x] Uygulama temiz Docker imajlarında README/Makefile talimatlarıyla yeniden çalıştırılabiliyor.

---

## 14. İnsan Onayı, Güvenlik Sınırları ve Denetim İzi

- Sistem karar veren makam değil, **karar destek aracıdır**.
- Düşük güvenli sınıflandırma, mevzuat ve yönlendirme sonuçları insan incelemesine aktarılır.
- Sistem elektronik imza atmaz, evrak göndermez ve resmî kayıt oluşturmaz.
- Yeterli mevzuat dayanağı bulunamadığında tahmin üretmek yerine "doğrulanmış dayanak bulunamadı" uyarısı verir.
- OCR metni ile orijinal belge yan yana gösterilir; kullanıcı düzeltmeleri analizden önce uygulanır.
- Her işlemde zaman, model/prompt sürümü, kullanılan kaynak maddeler, güven skorları ve kullanıcı değişiklikleri denetim izi olarak kaydedilir.
- Sentetik evraklarda dahi gerçek kişi bilgisi kullanılmaz; girdi yükleme boyutu ve dosya türü sınırlanır.

---

## 15. Teknik Yığın Kararı

| Katman | MVP tercihi | Not |
|---|---|---|
| Arayüz | React + Vite + TypeScript | Tek sayfalı, adım adım demo akışı |
| Servis katmanı | FastAPI | Sürümlü REST API ve arka plan işleri |
| Veri şeması | Pydantic | Yapılandırılmış ve doğrulanabilir çıktı |
| Metin/OCR | PyMuPDF metin çıkarımı + Tesseract OCR fallback | Metin katmanı kalite kontrolü zorunlu |
| RAG | Normalize NumPy matrisi + kosinüs benzerliği | Küçük corpus için haricî vektör veritabanı gerektirmez |
| Embedding | Ollama `/api/embed`; model arayüzden dinamik seçilir | Model ve vektör boyutu doğrulanır, değişiklikte yeniden indekslenir |
| LLM | Ollama yapılandırılmış JSON; model arayüzden dinamik seçilir | Pydantic şeması ve sınırlı yeniden deneme uygulanır |
| Veri | JSONL + SQLite + dosya tabanlı runtime | İş durumu, denetim izi ve sürümler kalıcı tutulur |
| Test | Pytest + Vitest + üretim derlemesi | Deterministik servisler ve istemci davranışı otomatik test edilir |
| Paketleme | Docker | Tek komutla kurulum hedeflenir |
| Dışa aktarma | DOCX + PDF | Yalnızca insan onayından sonra; sentetik filigranla |

Mimari kararlar `docs/DECISIONS.md`, model gereksinimleri ise `docs/MODELS.md` içinde kayıtlıdır.

---

## 16. İzlenebilir Çıktı Şeması

```json
{
  "evrak_id": "sentetik-001",
  "sema_surumu": "1.0",
  "evrak_turu": "bilgi_talebi",
  "evrak_turu_guven": 0.91,
  "ozet": "...",
  "cikarilan_bilgiler": {},
  "eksik_alanlar": [],
  "onerilen_mevzuat": [
    {
      "kaynak": "mevzuat-1.pdf",
      "madde": "Madde ...",
      "dayanak_metni": "...",
      "benzerlik_skoru": 0.84
    }
  ],
  "onerilen_birim": {
    "birim_id": "BRM-001",
    "birim_adi": "...",
    "gerekce": "...",
    "guven": 0.87
  },
  "taslak": "...",
  "uyarilar": [],
  "insan_onayi_gerekli": true
}
```

Kaynak metin parçalarının kullanıcı arayüzünde gösterimi, belge/madde atfı ve skorlarla birlikte yapılır. Benzerlik skoru tek başına "doğruluk" olarak sunulmaz.

---

## 17. Demo ve Hata Senaryoları

Demo, yalnızca başarılı bir örneği değil sistemin güvenli davranışını da göstermelidir:

1. **Temiz ve eksiksiz evrak:** Uçtan uca analiz, mevzuat, yönlendirme ve taslak başarıyla tamamlanır.
2. **Taranmış ve eksik evrak:** OCR sonucu, eksik alan uyarısı ve kullanıcıdan bilgi talebi gösterilir.
3. **Belirsiz veya kapsam dışı evrak:** Sistem düşük güven bildirir, kesin karar üretmez ve insan incelemesi ister.
4. **Yanıltıcı talimat içeren evrak:** Belge içindeki prompt-injection benzeri talimatlar veri olarak ele alınır; sistem kurallarını değiştiremez.

Her demo senaryosu için beklenen çıktı, tahmini süre, anlatılacak teknik kazanım ve yedek ekran kaydı önceden hazırlanır.

---

## 18. Deney Hedefleri ve Raporlama

| Ölçüt | MVP hedefi |
|---|---:|
| Evrak sınıflandırma macro-F1 | ≥ %80 |
| Bilgi çıkarımı alan bazlı F1 | ≥ %80 |
| Eksik bilgi tespit recall | ≥ %85 |
| Birim yönlendirme top-1 | ≥ %75 |
| Birim yönlendirme top-3 | ≥ %90 |
| Doğru mevzuatın ilk 3 sonuçta bulunması | ≥ %85 |
| Taslak biçim kuralı uyumu | ≥ %90 |
| Uçtan uca p95 yanıt süresi | ≤ 30 saniye |

Bu değerler yarışma sonucu vaadi değil, **geliştirme hedefidir**. Son raporda hedef yerine ölçülen gerçek sonuçlar; test seti boyutu, başarısız örnekler ve bilinen kısıtlarla birlikte verilir. Sentetik veri üretiminde kullanılan örnekler ile gizli test seti ayrı tutulur; aynı şablonun yakın kopyaları farklı bölümlere dağıtılmaz.

---

## 19. Teslim Çıktıları

- [x] Çalışan uygulama ve kaynak kod
- [x] Docker yapılandırması
- [x] Türkçe README ve tek komutla kurulum/çalıştırma talimatı
- [x] Mimari ve veri akışı diyagramı
- [x] Sentetik veri seti, veri üretim yöntemi ve veri kartı
- [x] Kullanılan kütüphane, veri ve lisans envanteri; dinamik model gereksinimi
- [ ] Gold test seti, metrikler ve hata analizi
- [x] Örnek sentetik evraklar ve aday beklenen çıktılar
- [ ] Demo videosu ve canlı demo yedek planı
- [ ] Teknik rapor ve sunum
- [x] Açık kaynak lisansı
- [x] Bilinen kısıtlar, etik/güvenlik notları ve gelecek çalışmalar

---

## 20. Haricî Veri Kaynağı Araştırması

Araştırma sonucunda, açık lisanslı ve gerçek kişisel veri içermeyen, doğrudan **"Türkçe kamu evrakı + birim yönlendirme"** veri kümesi bulunamamıştır. Bu nedenle ana veri stratejisi; resmî taksonomi ve mevzuatın yalnızca dayanak olarak kullanılması, asıl evrakların ise sentetik üretilmesidir.

İndirilen resmî referanslar, veri kartları, lisans kayıtları ve SHA-256 manifestosu `resources/` dizininde tutulur. Büyük veri kümeleri, alt küme ve depolama kararı verilmeden bu dizine indirilmez.

### 20.1. Kullanılabilecek Kaynaklar

| Kaynak | Lisans/erişim | Projedeki rol | Karar |
|---|---|---|---|
| [TR-DocVQA-Synth](https://huggingface.co/datasets/Ethosoft/TR-DocVQA-Synth) | CC BY 4.0 veri, MIT kod | Sentetik Türkçe belge görüntüleri; OCR, alan çıkarımı ve layout testi | Seçili alt küme kullanılabilir; kamu evrakı değil, ticari belge ağırlıklı olduğu belirtilir |
| [Turkish Law Corpus](https://huggingface.co/datasets/CtnkyaABC/turkish-law-corpus) | CC BY 4.0 | Mevzuat retrieval deneyi ve madde atfı testi | Yardımcı corpus; resmî kaynakla doğrulanmadan nihai dayanak olarak kullanılmaz |
| [Turkish Legal QA Triplets](https://huggingface.co/datasets/yunus-emre/tr-legal-triplets) | Apache 2.0 | Embedding/reranker karşılaştırması | MVP'de fine-tune yerine küçük, incelenmiş benchmark örneklemi |
| [Mevzuat Bilgi Sistemi](https://www.mevzuat.gov.tr/) | Kamuya açık resmî kaynak; portalın otomatik kullanım koşulları ayrıca kontrol edilir | Mevzuat adı, madde ve güncellik doğrulaması | Bağlayıcı doğrulama kaynağı; toplu scraping yapılmaz |
| [Devlet Arşivleri Standart Dosya Planı](https://www.devletarsivleri.gov.tr/Sayfalar/Sayfa.aspx?h=EC4EE38996FE1DD2D040D483800B793116ED6F1FD94ED1E517B581F5E16F395B&icerik=20) | Kamuya açık; açık veri lisansı belirtilmemiş | Konu sınıfları ve sentetik yönlendirme taksonomisine referans | Ham dosya yeniden dağıtılmaz; kaynak gösterilerek sentetik şema türetilir |
| [DocLayNet](https://github.com/DS4SD/DocLayNet) | CDLA-Permissive 1.0 | Başlık, paragraf, tablo ve şekil gibi layout bileşenleri | Dil sınıflandırması için değil; gerekirse küçük alt küme ile layout benchmark |
| [Turkish PII Corpus](https://huggingface.co/datasets/fevziegeyurtsevenler/turkish-pii-corpus) | Apache 2.0 | Kişisel veri maskeleme testleri ve etiket şeması | Küçük olduğu için yalnızca test tohumu; gerçek kimlik değerleri projeye alınmaz |

Yönlendirme senaryoları için kamu kurumlarının hizmet standartları tabloları, `talep konusu → sorumlu birim → gerekli belgeler` şemasına **ilham kaynağı** olabilir. Ancak açık veri lisansı belirtilmeyen tablolar projede aynen yeniden yayımlanmayacak; kurum/birim adları ve başvuru olayları kurgu olarak üretilecektir.

### 20.2. Sentetik Veri Üretim Araçları

| Araç | Lisans | Kullanım |
|---|---|---|
| [Faker](https://github.com/joke2k/faker) | MIT | `tr_TR` ile açıkça sentetik alan değerleri; gerçek TCKN üretimi yapılmaz |
| [TextRecognitionDataGenerator](https://github.com/Belval/TextRecognitionDataGenerator) | MIT | Türkçe karakter destekli fontlarla sentetik OCR satırı/görüntüsü |
| [Augraphy](https://github.com/sparkfish/augraphy) | MIT | Temiz belgelerden tarama, fotokopi, faks, leke, dönme ve sıkıştırma varyantları |

Her temiz belgenin doğru metni ground-truth olarak korunur; görsel bozulmalar ayrı dosyalar halinde aynı `document_family_id` ile izlenir. Böylece OCR başarımı CER/WER ile ölçülebilir.

### 20.3. Kullanılmaması veya İzin Beklenmesi Gereken Kaynaklar

- Gerçek mahkeme kararı/dava anlatısı içeren veri kümeleri, anonimleştirilmiş olsalar bile yarışma kısıtı nedeniyle kullanılmaz.
- Yargıtay/Danıştay karar toplulukları, gerçek dilekçeler, CİMER başvuruları, kurum içi EBYS çıktıları ve internette bulunan imzalı resmî yazılar veri setine alınmaz.
- Açık lisansı belirtilmeyen [OCRTurk](https://github.com/metunlp/ocrturk) gibi veri kaynakları, yazılı izin/lisans netliği olmadan indirilmez, eğitimde kullanılmaz veya yeniden dağıtılmaz.
- Yalnızca "internette herkese açık" olması, bir veri setini kullanılabilir saymak için yeterli değildir; lisans ve kişisel veri kontrolü zorunludur.
- Ticari kullanımı kısıtlayan `NC` lisanslı veri kümeleri, projenin ticarileşme hedefiyle çelişmemesi için ana veri setine karıştırılmaz.

### 20.4. Uygulama Sırası

1. 8-12 evrak türü ve sentetik birim taksonomisi kesinleştirilir.
2. Her tür için şema, zorunlu/opsiyonel alanlar ve 3-5 temel senaryo yazılır.
3. Önce 80 adet elle doğrulanmış gold evrak tamamlanır; sistem bu setle uçtan uca çalıştırılır.
4. Otomatik üretimle temiz metin sayısı 300-500'e çıkarılır ve kalite kurallarından geçirilir.
5. Temiz belgeler resmî yazı kılavuzundan türetilen farklı kurgu şablonlarla PDF/görsele dönüştürülür.
6. Seçili sayfalardan Augraphy/TRDG ile 1.000-2.000 bozulmuş OCR varyantı oluşturulur.
7. TR-DocVQA-Synth'in seçili alt kümesiyle alan çıkarımı ve OCR/layout sağlamlaştırma testi yapılır.
8. Gizli test seti sonuçları, hata analizi ve veri/lisans manifestosu rapora eklenir.

---

*Bu plan, şartname (2026_TYDA_SARTNAME_Birinci_Senaryo) ve proje klasöründeki mevzuat kaynaklarına dayanılarak hazırlanmıştır. Yönetmelik'in görsel olarak henüz doğrulanmamış maddeleri (format ölçüleri, imza/ek/dağıtım kuralları) ekip tarafından `mevzuat-1.pdf` üzerinden teyit edilmelidir.*
