# Snapshot Niyet ve Metin Alakası Değerlendirmesi — 24 Ağustos 2026

## Sonuç

Sabit yarışma snapshot'ında sekiz mühendislik fixture'ı canlı GPU/Jina/Qdrant
akışında **8/8 geçti**: dört cevaplanabilir olay ve aynı sınıflara düşen dört
no-answer/near-miss olay. Cevaplanabilir dilimde `Precision@5`, `Recall@5`, MRR,
`nDCG@5` ve hüküm ailesi `Recall@5` `%100`; no-answer diliminde abstention
doğruluğu `%100`, yanlış cevap ve yanlış abstention sayısı `0`dır.

| Ölçüt | Sonuç |
| --- | ---: |
| Cevaplanabilir sorgu | 4/4 |
| No-answer/near-miss | 4/4 doğru abstention |
| Precision@5 / Recall@5 | %100 / %100 |
| MRR / nDCG@5 | %100 / %100 |
| Hüküm ailesi Recall@5 | %100 |
| Hard-negative@5 | 0 |
| Sınıflandırma / profil doğruluğu | %100 / %100 |
| Yanlış cevap / yanlış abstention | 0 / 0 |

Tarihsel karşılaştırma yalnız ilk iki ana fixture için geçerlidir: eski hibrit
RRF yol bakımında `0/5`, hasarlı levhada `2/5` strict ilgili metinsel aday
döndürüyordu. V2 katmanı bu iki fixture ile iki olumlu paraphrase'in her birinde
`5/5` döndürdü. Jina dense kanalı kullanıldı ve fallback olmadı.

## Uygulanan yöntem

- Mevcut 2.603 Jina vektörü yeniden üretilmedi.
- Sınıflandırma etiketi tek başına kaynak üretemez. Kullanıcının gönderdiği
  özgün metinde yol yüzeyi için nesne + fiziksel bozukluk + onarım/güvenlik;
  trafik levhası için resmî işaret + hasar/işlev kaybı kavramları zorunludur.
- Tazminat, teknik şartname, ceza itirazı ve sigorta amaçlı yakın sorgular profil
  dışı sayılır; candidate retrieval çalıştırılmadan fail-closed abstention olur.
- Kontrollü expansion yalnız aday üretir. Expansion'dan gelen terimler özgün
  kullanıcı terimi veya lexical doğrulama kanıtı sayılmaz.
- Hibritte kanal başına top-20 korunur; RRF ile birleşen havuzdan en fazla 40 aday
  görünür chunk metni üzerinden `0.75` eşiğiyle denetlenir. BM25-only snapshot
  modu da aynı kapıdan geçer.
- Yalnız `context_text` içinde anlamlı olup gösterilen child metni yetersiz olan
  adaylar atıf yapılabilir sonuç sayılmaz. Desteklenmeyen profiller pass-through
  edilmez.

## İzlenebilir girdiler

- Gold/fixture seti: `data/evaluation/competition_snapshot_relevance_v1.json`
- Tarihsel iki-sorgu baseline: `reports/snapshot_relevance_baseline_2026-08-24.json`
- Tarihsel v1 aday: `reports/snapshot_relevance_candidate_2026-08-24.json`
- Güncel v2 canlı rapor: `reports/snapshot_relevance_candidate_v2_2026-08-24.json`
- Ölçüm betiği: `scripts/evaluate_snapshot_relevance.py`
- Corpus fingerprint:
  `ce0725cabadde785adadd49ba4ab2d7096e3b47a13f32c7ec5d1c442d88aa06b`

## Sınır

Bu sekiz kayıt, kuralları geliştirirken kullanılan şeffaf fixture regresyonudur;
bağımsız veya kör test değildir. Etiketler hukuk uzmanı onayı, mevzuat
güncelliği, yürürlük, yolun yetkili idaresi ya da somut olayda uygulanabilirlik
kanıtı değildir. Özellikle D-100 sorgusunda belediye görev maddeleri yalnız
metinsel adaydır. Production/genel saha başarımı iddiasından önce bağımsız
15-20 farklı sorgu ve ayrı yetki/uygulanabilirlik değerlendirmesi gerekir.
