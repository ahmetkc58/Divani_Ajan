# Şartname Eksikleri Uygulama Planı

Bu plan, **2026 TYDA Teknik Şartnamesi - 1. Senaryo** ile mevcut Divani Ajan
uygulamasının karşılaştırılmasına dayanır. Amaç; rapor ve sunumdan önce kodu,
veri akışını, Qdrant entegrasyonunu, testleri ve teknik dokümantasyonu
tamamlamaktır.

Durumlar: **Var**, **Kısmi**, **Eksik**, **Dış onay gerekli**.

## 1. Şartname uyum özeti

| Şartname gereksinimi | Durum | Kapatılması gereken iş |
|---|---|---|
| OCR veya doğrudan metin okuma | Kısmi | Görsel dosya yükleme, sayfa bazlı OCR kararı, dosya doğrulama ve OCR kalite ölçümü |
| Evrak türünü belirleme | Var | Kör test setiyle doğruluk ölçümünü dondurma |
| Önemli bilgi unsurlarını çıkarma | Var | Alan bazlı precision/recall/F1 raporu üretme |
| Eksik bilgileri tespit etme | Var | Kritik eksiklerde işlemi durduran testleri genişletme |
| Mevzuat/yazışma kuralı önerme | Kısmi | Güncel ve insan onaylı mevzuatı Qdrant'a indeksleme; gerçek korpus ölçümü |
| Kısa ve öz özet üretme | Var | Kaynağa sadakat ve halüsinasyon kontrolü ekleme |
| Uygun resmî yazı türünü seçme ve taslak oluşturma | Kısmi | Resmî biçim ve üslup kurallarını kalite kapısına bağlama |
| Doğru birime yönlendirme önerisi | Var | Kör sette top-1/top-3 başarımını doğrulama |
| Süreci kullanıcıya açıkça bildirme | Var | Hata, düşük güven ve yeniden deneme senaryolarını tamamlamak |
| Gerektiğinde eksik bilgi isteme | Var | Kullanıcı düzeltmesinden sonra akışın güvenli devamını test etmek |
| İki görevin uçtan uca bütünlüğü | Kısmi | Gerçek Qdrant, OCR, düşük güven ve çevrimdışı senaryolarıyla tekrarlı demo testi |
| Veri, lisans ve Türkçe dokümantasyon kuralları | Kısmi | Dağıtım denetimi, lisans envanteri, temiz kurulum ve kullanıcı onaylı GitHub hazırlığı |

## 2. Öncelikli uygulama sırası

### P0 - Kaynak bütünlüğü ve veri sınırı

**Hedef:** Yanlış veya dağıtılamaz kaynakla geliştirme yapılmasını engellemek.

- Çalışma ağacındaki şartname PDF'sinin bütünlüğünü kanonik kopyayla karşılaştır.
  Mevcut dosyada bozuk PDF stream uyarıları bulunduğu için doğrulanmadan
  değiştirme veya yayımlama yapma.
- Gerçek kamu evrakını yasakla; yalnız kurgu evrak, yapay taslak ve kamuya açık
  mevzuat kullan.
- Her kaynak için URL, sürüm/yürürlük, SHA-256, lisans, OCR durumu, inceleyen kişi
  ve inceleme tarihi tut.
- Aktif RAG'e yalnız `approved_for_active_rag=true` ve
  `validity_status=verified` kayıtları kabul et.

**Bitti sayılması için:** Aktif korpus manifestinde kaynağı belirsiz, lisansı
belirsiz veya insan onaysız kayıt bulunmamalı.

### P1 - Aktif mevzuat korpüsü ve Qdrant

**Hedef:** Şartnamedeki mevzuat önerisini sentetik fallback yerine gerçek,
izlenebilir retrieval akışıyla çalıştırmak.

1. En az 3-4 güncel ve kapsamla ilgili kamuya açık mevzuat/kılavuz belgesini alan
   uzmanına doğrulat.
2. OCR gereken sayfaları görsel olarak kontrol et; madde, fıkra, bent ve sayfa
   izini koruyan chunk'lar üret.
3. Qdrant'ı çalıştır; versiyonlu koleksiyonu oluştur ve onaylı korpüsü Jina
   `retrieval.passage` vektörleriyle indeksle.
