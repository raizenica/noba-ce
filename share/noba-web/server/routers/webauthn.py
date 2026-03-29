"""Noba – WebAuthn/FIDO2 passwordless authentication and MFA backup codes."""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import struct
import threading
import time

from fastapi import APIRouter, Depends, HTTPException, Request

from ..auth import token_store, users
from ..deps import _get_auth, _read_body, db, handle_errors

logger = logging.getLogger("noba")
router = APIRouter()

# ── In-memory challenge store ─────────────────────────────────────────────────
_challenges: dict[str, tuple[str, float]] = {}
_challenges_lock = threading.Lock()
_CHALLENGE_TTL = 120


def _store_challenge(username: str, challenge: bytes) -> str:
    b64 = base64.urlsafe_b64encode(challenge).rstrip(b"=").decode()
    with _challenges_lock:
        _challenges[username] = (b64, time.time() + _CHALLENGE_TTL)
    return b64


def _pop_challenge(username: str) -> str | None:
    with _challenges_lock:
        entry = _challenges.pop(username, None)
        if not entry:
            return None
        b64, expiry = entry
        return b64 if time.time() <= expiry else None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _b64url_decode(s: str) -> bytes:
    s = s.replace("-", "+").replace("_", "/")
    pad = 4 - len(s) % 4
    if pad != 4:
        s += "=" * pad
    return base64.b64decode(s)


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _get_rp_id(request: Request) -> str:
    return request.headers.get("X-Forwarded-Host", request.url.hostname or "localhost")


def _get_rp_name() -> str:
    return "NOBA Command Center"


def _cbor_decode(data: bytes) -> object:
    """Minimal CBOR decoder for WebAuthn attestation objects."""
    result, _ = _cbor_decode_item(data, 0)
    return result


def _cbor_decode_item(data: bytes, pos: int) -> tuple[int, object]:
    if pos >= len(data):
        raise ValueError("CBOR: unexpected end of data")
    initial = data[pos]
    major = (initial >> 5) & 0x07
    info = initial & 0x1F
    pos += 1
    if info < 24:
        length = info
    elif info == 24:
        length = data[pos]
        pos += 1
    elif info == 25:
        length = struct.unpack_from(">H", data, pos)[0]
        pos += 2
    elif info == 26:
        length = struct.unpack_from(">I", data, pos)[0]
        pos += 4
    else:
        raise ValueError(f"CBOR: unsupported additional info {info}")

    if major == 0:  # unsigned int
        return pos, length
    elif major == 2:  # bytes
        val = data[pos:pos + length]
        pos += length
        return pos, val
    elif major == 3:  # text
        val = data[pos:pos + length].decode()
        pos += length
        return pos, val
    elif major == 4:  # array
        items = []
        for _ in range(length):
            pos, item = _cbor_decode_item(data, pos)
            items.append(item)
        return pos, items
    elif major == 5:  # map
        d = {}
        for _ in range(length):
            pos, k = _cbor_decode_item(data, pos)
            pos, v = _cbor_decode_item(data, pos)
            d[k] = v
        return pos, d
    elif major == 1:  # negative int
        return pos, -1 - length
    # Note: Major types 6 (tagged) and 7 (floats/special) are not implemented.
    # Standard passkey attestation formats (none, packed, FIDO-U2F) do not use them.
    # Enterprise hardware tokens using CBOR tags will receive HTTP 500 from handle_errors.
    raise ValueError(f"CBOR: unsupported major type {major}")


def _cose_key_to_pem(cose_map: dict) -> str:
    """Convert a COSE EC2 P-256 key map to PEM public key."""
    from cryptography.hazmat.primitives.asymmetric.ec import (
        EllipticCurvePublicNumbers,
        SECP256R1,
    )
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        PublicFormat,
    )

    x = cose_map.get(-2, b"")
    y = cose_map.get(-3, b"")
    if not x or not y:
        raise ValueError("COSE key missing x or y")
    nums = EllipticCurvePublicNumbers(
        x=int.from_bytes(x, "big"),
        y=int.from_bytes(y, "big"),
        curve=SECP256R1(),
    )
    pub = nums.public_key()
    return pub.public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode()


def _verify_signature(pem: str, signature: bytes, signed_data: bytes) -> bool:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ec import ECDSA
    from cryptography.hazmat.primitives.hashes import SHA256
    from cryptography.hazmat.primitives.serialization import load_pem_public_key

    try:
        pub = load_pem_public_key(pem.encode())
        pub.verify(signature, signed_data, ECDSA(SHA256()))
        return True
    except InvalidSignature:
        return False


