# Denetlenmiş evrak gereksinimleri

Bu klasör LLM-2'nin eksiklik kontrolü için kullandığı küçük ve kapalı kural
korpusudur. Geniş mevzuat RAG koleksiyonunun yerine geçmez; ondan önce çalışır
ve yalnız evrak türü/alt türüyle eşleşen atomik kuralları sağlar.

Her kural resmî kaynağa, maddeye ve kısa birebir dayanak metnine bağlıdır.
`absence_is_missing=false` olan kayıtlar tavsiye veya form alanıdır; bulunmaması
kesin eksiklik üretemez. İzin, itiraz ve bildirim kuralları ancak alt tür eşleşirse
seçilir.

Yeni kayıt eklerken resmî kaynak URL'si, inceleme tarihi, uygulanabilirlik şartı
ve mümkünse evrak üzerindeki beklenen konum belirtilmelidir.
