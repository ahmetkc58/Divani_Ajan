# Karayolu Evrak Akıllı Ajan Sistemi

Bu depo, `PROJE_PLANI.md` içindeki TEKNOFEST 2026 projesinin çalışan MVP
uygulamasıdır. Sistem sentetik karayolu evraklarını uçtan uca işler:

1. metin/PDF alımı ve OCR fallback,
2. evrak sınıflandırma ve önemli alan çıkarımı,
3. eksik bilgi tespiti,
4. BM25 tabanlı mevzuat/kurum içi kural araması,
5. kaynak doğrulama,
6. resmî yazı türü ve LaTeX şablonu seçimi,
7. sentetik birime yönlendirme,
8. güvenli LaTeX taslağı oluşturma,
9. uygunluk kontrolü ve süreç bilgilendirmesi.

İlk sürüm çevrimdışı ve kural tabanlıdır. Ajan arayüzleri daha sonra LLM,
embedding, reranker ve grafik arama sağlayıcılarına bağlanabilecek şekilde
ayrılmıştır. Demo verileri sentetiktir; `veri_kaynaklari/` altındaki gerçek ve
herkese açık kayıtlar çalışma zamanında otomatik olarak kullanılmaz.

## Kurulum

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

Bu çalışma ortamında ana bağımlılıklar zaten kuruluysa kurulumsuz da
`$env:PYTHONPATH="src"` ile çalıştırılabilir.

## Komut satırı

```powershell
$env:PYTHONPATH="src"
python -m karayol_agent.cli process --file examples\yol_bakim_talebi.txt
```

Çıktılar varsayılan olarak `output/<evrak-id>/` altında saklanır. Sistemde
`xelatex`, `pdflatex` veya `tectonic` varsa PDF de derlenir; yoksa güvenli
`.tex` taslağı ve yapılandırılmış JSON çıktı üretilir.

Mevzuat PDF'sinin metin katmanını denetlemek ve Madde/Fıkra yapısında parçalamak:

```powershell
python -m karayol_agent.cli ingest `
  --file mevzuat-1.pdf `
  --title "Resmî Yazışma Yönetmeliği" `
  --output data\processed\resmi_yazisma.json
```

Kalite eşiğini geçmeyen PDF indekslenmez ve OCR gerektiği raporlanır. Düşük
kaliteli metni zorla indekslemek yalnızca inceleme amacıyla
`--allow-low-quality` seçeneğiyle mümkündür; üretim korpusunda önerilmez.

## Mevzuat kapsam ayırma ve doğrulama manifesti

DETSİS mevzuat kayıtlarını yerel PDF arşiviyle eşleştirmek, ulaşım alanı adayı
üretmek ve OCR kuyruğunu belirlemek için:

```powershell
$env:PYTHONPATH="src"
python -m karayol_agent.cli curate-legislation --inspect-pdfs
```

Komut iki çıktı üretir:

- `data/manifests/uab_legislation_manifest.json`: Makine tarafından okunabilir
  ana manifest, PDF eşleşmeleri, kapsam önerileri ve metin kalite sonuçları.
- `data/manifests/uab_legislation_manifest_review.csv`: Alan uzmanının kapsam,
  yürürlük ve aktif RAG onayı vermesi için inceleme tablosu.

Otomatik sınıflandırma hiçbir kaydı kendiliğinden aktif RAG verisi yapmaz.
`approved_for_active_rag` alanı insan doğrulaması tamamlanana kadar `false`
kalır. Böylece denizcilik, havacılık ve demiryolu mevzuatının karayolu
cevaplarına yanlışlıkla karışması önlenir.

## API

```powershell
$env:PYTHONPATH="src"
uvicorn karayol_agent.api:app --reload
```

- `GET /health`
- `POST /v1/process/text`
- `POST /v1/process/file`
- `GET /v1/process/{evrak_id}`
- `POST /v1/process/{evrak_id}/information`
- `POST /v1/process/{evrak_id}/approve`
- `GET /v1/process/{evrak_id}/artifacts/tex`
- `GET /v1/process/{evrak_id}/artifacts/pdf`

Swagger arayüzü: `http://127.0.0.1:8000/docs`

## Manuel test arayüzü

Yerel web arayüzünü örnek senaryolarla çalıştırmak için:

```powershell
$env:PYTHONPATH="src"
uvicorn karayol_agent.api:app --host 127.0.0.1 --port 8010
```

Tarayıcıdan `http://127.0.0.1:8010` adresini açın. Arayüz; hazır evrak
senaryolarını, TXT/MD/PDF yüklemeyi, sınıflandırma ve yönlendirme sonucunu,
doğrulanmış kaynakları, eksik bilgi tamamlama adımını, insan onayını ve LaTeX
çıktı indirmeyi tek ekranda sunar. Adım adım kabul testi için
[`MANUEL_TEST_SENARYOSU.md`](MANUEL_TEST_SENARYOSU.md) belgesini kullanın.

## Test

```powershell
$env:PYTHONPATH="src"
pytest
```

## Sayısal gold-set değerlendirmesi

48 kurgusal evraktan oluşan sabit veri setinde sınıflandırma, yönlendirme,
eksik alan, şablon seçimi ve mevzuat retrieval ölçümü yapmak için:

```powershell
$env:PYTHONPATH="src"
python -m karayol_agent.cli evaluate
```

Rapor `reports/evaluation_baseline.json` dosyasına yazılır. Veri setindeki 40
standart örnek ile doğrudan anahtar kelime kullanmayan 8 paraphrase challenge
örneği ayrı dilimler hâlinde raporlanır. Mevcut kural tabanlı başlangıç sürümü
standart dilimde başarılıdır; challenge dilimindeki düşük sonuçlar embedding,
reranker ve LLM entegrasyonunun ölçülebilir geliştirme hedefidir. Bu sonuçlar
gerçek saha başarımı olarak yorumlanmamalıdır.

## Güvenlik ve veri sınırı

- Model/kural motoru kaynakta bulunmayan kritik alanları uydurmaz.
- Eksik alanlar `kullanici_girdisi_gerekli` olarak işaretlenir.
- LaTeX özel karakterleri kaçış işleminden geçirilir.
- Şablonlar çalışma sırasında değiştirilemez.
- Shell escape kullanılmaz; derleme zaman aşımıyla sınırlandırılır.
- Gerçek vatandaş evrakı veya kapalı kamu verisi demo veri setine eklenmez.
