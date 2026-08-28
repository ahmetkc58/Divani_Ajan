# YolYaz frontend

Bu dizin backend paketinden bağımsız, statik bir web istemcisidir. İstemci yalnız
REST API üzerinden haberleşir; Python uygulamasından HTML veya statik dosya
almaz.

Yerel çalıştırma:

```bash
python -m http.server 3000 --directory frontend
```

Backend adresi `config.js` içindeki `apiBaseUrl` alanından değiştirilir. Yeni
origin kullanıldığında aynı adres backend tarafındaki
`KARAYOL_CORS_ALLOWED_ORIGINS` listesine de eklenmelidir.
