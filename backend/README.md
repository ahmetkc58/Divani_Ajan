# Backend

FastAPI tabanlı belge alımı, OCR, Ollama, RAG, yönlendirme, taslak ve export servisi.

Yerel geliştirme komutları proje kökündeki `README.md` ve `Makefile` içindedir. API çalışırken OpenAPI arayüzü `http://127.0.0.1:8000/docs`, sağlık kontrolü `/api/v1/health` adresindedir.

Servis yalnızca aynı cihazdaki Ollama API'sine HTTP çağrısı yapar. Model dosyalarını indirmez, uygulama içine gömmez ve modelin dosya/ağ aracı kullanmasına izin vermez.
