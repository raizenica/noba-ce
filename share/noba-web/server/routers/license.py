"""Noba – License management API endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from ..auth import users as _user_store
from ..deps import _client_ip, _require_admin, db, handle_errors
from ..license_manager import get_license_status, install_license

router = APIRouter()


@router.get("/api/license/status")
@handle_errors
def api_license_status(auth=Depends(_require_admin)):
    """Return full license status including trial state, features, and seat count."""
    status = get_license_status()
    users = _user_store.list_users()
    return {**status, "user_count": len(users)}


@router.post("/api/license/upload")
@handle_errors
async def api_license_upload(request: Request, auth=Depends(_require_admin)):
    """Upload and install a .noba-license file."""
    username, _ = auth
    raw = await request.body()
    if not raw:
        raise HTTPException(400, "Empty request body")
    if len(raw) > 65_536:
        raise HTTPException(413, "License file too large (max 64 KB)")
    try:
        status = install_license(raw)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    db.audit_log(
        "license_install", username,
        f"Installed {status['plan']} license for '{status['licensee']}'",
        _client_ip(request),
    )
    return status


@router.delete("/api/license")
@handle_errors
def api_license_remove(request: Request, auth=Depends(_require_admin)):
    """Remove the installed license file (reverts to trial/unlicensed state)."""
    import os
    from ..config import NOBA_LICENSE
    from ..license_manager import _invalidate_cache
    username, _ = auth
    if os.path.exists(NOBA_LICENSE):
        os.remove(NOBA_LICENSE)
        _invalidate_cache()
        db.audit_log("license_remove", username, "Removed license file", _client_ip(request))
    return get_license_status()
