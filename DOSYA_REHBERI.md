# Dosya Rehberi

Bu belge, proje klasöründeki her dosyanın neden bulunduğunu, hangi aşamada kullanılacağını ve model/veri akışındaki rolünü açıklar.

## Hızlı Bakış

| Grup | Amaç |
|---|---|
| Yarışma belgeleri | Ne geliştirmemiz ve nasıl değerlendirileceğimiz |
| Mevzuat belgeleri | Resmî yazı kuralları, taslak doğrulama ve RAG |
| Proje dokümantasyonu | Mimari, takvim, veri stratejisi ve teslim planı |
| Resmî sınıflandırma kaynakları | Konu kodları ve sentetik yönlendirme taksonomisi |
| Veri seti kartları | Haricî veri setini indirmeden önce kapsam/lisans kontrolü |
| Lisans kayıtları | Kullanılabilecek veri üretim araçlarının hukuki kaydı |
| Kaynak manifestosu | URL, boyut ve dosya bütünlüğü takibi |

## Kök Dizindeki Dosyalar

### `2026_TYDA_SARTNAME_Birinci_Senaryo_TR_1_A8mT1 (1).pdf`

- **Nedir?** TEKNOFEST 2026 Yapay Zeka Dil Ajanları Yarışması 1. Senaryo teknik şartnamesi.
- **Neden var?** Projenin zorunlu iki görevini, teknik beklentilerini, veri kısıtlarını, teslim kurallarını ve puanlama sistemini tanımlar.
- **Nasıl kullanılacak?** Gereksinim ve kabul kriterlerinin ana kaynağıdır. Geliştirilen her özellik bu belgeyle karşılaştırılır.
- **Modele verilecek mi?** Hayır. Uygulama gereksinimi olarak ekip tarafından kullanılır.
- **Durum:** Zorunlu, korunmalı.

### `PROJE_PLANI.md`

- **Nedir?** Projenin güncel teknik ve operasyonel yol haritası.
- **Neden var?** Kapsamı, mimariyi, Tier 0 MVP'yi, veri stratejisini, zaman çizelgesini, test hedeflerini, riskleri ve teslim çıktılarını tek yerde toplar.
- **Nasıl kullanılacak?** Günlük geliştirme kararları ve ilerleme takibi bu dosyaya göre yapılır.
- **Modele verilecek mi?** Hayır. Ekip ve proje yönetimi belgesidir.
- **Durum:** Zorunlu ve yaşayan belge; kararlar değiştikçe güncellenmeli.

### `mevzuat-1.pdf`

- **Nedir?** Resmî Yazışmalarda Uygulanacak Usul ve Esaslar Hakkında Yönetmelik ve ek/örnekleri.
- **Neden var?** Resmî yazılarda bulunması gereken alanları, biçim kurallarını, imza/ek/dağıtım yapısını ve temel kavramları belirler.
- **Nasıl kullanılacak?** Madde bazlı RAG kaynağına ve deterministik taslak doğrulama kurallarına dönüştürülür.
- **Modele verilecek mi?** Seçilmiş ve doğrulanmış madde parçaları RAG bağlamı olarak verilebilir; PDF'nin tamamı her istekte modele gönderilmez.
- **Durum:** Zorunlu, korunmalı.

### `mevzuat-kılavuz.pdf`

- **Nedir?** Resmî yazışma yönetmeliğinin uygulama kılavuzu.
- **Neden var?** Başlık, sayı, tarih, konu, muhatap ve benzeri yazı alanlarını görsel örneklerle açıklar.
- **Nasıl kullanılacak?** Sentetik resmî yazı şablonları ve taslak format doğrulama kuralları hazırlanırken referans alınır.
- **Modele verilecek mi?** Gerekli kılavuz parçaları RAG bağlamı olabilir; görsel yerleşim kuralları tercihen kod tabanlı doğrulayıcıya aktarılır.
- **Durum:** Zorunlu, korunmalı.

### `DOSYA_REHBERI.md`

- **Nedir?** Okuduğunuz dosya envanteri ve kullanım rehberi.
- **Neden var?** Projeye katılan birinin klasör yapısını hızla anlamasını sağlar.
- **Nasıl kullanılacak?** Yeni dosya veya dizin eklendikçe güncellenir.
- **Modele verilecek mi?** Hayır.
- **Durum:** Korunmalı ve güncel tutulmalı.

## `resources/` Dizini

Bu dizin, internetten indirilen resmî referansları, veri seti kartlarını, lisans metinlerini ve kaynak manifestosunu tutar. Doğrudan uygulama kodu veya sentetik evrak veri seti değildir.

### `resources/README.md`