def _parse_auth_data(auth_data: bytes) -> dict:
    rp_id_hash = auth_data[:32]
    flags = auth_data[32]
    sign_count = struct.unpack_from(">I", auth_data, 33)[0]
    result: dict = {"rp_id_hash": rp_id_hash, "flags": flags, "sign_count": sign_count}
    if flags & 0x40 and len(auth_data) > 37:  # AT flag — attested credential data
        aaguid = auth_data[37:53]
        cred_id_len = struct.unpack_from(">H", auth_data, 53)[0]
        cred_id = auth_data[55:55 + cred_id_len]
        cose_key_data = auth_data[55 + cred_id_len:]
        result["aaguid"] = aaguid
        result["credential_id"] = cred_id
        result["cose_key_data"] = cose_key_data
    return result


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/api/webauthn/register/begin")
@handle_errors
async def webauthn_register_begin(
    request: Request,
    auth: tuple[str, str] = Depends(_get_auth),
):
    """Return PublicKeyCredentialCreationOptions for registration."""
    username, _role = auth
    existing = db.webauthn_get_credentials(username)
    challenge = os.urandom(32)
    challenge_b64 = _store_challenge(username, challenge)
    rp_id = _get_rp_id(request)
    return {
        "challenge": challenge_b64,
        "rp": {"name": _get_rp_name(), "id": rp_id},
        "user": {
            "id": _b64url_encode(username.encode()),
            "name": username,
            "displayName": username,
        },
        "pubKeyCredParams": [{"type": "public-key", "alg": -7}],
        "excludeCredentials": [
            {"type": "public-key", "id": _b64url_encode(c["credential_id"])}
            for c in existing
        ],
        "authenticatorSelection": {"userVerification": "preferred"},
        "timeout": 60000,
    }


@router.post("/api/webauthn/register/complete")
@handle_errors
async def webauthn_register_complete(
    request: Request,
    auth: tuple[str, str] = Depends(_get_auth),
):
    """Verify attestation and store new credential."""
    username, _role = auth
    body = await _read_body(request)
    client_data_b64 = body.get("response", {}).get("clientDataJSON", "")
    auth_data_b64 = body.get("response", {}).get("attestationObject", "")
    name = body.get("name", "Security Key")
    if not client_data_b64 or not auth_data_b64:
        raise HTTPException(400, "Missing clientDataJSON or attestationObject")

    client_data = json.loads(_b64url_decode(client_data_b64))
    if client_data.get("type") != "webauthn.create":
        raise HTTPException(400, "Invalid ceremony type")

    stored_challenge = _pop_challenge(username)
    if not stored_challenge:
        raise HTTPException(400, "Challenge expired or not found")
    if client_data.get("challenge") != stored_challenge:
        raise HTTPException(400, "Challenge mismatch")

    att_obj = _cbor_decode(_b64url_decode(auth_data_b64))
    if not isinstance(att_obj, dict):
        raise HTTPException(400, "Invalid attestation object")
    auth_data_bytes = att_obj.get("authData", b"")
    parsed = _parse_auth_data(auth_data_bytes)
    if not (parsed["flags"] & 0x01):  # bit 0 = User Presence
        raise HTTPException(400, "User presence not set")

    cred_id = parsed.get("credential_id")
    cose_data = parsed.get("cose_key_data")
    if not cred_id or not cose_data:
        raise HTTPException(400, "Missing credential data in attestation")

    cose_map = _cbor_decode(cose_data)
    pem = _cose_key_to_pem(cose_map)
    db.webauthn_store_credential(username, cred_id, pem.encode(), parsed["sign_count"], name)
    db.audit_log("webauthn_register", username, f"Registered key: {name}")
    return {"status": "ok", "credential_id": _b64url_encode(cred_id)}


@router.post("/api/webauthn/login/begin")
@handle_errors
async def webauthn_login_begin(request: Request):
    """Return PublicKeyCredentialRequestOptions for authentication."""
    body = await _read_body(request)
    username = body.get("username", "")
    if not username:
        raise HTTPException(400, "Username required")
    if not users.exists(username):
        raise HTTPException(404, "User not found")
    credentials = db.webauthn_get_credentials(username)
    if not credentials:
        raise HTTPException(404, "No credentials registered for this user")

    challenge = os.urandom(32)
    challenge_b64 = _store_challenge(username, challenge)
    return {
        "challenge": challenge_b64,
        "allowCredentials": [
            {"type": "public-key", "id": _b64url_encode(c["credential_id"])}
            for c in credentials
        ],
        "userVerification": "preferred",
        "timeout": 60000,
    }


