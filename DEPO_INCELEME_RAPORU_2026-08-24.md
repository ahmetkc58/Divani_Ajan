# Depo İnceleme ve RAG Uygulama Raporu — 24 Ağustos 2026

## 1. Kapsam ve talimat ayrımı

Bu incelemede kullanıcının talebi çalışma emri, PDF/Markdown belgeleri ile
depo içindeki planlar ise gereksinim ve kanıt kaynağı olarak ele alındı. Ekli
şartname, mevzuat ve kılavuz içindeki metinler kullanıcı adına yeni yetki veya
çalışma talimatı sayılmadı.

İncelenen gerçek Git çalışma ağacı:

Bu raporun bulunduğu proje kökü.

Bir üst klasörde ayrıca `.git` görünse de `HEAD`, `refs/heads/.invalid` değerine
işaret ediyor. Geçerli `main`, geçmiş ve `origin/main` ilişkisi iç projededir;
üstteki bozuk metadata bu çalışma sırasında değiştirilmedi.

## 2. Depo yapısı ve mevcut mimari

İnceleme başlangıcında Git'te 141 dosya izleniyordu. Bu çalışma 14 yeni aday
dosya ekledi; mevcut izlenen + ignore edilmeyen toplam 155 dosyadır. Ana
sorumluluk sınırları:

- `src/karayol_agent/agents/`: sınıflandırma, içerik analizi, mevzuat araştırma,
  kaynak doğrulama, şablon seçimi, yönlendirme, taslak ve uygunluk rolleri.
- `src/karayol_agent/orchestrator.py`: uçtan uca süreç durum makinesi ve kalıcı
  süreç kaydı.
- `src/karayol_agent/documents/`: metin/PDF çıkarımı ve OCR fallback sınırı.
- `src/karayol_agent/ingestion/`: hukuk hiyerarşisini koruyan yapısal chunking ve
  onaylı/karantina ingestion akışları.
- `src/karayol_agent/curation/`: envanter, hash, PDF kalite ve insan inceleme
  manifesti.
- `src/karayol_agent/retrieval/`: BM25, güvenli repository, Jina sağlayıcısı,
  Qdrant, RRF hibrit arama ve vektör indeksleme.
- `src/karayol_agent/evaluation/`: sabit sentetik gold set ve dilim metrikleri.
- `src/karayol_agent/latex/`, `templates/`: güvenli resmî yazı üretimi.
- `src/karayol_agent/api.py`, `web/`, `cli.py`: API, manuel demo ve komut satırı.
- `data/`: sentetik çalışma verileri ile kalıcı mevzuat manifestleri.
- `resources/`: dış veri kartları ve referans kaynak açıklamaları.
- `tests/`: birim, entegrasyon, güvenlik regresyonu, API ve manuel arayüz testleri.

Mimari, eski genel “EvrakAI” yaklaşımından daraltılmış karayolu MVP'sine doğru
evrilmiş. En güçlü tarafları fail-closed veri sınırı, izlenebilir süreç durumu,
sayfa/hash koruyan yapısal mevzuat parçaları ve güvenli LaTeX üretimi. Bu çalışma
öncesindeki en büyük plan açığı dense retrieval'ın yalnız dokümante edilmiş,
uygulanmamış olmasıydı.

## 3. Git geçmişi

`main`, inceleme başlangıcında `origin/main` ile aynı `8065108` commit'indeydi;
çalışma ağacı temizdi. Son önemli commitler:

| Commit | Tarih | Anlamı | Değişim |
|---|---|---|---|
| `8065108` | 24 Ağustos 02:50 | Mevzuat veri hazırlama pipeline kapanışı | 11 dosya, +1.038/-22 |
| `d9342c2` | 24 Ağustos 02:12 | Doğrulanmış mevzuat ingestion ve fail-closed repository | 19 dosya, +2.314/-113 |
| `da3cacc` | 23 Ağustos 23:56 | Projeyi karayolu evrak MVP'si olarak yeniden kurma | 262 dosya, +47.234/-10.483 |
| `5606214` | 20 Ağustos | Durum raporu | 2 dosya, +300 |
| `041ccd3` | 20 Ağustos | Önceki geçmişin merge noktası | merge commit |
| `f2b1976` | 20 Ağustos | Eski EvrakAI MVP | 152 dosya, +11.756 |
| `984110c` | 8 Ağustos | İlk commit | 2 dosya, +23 |

