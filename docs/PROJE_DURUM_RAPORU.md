# EvrakAI Proje Durum Raporu

**Rapor tarihi:** 20 Ağustos 2026

**Proje:** TEKNOFEST 2026 Yapay Zeka Dil Ajanları Yarışması — 1. Senaryo

**GitHub:** <https://github.com/ahmetkc58/Divani_Ajan>

## 1. Kısa Özet

EvrakAI için sıfırdan, yerel çalışabilen ve Docker ile ayağa kaldırılabilen bir MVP geliştirildi. Sistem; sentetik bir evrakı PDF, görsel veya düz metin olarak kabul ediyor, metni çıkarıyor, belge türünü ve içeriğini analiz ediyor, eksik alanları belirliyor, ilgili mevzuat parçalarını buluyor, kurgu belediye birimine yönlendirme öneriyor ve insan onayına bağlı resmî yazı taslağı üretiyor.

Projenin temel ilkeleri şunlardır:

- Gerçek kamu evrakı ve gerçek kişisel veri kullanılmıyor.
- Kurum, birim ve başvuru örnekleri sentetik tutuluyor.
- Dil ve embedding modelleri yerel Ollama üzerinden çalışıyor.
- Sistem resmî karar vermiyor, elektronik imza atmıyor ve evrak göndermiyor.
- Taslaklar insan onayı olmadan dışa aktarılamıyor.
- Mevzuat sonuçları kaynak belge, sayfa bilgisi ve benzerlik skoru ile izlenebilir tutuluyor.

## 2. Şu Ana Kadar İzlenen Süreç

### 2.1. Başlangıç dosyaları incelendi

İlk olarak proje klasöründeki yarışma şartnamesi ve resmî yazışma kaynakları incelendi. Şartnameden projenin iki zorunlu görevi çıkarıldı:

1. Evrak sınıflandırma ve içerik analizi.
2. Resmî yazı taslaklama ve birim yönlendirme.

Gerçek kamu verisinin kullanılamaması, bütün dokümantasyonun Türkçe hazırlanması, uygulamanın açık kaynak yayımlanması ve iki görevin de çalışan demoda gösterilmesi temel gereksinimler olarak kaydedildi.

### 2.2. Proje planı genişletildi

`PROJE_PLANI.md`, yalnızca fikir listesi olmaktan çıkarılarak uygulanabilir bir teslim planına dönüştürüldü. Plana şu başlıklar eklendi:

- Tier 0, Tier 1 ve Tier 2 önceliklendirmesi.
- Uçtan uca veri ve kullanıcı akışı.
- Teknoloji yığını ve mimari kararlar.
- Sentetik veri üretim yaklaşımı.
- Test metrikleri ve kabul kriterleri.
- Güvenlik, insan onayı ve denetim izi kuralları.
- Demo senaryoları, riskler ve teslim çıktıları.
- Gün bazlı geliştirme takvimi.

Tier 0 MVP maddelerinin kodlama ve paketleme bölümü tamamlandı. Gold veri doğrulama, resmî performans ölçümü, demo videosu, teknik rapor ve sunum halen yapılması gereken teslim işleridir.

### 2.3. Haricî veri ve kaynak araştırması yapıldı

Projede işe yarayabilecek resmî belgeler, sentetik doküman veri setleri, Türkçe hukuk veri setleri ve OCR veri üretim araçları araştırıldı. Araştırma sonunda doğrudan “Türkçe kamu evrakı + doğru kurum birimi” problemine uyan, açık lisanslı ve kişisel veri riski taşımayan hazır bir veri kümesi bulunamadı.

Bu nedenle şu kararlar alındı:

- Ana evrak veri seti sentetik üretilecek.
- Gerçek kurum kayıtları ve gerçek başvurular kullanılmayacak.
- Resmî kaynaklar eğitim verisi gibi sunulmayacak; kural, taksonomi ve kaynak doğrulama amacıyla kullanılacak.
- Büyük haricî veri kümeleri doğrudan indirilmeyecek; önce lisans ve ihtiyaç değerlendirmesi yapılacak.
- Veri seti kartları ve araç lisansları, kararların izlenebilmesi için yerelde saklanacak.

### 2.4. Gerekli kaynaklar indirildi ve gereksiz olanlar temizlendi

Klasörde yalnızca doğrudan yararlı veya lisans/kaynak kaydı açısından gerekli içerikler bırakıldı:

