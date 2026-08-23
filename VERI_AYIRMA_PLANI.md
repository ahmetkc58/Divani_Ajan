# Ulaştırma ve Altyapı Bakanlığı Verilerini Ayırma Planı

## 1. Amaç

Bu planın amacı, DETSİS/KAYSİS üzerinden elde edilen Ulaştırma ve Altyapı
Bakanlığı mevzuat arşivini, TEKNOFEST 2026 Kamu Evrak Akıllı Agent Sistemi
için kullanılabilir ve doğrulanabilir veri kümelerine ayırmaktır.

Projenin ana kapsamı **karayolu** olacaktır. Bakanlığın bütün mevzuatı ham
arşivde korunacak, fakat tamamı aktif RAG indeksine eklenmeyecektir.

## 2. Mevcut Veri Durumu

- Kaynak kurum: Ulaştırma ve Altyapı Bakanlığı
- DETSİS numarası: `24325150`
- Toplam mevzuat kaydı: **501**
- Toplam PDF: **501**
- Toplam sayfa: **5.245**
- Toplam boyut: yaklaşık **382 MB**
- Eksik veya fazladan mevzuat kimliği: **0**
- Bozuk PDF: **0**
- Şifreli PDF: **0**
- İlk üç sayfasında yeterli metin katmanı bulunmayan PDF: **39**

501 PDF ile DETSİS mevzuat listesindeki 501 kimliğin tamamı eşleşmektedir.

### 23 Ağustos 2026 uygulama durumu

Planın ilk teknik aşaması kodlanmış ve çalıştırılmıştır:

- `data/manifests/uab_legislation_manifest.json` oluşturuldu.
- `data/manifests/uab_legislation_manifest_review.csv` insan doğrulama kuyruğu
  oluşturuldu.
- 501 DETSİS kaydının tamamı 501 yerel PDF ile bire bir eşleşti.
- Eksik, yinelenen veya kayıtsız PDF kimliği bulunmadı.
- Başlık tabanlı açıklanabilir sınıflandırma 50 kaydı karayolu/genel aktif korpus
  adayı olarak işaretledi.
- Tam belge metin katmanı taramasında 58 PDF OCR gerektiriyor olarak
  işaretlendi; okuma hatası oluşmadı.
- 501 kaydın hiçbirine otomatik aktif RAG onayı verilmedi. Kapsam ve yürürlük
  insan tarafından doğrulanana kadar `approved_for_active_rag=false` kalacaktır.

Önceki 39 PDF sayısı yalnızca ilk üç sayfaya uygulanan ön kontrolden gelmektedir.
Manifestteki 58 PDF sayısı ise belgenin tüm sayfalarına uygulanan daha sıkı kalite
eşiğinin sonucudur; OCR iş planında güncel kuyruk olarak bu liste kullanılacaktır.

## 3. Temel Karar

501 belgenin tamamı proje arşivinde saklanacaktır. Ancak aktif RAG sistemine
yalnızca aşağıdaki özellikleri taşıyan belgeler alınacaktır:

1. Karayolu proje kapsamıyla doğrudan ilişkili olması.
2. Yürürlükte veya güncel uygulamada kullanılıyor olması.
3. Kaynağının ve mevzuat kimliğinin doğrulanabilmesi.
4. Belgenin metninin güvenilir şekilde çıkarılabilmesi veya OCR ile
   doğrulanabilmesi.
5. Evrak sınıflandırma, mevzuat bulma, yönlendirme veya resmî yazı hazırlama
   görevlerinden en az birine katkı sağlaması.

Denizcilik, havacılık, demiryolu ve haberleşme belgeleri aktif karayolu
indeksine eklenmeyecek; kapsam dışı arşivde tutulacaktır.

## 4. Kapsam Ayrımı

Karayolu verileri iki ayrı alan olarak ele alınmalıdır.

### 4.1 KGM: Karayolu altyapısı ve işletmesi

Ana demo kapsamı olarak önerilen alandır:

- Otoyol, devlet yolu ve il yolları
- Yol yapım ve bakım faaliyetleri
- Köprü, tünel, viyadük ve sanat yapıları
- Trafik güvenliği ve işaretleme
- Yol güzergâhı, proje, harita ve ÇED işlemleri
- Kamulaştırma ve taşınmaz işlemleri
- Yol kenarı tesis izinleri
- Otoyol işletmesi ve geçiş sistemleri
- Bölge müdürlüklerine yönlendirme

### 4.2 Karayolu taşımacılığı ve düzenleme

KGM kapsamından ayrı tutulacaktır:

- Yolcu ve eşya taşımacılığı
- Yetki belgeleri
- Taşıt kartları
- Araç muayenesi
- Takograf
- Servis taşımacılığı
- Tehlikeli maddelerin karayoluyla taşınması
- Uluslararası geçiş ve UBAK izin belgeleri

Bu iki alan aynı vektör koleksiyonunda kontrolsüz şekilde karıştırılmamalıdır.

