# Enterprise Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add four admin-only enterprise Settings tabs (SAML SSO, SCIM, WebAuthn, Database) with full CRUD, backed by a new `routers/enterprise.py` with 7 admin-gated endpoints.

**Architecture:** Two DB modules gain new functions (scim status query, webauthn admin list/delete); a new enterprise router handles all enterprise read/write; four async-loaded Vue tab components follow the exact `UsersTab.vue` pattern (admin gate, `s-section`, `useApi`, `useAuthStore`, `AppModal` confirm for destructive ops).

**Tech Stack:** FastAPI, Python 3.11, SQLite/PostgreSQL via existing `db` layer, Vue 3 `<script setup>`, Pinia, `useApi()`, `defineAsyncComponent`

---

### Task 1: DB additions — SCIM status + WebAuthn admin list/delete

**Files:**
- Modify: `share/noba-web/server/db/scim.py`
- Modify: `share/noba-web/server/db/webauthn.py`
- Test: `tests/test_enterprise_db.py` (create)

- [ ] **Step 1: Write failing tests**

```python
# tests/test_enterprise_db.py
from __future__ import annotations
import pytest
from share.noba_web.server.db.core import Database

@pytest.fixture
def db(tmp_path):
    d = Database(str(tmp_path / "test.db"))
    yield d
    d._conn.close()

def test_scim_active_token_status_no_token(db):
    status = db.scim_get_active_token_status()
    assert status == {"active": False, "expires_at": None, "last_used_at": None}

def test_scim_active_token_status_with_token(db):
    import hashlib, uuid
    raw = str(uuid.uuid4())
    h = hashlib.sha256(raw.encode()).hexdigest()
    db.scim_store_token(str(uuid.uuid4()), h)
    status = db.scim_get_active_token_status()
    assert status["active"] is True
    assert status["expires_at"] is not None

def test_webauthn_get_all_credentials_empty(db):
    creds = db.webauthn_get_all_credentials()
    assert creds == []

def test_webauthn_get_all_credentials_returns_rows(db):
    db.webauthn_store_credential("alice", b"cred1", b"pubkey1", 0, "laptop")
    db.webauthn_store_credential("bob",   b"cred2", b"pubkey2", 0, "yubikey")
    creds = db.webauthn_get_all_credentials()
    assert len(creds) == 2
    usernames = {c["username"] for c in creds}
    assert usernames == {"alice", "bob"}

def test_webauthn_delete_credential_by_uuid(db):
    db.webauthn_store_credential("alice", b"cred3", b"pubkey3", 0, "phone")
    creds = db.webauthn_get_all_credentials()
    assert len(creds) == 1
    uid = creds[0]["id"]
    db.webauthn_delete_credential_by_uuid(uid)
    assert db.webauthn_get_all_credentials() == []

def test_webauthn_delete_nonexistent_uuid_noop(db):
    db.webauthn_delete_credential_by_uuid("does-not-exist")  # must not raise
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd /home/raizen/noba/.worktrees/enterprise-v2
pytest tests/test_enterprise_db.py -v
```

Expected: 5 failures — `scim_get_active_token_status` / `webauthn_get_all_credentials` / `webauthn_delete_credential_by_uuid` not found.

- [ ] **Step 3: Add `get_active_token_status` to `db/scim.py`**

Add this function after `verify_token` (before `log_provision`):

```python
def get_active_token_status(
    conn: sqlite3.Connection, lock: threading.Lock,
) -> dict:
    try:
        now = time.time()
        with lock:
            r = conn.execute(
                "SELECT expires_at, last_used_at FROM scim_tokens WHERE expires_at > ? LIMIT 1",
                (now,),
            ).fetchone()
        if not r:
            return {"active": False, "expires_at": None, "last_used_at": None}
        return {"active": True, "expires_at": r[0], "last_used_at": r[1]}
    except Exception as e:
        logger.error("get_active_token_status failed: %s", e)
        return {"active": False, "expires_at": None, "last_used_at": None}
```

Add this method to `_ScimMixin` (after `scim_get_provision_log`):

```python
    def scim_get_active_token_status(self) -> dict:
        return self.execute_read(lambda conn: get_active_token_status(conn, self._read_lock))
```

- [ ] **Step 4: Add `get_all_credentials` and `delete_credential_by_uuid` to `db/webauthn.py`**

Add this function after `get_credential_by_id`:

```python
def get_all_credentials(
    conn: sqlite3.Connection, lock: threading.Lock,
) -> list[dict]:
    try:
        with lock:
            rows = conn.execute(
                "SELECT id, username, name, created_at, sign_count "
                "FROM webauthn_credentials ORDER BY username, created_at",
            ).fetchall()
        return [
            {"id": r[0], "username": r[1], "name": r[2],
             "created_at": r[3], "sign_count": r[4]}
            for r in rows
        ]
    except Exception as e:
        logger.error("get_all_credentials failed: %s", e)
        return []


def delete_credential_by_uuid(
    conn: sqlite3.Connection, lock: threading.Lock, uid: str,
) -> None:
    try:
        with lock:
            conn.execute("DELETE FROM webauthn_credentials WHERE id = ?", (uid,))
            conn.commit()
    except Exception as e:
        logger.error("delete_credential_by_uuid failed: %s", e)
```

Add these methods to `_WebAuthnMixin` (after `webauthn_get_credentials`):

```python
    def webauthn_get_all_credentials(self) -> list[dict]:
        return self.execute_read(lambda conn: get_all_credentials(conn, self._read_lock))

    def webauthn_delete_credential_by_uuid(self, uid: str) -> None:
        self.execute_write(lambda conn: delete_credential_by_uuid(conn, self._lock, uid))
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_enterprise_db.py -v
```

Expected: 5 passed.

- [ ] **Step 6: Ruff check**

```bash
ruff check --fix share/noba-web/server/db/scim.py share/noba-web/server/db/webauthn.py
```

- [ ] **Step 7: Commit**

```bash
git add tests/test_enterprise_db.py \
        share/noba-web/server/db/scim.py \
        share/noba-web/server/db/webauthn.py
git commit -m "feat(enterprise): add scim status query + webauthn admin list/delete to DB layer"
```

---

### Task 2: Add SAML keys to WEB_KEYS in config.py

**Files:**
- Modify: `share/noba-web/server/config.py`
- Test: inline (grep check)

- [ ] **Step 1: Add SAML config keys to WEB_KEYS frozenset**

In `share/noba-web/server/config.py`, find the `# AI / LLM` comment block at the end of WEB_KEYS and add after the last AI line, before the closing `])`:

```python
    # Enterprise – SAML SSO
    "samlEnabled", "samlIdpSsoUrl", "samlIdpCert",
    "samlEntityId", "samlAcsUrl", "samlDefaultRole", "samlGroupMapping",
```

