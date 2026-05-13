"""
HMAC-SHA256 imzalama / doğrulama yardımcıları.

Kullanım amacı:
    UDP üzerinden gönderilen sensor verisinin yolda değiştirilmediğini
    (integrity) ve göndericinin paylaşılan secret'i bilen meşru bir
    kaynak olduğunu (authenticity) garanti altına almak.

Zarf (envelope) formatı:
    {
        "payload": {...orijinal sensor verisi...},
        "sig":     "<hex hmac-sha256>"
    }

Secret nereden gelir?
    İşletim sistemi environment variable'ı: IOT_HMAC_SECRET
    Üretim ortamında bir secret manager (Vault, AWS Secrets Manager,
    K8s secret) kullanılmalı. Geliştirme için .env dosyası yeterli.
"""

import hmac
import hashlib
import json
import os


_ENV_VAR = "IOT_HMAC_SECRET"


def _load_dotenv_if_present():
    """
    Proje kökündeki .env dosyasını basitçe ortama yükle.
    python-dotenv bağımlılığı eklememek için minimal parser.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.abspath(os.path.join(here, os.pardir))
    env_path = os.path.join(root, ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            # Var olan ortam değişkenini ezme
            os.environ.setdefault(key, value)


def get_secret() -> bytes:
    """
    HMAC secret'i ortamdan al. Bulamazsa açık hata fırlat.
    """
    _load_dotenv_if_present()
    secret = os.environ.get(_ENV_VAR)
    if not secret:
        raise RuntimeError(
            f"{_ENV_VAR} environment variable boş. "
            f"Proje kökünde .env dosyası oluşturup "
            f"{_ENV_VAR}=<güçlü-rastgele-değer> satırını ekleyin."
        )
    if len(secret) < 16:
        raise RuntimeError(
            f"{_ENV_VAR} en az 16 karakter olmalı (güçlü rastgele değer)."
        )
    return secret.encode("utf-8")


def _canonical(payload: dict) -> bytes:
    """
    Tutarlı (deterministik) JSON serileştirme.
    sort_keys + boşluksuz separator → aynı içerik her seferinde
    aynı byte dizisini üretir, bu da HMAC'ın platformlar arası
    uyumlu çalışmasını sağlar.
    """
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sign_payload(payload: dict, secret: bytes | None = None) -> dict:
    """
    Verilen payload'ı HMAC-SHA256 ile imzala ve zarf (envelope) döndür.
    """
    if secret is None:
        secret = get_secret()
    sig = hmac.new(secret, _canonical(payload), hashlib.sha256).hexdigest()
    return {"payload": payload, "sig": sig}


def verify_envelope(envelope: dict, secret: bytes | None = None) -> dict:
    """
    Gelen zarfı doğrula ve içindeki payload'ı geri ver.
    Doğrulama başarısızsa ValueError fırlatır.
    """
    if not isinstance(envelope, dict):
        raise ValueError("Envelope bir dict olmalı")
    if "payload" not in envelope or "sig" not in envelope:
        raise ValueError("Envelope eksik: 'payload' ve 'sig' alanları zorunlu")

    payload = envelope["payload"]
    received_sig = envelope["sig"]

    if not isinstance(payload, dict) or not isinstance(received_sig, str):
        raise ValueError("Envelope alan tipleri hatalı")

    if secret is None:
        secret = get_secret()

    expected_sig = hmac.new(
        secret, _canonical(payload), hashlib.sha256
    ).hexdigest()

    # Sabit zamanlı karşılaştırma — timing attack'ı önler
    if not hmac.compare_digest(expected_sig, received_sig):
        raise ValueError("HMAC imzası uyuşmuyor (payload manipüle edilmiş olabilir)")

    return payload