- **Nedir?** `resources/` dizininin kısa kullanım açıklaması.
- **Neden var?** Hangi kaynakların indirildiğini ve hangi büyük kaynakların bilinçli olarak indirilmediğini kaydeder.
- **Nasıl kullanılacak?** Kaynak paketiyle ilgili ilk okunacak belgedir.
- **Durum:** Korunmalı.

## `resources/official/` Dizini

### `resources/official/ssdp_v4_2024.pdf`

- **Nedir?** Devlet Arşivleri Başkanlığının Saklama Süreli Standart Dosya Planı V.4 belgesi.
- **Neden var?** Kamu belgelerinin konu alanlarını ve dosya kodlarını gösterir.
- **Nasıl kullanılacak?** Belgeden yalnızca proje senaryolarıyla ilgili 15-25 konu kodu seçilerek sentetik sınıflandırma/yönlendirme taksonomisine referans yapılır.
- **Modele verilecek mi?** Tamamı verilmez. Seçilmiş kod ve açıklamalar yapılandırılmış veri olarak kullanılabilir.
- **Durum:** Faydalı resmî referans, korunmalı.

### `resources/official/standart_dosya_plani_rehberi_v1.1.pdf`

- **Nedir?** Standart dosya planının nasıl uygulanacağını açıklayan resmî rehber.
- **Neden var?** Konu kodunun nasıl seçileceğini, dosya/vaka mantığını ve sınıflandırma yaklaşımını anlamamızı sağlar.
- **Nasıl kullanılacak?** Sentetik evrakları konu kodlarıyla etiketleme kuralları hazırlanırken referans alınır.
- **Modele verilecek mi?** Hayır; öncelikle ekip tarafından kural ve şema üretmek için kullanılır.
- **Durum:** Faydalı resmî referans, korunmalı.

## `resources/dataset_cards/` Dizini

Bu dizinde veri setinin kendisi değil, veri setini tanıtan metinler bulunur.

### `resources/dataset_cards/TR-DocVQA-Synth_README.md`

- **Nedir?** TR-DocVQA-Synth veri setinin ana kartı.
- **Neden var?** Veri setinin 15.000 sentetik Türkçe belge görseli, 235.000 soru-cevap çifti, belge aileleri ve CC BY 4.0 veri lisansı hakkındaki beyanını yerelde saklar.
- **Nasıl kullanılacak?** Veri setinin küçük bir alt kümesini indirip indirmeme kararında ve veri şemasını incelerken kullanılır.
- **Modele verilecek mi?** Hayır. Veri kartıdır; eğitim/test verisi değildir.
- **Durum:** Şimdilik korunmalı; veri setinden tamamen vazgeçilirse kaldırılabilir.

### `resources/dataset_cards/TR-DocVQA-Synth_dataset_card.md`

- **Nedir?** Aynı veri setine ait ek/alternatif dataset kartı.
- **Neden var?** Şema, bölümleme ve lisans bilgilerini ana README ile karşılaştırmak için tutulur.
- **Nasıl kullanılacak?** Alt küme seçimi ve lisans kaydı sırasında kontrol edilir.
- **Modele verilecek mi?** Hayır.
- **Durum:** Düşük hacimli destek kaydı; şimdilik korunmalı.

## `resources/tool_licenses/` Dizini

Bu dosyalar araç kodları değil, lisans metinleridir.

### `resources/tool_licenses/augraphy_LICENSE.txt`

- **Nedir?** Belge görüntülerine tarama, fotokopi, faks ve benzeri bozulmalar uygulayabilen Augraphy aracının MIT lisansı.
- **Neden var?** Aracı kullanırsak lisans uygunluğunu ve atıf yükümlülüğünü kaydetmek için.
- **Nasıl kullanılacak?** OCR test görüntüsü üretim aracı kurulursa dağıtım/lisans envanterine eklenir.
- **Modele verilecek mi?** Hayır.
- **Durum:** Augraphy kullanılacaksa korunmalı; kullanılmayacaksa kaldırılabilir.

### `resources/tool_licenses/trdg_LICENSE.txt`

- **Nedir?** TextRecognitionDataGenerator aracının MIT lisansı.
- **Neden var?** Sentetik OCR satırları üretmek için bu aracı seçersek lisans kaydını hazır tutmak için.
- **Nasıl kullanılacak?** Araç kurulursa yazılım/lisans envanterine dahil edilir.
- **Modele verilecek mi?** Hayır.
- **Durum:** TRDG kullanılacaksa korunmalı; kullanılmayacaksa kaldırılabilir.

## `resources/manifests/` Dizini

### `resources/manifests/sources.json`

