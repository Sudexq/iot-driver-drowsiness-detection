# Güvenlik Geliştirme Notları

Bu doküman, IoT Driver Drowsiness Detection projesine eklenen güvenlik
katmanlarını adım adım belgeler. Her bölümde **sorun → çözüm → yapılan
değişiklikler → test → doğrulama** sırası izlenir.

## Genel Tehdit Modeli

| # | Öncelik | Sorun | Çözüm | Zorluk | Durum |
|---|---|---|---|---|---|
| 1 | Kritik | UDP payload injection | HMAC imzalama | Kolay | ✅ |
| 2 | Kritik | Flask'ta auth yok | API key header | Kolay | ⏳ |
| 3 | Yüksek | Input validation yok | Pydantic şema | Kolay | ⏳ |
| 4 | Orta | Replay attack | Nonce + timestamp | Orta | ⏳ |
| 5 | Orta | readings.json açık | Dosya izni + şifreleme | Orta | ⏳ |
| 6 | Düşük | Grafana default şifre | Config değişikliği | Çok kolay | ⏳ |

---

## Adım 1 — UDP Payload Injection → HMAC İmzalama

### Sorun

Mevcut sistemde simulator/camera_detector → udp_bridge arasındaki tüm UDP
paketleri imzasız ham JSON olarak gönderiliyor. Aynı LAN'de olan herhangi
biri:

- `127.0.0.1:9999`'a kendi UDP paketini gönderebilir → bridge bunu Flask
  API'sine forward eder → sahte sensör verisi sisteme girer
- Yolda payload'ı değiştirebilir (man-in-the-middle) → drowsiness skoru
  manipüle edilir
- Sürücünün gerçek durumunu maskeleyebilir → kritik alarmlar bastırılır

Saldırı maliyeti sıfır: bir `nc -u` veya 5 satırlık Python ile sömürülür.

### Çözüm: HMAC-SHA256 Envelope

Her UDP paketi artık bir **zarf** içinde gönderiliyor:

```json
{
  "payload": { ...orijinal sensör verisi... },
  "sig":     "<64-hex-karakter HMAC-SHA256>"
}
```

İmza, payload'ın deterministik (sıralı anahtar, boşluksuz) JSON
serileştirmesi üzerinden hesaplanıyor. Bridge tarafında aynı sır ile
yeniden hesaplanan imza, gelen `sig` ile **sabit-zamanlı**
(`hmac.compare_digest`) karşılaştırılır — uymuyorsa paket düşürülür.

Sır (secret), `.env` üzerinden ortam değişkeni olarak yükleniyor:
`IOT_HMAC_SECRET`. Kod üzerine hard-code edilmedi.

### Yapılan değişiklikler

| Dosya | Değişiklik |
|---|---|
| `security/__init__.py` | Yeni paket (boş) |
| `security/crypto.py` | `sign_payload`, `verify_envelope`, `get_secret` |
| `.env.example` | Sır şablonu (commit'e güvenli) |
| `.env` | Gerçek geliştirme sırrı (gitignore'da) |
| `sensor/simulator.py` | Gönderim öncesi `sign_payload()` |
| `camera/camera_detector.py` | Gönderim öncesi `sign_payload()` |
| `network/udp_bridge.py` | Decode sonrası `verify_envelope()` + `rejected_hmac` sayacı |

### Tasarım kararları

- **Neden HMAC-SHA256?** Hafif, ek bağımlılık gerektirmiyor (`hmac`
  stdlib), AES-GCM gibi şifrelemenin tam karşılığı değil ama
  *integrity + authenticity* için yeterli. Veri zaten LAN'de hassas
  içerik taşımıyor (sürücü ID + sensör değerleri), öncelik manipülasyonu
  engellemek.
- **Neden canonical JSON?** `sort_keys=True, separators=(",",":")`
  → aynı içerik her platformda aynı byte dizisini üretir. Aksi halde
  Python ile gönderip Go ile doğrularken imza tutmaz.
- **Neden `hmac.compare_digest`?** Zaman temelli (timing) saldırıları
  önler — `==` ile karşılaştırma karakter karakter erken çıkar.
- **Neden ortam değişkeni?** "12-factor app" prensibi. Sır kod tabanına
  girmez, ortamlar arası (dev/staging/prod) farklı değer kullanılır.

### Test

`security/crypto.py` doğrudan test edildi, 3 senaryo:

| Senaryo | Beklenen | Sonuç |
|---|---|---|
| Doğru imza | Kabul | ✅ |
| Tampered payload | `ValueError` | ✅ |
| Yanlış secret | `ValueError` | ✅ |

Ayrıca uçtan uca smoke test (UDP üzerinden gerçek paket gönderimi):

| Senaryo | Beklenen | Sonuç |
|---|---|---|
| Meşru imzalı paket | Kabul | ✅ |
| İmzasız ham JSON (eski format) | Reddet | ✅ |
| Fake imza (rastgele 64 hex) | Reddet | ✅ |

### Çalıştırma

`.env` dosyası yoksa servis başlatıldığında açık hata verir:
> `IOT_HMAC_SECRET environment variable boş…`

Yeni sır üretmek için:
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```
Üretilen değeri `.env` dosyasına `IOT_HMAC_SECRET=...` olarak yapıştırın.

### Geride kalan açıklar

- **Replay attack**: aynı imzalı paket tekrar gönderilirse hâlâ kabul
  edilir → **Adım 4** çözecek (nonce + timestamp).
- **HTTP katmanı**: bridge → Flask hâlâ imzasız → **Adım 2** çözecek
  (API key).

---
