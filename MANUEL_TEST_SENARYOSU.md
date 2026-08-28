# YolYaz Manuel Test Senaryosu

Bu belge, Karayolu Evrak Akıllı Ajan Sistemi MVP'sinin tarayıcı üzerinden
tekrarlanabilir biçimde test edilmesi için hazırlanmıştır. Testlerde yalnızca
sentetik evrak girdileri kullanılmalıdır. Retrieval katmanı sabitlenmiş sekiz
belgeli `competition_snapshot` korpusunu kullanır; bu korpus güncel/yürürlükte
mevzuat veya hukuki görüş olarak sunulmamalıdır.

## 1. Test ortamını açma

Proje kökünde aşağıdaki komutları çalıştırın:

```powershell
$env:PYTHONPATH="src"
$env:KARAYOL_RETRIEVAL_MODE="hybrid"
$env:KARAYOL_CORPUS_MODE="competition_snapshot"
$env:KARAYOL_COMPETITION_SNAPSHOT_PATH="data/processed/competition_snapshot.json"
$env:KARAYOL_QDRANT_PATH="runtime/qdrant-competition-snapshot"
$env:KARAYOL_QDRANT_COLLECTION="competition_snapshot_chunks_v1"
$env:KARAYOL_EMBEDDING_LOCAL_FILES_ONLY="true"
$env:KARAYOL_EMBEDDING_DEVICE="cuda:0"
Remove-Item Env:QDRANT_URL -ErrorAction SilentlyContinue
python -m uvicorn karayol_agent.api:app --host 127.0.0.1 --port 8010
```

Önce `http://127.0.0.1:8010/ready` yanıtında `ready=true`,
`retrieval_mode=hybrid` ve **2.603/2.603 uyumlu nokta** bilgisini doğrulayın.
Ardından `http://127.0.0.1:8010` adresini açın. Üst bölümde yeşil durum
noktasıyla birlikte **RAG hazır** ve **Sabit yarışma snapshot'ı** ifadeleri
görünmelidir. Qdrant hazır değilse arayüz kırmızı **RAG HAZIR DEĞİL** durumunu
göstermelidir. Bilgisayarda LaTeX derleyicisi yoksa PDF oluşmaması normaldir;
`.tex` çıktısı yine oluşturulur.

## 2. Ana kabul senaryosu — yol bakım talebi

Amaç: Sınıflandırma, mevzuat arama, kaynak doğrulama, birim yönlendirme,
eksik bilgi tamamlama, LaTeX taslak üretimi ve insan onayını tek akışta sınamak.

| Adım | İşlem | Beklenen sonuç |
| --- | --- | --- |
| MT-A01 | Sol taraftan **A · Yol bakım talebi** senaryosunu seçin. | Sentetik yol bakım metni editöre yüklenir. |
| MT-A02 | **Evrakı işle** düğmesine basın. | Evrak türü **Yol bakım talebi**, birim **Örnek Yol Yapım ve Bakım Şube Müdürlüğü** (`ORKGM-YB-001`) olarak görünür. Yeşil “Senaryo beklentisi karşılandı” bildirimi çıkar. |
| MT-A03 | Genel sonuç alanını inceleyin. | Resmî yazı türü **Üst yazı**, şablon `ust_yazi_v1`; durum **Eksik bilgi bekleniyor** olur. |
| MT-A04 | **Kaynaklar** sekmesine geçin. | Beş sonuç da **Kaynak sözleşmesi geçti** ve **Sorgu alakası** bilgisini gösterir. Mühendislik fixture'ındaki ilgili metinsel adaylar KTY 21/b, KTK 14/b, KTK 10/b, KTK 13/c ve KTY 16/a'dır; araç servisi/bağlantı yolu maddeleri görünmez. Kartta korpus türü, chunk/madde/sayfa izi, alaka gerekçesi, **Güncellik: doğrulanmadı**, **Hukuki dayanak: kullanılamaz** ve snapshot uyarısı açıkça yer alır. |
| MT-A05 | **Alanlar** sekmesine geçin. | Metinden alınan alanların kaynağı gösterilir; ayrı **Zorunlu taslak alanları** bölümünde `sayi`, `imzalayan` ve `unvan` kullanıcı girdisi bekler. |
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
4. Kaynaklarda KTY 21/b, KTK 14/b, KTK 15, KTY 16/c ve KTY 19/b görünmelidir;
   kaza tutanağı, okul geçidi ve sürücü hasarı maddeleri görünmemelidir. Her
   kartta sorgu alakası skoru ve gerekçesi bulunmalıdır.
