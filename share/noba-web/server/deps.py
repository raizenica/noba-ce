"""Noba – Shared dependencies for route modules."""
from __future__ import annotations

import collections as _collections
import functools
import hashlib as _hl
import inspect
import ipaddress as _ipaddress
import json
import logging
import subprocess
import threading
import time

from fastapi import Depends, HTTPException, Request

from .auth import authenticate, has_permission, token_store, ws_token_store  # noqa: F401
from .config import MAX_BODY_BYTES, TRUST_PROXY
from .db import db  # noqa: F401  -- re-exported for route modules

_log = logging.getLogger("noba")

# ── bg_collector reference (set during lifespan) ─────────────────────────────
bg_collector: object | None = None


# ── Helpers ──────────────────────────────────────────────────────────────────

def _safe_int(value: object, default: int) -> int:
    """Convert *value* to int, returning *default* on bad input."""
    try:
        return int(value)  # type: ignore[arg-type]
    except (ValueError, TypeError):
        return default


def _int_param(request: Request, name: str, default: int, lo: int, hi: int) -> int:
    """Extract and validate an integer query parameter clamped to [lo, hi]."""
    try:
        v = int(request.query_params.get(name, str(default)))
    except (ValueError, TypeError):
        raise HTTPException(400, f"Invalid {name} parameter")
    return max(lo, min(hi, v))


def _client_ip(request: Request) -> str:
    """Extract client IP, supporting X-Forwarded-For when TRUST_PROXY is set."""
    if TRUST_PROXY:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "0.0.0.0"


async def _read_body(request: Request) -> dict:
    """Read JSON request body with MAX_BODY_BYTES size check."""
    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        raise HTTPException(413, "Request body too large")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid JSON")


