# Katman 2 — Altı Evrak Türü İçin Çift Korpus Testleri

Bu klasördeki metinler sentetiktir. Katman 1 eksiklik testlerinden farklı
olarak amaçları, Katman 2'nin aynı evrak için hem yaklaşık 30 bin parçalık
UAB/Karayolları korpusunda hem de yaklaşık 300 bin parçalık genel mevzuat
korpusunda araştırma yapmasını sağlamaktır.

Her metin 3–4 bağımsız hukuki/teknik mesele içerir. Bunlar sonuç sayısını veya
belirli bir maddeyi zorla garantilemez. Beklenti, modelin yalnız gerçekten
uygulanabilir ve alıntısı doğrulanabilen dayanakları göstermesidir. Metinlerde
kanun maddeleri yapay biçimde sıralanmamış; arama doğal olay ve talep diliyle
tetiklenmiştir.

## 01 — Dilekçe

- Dosya: `01_dilekce_k1_filo_islemleri.txt`
- Beklenen tür: `dilekce`
- Konu: K1 filosuna kiralık kamyon eklenmesi ve taşıt kartı
- Beklenen dayanak aileleri:
  - Karayolu Taşıma Yönetmeliği: K1, özmal/kiralık taşıt ve taşıt kartı
  - Araç muayene mevzuatı: geçerli periyodik muayene
  - Takograf mevzuatı: cihaz muayenesi ve mühür
  - Mesleki yeterlilik mevzuatı: SRC4 ve psikoteknik koşulları
- Karma korpus beklentisi: taşıma yetkilendirmesi 30K korpusu; genel teknik ve
  sürücü hükümleri 300K korpusu tarafından desteklenebilir.

## 02 — Şikâyet

- Dosya: `02_sikayet_sehirlerarasi_otobus.txt`
- Beklenen tür: `sikayet`
- Konu: şehirlerarası otobüste taşıma ve trafik güvenliği ihlalleri
- Beklenen dayanak aileleri:
  - Karayolu Taşıma Yönetmeliği: bilet, yolcu listesi ve terminal kullanımı
  - Sürüş/dinlenme ve takograf hükümleri
  - Karayolları Trafik Yönetmeliği: emniyet kemeri ve sürücü güvenliği
  - Araç muayene mevzuatı: muayenesiz veya teknik olarak uygunsuz araç
- Karma korpus beklentisi: taşıma işletmesi hükümleri 30K; trafik, takograf ve
  muayene hükümleri 300K korpusunda da karşılık bulmalıdır.

## 03 — İtiraz

- Dosya: `03_itiraz_arac_muayene_agir_kusur.txt`
- Beklenen tür: `itiraz`
- Konu: araç muayenesi ağır kusur kararının teknik dayanağı
- Beklenen dayanak aileleri:
  - Araç muayene istasyonları ve muayene usulü
  - Muayene kusur grupları: fren ve far kusurları
  - Karayolları Trafik Yönetmeliği: aracın teknik şartları
  - Takograf cihazlarının muayene ve mühür hükümleri
- Karma korpus beklentisi: UAB teknik düzenlemeleri 30K; trafik ve ölçüm
  hükümleri 300K korpusundan birlikte gelebilir.

## 04 — Talep

- Dosya: `04_talep_tehlikeli_madde_filo_islemleri.txt`
- Beklenen tür: `talep`
- Konu: akaryakıt tankerlerinin sevkiyat öncesi kayıt ve kontrol işlemleri
- Beklenen dayanak aileleri:
  - Tehlikeli maddelerin karayoluyla taşınması hükümleri
  - Tehlikeli madde taşıyan araçların teknik incelemesi
  - Tehlikeli madde güvenlik danışmanı görevlendirmesi
  - SRC5, zorunlu araç ekipmanı ve işaretleme hükümleri
- Karma korpus beklentisi: taşıma idaresi ve teknik uygulama 30K; ADR bağlantılı
  güvenlik, eğitim ve ekipman düzenlemeleri 300K korpusundan desteklenebilir.

## 05 — İzin

- Dosya: `05_izin_ubak_soguk_zincir.txt`
- Beklenen tür: `izin`
- Konu: C2 işletmesinin soğuk zincir yüküyle uluslararası taşıması
- Beklenen dayanak aileleri:
  - UBAK izin belgesi kullanım ve dağıtım esasları
  - Ülke/geçiş belgelerinin dağıtım esasları
  - Karayolu Taşıma Yönetmeliği: C2 ve taşıt kaydı
  - Bozulabilir gıda taşıyan özel ekipman, sürücü yeterliliği ve takograf
- Karma korpus beklentisi: uluslararası taşıma izinleri 30K; teknik uygunluk ve
  sürücü/takograf hükümleri 300K korpusundan da bulunabilir.

## 06 — Belge

- Dosya: `06_belge_yol_kenari_denetim_kayitlari.txt`
- Beklenen tür: `belge`
- Konu: yol kenarı denetimine ait kayıt ve karar örneklerinin istenmesi
- Beklenen dayanak aileleri:
  - Bilgi Edinme Hakkı mevzuatı: kişinin kendi idari kayıtlarına erişimi
  - Karayolu Taşıma Yönetmeliği: yetki belgesi ve taşıt kartı denetimi
  - Takograf/sürüş-dinlenme kayıtlarının denetimi
  - Trafik idari para cezası, ağırlık ölçümü ve araç muayene tespiti
- Karma korpus beklentisi: sektörel denetim 30K; bilgi edinme, ceza usulü ve
  teknik kayıt hükümleri 300K korpusundan birlikte gelmelidir.

## Manuel değerlendirme ölçütü

Başarılı bir Katman 2 çalıştırmasında:

1. Evrak türü yukarıdaki türle eşleşmelidir.
2. Arama izi, genel ve sektörel meseleleri kapsayan sorgular göstermelidir.
3. Nihai bölümde mümkünse en az üç farklı hüküm yer almalıdır.
4. Her bulgu evraktaki bir iddia/taleple ve birebir kaynak alıntısıyla
   bağlanmalıdır.
5. Yalnız kelime benzerliği bulunan hükümler uygulanabilir kabul edilmemelidir.
6. Sonuçlarda hem `leaf-*` hem `MEV-*` kaynaklarının görünmesi, iki korpusun da
   nihai bulgulara katkı verdiğine dair pratik bir göstergedir; ancak her
   çalıştırmada iki taraftan da hüküm kabul edilmesi garanti değildir.