`git fsck`, son yeniden-kurma commit'inden bugüne `git diff --check` ve branch
ileride/geride kontrolleri temizdi. Bu çalışma commit oluşturmaz; değişiklikler
kullanıcının inceleyip commit etmesi için çalışma ağacında bırakılır.

## 4. Mevzuat verisi denetimi

Çekirdek envanterdeki sekiz dosyanın byte boyutu ve SHA-256 değerleri manifestle
eşleşiyor. Pipeline sonucu:

- 8/8 fiziksel kaynak eşleşti.
- Metin katmanı kullanılabilir 6 belge 2.407 yapısal parçaya ayrıldı.
- Sayfa metadata kaybı: 0.
- İki belge için Türkçe OCR aday metni ve sayfa kalite raporu üretildi; insan
  sayfa doğrulaması bekliyor.
- İnsan tarafından aktif RAG için onaylanan belge/parça: 0.
- Yanlışlıkla aktif edilen parça: 0.

Bu nedenle gerçek kamu mevzuatı bugün Qdrant'a yazılamaz. Bu bir uygulama
eksikliği değil, kaynak/yürürlük/OCR insan onayı kapısının doğru çalışmasıdır.
Havacılık içerikli adayların çekirdek karayolu korpusuna alınmaması da kapsam
ayrımının bilinçli sonucudur.

Resmî kaynak incelemesinde sekiz dosyanın yerel hash/byte/sayfa bütünlüğü
doğrulandı. Altı UAB URL'si yerel kopyayla birebir eşleşse de 2918, 4925,
Karayolları Trafik Yönetmeliği ve Karayolu Taşıma Yönetmeliği daha sonraki
resmî değişiklikleri içermediği için kesin eski bulundu. Kılavuz 26/102 sayfalık
kesik kopya, yazışma yönetmeliği ise kanonik URL/hash bağı olmayan OCR adayıdır.

## 5. Kaynak araştırmasından çıkan mimari kararlar

1. Jina Embeddings v3, `retrieval.passage` ve `retrieval.query` görevlerini ayrı
   kullanır; varsayılan 1024 boyut ve cosine seçildi. 8K model bağlamı hukuk
   yapısını bozacak büyük chunk üretmek için gerekçe sayılmadı.
2. Contextual Retrieval yaklaşımına uygun olarak hem dense hem BM25 girdisi
   `context_text + original_text` olur; atıfta yalnız orijinal hüküm gösterilir.
3. Ham BM25 ve cosine skorları aynı ölçekte olmadığı için ağırlıklı ham skor
   toplamı yerine klasik rank-only RRF (`k=60`) kullanılır.
4. GraphRAG'ın local ve global yolları ayrıdır. Bu projede belirli madde/evrak
   sorgularında local hybrid varsayılan, topluluk özeti yalnız global sorgularda
   ileriki aşamadır.
5. LegalGraphRAG'ın Researcher/Auditor/Adjudicator ayrımı mevcut ajan sınırlarına
   uyarlandı; retrieval sonucu tek başına hukuk kanıtı sayılmaz.
6. Kullanıcının verdiği `arXiv:2605.19806`, LegalGraphRAG değil *Chunking German
   Legal Code* çalışmasıdır. LegalGraphRAG'ın doğru kaydı `arXiv:2605.28120`'dir.
7. `arXiv:2601.05265` CDTA yaklaşımı birincil hukuk parçası üretmek için değil,
   Tier 2 konu haritası/topluluk özeti deneyi için uygundur.

## 6. Bu çalışma ağacında uygulanan RAG katmanı

- Lazy yerel `jinaai/jina-embeddings-v3` sağlayıcısı; passage/query API ayrımı,
  1024D doğrulama ve L2 normalizasyonu.
- Model ağırlıkları ile modelin `auto_map` üzerinden çağırdığı ayrı
  `jinaai/xlm-roberta-flash-implementation` kod deposu kendi doğrulanmış Hugging
  Face commit'lerine ayrı ayrı pinli; iki revision Qdrant payload ve indeks
  raporunda taşınır.
- Test/geliştirme için açıkça üretim dışı deterministik hash sağlayıcı; Jina'nın
  yerine sessiz otomatik fallback değildir.
- Qdrant `legal_chunks_v1`, cosine/1024 şema doğrulaması, altı payload indeksi,
  kararlı UUIDv5 point kimliği ve sürümlü metadata.
- Public kayıt için repository ile aynı tam onay/yürürlük/OCR/hash/sayfa/domain
  kapılarının upsert ve sonuç okuma sırasında ikinci kez doğrulanması.
