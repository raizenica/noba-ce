"""Noba – Tenant management API endpoints."""
from __future__ import annotations

import json
import re

from fastapi import APIRouter, Depends, HTTPException, Request

from ..deps import (
    _client_ip, _get_auth, _require_superadmin, db, get_tenant_id, handle_errors,
)

router = APIRouter()

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{0,62}$")


def _validate_slug(slug: str) -> None:
    if not _SLUG_RE.match(slug):
        raise HTTPException(400, "Slug must be lowercase alphanumeric with hyphens (max 63 chars)")


async def _body(request: Request) -> dict:
    raw = await request.body()
    try:
        return json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid JSON")


# ── Current user's tenant context ────────────────────────────────────────────

@router.get("/api/tenant")
@handle_errors
def api_current_tenant(
    request: Request,
    tenant_id: str = Depends(get_tenant_id),
):
    """Return the current user's active tenant info and all their tenant memberships."""
    username, _ = _get_auth(request)
    tenant = db.get_tenant(tenant_id) or {
        "id": "default", "name": "Default Organization", "slug": "default",
        "created_at": 0, "disabled": 0, "metadata": "{}",
    }
    return {
        "tenant": tenant,
        "tenants": db.get_user_tenants(username),
    }


# ── Tenant CRUD ───────────────────────────────────────────────────────────────

@router.get("/api/tenants")
@handle_errors
def api_list_tenants(auth: tuple = Depends(_require_superadmin)):
    """List all tenants with member counts (admin only)."""
    tenants = db.list_tenants()
    for t in tenants:
        t["member_count"] = db.count_tenant_members(t["id"])
    return tenants


@router.post("/api/tenants")
@handle_errors
async def api_create_tenant(request: Request, auth: tuple = Depends(_require_superadmin)):
    """Create a new tenant."""
    username, _ = auth
    body = await _body(request)
    name = (body.get("name") or "").strip()
    slug = (body.get("slug") or "").strip().lower()
    metadata = body.get("metadata") or {}

    if not name:
        raise HTTPException(400, "name is required")
    if not slug:
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    _validate_slug(slug)

    existing = db.list_tenants()
    if any(t["name"] == name for t in existing):
        raise HTTPException(409, f"Tenant '{name}' already exists")
    if any(t["slug"] == slug for t in existing):
        raise HTTPException(409, f"Slug '{slug}' already taken")

    tenant = db.create_tenant(name, slug, metadata)
    db.audit_log("tenant_create", username,
                 f"Created tenant '{name}' (slug={slug})", _client_ip(request))
    return tenant


@router.get("/api/tenants/{tenant_id}")
@handle_errors
def api_get_tenant(tenant_id: str, auth: tuple = Depends(_require_superadmin)):
    tenant = db.get_tenant(tenant_id)
    if tenant is None:
        raise HTTPException(404, "Tenant not found")
    tenant["member_count"] = db.count_tenant_members(tenant_id)
    return tenant


@router.patch("/api/tenants/{tenant_id}")
@handle_errors
async def api_update_tenant(
    tenant_id: str, request: Request, auth: tuple = Depends(_require_superadmin),
):
    username, _ = auth
    if not db.tenant_exists(tenant_id):
        raise HTTPException(404, "Tenant not found")
    if tenant_id == "default":
        raise HTTPException(400, "The default tenant cannot be modified")
    body = await _body(request)
    db.update_tenant(
        tenant_id,
        name=body.get("name"),
        disabled=body.get("disabled"),
        metadata=body.get("metadata"),
    )
    db.audit_log("tenant_update", username,
                 f"Updated tenant {tenant_id}", _client_ip(request))
    return db.get_tenant(tenant_id)


@router.delete("/api/tenants/{tenant_id}")
@handle_errors
def api_delete_tenant(
    tenant_id: str, request: Request, auth: tuple = Depends(_require_superadmin),
):
    username, _ = auth
    if tenant_id == "default":
        raise HTTPException(400, "The default tenant cannot be deleted")
    if not db.tenant_exists(tenant_id):
        raise HTTPException(404, "Tenant not found")
    if db.count_tenant_members(tenant_id) > 0:
        raise HTTPException(409,
            "Remove all members before deleting the tenant")
    db.delete_tenant(tenant_id)
    db.audit_log("tenant_delete", username,
                 f"Deleted tenant {tenant_id}", _client_ip(request))
    return {"deleted": tenant_id}


# ── Membership management ────────────────────────────────────────────────────

@router.get("/api/tenants/{tenant_id}/members")
@handle_errors
def api_list_members(tenant_id: str, auth: tuple = Depends(_require_superadmin)):
    if not db.tenant_exists(tenant_id):
        raise HTTPException(404, "Tenant not found")
    return db.list_tenant_members(tenant_id)


@router.post("/api/tenants/{tenant_id}/members")
@handle_errors
async def api_add_member(
    tenant_id: str, request: Request, auth: tuple = Depends(_require_superadmin),
):
    caller, _ = auth
    if not db.tenant_exists(tenant_id):
        raise HTTPException(404, "Tenant not found")
    body = await _body(request)
    target = (body.get("username") or "").strip()
    role = (body.get("role") or "viewer").strip()
    if not target:
        raise HTTPException(400, "username is required")
    db.add_tenant_member(tenant_id, target, role)
    db.audit_log("tenant_member_add", caller,
                 f"Added {target} as {role} to tenant {tenant_id}",
                 _client_ip(request))
    return {"tenant_id": tenant_id, "username": target, "role": role}


@router.patch("/api/tenants/{tenant_id}/members/{username}")
@handle_errors
async def api_update_member_role(
    tenant_id: str, username: str, request: Request,
    auth: tuple = Depends(_require_superadmin),
):
    caller, _ = auth
    if not db.tenant_exists(tenant_id):
        raise HTTPException(404, "Tenant not found")
    body = await _body(request)
    role = (body.get("role") or "").strip()
    if not role:
        raise HTTPException(400, "role is required")
    db.update_tenant_member_role(tenant_id, username, role)
    db.audit_log("tenant_member_update", caller,
                 f"Updated {username} to role '{role}' in tenant {tenant_id}",
                 _client_ip(request))
    return {"tenant_id": tenant_id, "username": username, "role": role}


@router.delete("/api/tenants/{tenant_id}/members/{username}")
@handle_errors
def api_remove_member(
    tenant_id: str, username: str, request: Request,
    auth: tuple = Depends(_require_superadmin),
):
    caller, _ = auth
    if not db.tenant_exists(tenant_id):
        raise HTTPException(404, "Tenant not found")
    db.remove_tenant_member(tenant_id, username)
    db.audit_log("tenant_member_remove", caller,
                 f"Removed {username} from tenant {tenant_id}",
                 _client_ip(request))
    return {"removed": username, "tenant_id": tenant_id}
