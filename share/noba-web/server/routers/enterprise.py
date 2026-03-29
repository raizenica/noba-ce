"""Noba – Enterprise administration endpoints (SAML, SCIM, WebAuthn, Database, Audit, Compliance)."""
from __future__ import annotations

import csv
import io
import json
import logging
import time

import httpx

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..config import DATABASE_URL, HISTORY_DB, NOBA_PG_POOL_MIN, NOBA_PG_POOL_MAX
from ..deps import _get_auth, _client_ip, _require_enterprise, _require_feature, get_tenant_id, db, handle_errors
from ..db.rbac import VALID_RESOURCE_TYPES
from ..yaml_config import read_yaml_settings, write_yaml_settings

logger = logging.getLogger("noba")
router = APIRouter()


# ── SAML ─────────────────────────────────────────────────────────────────────

class SamlConfig(BaseModel):
    samlEnabled: bool = False
    samlIdpSsoUrl: str = ""
    samlIdpCert: str = ""
    samlEntityId: str = ""
    samlAcsUrl: str = ""
    samlDefaultRole: str = "viewer"
    samlGroupMapping: str = "{}"


@router.get("/api/enterprise/saml")
@handle_errors
async def get_saml_config(
    _auth: tuple = Depends(_require_feature("saml")),
):
    cfg = read_yaml_settings()
    return {
        "samlEnabled":      cfg.get("samlEnabled", False),
        "samlIdpSsoUrl":    cfg.get("samlIdpSsoUrl", ""),
        "samlIdpCert":      cfg.get("samlIdpCert", ""),
        "samlEntityId":     cfg.get("samlEntityId", ""),
        "samlAcsUrl":       cfg.get("samlAcsUrl", ""),
        "samlDefaultRole":  cfg.get("samlDefaultRole", "viewer"),
        "samlGroupMapping": cfg.get("samlGroupMapping", "{}"),
    }


@router.put("/api/enterprise/saml")
@handle_errors
async def put_saml_config(
    request: Request,
    body: SamlConfig,
    auth: tuple = Depends(_require_feature("saml")),
):
    import json as _json
    from ..auth import users, verify_password
    # Changing SSO config is a sensitive operation — require password re-confirmation
    confirm_pw = request.headers.get("X-Confirm-Password", "")
    if not confirm_pw:
        raise HTTPException(status_code=403, detail="Password confirmation required for SSO configuration changes")
    username = auth[0]
    user_data = users.get(username)
    if not user_data or not verify_password(user_data[0], confirm_pw, username=username):
        raise HTTPException(status_code=403, detail="Password confirmation failed")
    if body.samlDefaultRole not in ("viewer", "operator", "admin"):
        raise HTTPException(status_code=422, detail="samlDefaultRole must be viewer/operator/admin")
    try:
        _json.loads(body.samlGroupMapping)
    except ValueError:
        raise HTTPException(status_code=422, detail="samlGroupMapping must be valid JSON")
    db.audit_log("saml_config_change", username, "SAML SSO configuration updated", _client_ip(request))
    write_yaml_settings(body.model_dump())
    return {"ok": True}


@router.post("/api/enterprise/saml/test")
@handle_errors
async def test_saml_connection(
    _auth: tuple = Depends(_require_feature("saml")),
):
    cfg = read_yaml_settings()
    url = cfg.get("samlIdpSsoUrl", "")
    if not url:
        raise HTTPException(status_code=422, detail="samlIdpSsoUrl not configured")
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            r = await client.head(url)
        latency_ms = int((time.monotonic() - t0) * 1000)
        return {"ok": r.status_code < 500, "status": r.status_code, "latency_ms": latency_ms}
    except Exception as exc:
        latency_ms = int((time.monotonic() - t0) * 1000)
        return {"ok": False, "status": 0, "latency_ms": latency_ms, "error": str(exc)}


# ── SCIM ─────────────────────────────────────────────────────────────────────

@router.get("/api/enterprise/scim/status")
@handle_errors
async def get_scim_status(
    _auth: tuple = Depends(_require_enterprise),
):
    status = db.scim_get_active_token_status()
    last_activity = None
    if status["active"]:
        log = db.scim_get_provision_log(limit=1)
        if log:
            last_activity = log[0]["timestamp"]
    return {
        "active":        status["active"],
        "expires_at":    status["expires_at"],
        "last_used_at":  status["last_used_at"],
        "last_activity": last_activity,
    }


# ── WebAuthn ─────────────────────────────────────────────────────────────────

