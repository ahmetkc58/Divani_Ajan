# Kaggle Legal RAG v2

Bu paket, fiziksel PDF arşivine ihtiyaç duymadan
`uab_ministry_archive_snapshot.json` içindeki 501 belgenin çıkarılmış metnini
Kaggle GPU üzerinde yeniden chunklamak ve vektörlemek içindir.

## Araştırmadan alınan kararlar

- Edge ve diğerlerinin GraphRAG yaklaşımındaki entity graph ve community summary
  katmanı, bütün korpusa yönelik global sorular için değerlidir. Ancak mevzuat
  maddesi bulma indeksinin yerine geçmez. Bu nedenle bu koşu önce güvenilir yerel
  retrieval indeksini üretir; community summary katmanı daha sonra ayrı ve
  izlenebilir bir artefakt olarak eklenebilir.
- LegalGraphRAG'ın doğru arXiv kaydı `2605.28120`'dir. Önerdiği hiyerarşik hukuk
  graph'ı ile Researcher -> Auditor -> Adjudicator ayrımı, çalışma zamanı ajan
  mimarisine aittir. Kaggle indeksleme betiği bunun veri temelini (parent/leaf,
  kaynak izi ve atıf adayları) üretir; atıf adaylarını doğrulanmış kenar gibi
  işaretlemez.
- `2605.19806`, LegalGraphRAG değil **Chunking German Legal Code** çalışmasıdır.
  Çalışma, kanunun doğal section/subsection yapısını koruyan basit yöntemlerin
  karmaşık LLM tabanlı chunklamadan daha iyi retrieval ve maliyet dengesi
  sağlayabildiğini raporlar. Bu nedenle birincil chunker deterministiktir.
- Anthropic Contextual Retrieval'daki chunk'a özgü bağlam fikri uygulanır; fakat
  hukuk metnine yeni yorum eklememek için bağlam `Belge > Bölüm > Madde > Fıkra
  > Bent` metadata'sından deterministik üretilir. Aynı `embedding_text`, dense ve
  BM25 kanallarında kullanılır.
- Cross-Document Topic-Aligned Chunking (`2601.05265`) korpuslar arası sentezlenmiş
  topic chunkları önerir. Kaynak metni değiştiren sentez, mevzuat atıflarında
  provenance riskini artırdığı için birincil indeksin parçası yapılmamıştır.
  Daha sonra yalnız global özet/keşif kanalı olarak A/B test edilebilir.

Birincil kaynaklar:

- https://arxiv.org/abs/2404.16130
- https://arxiv.org/abs/2605.28120
- https://github.com/XMUDeepLIT/LegalGraphRAG
- https://arxiv.org/abs/2605.19806
- https://arxiv.org/abs/2601.05265
- https://www.anthropic.com/engineering/contextual-retrieval

## Kaggle'a yüklenecek dosyalar

Zorunlu:

1. `data/processed/uab_ministry_archive_snapshot.json` (23,77 MB)
2. `kaggle/kaggle_legal_rag_v2.py`

OCR klasörünü ayrıca yüklemek gerekmez. Snapshot, normal PDF metin katmanlarıyla
OCR seçilmiş metinleri zaten `data[].text` içinde birleştirir.

Bu iki dosyayı örneğin `divani-ajan-uab-v2-input` adında private Kaggle Dataset
olarak yükleyin. Notebook ayarlarında:

- Accelerator: **GPU**
- Internet: Jina modelini ilk kez indirebilmek için **On**

## Önce pilot

Kaggle hücresinde gerçek input yollarını görmek için:

```python
!find /kaggle/input -maxdepth 3 -type f | sort
```

İlk 25 belgeyi GPU kullanmadan yalnız parser kontrolünden geçirin:

```python
!python /kaggle/input/divani-ajan-uab-v2-input/kaggle_legal_rag_v2.py \
  --input /kaggle/input/divani-ajan-uab-v2-input/uab_ministry_archive_snapshot.json \
  --output /kaggle/working/uab_legal_rag_v2_pilot \
  --limit 25 --prepare-only --overwrite
```

