"""
readings.json Güvenliği — Dosya İzni + Opsiyonel Şifreleme.

Sorun:
    data/readings.json tüm sürücü sensör verilerini düz metin olarak
    saklıyor. Dosyaya erişebilen herkes tüm sürüş verilerini okuyabilir.

Bu modülün yaptıkları:
    1. Dosya izinlerini kısıtlar (Linux/Mac: chmod 600 → sadece sahip)
    2. READINGS_ENCRYPT=true ise Fernet (AES-128-CBC + HMAC) ile şifreler
    3. Windows'ta chmod çağrısı sessizce atlanır (uyarı loglanır)
    4. Şifreleme anahtarı .env üzerinden gelir (koda gömülmez)

Kullanım:
    from security.file_guard import save_data, load_data

    # Kaydet (şifreleme aktifse şifreli yazar)
    save_data("data/readings.json", readings_list)

    # Oku (şifreleme aktifse şifre çözer)
    readings = load_data("data/readings.json")

Environment değişkenleri (.env):
    READINGS_ENCRYPT=true          # Şifrelemeyi aktifleştirir
    READINGS_ENCRYPT_KEY=<fernet>  # Fernet anahtarı

Fernet anahtarı üretme:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""

import json
import os
import sys
import stat
import logging

logger = logging.getLogger(__name__)


# ── Environment yükleme ───────────────────────────────────────────

def _load_dotenv():
    """Proje kökündeki .env dosyasını ortama yükle (minimal parser)."""
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
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()

ENCRYPT_ENABLED = os.environ.get("READINGS_ENCRYPT", "false").lower() == "true"
ENCRYPT_KEY_ENV = "READINGS_ENCRYPT_KEY"


# ── Şifreleme yardımcıları ────────────────────────────────────────

def _get_fernet():
    """
    Fernet şifreleme nesnesi döndür.
    Anahtar .env içindeki READINGS_ENCRYPT_KEY değişkeninden okunur.
    """
    key_str = os.environ.get(ENCRYPT_KEY_ENV)
    if not key_str:
        raise RuntimeError(
            f"{ENCRYPT_KEY_ENV} ortam değişkeni boş.\n"
            "Yeni anahtar üretmek için:\n"
            "  python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"\n"
            "Üretilen değeri .env dosyasına READINGS_ENCRYPT_KEY=... olarak ekleyin."
        )
    try:
        from cryptography.fernet import Fernet
        return Fernet(key_str.encode())
    except Exception as e:
        raise RuntimeError(
            f"Fernet anahtarı geçersiz: {e}\n"
            "Lütfen geçerli bir Fernet anahtarı kullanın (base64 URL-safe, 32 byte)."
        )


def _encrypt(data: bytes) -> bytes:
    """Veriyi Fernet ile şifrele."""
    fernet = _get_fernet()
    return fernet.encrypt(data)


def _decrypt(data: bytes) -> bytes:
    """Fernet şifreli veriyi çöz. Anahtar yanlışsa açık hata."""
    fernet = _get_fernet()
    try:
        return fernet.decrypt(data)
    except Exception:
        raise RuntimeError(
            "Şifre çözme başarısız. Anahtar değiştirilmiş olabilir veya dosya bozulmuş."
        )


# ── Dosya izni yardımcıları ───────────────────────────────────────

def _set_permissions_600(path: str) -> None:
    """
    Dosya izinlerini 600 (sadece sahip okur/yazar) olarak ayarla.
    Linux/Mac'te çalışır. Windows'ta sessizce atlanır.
    """
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        logger.debug("Dosya izinleri 600 olarak ayarlandı: %s", path)
    except (AttributeError, NotImplementedError, PermissionError, OSError) as e:
        # Windows'ta chmod tam olarak desteklenmez — uyarı ver, devam et
        logger.warning(
            "Dosya izni ayarlanamadı (%s): %s — "
            "Windows'ta manuel olarak dosya özelliklerinden kısıtlayabilirsiniz.",
            path, e
        )


def _ensure_dir(path: str) -> None:
    """Üst klasörü oluştur (varsa atla)."""
    directory = os.path.dirname(path)
    if directory and not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)
        # Klasör izinlerini de kısıtla (Linux/Mac)
        try:
            os.chmod(directory, stat.S_IRWXU)  # 700
        except (AttributeError, NotImplementedError, PermissionError, OSError):
            pass


# ── Ana fonksiyonlar ──────────────────────────────────────────────

def save_data(path: str, data: list) -> None:
    """
    Veriyi belirtilen dosyaya kaydet.

    READINGS_ENCRYPT=true ise Fernet şifreli olarak yazar.
    Dosya ve klasör yoksa oluşturur.
    Dosya izinlerini kısıtlar (Linux/Mac: 600).

    Parametreler:
        path: Hedef dosya yolu (örn. "data/readings.json")
        data: Kaydedilecek liste (JSON serileştirilebilir olmalı)
    """
    _ensure_dir(path)

    json_bytes = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")

    if ENCRYPT_ENABLED:
        content = _encrypt(json_bytes)
        mode = "wb"
    else:
        content = json_bytes
        mode = "wb"

    with open(path, mode) as f:
        f.write(content)

    _set_permissions_600(path)


def load_data(path: str) -> list:
    """
    Belirtilen dosyadan veriyi oku.

    READINGS_ENCRYPT=true ise şifre çözme uygular.
    Dosya yoksa boş liste döner.
    JSON bozuksa uyarı loglanır ve boş liste döner.

    Parametreler:
        path: Kaynak dosya yolu

    Dönüş:
        list — okunan kayıtlar
    """
    if not os.path.exists(path):
        return []

    try:
        with open(path, "rb") as f:
            raw = f.read()

        if not raw.strip():
            return []

        if ENCRYPT_ENABLED:
            raw = _decrypt(raw)

        return json.loads(raw.decode("utf-8"))

    except RuntimeError:
        # Şifre çözme hatası — ciddi, yeniden fırlat
        raise
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        logger.warning("Dosya okunamadı / JSON bozuk (%s): %s — boş liste döndürülüyor", path, e)
        return []
    except OSError as e:
        logger.error("Dosya okuma hatası (%s): %s", path, e)
        return []
