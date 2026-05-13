"""
Pydantic tabanlı girdi doğrulama modelleri.

Neden gerekli?
    Flask endpoint'lerine gelen JSON verisi doğrulanmadan işlenirse:
    - Eksik alan → KeyError → 500 Internal Server Error (uygulama crash)
    - Sınır dışı değer (örn. blink_rate=-999) → hesaplama bozulur
    - Yanlış tip (örn. string yerine sayı bekleniyor) → sessiz hata

Bu modeller:
    - Her alanın tipini ve sınırlarını tanımlar
    - Eksik/hatalı veri için açıklayıcı 422 hatası döner
    - Uygulamanın crash olmasını engeller
    - Pydantic v1 ve v2 ile uyumludur

Kullanım:
    from security.validators import SensorReading, validate_sensor_reading

    @app.route('/sensor-data', methods=['POST'])
    @require_api_key
    def receive_data():
        data, error_response = validate_sensor_reading(request.get_json())
        if error_response:
            return error_response  # 422 + hata detayları
        # data artık doğrulanmış dict
"""

import sys

# Pydantic v1 ve v2 uyumluluğu
try:
    from pydantic import BaseModel, Field, validator
    PYDANTIC_V2 = False
except ImportError:
    try:
        from pydantic.v1 import BaseModel, Field, validator
        PYDANTIC_V2 = False
    except ImportError:
        BaseModel = None


def _pydantic_available():
    return BaseModel is not None


# ── Sensor Reading Modeli ─────────────────────────────────────────

if _pydantic_available():
    class SensorReading(BaseModel):
        """
        UDP Bridge → Flask API arasında beklenen sensör verisi formatı.

        Zorunlu alanlar:
            driver_id              : Sürücü kimliği (1-64 karakter)
            blink_rate             : Dakikadaki göz kırpma sayısı (0-60)
            eye_closure_duration   : Göz kapama süresi saniye (0-10)
            head_tilt_angle        : Baş eğim açısı derece (0-90)
            reaction_delay         : Tepki gecikmesi milisaniye (0-5000)

        Opsiyonel alanlar:
            state                  : Sürücü durumu ("alert"/"drowsy"/"transitioning")
            phone_risk_score       : Telefon riski 0-1 arası (varsayılan 0.0)
            sent_at                : ISO timestamp (latency ölçümü için)
            nonce                  : Replay attack koruması için tekil değer
        """

        # Zorunlu alanlar
        driver_id: str = Field(..., min_length=1, max_length=64)
        blink_rate: float = Field(..., ge=0.0, le=60.0,
                                  description="Dakikadaki göz kırpma sayısı")
        eye_closure_duration: float = Field(..., ge=0.0, le=10.0,
                                             description="Saniye cinsinden göz kapama süresi")
        head_tilt_angle: float = Field(..., ge=0.0, le=90.0,
                                        description="Derece cinsinden baş eğim açısı")
        reaction_delay: float = Field(..., ge=0.0, le=5000.0,
                                       description="Milisaniye cinsinden tepki gecikmesi")

        # Opsiyonel alanlar
        state: str = Field(default="unknown",
                           description="Sürücü durumu: alert / transitioning / drowsy")
        phone_risk_score: float = Field(default=0.0, ge=0.0, le=1.0,
                                         description="Telefon kullanım riski (0=yok, 1=yüksek)")
        sent_at: str = Field(default=None,
                             description="ISO 8601 UTC timestamp (opsiyonel)")
        nonce: str = Field(default=None,
                           description="Replay attack koruması için tekil değer")

        @validator('driver_id')
        def driver_id_no_whitespace_only(cls, v):
            """Sadece boşluktan oluşan driver_id'yi reddet."""
            if not v.strip():
                raise ValueError("driver_id boş veya sadece boşluk olamaz")
            return v.strip()

        @validator('state')
        def state_must_be_valid(cls, v):
            """Tanınan durumlarla sınırla; tanınmayan gelirse 'unknown' döndür."""
            valid = {"alert", "transitioning", "drowsy", "unknown"}
            return v if v in valid else "unknown"

        class Config:
            # Ekstra alanları sessizce kabul et (forward compatibility)
            extra = "allow"

