# Proje Kaynak Paketi

Bu dizin, proje için indirilen resmî referansları ve haricî veri/araç lisans kayıtlarını içerir. Kaynaklar 20 Ağustos 2026 tarihinde indirilmiş ve SHA-256 özetleri `manifests/sources.json` dosyasına kaydedilmiştir.

## Dizinler

- `official/`: Kamuya açık resmî referans PDF'leri.
- `dataset_cards/`: Henüz tam olarak indirilmeyen veri kümelerinin kartları, kapsam ve lisans bilgileri.
- `tool_licenses/`: Daha sonra kullanılabilecek veri üretim araçlarının lisans metinleri.
- `manifests/`: Kaynak URL, boyut, hash, lisans ve kullanım kararları.

## Şu Anda İndirilenler

1. `official/ssdp_v4_2024.pdf`: Saklama Süreli Standart Dosya Planı V.4. Sentetik konu/yönlendirme taksonomisine referans olacak.
2. `official/standart_dosya_plani_rehberi_v1.1.pdf`: Dosya planının uygulama mantığını açıklayan resmî rehber.
3. `dataset_cards/TR-DocVQA-Synth_README.md` ve `TR-DocVQA-Synth_dataset_card.md`: Veri kümesinin kapsamı, şeması ve CC BY 4.0 lisans beyanı.
4. `tool_licenses/augraphy_LICENSE.txt`: Augraphy MIT lisansı.
5. `tool_licenses/trdg_LICENSE.txt`: TextRecognitionDataGenerator MIT lisansı.

## Bilinçli Olarak İndirilmeyenler

- TR-DocVQA-Synth'in tamamı yaklaşık 5,15 GB'tır. Kamu evrakı değil, ticari belge ağırlıklı olduğu için önce küçük bir alt küme ve alan şeması incelenecektir.
- Genel hukuk corpusları MVP için indirilmemiştir. Projenin ana mevzuat kaynağı klasördeki resmî yazışma yönetmeliği ve kılavuzudur.
- Augraphy ve TRDG kod depoları henüz klonlanmamış veya bağımlılık olarak kurulmamıştır. Yalnızca lisansları doğrulanmıştır.

## Kullanım Kuralı

Resmî kaynaklar proje deposunda ham eğitim verisi olarak yeniden yayımlanmamalıdır. Kaynak gösterilerek kural, konu kodu ve sentetik senaryo şeması türetmek için kullanılmalıdır. Yeni bir kaynak eklenmeden önce lisans, kişisel veri, boyut ve gerçek kamu verisi kontrolleri yapılmalıdır.
