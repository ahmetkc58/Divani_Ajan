# Şartname analizi ve uygulama durumu

## Amaç

2026 TYDA Birinci Senaryo şartnamesindeki iki zorunlu görev ile mevcut projeyi
karşılaştırmak, tamamlanan işleri açık işlerden ayırmak ve ölçülmemiş bir
özelliği tamamlanmış gibi göstermemektir.

## İncelenen ana beklentiler

### Görev 1 - Evrak sınıflandırma ve içerik analizi

- Belge içeriğinin okunması ve anlamlandırılması.
- Evrak türünün kapalı etiket kümesinde belirlenmesi.
- Konu, talep, gönderen, tarih, sayı, konum ve benzeri alanların çıkarılması.
- Eksik bilgilerin gösterilmesi ve kaynağa sadık özet hazırlanması.
- İlgili mevzuatın bulunması; kanıt yoksa sonuç uydurulmaması.

### Görev 2 - Resmî yazı taslaklama ve birim yönlendirme

- Uygun resmî yazı türünün seçilmesi.
- Evrak içeriğine göre doğru birim önerisinin üretilmesi.
- Resmî yazışma biçimine uygun taslak hazırlanması.
- Eksik kritik alanların kullanıcıdan istenmesi.
- Nihai karar ve resmî kullanım öncesinde insan onayı alınması.

## Uygulanan bölümler

- TXT, Markdown, metin katmanlı PDF ve desteklenen raster görsellerden güvenli
  metin çıkarımı eklendi.
- Deterministik sınıflandırma ve yapılandırılmış belge analizi oluşturuldu.
- BM25 sentetik demo ve onaylı korpus hazır olduğunda kullanılacak hibrit
  retrieval yolu korundu.
- Şablon seçimi, taslak üretimi, uygunluk denetimi ve kullanıcı onayı uçtan uca
  bağlandı.
- Organizasyon şeması kapalı hedef kataloğuna dönüştürüldü ve birim önerisi
  denetlenebilir hâle getirildi.
- LaTeX kaynağının yanında doğrudan PDF üretimi ve indirme eklendi.
- Frontend ile backend ayrıldı; iletişim sürümlü REST API üzerinden kuruluyor.
- Dış LLM anahtarı zorunluluğu kaldırılarak varsayılan sağlayıcı yerel Ollama
  yapıldı.

## Açık kalan kapılar

- Bağımsız ve kör Türkçe test kümesinde sınıflandırma/yönlendirme ölçümü.
- Yetkili uzman tarafından onaylanmış birim görev ve coğrafi yetki matrisi.
- İnsan onaylı, güncel ve hukuki kullanıma açılmış mevzuat korpüsü.
- OCR için CER, WER ve kritik alan F1 ölçümleri.
- Resmî yazışma kurallarının uzman onayı ve geniş PDF görsel kalite seti.
- Yarışma teslim paketinde veri lisansı, kişisel veri ve yeniden dağıtım kararı.
- Nihai teknik rapor, sunum ve teslim GitHub organizasyonunun doğrulanması.

Detaylı ve yalnız açık işleri içeren güncel plan
`docs/SARTNAME_EKSIKLERI_UYGULAMA_PLANI.md` dosyasındadır.

## Veri sınırı

Yarışma senaryosunda gerçek vatandaş evrakı kullanılmamalıdır. Test evrakları
tamamen kurgusaldır. Organizasyon şemasından yalnız birim yapısı alınmış,
personel adları çalışma zamanı kataloğuna taşınmamıştır. Görev açıklamaları
uzman doğrulaması bekleyen `synthetic_draft` profilleridir.
