"""Noba – Enterprise license management.

License states
--------------
trial       : within the 60-day evaluation window (full features)
grace       : 7-day grace after trial expires (features still active, banner shown)
unlicensed  : past grace, no license — enterprise features gated
licensed    : valid signed license present, support period active
expired     : license support period ended — features still active (perpetual model)
"""
from __future__ import annotations

import base64
import json
import logging
import os
import threading
import time
from typing import Any

logger = logging.getLogger("noba")

# ── Embedded public key (Ed25519, base64url) ──────────────────────────────────
_PUBLIC_KEY_B64 = "Bi4w3QGS9umTzy8eGMvs21MUvU3l0Hxe8AAVO5qT9lQ="

# ── Constants ─────────────────────────────────────────────────────────────────
TRIAL_DAYS = 60
GRACE_DAYS = 7
FREE_SEATS = 3  # user accounts allowed without a license

ALL_FEATURES = [
    "saml", "scim", "webauthn", "branding",
    "multi_instance", "audit_export", "unlimited_seats",
]

# ── Cache ─────────────────────────────────────────────────────────────────────
_cache_lock = threading.Lock()
_cached_status: dict | None = None
_cache_ts = 0.0
_CACHE_TTL = 300  # 5 minutes


def _invalidate_cache() -> None:
    global _cached_status, _cache_ts
    with _cache_lock:
        _cached_status = None
        _cache_ts = 0.0


# ── Ed25519 signature verification ───────────────────────────────────────────
def _verify_signature(payload: dict, signature_b64: str) -> bool:
    """Verify that *payload* (minus the 'signature' key) was signed with our key."""
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        pub_bytes = base64.urlsafe_b64decode(_PUBLIC_KEY_B64 + "==")
        pub_key = Ed25519PublicKey.from_public_bytes(pub_bytes)

        # Canonical form: sorted keys, no whitespace, no signature field
        canonical = json.dumps(
            {k: v for k, v in payload.items() if k != "signature"},
            sort_keys=True, separators=(",", ":"),
        )
        sig_bytes = base64.urlsafe_b64decode(signature_b64 + "==")
        pub_key.verify(sig_bytes, canonical.encode())
        return True
    except InvalidSignature:
        return False
    except Exception as exc:
        logger.warning("License signature verification error: %s", exc)
        return False


# ── Trial state ───────────────────────────────────────────────────────────────
def _get_trial_start() -> int:
    """Return the trial start timestamp, initialising it on first call."""
    try:
        from .yaml_config import read_yaml_settings, write_yaml_settings
        cfg = read_yaml_settings()
        ts = int(cfg.get("trialStartTs", 0) or 0)
        if ts == 0:
            ts = int(time.time())
            write_yaml_settings({"trialStartTs": ts})
            logger.info("Enterprise trial started (ts=%d)", ts)
        return ts
    except Exception as exc:
        logger.warning("Could not persist trial start timestamp: %s", exc)
        return int(time.time())


# ── Core computation ──────────────────────────────────────────────────────────
def _compute_status() -> dict[str, Any]:
    from .config import NOBA_LICENSE

    now = int(time.time())

    # ── Try loading the license file first ────────────────────────────────────
    if os.path.exists(NOBA_LICENSE):
        try:
            with open(NOBA_LICENSE, encoding="utf-8") as fh:
                lic = json.load(fh)
            sig = lic.get("signature", "")
            if _verify_signature(lic, sig):
                expires_at = int(lic.get("expires_at", 0))
                features   = lic.get("features", ALL_FEATURES)
                seats      = int(lic.get("seats", 0))
                if expires_at and now >= expires_at:
                    state = "expired"
                    days_remaining = 0
                else:
                    state = "licensed"
                    days_remaining = (
                        max(0, (expires_at - now) // 86400) if expires_at else None
                    )
                return {
                    "state":          state,
                    "active":         True,   # perpetual: features never die
                    "plan":           lic.get("plan", "enterprise"),
                    "licensee":       lic.get("licensee", ""),
                    "seats":          seats,
                    "features":       features,
                    "expires_at":     expires_at,
                    "days_remaining": days_remaining,
                    "trial":          False,
                }
            else:
                logger.warning(
                    "License file at %s has an invalid signature — ignoring",
                    NOBA_LICENSE,
                )
        except Exception as exc:
            logger.warning("Could not read license file: %s", exc)

    # ── No valid license — check trial / grace / unlicensed ──────────────────
    trial_start = _get_trial_start()
    trial_end   = trial_start + TRIAL_DAYS * 86400
    grace_end   = trial_start + (TRIAL_DAYS + GRACE_DAYS) * 86400

    if now < trial_end:
        return {
            "state":          "trial",
            "active":         True,
            "plan":           "enterprise",
            "licensee":       "",
            "seats":          0,
            "features":       ALL_FEATURES,
            "expires_at":     trial_end,
            "days_remaining": max(0, (trial_end - now) // 86400),
            "trial":          True,
        }

    if now < grace_end:
        return {
            "state":          "grace",
            "active":         True,
            "plan":           "enterprise",
            "licensee":       "",
            "seats":          0,
            "features":       ALL_FEATURES,
            "expires_at":     grace_end,
            "days_remaining": max(0, (grace_end - now) // 86400),
            "trial":          True,
        }

    return {
        "state":          "unlicensed",
        "active":         False,
        "plan":           "free",
        "licensee":       "",
        "seats":          FREE_SEATS,
        "features":       [],
        "expires_at":     0,
        "days_remaining": 0,
        "trial":          False,
    }


# ── Public API ────────────────────────────────────────────────────────────────
def get_license_status() -> dict[str, Any]:
    """Return cached license status, recomputing every 5 minutes."""
    global _cached_status, _cache_ts
    with _cache_lock:
        if _cached_status is not None and time.time() - _cache_ts < _CACHE_TTL:
            return _cached_status
    status = _compute_status()
    with _cache_lock:
        _cached_status = status
        _cache_ts = time.time()
    return status


def install_license(data: bytes) -> dict[str, Any]:
    """Validate and install a license file. Returns the new status on success."""
    from .config import NOBA_LICENSE

    try:
        lic = json.loads(data.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"Invalid license file format: {exc}") from exc

    sig = lic.get("signature", "")
    if not sig:
        raise ValueError("License file is missing a signature field")
    if not _verify_signature(lic, sig):
        raise ValueError("License signature is invalid — file may be tampered or from a different issuer")

    os.makedirs(os.path.dirname(NOBA_LICENSE), exist_ok=True)
    tmp = NOBA_LICENSE + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, NOBA_LICENSE)

    _invalidate_cache()
    logger.info(
        "License installed: licensee=%s plan=%s seats=%s",
        lic.get("licensee"), lic.get("plan"), lic.get("seats"),
    )
    return get_license_status()
