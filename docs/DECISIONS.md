# Teknik Karar Kaydı

## ADR-001 - Yerel Ollama

Belge metni cihaz dışına gönderilmez. Model adları dinamik seçilir. Sonuç: daha iyi veri gizliliği; donanıma bağlı kalite ve gecikme.

## ADR-002 - React ve FastAPI Ayrımı

Jüri demosu ve gelecekteki ürünleşme için arayüz ve API ayrı bileşenlerdir. Sonuç: Streamlit'ten fazla kurulum, daha temiz API ve UX.

## ADR-003 - NumPy Vektör İndeksi

Corpus yüzlerce chunk düzeyindedir. FAISS/Chroma yerine normalize matris ve kosinüs benzerliği kullanılır. Sonuç: kolay Docker/Apple Silicon uyumu; büyük veri için uygun değil.

## ADR-004 - Fine-tuning Yok

Teslim süresi ve veri kalitesi nedeniyle prompting, RAG ve deterministik kurallar kullanılır. Sonuç: model değiştirilebilir, fakat alan başarımı prompt kalitesine bağlıdır.

## ADR-005 - İnsan Onayı

Sistem karar destek aracıdır. Yönlendirme ve taslak insan tarafından onaylanır; onaysız export engellenir.

## ADR-006 - Grounding ve Deterministik Güvenlik Ağı

Etiketli alanlar belge metnindeki gerçek satırlarla doğrulanır; desteklenmeyen tamamlanma/onay iddiaları nötr özete çevrilir. Taslak türü eksik alan listesiyle tutarlı hâle getirilir. LLM zaman aşımı veya şema hatasında güvenli şablon kullanılır.