| Kaynak | Kullanım amacı |
|---|---|
| Yarışma teknik şartnamesi | Gereksinim ve değerlendirme ölçütlerinin ana kaynağı |
| Resmî Yazışmalar Yönetmeliği | Yazışma alanları, kavramlar ve taslak doğrulama kuralları |
| Resmî Yazışmalar Kılavuzu | Biçim, alan yerleşimi ve örnek yazı yapıları |
| Standart Dosya Planı | Konu sınıfları ve sentetik yönlendirme taksonomisine referans |
| Standart Dosya Planı Rehberi | Konu kodu ve dosyalama mantığını anlamak |
| TR-DocVQA-Synth veri kartları | Olası OCR/layout test verisinin kapsam ve lisans incelemesi |
| Augraphy ve TRDG lisansları | İleride sentetik tarama/OCR varyantı üretilirse lisans kaydı |
| `sources.json` | URL, yayımcı, dosya boyutu, lisans durumu ve SHA-256 kaydı |

Mevzuat belgeleri hukukî karar vermek veya kullanıcıya hukuk danışmanlığı sunmak için kullanılmıyor. Görevleri; resmî yazışma yapısını doğrulamak, RAG sırasında ilgili kaynak parçasını göstermek ve modelin dayanaksız mevzuat iddiası üretmesini azaltmaktır.

### 2.5. Dosya envanteri oluşturuldu

`DOSYA_REHBERI.md` hazırlandı. Bu dosyada kök belgelerin, `resources/`, `data/`, `backend/`, `frontend/`, `scripts/`, `docs/` ve `runtime/` dizinlerinin neden bulunduğu ve nasıl kullanılacağı açıklandı.

## 3. Geliştirilen Uygulama

### 3.1. Backend

FastAPI tabanlı servis katmanı geliştirildi. Backend şu yetenekleri sağlıyor:

- PDF, PNG/JPEG ve TXT evrak yükleme.
- Dosya türü ve boyutu doğrulama.
- PyMuPDF ile doğrudan metin çıkarımı.
- Metin katmanı yetersizse Türkçe ve İngilizce Tesseract OCR fallback'i.
- OCR metnini analiz öncesinde kullanıcıya gösterme ve düzeltme.
- Ollama modellerini listeleme, analiz ve embedding modeli seçme.
- Seçilen modellerin gerekli yeteneklerini doğrulama.
- Belge türü sınıflandırma, yapılandırılmış alan çıkarımı ve özetleme.
- Belge türü kataloğuna göre deterministik eksik alan tespiti.
- Mevzuat ve belediye birimleri için embedding indeksi oluşturma.
- NumPy kosinüs benzerliği ile mevzuat RAG ve birim arama.
- Birim önerisini gerekçe ve skorla sunma.
- Resmî yazı, cevap, bilgilendirme veya eksik bilgi talebi taslağı oluşturma.
- Model zaman aşımı veya geçersiz çıktı durumunda güvenli şablon fallback'i.
- Taslak düzenleme ve açık insan onayı.
- Yalnızca onaylı taslakları DOCX veya PDF olarak dışa aktarma.
- Belge ve işlem bazlı denetim izi tutma.
- Belgeyle ilişkili runtime verilerini silme.

API, `/api/v1` altında sürümlenmiştir. Sağlık, model ayarları, indeksleme, belge, analiz, taslak, onay, export ve denetim izi uçları uygulanmıştır.

### 3.2. Frontend

React, Vite ve TypeScript ile tek sayfalı bir demo arayüzü geliştirildi. Arayüzde kullanıcı şu akışı izleyebiliyor:

1. Yerel analiz ve embedding modelini seçme.
2. Modelleri doğrulama.
3. Mevzuat ve birim indeksini oluşturma.
4. Belge yükleme.
5. Çıkarılan/OCR metnini kontrol edip düzeltme.
6. Analizi başlatma.
7. Tür, özet, alanlar, eksikler ve mevzuat kaynaklarını inceleme.
8. Önerilen birimi kontrol etme.
9. Taslak oluşturma ve düzenleme.
10. İnsan onayı verme.
11. DOCX veya PDF indirme.

İşlemler arka planda çalışırken iş durumu arayüzden takip ediliyor; hata ve düşük güven durumları kullanıcıya görünür biçimde bildiriliyor.

### 3.3. Veri katmanı

İki katalog hazırlandı:

- 10 sentetik evrak türü ve bunların zorunlu alanları.
- 12 kurgu Örnekşehir Belediyesi birimi ve yönlendirme anahtarları.