## 5. Oluşturulacak Veri Kümeleri

```text
data/
├── raw_archive/
│   └── uab_all_legislation/          # 501 PDF, değiştirilmeden korunur
├── active/
│   ├── official_writing_rules/       # Resmî yazışma kuralları
│   ├── general_application_rules/    # Dilekçe, bilgi edinme vb.
│   ├── kgm_infrastructure/            # KGM yol ve altyapı mevzuatı
│   ├── road_transport/                # Karayolu taşımacılığı mevzuatı
│   ├── organization_units/            # Kurum/birim hiyerarşisi
│   └── unit_duties/                   # Birim görev ve yetkileri
├── review_required/
│   ├── ocr_required/                  # Metin katmanı yetersiz PDF'ler
│   ├── scope_uncertain/               # Alanı kesin belirlenemeyenler
│   └── validity_uncertain/            # Güncellik/yürürlük kontrolü gerekenler
└── out_of_scope/
    ├── maritime/
    ├── aviation/
    ├── railway/
    ├── communications/
    └── internal_personnel/
```

Bu dizin yapısı mantıksal hedeftir. Ham dosyalar taşınmadan önce manifest
hazırlanacak; ilk aşamada fiziksel taşıma yerine etiketleme tercih edilecektir.

## 6. Zorunlu Genel Kaynaklar

Karayolu alanından bağımsız olarak aşağıdaki kaynaklar aktif sistemde yer
almalıdır:

- Resmî Yazışmalarda Uygulanacak Usul ve Esaslar Hakkında Yönetmelik
- Resmî Yazışmalarda Uygulanacak Usul ve Esaslar Hakkında Yönetmelik Kılavuzu
- 3071 sayılı Dilekçe Hakkının Kullanılmasına Dair Kanun
- 4982 sayılı Bilgi Edinme Hakkı Kanunu
- Gerekli olduğu ölçüde kişisel verilerin korunmasına ilişkin kurallar
- Bakanlık ve KGM teşkilat/görev düzenlemeleri

Bu kaynaklar taslak hazırlama, eksik alan tespiti ve süreç kontrolü için ayrı
bir koleksiyonda tutulacaktır.

## 7. Karayolu Çekirdek Mevzuat Listesi

İlk aktif RAG veri setinde öncelikle şu kaynaklar bulunmalıdır:

- 6001 sayılı Karayolları Genel Müdürlüğünün Hizmetleri Hakkında Kanun
- 2918 sayılı Karayolları Trafik Kanunu
- 4925 sayılı Karayolu Taşıma Kanunu
- Karayolları Trafik Yönetmeliği
- Karayolu Taşıma Yönetmeliği
- KGM Görev, Yetki ve Sorumluluk Yönetmeliği
- Karayolu Altyapısı Güvenlik Yönetimi Hakkında Yönetmelik
- Trafik İşaretleri Hakkında Yönetmelik
- Tünel İşletme Yönetmeliği
- Karayolları kenarında yapılacak ve açılacak tesislere ilişkin düzenlemeler
- Yol çalışmalarında trafik güvenliği tedbirlerine ilişkin düzenlemeler
- Karayolu yolboyu mühendislik yapıları için afet düzenlemeleri
- Kamulaştırma ve KGM taşınmazlarıyla ilgili düzenlemeler
- Otoyol ve geçiş ücretlerine ilişkin düzenlemeler

Liste, mevzuat kimliği ve yürürlük durumu doğrulandıktan sonra genişletilecektir.

## 8. Belge Sınıflandırma Etiketleri

Her PDF için aşağıdaki alanları içeren bir manifest kaydı oluşturulacaktır:

```json
{
  "mevzuat_id": 0,
  "title": "",
  "document_type": "",
  "domain": "kgm_infrastructure",
  "subdomain": "traffic_safety",
  "scope_status": "active",
  "validity_status": "needs_verification",
  "text_layer_status": "available",
  "ocr_required": false,
  "source_pdf": "",
  "source_url": "",
  "official_gazette_date": "",
  "official_gazette_number": "",
  "reviewed_by": null,
  "review_notes": ""
}
```

### `domain` değerleri

- `official_writing`
- `general_application`
- `kgm_infrastructure`
- `road_transport`
- `maritime`
- `aviation`
- `railway`
- `communications`
- `internal_administration`
- `unknown`

### `scope_status` değerleri

- `active`
- `review_required`
- `out_of_scope`
- `archived`

## 9. Ayırma Yöntemi

### Aşama 1: Dosya ve kimlik eşleştirmesi

- Dosya adındaki sayısal kimlik `mevzuatId` olarak alınır.
- DETSİS mevzuat kaydıyla eşleştirilir.
- Başlık, tür, Resmî Gazete tarihi ve sayısı manifest dosyasına yazılır.
- Kimliği eşleşmeyen dosya aktif indekse alınmaz.

### Aşama 2: Kural tabanlı ön sınıflandırma

