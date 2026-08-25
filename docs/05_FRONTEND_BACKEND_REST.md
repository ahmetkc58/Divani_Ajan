# Frontend-backend ayrımı ve REST köprüsü

## Yeni mimari

```text
frontend/                    backend/
statik HTML/CSS/JS :3000     FastAPI :8010
          |                       |
          +----- REST + CORS -----+
                                  |
                         EvrakOrchestrator
                                  |
             analiz - retrieval - yönlendirme - PDF
```

Backend artık HTML, CSS veya JavaScript sunmaz. Frontend de Python paketini
doğrudan çağırmaz. İki parça yalnız JSON, multipart dosya yükleme ve PDF
artifact yanıtlarından oluşan REST sözleşmesiyle haberleşir.

## Dizin sorumlulukları

### `frontend/`

- `index.html`: uygulama kabuğu ve erişilebilir form yapısı.
- `static/app.css`: görsel düzen.
- `static/app.js`: REST çağrıları, süreç durumu ve indirme davranışı.
- `config.js`: backend origin ayarı.

### `src/karayol_agent/backend/`

- `routes.py`: sürümlü API router'ları, yükleme ve artifact yanıtları.
- `api.py`: FastAPI uygulaması, CORS ve router montajı.
- `orchestrator.py`: HTTP'den bağımsız iş akışı.

## Ana uç noktalar

| Yöntem | Uç nokta | Açıklama |
|---|---|---|
| GET | `/api/v1/system/health` | Servis ve sağlayıcı özeti |
| GET | `/api/v1/system/readiness` | Korpus ve bağımlılık hazırlığı |
| POST | `/api/v1/processes/text` | Metin evrakı işle |
| POST | `/api/v1/processes/file` | Dosya evrakı yükle ve işle |
| GET | `/api/v1/processes/{document_id}` | Süreç durumunu getir |
| POST | `/api/v1/processes/{document_id}/information` | Eksik alanları tamamla |
| POST | `/api/v1/processes/{document_id}/approval` | İnsan onayı ver |
| GET | `/api/v1/processes/{document_id}/artifacts/pdf` | PDF indir |
| GET | `/api/v1/processes/{document_id}/artifacts/tex` | Teknik LaTeX indir |

## CORS politikası

Varsayılan izin listesi yalnız şunları kapsar:

```dotenv
KARAYOL_CORS_ALLOWED_ORIGINS=http://127.0.0.1:3000,http://localhost:3000
```

Joker origin kabul edilmez. Yeni frontend adresi hem `frontend/config.js`
dosyasında backend adresiyle hem de backend CORS izin listesinde açıkça
tanımlanmalıdır.

## Geriye uyumluluk

Eski `/health`, `/ready` ve `/v1/process/...` yolları geçiş için korunmuştur;
OpenAPI şemasında görünmez. Yeni istemciler yalnız `/api/v1` kullanmalıdır.

## Doğrulama

`tests/test_frontend_backend_separation.py`; backend'in statik frontend
sunmadığını, tüm belgelenen yolların `/api/v1` ile başladığını, CORS allowlist
davranışını ve kaydedilen Swagger dosyasının canlı şemayla aynı olduğunu test
eder.
