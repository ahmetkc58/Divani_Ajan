# YolYaz Manuel Test Senaryosu

Bu belge, Karayolu Evrak Akıllı Ajan Sistemi MVP'sinin tarayıcı üzerinden
tekrarlanabilir biçimde test edilmesi için hazırlanmıştır. Testlerde yalnızca
sentetik veriler kullanılmalıdır.

## 1. Test ortamını açma

Proje kökünde aşağıdaki komutları çalıştırın:

```powershell
$env:PYTHONPATH="src"
uvicorn karayol_agent.api:app --host 127.0.0.1 --port 8010
```

Ardından `http://127.0.0.1:8010` adresini açın. Üst bölümde yeşil durum
noktasıyla birlikte **Sistem hazır** ifadesi görünmelidir. Bilgisayarda LaTeX
derleyicisi yoksa “PDF derleyicisi yok” bilgisi normaldir; `.tex` çıktısı yine
oluşturulur.

## 2. Ana kabul senaryosu — yol bakım talebi

Amaç: Sınıflandırma, mevzuat arama, kaynak doğrulama, birim yönlendirme,
eksik bilgi tamamlama, LaTeX taslak üretimi ve insan onayını tek akışta sınamak.

| Adım | İşlem | Beklenen sonuç |
| --- | --- | --- |
| MT-A01 | Sol taraftan **A · Yol bakım talebi** senaryosunu seçin. | Sentetik yol bakım metni editöre yüklenir. |
| MT-A02 | **Evrakı işle** düğmesine basın. | Evrak türü **Yol bakım talebi**, birim **Örnek Yol Yapım ve Bakım Şube Müdürlüğü** (`ORKGM-YB-001`) olarak görünür. Yeşil “Senaryo beklentisi karşılandı” bildirimi çıkar. |
| MT-A03 | Genel sonuç alanını inceleyin. | Resmî yazı türü **Üst yazı**, şablon `ust_yazi_v1`; durum **Eksik bilgi bekleniyor** olur. |
| MT-A04 | **Kaynaklar** sekmesine geçin. | En az bir kaynak “Doğrulandı” rozetiyle görünür; sentetik karayolu kuralı sonuçlar arasındadır. |
| MT-A05 | **Alanlar** sekmesine geçin. | Metinden alınan alanların kaynağı gösterilir; `sayi`, `imzalayan` ve `unvan` kullanıcı girdisi bekler. |
| MT-A06 | **Genel** sekmesinde **Örnek değerleri doldur**, ardından **Bilgileri kaydet ve taslağı yenile** düğmesine basın. | Eksik alanlar kapanır; durum **Kullanıcı onayı bekleniyor** olur ve uygunluk kontrolü geçer. |
| MT-A07 | **Taslak** sekmesini açın. | Kurum başlığı, sayı, tarih, konu, muhatap, gövde ve imza alanlarıyla resmî yazı önizlemesi görünür. **LaTeX taslağını indir** bağlantısı çalışır. |
| MT-A08 | **Akış** sekmesini açın. | Belge kabulünden uygunluk kontrolüne kadar ajan olayları zaman sırasıyla görünür. |
| MT-A09 | Genel sekmesinde onaylayan adı olarak `Yetkili Demo Kullanıcısı` bırakıp **Taslağı nihai olarak onayla** düğmesine basın. | Durum **Süreç tamamlandı** olur ve başarı bildirimi görünür. |

Ana senaryo, MT-A01–MT-A09 adımlarının tamamı beklenen sonucu veriyorsa
başarılıdır.

## 3. Eksik bilgi senaryosu

1. **B · Eksik trafik bildirimi** senaryosunu seçip evrakı işleyin.
2. Türün **Trafik güvenliği bildirimi**, birimin `ORKGM-TG-001` olduğunu
   doğrulayın.
3. En az `gonderen` ve `konum` alanlarının eksik bilgi formunda istendiğini
   doğrulayın. İlk şablon kararı `eksik_bilgi_talebi_v1` olmalıdır.
4. Örnek değerleri doldurup kaydedin. Sistem kalan taslak alanlarını da
   tamamlatmalı ve onay aşamasına geçmelidir.

Bu senaryo, sistemin kritik bilgileri uydurmayıp kullanıcıdan istemesini
kanıtlar.

## 4. Bilinçli sınır testi

1. **C · Paraphrase sınır testi** senaryosunu seçip çalıştırın.
2. Metin anlam bakımından yol yüzeyi bakım talebidir; ancak “asfalt”, “bakım”
   veya “çukur” gibi doğrudan anahtar kelimeleri kullanmaz.
3. Mevcut kural tabanlı MVP genel başvuru sonucu üretirse sarı **Beklenen MVP
   sınırı görüldü** bildirimi çıkar. Bu bir arayüz hatası değildir; embedding,
   reranker ve LLM entegrasyonuyla iyileştirilecek ölçülebilir sınırdır.
4. Gelecekte semantik katman eklendiğinde aynı senaryo **Yol bakım talebi**
   olarak sonuçlanmalı ve arayüz bunu yeşil bildirimle göstermelidir.

## 5. Dosya yükleme testi

1. Orta panelde **TXT / MD / PDF yükle** sekmesini açın.
2. `examples/yol_bakim_talebi.txt` dosyasını seçin veya alana sürükleyin.
3. **Evrakı işle** düğmesine basın.
4. Türün `yol_bakim_talebi`, birimin `ORKGM-YB-001` olduğunu doğrulayın.
5. İsteğe bağlı olarak küçük, metin katmanlı bir PDF deneyin. Taranmış PDF'nin
   OCR desteği yoksa sistem anlaşılır bir hata vermelidir.

## 6. Test kayıt formu

Her test turunda şu bilgileri kaydedin:

- tarih, test eden kişi ve uygulama sürümü;
- senaryo/adım kimliği;
- beklenen ve gerçekleşen sonuç;
- evrak kimliği (`EVR-...`);
- hata varsa ekran görüntüsü ve tarayıcı konsol mesajı;
- sonuç: **Geçti**, **Kaldı** veya **Bloke**.

Gerçek kişi adı, T.C. kimlik numarası, telefon, adres veya kuruma ait kapalı
evrak bu yerel prototipe girilmemelidir.