## Tam GPU koşusu

```python
!python /kaggle/input/divani-ajan-uab-v2-input/kaggle_legal_rag_v2.py \
  --input /kaggle/input/divani-ajan-uab-v2-input/uab_ministry_archive_snapshot.json \
  --output /kaggle/working/uab_legal_rag_v2 \
  --install-deps --devices cuda:0 cuda:1 \
  --batch-size 32 --upsert-batch-size 64 --overwrite
```

`--install-deps`, Kaggle'ın CUDA'lı PyTorch paketini kaldırmaz veya yeniden
kurmaz. Yalnız Transformers, Jina için gereken yardımcı paketler ve Qdrant
istemcisini kurar. Betik CUDA yoksa embedding başlamadan hata verir.

`--devices` verilmezse betik görünen bütün CUDA GPU'larını otomatik kullanır.
T4 x2 oturumunda her GPU'ya ayrı Jina modeli yüklenir ve embedding batchleri iki
tek-iş parçacıklı GPU kuyruğunda paralel yürür. Qdrant'a yazma yalnız ana süreçte
yapıldığı için embedded-local veritabanına eşzamanlı yazma riski oluşmaz.

GPU belleği yetmezse `--batch-size 16` veya `--batch-size 8` kullanın. Bir koşu
yarıda kalırsa aynı output klasörüyle komutu `--overwrite` olmadan tekrar
çalıştırın; mevcut Qdrant pointleri atlanır.

## Üretilenler

`/kaggle/working/uab_legal_rag_v2/` altında:

- `parents.jsonl`: bütün Madde parentları veya yapısız belgelerin sayfa parentları
- `leaves.jsonl`: aramada kullanılacak fıkra/bent leafleri
- `reference_edges_candidates.jsonl`: doğrulama bekleyen çapraz atıf adayları
- `bm25_vocabulary.json`: ham Türkçe BM25 sparse kanalının sözlüğü ve IDF verisi
- `qdrant/`: `uab_legal_leaf_v2` dense + sparse yerel Qdrant koleksiyonu
- `build_manifest.json`: model revizyonları, sayımlar ve SHA-256 doğrulama izleri
- `checkpoint.json`: her başarılı embedding batch'inden sonra atomik ilerleme kaydı
- `/kaggle/working/uab_legal_rag_v2.zip`: indirilecek bütün çıktı

Yerel prepare-only doğrulamasında 501 belgeden şu sonuçlar alınmıştır:

- 6.234 parent
- 30.972 leaf
- 1.819 doğrulanmamış atıf adayı
- Madde yapısı bulunmayan belgeler için 1.278 page-fallback leaf

Bu sayılar embedding sonrasında da aynı olmalıdır. `build_manifest.json` içindeki
`indexed_count`, `leaf_count` ile eşleşmeden koleksiyon tamamlanmış sayılmaz.

Bir hata veya Kaggle kesintisi olursa aynı output klasörüyle betiği yeniden
çalıştırın ve `--overwrite` kullanmayın. Checkpoint korpus kimliğini denetler;
Qdrant'ta gerçekten bulunan pointler nihai doğruluk kaynağı olarak sayılır ve
yalnız eksik leafler yeniden embedlenir.

## Bilinçli sınırlar

- Atıf regex'i yalnız aday kenar üretir. Kanun/madde resolver ve kaynak denetçisi
  tamamlanmadan bu kenarlar LLM bağlamına otomatik eklenmemelidir.
- `legal_reliance_allowed=false` korunur; snapshot'ın güncelliği doğrulanmış
  değildir.
- GraphRAG community özetleri, LLM contextual başlıkları, Zemberek lemma kanalı
  ve reranker bu indeksleme koşusuna zorunlu dahil edilmemiştir. Bunlar retrieval
  gold seti üzerinde ayrı ablation sonrasında etkinleştirilmelidir.