5. Örnek değerleri doldurup kaydedin. Sistem kalan taslak alanlarını da
   tamamlatmalı, şablonu `ust_yazi_v1` olarak yenilemeli, uygunluk kontrolünü
   geçmeli ve onay aşamasına geçmelidir.

Bu senaryo, sistemin kritik bilgileri uydurmayıp kullanıcıdan istemesini
kanıtlar.

## 4. Bilinçli sınır testi

1. **C · Paraphrase sınır testi** senaryosunu seçip çalıştırın.
2. Metin anlam bakımından yol yüzeyi bakım talebidir; ancak “asfalt”, “bakım”
   veya “çukur” gibi doğrudan anahtar kelimeleri kullanmaz.
3. Mevcut kural tabanlı sınıflandırıcı genel başvuru sonucu üretirse sarı **Beklenen MVP
   sınırı görüldü** bildirimi çıkar. Bu bir arayüz hatası değildir; embedding,
   reranker ve LLM tabanlı sınıflandırmayla iyileştirilecek ölçülebilir sınırdır.
   Jina dense RAG'ın çalışıyor olması sınıflandırıcıyı kendiliğinden semantik
   hâle getirmez; bunlar ayrı katmanlardır.
   Kaynaklar sekmesinde incelenmiş profil bulunmadığı için fail-closed boş sonuç
   ve **Sorgu kapısı** gerekçesi görünmelidir.
4. Gelecekte semantik sınıflandırma katmanı eklendiğinde aynı senaryo **Yol bakım talebi**
   olarak sonuçlanmalı ve arayüz bunu yeşil bildirimle göstermelidir.

## 5. Yakın ama cevaplanmaması gereken sorgu testi

Metin alanına aşağıdaki örnekleri ayrı ayrı yapıştırıp çalıştırın:

```text
Konu: Yol bakım ve asfalt çukuru
Yoldaki çukura girince aracımın jantı kırıldı. Belediyeden tazminat ve değer
kaybı almak istiyorum.
```

```text
Konu: Trafik güvenliği ve işaret levhası cezası
Trafik levhasına uymadığım için cezaya itiraz etmek istiyorum.
```

İlk metin `yol_bakim_talebi`, ikincisi `trafik_guvenligi_bildirimi` sınıfına
düşse bile **Kaynaklar** sekmesinde madde gösterilmemelidir. Sistem tazminat veya
ceza itirazı hükmü korpusta doğrulanmadığı için **Kaynak üretilmedi** ve sorgu
kapısı gerekçesini göstermelidir. `search_hits=[]`, doğrulanmış kaynak sayısı `0`,
`relevance_query_supported=false` ve `relevance_abstained=true` beklenir.

## 6. Dosya yükleme testi

1. Orta panelde **TXT / MD / PDF yükle** sekmesini açın.
2. `examples/manuel_test_yol_bakim_talebi.txt` dosyasını seçin veya alana sürükleyin.
3. **Evrakı işle** düğmesine basın.
4. Türün `yol_bakim_talebi`, birimin `ORKGM-YB-001` olduğunu doğrulayın.
5. İsteğe bağlı olarak küçük, metin katmanlı bir PDF deneyin. Taranmış PDF için
   çalışma zamanı OCR sağlayıcısı yoksa sistem anlaşılır bir `422` hatası
   vermelidir.

## 7. Otomatik canlı kabul turu

Sunucu açıkken manuel sözleşmenin kritik API adımları tek komutla yeniden
çalıştırılabilir:

```powershell
python -X utf8 scripts\run_production_demo_acceptance.py `
  --output reports\production_demo_acceptance_live_v2_2026-08-24.json
```

Komut, zorunlu kontrollerin tamamı geçerse `passed=true` içeren JSON üretir ve
`0` koduyla çıkar. Güncel sözleşme iki olumlu alaka ve üç fail-closed abstention
kontrolü dahil **23 zorunlu kontrol** içerir. Evrak kimlikleri her çalıştırmada
yeniden üretilir.

## 8. Test kayıt formu

Her test turunda şu bilgileri kaydedin:

- tarih, test eden kişi ve uygulama sürümü;
- senaryo/adım kimliği;
- beklenen ve gerçekleşen sonuç;
- evrak kimliği (`EVR-...`);
- hata varsa ekran görüntüsü ve tarayıcı konsol mesajı;
- sonuç: **Geçti**, **Kaldı** veya **Bloke**.

Gerçek kişi adı, T.C. kimlik numarası, telefon, adres veya kuruma ait kapalı
evrak bu yerel prototipe girilmemelidir.