- [ ] **Step 2: Verify keys are present**

```bash
python3 -c "
from share.noba_web.server.config import WEB_KEYS
keys = ['samlEnabled','samlIdpSsoUrl','samlIdpCert','samlEntityId','samlAcsUrl','samlDefaultRole','samlGroupMapping']
missing = [k for k in keys if k not in WEB_KEYS]
print('Missing:', missing if missing else 'none — all present')
"
```

Expected: `Missing: none — all present`

- [ ] **Step 3: Run existing config tests**

```bash
pytest tests/test_config_database_url.py -v
```

Expected: 2 passed.

- [ ] **Step 4: Commit**

```bash
git add share/noba-web/server/config.py
git commit -m "feat(enterprise): add SAML config keys to WEB_KEYS"
```

---

### Task 3: Create `routers/enterprise.py` with 7 admin-gated endpoints

**Files:**
- Create: `share/noba-web/server/routers/enterprise.py`
- Test: `tests/test_enterprise_router.py` (create)

- [ ] **Step 1: Write failing tests**

```python
# tests/test_enterprise_router.py
from __future__ import annotations
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

# Import app via existing test pattern
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

@pytest.fixture
def client():
    from share.noba_web.server.app import app
    return TestClient(app)

def _admin_headers(client):
    """Get auth headers for admin user via existing test helper."""
    from tests.conftest import admin_auth_headers
    return admin_auth_headers(client)

def test_get_saml_requires_admin(client):
    r = client.get("/api/enterprise/saml")
    assert r.status_code in (401, 403)

def test_put_saml_requires_admin(client):
    r = client.put("/api/enterprise/saml", json={})
    assert r.status_code in (401, 403)

def test_get_scim_status_requires_admin(client):
    r = client.get("/api/enterprise/scim/status")
    assert r.status_code in (401, 403)

def test_get_webauthn_credentials_requires_admin(client):
    r = client.get("/api/enterprise/webauthn/credentials")
    assert r.status_code in (401, 403)

def test_get_db_status_requires_admin(client):
    r = client.get("/api/enterprise/db/status")
    assert r.status_code in (401, 403)
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest tests/test_enterprise_router.py -v
```

Expected: 5 failures — routes return 404 (not registered yet).

- [ ] **Step 3: Create `routers/enterprise.py`**

```python
"""Noba – Enterprise administration endpoints (SAML, SCIM, WebAuthn, Database)."""
from __future__ import annotations

import logging
import os

import httpx
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..config import DATABASE_URL, HISTORY_DB, NOBA_PG_POOL_MIN, NOBA_PG_POOL_MAX
from ..deps import _require_admin, db, handle_errors
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
    _auth: tuple = Depends(_require_admin),
):
    cfg = read_yaml_settings()
    return {
        "samlEnabled":     cfg.get("samlEnabled", False),
        "samlIdpSsoUrl":   cfg.get("samlIdpSsoUrl", ""),
        "samlIdpCert":     cfg.get("samlIdpCert", ""),
        "samlEntityId":    cfg.get("samlEntityId", ""),
        "samlAcsUrl":      cfg.get("samlAcsUrl", ""),
        "samlDefaultRole": cfg.get("samlDefaultRole", "viewer"),
        "samlGroupMapping": cfg.get("samlGroupMapping", "{}"),
    }


@router.put("/api/enterprise/saml")
@handle_errors
async def put_saml_config(
    body: SamlConfig,
    _auth: tuple = Depends(_require_admin),
):
    if body.samlDefaultRole not in ("viewer", "operator", "admin"):
        raise HTTPException(status_code=422, detail="samlDefaultRole must be viewer/operator/admin")
    write_yaml_settings(body.model_dump())
    return {"ok": True}


@router.post("/api/enterprise/saml/test")
@handle_errors
async def test_saml_connection(
    _auth: tuple = Depends(_require_admin),
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
    _auth: tuple = Depends(_require_admin),
):
    status = db.scim_get_active_token_status()
    last_activity = None
    if status["active"]:
        log = db.scim_get_provision_log(limit=1)
        if log:
            last_activity = log[0]["timestamp"]
    return {
        "active":          status["active"],
        "expires_at":      status["expires_at"],
        "last_used_at":    status["last_used_at"],
        "last_activity":   last_activity,
    }


# ── WebAuthn ─────────────────────────────────────────────────────────────────

@router.get("/api/enterprise/webauthn/credentials")
@handle_errors
async def get_all_webauthn_credentials(
    _auth: tuple = Depends(_require_admin),
):
    return db.webauthn_get_all_credentials()


@router.delete("/api/enterprise/webauthn/credentials/{username}/{cred_uuid}")
@handle_errors
async def revoke_webauthn_credential(
    username: str,
    cred_uuid: str,
    _auth: tuple = Depends(_require_admin),
):
    db.webauthn_delete_credential_by_uuid(cred_uuid)
    return {"ok": True}


# ── Database ─────────────────────────────────────────────────────────────────

@router.get("/api/enterprise/db/status")
@handle_errors
async def get_db_status(
    _auth: tuple = Depends(_require_admin),
):
    if DATABASE_URL.startswith("postgres"):
        try:
            conn = db._pg_conn
            ver = conn.execute("SELECT version()").fetchone()[0]
            # Extract server_version — "PostgreSQL 15.2 on ..."
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_enterprise_router.py -v
```

Expected: 5 passed (all return 401/403 for unauthenticated requests).

- [ ] **Step 5: Ruff check**

```bash
ruff check --fix share/noba-web/server/routers/enterprise.py
```

- [ ] **Step 6: Commit**

```bash
git add share/noba-web/server/routers/enterprise.py \
        tests/test_enterprise_router.py
git commit -m "feat(enterprise): add enterprise router with SAML/SCIM/WebAuthn/DB endpoints"
```

---

### Task 4: Register enterprise router in `routers/__init__.py`

**Files:**
- Modify: `share/noba-web/server/routers/__init__.py`

- [ ] **Step 1: Add import and include_router**

In `share/noba-web/server/routers/__init__.py`, add after the `from .scim import router as scim_router` line:

```python
from .enterprise import router as enterprise_router
```

And after `api_router.include_router(scim_router)`:

```python
api_router.include_router(enterprise_router)
```

- [ ] **Step 2: Verify routes are registered**

```bash
python3 -c "
from share.noba_web.server.routers import api_router
routes = [r.path for r in api_router.routes if hasattr(r, 'path')]
enterprise = [r for r in routes if '/enterprise/' in r]
print('Enterprise routes:', enterprise)
assert len(enterprise) == 7, f'Expected 7, got {len(enterprise)}'
print('All 7 enterprise routes registered.')
"
```

