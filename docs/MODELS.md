# Model Gereksinimleri ve Deney Kaydı

Uygulama model adlarını sabitlemez. Ollama'nın `/api/tags` yanıtındaki modeller arayüzde listelenir; kullanıcı bir analiz modeli ve bir embedding modeli seçer. Kayıt öncesinde analiz modelinin JSON şema çıktısı, embedding modelinin ise `/api/embed` desteği ve vektör boyutu doğrulanır.

## 20 Ağustos 2026 Yerel Smoke Testi

| Rol | Ollama etiketi | Yerel digest | Lisans beyanı | Durum |
|---|---|---|---|---|
| Analiz/taslak | `qwen2.5:0.5b` | `a8b0c5157701…` | Ollama paketindeki `LICENSE`: Apache-2.0, Alibaba Cloud | JSON şema testi geçti; küçük model olduğu için kalite yalnızca smoke-test seviyesindedir |
| Embedding | `bge-m3:latest` | `790764642607…` | Ollama paketindeki `LICENSE`: MIT | Türkçe probe embedding testi geçti |

Model ağırlıkları bu depoya eklenmez ve proje lisansı altında yeniden dağıtılmaz. Teslim ortamında seçilen modelin tam etiketi, digest'i ve kendi lisansı yeniden kaydedilmelidir. `*-cloud` etiketli modeller yerel veri işleme iddiasıyla kullanılmamalıdır.

## Kabul Edilen Yetenekler

- Analiz modeli Ollama `/api/chat` üzerinden `format=<JSON Schema>` kabul etmelidir.
- Embedding modeli Ollama `/api/embed` üzerinden her girdi için dolu ve sabit boyutlu vektör döndürmelidir.
- Embedding modeli değiştirildiğinde mevzuat/birim indeksi yeniden oluşturulmalıdır.
- Model çıktısı geçerli olsa bile karar, yönlendirme ve taslak insan incelemesi gerektirir.

## Kalite Kararı

Dinamik model seçimi operasyonel esneklik sağlar; farklı modellerin aynı kalitede olduğu anlamına gelmez. Yarışma raporunda yalnızca insan tarafından onaylanmış test seti üzerinde ölçülen sonuçlar paylaşılmalıdır. Smoke testi, başarı metriği olarak raporlanmamalıdır.