Başlık, mevzuat türü ve varsa ilk sayfa metni kullanılarak alan etiketi üretilir.
Anahtar kelime eşleştirmesi yalnızca aday üretmek için kullanılacaktır.

### Aşama 3: İçerik tabanlı sınıflandırma

- İlk bölüm, amaç, kapsam ve dayanak maddeleri çıkarılır.
- Belgenin hangi ulaşım alanını düzenlediği belirlenir.
- Birden fazla alanı ilgilendiren belgeler çoklu etiketlenir.

### Aşama 4: İnsan doğrulaması

- `active` olarak işaretlenecek belgeler ekip tarafından kontrol edilir.
- Eski ve yeni sürümler ayrılır.
- Yürürlükten kaldırılan belgeler aktif indeks dışında tutulur.
- Her aktif belge için doğrulayan kişi ve kontrol notu kaydedilir.

### Aşama 5: OCR

- Metin katmanı yetersiz olduğu belirlenen 39 PDF OCR kuyruğuna alınır.
- Türkçe OCR uygulanır.
- OCR çıktısı PDF görüntüsüyle örneklem yöntemiyle karşılaştırılır.
- Güvenilirliği doğrulanmayan OCR metni mevzuat cevabında tek kaynak olarak
  kullanılmaz.

### Aşama 6: Yapısal parçalama

Mevzuat metinleri sabit token boyutuyla rastgele bölünmeyecektir:

```text
Mevzuat
  → Bölüm
    → Madde
      → Fıkra
        → Bent
```

Her parçaya kaynak PDF, sayfa, mevzuat kimliği, madde ve yürürlük bilgisi
eklenecektir.

## 10. RAG Koleksiyonları

Önerilen aktif koleksiyonlar:

```text
official_writing_rules
general_application_rules
kgm_infrastructure_legislation
road_transport_legislation
organization_units
unit_duties
```

Kullanıcı evrakı önce alan sınıflandırmasından geçirilecek, daha sonra yalnızca
ilgili koleksiyonlarda arama yapılacaktır. Resmî yazışma kontrolünde ayrıca
`official_writing_rules` koleksiyonu sorgulanacaktır.

## 11. Kalite Kontrol Kuralları

Bir belge aktif RAG sistemine alınmadan önce:

- [ ] DETSİS/KAYSİS kimliği doğrulandı.
- [ ] Kaynak PDF açılıyor ve bozuk değil.
- [ ] Belgenin alanı doğrulandı.
- [ ] Yürürlük durumu kontrol edildi.
- [ ] Eski/yeni sürüm ilişkisi belirlendi.
- [ ] Metin katmanı veya OCR çıktısı kontrol edildi.
- [ ] Madde yapısı doğru çıkarıldı.
- [ ] Sayfa ve kaynak metadata'sı eklendi.
- [ ] En az bir örnek sorguyla retrieval testi yapıldı.

## 12. Başarı Ölçütleri

- Aktif veri setindeki belgelerin `%100` kaynak kimliği doğrulanmış olmalıdır.
- Kapsam dışı belge getirme oranı test setinde `%5` altında olmalıdır.
- Karayolu sorgularında doğru mevzuatın `Recall@5` değeri en az `%90` olmalıdır.
- Kaynak gösterilmeyen mevzuat iddiası üretilmemelidir.
- OCR gerektiren belgelerin tamamı işaretlenmiş olmalıdır.
- Yürürlük durumu belirsiz belge, nihai cevapta kesin hüküm kaynağı yapılmamalıdır.

## 13. Uygulama Sırası

1. 501 belge için ana manifest oluştur.
2. Genel yazışma kaynaklarını ayır.
3. KGM altyapı belgelerini ayır.
4. Karayolu taşımacılığı belgelerini ayrı koleksiyona ayır.
5. Denizcilik, havacılık, demiryolu ve haberleşme belgelerini kapsam dışı etiketle.
6. Belirsiz belgeleri inceleme kuyruğuna al.
7. 39 metin katmanı yetersiz PDF için OCR uygula.
8. Aktif belgelerin yürürlük durumunu doğrula.
9. Madde/fıkra/bent tabanlı parçalama yap.
10. Qdrant ve BM25 indekslerini oluştur.
11. Retrieval değerlendirme setini çalıştır.
12. Yalnızca doğrulanan koleksiyonları demo sistemine bağla.

## 14. Proje Notu

**Bütün Ulaştırma ve Altyapı Bakanlığı verileri doğrudan RAG sistemine
eklenmemelidir.** Tüm veri ham arşivde korunmalı; aktif sistem için genel resmî
yazışma kuralları, KGM altyapı mevzuatı ve karayolu taşımacılığı mevzuatı ayrı
veri kümelerine ayrılmalıdır. Bu ayrım yapılmadan kurulacak tek koleksiyon,
karayolu evraklarında denizcilik, havacılık veya demiryolu kaynaklarının
getirilmesine ve yanlış birim yönlendirmelerine neden olabilir.
