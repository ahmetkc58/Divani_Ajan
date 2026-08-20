# Sentetik Veri Kartı

## Amaç

Veri seti, Türkçe kamu evrakı sınıflandırma, alan çıkarımı, eksik bilgi tespiti ve sentetik belediye birimine yönlendirme davranışını test etmek için tasarlanmıştır. Model eğitimi veya gerçek kamu hizmeti kararı için tasarlanmamıştır.

## Kapsam

- 10 evrak türü
- 12 sentetik belediye birimi
- 80 deterministik aday gold kayıt
- Development ve şablon ailesi ayrılmış gizli test bölümü
- Eksik alan ve prompt-injection örnekleri

## Kişisel Veri

Gerçek ad, TCKN, adres, telefon, e-posta, sicil veya imza kullanılmaz. Alanlar `SENTETIK` işaretli değerler ve `.invalid` e-posta alanı kullanır.

## Üretim

`scripts/generate_synthetic_data.py` sabit seed ile veri üretir. Script çıktıları `needs_review` durumundadır. İnsan incelemesi tamamlandığında kayıt bazında `review_status=approved` yapılmalıdır.

`scripts/evaluate_predictions.py`, onaylı gold kayıtlar için sınıflandırma macro-F1, alan exact-match F1, eksik alan recall ve yönlendirme top-1/top-3 metriklerini hesaplar. `needs_review` kayıtları varsayılan olarak resmî ölçüme alınmaz.

## Bilinen Kısıtlar

- Metinler gerçek kamu evrakı dağılımını temsil etmez.
- Kurum ve birim görevleri sadeleştirilmiştir.
- Sentetik dil, gerçek kullanıcı yazım hatalarını sınırlı yansıtır.
- Gold etiketi ancak insan incelemesinden sonra kullanılabilir.