def _run_cmd(cmd: list, timeout: float = 3) -> str:
    """Run a subprocess with timeout, returning stdout or empty string on failure."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        return r.stdout.strip()
    except Exception:
        return ""


# ── Route error handler ───────────────────────────────────────────────────────

def handle_errors(func):
    """Catch unhandled exceptions in route handlers and return HTTP 500.

    HTTPException passes through unchanged.
    Do NOT apply to @router.websocket routes or routes returning StreamingResponse —
    those connections are already upgraded; wrapping them corrupts the protocol.
    """
    if inspect.iscoroutinefunction(func):
        @functools.wraps(func)
        async def _async_wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except HTTPException:
                raise
            except Exception:
                _log.exception("Unhandled error in %s", func.__name__)
                raise HTTPException(status_code=500, detail="Internal server error")
        return _async_wrapper
    else:
        @functools.wraps(func)
        def _sync_wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except HTTPException:
                raise
            except Exception:
                _log.exception("Unhandled error in %s", func.__name__)
                raise HTTPException(status_code=500, detail="Internal server error")
        return _sync_wrapper


# ── API key scope / IP / rate-limit enforcement ──────────────────────────────
_api_key_rate_windows: dict[str, _collections.deque] = {}
_rate_windows_lock = threading.Lock()


def _check_api_key_scope(key_row: dict, path: str, client_ip: str) -> None:
    """Enforce scope, IP allowlist, and rate limit on an API key.

    Raises HTTPException(403) for scope/IP violations.
    Raises HTTPException(429) for rate limit exceeded.
    """
    # Scope check: non-empty scope → path must start with one of the prefixes.
    # Paths are like /api/metrics/available — prefixes like "metrics" match against
    # the segment after /api/, or "api/metrics" matches from the root.
    scope = (key_row.get("scope") or "").strip()
    if scope:
        prefixes = [s.strip().lstrip("/") for s in scope.split(",") if s.strip()]
        # Normalise path: strip leading slash
        clean_path = path.lstrip("/")
        # Also try matching against the path with /api/ prefix stripped
        api_stripped = clean_path[4:] if clean_path.startswith("api/") else clean_path
        if not any(
            clean_path == p or clean_path.startswith(p + "/")
            or api_stripped == p or api_stripped.startswith(p + "/")
            for p in prefixes
        ):
            raise HTTPException(status_code=403, detail="API key scope does not permit this endpoint")

    # IP allowlist check
    allowed_ips_raw = key_row.get("allowed_ips") or "[]"
    try:
        allowed_ips = json.loads(allowed_ips_raw) if isinstance(allowed_ips_raw, str) else allowed_ips_raw
    except (ValueError, TypeError):
        allowed_ips = []
    if allowed_ips:
        try:
            client_addr = _ipaddress.ip_address(client_ip)
        except ValueError:
            # Non-parseable client IP (e.g. test hostname) — treat as not in allowlist
            raise HTTPException(status_code=403, detail="Client IP not in API key allowlist")
        allowed = False
        for cidr in allowed_ips:
            try:
                if client_addr in _ipaddress.ip_network(cidr, strict=False):
                    allowed = True
                    break
            except ValueError:
                pass  # malformed CIDR in config — skip this entry
        if not allowed:
            raise HTTPException(status_code=403, detail="Client IP not in API key allowlist")

    # Rate limit check (rolling 60-second window, in-memory)
    rate_limit = key_row.get("rate_limit") or 0
    if rate_limit > 0:
        key_id = key_row.get("id", "")
        now = time.time()
        with _rate_windows_lock:
            if key_id not in _api_key_rate_windows:
                _api_key_rate_windows[key_id] = _collections.deque()
            window = _api_key_rate_windows[key_id]
            while window and window[0] < now - 60:
                window.popleft()
            if len(window) >= rate_limit:
                raise HTTPException(status_code=429, detail="API key rate limit exceeded")
            window.append(now)


# ── Auth dependencies ────────────────────────────────────────────────────────

def _get_auth(request: Request) -> tuple[str, str]:
    """Validate Authorization header and return (username, role).

    Enforces scope/IP/rate-limit for API key tokens.
    """
    auth = request.headers.get("Authorization", "")
    username, role = authenticate(auth)
    if not username:
        raise HTTPException(status_code=401, detail="Unauthorized")
    # Scope/IP/rate check only for API keys (ApiKey prefix)
    if auth.startswith("ApiKey "):
        key = auth[7:]
        key_hash = _hl.sha256(key.encode()).hexdigest()
        try:
            key_row = db.get_api_key(key_hash)
            if key_row:
                _check_api_key_scope(key_row, request.url.path, _client_ip(request))
        except HTTPException:
            raise
        except Exception:
            pass  # DB error — skip scope check
    return username, role


def _get_auth_sse(request: Request) -> tuple[str, str]:
    """Auth for SSE -- also accepts token query param since EventSource can't set headers."""
    auth = request.headers.get("Authorization", "")
    username, role = authenticate(auth)
    if not username:
        tok = request.query_params.get("token", "")
        if tok:
            username, role = token_store.validate(tok)
    if not username:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return username, role


def _require_operator(request: Request) -> tuple[str, str]:
    """Require admin or operator role."""
    username, role = _get_auth(request)
    if role not in ("admin", "operator"):
        raise HTTPException(status_code=403, detail="Forbidden")
    return username, role


def _require_admin(request: Request) -> tuple[str, str]:
    """Require admin role."""
    username, role = _get_auth(request)
    if role != "admin":
        raise HTTPException(status_code=403, detail="Forbidden")
    return username, role


def _require_permission(permission: str):
    """Create a dependency that checks a specific permission."""
    def checker(request: Request) -> tuple[str, str]:
        username, role = _get_auth(request)
        if not has_permission(role, permission):
            raise HTTPException(status_code=403, detail=f"Missing permission: {permission}")
        return username, role
    return checker


