"""Noba -- Healing pipeline API endpoints."""
from __future__ import annotations

import json
import logging
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException, Request

from ..agent_store import _agent_cmd_lock, _agent_commands, _agent_data, _agent_data_lock
from ..deps import _get_auth, _require_admin, _require_operator, db

logger = logging.getLogger("noba")

router = APIRouter()


@router.get("/api/healing/ledger")
def api_healing_ledger(request: Request, auth=Depends(_get_auth)):
    limit = int(request.query_params.get("limit", 50))
    rule_id = request.query_params.get("rule_id")
    target = request.query_params.get("target")
    return db.get_heal_outcomes(limit=limit, rule_id=rule_id, target=target)


@router.get("/api/healing/effectiveness")
def api_healing_effectiveness(request: Request, auth=Depends(_get_auth)):
    action_type = request.query_params.get("action_type", "")
    condition = request.query_params.get("condition", "")
    target = request.query_params.get("target")
    if not action_type or not condition:
        raise HTTPException(400, "action_type and condition required")
    rate = db.get_heal_success_rate(action_type, condition, target=target)
    return {"action_type": action_type, "condition": condition, "success_rate": rate}


@router.get("/api/healing/suggestions")
def api_healing_suggestions(auth=Depends(_get_auth)):
    return db.list_heal_suggestions()


@router.post("/api/healing/suggestions/{suggestion_id}/dismiss")
def api_dismiss_suggestion(suggestion_id: int, auth=Depends(_require_operator)):
    db.dismiss_heal_suggestion(suggestion_id)
    return {"success": True}


@router.get("/api/healing/trust")
def api_healing_trust(auth=Depends(_get_auth)):
    return db.list_trust_states()


@router.post("/api/healing/trust/{rule_id}/promote")
async def api_promote_trust(rule_id: str, request: Request, auth=Depends(_require_admin)):
    from ..deps import _read_body
    body = await _read_body(request)
    target_level = body.get("level", "approve")
    if target_level not in ("approve", "execute"):
        raise HTTPException(400, "level must be 'approve' or 'execute'")
    state = db.get_trust_state(rule_id)
    if not state:
        raise HTTPException(404, f"No trust state for rule: {rule_id}")
    db.upsert_trust_state(rule_id, target_level, state["ceiling"])
    username, _ = auth
    db.audit_log("trust_promote", username, f"{rule_id}: {state['current_level']} -> {target_level}")
    return {"success": True, "rule_id": rule_id, "new_level": target_level}


@router.get("/api/healing/capabilities/{hostname}")
def api_get_capabilities(hostname: str, auth=Depends(_get_auth)):
    """Return the capability manifest for a given agent hostname."""
    row = db.get_capability_manifest(hostname)
    if row is None:
        raise HTTPException(404, f"No manifest for {hostname}")
    # Parse the manifest JSON string into a dict
    try:
        manifest_data = json.loads(row["manifest"])
    except (json.JSONDecodeError, KeyError):
        manifest_data = {}
    return {
        "hostname": row["hostname"],
        "manifest": manifest_data,
        "probed_at": row.get("probed_at"),
        "degraded_capabilities": json.loads(row.get("degraded_capabilities") or "[]"),
    }


@router.post("/api/healing/capabilities/{hostname}/refresh")
def api_refresh_capabilities(hostname: str, auth=Depends(_require_operator)):
    """Queue a refresh_capabilities command to the named agent."""
    with _agent_data_lock:
        known = hostname in _agent_data
    if not known:
        raise HTTPException(404, f"No known agent: {hostname}")
    cmd_id = secrets.token_hex(8)
    username, _ = auth
    cmd = {
        "id": cmd_id,
        "type": "refresh_capabilities",
        "params": {},
        "queued_by": username,
        "queued_at": int(time.time()),
    }
    with _agent_cmd_lock:
        _agent_commands.setdefault(hostname, []).append(cmd)
    return {"status": "refresh_queued", "hostname": hostname}