- **Nedir?** İndirilen kaynakların makine tarafından okunabilir envanteri.
- **Neden var?** Her dosyanın kaynak URL'sini, yayımcısını, boyutunu, SHA-256 özetini, lisans durumunu ve projedeki kullanım kararını kaydeder.
- **Nasıl kullanılacak?** Dosya bütünlüğü doğrulamasında, lisans envanterinde ve teknik raporun kaynak bölümünde kullanılır.
- **Modele verilecek mi?** Hayır.
- **Durum:** Zorunlu kaynak kaydı, korunmalı ve yeni kaynaklarda güncellenmeli.

## Uygulama ve Veri Dizinleri

### `backend/`

- **Nedir?** FastAPI uygulaması, SQLite veri erişimi, Pydantic şemaları, OCR, Ollama istemcisi, RAG, analiz, taslak ve DOCX/PDF export servisleri.
- **Neden var?** Evrak akışının sürümlü `/api/v1` API'sini ve güvenlik kontrollerini tek yerde çalıştırır.
- **Önemli dosyalar:** `app/main.py` uçlar ve orkestrasyon; `app/services/` iş mantığı; `tests/` otomatik testler; `pyproject.toml` ve `uv.lock` tekrarlanabilir Python ortamı.
- **Durum:** MVP uygulama kodu; korunmalı.

### `frontend/`

- **Nedir?** React, Vite ve TypeScript tabanlı tek sayfalı kullanıcı arayüzü.
- **Neden var?** Model kurulumu, indeksleme, belge/metin kontrolü, analiz, yönlendirme, taslak, insan onayı ve export adımlarını görünür kılar.
- **Önemli dosyalar:** `src/App.tsx`, `src/api.ts`, `src/types.ts`, `src/styles.css`; `package-lock.json` bağımlılıkları sabitler.
- **Durum:** MVP arayüz kodu; `node_modules/` ve `dist/` üretilen dosyalardır ve Git'e girmez.

### `data/`

- `catalog/document_types.json`: 10 evrak türü, zorunlu alanlar ve açıklamalar.
- `catalog/municipal_units.json`: 12 kurgu Örnekşehir Belediyesi birimi ve yönlendirme anahtarları.
- `synthetic/`: Sabit seed ile üretilmiş 80 TXT evrak, `candidate_gold.jsonl` etiket adayları ve özet.
- `processed/`: İleride insan onaylı türevler için ayrılmış, şu anda boş dizin.

`candidate_gold.jsonl` kayıtları `needs_review` durumundadır; insan kontrolü olmadan gold veya başarı ölçümü olarak kullanılamaz.

### `scripts/`

- `generate_synthetic_data.py`: Kişisel veri içermeyen sentetik korpüsü deterministik olarak yeniden üretir.
- `evaluate_predictions.py`: İnsan onaylı gold ile tahminleri karşılaştırır; onaysız adaylardan resmî metrik üretilmesini varsayılan olarak engeller.

### `docs/`

- `ARCHITECTURE.md`: Gerçekleşen veri akışı ve güven sınırları.
- `DATA_CARD.md`: Sentetik veri kapsamı, üretimi ve kısıtları.
- `DECISIONS.md`: Temel mimari karar kayıtları.
- `MODELS.md`: Dinamik model gereksinimleri ve yerel smoke-test kaydı.

### `runtime/`

- **Nedir?** SQLite veritabanı, kullanıcı yüklemeleri, vektör indeksi ve onaylı export çıktılarının çalışma alanı.
- **Durum:** İçeriği geçicidir ve Git'e girmez; yalnızca `.gitkeep` korunur. Gerçek kişisel veri yüklenmemelidir.

## Kök Yapılandırma Dosyaları

- `README.md`: Kurulum, çalıştırma ve ilk kullanım akışı.
- `docker-compose.yml`: Frontend/backend konteynerleri ve yerel Ollama bağlantısı.
- `.env.example`: Güvenli örnek ortam ayarları.
- `Makefile`: Kurulum, geliştirme, test, lint ve sentetik veri komutları.
- `LICENSE` / `NOTICE`: Apache-2.0 proje lisansı ve atıf notları.
- `.gitignore`: Bağımlılık, derleme ve runtime çıktılarının sürüm kontrolü dışında tutulması.

## Koruma Özeti

- **Kesinlikle korunacak:** Yarışma şartnamesi, iki resmî yazışma belgesi, `PROJE_PLANI.md`, resmî SSDP kaynakları ve `sources.json`.
- **Karara bağlı destek dosyaları:** TR-DocVQA veri kartları ile Augraphy/TRDG lisansları.
- **Geçici/üretilen içerik:** `runtime/`, `frontend/node_modules/`, `frontend/dist/`, test cache'leri ve `tmp/`; Git'e eklenmez.
