# Sistemi çalıştırma ve test etme

## Gereksinimler

- Python 3.11 veya daha yeni sürüm; kilitli ortam Python 3.12 kullanır.
- `uv`
- Yerel LLM için Ollama ve seçilen model.
- PDF derleme için LaTeX isteğe bağlıdır; yoksa ReportLab fallback kullanılır.

Sistem Python 3.9 ile çalıştırılmamalıdır; projede kullanılan `StrEnum` ve bazı
modern dil özellikleri bu sürümde yoktur.

## Backend'i başlatma

```bash
uv run uvicorn karayol_agent.api:app --host 127.0.0.1 --port 8010
```

Kontrol adresleri:

- Sağlık: `http://127.0.0.1:8010/api/v1/system/health`
- Hazırlık: `http://127.0.0.1:8010/api/v1/system/readiness`
- Swagger: `http://127.0.0.1:8010/docs`

## Frontend'i başlatma

```bash
python3 -m http.server 3000 --directory frontend --bind 127.0.0.1
```

Arayüz: `http://127.0.0.1:3000`

Frontend başka portta çalıştırılırsa `frontend/config.js` ve
`KARAYOL_CORS_ALLOWED_ORIGINS` birlikte güncellenmelidir.

## Test PDF'leri

### Yol bakım testi

`output/pdf/divani_ajan_test_yol_bakim_basvurusu.pdf`

Beklenti: Yol bakım/asfalt sinyallerinin `ORKGM-YB-001` birimine yönelmesi.

### Belirsiz yönlendirme testi

`output/pdf/divani_ajan_test_belirsiz_yonlendirme.pdf`

Belge hem asfalt bakım hem trafik levhası/bariyer konularını içerir. Beklenti:

- İlk aday: `ORKGM-YB-001`
- Alternatif: `ORKGM-TG-001`
- Skor farkı yaklaşık `0.18`
- `routing_status=needs_review`
- `requires_human_review=true`

Her iki belge de tamamen kurgusaldır ve gerçek kişi/kurum verisi içermez.

## Otomatik testler

Yönlendirme ve ana akış:

```bash
uv run pytest -q \
  tests/test_organization_routing.py \
  tests/test_orchestrator.py \
  tests/test_api.py
```

Frontend/backend ve Swagger:

```bash
uv run pytest -q tests/test_frontend_backend_separation.py
```

Sağlam veri testleri hariç geniş regresyon koşusunda 391 test geçti. Son yakın
skor düzeltmesinden sonra yönlendirme, orkestrasyon ve API hedef paketindeki 10
test de geçti.

## Bilinen test engelleri

Tam depo koşusunda yönlendirmeden bağımsız, önceden mevcut aşağıdaki provenance
sorunları vardır:

- İki OCR aday metninin sabit SHA-256 değeri dosyayla uyuşmuyor.
- Bazı karantina JSON kayıtlarında başka bir Windows makinesine ait mutlak
  kaynak yolları bulunuyor.
- Snapshot relevance gold dosyasındaki kaynak hash'i mevcut snapshot ile
  uyuşmuyor.

Son tam koşuda bunlar 6 başarısız test ve 2 kurulum hatası üretti. Güven
kayıtlarını test geçirmek amacıyla otomatik olarak güncellemek doğru olmadığı
için bu dosyalara dokunulmadı.

## Manuel arayüz kontrolü

1. Backend hazırlık adresinin `ready=true` döndürdüğünü kontrol edin.
2. Frontend'i açıp PDF yükleme sekmesini seçin.
3. Belirsiz yönlendirme PDF'ini yükleyin.
4. Özet kartında birim, katalog `2026-07-16`, `%18` civarı skor farkı ve insan
   inceleme uyarısını doğrulayın.
5. Alternatif adayda Trafik Güvenliği İşaret biriminin bulunduğunu kontrol edin.
6. Eksik bilgileri tamamlayın, taslağı inceleyin ve yalnız yetkili test
   kullanıcısıyla onaylayın.
7. Taslak sekmesinden PDF'in doğrudan indirilebildiğini doğrulayın.
