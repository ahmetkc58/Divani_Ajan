# Retrieval Ablation Raporu — 24 Ağustos 2026

## Karar

Varsayılan retrieval yolu **BM25 + Jina Embeddings v3 + Qdrant + RRF** olarak
kalmalıdır. `jinaai/jina-reranker-v2-base-multilingual` entegrasyonu kodlandı ve
gerçek CPU koşusunda ölçüldü; bu dondurulmuş sette kaliteyi düşürüp gecikmeyi
artırdığı için varsayılan/üretim akışında etkinleştirilmemiştir.

Bu deney yalnızca 48 kayıtlık sentetik gold set üzerindedir. Kamu mevzuatı
kanıtı veya hukuk uzmanı onayı değildir.

## Sonuçlar

| Yöntem | Recall@5 | MRR | Parafraz Recall@5 |
|---|---:|---:|---:|
| BM25 | 0,8056 (29/36) | 0,8056 | 0,1250 (1/8) |
| Jina v3 + Qdrant + BM25 + RRF | **1,0000 (36/36)** | **0,9097** | **1,0000 (8/8)** |
| Hibrit + Jina reranker v2 | 0,9722 (35/36) | 0,8806 | 0,8750 (7/8) |

Hibrit sistem BM25'e göre Recall@5'i `+0,1944`, MRR'ı `+0,1041` artırdı.
Reranker ise hibrite göre Recall@5'te `-0,0278`, MRR'da `-0,0291` değişim
üretti. Reranker'ın tek yeni gold kaybı `HASAR-08` kaydıdır: beklenen
`SENT-KRY-003` parçası ilk beş dışına itilmiştir.

## Çalışma zamanı

- Jina v3 sentetik yedi parçalık indeksleme ve pinli yerel model yükleme:
  `6,711657 sn`.
- Ana hibrit geçiş: 48 dense sorgu, toplam `37,510201 sn`, ortalama
  `781,463 ms/sorgu`; dense sağlık sonucu `48/48` başarılı, `0` hata ve `0`
  fallback.
- Reranker değerlendirme geçişinin ek dense maliyeti: 48 sorgu, toplam
  `32,678964 sn`, ortalama `680,812 ms/sorgu`; ek dense sağlık sonucu `48/48`
  başarılı, `0` hata ve `0` fallback.
- Reranker: 48 skor çağrısı, toplam `178,757154 sn`, ortalama
  `3.724,107 ms/çağrı`.
- Ortam: Windows, CPU, 14 thread; Transformers `4.57.6`.

Reranker gecikmesi ayrı model skor çağrısıdır; uygulamanın tüm uçtan uca
gecikmesi olarak yorumlanmamalıdır.

## Tekrarlanabilirlik

- Birleşik özet: `reports/evaluation_retrieval_comparison_2026-08-24.json`
- BM25 ayrıntısı: `reports/evaluation_bm25_2026-08-24.json`
- Hibrit ayrıntısı: `reports/evaluation_hybrid_jina_qdrant_2026-08-24.json`
- Reranker ayrıntısı: `reports/evaluation_hybrid_reranked_2026-08-24.json`
- Jina/Qdrant smoke: `reports/jina_qdrant_smoke_2026-08-24.json`

Birleşik özet; model ve remote-code commitlerini, `retrieval.passage` /
`retrieval.query` görevlerini, kaynak dosya SHA-256'sını ve kanonik corpus
fingerprint'ini birlikte kaydeder. Rapor yolları proje-görelidir.
Şema `1.2`, herhangi bir kayıtta dense hata/boş sonuç/fallback görülürse BM25
sonucunun hibrit etiketiyle yazılmasını engeller. Dense-only hukuki kanıt kabulü
ayrıca ham cosine `>= 0,20` mutlak eşiğine bağlıdır; RRF göreli skoru tek başına
kanıt doğrulaması değildir.

Reranker tekrar değerlendirilmek istenirse önce daha geniş ve insan etiketli
bir doğrulama seti hazırlanmalı; aday sayısı, sorgu biçimi ve model seçimi ayrı
ablationlarla ölçülmelidir. Model kartındaki `CC BY-NC 4.0` lisansı ticari
kullanım öncesinde ayrıca incelenmelidir.