Sabit seed kullanan üretim script'i ile 80 sentetik TXT evrak ve aday beklenen çıktı üretildi. Örneklerde eksik alan ve prompt-injection benzeri güvenlik senaryoları da bulunuyor.

Bu 80 kayıt `needs_review` durumundadır. İnsan tarafından tek tek kontrol edilmeden “gold veri” sayılamaz ve bunlardan resmî başarı metriği raporlanamaz.

### 3.4. RAG ve model yaklaşımı

Uygulama belirli bir model adına kilitlenmedi. Ollama'da kurulu modeller arayüzden seçiliyor:

- Analiz/taslak modeli `/api/chat` üzerinden JSON Schema çıktısı verebilmelidir.
- Embedding modeli `/api/embed` üzerinden sabit boyutlu vektör üretmelidir.
- Model veya kaynak dosya özeti değiştiğinde indeks yeniden oluşturulur.
- Küçük corpus nedeniyle haricî vektör veritabanı yerine normalize NumPy matrisi kullanılır.

Yerel smoke testinde `qwen2.5:0.5b` analiz/taslak için, `bge-m3:latest` embedding için doğrulandı. Bu kontrol yalnızca teknik uyumluluk testidir; model kalite metriği değildir.

### 3.5. Güvenlik ve doğrulama önlemleri

- Belge metni güvenilmeyen girdi kabul edilir.
- Belge içindeki talimatlar sistem talimatı olarak uygulanmaz.
- Modelin dosya sistemi, araç veya ağ erişimi yoktur.
- Model çıktıları Pydantic şemalarından geçirilir.
- Çıkarılan bazı alanlar kaynak metindeki satırlarla grounded biçimde doğrulanır.
- Eksik alanlar model beyanından değil, katalog ve çıkarılmış alan karşılaştırmasından hesaplanır.
- Doğrulanmış kaynak parçası yoksa kesin mevzuat iddiası gösterilmez.
- Modelin uydurduğu ek, dağıtım veya kaynak listeleri kabul edilmez.
- İnsan onayı olmadan export engellenir.
- Gerçek kişisel veri yüklenmemesi uygulama ve dokümantasyon seviyesinde açıkça belirtilir.

## 4. Paketleme ve Çalıştırma

Proje hem yerel geliştirme ortamında hem Docker ile çalışacak şekilde hazırlandı:

- Backend ve frontend için ayrı Dockerfile oluşturuldu.
- `docker-compose.yml` ile iki servis birlikte ayağa kaldırıldı.
- Docker içinden ana makinedeki Ollama servisine erişim yapılandırıldı.
- `.env.example` ile güvenli örnek ayarlar sağlandı.
- `Makefile` içine kurulum, geliştirme, test, lint, sentetik veri ve Docker komutları eklendi.
- Bağımlılıklar `backend/uv.lock` ve `frontend/package-lock.json` ile sabitlendi.
- Türkçe karakter içeren klasör adlarında Docker Buildx sorunu için güvenli build akışı eklendi.

20 Ağustos 2026 itibarıyla çalışan servisler:

| Bileşen | Adres | Durum |
|---|---|---|
| Frontend | `http://localhost:8080` | Çalışıyor |
| Backend API | `http://localhost:8000` | Sağlıklı |
| API dokümanı | `http://localhost:8000/docs` | Erişilebilir |

## 5. Test ve Doğrulama Sonuçları

Son doğrulama turunda:

- Backend: **14 test geçti**.
- Frontend: **2 test geçti**.
- Ruff statik kod kontrolü: **temiz**.
- Vite production build: **başarılı**.
- Docker backend health check: **başarılı**.
- Docker frontend servisi: **çalışıyor**.

Backend testleri; analiz güvenlik ağı, katalog davranışı, taslak türü ve biçim kuralları, onay/export koruması, OCR fallback'i ve RAG parçalama davranışı gibi modelden bağımsız bölümleri kapsıyor.

Henüz raporlanmayan sonuçlar:

- Sınıflandırma macro-F1.
- Alan çıkarımı F1.
- Eksik alan recall.
- Birim yönlendirme top-1/top-3.
- Mevzuat retrieval top-3 başarımı.
- Taslak biçim uyum oranı.
- Uçtan uca p95 süre.

Bu metrikler ancak 80 aday kayıt insan tarafından doğrulanıp ayrı bir test seti oluşturulduktan sonra ölçülmelidir.

## 6. Dokümantasyon ve Lisanslama

Şu belgeler hazırlandı:

| Dosya | İçerik |
|---|---|
| `README.md` | Kurulum, çalıştırma ve ilk kullanım akışı |
| `PROJE_PLANI.md` | Detaylı kapsam, takvim, mimari, veri ve teslim planı |
| `DOSYA_REHBERI.md` | Klasördeki dosya ve dizinlerin neden var olduğu |
| `docs/ARCHITECTURE.md` | Gerçekleşen mimari ve veri akışı |
| `docs/DECISIONS.md` | Mimari karar kayıtları |
| `docs/DATA_CARD.md` | Sentetik veri kapsamı, üretimi ve sınırlamaları |
| `docs/MODELS.md` | Dinamik model gereksinimleri ve smoke-test kaydı |
| `resources/manifests/sources.json` | Haricî kaynak, lisans ve bütünlük envanteri |

Proje Apache License 2.0 ile lisanslandı. Haricî model ağırlıkları depoya alınmadı. Kamuya açık olmakla birlikte açık veri lisansı belirtilmeyen resmî PDF'ler, uygulamanın ürettiği veri gibi yeniden lisanslanmıyor; kaynak ve kullanım durumları ayrıca kaydediliyor.

## 7. GitHub'a Aktarım

Yerel proje Git deposuna dönüştürüldü ve GitHub'a gönderildi:

- Proje commit'i: `f2b1976` — `feat: implement EvrakAI MVP`
- Mevcut uzak depo geçmişini koruyan birleştirme commit'i: `041ccd3`
- Dal: `main`
- Uzak depo: `origin/main`

GitHub'da önceden bulunan `Initial commit` silinmedi veya force-push ile ezilmedi. İki geçmiş güvenli biçimde birleştirildi. `.env`, sanal ortamlar, `node_modules`, derleme çıktıları, runtime veritabanı, yüklenen evraklar, vektör indeksleri ve geçici dosyalar Git dışında bırakıldı.

## 8. Güncel Tamamlanma Durumu

| İş paketi | Durum |
|---|---|
| Gereksinim analizi | Tamamlandı |
| Kaynak ve veri araştırması | Tamamlandı |
| Kaynak/lisans envanteri | Tamamlandı |
| Sentetik kataloglar | Tamamlandı |
| 80 aday sentetik evrak | Üretildi, insan incelemesi bekliyor |
| Backend MVP | Tamamlandı |
| Frontend MVP | Tamamlandı |
| OCR ve metin düzeltme akışı | Tamamlandı |
| Mevzuat RAG | Tamamlandı |
| Birim yönlendirme | Tamamlandı |
| Taslak, onay ve export | Tamamlandı |
| Denetim izi | Tamamlandı |
| Otomatik testler ve Docker doğrulaması | Tamamlandı |
| GitHub yayını | Tamamlandı |
| İnsan onaylı gold set | Bekliyor |
| Sayısal kalite ölçümü ve hata analizi | Bekliyor |
| Demo videosu ve yedek kayıt | Bekliyor |
| Teknik rapor | Bekliyor |
| Sunum | Bekliyor |

## 9. Bundan Sonra Önerilen Sıra

1. 80 aday sentetik kaydı iki kişiyle gözden geçirip onaylamak.
2. Geliştirme ve gizli test ayrımını şablon ailesi sızıntısı olmayacak şekilde kesinleştirmek.
3. Uygulamayı daha güçlü bir yerel analiz modeliyle test etmek.
4. Gold set üzerinde bütün metrikleri ölçmek ve hata örneklerini sınıflandırmak.
5. En az üç demo senaryosu hazırlamak: başarılı, eksik/taranmış ve kapsam dışı/yanıltıcı evrak.
6. Demo sırasında kullanılacak modelleri, digest'leri ve lisansları son kez kaydetmek.
7. Teknik raporu ve sunumu gerçek ölçüm sonuçlarıyla hazırlamak.
8. Canlı demo provası yapmak ve yedek ekran kaydı almak.
9. Teslim öncesi lisans, kişisel veri, kaynak ve temiz kurulum kontrolünü tekrarlamak.

## 10. Hızlı Çalıştırma

Docker ile:

```bash
cp .env.example .env
make docker-up
```

Test ve kod kontrolü:

```bash
make test
make lint
```

Sentetik veriyi yeniden üretmek için:

```bash
make synthetic
```

Bu rapor yaşayan bir belgedir. Gold veri incelemesi, ölçüm, demo, teknik rapor veya teslim adımlarından biri tamamlandığında güncellenmelidir.
