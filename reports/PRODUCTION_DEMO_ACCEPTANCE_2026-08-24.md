# Production-Demo Kabul Raporu — 24 Ağustos 2026

## Sonuç

Kalıcı yarışma snapshot'ını kullanan GPU destekli uçtan uca demo akışı **geçti**.
Canlı API üzerinden yürütülen **23/23 zorunlu kontrol başarılıdır**. Bu kabul,
uygulamanın teknik demo akışına ilişkindir; snapshot mevzuatının güncel veya
yürürlükte olduğu ve sonuçların hukuki görüş niteliği taşıdığı iddia edilmez.

## Doğrulanan çalışma zamanı

| Bileşen | Gerçekleşen |
| --- | --- |
| API / UI | `http://127.0.0.1:8010` |
| Retrieval | Hibrit BM25 + Jina dense + RRF + niyet/metin alaka kapısı v2 |
| Embedding | `jinaai/jina-embeddings-v3`, 1024 boyut |
| GPU | NVIDIA GeForce RTX 3050 Laptop GPU, `cuda:0` |
| Qdrant | Gömülü ve kalıcı `competition_snapshot_chunks_v1` |
| Readiness | 2.603/2.603 uyumlu vektör |
| Corpus fingerprint | `ce0725cabadde785adadd49ba4ab2d7096e3b47a13f32c7ec5d1c442d88aa06b` |
| Güven sınırı | `currentness_verified=false`, `legal_reliance_allowed=false` |

## Canlı senaryolar

| Senaryo | Sonuç |
| --- | --- |
| A — Yol bakım | `yol_bakim_talebi`, `ORKGM-YB-001`, `ust_yazi_v1`; dense kanal kullanıldı, fallback olmadı. Fixture'daki 5/5 ilgili metinsel aday döndü, 28 aday elendi. `sayi`, `imzalayan`, `unvan` tamamlandı; uygunluk skoru 0,96; LaTeX indirildi ve insan onayıyla `tamamlandi`. |
| B — Eksik trafik | `trafik_guvenligi_bildirimi`, `ORKGM-TG-001`, ilk şablon `eksik_bilgi_talebi_v1`; beş alan uydurulmadan istendi. Fixture'daki 5/5 ilgili metinsel aday döndü, 29 aday elendi. Bilgilerden sonra `ust_yazi_v1`, uygunluk 0,96 ve nihai durum `tamamlandi`. |
| C — Desteklenmeyen paraphrase | `genel_basvuru` sınıfına düşen olayda incelenmiş profil olmadığı için kaynak pass-through edilmedi; açık abstention üretildi. Sınıflandırma hâlâ kural tabanlıdır. |
| D — Çukur/tazminat near-miss | `yol_bakim_talebi` sınıfına rağmen amaç tazminat olduğundan kullanıcı-niyeti kapısı reddetti; hit ve doğrulanmış kaynak sayısı `0`. |
| E — Levha/ceza near-miss | `trafik_guvenligi_bildirimi` sınıfına rağmen amaç ceza itirazı olduğundan kullanıcı-niyeti kapısı reddetti; hit ve doğrulanmış kaynak sayısı `0`. |
| TXT yükleme | Gerçek multipart endpoint üzerinden dosya adı, metin çıkarımı, `yol_bakim_talebi` ve `ORKGM-YB-001` sözleşmesi geçti. |

## Bu turda kapatılan hatalar

- UI hazır rozeti artık yalnız `/health` yanıtına bakmıyor; gerçek `/ready`
  sonucunu ve Qdrant sözleşmesini kullanıyor. `503` veya `ready=false` kırmızı
  **RAG HAZIR DEĞİL** durumuna dönüşüyor.
- Alanlar sekmesi artık analiz alanlarıyla birlikte zorunlu `sayi`, `imzalayan`
  ve `unvan` taslak alanlarını, durumlarını ve kaynaklarını gösteriyor.
- Kaynak kartları korpus türü, güncellik, hukuki dayanak izni, doğrulama notu ve
  sabit snapshot uyarısını ayrı ayrı gösteriyor. Yanıltıcı “Doğrulandı” etiketi
  “Kaynak sözleşmesi geçti” olarak düzeltildi.
- Uygunluk denetimi başarısız ve eksik alan yoksa süreç artık fail-closed biçimde
  `hata` durumuna geçiyor; onay eylemi sunulmuyor.
- Eksik-bilgi talebi taslağında snapshot kaynakları varsa zorunlu
  güncellik/yürürlük uyarısı korunuyor.
- RRF ilk 5'ini doğrudan güvenilir saymak yerine iki incelenmiş olay tipi için
  özgün kullanıcı metni niyet kapısı, sorgu genişletme ve görünür metinde
  nesne+görev/giderme concept gate'i eklendi. Expansion kelimeleri kullanıcı
  lexical kanıtı sayılmaz ve BM25 snapshot yolu da aynı kapıdan geçer.
  Arayüz her kaynakta ayrı alaka skoru ve gerekçesi gösteriyor; eşik altındaki
  adaylar atılıyor ve yeterli aday yoksa sistem yanlış atıf yerine abstain ediyor.

## Otomasyon

Canlı sözleşme tekrar çalıştırılabilir:

```powershell
python -X utf8 scripts\run_production_demo_acceptance.py `
  --output reports\production_demo_acceptance_live_v2_2026-08-24.json
```

Test koleksiyonunda **315 test** vardır. Bu makinede proje gereksiniminin altında
Python 3.10 bulunduğu için alt süreçte doğrudan Python 3.11 `enum.StrEnum`
sözleşmesini kullanan tek CLI testi ortam kaynaklı olarak hariç tutuldu;
çalıştırılabilir paket **314/314 geçti**. UI/API/orchestrator hedef regresyonları,
JavaScript sözdizimi ve `git diff --check` ayrıca geçti.

## Kalan bilinçli sınırlar

- Yarışma snapshot'ı güncel hukuk kaynağı değildir ve hukuki dayanak olarak
  kullanılamaz; arayüz bunu açıkça gösterir.
- C paraphrase örneğinin sınıflandırması semantik değildir. Dense RAG mevcut olsa
  da sınıflandırıcı ayrı bir kural katmanıdır; bu yüzden örnek genel başvuruya
  düşer.
- Niyet/alaka fixture'ı iki ana sorgu, iki olumlu paraphrase ve dört no-answer
  örneği kapsar; kurallar geliştirilirken kullanıldığı için bağımsız test değildir.
  Genel başarı iddiası için ayrı 15-20 kör sorguya genişletilmelidir.
- Makinede LaTeX derleyicisi yoktur. Kaynak bölümü bulunan indirilebilir `.tex`
  çıktısı doğrulanmış, PDF derlemesi bu turda kapsam dışı kalmıştır.
- Makinedeki global Python 3.10 ortamı proje gereksinimi olan Python `>=3.11`in
  altındadır ve proje dışı paket sürüm çakışmaları taşır. Teslim provası izole
  Python `>=3.11` sanal ortamında tekrarlanmalıdır.

Ayrıntılı makine-okunur sonuç:
[`production_demo_acceptance_live_v2_2026-08-24.json`](production_demo_acceptance_live_v2_2026-08-24.json).
