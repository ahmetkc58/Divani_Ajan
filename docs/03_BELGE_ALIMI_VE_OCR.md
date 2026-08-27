# Belge alımı, metin çıkarımı ve OCR

## Desteklenen girdiler

REST dosya yükleme ucu TXT, MD, PDF, PNG, JPG/JPEG ve TIFF dosyalarını kabul
eder. Dosya adı doğrudan yol olarak kullanılmaz; yalnız güvenli temel ad alınır
ve içerik geçici dosyada işlenir.

## Güvenli işleme kapıları

- Dosya türü yalnız uzantıya göre kabul edilmez; PDF ve görseller için içerik
  imzası kontrol edilir.
- Maksimum yükleme boyutu uygulanır.
- PDF sayfa sayısı, sayfa başına piksel, toplam OCR pikseli ve OCR süreleri
  sınırlıdır.
- Metin karakter sınırı aşıldığında sessiz kesme yapılmaz; işlem fail-closed
  durur.
- Geçici yükleme dosyası işlem sonunda silinir.
- OCR stderr ve iç sistem ayrıntıları kullanıcı yanıtına sızdırılmaz.

## PDF stratejisi

Metin katmanı yeterliyse doğrudan kullanılır. Karma PDF'de kalite sayfa bazında
değerlendirilir; yalnız boş veya zayıf sayfalar OCR'a gönderilir ve özgün sayfa
sırası korunur. Okunamayan sayfa varsa belge güvenilir şekilde okunmuş sayılmaz.

## Görsel stratejisi

PNG, JPEG ve TIFF güvenli decoder üzerinden açılır. Boyut/piksel sınırından
sonra OCR uygulanır. Kısa watermark metninin gerçek içerik gibi kabul edilmesini
önleyen kontroller bulunur.

## Alan çıkarımı korumaları

- Unicode ve görünmez karakter temizliği yapılır.
- Güvenli satır sonu birleştirme uygulanır.
- Gönderen, konu, tarih, sayı ve konum için kontrollü desenler kullanılır.
- Placeholder, geçersiz tarih ve talep cümlesinin kişi adı sanılması gibi
  false-positive durumları reddedilir.
- OCR düzeltmesi sınıflandırma güvenini yapay olarak artırmaz ve özgün retrieval
  kanıt metnini değiştirmez.

## Bilinen sınırlar

OCR çalışma yolu mevcut olsa da döndürülmüş sayfa, düşük DPI, faks/fotokopi ve
karma tablo düzenlerinde bağımsız insan etiketli CER/WER ölçümü tamamlanmadı.
Tam test paketinde iki OCR aday dosyasının sabit SHA-256 değerleriyle uyuşmayan
önceden mevcut provenance hataları vardır; güven kayıtları otomatik olarak
yeniden yazılmamıştır.

## İlgili dosyalar

- `src/karayol_agent/documents/extractor.py`
- `src/karayol_agent/backend/routes.py`
- `tests/test_extractor.py`
- `tests/test_ocr_candidate_ingestion.py`