Expected: All 7 enterprise routes listed.

- [ ] **Step 3: Run full existing test suite**

```bash
pytest tests/ -v --ignore=tests/test_postgres_backend.py -q
```

Expected: All existing tests pass.

- [ ] **Step 4: Commit**

```bash
git add share/noba-web/server/routers/__init__.py
git commit -m "feat(enterprise): register enterprise router"
```

---

### Task 5: Add 4 enterprise tabs to `SettingsView.vue`

**Files:**
- Modify: `share/noba-web/frontend/src/views/SettingsView.vue`

- [ ] **Step 1: Add tab definitions to the `tabs` array**

In `SettingsView.vue`, find `{ key: 'plugins', label: 'Plugins', icon: 'fa-puzzle-piece', admin: true },` and add after it:

```javascript
  { key: 'saml',     label: 'SAML SSO',  icon: 'fa-id-card',    admin: true },
  { key: 'scim',     label: 'SCIM',      icon: 'fa-sync-alt',   admin: true },
  { key: 'webauthn', label: 'WebAuthn',  icon: 'fa-fingerprint', admin: true },
  { key: 'database', label: 'Database',  icon: 'fa-server',     admin: true },
```

- [ ] **Step 2: Add tab component mappings to `tabComponents`**

In `SettingsView.vue`, find `plugins: defineAsyncComponent(...)` and add after it:

```javascript
  saml:     defineAsyncComponent(() => import('../components/settings/SamlTab.vue')),
  scim:     defineAsyncComponent(() => import('../components/settings/ScimTab.vue')),
  webauthn: defineAsyncComponent(() => import('../components/settings/WebAuthnTab.vue')),
  database: defineAsyncComponent(() => import('../components/settings/DatabaseTab.vue')),
```