def _require_superadmin(request: Request) -> tuple[str, str]:
    """Require admin role (superadmin actions — tenant management).

    Treats 'admin' and 'superadmin' as equivalent so existing single-tenant
    installs continue to work without a role migration.
    """
    username, role = _get_auth(request)
    if role not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Admin role required")
    return username, role


def check_tenant_quota(tenant_id: str, resource: str, limit_key: str) -> None:
    """Raise HTTP 429 if the tenant has hit its quota for *resource*.

    *resource*: human label used in the error message (e.g. "API key").
    *limit_key*: key in limits dict (e.g. "max_api_keys").
    0 = unlimited.
    """
    limits = db.get_tenant_limits(tenant_id)
    max_val = limits.get(limit_key, 0)
    if max_val <= 0:
        return  # unlimited
    counts = db.count_tenant_resources(tenant_id)
    # Map limit_key to count key (strip "max_")
    count_key = limit_key[4:]  # "max_api_keys" → "api_keys"
    current = counts.get(count_key, 0)
    if current >= max_val:
        raise HTTPException(
            status_code=429,
            detail=f"Tenant quota exceeded: maximum {max_val} {resource}(s) allowed.",
        )


def check_resource_acl(resource_type: str, write: bool = False):
    """FastAPI dependency factory — enforce resource-type ACL for the calling user.

    No ACL row = full access (open by default).
    ACL row present = check can_read / can_write flag.
    Admins always bypass ACL checks.
    """
    def _checker(
        request: Request,
        auth: tuple = Depends(_get_auth),
        tenant_id: str = Depends(get_tenant_id),
    ) -> tuple[str, str]:
        username, role = auth
        if role == "admin":
            return auth
        acl = db.get_acl(tenant_id, username, resource_type)
        if acl is None:
            return auth  # no restriction row — full access
        flag = acl["can_write"] if write else acl["can_read"]
        if not flag:
            action = "write" if write else "read"
            raise HTTPException(
                status_code=403,
                detail=f"Access denied: {action} on {resource_type} not permitted.",
            )
        return auth
    return _checker


def get_tenant_id(request: Request) -> str:
    """FastAPI dependency — resolve the calling user's tenant_id.

    Returns 'default' if the user has no tenant membership (backwards compat
    with single-tenant installs).
    """
    username, _ = _get_auth(request)
    return db.get_user_tenant(username) or "default"


def check_not_frozen(
    request: Request,
    auth: tuple = Depends(_get_auth),
    tenant_id: str = Depends(get_tenant_id),
) -> None:
    """Raise HTTP 423 Locked if a change freeze window is active.

    Admins may always proceed. Only operator-level writes are blocked.
    """
    username, role = auth
    if role == "admin":
        return
    if db.is_frozen(tenant_id):
        raise HTTPException(
            status_code=423,
            detail="Change freeze window is active. Operator writes are locked.",
        )


def _require_enterprise(request: Request) -> tuple[str, str]:
    """Require an active enterprise license (trial, grace, or licensed). Admin-only."""
    from .license_manager import get_license_status
    auth = _require_admin(request)
    status = get_license_status()
    if not status["active"]:
        raise HTTPException(
            status_code=402,
            detail="Enterprise license required. Visit Settings → License to activate.",
        )
    return auth


def _require_feature(feature: str):
    """FastAPI dependency factory — requires an active enterprise license with the given feature.

    Usage::

        @router.get("/api/saml/config")
        def my_endpoint(auth=Depends(_require_feature("saml"))):
            ...
    """
    def _check(request: Request) -> tuple[str, str]:
        from .license_manager import get_license_status
        auth = _require_admin(request)
        status = get_license_status()
        if not status["active"]:
            raise HTTPException(
                status_code=402,
                detail="Enterprise license required. Visit Settings → License to activate.",
            )
        if feature not in status["features"]:
            raise HTTPException(
                status_code=402,
                detail=f"The '{feature}' feature is not included in your current plan.",
            )
        return auth
    return _check
