# Altı Evrak Türü — Eksik Bilgili Manuel Test Seti

Bu dosyalardaki bütün adlar, adresler, numaralar ve olaylar sentetiktir. Beklenen
çıktılar kelimesi kelimesine LLM metni değil; sınıflandırma ve doğrulama
sözleşmesidir.

## Ortak sınıflandırma sözleşmesi

LLM-1 `document_type` ve `general_document_type` alanlarının ikisinde de yalnız
şu altı değerden birini üretmelidir:

`dilekce`, `sikayet`, `itiraz`, `talep`, `izin`, `belge`

Konuya özgü daha ayrıntılı ad yalnız `operational_category` veya
`document_subtype` alanına yazılmalıdır.

## 01 — Dilekçe

- Dosya: `01_dilekce_eksik.txt`
- Beklenen tür: `dilekce`
- Beklenen operasyonel kategori: `genel_basvuru` veya erişilebilirlik önerisi
- Bilinçli kesin eksik: `talep` — metin gözlemi anlatıyor fakat kurumdan istenen
  somut işlem açıkça belirtilmiyor.
- Mevzuata dayalı diğer eksikler: `adres`, `imza`
- Bulunması gereken önemli bilgiler: gönderen `Deniz Aras`, tarih `14.08.2026`,
  konu ve iki erişilebilirlik gözlemi.
- Beklenen dayanaklar: `3071-M4-ADRES`, `3071-M4-IMZA`; konu mevcut olduğundan
  `3071-M6-KONU` eksik sayılmamalıdır.

## 02 — Şikâyet

- Dosya: `02_sikayet_eksik.txt`
- Beklenen tür: `sikayet`
- Beklenen operasyonel kategori: gürültü/yol çalışması şikâyeti
- Bilinçli kesin eksikler: `gonderen`, `adres`, `imza`
- Eksik sayılmaması gerekenler: `konu`, `tarih`, `konum`, `talep`
- Önemli bulgular: gece çalışma aralığı `00.30–04.00`, dört gecedir sürmesi,
  denetim ve gürültünün giderilmesi isteği.
- Beklenen dayanaklar: `3071-M4-AD-SOYAD`, `3071-M4-ADRES`, `3071-M4-IMZA`.

## 03 — İtiraz

- Dosya: `03_itiraz_eksik.txt`
- Beklenen tür: `itiraz`
- Beklenen operasyonel kategori: geçiş ihlali/ceza itirazı
- Bilinçli kesin eksik: `talep` — itiraz iradesi var fakat işlemin iptali,
  düzeltilmesi veya yeniden incelenmesi şeklinde beklenen sonuç belirtilmiyor.
- Biçimsel eksik: `imza`
- Önemli bulgular: bildirim numarası `2026/8472`, aracın serviste olduğu savı ve
  servis teslim tutanağı eki.
- Beklenen davranış: LLM-1 bunu genel `dilekce` veya `talep` yapmamalıdır.
  LLM-2 açık talep sonucunu ve imzayı eksik göstermelidir.

## 04 — Talep

- Dosya: `04_talep_eksik.txt`
- Beklenen tür: `talep`
- Beklenen operasyonel kategori: trafik güvenliği/levha ve yol çizgisi yenileme
- Bilinçli mevzuat eksikleri: `adres`, `imza`
- Eksik sayılmaması gerekenler: `gonderen`, `konu`, `tarih`, `konum`, `talep`
- Önemli bulgular: okul geçidi çizgilerinin silinmesi, levhanın görünmez olması
  ve iki ayrı yenileme isteği.
- Beklenen dayanaklar: `3071-M4-ADRES`, `3071-M4-IMZA`.

## 05 — İzin

- Dosya: `05_izin_eksik.txt`
- Beklenen tür: `izin`
- Beklenen operasyonel kategori: `gecis_yolu_on_izin`
- Bilinçli kesin eksikler: `sahiplik_belgesi`, `vaziyet_plani`
- Koşullu uyarı: tesisin belediye/mücavir alan dışında olduğu açıklandığı için
  `belediye_sinir_yazisi` istenmelidir. Katalogdaki kural koşullu ve uyarı
  seviyesinde olduğundan kesin eksikle aynı gösterilmemelidir.
- Eksik sayılmaması gerekenler: `gonderen`, `adres`, `tarih`, `konu`, `talep`,
  taşınmaz ada/parsel bilgisi. Sondaki ad, ıslak/e-imza doğrulaması değildir.
- Beklenen dayanaklar: `KGM-GECIS-M23-SAHIPLIK`, `KGM-GECIS-M23-VAZIYET`,
  koşullu olarak `KGM-GECIS-M23-BELEDIYE-YAZISI`.

## 06 — Belge

- Dosya: `06_belge_eksik.txt`
- Beklenen tür: `belge`
- Beklenen operasyonel kategori: `bilgi_talebi`
- Bilinçli kesin eksikler: `imza`, `talep` alanında mevzuata uygun açıklık
- Talep açıklığı gerekçesi: hangi yol veya yolların, hangi kesin tarih aralığının
  ve hangi rapor/harcama belgesi türlerinin istendiği ayrıntılı değildir.
- Eksik sayılmaması gerekenler: `gonderen`, `adres`, `tarih`, `konu`; genel bir
  belge isteme cümlesi vardır ancak mevzuattaki açıklık şartını karşılamaz.
- Beklenen dayanaklar: `4982-M9-IMZA`, `4982-M9-TALEP-ACIKLIGI`.

## 96abf26 resmî yazışma kontrolleri hakkında

`RY-10`–`RY-19` ve `RY-28`, yukarıdaki gelen evraklardan sonra sistemin ürettiği
resmî cevap/taslak üzerinde uygulanmalıdır. Beklenen taslakta başlık, sayı, geçerli
tarih, kısa konu, muhatap, makam ilişkisine uygun kapanış, imzalayan adı-soyadı ve
unvanı bulunmalıdır. Varsa ilgi, ek ve dağıtım listeleri boş veya yinelenen kayıt
içermemelidir. DETSİS/EBYS kaydı, imza yetkisi ve güvenli elektronik imza gibi
kurumsal doğrulamalar otomatik başarı olarak gösterilmemeli; insan doğrulaması
gerektirdiği belirtilmelidir.