else:
    # Pydantic yoksa basit fallback sınıfı
    class SensorReading:
        """Pydantic yokken kullanılan minimal fallback — sadece zorunlu alan kontrolü."""

        # (alan_adı, tip, min, max) — str için min/max = uzunluk sınırları
        REQUIRED_FIELDS = [
            ("driver_id",            str,   1,    64),
            ("blink_rate",           float, 0.0,  60.0),
            ("eye_closure_duration", float, 0.0,  10.0),
            ("head_tilt_angle",      float, 0.0,  90.0),
            ("reaction_delay",       float, 0.0,  5000.0),
        ]

        def __init__(self, **data):
            for key, typ, min_val, max_val in self.REQUIRED_FIELDS:
                if key not in data:
                    raise ValueError(f"Eksik zorunlu alan: {key}")
                try:
                    val = typ(data[key])
                except (TypeError, ValueError):
                    raise ValueError(f"{key} tipi hatalı, beklenen: {typ.__name__}")
                if isinstance(val, str):
                    # String için uzunluk kontrolü
                    stripped = val.strip()
                    if len(stripped) < int(min_val) or len(stripped) > int(max_val):
                        raise ValueError(
                            f"{key} uzunluğu {int(min_val)}-{int(max_val)} karakter arasında olmalı"
                        )
                    val = stripped
                else:
                    # Sayısal tipler için sınır kontrolü
                    if val < min_val or val > max_val:
                        raise ValueError(
                            f"{key} değeri {min_val} ile {max_val} arasında olmalı, gelen: {val}"
                        )
                setattr(self, key, val)

            self.state = data.get("state", "unknown")
            self.phone_risk_score = float(data.get("phone_risk_score", 0.0))
            self.sent_at = data.get("sent_at")
            self.nonce = data.get("nonce")

        def dict(self):
            field_names = [name for name, *_ in self.REQUIRED_FIELDS]
            return {k: getattr(self, k) for k in
                    field_names + ["state", "phone_risk_score", "sent_at", "nonce"]
                    if getattr(self, k, None) is not None}


# ── Yardımcı fonksiyon ────────────────────────────────────────────

def validate_sensor_reading(raw_data):
    """
    Ham JSON verisini doğrula.

    Dönüş değerleri:
        (dict, None)          — doğrulama başarılı, dict kullanılabilir veri
        (None, flask_response) — doğrulama hatası, response'u direkt döndür

    Kullanım:
        data, error = validate_sensor_reading(request.get_json())
        if error:
            return error
        # data güvenli şekilde kullanılabilir
    """
    # Flask import sadece bu fonksiyon çağrıldığında yapılır
    try:
        from flask import jsonify
    except ImportError:
        jsonify = None

    def _error(message, details=None, status=422):
        """422 Unprocessable Entity formatında hata döndür."""
        body = {"error": "validation_error", "message": message}
        if details:
            body["details"] = details
        if jsonify:
            return None, (jsonify(body), status)
        return None, (body, status)

    # Body hiç gönderilmemişse
    if raw_data is None:
        return _error("İstek gövdesi boş. JSON Content-Type ile veri gönderin.")

    if not isinstance(raw_data, dict):
        return _error("İstek gövdesi bir JSON nesnesi (dict) olmalı.")

    # Pydantic ile doğrula
    try:
        reading = SensorReading(**raw_data)
        # Pydantic v1 → .dict(), Pydantic v2 → .model_dump()
        if hasattr(reading, "model_dump"):
            validated = reading.model_dump()
        elif hasattr(reading, "dict"):
            validated = reading.dict()
        else:
            validated = vars(reading)

        # Ekstra alanları da koru (örn. nonce, sent_at, phone_risk_score)
        for k, v in raw_data.items():
            if k not in validated:
                validated[k] = v

        return validated, None

    except Exception as exc:
        # Pydantic validation hatası veya fallback ValueError
        details = []
        if hasattr(exc, "errors"):
            # Pydantic ValidationError → alan bazında detay
            for err in exc.errors():
                field = " → ".join(str(e) for e in err.get("loc", []))
                details.append({"field": field, "message": err.get("msg", str(err))})
        else:
            details = [{"message": str(exc)}]

        return _error(
            "Girdi doğrulama hatası. Lütfen gerekli alanları ve değer sınırlarını kontrol edin.",
            details=details
        )
