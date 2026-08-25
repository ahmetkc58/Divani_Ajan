# Frontend–backend mimarisi

Uygulama iki bağımsız çalışma birimine ayrılmıştır:

```text
frontend/ (statik HTML, CSS, JavaScript; :3000)
        │
        │ JSON / multipart / PDF — REST + CORS
        ▼
src/karayol_agent/backend/ (FastAPI; :8010)
        │
        ├─ orkestrasyon ve ajanlar
        ├─ retrieval / Ollama
        └─ süreç ve PDF artifact depoları
```

Backend HTML, CSS veya JavaScript sunmaz. Frontend ise Python paketini doğrudan
çağırmaz; bütün işlemleri `/api/v1` REST sözleşmesi üzerinden yapar. Frontend
backend origin adresini `frontend/config.js` dosyasından okur. Backend yalnız
`KARAYOL_CORS_ALLOWED_ORIGINS` içindeki açık origin adreslerine tarayıcı erişimi
verir; joker origin kabul edilmez.

## REST sözleşmesi

| Yöntem | Uç nokta | İşlev |
|---|---|---|
| `GET` | `/api/v1/system/health` | Servis ve bağımlılık özeti |
| `GET` | `/api/v1/system/readiness` | Retrieval/ajan hazırlık kapısı |
| `POST` | `/api/v1/processes/text` | Metin evrakı işleme |
| `POST` | `/api/v1/processes/file?compile_pdf=true` | Dosya yükleme ve işleme |
| `GET` | `/api/v1/processes/{evrak_id}` | Süreç durumunu okuma |
| `POST` | `/api/v1/processes/{evrak_id}/information` | Eksik alanları tamamlama |
| `POST` | `/api/v1/processes/{evrak_id}/approval` | İnsan onayı verme |
| `GET` | `/api/v1/processes/{evrak_id}/artifacts/pdf` | PDF indirme |
| `GET` | `/api/v1/processes/{evrak_id}/artifacts/tex` | Teşhis amaçlı LaTeX indirme |

Eski `/health`, `/ready` ve `/v1/process/...` yolları geçiş sürecinde şema dışı
geriye uyumluluk uçları olarak korunur. Yeni istemciler yalnız `/api/v1`
sözleşmesini kullanmalıdır.

Frontend ekibine aktarılacak makinece okunabilir OpenAPI 3.1 sözleşmesi
[`swagger.json`](swagger.json) dosyasındadır. Dosya Swagger UI, Postman ve
OpenAPI kod üreticilerine doğrudan içe aktarılabilir.

## Organizasyon şemasıyla birim yönlendirme

Çalışma zamanı, değerlendirme amacıyla korunan `synthetic_units.json` yerine
`data/organization/kgm_units_2026-07-16.json` kataloğunu kullanır. Katalog,
16.07.2026 tarihli organizasyon şemasındaki merkez ve taşra birimlerini kapalı
bir hedef listesi olarak tutar; yönetici/personel adlarını içermez. Şemadan
çıkarılamayan görev açıklamaları `synthetic_draft`, yalnız konumu bilinen taşra
profilleri ise `chart_only` olarak işaretlidir.

Yönlendirme akışı şu güvenlik kapılarına sahiptir:

1. Evrak metni, çıkarılan alanlar ve konum sinyalleri katalog profilleriyle
   puanlanır; katalog dışında birim üretilemez.
2. Sonuçla birlikte eşleşme kanıtı, hiyerarşi, katalog sürümü, alternatifler ve
   ilk iki aday arasındaki skor farkı REST yanıtına yazılır.
3. Yeterli kanıt yoksa hedef `GENEL MÜDÜRLÜK` olur ve sonuç kesin havale değil,
   `needs_review` önerisi olarak döner.
4. Düşük sınıflandırma güveni, yakın adaylar ve yetki alanı uzman tarafından
   doğrulanmamış taşra eşleşmeleri insan incelemesini zorunlu kılar.

Şemada bölge müdürlüklerinin yalnız merkez şehirleri bulunduğundan katalog bu
şehirleri yetki alanının tamamı gibi yorumlamaz. İl-bölge kapsama matrisi ancak
kurumsal uzman onayı ve yeni katalog sürümüyle kesinleştirilebilir.
