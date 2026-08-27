# Yapılacaklar

**Kaynak:** 26 Ağustos 2026 tarihli, 2026 TYDA şartnamesi + beş paralel bağımsız
araştırma ajanı ile yapılan detaylı kod/veri/test denetimi (mevcut HEAD `a7454bb`
+ o an commit edilmemiş `retrieval/contracts.py` değişikliği üzerinden).

Bu liste `docs/SARTNAME_EKSIKLERI_UYGULAMA_PLANI.md` içindeki bilinen açıkları
**tekrarlamaz**; yalnızca o belgede olmayan, gerçek kod çalıştırılarak
doğrulanmış yeni bulgu/eylem içerir. İşaretleme: `[ ]` açık, `[x]` tamamlandı.
Her madde somut kanıt/dosya referansı taşır.

---

## P0 — Acil, hukuki/etik risk veya şartname puanını doğrudan tehdit eden

- [ ] **Gerçek kamu personeli isimlerini git geçmişinden temizle.**
  `ustyonetimorganizasyonsema.jpg` (T.C. UAB Karayolları Genel Müdürlüğü
  16.07.2026 teşkilat şeması, Genel Müdür dahil ~150 gerçek isim/unvan)
  `da3cacc` commit'inden beri tracked ve **public** `github.com/ahmetkc58/
  Divani_Ajan` reposuna push edilmiş. Kendi belgemiz
  (`docs/07_ORGANIZASYON_SEMASI.md:12-14`) bunun "yarışma teslim commit'ine
  eklenmeyeceğini" söylüyor ama fiilen eklenmiş.
  Eylem: `git rm` + geçmişten kalıcı temizlik (BFG/`git filter-repo`), sonra
  `.gitignore`'a ekle. Push edilmiş bir repo olduğu için **acil**.

- [ ] **`delivery_policy.json`'daki "exclude" kararlarını fiilen uygula.**
  61 dosya (gerçek DETSİS kayıtları, `mevzuat-1.pdf` vb.) "exclude" işaretli
  ama `scripts/audit_delivery_inventory.py` yalnız raporluyor; `git rm`,
  pre-push hook veya CI gate yok. Bu dosyalar hâlâ HEAD'de.
  Eylem: (a) exclude edilen dosyaları depodan çıkar veya ayrı, teslim
  edilmeyecek bir dala taşı, (b) `audit_delivery_inventory.py`'ye gerçek bir
  enforcement modu (CI'da `exclude` sayısı >0 ise fail) ekle.

- [ ] **`ustyonetimorganizasyonsema.jpg`'yi `delivery_policy.json` kapsamına al.**
  Mevcut `scope` yalnız `data/**, resources/**, runtime/**, veri_kaynaklari/**,
  *.pdf` deseniyle sınırlı; `.jpg` hiç taranmıyor. Bu yüzden araç dosyayı
  görmüyor bile. Kapsamı genişlet, benzer risk taşıyan başka uzantılar
  (`.png`, `.docx`, `.xlsx`) için de tara.

- [ ] **`scripts/build_uab_archive_snapshot.py` çıktısının etiketini düzelt.**
  Gerçek, insan onayı olmayan 501 taze OCR'lı bakanlık PDF'i,
  `approved_for_competition_use=True` ile orijinal insan-incelemeli
  snapshot'la AYNI güven etiketini taşıyor. Bu iki veri kümesini (insan
  onaylı vs. henüz onaysız-taze-OCR) ayrı ve açıkça farklı etiketlerle işaretle;
  onaysız olanı `approved_for_active_rag=false` ile tutarlı hale getir.

- [ ] **Karayolu-dışı evrakta yanlış kurum kimliği/yönlendirmeyi düzelt.**
  Canlı test: denizcilik konulu bir evrak `KGM-PER-OZLUK` (personel birimi)
  birimine yönlendirildi, taslakta "Örnek Karayolu Genel Müdürlüğü" kurum adı
  basıldı, `ComplianceAgent.run` (`src/karayol_agent/agents/compliance.py`)
  **passed=True, errors=[]** döndürdü. Kök neden: mevzuat korpusu Bakanlık
  geneline (deniz/hava/demiryolu) genişlerken sınıflandırma
  (`classifier.py`), yönlendirme (`routing.py`) ve taslaklama
  (`drafting.py:21` sabit `institution_name`) hâlâ %100 KGM/karayolu'na sabit.
  Eylem: ya (a) domain genişlemesini şimdilik geri al/dondur (yalnız
  `road_transport`+`kgm_infrastructure` aktif kalsın), ya da (b) sınıflandırma/
  yönlendirme/taslaklama katmanlarını gerçekten çok-domainli hale getir
  (yeni birim kataloğu + kurum-adı alanını dinamikleştir + `ComplianceAgent`'a
  "evrak konusu ↔ seçilen kurum/birim alanı" tutarlılık kontrolü ekle).

- [ ] **Özet/talep alanındaki "T.C." cümle-bölme hatasını düzelt.**
  `src/karayol_agent/agents/analysis.py:610` ve `:725` aynı naif
  `re.split(r"(?<=[.!?])\s+|\n+", text)` deseni "T.C. Kimlik No: ..." metnini
  yanlışlıkla ikiye bölüyor; `summary` alanı gerçek içerik yerine yalnız
  kimlik numarasını üretebiliyor. Aynı kök neden, tek satıra sığmayan normal
  cümlelerde `talep` alanını da güdükleştiriyor (OCR gerekmeden).
  Eylem: cümle bölücüyü bilinen Türkçe kısaltmalar (T.C., vb., Dr., Av. vb.)
  ve satır-sarması birleştirmesi (`_should_join_continuation` deseninin
  özet/talep çıkarımına da uygulanması) ile güçlendir.

- [ ] **CI kapsamını genişlet; yeni şartname/kör-test dosyalarını CI'ya ekle.**
  `.github/workflows/ci.yml` yalnız 10/45 test dosyasını (116/479 test)
  çalıştırıyor. `tests/test_sartname_compliance.py` ve
  `tests/test_blind_evaluation.py` CI'da hiç yok — hiçbir otomatik regresyon
  korumaları yok. Eylem: bu iki dosyayı CI adımına ekle; mümkünse tam paketi
  (RAG/OCR extra'ları hariç tutulsa bile) CI'da çalıştır.

- [ ] **Tek bir toplu "doğruluk" metriği yayınlamayı bırak; dilimlere ayır.**
  `reports/evaluation_baseline.json`'daki harmanlanmış "%83 doğruluk", 40 kolay
  + 8 parafraz örneğini karıştırıp parafrazdaki çöküşü (gerçek: **%0→%14**,
  bkz. `reports/blind_evaluation_v1.json` `paraphrase_positive: 1/7`) gizliyor.
  Eylem: her rapor/README çıktısında `standard` ve `challenge_paraphrase`
  (ve artık kör set) sonuçlarını her zaman AYRI göster, tek harmanlanmış
  sayı asla tek başına raporlanmasın.

---

## P1 — Uygulama kalitesi ve güvenilirlik

- [ ] **Alaka kapısını (relevance gate) genişlet veya kapsam dışını netleştir.**
  `intent_profile_concept_gate_v2` yalnız 2-3 evrak türü (yol bakım, trafik/
  hasar) için mevzuat önerisi üretiyor; kalan 5 tür + yeni deniz/hava/
  demiryolu içeriğinin tamamı güvenli ama işlevsiz şekilde abstain ediyor.
  Yeni korpusun **%83'ü** şu an hiçbir sorguya asla yanıt veremiyor.

- [ ] **`authority_relation`/kapanış alanını kapalı enum gibi davran.**
  Kullanıcı `provide_information` ile `makam_iliskisi=superior` +
  `kapanis=Arz ederim.` gönderip vatandaşa yazılan bir cevap yazısına yanlış
  üslup enjekte edebiliyor; `ComplianceAgent` yalnız
  `OFFICIAL_CLOSINGS[authority_relation]==closing` eşleşmesine bakıyor,
  şablon/muhatap türüyle tutarlılığı kontrol etmiyor.

- [ ] **"reddet" eylemi için gerçek bir backend uç noktası ekle (veya UI'dan kaldır).**
  `orchestrator.py`'de `possible_actions` içinde `"reddet"` kullanıcıya vaat
  ediliyor ama `EvrakOrchestrator`'da `reject`/`deny` metodu yok, hiçbir REST
  ucu yok, frontend'de buton/handler yok.

- [ ] **Yönlendirme eşik sınırını düzelt.**
  `routing.py:75` tek bir anahtar-kelime eşleşmesi tam `4` puan veriyor,
  `routing.py:91` fallback koşulu `< 4` — tam sınırda kalan (skor=4), tek
  ve zayıf kanıtlı eşleşmeler triyaj yerine "somut ama alakasız" bir birim
  adı üretebiliyor. Eşik değerini `<= 4` yap veya minimum kanıt sayısını 2'ye çıkar.

- [ ] **`ACTIVE_PROJECT_DOMAINS` (`retrieval/contracts.py`) ile
  `ACTIVE_RETRIEVAL_DOMAINS`/`AnalysisDomainResolver` (`retrieval/runtime.py`)
  senkronizasyonunu sağla.** Şu an ikisi ayrı listeler taşıyor; biri
  güncellenirken diğeri unutuldu. Hibrit moda geçildiğinde sessiz bir
  `DomainResolutionError` kör noktasına dönüşebilir. Tek bir kaynağa
  (`SSOT`) indirgenmeli.

- [ ] **CRLF/hash kırılganlığını kalıcı çöz.**
  20 test başarısızlığının 18'i tek kök nedene bağlı: Windows
  `core.autocrlf` dönüşümü pinlenmiş SHA-256'ları bozuyor (`.gitattributes`
  `*.json text eol=lf` diyor ama `.txt` uzantısı listede yok, ayrıca dosyalar
  attribute eklenmeden önce checkout edilmiş). Bu, dokümanların "bilinen OCR
  hash uyuşmazlığı" dediği şeyden farklı ve daha temel bir sorun; üretimde
  aynı mekanizma veriyi sessizce `restricted`e düşürebilir.
  Eylem: `.gitattributes`'a `*.txt text eol=lf` ekle, tüm pinlenmiş dosyaları
  `git add --renormalize .` ile yeniden normalize et, SHA-256'ları güncelle.

- [ ] **`data/processed/stage3_quarantine/uab-road-transport-regulation.json`
  içindeki başka bir geliştiricinin mutlak Windows yolunu temizle.**
  (`C:\Users\matri\OneDrive\Desktop\testing3\...`) — `test_snapshot_corpus.py`
  bunu haklı olarak reddediyor.

- [ ] **Gerçek Tesseract OCR başarısızlığını araştır.**
  `tests/test_extractor.py::test_real_tesseract_scanned_pdf_extracts_
  sender_end_to_end` bu makinede kurulu gerçek Tesseract ile taranmış test
  PDF'inden okunabilir metin üretemiyor; ortam eksikliği mi yoksa kod
  regresyonu mu belirsiz.

- [ ] **`scripts/evaluate_blind_documents.py::_evaluate_record` puanlama
  mantığını gold etiketlerini tam kullanacak şekilde düzelt.**
  `near_miss_ambiguous` kategorisinde `gold["acceptable_document_types"]`
  hesaplanıyor ama "passed"a hiç dahil edilmiyor (yalnız
  `requires_human_review` kontrol ediliyor); `no_answer_offtopic`'te
  `gold["expects_abstention"]`/`acceptable_unit_ids` hiç okunmuyor, sabit
  `GENERIC_UNIT_ID` kullanılıyor. Şu an göründüğünden daha gevşek bir ölçüm.

- [ ] **Demo veri kaynağı/kullanım haklarını kullanıcı arayüzünde göster.**
  Şartname madde 8 özellikle demo sırasında bunun açık belirtilmesini
  istiyor; şu an yalnız `resources/README.md`/`NOTICE` gibi iç dokümanlarda
  var. `frontend/index.html`'e veya ayrı bir "Hakkında" panosuna sentetik
  veri/kaynak/lisans özeti ekle.

- [ ] **`docs/SARTNAME_EKSIKLERI_UYGULAMA_PLANI.md`'yi güncelle.**
  Belge `main@93b3e08` sürümünü incelediğini iddia ediyor; HEAD (`a7454bb`)
  bundan 72 dosya, ~9800 satır ileride. Belgeyi güncel HEAD'e göre yeniden
  gözden geçir.

- [ ] **`reports/sbom.cdx.json`'a Jina modelini ekle.**
  `NOTICE` dosyası Jina Embeddings v3'ü (CC BY-NC 4.0) doğru belgeliyor ama
  SBOM'da (95 bileşen) "jina" hiç geçmiyor.

- [ ] **`_infer_signature_sender` (`analysis.py:657-676`) en yaygın imza
  biçimini kapsayacak şekilde genişlet.** Şu an yalnız TAMAMEN BÜYÜK HARF
  soyadı veya rol satırı olan imzaları kabul ediyor; normal Title-Case
  "Saygılarımla, Ali Yılmaz" biçimi reddediliyor. `_LABEL_ALIASES["gonderen"]`
  listesine "Ad ve Soyad" varyantını da ekle.

---

## P2 — Küçük ama gerçek riskler

- [ ] **Teslim paketleme kontrolü ekle.** `AnyDesk.exe` (8.3 MB) ve
  `Ulaştırma ve Altyapı Bakanlığı.7z`/klasörü (~289-366 MB, 501 gerçek PDF)
  şu an `.gitignore` ile korunuyor (git-tabanlı teslimde sorun yok) ama zip/
  manuel kopyalama ile teslim edilirse yanlışlıkla dahil olabilir. Teslim
  script'inin yalnız `git ls-files` çıktısını paketlediğini doğrulayan bir
  CI/manuel kontrol ekle.

- [ ] **Artifact indirme uçlarına (`/artifacts/tex`, `/artifacts/pdf`)
  doğrudan path-traversal regresyon testi ekle.** Koruma şu an merkezi ve
  sağlam (`state_store.py` `_DOCUMENT_ID_PATTERN`) ama
  `test_artifact_download_regression_1.py` bu iki ucu traversal açısından
  hiç doğrudan sınamıyor — savunma-derinliği testi eksik.

- [ ] **Çekirdek modüllere doğrudan birim testi ekle.** `state_store.py`
  (özellikle `_replace_with_retry` atomik-yazma/Windows AV kilit toleransı),
  `documents/text_normalization.py`, `ingestion/chunker.py`,
  `agents/classifier.py`, `agents/analysis.py`, `agents/template_selection.py`,
  `llm/providers.py`, `llm/contracts.py` hiçbir testte doğrudan import
  edilmiyor; yalnız uçtan-uca senaryolarla dolaylı dokunuluyor.

- [ ] **`pytest-timeout` ekle.** Ağ/model gerektiren bir test askıda kalırsa
  hem yerel hem CI koşusu süresiz bekleyebilir.

---

## Not

Bu liste 26 Ağustos 2026'daki tek seferlik bir denetimin sonucudur; kod
değiştikçe güncelliğini yitirir. Bir madde tamamlandığında yalnız kutucuğu
işaretlemek yeterli değildir — kapanış kanıtı (test adı, commit hash'i) bu
dosyaya veya `docs/DEGISIKLIKLER.md`'ye eklenmelidir.