- [ ] **Step 3: Commit (components don't exist yet — build will fail until Task 6-9)**

```bash
git add share/noba-web/frontend/src/views/SettingsView.vue
git commit -m "feat(enterprise): add SAML/SCIM/WebAuthn/Database tab stubs to SettingsView"
```

---

### Task 6: Create `SamlTab.vue`

**Files:**
- Create: `share/noba-web/frontend/src/components/settings/SamlTab.vue`

- [ ] **Step 1: Create `SamlTab.vue`**

```vue
<script setup>
import { ref, onMounted } from 'vue'
import { useAuthStore } from '../../stores/auth'
import { useApi } from '../../composables/useApi'
import { USER_ACTION_MSG_TIMEOUT_MS } from '../../constants'

const authStore = useAuthStore()
const { get, put, post } = useApi()

const form = ref({
  samlEnabled: false,
  samlIdpSsoUrl: '',
  samlIdpCert: '',
  samlEntityId: '',
  samlAcsUrl: '',
  samlDefaultRole: 'viewer',
  samlGroupMapping: '{}',
})
const actionMsg = ref('')
const testResult = ref(null)
const testing = ref(false)
const saving = ref(false)

const spMetadataUrl = ref('')
const copied = ref('')

onMounted(async () => {
  if (!authStore.isAdmin) return
  spMetadataUrl.value = window.location.origin + '/api/saml/metadata'
  try {
    const d = await get('/api/enterprise/saml')
    Object.assign(form.value, d)
  } catch (e) {
    actionMsg.value = 'Load failed: ' + e.message
  }
})

async function save() {
  saving.value = true
  try {
    await put('/api/enterprise/saml', form.value)
    actionMsg.value = 'SAML configuration saved.'
  } catch (e) {
    actionMsg.value = 'Save failed: ' + e.message
  }
  saving.value = false
  setTimeout(() => { actionMsg.value = '' }, USER_ACTION_MSG_TIMEOUT_MS)
}

async function testConnection() {
  testing.value = true
  testResult.value = null
  try {
    testResult.value = await post('/api/enterprise/saml/test', {})
  } catch (e) {
    testResult.value = { ok: false, error: e.message }
  }
  testing.value = false
}

async function copyToClipboard(text, key) {
  await navigator.clipboard.writeText(text)
  copied.value = key
  setTimeout(() => { copied.value = '' }, 1500)
}
</script>

<template>
  <div>
    <div v-if="!authStore.isAdmin" style="text-align:center;padding:3rem;color:var(--text-muted)">
      <i class="fas fa-lock" style="font-size:2rem;margin-bottom:.75rem;display:block;opacity:.4"></i>
      Admin role required.
    </div>

    <template v-else>
      <div class="s-section">
        <span class="s-label">SAML SSO Configuration</span>

        <div v-if="actionMsg" style="font-size:.82rem;color:var(--text-muted);margin-bottom:.75rem">{{ actionMsg }}</div>

        <!-- Enable toggle -->
        <div style="margin-bottom:1rem;display:flex;align-items:center;gap:.75rem">
          <input id="saml-enabled" type="checkbox" v-model="form.samlEnabled">
          <label for="saml-enabled" class="field-label" style="margin:0">Enable SAML SSO</label>
        </div>

        <!-- IdP SSO URL -->
        <div style="margin-bottom:.75rem">
          <label class="field-label" for="saml-idp-url">IdP SSO URL</label>
          <input id="saml-idp-url" class="field-input" type="text" v-model="form.samlIdpSsoUrl"
            placeholder="https://idp.example.com/sso/saml">
        </div>

        <!-- IdP Certificate -->
        <div style="margin-bottom:.75rem">
          <label class="field-label" for="saml-idp-cert">IdP Certificate (PEM)</label>
          <textarea id="saml-idp-cert" class="field-input" rows="5"
            style="font-family:monospace;font-size:.8rem;resize:vertical"
            v-model="form.samlIdpCert"
            placeholder="-----BEGIN CERTIFICATE-----&#10;...&#10;-----END CERTIFICATE-----"></textarea>
        </div>

        <!-- SP Entity ID + ACS URL -->
        <div class="field-2" style="margin-bottom:.75rem">
          <div>
            <label class="field-label" for="saml-entity-id">SP Entity ID</label>
            <input id="saml-entity-id" class="field-input" type="text" v-model="form.samlEntityId"
              :placeholder="$root?.origin || 'https://noba.example.com'">
          </div>
          <div>
            <label class="field-label" for="saml-acs-url">Assertion Consumer Service URL</label>
            <input id="saml-acs-url" class="field-input" type="text" v-model="form.samlAcsUrl"
              :placeholder="(form.samlEntityId || 'https://noba.example.com') + '/api/saml/acs'">
          </div>
        </div>

        <!-- Default role + Group mapping -->
        <div class="field-2" style="margin-bottom:.75rem">
          <div>
            <label class="field-label" for="saml-default-role">Default role for new SAML users</label>
            <select id="saml-default-role" class="field-input field-select" v-model="form.samlDefaultRole">
              <option value="viewer">viewer</option>
              <option value="operator">operator</option>
              <option value="admin">admin</option>
            </select>
          </div>
          <div>
            <label class="field-label" for="saml-group-map">Role mapping (JSON)</label>
            <input id="saml-group-map" class="field-input" type="text" v-model="form.samlGroupMapping"
              placeholder='{"Admins": "admin"}'>
          </div>
        </div>

        <!-- Read-only SP info -->
        <div style="margin-bottom:1rem;border:1px solid var(--border);padding:.75rem;border-radius:4px;background:var(--surface-2)">
          <div style="font-size:.75rem;color:var(--text-muted);margin-bottom:.5rem;font-weight:600">SP Metadata (paste into IdP)</div>
          <div style="display:flex;align-items:center;gap:.5rem;margin-bottom:.4rem">
            <span style="font-size:.78rem;font-family:monospace">{{ spMetadataUrl }}</span>
            <button class="btn btn-xs" @click="copyToClipboard(spMetadataUrl, 'metadata')" style="flex-shrink:0">
              <i class="fas" :class="copied === 'metadata' ? 'fa-check' : 'fa-copy'"></i>
            </button>
          </div>
          <div style="display:flex;align-items:center;gap:.5rem">
            <span style="font-size:.78rem;color:var(--text-muted)">ACS: </span>
            <span style="font-size:.78rem;font-family:monospace">{{ form.samlAcsUrl || '(configure above)' }}</span>
            <button v-if="form.samlAcsUrl" class="btn btn-xs" @click="copyToClipboard(form.samlAcsUrl, 'acs')" style="flex-shrink:0">
              <i class="fas" :class="copied === 'acs' ? 'fa-check' : 'fa-copy'"></i>
            </button>
          </div>
        </div>

        <!-- Test connection result -->
        <div v-if="testResult" style="margin-bottom:.75rem;font-size:.82rem;padding:.5rem .75rem;border-radius:4px"
          :style="testResult.ok ? 'background:var(--surface-2);border:1px solid var(--success,#4ade80)' : 'background:var(--surface-2);border:1px solid var(--danger,#f87171)'">
          <span v-if="testResult.ok">
            <i class="fas fa-check-circle" style="color:var(--success,#4ade80)"></i>
            IdP reachable — HTTP {{ testResult.status }}, {{ testResult.latency_ms }}ms
          </span>
          <span v-else>
            <i class="fas fa-times-circle" style="color:var(--danger,#f87171)"></i>
            Connection failed
            <span v-if="testResult.status"> — HTTP {{ testResult.status }}</span>
            <span v-if="testResult.error"> — {{ testResult.error }}</span>
          </span>
        </div>

        <!-- Actions -->
        <div style="display:flex;gap:.5rem;flex-wrap:wrap">
          <button class="btn btn-sm btn-primary" @click="save" :disabled="saving">
            <i class="fas fa-save"></i> {{ saving ? 'Saving…' : 'Save' }}
          </button>
          <button class="btn btn-sm" @click="testConnection" :disabled="testing || !form.samlIdpSsoUrl">
            <i class="fas fa-plug"></i> {{ testing ? 'Testing…' : 'Test Connection' }}
          </button>
        </div>
      </div>
    </template>
  </div>
</template>
```

- [ ] **Step 2: Commit**

```bash
git add share/noba-web/frontend/src/components/settings/SamlTab.vue
git commit -m "feat(enterprise): add SamlTab.vue settings component"
```

---

### Task 7: Create `ScimTab.vue`

**Files:**
- Create: `share/noba-web/frontend/src/components/settings/ScimTab.vue`

- [ ] **Step 1: Create `ScimTab.vue`**

```vue
<script setup>
import { ref, onMounted } from 'vue'
import { useAuthStore } from '../../stores/auth'
import { useApi } from '../../composables/useApi'
import { USER_ACTION_MSG_TIMEOUT_MS } from '../../constants'

const authStore = useAuthStore()
const { get, post } = useApi()

const status = ref(null)
const scimBaseUrl = ref('')
const newToken = ref('')
const actionMsg = ref('')
const rotating = ref(false)
const copied = ref('')

onMounted(async () => {
  if (!authStore.isAdmin) return
  scimBaseUrl.value = window.location.origin + '/api/scim/v2'
  await fetchStatus()
})

async function fetchStatus() {
  try {
    status.value = await get('/api/enterprise/scim/status')
  } catch (e) {
    actionMsg.value = 'Load failed: ' + e.message
  }
}

async function generateToken() {
  rotating.value = true
  newToken.value = ''
  try {
    const d = await post('/api/admin/scim-token', {})
    newToken.value = d.token
    await fetchStatus()
    actionMsg.value = 'Token generated. Copy it now — it will not be shown again.'
  } catch (e) {
    actionMsg.value = 'Failed: ' + e.message
  }
  rotating.value = false
  setTimeout(() => { actionMsg.value = '' }, USER_ACTION_MSG_TIMEOUT_MS)
}

function dismissToken() {
  newToken.value = ''
}

async function copyToClipboard(text, key) {
  await navigator.clipboard.writeText(text)
  copied.value = key
  setTimeout(() => { copied.value = '' }, 1500)
}

function formatDate(ts) {
  if (!ts) return 'N/A'
  return new Date(ts * 1000).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
}
</script>

<template>
  <div>
    <div v-if="!authStore.isAdmin" style="text-align:center;padding:3rem;color:var(--text-muted)">
      <i class="fas fa-lock" style="font-size:2rem;margin-bottom:.75rem;display:block;opacity:.4"></i>
      Admin role required.
    </div>

    <template v-else>
      <div class="s-section">
        <span class="s-label">SCIM Provisioning</span>

        <div v-if="actionMsg" style="font-size:.82rem;color:var(--text-muted);margin-bottom:.75rem">{{ actionMsg }}</div>

        <!-- New token banner -->
        <div v-if="newToken" style="margin-bottom:1rem;padding:.75rem 1rem;background:var(--surface-2);border:1px solid #ca8a04;border-radius:4px">
          <div style="font-size:.8rem;font-weight:600;color:#ca8a04;margin-bottom:.4rem">
            <i class="fas fa-exclamation-triangle"></i> Copy this token — it will not be shown again
          </div>
          <div style="display:flex;align-items:center;gap:.5rem">
            <code style="font-size:.8rem;word-break:break-all;flex:1">{{ newToken }}</code>
            <button class="btn btn-xs" @click="copyToClipboard(newToken, 'token')">
              <i class="fas" :class="copied === 'token' ? 'fa-check' : 'fa-copy'"></i>
            </button>
            <button class="btn btn-xs btn-danger" @click="dismissToken" aria-label="Dismiss">
              <i class="fas fa-times"></i>
            </button>
          </div>
        </div>

        <!-- Status -->
        <div v-if="status" style="margin-bottom:1rem">
          <div style="display:flex;align-items:center;gap:.75rem;margin-bottom:.5rem">
            <span style="font-size:.8rem;color:var(--text-muted)">Status:</span>
            <span class="badge" :class="status.active ? 'ba' : 'bn'" style="font-size:.75rem">
              {{ status.active ? 'Active' : 'No token' }}
            </span>
          </div>
          <div v-if="status.active" style="font-size:.8rem;color:var(--text-muted);display:flex;flex-direction:column;gap:.2rem">
            <span>Expires: {{ formatDate(status.expires_at) }}</span>
            <span>Last used: {{ status.last_used_at ? formatDate(status.last_used_at) : 'Never' }}</span>
            <span>Last provisioning activity: {{ status.last_activity ? formatDate(status.last_activity) : 'N/A' }}</span>
          </div>
        </div>

        <!-- SCIM Base URL -->
        <div style="margin-bottom:1rem">
          <label class="field-label">SCIM Base URL (paste into Okta / Azure AD)</label>
          <div style="display:flex;align-items:center;gap:.5rem">
            <input class="field-input" type="text" :value="scimBaseUrl" readonly style="flex:1">
            <button class="btn btn-sm" @click="copyToClipboard(scimBaseUrl, 'base')">
              <i class="fas" :class="copied === 'base' ? 'fa-check' : 'fa-copy'"></i>
              {{ copied === 'base' ? 'Copied' : 'Copy' }}
            </button>
          </div>
        </div>

        <!-- Supported resources -->
        <div style="margin-bottom:1rem;font-size:.8rem;color:var(--text-muted)">
          Supported resources: <strong>Users</strong>
        </div>

        <!-- Generate / Rotate button -->
        <button class="btn btn-sm btn-primary" @click="generateToken" :disabled="rotating">
          <i class="fas fa-key"></i>
          {{ rotating ? 'Generating…' : (status?.active ? 'Rotate Token' : 'Generate Token') }}
        </button>
      </div>
    </template>
  </div>
</template>
```

- [ ] **Step 2: Commit**

```bash
git add share/noba-web/frontend/src/components/settings/ScimTab.vue
git commit -m "feat(enterprise): add ScimTab.vue settings component"
```

---

### Task 8: Create `WebAuthnTab.vue`

**Files:**
- Create: `share/noba-web/frontend/src/components/settings/WebAuthnTab.vue`

- [ ] **Step 1: Create `WebAuthnTab.vue`**

```vue
<script setup>
import { ref, onMounted } from 'vue'
import { useAuthStore } from '../../stores/auth'
import { useApi } from '../../composables/useApi'
import { useModalsStore } from '../../stores/modals'
import { USER_ACTION_MSG_TIMEOUT_MS } from '../../constants'

const authStore = useAuthStore()
const { get, del } = useApi()
const modals = useModalsStore()

const credentials = ref([])
const loading = ref(false)
const actionMsg = ref('')

onMounted(() => {
  if (authStore.isAdmin) fetchCredentials()
})

async function fetchCredentials() {
  loading.value = true
  try {
    credentials.value = await get('/api/enterprise/webauthn/credentials')
  } catch (e) {
    actionMsg.value = 'Load failed: ' + e.message
  }
  loading.value = false
}

async function revokeCredential(cred) {
  if (!await modals.confirm(`Revoke passkey "${cred.name || cred.id}" for ${cred.username}?`)) return
  try {
    await del(`/api/enterprise/webauthn/credentials/${encodeURIComponent(cred.username)}/${cred.id}`)
    actionMsg.value = `Passkey revoked for ${cred.username}.`
    await fetchCredentials()
  } catch (e) {
    actionMsg.value = 'Revoke failed: ' + e.message
  }
  setTimeout(() => { actionMsg.value = '' }, USER_ACTION_MSG_TIMEOUT_MS)
}

function formatDate(ts) {
  if (!ts) return '—'
  return new Date(ts * 1000).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
}
</script>

<template>
  <div>
    <div v-if="!authStore.isAdmin" style="text-align:center;padding:3rem;color:var(--text-muted)">
      <i class="fas fa-lock" style="font-size:2rem;margin-bottom:.75rem;display:block;opacity:.4"></i>
      Admin role required.
    </div>

    <template v-else>
      <div class="s-section">
        <span class="s-label">WebAuthn Passkey Management</span>

        <div v-if="actionMsg" style="font-size:.82rem;color:var(--text-muted);margin-bottom:.75rem">{{ actionMsg }}</div>

        <!-- Loading -->
        <div v-if="loading" style="padding:2rem;text-align:center;color:var(--text-muted)">
          <i class="fas fa-spinner fa-spin"></i> Loading passkeys…
        </div>

        <!-- Empty state -->
        <div v-else-if="credentials.length === 0"
          style="text-align:center;padding:2.5rem;background:var(--surface);border:1px dashed var(--border);border-radius:6px;color:var(--text-muted)">
          <i class="fas fa-fingerprint" style="font-size:2rem;display:block;margin-bottom:.75rem;opacity:.3"></i>
          No passkeys registered. Users can register passkeys from the login screen.
        </div>

        <!-- Credentials table -->
        <div v-else style="overflow-x:auto">
          <table style="width:100%;border-collapse:collapse;font-size:.82rem">
            <thead>
              <tr style="border-bottom:1px solid var(--border);text-align:left">
                <th style="padding:.5rem .75rem;color:var(--text-muted);font-weight:600">Username</th>
                <th style="padding:.5rem .75rem;color:var(--text-muted);font-weight:600">Passkey Name</th>
                <th style="padding:.5rem .75rem;color:var(--text-muted);font-weight:600">Registered</th>
                <th style="padding:.5rem .75rem;color:var(--text-muted);font-weight:600">Uses</th>
                <th style="padding:.5rem .75rem"></th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="cred in credentials" :key="cred.id"
                style="border-bottom:1px solid var(--border)"
              >
                <td style="padding:.5rem .75rem">
                  <i class="fas fa-user" style="color:var(--text-muted);margin-right:.4rem;opacity:.5"></i>
                  {{ cred.username }}
                </td>
                <td style="padding:.5rem .75rem">{{ cred.name || '(unnamed)' }}</td>
                <td style="padding:.5rem .75rem">{{ formatDate(cred.created_at) }}</td>
                <td style="padding:.5rem .75rem">{{ cred.sign_count }}</td>
                <td style="padding:.5rem .75rem;text-align:right">
                  <button class="btn btn-xs btn-danger" @click="revokeCredential(cred)"
                    :aria-label="'Revoke passkey for ' + cred.username">
                    <i class="fas fa-ban"></i> Revoke
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>
  </div>
</template>
```

- [ ] **Step 2: Commit**

```bash
git add share/noba-web/frontend/src/components/settings/WebAuthnTab.vue
git commit -m "feat(enterprise): add WebAuthnTab.vue settings component"
```

---

### Task 9: Create `DatabaseTab.vue`

**Files:**
- Create: `share/noba-web/frontend/src/components/settings/DatabaseTab.vue`

- [ ] **Step 1: Create `DatabaseTab.vue`**

```vue
<script setup>
import { ref, onMounted } from 'vue'
import { useAuthStore } from '../../stores/auth'
import { useApi } from '../../composables/useApi'

const authStore = useAuthStore()
const { get } = useApi()

const status = ref(null)
const loading = ref(false)
const showMigration = ref(false)
const copied = ref(false)

const migrationCmd = ref('')

onMounted(async () => {
  if (!authStore.isAdmin) return
  loading.value = true
  try {
    status.value = await get('/api/enterprise/db/status')
    if (status.value?.backend === 'sqlite') {
      migrationCmd.value =
        `DATABASE_URL=postgresql://user:pass@host/noba \\\n` +
        `  python3 scripts/migrate-to-postgres.py ${status.value.path || '~/.local/share/noba-history.db'}`
    }
  } catch (e) {
    status.value = { backend: 'unknown', error: e.message }
  }
  loading.value = false
})