4. Koleksiyon geçişini atomik alias ile yap; eski veya yarım indeksin sorguya
   açılmasını önle.
5. `/ready` üzerinden şema, payload indeksleri, embedding sözleşmesi, nokta
   sayısı ve korpus fingerprint'ini doğrula.
6. Jina + Qdrant + BM25 + RRF akışını gerçek korpusta ölç; BM25 çevrimdışı
   fallback'ini koru.

**Bitti sayılması için:** Boş, eski ve yanlış fingerprint'li koleksiyonlar
fail-closed olmalı; en az 100 uzman etiketli sorguda Recall@5, MRR, atıf doğruluğu,
abstention ve sıcak p95 değerleri kayıt altına alınmalı.

### P2 - Belge alımı ve OCR dayanımı

**Hedef:** Evrakı yalnız temiz metin/PDF örneklerinde değil, gerçekçi taramalarda
da güvenli okuyabilmek.

- PNG, JPG ve TIFF yüklemeyi ekle.
- Uzantı yerine magic-byte/MIME doğrulaması yap; dosya boyutu, sayfa sayısı,
  piksel ve çözünürlük sınırları koy.
- PDF'de sayfa bazlı metin kalitesi ölç; yalnız zayıf sayfalara OCR uygula.
- OCR çıktısında sayfa ve güven skorunu koru; düşük güvenli alanları kullanıcı
  düzeltmesine gönder.
- Temiz, bozuk, döndürülmüş ve taranmış Türkçe belgelerden test seti oluştur.

**Bitti sayılması için:** Desteklenen tüm dosya türlerinde pozitif/negatif yükleme
testleri geçmeli; insan doğrulamalı sette CER/WER ve kritik alan F1 ölçülmeli.

### P3 - Resmî yazı kalite kapısı

**Hedef:** Üretilen metnin yalnızca okunabilir değil, resmî yazışma biçim ve
üslubuna da uygun olmasını sağlamak.

- Muhatap, sayı/tarih, konu, ilgi, ek, dağıtım, imza/unvan ve iletişim alanlarını
  şema ve kurallarla doğrula.
- `arz ederim`, `rica ederim` ve `arz ve rica ederim` seçimini makam ilişkisine
  bağla; belirsizlikte otomatik onay verme.
- Mevzuat atfının gerçekten retrieval kanıtında bulunmasını zorunlu tut.
- Kritik eksik, kaynak uyuşmazlığı veya uygunluk hatasında PDF üretimini/onayını
  durdur.
- LaTeX kaçışı, Türkçe karakterler, sayfa taşması, ek/dağıtım ve imza alanlarını
  render edilmiş PDF üzerinden test et.

**Bitti sayılması için:** En az 30 gold taslakta kritik biçim hatası kalmamalı;
yanlış atıf ve eksik kritik alanlar fail-closed sonuçlanmalı.

### P4 - İnsan onayı, hata yönetimi ve güvenlik

**Hedef:** Düşük güvenli kararların kullanıcıdan habersiz kesin karar gibi
sunulmasını önlemek.

- Düşük güven, alakasız evrak, çelişkili kaynak ve retrieval sonucu bulunamaması
  için açık `inceleme_gerekli` durumu ekle.
- Kullanıcı düzeltmesi ve onayından sonra süreci kaldığı yerden güvenli devam
  ettir.
- Süreç durumu ve artifact'lar için TTL ile kullanıcı tetiklemeli silme ekle.
- API yanıtlarında mutlak yerel yol, gizli anahtar ve iç hata ayrıntısı sızmasını
  engelle.
- Ağ erişimini varsayılan olarak loopback ile sınırla; dış erişimde kimlik
  doğrulama zorunlu olsun.

**Bitti sayılması için:** Abstention, insan onayı, yeniden deneme, yetkisiz dosya
erişimi ve veri silme testleri geçmeli.

### P5 - Bağımsız değerlendirme ve uçtan uca demo

**Hedef:** Şartnamenin uygulama puanını tekrar üretilebilir metriklerle kanıtlamak.

