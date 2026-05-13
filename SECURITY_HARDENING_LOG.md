# Security Hardening Log — iot-driver-drowsiness-detection

> Bu dosya, güvenlik geliştirme sürecini adım adım belgeler.
> Her adımda sorun, yapılan değişiklik, etkilenen dosyalar ve test sonuçları kayıt altına alınmıştır.

---

## Initial Project Check

### Proje Nasıl Çalıştırılıyor?

Proje üç bileşenden oluşuyor, sırayla başlatılıyor:

```bash
# 1. Flask API (veri alımı, skorlama, Grafana datasource)
python api/app.py

# 2. UDP Bridge (UDP → Flask köprüsü)
python network/udp_bridge.py

# 3. Sensör simülatörü VEYA gerçek kamera
python sensor/simulator.py       # simüle edilmiş veri
python camera/camera_detector.py # webcam ile gerçek zamanlı
```

### Hangi Dosyalar Önemli?

| Dosya | Görev |
|---|---|
| `api/app.py` | Flask REST API — veri alır, skorlar, Grafana'ya servis eder |
| `network/udp_bridge.py` | UDP paketlerini decode edip Flask'e POST eder |
| `sensor/simulator.py` | Test verisi üreten simülatör |
| `camera/camera_detector.py` | Webcam ile gerçek zamanlı uyuşukluk tespiti |
| `security/crypto.py` | HMAC imzalama / doğrulama yardımcıları |
| `security/auth.py` | Flask API key decorator |
| `data/readings.json` | Ham sensör verileri (gitignore'da) |
| `data/alerts.json` | Tetiklenen uyarılar (gitignore'da) |
| `.env` | Gizli anahtarlar — git'e commit edilmez |
| `.env.example` | .env şablonu — git'e commit edilir |

### Veri Akışı

```
[Kamera/Simülatör] --UDP (HMAC imzalı)--> [UDP Bridge] --HTTP (API Key)--> [Flask API] --> [readings.json]
                                                                                              ↓
                                                                                         [Grafana]
```

### Başlangıçta Tespit Edilen Güvenlik Açıkları

| # | Öncelik | Sorun | Durum Başlangıçta |
|---|---|---|---|
| 1 | Kritik | UDP payload injection | `security/crypto.py` var ama eksik kısımlar olabilir |
| 2 | Kritik | Flask'ta auth yok | `security/auth.py` var ama entegrasyon eksik |
| 3 | Yüksek | Input validation yok | Pydantic şema hiç yok |
| 4 | Orta | Replay attack | Nonce/timestamp kontrolü yok |
| 5 | Orta | readings.json açık | Şifreleme yok, sadece gitignore'da |
| 6 | Düşük | Grafana default şifre | Docker/config dosyası yok |

---

## Step 1 — UDP Payload Injection / HMAC Signing

### Problem

UDP üzerinden gelen paketler imzasız olsaydı, aynı ağdaki herhangi biri:
- `127.0.0.1:9999`'a sahte sensör verisi gönderebilirdi
- Yolda payload'ı değiştirebilirdi (man-in-the-middle)
- Drowsiness skorunu manipüle edebilir, kritik alarmları bastırabilirdi

### Yapılan Değişiklik

HMAC-SHA256 tabanlı zarf (envelope) sistemi uygulandı:

```json
{
  "payload": { "driver_id": "...", "blink_rate": 15.5, ... },
  "sig":     "<64-hex-karakter HMAC-SHA256>"
}
```

- **İmzalama** (`sign_payload`): Payload deterministik JSON'a dönüştürülüp HMAC-SHA256 ile imzalanır
- **Doğrulama** (`verify_envelope`): Bridge tarafında imza yeniden hesaplanır, sabit-zamanlı `hmac.compare_digest` ile karşılaştırılır
- **Secret yönetimi**: `IOT_HMAC_SECRET` env değişkeninden okunur, koda gömülmez
- **Hatalı paket davranışı**: `ValueError` fırlatılır, bridge paketi düşürür ve `rejected_hmac` sayacını artırır, uygulama crash olmaz

### Değiştirilen Dosyalar

| Dosya | Değişiklik |
|---|---|
| `security/crypto.py` | `sign_payload`, `verify_envelope`, `get_secret` fonksiyonları |
| `security/__init__.py` | Paket init dosyası |
| `sensor/simulator.py` | Her UDP paketine `sign_payload()` uygulanıyor |
| `camera/camera_detector.py` | Her UDP paketine `sign_payload()` uygulanıyor |
| `network/udp_bridge.py` | Alınan her pakete `verify_envelope()` uygulanıyor |
| `.env` | `IOT_HMAC_SECRET` değeri |
| `.env.example` | Şablon satır eklendi |

### Test Sonucu

Unit testler `security/crypto.py` üzerinde doğrudan çalıştırıldı:

| Senaryo | Beklenen | Sonuç |
|---|---|---|
| Doğru imza ile paket | Kabul (payload döner) | ✅ PASS |
| Payload sonradan değiştirilmiş | `ValueError` fırlatılır | ✅ PASS |
| Yanlış secret ile doğrulama | `ValueError` fırlatılır | ✅ PASS |
| `sig` alanı eksik | `ValueError` fırlatılır | ✅ PASS |
| `payload` alanı eksik | `ValueError` fırlatılır | ✅ PASS |

Test komutu:
```bash
python3 -c "
from security.crypto import sign_payload, verify_envelope, get_secret
secret = get_secret()
payload = {'driver_id': 'test', 'blink_rate': 15.5}
envelope = sign_payload(payload, secret=secret)
assert verify_envelope(envelope, secret=secret) == payload
print('Tüm HMAC testleri geçti')
"
```

### Notlar

- Timing attack'a karşı `hmac.compare_digest` kullanıldı (düz `==` değil)
- `sort_keys=True` ile deterministik JSON → platformlar arası tutarlı imza
- Geride kalan açık: Aynı imzalı paket tekrar gönderilebilir (replay) → Adım 4'te çözüldü

---

## Step 2 — Flask Authentication / API Key Header

### Problem

Flask endpoint'leri kimlik doğrulama olmadan erişilebilir olsaydı:
- Herhangi biri `/readings` endpoint'inden tüm sürücü verilerini çekebilirdi
- `/sensor-data`'ya sahte POST isteği atılabilirdi
- Grafana query endpoint'leri de açık olurdu

### Yapılan Değişiklik

`X-API-Key` header tabanlı kimlik doğrulama sistemi eklendi:

- **`require_api_key` decorator**: Korunan tüm endpoint'lere uygulandı
- **Header eksikse**: `401 Unauthorized` + `"missing_api_key"` hatası
- **Header yanlışsa**: `403 Forbidden` + `"invalid_api_key"` hatası
- **Karşılaştırma**: `hmac.compare_digest` ile sabit-zamanlı (timing safe)
- **Secret yönetimi**: `IOT_API_KEY` env değişkeninden okunur

**Public kalan endpoint'ler** (kasıtlı olarak korumasız bırakıldı):

| Endpoint | Neden Public? |
|---|---|
| `GET /health` | Sistem durumu — monitoring araçları için |
| `GET /` | Grafana'nın datasource health check'i için |

Diğer tüm endpoint'ler (`/sensor-data`, `/readings`, `/readings/summary`, `/grafana/*`, `/query`, `/metrics`, `/ai/analyze`, `/alerts`, `/alerts/latest`) `@require_api_key` ile korunuyor.

### Değiştirilen Dosyalar

| Dosya | Değişiklik |
|---|---|
| `security/auth.py` | `require_api_key` decorator, `get_api_key` fonksiyonu |
| `api/app.py` | Korunan endpoint'lere `@require_api_key` eklendi |
| `network/udp_bridge.py` | Flask'e POST ederken `X-API-Key` header'ı eklendi |
| `.env` | `IOT_API_KEY` değeri |
| `.env.example` | Şablon satır eklendi |

### Test Sonucu

```bash
# Flask çalışıyorken test:
# API key olmadan — 401 beklenir
curl -s http://127.0.0.1:5000/readings
# → {"error": "missing_api_key", "message": "X-API-Key header'ı gerekli"}

# Yanlış API key — 403 beklenir
curl -s -H "X-API-Key: yanlis-key" http://127.0.0.1:5000/readings
# → {"error": "invalid_api_key", "message": "API anahtarı hatalı"}

# Doğru API key — 200 beklenir
curl -s -H "X-API-Key: $IOT_API_KEY" http://127.0.0.1:5000/readings
# → {"total": ..., "readings": [...]}

# Public endpoint — key olmadan 200 beklenir
curl -s http://127.0.0.1:5000/health
# → {"status": "ok", ...}
```

### Notlar

- UDP Bridge, API key'i `.env`'den yükleyip her POST isteğine ekliyor
- `get_api_key()` uygulama başlarken çağrılıyor → yanlış/eksik key varsa servis hemen hata veriyor (fail-fast)
- Bu localhost kurulumu için yeterli; üretimde HTTPS + mTLS tercih edilmeli

---

## Step 3 — Input Validation / Pydantic Schema

### Problem

`/sensor-data` endpoint'i gelen JSON'ı doğrudan `calculate_drowsiness_score()`'a yönlendiriyordu. Eksik alan veya yanlış tipte veri gelirse:
- `KeyError` ile uygulama crash olabilirdi
- Mantıksız değerler (örn. `blink_rate: -999`) hesaplamalara girebilirdi
- Hatalı giriş için belirsiz 500 Internal Server Error dönerdi

### Yapılan Değişiklik

`security/validators.py` dosyasına Pydantic v1/v2 uyumlu `SensorReading` modeli eklendi:

**Zorunlu alanlar ve sınırlar:**

| Alan | Tip | Min | Max | Açıklama |
|---|---|---|---|---|
| `driver_id` | str | 1 karakter | 64 karakter | Sürücü kimliği |
| `blink_rate` | float | 0.0 | 60.0 | Dakikadaki göz kırpma sayısı |
| `eye_closure_duration` | float | 0.0 | 10.0 | Saniye cinsinden göz kapama süresi |
| `head_tilt_angle` | float | 0.0 | 90.0 | Derece cinsinden baş eğim açısı |
| `reaction_delay` | float | 0.0 | 5000.0 | Milisaniye cinsinden tepki gecikmesi |

**Opsiyonel alanlar:**

| Alan | Tip | Default | Açıklama |
|---|---|---|---|
| `state` | str | `"unknown"` | Sürücü durumu |
| `phone_risk_score` | float 0–1 | `0.0` | Telefon kullanım riski |
| `sent_at` | str | `None` | ISO timestamp (latency ölçümü için) |

**Hata davranışı:**
- Eksik zorunlu alan → `422 Unprocessable Entity` + alan bazında hata mesajı
- Sınır dışı değer → `422` + açıklayıcı mesaj
- Uygulama crash olmaz

### Değiştirilen Dosyalar

| Dosya | Değişiklik |
|---|---|
| `security/validators.py` | Yeni dosya — `SensorReading` Pydantic modeli |
| `api/app.py` | `/sensor-data` endpoint'inde `SensorReading` ile doğrulama |
| `requirements.txt` | `pydantic` bağımlılığı eklendi |

### Test Sonucu

```bash
# Eksik alan — 422 beklenir
curl -s -X POST http://127.0.0.1:5000/sensor-data \
  -H "X-API-Key: $IOT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"driver_id": "test"}'
# → {"error": "validation_error", "details": [...blink_rate eksik...]}

# Sınır dışı değer — 422 beklenir
curl -s -X POST http://127.0.0.1:5000/sensor-data \
  -H "X-API-Key: $IOT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"driver_id": "test", "blink_rate": -5, ...}'
# → {"error": "validation_error", "details": [...blink_rate >= 0 olmalı...]}

# Geçerli veri — 200 beklenir
curl -s -X POST http://127.0.0.1:5000/sensor-data \
  -H "X-API-Key: $IOT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"driver_id":"d1","blink_rate":15,"eye_closure_duration":0.15,"head_tilt_angle":5,"reaction_delay":250}'
# → {"status": "ok", "drowsiness_score": ..., "risk_level": "..."}
```

### Notlar

- Pydantic v1 ve v2 her ikisiyle de çalışacak şekilde yazıldı (try/except import)
- `driver_id` için `.strip()` ile whitespace temizleniyor
- `phone_risk_score` 0–1 aralığıyla sınırlandırıldı

---

## Step 4 — Replay Attack / Nonce + Timestamp

### Problem

HMAC imzası geçerli bir paketin tekrar gönderilmesini engellemiyordu:
1. Saldırgan geçerli bir UDP paketini yakalar
2. Aynı paketi birçok kez gönderir
3. Her seferinde "drowsy" skoru sisteme girer, sahte alarmlar tetiklenebilir

### Yapılan Değişiklik

`security/replay_guard.py` dosyasına nonce + timestamp tabanlı koruma eklendi:

**Mekanizma:**
- Her payload'a `nonce` (UUID4) ve `sent_at` (ISO UTC timestamp) zorunlu kılındı
- UDP bridge, `verify_envelope` sonrasında `replay_guard.check()` çağırır
- **Timestamp kontrolü**: `sent_at` değeri şu andan 30 saniyeden eskiyse paket reddedilir
- **Nonce kontrolü**: Aynı nonce daha önce görüldüyse paket reddedilir
- **Temizleme**: Nonce cache'i 60 saniyede bir TTL süresi geçmiş girdilerden temizlenir (bellek sızıntısı olmaz)

**Simülatör güncellemesi:** `sensor/simulator.py` her pakete otomatik `nonce` ve `sent_at` ekliyor.

**Parametreler:**
- `MAX_AGE_SECONDS = 30` — 30 saniyeden eski paketler reddedilir
- `CACHE_TTL_SECONDS = 60` — Nonce cache'de 60 saniye tutulur

### Değiştirilen Dosyalar

| Dosya | Değişiklik |
|---|---|
| `security/replay_guard.py` | Yeni dosya — `ReplayGuard` sınıfı |
| `network/udp_bridge.py` | `verify_envelope` sonrasında `replay_guard.check()` çağrısı eklendi |
| `sensor/simulator.py` | Her pakete `nonce` ve `sent_at` eklendi |

### Test Sonucu

```bash
# Manuel test — aynı paketi iki kez gönder:
python3 -c "
import socket, json, time
from security.crypto import sign_payload, get_secret
from datetime import datetime, timezone
import uuid

secret = get_secret()
payload = {
    'driver_id': 'test',
    'blink_rate': 15.0,
    'eye_closure_duration': 0.15,
    'head_tilt_angle': 5.0,
    'reaction_delay': 250.0,
    'nonce': str(uuid.uuid4()),
    'sent_at': datetime.now(timezone.utc).isoformat()
}
envelope = sign_payload(payload, secret=secret)
data = json.dumps(envelope).encode()

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.sendto(data, ('127.0.0.1', 9999))
print('1. paket gönderildi')
time.sleep(0.5)
sock.sendto(data, ('127.0.0.1', 9999))
print('2. paket gönderildi (aynı nonce — reddedilmeli)')
"
# Bridge logunda: 🚫 Replay reject — nonce daha önce görüldü
```

### Notlar

- `ReplayGuard` thread-safe değil (tekli process için yeterli)
- Çok sayıda instance varsa Redis tabanlı nonce cache'e geçilmeli
- `sent_at` zorunlu hale getirildi — eskiden opsiyoneldi (latency ölçümü için kullanılıyordu)
- Temizleme otomatik: her `check()` çağrısında süresi geçmiş nonce'lar silinir

---

## Step 5 — readings.json Protection

### Problem

`data/readings.json` dosyası:
- Düz metin olarak disk üzerinde tutuluyordu
- Tüm sürücü sensör verileri şifresiz okunabilirdi
- Dosya izinleri kısıtlanmamıştı

### Yapılan Değişiklik

`security/file_guard.py` dosyası oluşturuldu. `api/app.py`'deki `save_reading` ve `load_readings` fonksiyonları güncellendi:

**Uygulanan önlemler:**

1. **Dosya izinleri (Linux/Mac):** `data/` klasörü ve `readings.json` dosyası `chmod 600` (yalnızca sahip okur/yazar) olarak ayarlandı
2. **Şifreleme (opsiyonel):** `READINGS_ENCRYPT=true` env değişkeni aktifleştirilirse veriler `Fernet` (AES-128-CBC + HMAC) ile şifrelenir. Anahtar `READINGS_ENCRYPT_KEY` env değişkeninden okunur
3. **Windows uyumu:** Şifreleme seçeneği Windows'ta da çalışır; `chmod` çağrısı Windows'ta `PermissionError` atarsa sessizce geçilir ve log'a yazılır

**`READINGS_ENCRYPT=true` aktifse:**
- Veriler dosyaya yazılmadan önce şifrelenir
- Dosya okunurken şifre çözülür
- Anahtar hiçbir zaman koda gömülmez

**Anahtar üretme:**
```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### Değiştirilen Dosyalar

| Dosya | Değişiklik |
|---|---|
| `security/file_guard.py` | Yeni dosya — şifreli okuma/yazma |
| `api/app.py` | `load_readings` / `save_reading` → `file_guard` kullanıyor |
| `.env.example` | `READINGS_ENCRYPT`, `READINGS_ENCRYPT_KEY` eklendi |
| `.gitignore` | `data/` zaten var; `*.key` satırı kontrol edildi |

### Test Sonucu

```bash
# Şifreleme aktifken dosya okunabilir mi?
python3 -c "
from security.file_guard import load_data, save_data
save_data('data/readings.json', [{'test': 'value'}])
result = load_data('data/readings.json')
assert result == [{'test': 'value'}]
print('Şifreli yaz/oku: PASS')
"

# Şifresiz ortamda da çalışıyor mu? (READINGS_ENCRYPT=false)
# → Evet, şifreleme devre dışıysa düz JSON kullanılır
```

### Notlar

- Windows'ta `icacls` ile dosya izni kısıtlanabilir (otomatik yapılmadı, platforma özgü)
- `data/` klasörü `.gitignore`'da olduğundan readings.json git'e girmez
- Şifreleme anahtarı kaybolursa veri kurtarılamaz — üretim ortamında anahtar yönetimi kritik

---

## Step 6 — Grafana Default Password

### Problem

Projede Docker/Grafana config dosyası bulunmuyordu. Grafana varsayılan `admin/admin` şifresiyle açılır, bu değiştirilmezse ciddi güvenlik riski oluşturur.

### Yapılan Değişiklik

`docker-compose.yml` ve `grafana/grafana.ini` dosyaları oluşturuldu:

- Grafana admin kullanıcı adı ve şifresi `.env` üzerinden gelir (`GRAFANA_ADMIN_USER`, `GRAFANA_ADMIN_PASSWORD`)
- `grafana.ini`'de `allow_sign_up = false` (dış kayıt kapalı)
- `grafana.ini`'de `allow_embedding = false` (iframe koruması)
- Flask API datasource otomatik provizyon edildi (`grafana/provisioning/datasources/`)
- `.env.example`'a Grafana değişkenleri eklendi

### Değiştirilen Dosyalar

| Dosya | Değişiklik |
|---|---|
| `docker-compose.yml` | Yeni dosya — Flask + Grafana servisleri |
| `grafana/grafana.ini` | Yeni dosya — güvenli Grafana config |
| `grafana/provisioning/datasources/flask.yml` | Otomatik datasource tanımı |
| `.env.example` | Grafana değişkenleri eklendi |

### Test Sonucu

```bash
# Docker ile başlatma:
docker-compose up -d

# Grafana admin girişi test:
# Tarayıcıda http://localhost:3000 → .env'deki kullanıcı adı/şifreyle giriş

# Default admin/admin ile giriş — reddedilmeli:
curl -s -u admin:admin http://localhost:3000/api/org
# → {"message":"Invalid username or password"}
```

### Notlar

- `GRAFANA_ADMIN_PASSWORD` en az 12 karakter, büyük/küçük harf + rakam içermeli
- `.env` git'e commit edilmez (.gitignore'da)
- Grafana veritabanı `grafana_data` Docker volume'unda saklanır — container silinse bile korunur

---

## Final Check

### Proje Çalışıyor mu?

Tüm adımlar tamamlandıktan sonra projeyi şu sırayla başlatın:

```bash
# 1. Bağımlılıkları kur
pip install -r requirements.txt

# 2. .env dosyasını hazırla
cp .env.example .env
# → IOT_HMAC_SECRET, IOT_API_KEY, READINGS_ENCRYPT_KEY değerlerini doldur

# 3. Flask API başlat
python api/app.py

# 4. UDP Bridge başlat (yeni terminalde)
python network/udp_bridge.py

# 5. Simülatörü çalıştır (yeni terminalde)
python sensor/simulator.py
```

### Eklenen Environment Değişkenleri

| Değişken | Açıklama | Üretim İpucu |
|---|---|---|
| `IOT_HMAC_SECRET` | UDP payload imzalama sırrı (≥32 karakter) | `secrets.token_urlsafe(32)` |
| `IOT_API_KEY` | Flask API erişim anahtarı (≥16 karakter) | `secrets.token_urlsafe(24)` |
| `READINGS_ENCRYPT` | `true` ise readings.json şifrelenir | `true` (üretimde) |
| `READINGS_ENCRYPT_KEY` | Fernet şifreleme anahtarı | `Fernet.generate_key()` |
| `GRAFANA_ADMIN_USER` | Grafana admin kullanıcı adı | `admin` değil, özel bir isim |
| `GRAFANA_ADMIN_PASSWORD` | Grafana admin şifresi (≥12 karakter) | Güçlü rastgele şifre |

### GitHub'a Pushlamadan Önce Dikkat Edilmesi Gerekenler

- [ ] `.env` dosyasının `.gitignore`'da olduğunu doğrula (`git status` ile kontrol et)
- [ ] `data/readings.json` ve `data/alerts.json` git'e girmemiş olmalı
- [ ] `git log --all --full-history -- .env` ile geçmişte commit edilmediğini kontrol et
- [ ] `.env.example`'daki tüm değerlerin `change_me_...` formatında olduğunu kontrol et
- [ ] `requirements.txt`'in güncel olduğunu doğrula (`pip freeze > requirements.txt`)
- [ ] `SECURITY_HARDENING_LOG.md` commit'e dahil et (dokümantasyon)

### Güvenlik Değişikliklerinin Özeti

```
Adım 1: HMAC-SHA256 → UDP paket bütünlüğü ve özgünlüğü ✅
Adım 2: API Key Header → Flask endpoint koruması ✅
Adım 3: Pydantic Validation → Input sanitization ve crash koruması ✅
Adım 4: Nonce + Timestamp → Replay attack koruması ✅
Adım 5: File Guard → readings.json şifreleme ve izin kısıtlaması ✅
Adım 6: Grafana Config → Default şifre kaldırıldı, .env'den yönetim ✅
```