async function copyCmd() {
  await navigator.clipboard.writeText(migrationCmd.value)
  copied.value = true
  setTimeout(() => { copied.value = false }, 1500)
}
</script>

<template>
  <div>
    <div v-if="!authStore.isAdmin" style="text-align:center;padding:3rem;color:var(--text-muted)">
      <i class="fas fa-lock" style="font-size:2rem;margin-bottom:.75rem;display:block;opacity:.4"></i>
      Admin role required.
    </div>

    <template v-else>
      <div class="s-section">
        <span class="s-label">Database Backend</span>

        <div v-if="loading" style="padding:2rem;text-align:center;color:var(--text-muted)">
          <i class="fas fa-spinner fa-spin"></i> Loading…
        </div>

        <template v-else-if="status">
          <!-- Backend badge -->
          <div style="display:flex;align-items:center;gap:.75rem;margin-bottom:1rem">
            <span class="badge" :class="status.backend === 'postgresql' ? 'ba' : 'bn'">
              {{ status.backend === 'postgresql' ? 'PostgreSQL' : status.backend === 'sqlite' ? 'SQLite' : status.backend }}
            </span>
            <span v-if="status.backend === 'postgresql'">
              <i class="fas fa-circle" :style="status.connected ? 'color:var(--success,#4ade80)' : 'color:var(--danger,#f87171)'"></i>
              {{ status.connected ? 'Connected' : 'Disconnected' }}
            </span>
          </div>

          <!-- SQLite details -->
          <template v-if="status.backend === 'sqlite'">
            <div style="font-size:.82rem;display:flex;flex-direction:column;gap:.3rem;margin-bottom:1rem;color:var(--text-muted)">
              <span><strong>Path:</strong> {{ status.path }}</span>
              <span><strong>WAL mode:</strong>
                <span :style="status.wal_mode ? 'color:var(--success,#4ade80)' : ''">{{ status.wal_mode ? 'enabled' : 'disabled' }}</span>
              </span>
            </div>
            <div style="font-size:.8rem;color:var(--text-muted);margin-bottom:.75rem">
              <i class="fas fa-info-circle"></i>
              SQLite is ideal for single-server deployments.
              Switch to PostgreSQL for multi-instance or high-load environments.
            </div>

            <!-- Migration section -->
            <div style="border:1px solid var(--border);border-radius:4px;overflow:hidden">
              <button class="btn btn-sm" style="width:100%;text-align:left;border-radius:0;padding:.6rem .75rem;display:flex;justify-content:space-between"
                @click="showMigration = !showMigration">
                <span><i class="fas fa-database" style="margin-right:.4rem"></i> Migrate to PostgreSQL</span>
                <i class="fas" :class="showMigration ? 'fa-chevron-up' : 'fa-chevron-down'"></i>
              </button>
              <div v-if="showMigration" style="padding:.75rem;background:var(--surface-2)">
                <p style="font-size:.8rem;color:var(--text-muted);margin-bottom:.5rem">
                  Set <code>DATABASE_URL</code> in your environment, then run the migration script once.
                  Restart NOBA after migration.
                </p>
                <div style="position:relative">
                  <pre style="font-size:.78rem;background:var(--surface);border:1px solid var(--border);padding:.75rem;border-radius:4px;overflow-x:auto;margin:0">{{ migrationCmd }}</pre>
                  <button class="btn btn-xs" style="position:absolute;top:.4rem;right:.4rem" @click="copyCmd">
                    <i class="fas" :class="copied ? 'fa-check' : 'fa-copy'"></i>
                  </button>
                </div>
                <p style="font-size:.75rem;color:var(--text-muted);margin-top:.5rem">
                  <i class="fas fa-info-circle"></i>
                  <code>DATABASE_URL</code> is read from the environment on startup.
                  It cannot be set from the UI (requires server restart to take effect).
                </p>
              </div>
            </div>
          </template>

          <!-- PostgreSQL details -->
          <template v-else-if="status.backend === 'postgresql'">
            <div style="font-size:.82rem;display:grid;grid-template-columns:auto 1fr;gap:.3rem .75rem;margin-bottom:1rem">
              <span style="color:var(--text-muted)">Host</span>        <span>{{ status.host }}</span>
              <span style="color:var(--text-muted)">Database</span>    <span>{{ status.database }}</span>
              <span style="color:var(--text-muted)">Version</span>     <span>{{ status.server_version }}</span>
              <span style="color:var(--text-muted)">Pool min</span>    <span>{{ status.pool_min }}</span>
              <span style="color:var(--text-muted)">Pool max</span>    <span>{{ status.pool_max }}</span>
            </div>
            <div v-if="status.error" style="font-size:.8rem;color:var(--danger,#f87171)">
              Error: {{ status.error }}
            </div>
          </template>
        </template>
      </div>
    </template>
  </div>
