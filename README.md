# EvrakAI - Kamu Evrak ve Yazışma Karar Destek Sistemi

TEKNOFEST 2026 Yapay Zeka Dil Ajanları Yarışması 1. Senaryo için geliştirilen, tamamı sentetik verilerle çalışan yerel karar destek prototipi.

Sistem bir evrakı PDF, görsel veya metin olarak alır; OCR/metin çıkarımı, sınıflandırma, bilgi ve eksik alan tespiti, mevzuat RAG'i, sentetik belediye birimine yönlendirme ve resmî yazı taslağı üretimi yapar. Hiçbir karar veya taslak insan onayı olmadan kesinleşmez.

## Önemli Sınırlar

- Uygulama resmî karar vermez, elektronik imza atmaz ve evrak göndermez.
- Gerçek kamu evrakı veya gerçek kişi bilgisi kullanılmaz.
- Kurum ve birimler tamamen sentetiktir.
- Ollama aynı bilgisayarda yerel olarak çalışır.
- Analiz ve embedding model adları arayüzden seçilir; kod içinde sabit değildir.

## Bileşenler

- `frontend/`: React + Vite + TypeScript arayüz
- `backend/`: FastAPI, OCR, Ollama, NumPy RAG, SQLite, DOCX/PDF export
- `data/catalog/`: 10 evrak türü ve 12 sentetik belediye birimi
- `data/synthetic/`: Script ile üretilen ve henüz insan incelemesi bekleyen aday gold veri
- `resources/`: Resmî referanslar, veri kartları ve lisans kayıtları
- `runtime/`: Yüklenen belgeler, SQLite, vektör indeksi ve export dosyaları

## Ön Koşullar

- macOS/Linux
- Ollama
- Docker Desktop veya Python 3.11 + Node.js
- Yerel Ollama'da en az bir chat modeli ve `/api/embed` destekleyen embedding modeli

Ollama servisinin çalıştığını doğrulayın:

```bash
ollama serve
curl http://127.0.0.1:11434/api/tags
```

Model adlarını uygulamadaki ayar panelinden seçeceğiniz için README belirli bir modeli zorunlu tutmaz.

## Docker ile Çalıştırma

```bash
cp .env.example .env
make docker-up
```

Arayüz: `http://localhost:8080`

API dokümanı: `http://localhost:8000/docs`

Docker içindeki backend Ollama'ya ulaşamıyorsa `.env` içindeki `OLLAMA_BASE_URL` değerini kontrol edin. macOS Docker Desktop için varsayılan adres `http://host.docker.internal:11434` olur.

`make docker-up`, imajları doğrudan `docker build` ile üretip Compose'u `--no-build` ile başlatır. Bu yöntem, bazı Docker Desktop sürümlerinde Türkçe karakter içeren klasör adlarında görülen Compose/Buildx oturum anahtarı hatasını da önler.

## Yerel Geliştirme

Bağımlılıkları kurun:

```bash
make setup
```

Bir terminalde backend:

```bash
make backend
```

Başka terminalde frontend:

```bash
make frontend
```

Arayüz: `http://localhost:5173`

## İlk Kurulum Akışı

1. Ollama'yı başlatın.
2. Arayüzü açın.
3. Analiz ve embedding modelini seçin.
4. `Modelleri doğrula` düğmesine basın.
5. `İndeksi oluştur` ile mevzuat ve belediye birim vektörlerini hazırlayın.
6. Sentetik bir PDF/görsel/TXT yükleyin.
7. OCR metnini kontrol edip analizi başlatın.
8. Birim önerisini onaylayıp taslak oluşturun.
9. Taslağı düzenleyin, insan onayı verin ve DOCX/PDF indirin.

## Sentetik Veri

80 aday evrakı deterministik olarak üretmek için:

```bash
make synthetic
```

Üretilen kayıtlar `needs_review` durumundadır. Bir ekip üyesi alanları, beklenen birimi ve metni kontrol etmeden bu veri "gold" olarak raporlanmamalıdır.

## Test ve Kontroller

```bash
make test
make lint
```

Backend testleri Ollama olmadan çalışabilen servisleri kapsar. Gerçek model smoke testi, Ollama başlatıldıktan sonra arayüz veya API üzerinden yapılır.

İnsan tarafından onaylanmış tahmin/gold karşılaştırması için:

```bash
python3 scripts/evaluate_predictions.py predictions.jsonl
```

Değerlendirici sınıflandırma macro-F1, alan exact-match F1, eksik alan recall ve yönlendirme top-1/top-3 ölçülerini üretir. `needs_review` kayıtlarıyla resmî metrik yazılmasını varsayılan olarak engeller.

## Kaynak ve Lisans

Proje Apache License 2.0 ile lisanslanmıştır. Haricî kaynakların URL, lisans ve SHA-256 bilgileri `resources/manifests/sources.json` içindedir. Kamuya açık fakat açık veri lisansı belirtilmemiş resmî PDF'ler, uygulama verisi olarak yeniden lisanslanmamalıdır.
