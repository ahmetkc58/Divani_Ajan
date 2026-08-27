# Divani Ajan

**Yarışma:** TEKNOFEST 2026 Yapay Zekâ Dil Ajanları Yarışması — Birinci Senaryo

**Amaç:** Kamu evrak ve yazışma süreçleri için Türkçe karar destek sistemi

**Ana paket:** `karayol_agent`
**Lisans:** Apache-2.0

## Proje sınırı

Divani Ajan; kurgu evrakı analiz eder, evrak türünü ve eksik alanları belirler,
mevzuat adayı bulur, kurgu birim önerir ve resmî yazı taslağı üretir. Sistem
hukuk mütalaası veya insan adına resmî karar üretmez. Kanıt, güven ya da zorunlu
bilgi yetersizse bu durum kullanıcıya açıkça gösterilmelidir.

Yarışma demosunda gerçek vatandaş/kamu personeli evrakı kullanılmaz. Kamuya
açık mevzuat da insan incelemesi, yürürlük, kaynak, hash, sayfa ve OCR kapıları
tamamlanmadan aktif hukuki kanıt olarak kullanılamaz.

## Zorunlu görevler

### Görev 1 — Evrak sınıflandırma ve içerik analizi

- Desteklenen belgeden metin çıkarma.
- Kapalı etiket kümesinde evrak türü belirleme.
- Konu, talep, tarih, sayı, muhatap ve diğer alanları çıkarma.
- Kaynağa sadık özet ve eksik bilgi listesi üretme.
- Mevzuatı BM25 veya onaylı corpus hazırsa hibrit RAG ile arama.
- Alakasız, düşük güvenli veya kanıtsız girdide sonuç uydurmama.

### Görev 2 — Resmî yazı taslaklama ve birim yönlendirme

- Uygun yazı türünü ve sürümlü şablonu seçme.
- Kurgu birim ağacından gerekçeli yönlendirme yapma.
- Yapılandırılmış alanları güvenli LaTeX şablonuna yerleştirme.
- Zorunlu alan ve uygunluk denetimleri uygulama.
- Nihai kullanım öncesinde insan onayı isteme.

## Veri ve retrieval akışı

```text
TXT / Markdown / metin katmanlı PDF
  → güvenli metin çıkarımı
  → sınıflandırma ve içerik analizi
  → eksik alan tespiti
  → BM25 veya onaylı corpus üzerinde Jina + Qdrant + BM25 + RRF
  → kaynak doğrulama / no-answer kapısı
  → şablon ve kurgu birim seçimi
  → taslak ve uygunluk denetimi
  → insan onayı
  → TEX ve derleyici varsa PDF
```

### `bm25` modu

Varsayılan çevrimdışı demo modudur. Sentetik mevzuat üzerinde çalışır; model
indirmesi veya Qdrant gerektirmez.

### `hybrid` modu

- İnsan onaylı aynı corpus üzerinde contextual BM25 ve Jina dense arama yapar.
- Belge vektöründe `retrieval.passage`, sorguda `retrieval.query` kullanır.
- Qdrant sonuçlarını domain, onay, yürürlük, corpus ve chunk kimliğiyle sınırlar.
- Kanalları ham skor toplamıyla değil RRF ile birleştirir.
- Dense hata/fallback nedenini süreç teşhisinde görünür tutar.
- `/ready`, mevcut koleksiyonu değiştirmeden şema, payload indeksleri, nokta
  sayısı, corpus fingerprint ve embedding metadata sözleşmesini denetler.
- Sorgu yolu eksik koleksiyonu otomatik oluşturmaz; önce `index-vectors`
  çalıştırılmalıdır.

## Güncel ve kanıtlanabilir durum

| Alan | Durum | Kalan kapı |
|---|---|---|
| TXT/MD/metin katmanlı PDF | Uygulandı | Görsel yükleme/OCR ana API akışına bağlı değil |
| Sınıflandırma ve alan çıkarımı | Uygulandı | Bağımsız kör set ve düşük güven kapsamı genişletilmeli |
| Sentetik BM25 demo | Uygulandı | Sentetik olduğu arayüz ve raporda korunmalı |
| Jina/Qdrant hibrit kod yolu | Uygulandı | İnsan onaylı aktif kamu corpus'u yok |
| Qdrant read-only readiness | Uygulandı | Gerçek Qdrant/aktif corpus smoke testi dış kapıya bağlı |
| Mevzuat aktivasyon kapıları | Uygulandı | Hukuk/alan uzmanı onayı bekliyor |
| Şablonlu TEX/PDF taslak | Uygulandı | PDF için yerel LaTeX derleyici gerekir |
| Rapor ve sunum | Ertelendi | Kod freeze ve nihai metriklerden sonra hazırlanacak |
| GitHub teslimi | Kullanıcı onayına bağlı | PDF, PII, lisans ve secret taraması yapılmadan push yok |

## Tamamlanma ölçütü

Proje ancak aşağıdakiler birlikte sağlandığında bitmiş sayılır:

1. İki zorunlu görev uçtan uca ve tekrarlanabilir çalışır.
2. Pozitif, negatif, düşük güven, no-answer ve fallback testleri geçer.
3. Aktif mevzuat corpus'u yazılı insan onayı ve kaynak izi taşır.
4. Veri/model sürümü ve lisans kararları kayıtlıdır.
5. Sentetik sonuç gerçek saha başarısı gibi sunulmaz.
6. Push öncesi PDF, kişisel veri, secret ve yeniden dağıtım hakları incelenir.
7. Kod freeze sonrasında nihai değerlendirme, ardından rapor ve sunum yapılır.

## İlgili belgeler

- Ana yarışma planı: `PROJE_PLANI.md`
- Güncel kapanış planı: `docs/SARTNAME_EKSIKLERI_UYGULAMA_PLANI.md`
- Kurulum ve kullanım: `README.md`
- Ajan davranış sözleşmesi: `openai.md`
- Değişiklik günlüğü: `docs/DEGISIKLIKLER.md`
