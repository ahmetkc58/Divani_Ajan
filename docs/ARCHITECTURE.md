# Mimari

## Veri Akışı

```text
React arayüz
    |
    v
FastAPI -> SQLite / runtime dosyaları
    |
    +--> PyMuPDF -> kalite kontrol -> Tesseract tur+eng
    |
    +--> Ollama chat -> tür, konu, alanlar, özet
    |
    +--> Ollama embed -> NumPy mevzuat ve birim araması
    |
    +--> deterministik eksik alan / taslak kuralları
    |
    +--> Ollama chat -> taslak içeriği
    |
    +--> insan onayı -> DOCX / PDF
```

## Tasarım Kararları

- Ayrı bir agent framework kullanılmaz. Modüler orkestratör tarafından sıralı çalıştırılır.
- Bir belge için normal akışta iki chat görevi yapılır: analiz ve taslak. Geçersiz JSON için her görev bir kez yeniden denenebilir.
- Eksik alanlar LLM tarafından değil katalog ve yapılandırılmış alanlar karşılaştırılarak hesaplanır.
- Birim yönlendirme taslak üretiminden önce kesinleşir.
- LLM sayfa yerleşimi üretmez; DOCX ve PDF aynı `DraftV1` nesnesinden render edilir.
- Vektör corpus küçük olduğu için haricî vektör veritabanı yerine normalize NumPy matrisi kullanılır.
- Model ve kaynak hash'i değiştiğinde indeks yeniden oluşturulur.
- Bozuk/taranmış mevzuat sayfaları Tesseract ile okunur; OCR artifaktı taşıyan parçalar doğrulanmış dayanak olarak gösterilmez.
- Taslak modeli zaman aşımına uğrarsa güvenli, deterministik şablon devreye girer; modelin uydurduğu ek, dağıtım ve kaynak listeleri kabul edilmez.

## Güven Sınırları

- Belge metni güvenilmeyen veri kabul edilir.
- Modelin tool, dosya sistemi veya ağ erişimi yoktur.
- Model çıktısı Pydantic şemasından geçer.
- Doğrulanmış kaynak parçası yoksa mevzuat iddiası gösterilmez.
- Kullanıcı onayı olmadan export yapılmaz.
