"""
Replay Attack Koruması — Nonce + Timestamp tabanlı.

Sorun:
    HMAC imzası bir paketin gerçek kaynaktan geldiğini kanıtlar ama
    aynı geçerli paketin tekrar gönderilmesini (replay) engellemez.
    Saldırgan şu senaryoyu uygulayabilir:
        1. Geçerli bir UDP paketi ağdan yakalar.
        2. Aynı paketi defalarca gönderir.
        3. Her seferinde sistem paketi "geçerli" olarak kabul eder.
        → Sahte "drowsy" okumalar → gereksiz alarm patlaması

Çözüm:
    Her pakette iki ek alan zorunlu:
        - nonce  : UUID4 veya rastgele string — her pakette tekil olmalı
        - sent_at: ISO 8601 UTC timestamp   — ne zaman gönderildiğini belirtir

    Kurallar:
        1. sent_at şu andan MAX_AGE_SECONDS saniyeden eskiyse → RED
        2. Aynı nonce daha önce görüldüyse → RED
        3. Geçerli nonce → kabul et, nonce'u cache'e ekle

    Cache yönetimi:
        - Her kontrolde süresi dolmuş (TTL_SECONDS geçmiş) nonce'lar silinir
        - Bu bellek sızıntısını önler

Kullanım:
    from security.replay_guard import ReplayGuard

    guard = ReplayGuard()          # UDP Bridge başlarken bir kez oluştur

    # Her paket alındığında:
    try:
        guard.check(payload)       # payload dict içinde 'nonce' ve 'sent_at' olmalı
    except ValueError as e:
        print(f"Replay veya eski paket reddedildi: {e}")
        continue
"""

import time
from datetime import datetime, timezone, timedelta


# Saniye cinsinden maksimum paket yaşı — bundan eski paketler reddedilir
MAX_AGE_SECONDS = 30

# Saniye cinsinden nonce cache TTL — bu süre geçince nonce cache'den silinir
CACHE_TTL_SECONDS = 60


class ReplayGuard:
    """
    Thread-safe olmayan, tek process için nonce + timestamp replay koruması.

    Çok sayıda process / worker varsa nonce'ların Redis veya veritabanında
    saklanması gerekir. Bu proje tek process çalıştığından in-memory yeterli.
    """

    def __init__(
        self,
        max_age_seconds: int = MAX_AGE_SECONDS,
        cache_ttl_seconds: int = CACHE_TTL_SECONDS,
    ):
        self.max_age = max_age_seconds
        self.cache_ttl = cache_ttl_seconds
        # {nonce: unix_timestamp_float} — ne zaman görüldüğünü sakla
        self._seen: dict[str, float] = {}

    # ── Ana kontrol ───────────────────────────────────────────────

    def check(self, payload: dict) -> None:
        """
        Payload'ı replay ve yaş kontrolünden geçir.

        Başarılıysa None döner (sessiz).
        Başarısızsa ValueError fırlatır.

        Parametre:
            payload: verify_envelope() sonucundan gelen dict.
                     'nonce' ve 'sent_at' alanları bekleniyor.
        """
        self._cleanup_expired()

        # ── 1. Timestamp kontrolü ─────────────────────────────────
        sent_at_raw = payload.get("sent_at")
        if sent_at_raw is None:
            raise ValueError(
                "Payload 'sent_at' alanı eksik — timestamp zorunlu (replay koruması)"
            )

        try:
            sent_at = datetime.fromisoformat(sent_at_raw)
            # Timezone-aware değilse UTC kabul et
            if sent_at.tzinfo is None:
                sent_at = sent_at.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            raise ValueError(
                f"'sent_at' alanı geçerli ISO 8601 timestamp değil: {sent_at_raw!r}"
            )

        now = datetime.now(timezone.utc)
        age_seconds = (now - sent_at).total_seconds()

        if age_seconds > self.max_age:
            raise ValueError(
                f"Paket çok eski: {round(age_seconds, 1)}s geçmiş "
                f"(maksimum {self.max_age}s izin veriliyor) — replay saldırısı olabilir"
            )

        if age_seconds < -5:
            # Gönderenin saati 5 saniyeden fazla ileriyse şüpheli
            raise ValueError(
                f"Paket timestamp'i gelecekte: {round(-age_seconds, 1)}s ileride — "
                "saat senkronizasyonu kontrol edilmeli"
            )

        # ── 2. Nonce kontrolü ─────────────────────────────────────
        nonce = payload.get("nonce")
        if nonce is None:
            raise ValueError(
                "Payload 'nonce' alanı eksik — her pakette tekil nonce zorunlu"
            )
        if not isinstance(nonce, str) or len(nonce) < 8:
            raise ValueError(
                f"'nonce' en az 8 karakter olmalı (gelen: {len(str(nonce))} karakter)"
            )

        if nonce in self._seen:
            raise ValueError(
                f"Nonce daha önce görüldü: {nonce!r} — replay saldırısı!"
            )

        # Geçerli — nonce'u kaydet
        self._seen[nonce] = time.monotonic()

    # ── Cache temizliği ───────────────────────────────────────────

    def _cleanup_expired(self) -> None:
        """
        TTL süresi geçmiş nonce'ları sil.
        Her check() çağrısında otomatik çalışır — bellek sızıntısı olmaz.
        """
        now = time.monotonic()
        expired = [
            nonce for nonce, seen_at in self._seen.items()
            if (now - seen_at) > self.cache_ttl
        ]
        for nonce in expired:
            del self._seen[nonce]

    @property
    def cache_size(self) -> int:
        """Şu an cache'de kaç nonce var."""
        return len(self._seen)


# ── Modül düzeyinde paylaşılan instance ──────────────────────────
# udp_bridge.py bu singleton'ı import eder — her paket için aynı
# instance kullanılır, böylece nonce geçmişi korunur.
_guard = ReplayGuard()


def check_replay(payload: dict) -> None:
    """
    Modül düzeyindeki ReplayGuard singleton'ı ile kontrol.

    Kullanım:
        from security.replay_guard import check_replay

        check_replay(payload)   # ValueError fırlatırsa reddet
    """
    _guard.check(payload)
