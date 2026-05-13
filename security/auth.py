"""
Flask API key auth — basit, paylaşılan-sır tabanlı kimlik doğrulama.

Kullanım:
    from security.auth import require_api_key

    @app.route('/sensor-data', methods=['POST'])
    @require_api_key
    def receive_data():
        ...

Çağıran taraf isteklere `X-API-Key: <key>` header'ı eklemeli.
Anahtar `.env` içindeki IOT_API_KEY environment variable'ından okunur.

Not: Bu, TLS olmayan localhost setup için yeterli. Üretimde mutlaka
HTTPS + sertifika tabanlı mTLS veya OAuth gibi standartlar tercih edin.
"""

from functools import wraps
import hmac
import os

from flask import request, jsonify

from security.crypto import _load_dotenv_if_present


_ENV_VAR = "IOT_API_KEY"
_HEADER_NAME = "X-API-Key"


def get_api_key() -> str:
    """
    API anahtarını ortamdan al. Eksikse açık hata fırlat.
    """
    _load_dotenv_if_present()
    key = os.environ.get(_ENV_VAR)
    if not key:
        raise RuntimeError(
            f"{_ENV_VAR} environment variable boş. "
            f".env dosyasına {_ENV_VAR}=<rastgele-değer> ekleyin."
        )
    if len(key) < 16:
        raise RuntimeError(
            f"{_ENV_VAR} en az 16 karakter olmalı."
        )
    return key


def require_api_key(view):
    """
    Flask view'ı kimlik doğrulamayla koru.

    - Header eksikse 401
    - Header yanlışsa 403
    - Karşılaştırma sabit-zamanlı (timing attack koruması)
    """
    expected = get_api_key()  # uygulama açılırken yüklenir → fail-fast

    @wraps(view)
    def wrapper(*args, **kwargs):
        provided = request.headers.get(_HEADER_NAME)
        if not provided:
            return jsonify({
                "error": "missing_api_key",
                "message": f"{_HEADER_NAME} header'ı gerekli"
            }), 401
        if not hmac.compare_digest(provided, expected):
            return jsonify({
                "error": "invalid_api_key",
                "message": "API anahtarı hatalı"
            }), 403
        return view(*args, **kwargs)

    return wrapper