@router.get("/api/enterprise/webauthn/credentials")
@handle_errors
async def get_all_webauthn_credentials(
    _auth: tuple = Depends(_require_feature("webauthn")),
):
    return db.webauthn_get_all_credentials()


@router.delete("/api/enterprise/webauthn/credentials/{cred_uuid}")
@handle_errors
async def revoke_webauthn_credential(
    cred_uuid: str,
    _auth: tuple = Depends(_require_feature("webauthn")),
):
    db.webauthn_delete_credential_by_uuid(cred_uuid)
    return {"ok": True}


# ── Database ─────────────────────────────────────────────────────────────────

@router.get("/api/enterprise/db/status")
@handle_errors
async def get_db_status(
    _auth: tuple = Depends(_require_enterprise),
):
    if DATABASE_URL.startswith("postgres"):
        try:
            conn = db._get_conn()
            ver = conn.execute("SELECT version()").fetchone()[0]
            server_version = ver.split()[1] if ver else "unknown"
            url_parts = DATABASE_URL.split("@")[-1] if "@" in DATABASE_URL else DATABASE_URL
            host_db = url_parts.split("/")
            host = host_db[0].split(":")[0] if host_db else "unknown"
            database = host_db[1] if len(host_db) > 1 else "unknown"
            return {
                "backend": "postgresql",
                "connected": True,
                "server_version": server_version,
                "host": host,
                "database": database,
                "pool_min": NOBA_PG_POOL_MIN,
                "pool_max": NOBA_PG_POOL_MAX,
            }
        except Exception as exc:
            return {"backend": "postgresql", "connected": False, "error": str(exc)}
    else:
        wal_mode = False
        try:
            r = db._read_conn.execute("PRAGMA journal_mode").fetchone()
            wal_mode = r[0].lower() == "wal" if r else False
        except Exception:
            pass
        return {
            "backend": "sqlite",
            "path": HISTORY_DB,
            "wal_mode": wal_mode,
        }


# ── Tenant Quotas ────────────────────────────────────────────────────────────

class TenantLimitsBody(BaseModel):
    max_api_keys: int = 0
    max_automations: int = 0
    max_webhooks: int = 0


class FreezeWindowBody(BaseModel):
    name: str
    start_ts: int
    end_ts: int
    reason: str = ""


class VaultSecretBody(BaseModel):
    name: str
    value: str


class AclBody(BaseModel):
    username: str
    resource_type: str
    can_read: bool = True
    can_write: bool = True


class PasswordPolicyBody(BaseModel):
    min_length: int = 8
    require_uppercase: bool = True
    require_digit: bool = True
    require_special: bool = False
    max_age_days: int = 0
    history_count: int = 0


class RetentionBody(BaseModel):
    metrics_days: int = 30
    audit_days: int = 90
    alerts_days: int = 30
    job_runs_days: int = 30



@router.get("/api/enterprise/tenants/{tenant_id}/limits")
@handle_errors
async def get_tenant_limits(
    tenant_id: str,
    _auth: tuple = Depends(_require_enterprise),
):
    limits = db.get_tenant_limits(tenant_id)
    counts = db.count_tenant_resources(tenant_id)
    return {"limits": limits, "counts": counts}


@router.put("/api/enterprise/tenants/{tenant_id}/limits")
@handle_errors
async def put_tenant_limits(
    tenant_id: str,
    body: TenantLimitsBody,
    _auth: tuple = Depends(_require_enterprise),
):
    if not db.tenant_exists(tenant_id):
        raise HTTPException(status_code=404, detail="Tenant not found")
    db.set_tenant_limits(tenant_id, body.model_dump())
    return {"ok": True}


# ── Audit Log ─────────────────────────────────────────────────────────────────

@router.get("/api/enterprise/audit/actions")
@handle_errors
async def get_audit_actions(
    _auth: tuple = Depends(_require_enterprise),
    tenant_id: str = Depends(get_tenant_id),
):
    """Return distinct action values for filter dropdown."""
    return db.get_audit_actions(tenant_id=tenant_id)


@router.get("/api/enterprise/audit")
@handle_errors
async def get_audit_log(
    _auth: tuple = Depends(_require_enterprise),
    tenant_id: str = Depends(get_tenant_id),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    username: str = Query(default=""),
    action: str = Query(default=""),
    from_ts: int = Query(default=0),
    to_ts: int = Query(default=0),
):
    rows = db.get_audit(
        limit=limit, offset=offset,
        username_filter=username, action_filter=action,
        from_ts=from_ts, to_ts=to_ts,
        tenant_id=tenant_id,
    )
    total = db.count_audit(
        username_filter=username, action_filter=action,
        from_ts=from_ts, to_ts=to_ts,
        tenant_id=tenant_id,
    )
    return {"rows": rows, "total": total, "limit": limit, "offset": offset}