- `context_text + "\n\n" + original_text` batch passage indeksleme ve tüm corpus
  için model çağrısından önce ön doğrulama.
- Kanal başına top-20 BM25/dense aday, chunk kimliğiyle dedup, klasik RRF ve
  deterministik tie-break.
- Dense hata/eksikliği için açık uyarılı BM25 fallback; süreç kaydında kanal
  sırası, ham skor, RRF katkısı, aday sayıları ve hata türü.
- Analysis-aware domain çözümü; belirsiz alan geniş Qdrant sorgusuna dönüşmez.
- Hybrid modda lexical ve dense aynı strict public corpusu temsil eder. Public
  corpus yok/boş/geçersizse public Qdrant ile sentetik BM25 karıştırılmaz; tüm
  akış sentetik BM25'e tanılı şekilde döner.
- `index-vectors` CLI komutu, ortam tabanlı secret/config ve `.env.example`.
- Evaluation raporunda `retrieval_mode`, request diagnostics ve rank/kanal izi;
  aynı gold set için BM25/hybrid/reranker raporlarını ayrı üreten enjeksiyon.
- Auditor, dense-only kanıtı yalnız tam doğrulanmış public kaynaktan kabul eder;
  sentetik demo kuralı ayrı kaynak türü olarak işaretlenir.
- Pinli gerçek Jina v3 CPU smoke testi, yedi sentetik parçalık yerel Qdrant
  indeksi ve BM25/hibrit ablation raporu tamamlandı. Hibrit Recall@5 `1,0000`,
  MRR `0,9097`; BM25'e göre sırasıyla `+0,1944` ve `+0,1041`.
- Çok dilli Jina reranker kodlandı fakat Recall@5'i `0,9722`, MRR'ı `0,8806`
  değerine düşürüp yaklaşık `3,7 sn/skor çağrısı` eklediği için varsayılan
  akışta kapalı bırakıldı.
- Kural → evrak türü/birim/şablon/zorunlu alan yollarını gold kayıt kanıtıyla
  taşıyan küçük sentetik graf üretildi; sentetik olmayan girdiyi reddeder.

## 7. Takip çalışmasının kapanış durumu

1. OCR aday metinleri ve kaynak/güncellik inceleme paketi tamamlandı.
2. Jina v3/Qdrant smoke ve dondurulmuş gold-set hibrit ölçümü tamamlandı.
3. Reranker ablation'ı tamamlandı; ölçülen olumsuz sonuç nedeniyle kapalı.
4. Elle doğrulanabilir küçük sentetik mevzuat-birim-şablon grafı tamamlandı.
5. **Bekleyen dış kapı:** Yetkili hukuk/kapsam uzmanı güncel kanonik kopyaları
   seçip her kayıt için `approve`, `reject` veya `needs_replacement` kararı
   vermelidir. Bu olmadan aktif public corpus ve gerçek public Qdrant indeksi
   bilerek üretilemez.
6. CDTA/global topluluk özetleri hâlâ birincil kanıt olmayan Tier 2 gelecek
   deneyidir.

Modelin `CC BY-NC 4.0` lisansı yarışma demosundan ticari ürüne geçişte ayrıca
değerlendirilmelidir. Üretilen canlı Jina/Qdrant metriği yalnız sentetik
benchmark kapsamındadır; kamu mevzuatı veya gerçek saha başarımı iddiası değildir.

## 8. Birincil teknik kaynaklar

- Jina Embeddings v3 makalesi: <https://arxiv.org/abs/2409.10173>
- Jina Embeddings v3 model kartı: <https://jina.ai/models/jina-embeddings-v3/>
- Microsoft GraphRAG makalesi: <https://arxiv.org/abs/2404.16130>
- Microsoft GraphRAG sorgu dokümantasyonu:
  <https://microsoft.github.io/graphrag/query/overview/>
- LegalGraphRAG makalesi: <https://arxiv.org/abs/2605.28120>
- LegalGraphRAG resmî kodu: <https://github.com/XMUDeepLIT/LegalGraphRAG>
- *Chunking German Legal Code*: <https://arxiv.org/abs/2605.19806>
- Cross-Document Topic-Aligned Chunking: <https://arxiv.org/abs/2601.05265>
- Anthropic Contextual Retrieval:
  <https://www.anthropic.com/engineering/contextual-retrieval>
- Qdrant hybrid sorgu dokümantasyonu:
  <https://qdrant.tech/documentation/search/hybrid-queries/>