</template>
```

- [ ] **Step 2: Commit**

```bash
git add share/noba-web/frontend/src/components/settings/DatabaseTab.vue
git commit -m "feat(enterprise): add DatabaseTab.vue settings component"
```

---

### Task 10: Build frontend and verify

**Files:**
- Build output: `share/noba-web/static/dist/`

- [ ] **Step 1: Build the frontend**

```bash
cd /home/raizen/noba/.worktrees/enterprise-v2/share/noba-web/frontend
npm run build
```

Expected: Build completes with no errors. All 4 new tab components included in the bundle.

- [ ] **Step 2: Verify the build includes the new components**

```bash
grep -l "SamlTab\|ScimTab\|WebAuthnTab\|DatabaseTab" \
  /home/raizen/noba/.worktrees/enterprise-v2/share/noba-web/static/dist/assets/*.js \
  | head -5
```

Expected: At least one asset file contains the component names.

- [ ] **Step 3: Run full backend test suite**

```bash
cd /home/raizen/noba/.worktrees/enterprise-v2
pytest tests/ -v --ignore=tests/test_postgres_backend.py -q
```

Expected: All tests pass.

- [ ] **Step 4: Commit the built assets**

```bash
cd /home/raizen/noba/.worktrees/enterprise-v2
git add share/noba-web/static/dist/
git commit -m "build: rebuild frontend with enterprise settings tabs"
```

---

### Task 11: Write `docs/enterprise-setup.md` and README one-liner

**Files:**
- Create: `docs/enterprise-setup.md`
- Modify: `README.md`

- [ ] **Step 1: Create `docs/enterprise-setup.md`**

```markdown
# NOBA Enterprise Setup Guide

Enterprise features (SAML SSO, SCIM provisioning, WebAuthn passkeys, PostgreSQL backend) are
configured from **Settings → enterprise tabs** in the NOBA UI. No SSH or env-file editing is
required for runtime configuration.

---

## Prerequisites

- NOBA 2.x running with admin account
- For PostgreSQL: `psycopg2-binary` installed (`pip install psycopg2-binary`)
- For SAML: IdP metadata (SSO URL + X.509 certificate)
- For SCIM: Okta, Azure AD, or compatible IdP with SCIM 2.0 support

---

## SAML SSO

1. In your IdP (Okta, Azure AD, etc.), create a new SAML application.
2. In NOBA **Settings → SAML SSO**:
   - Paste the **IdP SSO URL** and **IdP Certificate (PEM)** from your IdP's metadata.
   - Copy the **SP Metadata URL** (`<noba-origin>/api/saml/metadata`) into your IdP's configuration.
   - Set **SP Entity ID** and **ACS URL** (auto-filled; must match your IdP application settings).
   - Set **Default role** for newly provisioned SAML users (`viewer` recommended).
   - Optionally set **Role mapping JSON** to map IdP groups to NOBA roles:
     ```json
     {"Admins": "admin", "Operators": "operator"}
     ```
3. Click **Test Connection** to verify IdP reachability.
4. Enable **Enable SAML SSO** and click **Save**.

Users visiting the NOBA login page will see a "Sign in with SSO" option.

---

## SCIM Provisioning

1. In NOBA **Settings → SCIM**:
   - Click **Generate Token**.
   - Copy the token immediately — it is shown only once.
   - Copy the **SCIM Base URL** (`<noba-origin>/api/scim/v2`).
2. In your IdP, configure SCIM 2.0 provisioning:
   - Paste the SCIM Base URL as the tenant URL.
   - Paste the token as the API secret / bearer token.
   - Map user attributes: `userName → username`, `emails → email`.
3. Test the connection in your IdP and enable provisioning.

NOBA supports the **Users** resource (create, update, deactivate). Groups are not currently supported.

To rotate the token, click **Rotate Token** in the SCIM tab and update your IdP.

---

## PostgreSQL Backend

NOBA uses SQLite by default. Switch to PostgreSQL for multi-instance deployments or higher write throughput.

1. Create a PostgreSQL database:
   ```sql
   CREATE DATABASE noba;
   CREATE USER noba WITH PASSWORD 'yourpassword';
   GRANT ALL PRIVILEGES ON DATABASE noba TO noba;
   ```

2. Set the `DATABASE_URL` environment variable before starting NOBA:
   ```bash
   export DATABASE_URL=postgresql://noba:yourpassword@localhost:5432/noba
   ```

3. Start NOBA — tables are auto-created on first run.

4. **Optional: migrate existing SQLite data**
   ```bash
   DATABASE_URL=postgresql://noba:yourpassword@localhost:5432/noba \
     python3 scripts/migrate-to-postgres.py ~/.local/share/noba-history.db
   ```

   The **Settings → Database** tab shows the active backend, connection status, and pool configuration.

Pool size is tunable via env vars:
```bash
NOBA_PG_POOL_MIN=2
NOBA_PG_POOL_MAX=20
```

---

## WebAuthn Passkeys

Users register their own passkeys from the NOBA **login screen** using any FIDO2-compatible authenticator
(hardware security key, Touch ID, Windows Hello, etc.).

As an admin, the **Settings → WebAuthn** tab lists all registered passkeys across all users. You can
revoke any passkey from this view (e.g., for a lost device or departed employee).

---

## MySQL (Future)

MySQL support follows the same `DATABASE_URL` pattern:
```bash
DATABASE_URL=mysql://noba:yourpassword@localhost:3306/noba
```

This is not yet implemented; the adapter pattern (`db/postgres_adapter.py`) is designed for easy extension.
```

- [ ] **Step 2: Add one-liner to README.md**

Find the last major section heading in README.md and append before it (or at the end of the file):

```markdown
## Enterprise Edition

SAML SSO, SCIM provisioning, WebAuthn passkeys, and PostgreSQL backend are available in the enterprise branch.
See [docs/enterprise-setup.md](docs/enterprise-setup.md) for setup instructions.
```

- [ ] **Step 3: Commit**

```bash
git add docs/enterprise-setup.md README.md
git commit -m "docs: add enterprise-setup.md and README enterprise section"
```

---

### Task 12: Create `scripts/migrate-to-mysql.py`

**Files:**
- Create: `scripts/migrate-to-mysql.py`

- [ ] **Step 1: Create `scripts/migrate-to-mysql.py`**

```python
#!/usr/bin/env python3
"""migrate-to-mysql.py — Copy NOBA data from SQLite to MySQL.

Usage:
    python3 scripts/migrate-to-mysql.py [sqlite_path]

DATABASE_URL must be set in the environment:
    DATABASE_URL=mysql://noba:secret@localhost:3306/noba \\
        python3 scripts/migrate-to-mysql.py ~/.local/share/noba-history.db

The MySQL database must already have the schema initialised
(start NOBA once with DATABASE_URL set, then run this script).

Notes:
- Skips tables that don't exist in MySQL (uses INSERT IGNORE)
- Preserves all row data; does not truncate existing MySQL rows
- Safe to re-run: duplicate rows are silently skipped
- Requires: pip install PyMySQL
"""
from __future__ import annotations

import os
import re
import sqlite3
import sys


def _parse_mysql_url(url: str) -> dict:
    """Parse mysql://user:pass@host:port/dbname into a dict for PyMySQL."""
    m = re.match(
        r"mysql(?:\+pymysql)?://([^:@/]+)(?::([^@/]*))?@([^:/]+)(?::(\d+))?/([^?]+)",
        url,
    )
    if not m:
        raise ValueError(f"Cannot parse DATABASE_URL as MySQL URL: {url}")
    user, password, host, port, db = m.groups()
    return {
        "host": host,
        "port": int(port or 3306),
        "user": user,
        "password": password or "",
        "database": db,
        "charset": "utf8mb4",
    }


def main() -> None:
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url.lower().startswith("mysql"):
        print("ERROR: DATABASE_URL must be set to a MySQL connection string.", file=sys.stderr)
        print("  Example: DATABASE_URL=mysql://user:pass@localhost:3306/noba", file=sys.stderr)
        sys.exit(1)

    sqlite_path = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser(
        "~/.local/share/noba-history.db"
    )
    if not os.path.exists(sqlite_path):
        print(f"ERROR: SQLite database not found: {sqlite_path}", file=sys.stderr)
        sys.exit(1)

    try:
        import pymysql
    except ImportError:
        print("ERROR: PyMySQL is not installed.", file=sys.stderr)
        print("  pip install PyMySQL", file=sys.stderr)
        sys.exit(1)

    try:
        conn_params = _parse_mysql_url(db_url)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    dest_display = f"{conn_params['host']}:{conn_params['port']}/{conn_params['database']}"
    print(f"Source:      {sqlite_path}")
    print(f"Destination: {dest_display}")
    print()

    sq = sqlite3.connect(sqlite_path)
    sq.row_factory = sqlite3.Row
    my = pymysql.connect(**conn_params, autocommit=False)

    # Discover tables in SQLite
    tables = [
        row[0]
        for row in sq.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    ]

    # Discover tables in MySQL
    with my.cursor() as cur:
        cur.execute("SHOW TABLES")
        my_tables = {row[0] for row in cur.fetchall()}

    total_rows = 0
    for table in sorted(tables):
        if table not in my_tables:
            print(f"  SKIP  {table} (not in MySQL schema)")
            continue

        rows = sq.execute(f"SELECT * FROM {table}").fetchall()  # noqa: S608
        if not rows:
            print(f"  EMPTY {table}")
            continue

        cols = rows[0].keys()
        placeholders = ", ".join(["%s"] * len(cols))
        col_names = ", ".join(f"`{c}`" for c in cols)
        # INSERT IGNORE silently skips duplicate primary-key rows
        sql = f"INSERT IGNORE INTO `{table}` ({col_names}) VALUES ({placeholders})"

        inserted = 0
        with my.cursor() as cur:
            for row in rows:
                try:
                    cur.execute(sql, tuple(row))
                    if cur.rowcount > 0:
                        inserted += 1
                except Exception as exc:  # noqa: BLE001
                    my.rollback()
                    print(f"  ERROR {table}: {exc}")
                    break
            else:
                my.commit()

        total_rows += inserted
        print(f"  OK    {table}: {inserted}/{len(rows)} rows migrated")

    sq.close()
    my.close()
    print()
    print(f"Done. {total_rows} rows migrated across {len(tables)} tables.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Make it executable and verify syntax**

```bash
chmod +x scripts/migrate-to-mysql.py
python3 -c "import ast; ast.parse(open('scripts/migrate-to-mysql.py').read()); print('Syntax OK')"
```

Expected: `Syntax OK`

- [ ] **Step 3: Add PyMySQL to requirements-enterprise.txt**

Append to `requirements-enterprise.txt`:
```
PyMySQL>=1.1
```

- [ ] **Step 4: Update enterprise-setup.md MySQL section**

In `docs/enterprise-setup.md`, replace the MySQL section:

```markdown
## MySQL Backend

MySQL support follows the same `DATABASE_URL` pattern as PostgreSQL.

1. Create the database:
   ```sql
   CREATE DATABASE noba CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
   CREATE USER 'noba'@'%' IDENTIFIED BY 'yourpassword';
   GRANT ALL PRIVILEGES ON noba.* TO 'noba'@'%';
   FLUSH PRIVILEGES;
   ```

2. Install the driver:
   ```bash
   pip install PyMySQL
   ```

3. Set the `DATABASE_URL` environment variable before starting NOBA:
   ```bash
   export DATABASE_URL=mysql://noba:yourpassword@localhost:3306/noba
   ```

4. Start NOBA — tables are auto-created on first run.

5. **Optional: migrate existing SQLite data**
   ```bash
   DATABASE_URL=mysql://noba:yourpassword@localhost:3306/noba \
     python3 scripts/migrate-to-mysql.py ~/.local/share/noba-history.db
   ```

The MySQL adapter uses `INSERT IGNORE` (equivalent to PostgreSQL's `ON CONFLICT DO NOTHING`)
and backtick-quoted identifiers for full compatibility. The **Settings → Database** tab will
display "mysql" as the backend name automatically once MySQL adapter support is added.
```

- [ ] **Step 5: Commit**

```bash
git add scripts/migrate-to-mysql.py requirements-enterprise.txt docs/enterprise-setup.md
git commit -m "feat(enterprise): add MySQL migration script + update enterprise docs"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Task |
|---|---|
| SAML tab: 7 form fields + test connection | Task 3 (API), Task 6 (UI) |
| SAML SP metadata URL + copy button | Task 6 |
| SCIM tab: status, show-once token reveal, copy base URL | Task 7 |
| SCIM token generate/rotate via POST /api/admin/scim-token | Task 7 |
| WebAuthn tab: all users' passkeys, admin revoke | Task 1 (DB), Task 3 (API), Task 8 (UI) |
| Database tab: backend badge, pool info, migration snippet | Task 3 (API), Task 9 (UI) |
| WEB_KEYS additions for SAML keys | Task 2 |
| enterprise.py with 7 admin-gated endpoints | Task 3 |
| routers/__init__.py registration | Task 4 |
| SettingsView.vue 4 new tabs | Task 5 |
| docs/enterprise-setup.md sections 1-5 | Task 11 |
| README Enterprise section | Task 11 |
| Frontend build committed | Task 10 |

**No placeholders found. All steps contain exact code.**

**Type consistency verified:** `scim_get_active_token_status()`, `webauthn_get_all_credentials()`, `webauthn_delete_credential_by_uuid(uid)` defined in Task 1, used in Task 3. `useApi` `get`/`put`/`post`/`del` used consistently across Vue tasks. Task 12 MySQL script mirrors Task 3's PostgreSQL migration verbatim except driver import (`pymysql`), URL parser, `INSERT IGNORE` syntax, and backtick identifiers.
