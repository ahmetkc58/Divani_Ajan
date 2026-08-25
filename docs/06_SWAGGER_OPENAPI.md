# Swagger ve OpenAPI teslim sözleşmesi

## Amaç

Frontend ekibinin backend kodunu incelemeden istemci geliştirebilmesi için
makinece okunabilir OpenAPI 3.1 sözleşmesi üretildi.

## Dosya ve canlı adresler

- Teslim dosyası: `docs/swagger.json`
- Canlı OpenAPI: `http://127.0.0.1:8010/openapi.json`
- Swagger UI: `http://127.0.0.1:8010/docs`

`docs/swagger.json`, FastAPI uygulamasının `app.openapi()` çıktısıdır. Swagger
UI, Postman ve OpenAPI kod üreticilerine doğrudan aktarılabilir.

## Sözleşmedeki önemli modeller

- `TextProcessRequest`
- `InformationUpdateRequest`
- `ApprovalRequest`
- `ProcessState`
- `DocumentAnalysis`
- `RoutingRecommendation`
- `DraftPayload`
- `ArtifactResult`

`RoutingRecommendation` özellikle şu denetlenebilir alanları içerir:

- `unit_id`, `unit_name`, `hierarchy`
- `score`, `score_margin`
- `alternatives`
- `routing_status`
- `requires_human_review`
- `evidence`, `decision_basis`
- `organization_version`, `target_level`

## Frontend entegrasyon kuralı

Frontend, artifact yollarını kendisi üretmez; API'nin döndürdüğü
`pdf_download_url` değerini kullanır. Süreç durumu enum değerleri ve eksik bilgi
alanları yine sözleşmeden okunmalıdır. `needs_review` sonucu kesin havale gibi
gösterilmemelidir.

## Sürümleme ve güncelleme

Response modeli veya uç nokta değiştiğinde:

1. FastAPI modeli ve testleri güncellenir.
2. `app.openapi()` yeniden üretilerek `docs/swagger.json` yazılır.
3. Kaydedilen JSON ile canlı OpenAPI'nin eşitliği test edilir.
4. Geriye uyumsuz değişiklik gerekiyorsa yeni `/api/v2` değerlendirilir.

## Doğrulama

`tests/test_frontend_backend_separation.py` içindeki sözleşme testi, kaydedilen
Swagger dosyasının canlı uygulama şemasıyla birebir aynı olmasını zorunlu tutar.
