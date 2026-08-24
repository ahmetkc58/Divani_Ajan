# Mevzuat Kaynak İnceleme Paketi — 24 Ağustos 2026

## Amaç ve karar sınırı

Bu çalışma, `data/manifests/core_legislation_manifest.json` içindeki sekiz kaydı ve bunlara bağlanan fiziksel PDF'leri, yalnızca resmî/otoritatif kamu kaynakları üzerinden belge kimliği, yayımlayan kurum, tarih/sürüm, yürürlük-güncellik sinyali, kapsam/domain ve dosya eşleşmesi bakımından inceler.

Bu bir hukuk mütalaası veya hukuk uzmanı onayı değildir. Hiçbir kaydın `approved_for_active_rag` değeri değiştirilmemiştir; sekiz kayıt için de manifestte gözlenen değer `false` olarak kalmıştır. PDF içindeki hükümler, örnekler ve yönergeler yalnızca incelenen belge içeriğidir; çalışma talimatı olarak yorumlanmamıştır.

Makine-okunur ayrıntılar:

- `reports/mevzuat_kaynak_inceleme_2026-08-24.json`
- `reports/mevzuat_kaynak_inceleme_2026-08-24.csv`

## Yönetici özeti

| Sonuç | Kayıt sayısı | Kayıtlar |
|---|---:|---|
| Belge kimliği yerel içerik ve resmî kaynakla desteklendi | 8/8 | Tümü |
| Manifestteki resmî UAB URL'sinden 24.08.2026'da indirilen dosya yerel SHA-256 ile birebir aynı | 6/8 | 2918, 4925, trampa, altyapı güvenliği, trafik yönetmeliği, taşıma yönetmeliği |
| Daha sonraki resmî değişiklik nedeniyle kesin güncellik engeli | 4/8 | 2918, 4925, Karayolları Trafik Yönetmeliği, Karayolu Taşıma Yönetmeliği |
| Eksik/kesik fiziksel kopya | 1/8 | Resmî Yazışma Kılavuzu: yerel 26 sayfa, resmî kamu aynası 102 sayfa |
| Kaynak URL'si olmayan, byte olarak kanonik olmayan ve OCR gerektiren kopya | 1/8 | Resmî Yazışma Yönetmeliği |
| Güncel listelenme sinyali var; yine de hukuk uzmanının karar-anı kontrolü gerekli | 2/8 | Trampa Yönetmeliği, Karayolu Altyapısı Güvenlik Yönetimi |
| Bu inceleme sonucunda aktif RAG'e doğrudan alınması önerilen | 0/8 | İnsan kapsam/yürürlük kararı bekleniyor |

En kritik bulgu şudur: UAB'nin bugün erişilebilen medya URL'siyle byte eşleşmesi, konsolide metnin güncel olduğu anlamına gelmemektedir. Dört dosyada UAB URL'si yerel dosyayla birebir eşleştiği hâlde daha sonraki TBMM/Resmî Gazete değişiklikleri vardır.

## Yöntem ve kanıt seviyesi

1. Manifest yolu, SHA-256, byte boyutu, sayfa sayısı ve `approved_for_active_rag` alanları yerel dosyayla yeniden karşılaştırıldı.
2. Manifestte URL bulunan altı UAB PDF'si 24.08.2026 tarihinde yeniden indirildi; SHA-256 karşılaştırması yapıldı.
3. İlk/son sayfalar, kimlik başlığı, amaç-kapsam, dayanak, yürürlük/yürütme ve değişiklik cetvelleri incelendi. Görsel içerikli iki resmî yazışma PDF'si sayfa render'larıyla kontrol edildi.
4. Belge kimliği ve sonraki değişiklikler için Mevzuat Bilgi Sistemi, Resmî Gazete, TBMM, Cumhurbaşkanlığı, UAB/KGM ve diğer ilgili kamu kurumlarının resmî alan adları kullanıldı.
5. “Değişiklik bulunamadı” sonucu yürürlük kararı değildir. Böyle sonuçlar aşağıda açıkça **[ÇIKARIM]** olarak işaretlenmiştir ve karar anında hukuk uzmanının MBS/Resmî Gazete kontrolünü gerektirir.

