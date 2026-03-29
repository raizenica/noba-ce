"""Noba – SCIM 2.0 user provisioning (RFC 7644)."""
from __future__ import annotations

import hashlib
import logging
import secrets

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from ..auth import pbkdf2_hash, users, valid_username
from ..deps import _int_param, _read_body, db, handle_errors

logger = logging.getLogger("noba")
router = APIRouter()

_SCIM_CONTENT = "application/scim+json"
_VALID_ROLES = {"viewer", "operator", "admin"}


def _scim_error(status: int, detail: str, scim_type: str = "") -> JSONResponse:
    body: dict = {
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:Error"],
        "detail": detail,
        "status": str(status),
    }
    if scim_type:
        body["scimType"] = scim_type
    return JSONResponse(content=body, status_code=status, media_type=_SCIM_CONTENT)


def _require_scim_auth(request: Request) -> None:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bearer token required")
    token = auth_header[7:]
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    if not db.scim_verify_token(token_hash):
        raise HTTPException(status_code=401, detail="Invalid SCIM bearer token")


def _user_to_scim(username: str, request: Request) -> dict:
    user_list = users.list_users()
    user_data = next((u for u in user_list if u["username"] == username), None)
    if not user_data:
        return {}
    base_url = str(request.base_url).rstrip("/")
    result = {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
        "id": username,
        "userName": username,
        "active": not user_data.get("disabled", False),
        "roles": [{"value": user_data.get("role", "viewer")}],
        "meta": {
            "resourceType": "User",
            "location": f"{base_url}/api/scim/v2/Users/{username}",
        },
    }
    display_name = user_data.get("display_name", "")
    if display_name:
        result["displayName"] = display_name
    return result


def _map_scim_role(scim_body: dict) -> str:
    roles = scim_body.get("roles", [])
    if roles and isinstance(roles, list):
        val = roles[0].get("value", "viewer") if isinstance(roles[0], dict) else str(roles[0])
        if val in _VALID_ROLES:
            return val
    return "viewer"


# ── Discovery ─────────────────────────────────────────────────────────────────

@router.get("/api/scim/v2/ServiceProviderConfig")
@handle_errors
async def scim_service_provider_config(request: Request):
    _require_scim_auth(request)
    return JSONResponse(content={
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"],
        "patch": {"supported": True},
        "bulk": {"supported": False, "maxOperations": 0, "maxPayloadSize": 0},
        "filter": {"supported": True, "maxResults": 200},
        "changePassword": {"supported": True},
        "sort": {"supported": False},
        "etag": {"supported": False},
        "authenticationSchemes": [{"type": "oauthbearertoken", "name": "Bearer Token"}],
    }, media_type=_SCIM_CONTENT)


@router.get("/api/scim/v2/Schemas")
@handle_errors
async def scim_schemas(request: Request):
    _require_scim_auth(request)
    return JSONResponse(content={
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:ListResponse"],
        "totalResults": 1,
        "Resources": [{
            "id": "urn:ietf:params:scim:schemas:core:2.0:User",
            "name": "User",
            "attributes": [
                {"name": "userName", "type": "string", "required": True, "uniqueness": "server"},
                {"name": "displayName", "type": "string", "required": False},
                {"name": "active", "type": "boolean", "required": False},
                {"name": "roles", "type": "complex", "multiValued": True},
            ],
        }],
    }, media_type=_SCIM_CONTENT)


@router.get("/api/scim/v2/ResourceTypes")
@handle_errors
async def scim_resource_types(request: Request):
    _require_scim_auth(request)
    return JSONResponse(content={
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:ListResponse"],
        "totalResults": 1,
        "Resources": [{
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ResourceType"],
            "id": "User",
            "name": "User",
            "endpoint": "/api/scim/v2/Users",
            "schema": "urn:ietf:params:scim:schemas:core:2.0:User",
        }],
    }, media_type=_SCIM_CONTENT)


# ── Users CRUD ────────────────────────────────────────────────────────────────

@router.get("/api/scim/v2/Users")
@handle_errors
async def scim_list_users(request: Request):
    _require_scim_auth(request)
    start = _int_param(request, "startIndex", 1, 1, 10000)
    count = _int_param(request, "count", 100, 1, 200)
    all_users = users.list_users()
    page = all_users[start - 1:start - 1 + count]
    return JSONResponse(content={
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:ListResponse"],
        "totalResults": len(all_users),
        "startIndex": start,
        "itemsPerPage": len(page),
        "Resources": [_user_to_scim(u["username"], request) for u in page],
    }, media_type=_SCIM_CONTENT)


@router.get("/api/scim/v2/Users/{user_id}")
@handle_errors
async def scim_get_user(user_id: str, request: Request):
    _require_scim_auth(request)
    if not users.exists(user_id):
        return _scim_error(404, f"User {user_id} not found")
    return JSONResponse(content=_user_to_scim(user_id, request), media_type=_SCIM_CONTENT)


@router.post("/api/scim/v2/Users")
@handle_errors
async def scim_create_user(request: Request):
    _require_scim_auth(request)
    body = await _read_body(request)
    username = body.get("userName", "").strip()
    if not username or not valid_username(username):
        return _scim_error(400, "Invalid or missing userName", "invalidValue")
    if users.exists(username):
        return _scim_error(409, f"User {username} already exists", "uniqueness")
    role = _map_scim_role(body)
    display_name = body.get("displayName", "")
    initial_pw = pbkdf2_hash(secrets.token_urlsafe(32))
    users.add(username, initial_pw, role, display_name=display_name)
    db.scim_log_provision("create", body.get("id"), username, "ok")
    return JSONResponse(
        content=_user_to_scim(username, request),
        status_code=201,
        media_type=_SCIM_CONTENT,
    )


@router.put("/api/scim/v2/Users/{user_id}")
@handle_errors
async def scim_replace_user(user_id: str, request: Request):
    _require_scim_auth(request)
    if not users.exists(user_id):
        return _scim_error(404, f"User {user_id} not found")
    body = await _read_body(request)
    role = _map_scim_role(body)
    users.update_role(user_id, role)
    db.scim_log_provision("update", body.get("id"), user_id, "ok")
    return JSONResponse(content=_user_to_scim(user_id, request), media_type=_SCIM_CONTENT)


@router.patch("/api/scim/v2/Users/{user_id}")
@handle_errors
async def scim_patch_user(user_id: str, request: Request):
    _require_scim_auth(request)
    if not users.exists(user_id):
        return _scim_error(404, f"User {user_id} not found")
    body = await _read_body(request)
    for op in body.get("Operations", []):
        op_type = op.get("op", "").lower()
        path = op.get("path", "")
        value = op.get("value")
        if op_type == "replace" and path == "active":
            disabled = not bool(value) if isinstance(value, bool) else str(value).lower() != "true"
            users.set_disabled(user_id, disabled)
        elif op_type == "replace" and path == "displayName":
            users.update_display_name(user_id, str(value) if value else "")
        elif op_type == "replace" and path == "roles":
            if isinstance(value, list):
                new_role = _map_scim_role({"roles": value})
                users.update_role(user_id, new_role)
    db.scim_log_provision("patch", None, user_id, "ok")
    return JSONResponse(content=_user_to_scim(user_id, request), media_type=_SCIM_CONTENT)


@router.delete("/api/scim/v2/Users/{user_id}")
@handle_errors
async def scim_delete_user(user_id: str, request: Request):
    _require_scim_auth(request)
    if not users.exists(user_id):
        return _scim_error(404, f"User {user_id} not found")
    users.remove(user_id)
    db.scim_log_provision("delete", None, user_id, "ok")
    return Response(status_code=204)