@router.post("/api/webauthn/login/complete")
@handle_errors
async def webauthn_login_complete(request: Request):
    """Verify assertion and issue session token on success."""
    body = await _read_body(request)
    username = body.get("username", "")
    client_data_b64 = body.get("response", {}).get("clientDataJSON", "")
    auth_data_b64 = body.get("response", {}).get("authenticatorData", "")
    sig_b64 = body.get("response", {}).get("signature", "")
    cred_id_b64 = body.get("id", "")
    if not all([username, client_data_b64, auth_data_b64, sig_b64, cred_id_b64]):
        raise HTTPException(400, "Missing required fields")

    stored_challenge = _pop_challenge(username)
    if not stored_challenge:
        raise HTTPException(400, "Challenge expired or not found")

    client_data = json.loads(_b64url_decode(client_data_b64))
    if client_data.get("type") != "webauthn.get":
        raise HTTPException(400, "Invalid ceremony type")
    if client_data.get("challenge") != stored_challenge:
        raise HTTPException(400, "Challenge mismatch")

    cred_id_bytes = _b64url_decode(cred_id_b64)
    cred = db.webauthn_get_credential_by_id(cred_id_bytes)
    if not cred or cred["username"] != username:
        raise HTTPException(401, "Credential not found")

    auth_data_bytes = _b64url_decode(auth_data_b64)
    sig_bytes = _b64url_decode(sig_b64)
    client_data_hash = hashlib.sha256(_b64url_decode(client_data_b64)).digest()
    signed_data = auth_data_bytes + client_data_hash

    pem = cred["public_key"].decode() if isinstance(cred["public_key"], bytes) else cred["public_key"]
    if not _verify_signature(pem, sig_bytes, signed_data):
        raise HTTPException(401, "Signature verification failed")

    parsed = _parse_auth_data(auth_data_bytes)
    expected_rp_id_hash = hashlib.sha256(_get_rp_id(request).encode()).digest()
    if parsed["rp_id_hash"] != expected_rp_id_hash:
        raise HTTPException(400, "RP ID hash mismatch")
    if not (parsed["flags"] & 0x01):  # bit 0 = User Presence
        raise HTTPException(400, "User presence not set")
    new_count = parsed["sign_count"]
    if new_count != 0 and new_count <= cred["sign_count"]:
        raise HTTPException(401, "Sign count replay detected")
    db.webauthn_update_sign_count(cred_id_bytes, new_count)

    user_data = users.get(username)
    role = user_data[1] if user_data else "viewer"
    token = token_store.generate(username, role)
    db.audit_log("webauthn_login", username, "success")
    return {"token": token, "username": username, "role": role}


@router.post("/api/webauthn/backup-codes/generate")
@handle_errors
async def backup_codes_generate(
    request: Request,
    auth: tuple[str, str] = Depends(_get_auth),
):
    """Generate 10 single-use 8-char hex recovery codes."""
    username, _role = auth
    codes: list[str] = []
    hashes: list[str] = []
    for _ in range(10):
        code = secrets.token_hex(4).upper()
        codes.append(code)
        hashes.append(hashlib.sha256(code.encode()).hexdigest())
    db.webauthn_store_backup_codes(username, hashes)
    db.audit_log("backup_codes_generate", username, "Generated 10 backup codes")
    return {"codes": codes, "count": 10}


@router.post("/api/webauthn/backup-codes/verify")
@handle_errors
async def backup_codes_verify(request: Request):
    """Consume a backup code and issue a session token."""
    body = await _read_body(request)
    username = body.get("username", "")
    code = body.get("code", "")
    if not username or not code:
        raise HTTPException(400, "username and code required")
    if not users.exists(username):
        raise HTTPException(404, "User not found")
    code_hash = hashlib.sha256(code.upper().encode()).hexdigest()
    if not db.webauthn_verify_backup_code(username, code_hash):
        raise HTTPException(401, "Invalid or already used backup code")
    user_data = users.get(username)
    role = user_data[1] if user_data else "viewer"
    token = token_store.generate(username, role)
    db.audit_log("backup_code_login", username, "Backup code consumed")
    return {"token": token, "username": username, "role": role}


@router.get("/api/webauthn/credentials")
@handle_errors
async def webauthn_list_credentials(
    request: Request,
    auth: tuple[str, str] = Depends(_get_auth),
):
    """List registered WebAuthn credentials for the authenticated user."""
    username, _role = auth
    creds = db.webauthn_get_credentials(username)
    return {
        "credentials": [
            {
                "id": _b64url_encode(c["credential_id"]),
                "name": c["name"],
                "created_at": c["created_at"],
            }
            for c in creds
        ]
    }


@router.delete("/api/webauthn/credentials/{cred_id}")
@handle_errors
async def webauthn_delete_credential(
    cred_id: str,
    request: Request,
    auth: tuple[str, str] = Depends(_get_auth),
):
    """Delete a WebAuthn credential by base64url-encoded ID."""
    username, _role = auth
    cred_id_bytes = _b64url_decode(cred_id)
    cred = db.webauthn_get_credential_by_id(cred_id_bytes)
    if not cred or cred["username"] != username:
        raise HTTPException(404, "Credential not found")
    db.webauthn_delete_credential(cred_id_bytes)
    db.audit_log("webauthn_delete", username, f"Deleted credential id={cred_id}")
    return {"status": "ok"}
