# Değişiklik Günlüğü

Proje tanımı kökteki `project.md`, ajan davranış sözleşmesi kökteki `openai.md`
dosyasındadır. Bu dosya uygulama değişikliklerini, doğrulamaları ve kalan
engelleri kaydeder.

## 24 Ağustos 2026 — Yanlış çalışma klasöründen seçici aktarım

### İnceleme

- Doğru çalışma kökü `pwd` ile doğrulandı.
- Doğru projedeki mevcut ve izlenmeyen değişiklikler korunarak `git status`
  kaydedildi.
- `<yanlis-calisma-klasoru>` bir Git deposu olmadığı için dosya
  bazlı karşılaştırıldı; klasör silinmedi veya değiştirilmedi.
- Sanal ortam, pytest/ruff cache'i, bytecode ve toplu kaynak kopyaları kapsam
  dışı bırakıldı.

### Belgeler

- `project.md` ve `openai.md` doğru proje köküne uyarlandı.
- Şartname kapanış sırası `GELISTIRME_PLANI_2026-08-24.md` içinde kod ve veri
  odaklı olarak düzenlendi; rapor/sunum kod freeze sonrasına bırakıldı.
- Yanlış klasörde tamamlanmış gösterilen fakat doğru projede bulunmayan Docker,
  TTL, görsel API yükleme ve benzeri özellikler tamamlandı diye taşınmadı.

### Qdrant readiness

- `QdrantReadinessReport` ve salt okunur koleksiyon doğrulaması eklendi.
- Readiness; vektör şeması, zorunlu payload indeksleri, toplam nokta sayısı,
  corpus fingerprint, embedding model/boyut/görev ve indeks sürümünü denetler.
- Hibrit retrieval için `/ready` başarılı durumda 200, eksik/uyumsuz bağımlılıkta
  açıklamalı 503 döndürür. `/health` liveness ucu olarak ayrı kaldı.
- Sorgu yolu artık eksik Qdrant koleksiyonu oluşturmaz veya indeks onarmaz.
- İndeksleme yolu koleksiyonu oluşturabilmeye devam eder; yanlış klasördeki
  indekslemeyi bozan `require_collection()` değişikliği taşınmadı.

### Doğrulama

- `tests/test_qdrant_store.py` + `tests/test_api.py`: **26/26 geçti**.
- Tüm pytest paketi: **215/215 geçti** (Python 3.12).
- Ruff tam kural seti, taşınan davranışla ilişkili olmayan mevcut B008,
  RUF012, DTZ005, TRY004, import sırası ve satır uzunluğu borçlarını raporladı;
  bu seçici aktarımda ilgisiz kod yeniden biçimlendirilmedi.

### Kalan dış kapılar

- İnsan onaylı güncel kamu mevzuatı corpus'u.
- Gerçek Qdrant sunucusunda aktif-corpus readiness smoke testi.
- OCR/görsel belge ana akışı, paketleme/CI ve lisans kararları.
- Push öncesi PDF, kişisel veri, secret ve yeniden dağıtım hakkı incelemesi.