- Geliştirme, regresyon ve kör değerlendirme setlerini ayır; hash ile dondur.
- Sınıflandırma doğruluğu, alan F1, eksik bilgi başarımı, yönlendirme top-1/top-3,
  özet sadakati, taslak uygunluğu ve retrieval metriklerini tek koşuda üret.
- Başarılı, eksik bilgi, düşük güven, alakasız belge, OCR ve çevrimdışı fallback
  senaryolarını kapsayan uçtan uca test hazırla.
- Ana akışı en az 20 kez çalıştır; çakışma, kalıcı süreç ve artifact hatalarını
  kaydet.
- Demo için internet yokken BM25 fallback ile çalışan yedek akışı doğrula.

**Bitti sayılması için:** Sonuçlarda veri sürümü, Git commit'i, kirli çalışma
ağacı bilgisi, pay/payda, hata sayısı ve p95 süre bulunmalı; kör koşudan sonra
benchmark'a özel kod ayarı yapılmamalı.

### P6 - Açık kaynak teslim hazırlığı ve dokümantasyon

**Hedef:** Şartnamenin Türkçe dokümantasyon, açık kaynak ve üçüncü taraf hakları
koşullarını karşılamak.

- Temiz ortam kurulumunu ve paket/wheel çalıştırmasını doğrula; bağımlılık kilit
  dosyası ve SBOM üret.
- Kod, veri, model, OCR aracı ve PDF kaynaklarının lisans/atıf envanterini tamamla.
- Kısıtlı veya açık kaynak tanımına uymayan model ağırlıklarını depoya koyma;
  yalnız bağlantı, sabit sürüm, lisans ve kullanım talimatı ver.
- README'de kurulum, Qdrant başlatma, indeksleme, `/ready`, demo, test ve
  çevrimdışı fallback komutlarını tek akış halinde doğrula.
- Push öncesinde PDF, kişisel veri, secret, model cache'i, Qdrant storage'ı ve
  yeniden dağıtım haklarını incele.
- GitHub'a push etmeden önce kullanıcıdan açık onay al.

**Bitti sayılması için:** Temiz klonda kurulum ve demo smoke testi geçmeli;
dağıtılacak dosya listesi kullanıcı tarafından onaylanmalı.

## 3. Uygulama takvimi

| Sıra | İş paketi | Tahmini süre | Bağımlılık |
|---|---|---:|---|
| 1 | P0 kaynak/veri kapısı | 2-3 saat | İnsan kaynak doğrulaması |
| 2 | P1 aktif korpus ve Qdrant | 6-10 saat | P0, çalışan Qdrant, uzman onayı |
| 3 | P2 OCR ve dosya güvenliği | 4-6 saat | Test belgeleri |
| 4 | P3 resmî yazı kalite kapısı | 5-8 saat | Doğrulanmış yazışma kuralları |
| 5 | P4 insan onayı ve güvenlik | 3-5 saat | P1-P3 |
| 6 | P5 kör değerlendirme ve demo | 4-6 saat | P1-P4 |
| 7 | P6 paketleme ve teslim denetimi | 3-4 saat | P5 ve kod freeze |

P0-P1-P3-P5 tamamlanmadan proje şartname açısından bitmiş kabul edilmemelidir.
Rapor, sunum ve video; P6 sonunda kod dondurulup nihai metrikler alındıktan sonra
hazırlanacaktır.

## 4. Nihai tamamlanma kontrolü

- [ ] Şartnamedeki Görev 1 ve Görev 2 tek süreçte uçtan uca çalışıyor.
- [ ] Aktif mevzuat insan onaylı ve izlenebilir; gerçek Qdrant readiness başarılı.
- [ ] Düşük güven ve eksik bilgi durumlarında otomasyon güvenli biçimde duruyor.
- [ ] Resmî yazı taslağı kaynak, biçim ve üslup kapılarından geçiyor.
- [ ] Kör test ve 20 tekrarlı demo sonuçları kayıtlı.
- [ ] Çevrimdışı demo fallback'i doğrulandı.
- [ ] Lisans, atıf, veri ve gizlilik denetimi tamamlandı.
- [ ] Temiz kurulum ve çalıştırma dokümantasyonu doğrulandı.
- [ ] GitHub push'u için kullanıcı onayı alındı.
