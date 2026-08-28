# Resmî Yazışma Uygunluk Kuralları

## Kaynak sözleşmesi

Kural motorunun sürümü `2646-RG-2020-31151` olarak sabitlenmiştir. Birincil
kaynak, 10 Haziran 2020 tarihli ve 31151 sayılı Resmî Gazete'de yayımlanan 2646
sayılı Cumhurbaşkanı Kararı eki **Resmî Yazışmalarda Uygulanacak Usul ve Esaslar
Hakkında Yönetmelik**tir:

<https://www.resmigazete.gov.tr/eskiler/2020/06/20200610.pdf>

Depodaki `mevzuat-1.pdf` ve makine OCR çıktısı geliştirme sırasında sayfa
eşleştirmesi için kullanılmıştır. OCR raporundaki `human_verification_required`
ve `approved_for_active_rag=false` sınırları kaldırılmamıştır. Üretim öncesinde
kurumun DETSİS, EBYS, standart dosya planı ve imza yetkisi kayıtları ayrıca
yetkili kişi tarafından doğrulanmalıdır.

## Uygulanan kurallar

| Kimlik | Dayanak | Otomatik kontrol | Kalan insan/kurum kontrolü |
|---|---|---|---|
| `RY-10` | Madde 10 | Belge başlığında kurum adının varlığı | DETSİS başlık kaydının ve birim hiyerarşisinin doğruluğu |
| `RY-11` | Madde 11 | Sayının görünür yapısı | DETSİS, dosya planı ve EBYS kayıt geçerliliği |
| `RY-12` | Madde 12 | Noktalı tarih veya ay adıyla tarih biçimi | Elektronik imza zaman damgası |
| `RY-13` | Madde 13 | Konu alanının varlığı | Konunun kısa ve öz olup olmadığı |
| `RY-14` | Madde 14 | Muhatabın varlığı | DETSİS adı, makam ve adres doğruluğu |
| `RY-15` | Madde 15 | İlgi listesinin boş/yinelenen kayıt içermemesi | İlgi belgesinin tarih, sayı ve kronolojisi |
| `RY-16` | Madde 16/12 | Makam ilişkisi-kapanış uyumu ve tek kapanış | Makam ilişkisinin kurumsal doğruluğu |
| `RY-17` | Madde 17 | İmzalayan alanları ve e-imza uyarısı | İmza yetkisi ve güvenli e-imza doğrulaması |
| `RY-18` | Madde 18 | Ek listesinin boş/yinelenen kayıt içermemesi | Ek numarası, sayfa/adet ve dosya biçimi |
| `RY-19` | Madde 19 | Dağıtım listesinin boş/yinelenen kayıt içermemesi | Gereği/bilgi ayrımı ve dağıtım yetkisi |
| `RY-28` | Madde 28 | Kural sürümü ve temel sistem üstverisi | e-Yazışma üstveri paketinin tamamı |

`İlgi`, yazının bağlantılı olduğu önceki belgedir; RAG tarafından bulunan
mevzuat referansları değildir. Bu iki veri alanı ve doğrulamaları ayrı tutulur.

## Bilinçli sınırlar

- Kural motoru hukuki görüş vermez ve belgenin içeriğinin hukuken doğru olduğunu
  tek başına kanıtlamaz.
- Biçimsel olarak doğru görünen bir sayı, kurumsal sistemlerde kayıtlı olmayabilir.
- Makam ilişkisi yönlendirme kararından üretilir; nihai seçim insan onayına tabidir.
- Eksik alanlar taslak aşamasında uyarı olarak gösterilebilir ancak tamamlanmadan
  onay ve süreç bitirme kapısı geçilemez.
- Yönetmelikte bulunmayan asgari karakter sayısı gibi geliştirici eşikleri
  uygunluk kuralı olarak kullanılmaz.