@router.get("/api/enterprise/audit/export")
async def export_audit_log(
    request: Request,
    _auth: tuple = Depends(_require_enterprise),
    tenant_id: str = Depends(get_tenant_id),
    fmt: str = Query(default="csv", alias="format"),
    username: str = Query(default=""),
    action: str = Query(default=""),
    from_ts: int = Query(default=0),
    to_ts: int = Query(default=0),
):
    """Stream full audit log as CSV or JSON attachment. Not wrapped in @handle_errors
    because it returns StreamingResponse — wrapping would corrupt the stream."""
    rows = db.get_audit(
        limit=10000, offset=0,
        username_filter=username, action_filter=action,
        from_ts=from_ts, to_ts=to_ts,
        tenant_id=tenant_id,
    )

    if fmt == "json":
        content = json.dumps(rows, indent=2).encode()
        return StreamingResponse(
            iter([content]),
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=audit-log.json"},
        )

    # CSV
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["time", "username", "action", "details", "ip"])
    writer.writeheader()
    writer.writerows(rows)
    content_bytes = buf.getvalue().encode()
    return StreamingResponse(
        iter([content_bytes]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit-log.csv"},
    )


# ── Compliance Report ─────────────────────────────────────────────────────────

@router.get("/api/enterprise/compliance/report")
@handle_errors
async def get_compliance_report(
    _auth: tuple = Depends(_require_enterprise),
    tenant_id: str = Depends(get_tenant_id),
):
    """Aggregate compliance data: security posture, incidents, drift, audit, resource inventory."""
    now = int(time.time())
    week_ago = now - 7 * 86400

    # Security scores (latest per host)
    security_scores = db.get_security_scores()
    if security_scores:
        avg_score = round(sum(s["score"] for s in security_scores) / len(security_scores), 1)
    else:
        avg_score = None

    # Open incidents (not resolved) — use 8760h = 1 year to get all history
    all_incidents = db.get_incidents(limit=500, hours=8760)
    open_incidents = [i for i in all_incidents if not i.get("resolved_at")]

    # Drift checks (drifted in last 7 days)
    drift_results = db.get_drift_results()
    drifted = [d for d in drift_results if d.get("status") == "drifted"]

    # Audit activity summary (last 7 days, tenant-scoped)
    audit_rows = db.get_audit(
        limit=10000, from_ts=week_ago, tenant_id=tenant_id
    )
    action_counts: dict[str, int] = {}
    for row in audit_rows:
        action_counts[row["action"]] = action_counts.get(row["action"], 0) + 1
    top_actions = sorted(action_counts.items(), key=lambda x: -x[1])[:8]

    # Resource inventory (tenant-scoped)
    counts = db.count_tenant_resources(tenant_id)
    limits = db.get_tenant_limits(tenant_id)

    # User count from tenant members
    member_count = db.count_tenant_members(tenant_id)

    return {
        "generated_at": now,
        "tenant_id": tenant_id,
        "security": {
            "avg_score": avg_score,
            "host_count": len(security_scores),
            "hosts": [
                {
                    "hostname": s["hostname"],
                    "score": s["score"],
                    "scanned_at": s["scanned_at"],
                }
                for s in security_scores
            ],
        },
        "incidents": {
            "open": len(open_incidents),
            "total_7d": len([i for i in all_incidents if i.get("timestamp", 0) >= week_ago]),
            "by_severity": _count_by(open_incidents, "severity"),
        },
        "drift": {
            "drifted_count": len(drifted),
            "total_baselines": len(drift_results),
        },
        "audit": {
            "event_count_7d": len(audit_rows),
            "top_actions": [{"action": a, "count": c} for a, c in top_actions],
        },
        "resources": {
            "members": member_count,
            "api_keys": counts["api_keys"],
            "automations": counts["automations"],
            "webhooks": counts["webhooks"],
            "quotas": limits,
        },
    }




# ── RBAC ACLs ────────────────────────────────────────────────────────────────

@router.get("/api/enterprise/rbac/acls")
@handle_errors
async def list_rbac_acls(
    _auth: tuple = Depends(_require_enterprise),
    tenant_id: str = Depends(get_tenant_id),
    username: str = Query(default=""),
):
    return db.list_acls(tenant_id, username=username or None)


@router.put("/api/enterprise/rbac/acls")
@handle_errors
async def upsert_rbac_acl(
    body: AclBody,
    _auth: tuple = Depends(_require_enterprise),
    tenant_id: str = Depends(get_tenant_id),
):
    if body.resource_type not in VALID_RESOURCE_TYPES:
        raise HTTPException(status_code=422,
                            detail=f"Invalid resource_type. Valid: {sorted(VALID_RESOURCE_TYPES)}")
    db.set_acl(tenant_id, body.username, body.resource_type, body.can_read, body.can_write)
    return {"ok": True}


@router.delete("/api/enterprise/rbac/acls")
@handle_errors
async def delete_rbac_acl(
    username: str = Query(),
    resource_type: str = Query(),
    _auth: tuple = Depends(_require_enterprise),
    tenant_id: str = Depends(get_tenant_id),
):
    if resource_type not in VALID_RESOURCE_TYPES:
        raise HTTPException(status_code=422,
                            detail=f"Invalid resource_type. Valid: {sorted(VALID_RESOURCE_TYPES)}")
    db.delete_acl(tenant_id, username, resource_type)
    return {"ok": True}


# ── Change Freeze Windows ─────────────────────────────────────────────────────

@router.get("/api/enterprise/freeze-windows")
@handle_errors
async def list_freeze_windows(
    _auth: tuple = Depends(_require_enterprise),
    tenant_id: str = Depends(get_tenant_id),
):
    return db.list_freeze_windows(tenant_id)


@router.post("/api/enterprise/freeze-windows")
@handle_errors
async def create_freeze_window(
    body: FreezeWindowBody,
    auth: tuple = Depends(_require_enterprise),
    tenant_id: str = Depends(get_tenant_id),
):
    if body.end_ts <= body.start_ts:
        raise HTTPException(status_code=422, detail="end_ts must be after start_ts")
    username, _ = auth
    window_id = db.add_freeze_window(
        tenant_id, body.name, body.start_ts, body.end_ts, username, body.reason
    )
    return {"ok": True, "id": window_id}


@router.get("/api/enterprise/freeze-windows/status")
@handle_errors
async def freeze_window_status(
    _auth: tuple = Depends(_get_auth),
    tenant_id: str = Depends(get_tenant_id),
):
    """Lightweight status check — used by UI to show freeze banner."""
    return {"frozen": db.is_frozen(tenant_id)}


@router.delete("/api/enterprise/freeze-windows/{window_id}")
@handle_errors
async def delete_freeze_window(
    window_id: str,
    _auth: tuple = Depends(_require_enterprise),
):
    db.delete_freeze_window(window_id)
    return {"ok": True}


# ── Secrets Vault ─────────────────────────────────────────────────────────────

@router.get("/api/enterprise/vault/secrets")
@handle_errors
async def list_vault_secrets(
    _auth: tuple = Depends(_require_enterprise),
    tenant_id: str = Depends(get_tenant_id),
):
    """Return secret names only — values are never sent to the client."""
    return db.vault_list(tenant_id)


@router.post("/api/enterprise/vault/secrets")
@handle_errors
async def create_vault_secret(
    body: VaultSecretBody,
    _auth: tuple = Depends(_require_enterprise),
    tenant_id: str = Depends(get_tenant_id),
):
    if not body.name or not body.name.replace("-", "").replace("_", "").isalnum():
        raise HTTPException(status_code=422,
                            detail="Secret name must be alphanumeric with dashes/underscores only")
    db.vault_store(tenant_id, body.name, body.value)
    return {"ok": True}


@router.delete("/api/enterprise/vault/secrets/{name}")
@handle_errors
async def delete_vault_secret(
    name: str,
    _auth: tuple = Depends(_require_enterprise),
    tenant_id: str = Depends(get_tenant_id),
):
    db.vault_delete(tenant_id, name)
    return {"ok": True}


# ── Password Policies ────────────────────────────────────────────────────────

@router.get("/api/enterprise/password-policy")
@handle_errors
async def get_password_policy(
    _auth: tuple = Depends(_require_enterprise),
    tenant_id: str = Depends(get_tenant_id),
):
    return db.password_policy_get(tenant_id)


@router.put("/api/enterprise/password-policy")
@handle_errors
async def set_password_policy(
    body: PasswordPolicyBody,
    _auth: tuple = Depends(_require_enterprise),
    tenant_id: str = Depends(get_tenant_id),
):
    if body.min_length < 6 or body.min_length > 128:
        raise HTTPException(status_code=422, detail="min_length must be between 6 and 128")
    if body.max_age_days < 0:
        raise HTTPException(status_code=422, detail="max_age_days must be >= 0")
    if body.history_count < 0 or body.history_count > 50:
        raise HTTPException(status_code=422, detail="history_count must be between 0 and 50")
    db.password_policy_set(
        tenant_id,
        min_length=body.min_length,
        require_uppercase=body.require_uppercase,
        require_digit=body.require_digit,
        require_special=body.require_special,
        max_age_days=body.max_age_days,
        history_count=body.history_count,
    )
    return {"ok": True}


# ── Login IP Allowlist ───────────────────────────────────────────────────────

@router.get("/api/enterprise/login-ip-rules")
@handle_errors
async def list_login_ip_rules(
    _auth: tuple = Depends(_require_enterprise),
    tenant_id: str = Depends(get_tenant_id),
):
    return db.list_login_cidrs(tenant_id)


@router.post("/api/enterprise/login-ip-rules")
@handle_errors
async def add_login_ip_rule(
    request: Request,
    _auth: tuple = Depends(_require_enterprise),
    tenant_id: str = Depends(get_tenant_id),
):
    body = json.loads(await request.body())
    cidr = body.get("cidr", "").strip()
    label = body.get("label", "").strip()
    if not cidr:
        raise HTTPException(status_code=422, detail="cidr is required")
    try:
        import ipaddress
        ipaddress.ip_network(cidr, strict=False)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid CIDR: {cidr}")
    rule_id = db.add_login_cidr(tenant_id, cidr, label)
    return {"ok": True, "id": rule_id}


@router.delete("/api/enterprise/login-ip-rules/{rule_id}")
@handle_errors
async def delete_login_ip_rule(
    rule_id: int,
    _auth: tuple = Depends(_require_enterprise),
):
    db.delete_login_cidr(rule_id)
    return {"ok": True}


# ── Data Retention Policies ──────────────────────────────────────────────────

@router.get("/api/enterprise/retention")
@handle_errors
async def get_retention_policy(
    _auth: tuple = Depends(_require_enterprise),
    tenant_id: str = Depends(get_tenant_id),
):
    return db.retention_get(tenant_id)


@router.put("/api/enterprise/retention")
@handle_errors
async def set_retention_policy(
    body: RetentionBody,
    _auth: tuple = Depends(_require_enterprise),
    tenant_id: str = Depends(get_tenant_id),
):
    for field in ["metrics_days", "audit_days", "alerts_days", "job_runs_days"]:
        val = getattr(body, field)
        if val < 1 or val > 3650:
            raise HTTPException(status_code=422, detail=f"{field} must be between 1 and 3650")
    db.retention_set(
        tenant_id,
        metrics_days=body.metrics_days,
        audit_days=body.audit_days,
        alerts_days=body.alerts_days,
        job_runs_days=body.job_runs_days,
    )
    return {"ok": True}


# ── Webhook Signing ──────────────────────────────────────────────────────────

@router.get("/api/enterprise/webhook-signing")
@handle_errors
async def get_webhook_signing_status(
    _auth: tuple = Depends(_require_enterprise),
    tenant_id: str = Depends(get_tenant_id),
):
    """Check if a webhook signing secret is configured (never returns the secret)."""
    has_secret = db.vault_get_plaintext(tenant_id, "webhook-signing-secret") is not None
    return {"configured": has_secret}


@router.put("/api/enterprise/webhook-signing")
@handle_errors
async def set_webhook_signing_secret(
    request: Request,
    _auth: tuple = Depends(_require_enterprise),
    tenant_id: str = Depends(get_tenant_id),
):
    """Store the webhook signing secret in the vault."""
    body = json.loads(await request.body())
    secret = body.get("secret", "").strip()
    if not secret or len(secret) < 16:
        raise HTTPException(status_code=422, detail="Secret must be at least 16 characters")
    db.vault_store(tenant_id, "webhook-signing-secret", secret)
    return {"ok": True}


@router.delete("/api/enterprise/webhook-signing")
@handle_errors
async def delete_webhook_signing_secret(
    _auth: tuple = Depends(_require_enterprise),
    tenant_id: str = Depends(get_tenant_id),
):
    db.vault_delete(tenant_id, "webhook-signing-secret")
    return {"ok": True}


def _count_by(rows: list[dict], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in rows:
        v = r.get(key, "unknown") or "unknown"
        out[v] = out.get(v, 0) + 1
    return out