## Kayıt bazında inceleme

### 1. `law-2918` — 2918 Sayılı Karayolları Trafik Kanunu

- **Yerel dosya:** `veri_kaynaklari/karayolu/uab_pdf/06_uab_mevzuat.pdf`; 90 sayfa; 1.188.796 byte; SHA-256 `d4ed00b767b7b8024e16f8d96f6308774d2ec3a740da9cc02e9bce0d339b020a`.
- **Kimlik/yayımlayan:** Kanun No. 2918; kabul 13.10.1983; Resmî Gazete 18.10.1983/18195. Kanun koyucu TBMM; resmî yayımlama Resmî Gazete; yerel kopya UAB medya alanında yayımlanan konsolide kopyadır.
- **Kapsam/domain:** Karayollarında trafik düzeni, can-mal güvenliği, kurallar, hak ve yükümlülükler, kurum görevleri. Manifest domain'i `kgm_infrastructure / traffic_safety`; metin İçişleri, belediye, tescil, sigorta ve sürücü hükümleri de içerdiğinden **[ÇIKARIM]** ikincil domain/kurum kapsamı hukuk uzmanı tarafından ayrıca etiketlenmelidir.
- **Dosya eşleşmesi:** Manifest UAB URL'sinden 24.08.2026'da indirilen PDF'nin byte sayısı ve SHA-256'sı yerel dosyayla birebir aynıdır.
- **Sürüm/güncellik:** Yerel değişiklik cetveli 11.07.2023 tarihli AYM kararıyla biter. Oysa 7574 sayılı Kanun 27.02.2026 tarihli ve 33181 sayılı Resmî Gazete'de yayımlanmış ve 2918'in çok sayıda maddesini değiştirmiştir. Yerel/UAB medya kopyası **kesin olarak güncel değildir**.
- **Resmî kaynaklar:** [MBS güncel kayıt](https://www.mevzuat.gov.tr/mevzuat?MevzuatNo=2918&MevzuatTur=1&MevzuatTertip=5), [UAB PDF](https://www.uab.gov.tr/media/ht0cb5st/karayollari-trafik-kanunu.pdf), [27.02.2026 Resmî Gazete/7574](https://resmigazete.gov.tr/27.02.2026), [TBMM 7574 metni](https://cdn.tbmm.gov.tr/KKBSPublicFile/D28/Y4/KanunMetni/df1886cd-184c-4347-a107-15075f1cc0f3.htm).
- **Blocker:** Eski konsolide metin; kapsam genişliği; insan yürürlük/kapsam onayı yok.
- **Önerilen uzman kararı:** `replace_with_current_canonical_copy_then_review` — MBS'den güncel konsolide metni arşivle, kaynak tarih/hash bilgisini sabitle, madde/değişiklik kontrolü ve domain incelemesi sonrasında ayrı bir insan kararı ver.

### 2. `law-4925` — 4925 Sayılı Karayolu Taşıma Kanunu

- **Yerel dosya:** `veri_kaynaklari/karayolu/uab_pdf/07_uab_mevzuat.pdf`; 14 sayfa; 391.477 byte; SHA-256 `e117603dd4fa383ec8844902b79d90fdd84abb4a766ca613cb30a4e438bfba96`.
- **Kimlik/yayımlayan:** Kanun No. 4925; kabul 10.07.2003; Resmî Gazete 19.07.2003/25173. Kanun koyucu TBMM; resmî yayımlama Resmî Gazete; kopya UAB alanındadır.
- **Kapsam/domain:** Kamuya açık karayolunda motorlu taşıtlarla yolcu/eşya taşımaları; taşımacı, acente, komisyoncu, ambar, kargo, çalışanlar ve araç/tesisler. Manifest `road_transport / transport_operations` sınıflaması içerikle uyumludur; nihai kapsam kararı insandadır.
- **Dosya eşleşmesi:** 24.08.2026 UAB indirmesi yerel byte ve SHA-256 ile birebir aynıdır.
- **Sürüm/güncellik:** Yerel değişiklik listesi 7491 sayılı Kanunun 01.01.2024'te yürürlüğe giren değişikliğiyle biter. 7546 sayılı Kanun 30.03.2025 tarihli ve 32857 sayılı Resmî Gazete'de yayımlanmış; 4925'in 26'ncı maddesini yeniden düzenlemiştir. Yerel/UAB medya kopyası **kesin olarak güncel değildir**.
- **Resmî kaynaklar:** [MBS güncel kayıt](https://www.mevzuat.gov.tr/mevzuat?MevzuatNo=4925&MevzuatTur=1&MevzuatTertip=5), [UAB PDF](https://www.uab.gov.tr/media/gbabqkkn/karayolu-taşima-kanunu.pdf), [TBMM 4925 kimlik kaydı](https://tbmm.gov.tr/Yasama/Kanun/f72877bd-b3b6-037b-e050-007f01005610), [TBMM 7546 kimlik/yayım kaydı](https://www.tbmm.gov.tr/Yasama/Kanun/120dfb72-8497-4a49-a41a-019580137ac7), [7546 metni](https://cdn.tbmm.gov.tr/KKBSPublicFile/D28/Y3/KanunMetni/5001139f-708f-4b18-ac1b-e0b6ac9b196f.htm).
- **Blocker:** 30.03.2025 değişikliği yerel konsolide metinde yok; insan yürürlük/kapsam onayı yok.
- **Önerilen uzman kararı:** `replace_with_current_canonical_copy_then_review`.

### 3. `official-writing-guide` — Resmî Yazışma Yönetmeliği Kılavuzu

- **Yerel dosya:** `mevzuat-kılavuz.pdf`; 26 sayfa; 7.599.373 byte; SHA-256 `0716b0e39b62fadf8d9ded7b20f6be3660199eea397f417e127b81775ca129e1`; metin katmanı yok/OCR gerekli.
- **Kimlik/yayımlayan:** Kapak ve ikinci sayfa 2025 tarihli “Resmî Yazışmalarda Uygulanacak Usul ve Esaslar Hakkında Yönetmelik Kılavuzu”nu gösterir. Belge, Yönetmeliğin 36'ncı maddesi uyarınca Cumhurbaşkanlığı Genel Sekreterliği Destek ve Mali Hizmetler Genel Müdürlüğü Bilgi ve Belge Yönetimi Daire Başkanlığınca hazırlanmıştır.
- **Kapsam/domain:** Resmî yazışma ortamı, biçim, başlık, sayı, tarih, konu, muhatap, ilgi, metin, imza ve örnekler; manifest `official_writing / formal_correspondence` ile uyumludur.
- **Dosya eşleşmesi:** Manifestte `source_url` yoktur. Resmî bir MEB alanındaki 2025 kamu aynası 102 sayfa, 13.351.903 byte ve SHA-256 `0899b5a8e0328a598cac70619c4ab957507a1bac425de87a6a99fb62950a7d74` iken yerel dosya 26 sayfadır. Render karşılaştırmasında yerel 3 ve 26'ncı sayfalar resmî aynanın aynı numaralı sayfalarıyla aynı içerik/tasarıma sahiptir; yerel son sayfanın basılı iç sayfa numarası 22'dir. **[ÇIKARIM]** Yerel dosya resmî 102 sayfalık kılavuzun Microsoft Print to PDF ile alınmış ilk 26 sayfalık kesik kopyasıdır; kriptografik eşleşme yoktur.
- **Sürüm/güncellik:** KTB resmî duyurusu kılavuzun TDK değişikliklerine göre güncellendiğini ve Cumhurbaşkanlığı resmî sayfasında yayımlandığını bildirir. Yerel kopya aynı 2025 tasarımını taşır fakat eksiktir; içerik bütünlüğü sağlanmadığından aktif kullanım uygun değildir.
- **Resmî kaynaklar:** [Cumhurbaşkanlığı kılavuz sayfası](https://www.tccb.gov.tr/resmiyazisma/kilavuz/), [KTB güncelleme duyurusu](https://btgm.ktb.gov.tr/TR-347591/resmi-yazisma-kilavuzu-guncellenmistir.html), [MEB resmî 2025 PDF aynası](https://erzincan.meb.gov.tr/meb_iys_dosyalar/2025_04/24150714_cumhurbaskanligiresmiyazisma2025.pdf).
- **Blocker:** Kesik/eksik dosya; kaynak URL zinciri yok; OCR gerekli; insan bütünlük ve kapsam onayı yok.
- **Önerilen uzman kararı:** `reject_local_copy_replace_with_complete_official_edition` — TCCB'deki tam sürümü indir, sayfa sayısı/hash/provenans kaydet, OCR+sayfa bütünlüğü QA'sı yap, ardından uzman kapsam kararı ver.

### 4. `official-writing-regulation` — Resmî Yazışmalarda Uygulanacak Usul ve Esaslar Hakkında Yönetmelik

- **Yerel dosya:** `mevzuat-1.pdf`; 49 sayfa; 13.689.739 byte; SHA-256 `aabd2d739037fff061f348c4a1f239afac5e1a58241fe041f15728775d6ccab9`; seyrek metin katmanı/OCR gerekli. İlk 16 sayfa yönetmelik metni, sonraki sayfalar ek/örneklerdir.
- **Kimlik/yayımlayan:** 09.06.2020 tarihli 2646 sayılı Cumhurbaşkanı Kararı; 10.06.2020 tarihli ve 31151 sayılı Resmî Gazete. Yetkili düzenleyici Cumhurbaşkanlığı; yürütme Cumhurbaşkanı. Yönetmelik yayımını izleyen ayın ilk günü yürürlüğe girer.
- **Kapsam/domain:** Güvenli elektronik imzalı veya zorunlu hâllerde fiziksel resmî yazışma kuralları ve uygulama birliği; `official_writing / formal_correspondence` uyumludur.
- **Dosya eşleşmesi:** Manifestte `source_url` yoktur. TÜİK'in resmî kamu aynasındaki temel metin 13 sayfa ve SHA-256 `3bf2dadbe0088bc106761f5343e56b085e93d91e936dec6e28bcc084226646a1`; yerel kopya byte olarak eşleşmez ve farklı paketleme/ekler içerir. Başlık, Karar No. 2646, amaç ve son 38-39'uncu maddeler içerik kimliğini destekler. Yerel PDF'nin 12.08.2026 “Microsoft Print To PDF” tarihi hukuki sürüm tarihi değildir.
- **Sürüm/güncellik:** MBS 2646 kaydı ve Sağlık Bakanlığının 19.05.2026 tarihli yönetmelik listesi düzenlemeyi hâlen listeler. Resmî kaynak taramasında sonraki değişiklik bulunmadı; **[ÇIKARIM]** temel 2020 metninin yürürlükte olduğu yönünde güçlü sinyal vardır, fakat yerel non-kanonik kopyanın eksiksiz/güncel olduğuna dair byte kanıtı yoktur.
- **Resmî kaynaklar:** [MBS 2646](https://www.mevzuat.gov.tr/mevzuat?MevzuatNo=2646&MevzuatTertip=5&MevzuatTur=21), [HMB kimlik/yayım bilgisi](https://kmyd.hmb.gov.tr/mevzuat-hazirlama), [KTB MBS bağlantılı kayıt](https://teftis.ktb.gov.tr/TR-265426/resmi-yazismalarda-uygulanacak-usul-ve-esaslar-hakkinda-yonetmelik-karar-sayisi-2646.html), [TÜİK resmî PDF aynası](https://www.tuik.gov.tr/media/corporatecontent/21.5.2646Resmi_Yazismalarda_Uygulanacak_Usul_ve_Esaslar_Hakkinda_Yonetmelik.pdf), [Sağlık Bakanlığı 2026 listesi](https://sygm.saglik.gov.tr/TR-28881/yonetmelikler.html).
- **Blocker:** Manifest kaynak URL'si yok; kanonik kopyayla byte eşleşmesi yok; OCR/ek bütünlüğü QA'sı ve insan yürürlük-kapsam kararı yok.
- **Önerilen uzman kararı:** `replace_or_bind_to_canonical_mbs_copy_then_review`.

### 5. `uab-road-expropriation-regulation` — Karayolu Yapımı Amaçlı Kamulaştırmalarda Hazine Taşınmazlarının Trampası Hakkında Yönetmelik

- **Yerel dosya:** `veri_kaynaklari/karayolu/uab_pdf/01_uab_mevzuat.pdf`; 3 sayfa; 42.165 byte; SHA-256 `6318e04b71eaf295b66c76fc27c206bdf849c7922f7dec64d22b69a1d7aa7d75`.
- **Kimlik/yayımlayan:** 30.01.2016 tarihli ve 29609 sayılı Resmî Gazete. 6001 sayılı Kanunun 23'üncü maddesine dayanır; Maliye Bakanlığı ile Ulaştırma, Denizcilik ve Haberleşme Bakanınca birlikte yürütülür; uygulama KGM ve ilgili mali idareleri kapsar.
- **Kapsam/domain:** KGM yol yapımı/geliştirmesi için kamulaştırılan özel taşınmazların bedeline karşılık Hazine taşınmazlarının malik muvafakatiyle trampası; `kgm_infrastructure / expropriation` uyumludur.
- **Dosya eşleşmesi:** 24.08.2026 UAB indirmesi yerel byte ve SHA-256 ile birebir aynıdır. TKGM'nin resmî 2016 duyurusu aynı RG tarihi/sayısı ve belge başlığını doğrular.
- **Sürüm/güncellik:** KGM'nin güncel “İlgili Yönetmelikler” sayfasında hâlen listelenmektedir. Resmî aramada değişiklik/yürürlükten kaldırma kaydı bulunmadı; **[ÇIKARIM]** özgün 2016 metninin hâlen geçerli olduğuna ilişkin orta kuvvette sinyal vardır, fakat negatif arama hukuk uzmanı yürürlük kontrolünün yerine geçmez.
- **Resmî kaynaklar:** [MBS kayıt 21396](https://www.mevzuat.gov.tr/mevzuat?MevzuatNo=21396&MevzuatTur=7&MevzuatTertip=5), [UAB PDF](https://www.uab.gov.tr/media/iejpzo3a/karayolu-yapimi-amaçli-kamulaştirmalarda-hazine-taşinmazlarinin-trampasi-hakkinda-yoenetmelik.pdf), [TKGM duyurusu](https://www.tkgm.gov.tr/30012016-tarihli-ve-29609-sayili-resmi-gazete%27de-yayimlanan-karayolu-yapimi-amacli), [KGM güncel yönetmelikler listesi](https://www.kgm.gov.tr/Sayfalar/KGM/SiteTr/Kurumsal/Yonetmelikler.aspx).
- **Blocker:** Karar-anı MBS/Resmî Gazete yürürlük kontrolü ve insan kapsam onayı eksik.
- **Önerilen uzman kararı:** `expert_verify_current_status_then_decide` — kanonik MBS kopyasıyla madde/ek karşılaştırması sonrası onay veya ret kararı ver.

### 6. `uab-road-infrastructure-safety-regulation` — Karayolu Altyapısı Güvenlik Yönetimi Hakkında Yönetmelik

- **Yerel dosya:** `veri_kaynaklari/karayolu/uab_pdf/03_uab_mevzuat.pdf`; 3 sayfa; 43.901 byte; SHA-256 `f24b6a1d16ec4ce279108e4da9b47acffb85d2550242b6c3c65a59c129564347`.
- **Kimlik/yayımlayan:** 21.10.2018 tarihli ve 30572 sayılı Resmî Gazete; 2918 sayılı Kanun ve 4 sayılı CBK m.796 dayanağı; yetkili birim KGM, yürütme KGM Genel Müdürü.
- **Kapsam/domain:** Türkiye Trans-Avrupa Karayolu Ağında 500 metreden uzun tüneller hariç planlama/proje/yapım ve trafiğe açık yol kesimlerinin güvenlik etki değerlendirmesi, kontrol, ağ sıralaması ve teftişi; `kgm_infrastructure / traffic_safety` uyumludur.
- **Dosya eşleşmesi:** 24.08.2026 UAB indirmesi yerel byte ve SHA-256 ile birebir aynıdır.
- **Sürüm/güncellik:** KGM 2025 Faaliyet Raporu ve 2026 Performans Programı özgün 21.10.2018/30572 düzenlemesini teyit eder; 2019/1936 sayılı AB değişikliği nedeniyle yönetmelik revizyonunun yapıldığını ve yayımlanma sürecinin sürdüğünü bildirir. Resmî Gazete taramasında yayımlanmış değişiklik bulunmadı; **[ÇIKARIM]** yerel özgün metin araştırma tarihinde yürürlükte görünüyor, ancak yakındaki revizyon olasılığı yüksek bir karar-anı blocker'ıdır.
- **Resmî kaynaklar:** [MBS kayıt 25893](https://www.mevzuat.gov.tr/mevzuat?MevzuatNo=25893&MevzuatTur=7&MevzuatTertip=5), [UAB PDF](https://www.uab.gov.tr/media/lczj5l4z/karayolu-altyapisi-guevenlik-yoenetimi-hakkinda-yoenetmelik.pdf), [KGM güncel yönetmelikler listesi](https://www.kgm.gov.tr/Sayfalar/KGM/SiteTr/Kurumsal/Yonetmelikler.aspx), [KGM 2026 Performans Programı](https://www.kgm.gov.tr/SiteCollectionDocuments/KGMdocuments/MerkezBirimler/Kurumsal/PerformansProgrami/2026Performans.pdf), [KGM 2025 Faaliyet Raporu](https://www.kgm.gov.tr/SiteCollectionDocuments/KGMdocuments/MerkezBirimler/Kurumsal/FaaliyetRaporu/2025Faaliyet.pdf).
- **Blocker:** Revizyonun yayımlanma süreci; karar-anı Resmî Gazete/MBS kontrolü; insan kapsam onayı.
- **Önerilen uzman kararı:** `hold_for_publication_check_then_expert_decide`.

### 7. `uab-road-traffic-regulation` — Karayolları Trafik Yönetmeliği

- **Yerel dosya:** `veri_kaynaklari/karayolu/uab_pdf/05_uab_mevzuat.pdf`; 114 sayfa; 1.678.165 byte; SHA-256 `7addf9f0fbf804335eb8368d7672d74ee48c21f3f2612ce6d73ed76934972d53`.
- **Kimlik/yayımlayan:** 18.07.1997 tarihli ve 23053 mükerrer sayılı Resmî Gazete; düzenleyici başlıca İçişleri Bakanlığı, ilgili hükümler birden fazla kurumun görev alanına uzanır.
- **Kapsam/domain:** Trafik kuruluşları, tescil, sürücüler, araç şartları, trafik kuralları, sağlık/psikoteknik ve ek cetveller. `kgm_infrastructure / traffic_safety` temel olarak uygundur; **[ÇIKARIM]** geniş kurum ve konu kapsamı için ikincil domain etiketleri gereklidir.
- **Dosya eşleşmesi:** 24.08.2026 UAB indirmesi yerel byte ve SHA-256 ile birebir aynıdır.
- **Sürüm/güncellik:** Yerel değişiklik cetveli 10.02.2024/32456 ile biter. 19.08.2025 tarihli ve 32991 sayılı Resmî Gazete geçici 12 ve 13'üncü maddeleri değiştirmiştir. Yerel/UAB medya kopyası **kesin olarak güncel değildir**.
- **Resmî kaynaklar:** [MBS kayıt 8182](https://www.mevzuat.gov.tr/mevzuat?MevzuatNo=8182&MevzuatTur=7&MevzuatTertip=5), [UAB PDF](https://www.uab.gov.tr/media/aqgbh4kp/karayollari-trafik-yoenetmeliği.pdf), [19.08.2025 Resmî Gazete değişikliği](https://resmigazete.gov.tr/eskiler/2025/08/20250819-1.htm), [KGM güncel yönetmelikler listesi](https://www.kgm.gov.tr/Sayfalar/KGM/SiteTr/Kurumsal/Yonetmelikler.aspx).
- **Blocker:** 19.08.2025 değişikliği eksik; geniş domain; insan yürürlük/kapsam onayı yok.
- **Önerilen uzman kararı:** `replace_with_current_canonical_copy_then_review`.

### 8. `uab-road-transport-regulation` — Karayolu Taşıma Yönetmeliği

- **Yerel dosya:** `veri_kaynaklari/karayolu/uab_pdf/08_uab_mevzuat.pdf`; 54 sayfa; 1.175.538 byte; SHA-256 `13b6d0dec53030f70bcc2c78eb2ded5215fa0f9ef185e63feba45a1eb5af9feb`.
- **Kimlik/yayımlayan:** Ulaştırma ve Altyapı Bakanlığı; özgün yayım 08.01.2018 tarihli ve 30295 sayılı Resmî Gazete; 4925 sayılı Kanun ve ilgili teşkilat mevzuatı dayanağı.
- **Kapsam/domain:** Yolcu/eşya taşımacılığı, yetki belgeleri, taşıt/işletme şartları, çalışanlar, terminaller, denetim; `road_transport / transport_operations` uyumludur.
- **Dosya eşleşmesi:** 24.08.2026 UAB indirmesi yerel byte ve SHA-256 ile birebir aynıdır.
- **Sürüm/güncellik:** Yerel değişiklik cetveli 16.07.2023/32250 ile biter. Resmî Gazete 31.05.2024/32562 değişikliği ve UAB'nin 15.05.2025/32901 değişikliği (motokurye dâhil) yerel metinde yoktur. Yerel/UAB medya kopyası **kesin olarak güncel değildir**.
- **Resmî kaynaklar:** [MBS kayıt 24299](https://www.mevzuat.gov.tr/mevzuat?MevzuatNo=24299&MevzuatTur=7&MevzuatTertip=5), [UAB PDF](https://www.uab.gov.tr/media/potlbwur/karayolu-taşima-yoenetmeliği.pdf), [31.05.2024 Resmî Gazete değişikliği](https://resmigazete.gov.tr/eskiler/2024/05/20240531-15.htm), [UAB 15.05.2025 değişiklik duyurusu](https://www.uab.gov.tr/haberler/karayolu-tasima-yoenetmeliginde-degisiklik/), [KGM güncel yönetmelikler listesi](https://www.kgm.gov.tr/Sayfalar/KGM/SiteTr/Kurumsal/Yonetmelikler.aspx).
- **Blocker:** 2024 ve 2025 değişiklikleri eksik; insan yürürlük/kapsam onayı yok.
- **Önerilen uzman kararı:** `replace_with_current_canonical_copy_then_review`.

## Uzman karar kuyruğu

Önerilen sıra:

1. Kesin eski dört metni (`law-2918`, `law-4925`, `uab-road-traffic-regulation`, `uab-road-transport-regulation`) kanonik MBS konsolide sürümleriyle değiştir; değişiklik cetveli ve madde düzeyinde karşılaştır.
2. Kesik `official-writing-guide` kopyasını tam 102 sayfalık resmî TCCB baskısıyla değiştir; OCR ve sayfa bütünlüğü QA'sı yap.
3. `official-writing-regulation` için doğrudan MBS/TCCB kaynak URL'si, kanonik hash ve ek seti oluştur; OCR sonucu ile temel madde sayısını doğrula.
4. Trampa Yönetmeliğinde karar-anı yürürlük/repeal kontrolü; Altyapı Güvenlik Yönetmeliğinde beklenen revizyonun yayımlanıp yayımlanmadığı kontrolü yap.
5. Her kayıt için insan hukuk/kapsam uzmanı `approve`, `reject` veya `needs_replacement` kararı versin; bu rapor otomatik onay üretmez.

## Tekrarlanabilirlik notu

- Yerel hash/byte/sayfa değerleri manifestteki değerlerle 8/8 eşleşti.
- Altı UAB URL'sinin 24.08.2026 indirmeleri yerel dosyalarla SHA-256 düzeyinde 6/6 eşleşti.
- Resmî yazışma kılavuzu karşılaştırma aynası: MEB 2025 PDF, 102 sayfa, SHA-256 `0899b5a8e0328a598cac70619c4ab957507a1bac425de87a6a99fb62950a7d74`.
- Resmî yazışma yönetmeliği karşılaştırma aynası: TÜİK PDF, 13 sayfa, SHA-256 `3bf2dadbe0088bc106761f5343e56b085e93d91e936dec6e28bcc084226646a1`.
- İnceleme tarihi sabittir: 24.08.2026. Sonraki mevzuat değişiklikleri için yeniden tarama zorunludur.
