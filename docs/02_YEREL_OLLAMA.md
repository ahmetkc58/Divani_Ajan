# Yerel Ollama LLM entegrasyonu

## Yapılan değişiklik

Varsayılan LLM sağlayıcısı Gemini API anahtarı kullanan dış servis yerine yerel
Ollama yapıldı. Varsayılan bağlantı yalnız yerel makinedeki
`http://127.0.0.1:11434` adresine gider ve API anahtarı istemez.

## Varsayılan yapılandırma

```dotenv
KARAYOL_LLM_PROVIDER=ollama
KARAYOL_LLM_MODEL=qwen2.5:0.5b
KARAYOL_LLM_BASE_URL=http://127.0.0.1:11434
KARAYOL_LLM_TIMEOUT_SECONDS=20
KARAYOL_LLM_MAX_OUTPUT_TOKENS=2048
KARAYOL_LLM_TEMPERATURE=0
KARAYOL_LLM_MAX_INPUT_CHARS=120000
```

Başka bir kurulu Ollama modeli kullanılacaksa yalnız
`KARAYOL_LLM_MODEL` değiştirilmelidir.

## Çalışma akışı

1. Uygulama `LLMConfig.from_env()` ile sağlayıcı, model ve taban URL'yi okur.
2. Ollama sağlayıcısı native `/api/chat` protokolünü kullanır.
3. Beklenen çıktı şeması Ollama'nın `format` alanına kapalı JSON Schema olarak
   gönderilir.
4. Yanıt Pydantic sözleşmesinden geçmeden orkestrasyon kararına uygulanmaz.
5. Hata, zaman aşımı veya şema ihlalinde deterministik akış korunur.

## Güvenlik sınırları

- Ollama URL'si yalnız `localhost`, `127.0.0.1` veya `::1` olabilir.
- URL içinde kullanıcı bilgisi, query, fragment veya beklenmeyen yol reddedilir.
- LAN ya da internet üzerindeki Ollama sunucusuna yanlışlıkla veri gönderilmez.
- Gizli anahtar desenleri yerel çağrıda da filtrelenir.
- LLM kapalı birim ve şablon izin listesini aşamaz.
- LLM uygunluk denetimini veya insan onayını atlayamaz.

## İzlenebilirlik

Süreç JSON'unda ve arayüz akışında sağlayıcı, model, `local_execution`, ağ
denemesi, fallback ve uyarı bilgileri görünür. Yerel HTTP çağrısı haricî veri
aktarımı olarak gösterilmez; ancak gerçekten yapılan ağ denemesi yine izde
tutulur.

## Başlatma

```bash
ollama serve
ollama pull qwen2.5:0.5b
```

Windows için `scripts/start_local_ollama.ps1` yardımcı betiği de eklendi.

## İlgili dosyalar ve testler

- `src/karayol_agent/llm/contracts.py`
- `src/karayol_agent/llm/providers.py`
- `src/karayol_agent/llm/gateway.py`
- `src/karayol_agent/llm/privacy.py`
- `.env.example`
- `tests/test_llm_gateway.py`
- `tests/test_llm_schema_privacy.py`
- `tests/test_orchestrator_llm_integration.py`
