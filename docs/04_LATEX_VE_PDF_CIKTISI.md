# LaTeX şablonları ve doğrudan PDF çıktısı

## Sorun

İlk sürümde kullanıcıya gösterilen LaTeX çıktısında boş veya teknik bölümler
bulunabiliyor ve ana indirme eylemi kaynak `.tex` dosyasına yöneliyordu.

## Yapılan temizlik

Dört sürümlü şablonda aşağıdaki bölümler yalnız veri varsa basılır:

- İlgi
- Ekler
- Dağıtım
- İletişim
- Paraf/koordinasyon
- Elektronik imza

Son kullanıcı belgesine ait olmayan `Belge üstverisi` ve `Doğrulanan kaynaklar`
blokları resmî çıktıdan çıkarıldı. Bu bilgiler kaybolmaz; süreç JSON'u ve
arayüzdeki kanıt alanlarında tutulur.

## PDF üretim zinciri

1. Ajanlar serbest LaTeX kodu üretmez; yalnız doğrulanan `DraftPayload` alanları
   sürümlü şablona yerleştirilir.
2. `compile_pdf=true` geldiğinde sistem yerel LaTeX derleyicisini arar.
3. Derleyici yoksa ReportLab tabanlı taşınabilir A4 üretici devreye girer.
4. `ArtifactResult` içine PDF yolu, derleyici adı ve güvenli indirme URL'si
   yazılır.
5. Frontend yalnız PDF indirme düğmesini ana kullanıcı eylemi olarak gösterir.

LaTeX indirme ucu geriye uyumluluk ve teknik teşhis için korunmuştur; normal
kullanıcı akışında gösterilmez.

## Artifact güvenliği

- İndirilecek dosya, yapılandırılmış `output_dir` altında olmak zorundadır.
- Yol traversal girişimleri ve dizin dışındaki artifact yolları reddedilir.
- Dosya yoksa açık 404 yanıtı üretilir.
- PDF yanıtı `application/pdf`, indirme başlığı ve güvenli cache başlıklarıyla
  döner.

## İlgili dosyalar

- `src/karayol_agent/latex/renderer.py`
- `templates/ust_yazi_v1/`
- `templates/cevap_yazisi_v1/`
- `templates/bilgilendirme_yazisi_v1/`
- `templates/eksik_bilgi_talebi_v1/`
- `frontend/static/app.js`
- `tests/test_artifact_download_regression_1.py`
- `tests/test_official_closing_regression_1.py`

## Test belgeleri

- `output/pdf/divani_ajan_test_yol_bakim_basvurusu.pdf`
- `output/pdf/divani_ajan_test_belirsiz_yonlendirme.pdf`

İkinci belge, yol bakım ile trafik güvenliği adaylarını yakın skorla üreterek
insan inceleme kapısını sınar.
