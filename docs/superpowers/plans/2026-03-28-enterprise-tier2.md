# Enterprise Tier 2 — RBAC, Freeze Windows, Secrets Vault

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add three enterprise security features: resource-type RBAC ACLs, change freeze windows, and an AES-256 secrets vault — all tenant-scoped.

**Architecture:** Each feature is an independent DB module (`db/rbac.py`, `db/freeze.py`, `db/vault.py`) following the existing `(conn, lock, ...)` pattern with a `_*Mixin` class registered in `core.py`. Router endpoints go in `routers/enterprise.py`. FastAPI guard dependencies go in `deps.py`. Three new Vue settings tabs.

**Tech Stack:** FastAPI, SQLite/PostgreSQL, `cryptography` (already in requirements), Vue 3 `<script setup>`, Pinia `useApi()`

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `share/noba-web/server/db/rbac.py` | `resource_acls` schema, CRUD, `_RBACMixin` |
| Create | `share/noba-web/server/db/freeze.py` | `freeze_windows` schema, CRUD, active-check, `_FreezeMixin` |
| Create | `share/noba-web/server/db/vault.py` | `vault_secrets` schema, AES-256-GCM encrypt/decrypt, `_VaultMixin` |
| Modify | `share/noba-web/server/db/core.py` | Import + register 3 new mixins; add rbac/freeze/vault to `_SCHEMA_MODULES` |
| Modify | `share/noba-web/server/deps.py` | Add `check_resource_acl()` factory and `check_not_frozen()` dependency |
| Modify | `share/noba-web/server/routers/enterprise.py` | RBAC, freeze-window, vault CRUD endpoints |
| Modify | `share/noba-web/server/routers/automations.py` | Inject `check_not_frozen()` into create/update/delete automation + webhook |
| Create | `share/noba-web/frontend/src/components/settings/RBACTab.vue` | ACL management UI per user/resource type |
| Create | `share/noba-web/frontend/src/components/settings/FreezeTab.vue` | Freeze window CRUD UI |
| Create | `share/noba-web/frontend/src/components/settings/VaultTab.vue` | Vault secret list + add/delete (values never shown) |
| Modify | `share/noba-web/frontend/src/views/SettingsView.vue` | Register 3 new tabs |
| Create | `tests/test_rbac.py` | Unit tests for RBAC DB layer |
| Create | `tests/test_freeze.py` | Unit tests for freeze window DB layer + active-check logic |
| Create | `tests/test_vault.py` | Unit tests for vault encrypt/decrypt round-trip |

---

## ── FEATURE 1: RBAC Policy Engine ──────────────────────────────────────

### Task 1: `db/rbac.py` — schema + CRUD

**Files:**
- Create: `share/noba-web/server/db/rbac.py`
- Create: `tests/test_rbac.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_rbac.py
"""Tests for db.rbac: resource_acls table."""
from __future__ import annotations
import sqlite3
import threading
import pytest
from server.db.rbac import init_schema, set_acl, get_acl, list_acls, delete_acl


@pytest.fixture()
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    lock = threading.Lock()
    init_schema(conn)
    return conn, lock


class TestRBACSchema:
    def test_set_and_get_acl(self, db):
        conn, lock = db
        set_acl(conn, lock, tenant_id="default", username="alice",
                resource_type="automations", can_read=True, can_write=False)
        row = get_acl(conn, lock, "default", "alice", "automations")
        assert row is not None
        assert row["can_read"] == 1
        assert row["can_write"] == 0

    def test_list_acls_by_tenant(self, db):
        conn, lock = db
        set_acl(conn, lock, "t1", "alice", "automations", True, False)
        set_acl(conn, lock, "t1", "alice", "api_keys", True, True)
        set_acl(conn, lock, "t2", "bob", "automations", True, False)
        rows = list_acls(conn, lock, tenant_id="t1")
        assert len(rows) == 2

    def test_upsert_overwrites(self, db):
        conn, lock = db
        set_acl(conn, lock, "default", "alice", "automations", True, False)
        set_acl(conn, lock, "default", "alice", "automations", False, False)
        row = get_acl(conn, lock, "default", "alice", "automations")
        assert row["can_read"] == 0

    def test_delete_acl(self, db):
        conn, lock = db
        set_acl(conn, lock, "default", "alice", "automations", True, True)
        delete_acl(conn, lock, "default", "alice", "automations")
        assert get_acl(conn, lock, "default", "alice", "automations") is None

    def test_no_acl_returns_none(self, db):
        conn, lock = db
        assert get_acl(conn, lock, "default", "bob", "integrations") is None
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd /home/raizen/noba/.worktrees/enterprise-v2
PYTHONPATH=share/noba-web pytest tests/test_rbac.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'server.db.rbac'`

- [ ] **Step 3: Implement `db/rbac.py`**

```python
# share/noba-web/server/db/rbac.py
"""Noba – Resource-type RBAC ACL DB functions."""
from __future__ import annotations

import logging
import sqlite3
import threading

logger = logging.getLogger("noba")

VALID_RESOURCE_TYPES = frozenset({
    "integrations", "automations", "api_keys", "webhooks", "users", "audit",
})


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS resource_acls (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id   TEXT NOT NULL DEFAULT 'default',
            username    TEXT NOT NULL,
            resource_type TEXT NOT NULL,
            can_read    INTEGER NOT NULL DEFAULT 1,
            can_write   INTEGER NOT NULL DEFAULT 1,
            UNIQUE(tenant_id, username, resource_type)
        );
        CREATE INDEX IF NOT EXISTS idx_acls_tenant_user
            ON resource_acls(tenant_id, username);
    """)


def set_acl(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    tenant_id: str,
    username: str,
    resource_type: str,
    can_read: bool,
    can_write: bool,
) -> None:
    with lock:
        conn.execute(
            "INSERT INTO resource_acls (tenant_id, username, resource_type, can_read, can_write)"
            " VALUES (?,?,?,?,?)"
            " ON CONFLICT(tenant_id, username, resource_type)"
            " DO UPDATE SET can_read=excluded.can_read, can_write=excluded.can_write",
            (tenant_id, username, resource_type, int(can_read), int(can_write)),
        )
        conn.commit()


def get_acl(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    tenant_id: str,
    username: str,
    resource_type: str,
) -> dict | None:
    with lock:
        row = conn.execute(
            "SELECT tenant_id, username, resource_type, can_read, can_write"
            " FROM resource_acls WHERE tenant_id=? AND username=? AND resource_type=?",
            (tenant_id, username, resource_type),
        ).fetchone()
    if row is None:
        return None
    return dict(row)


def list_acls(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    tenant_id: str,
    username: str | None = None,
) -> list[dict]:
    with lock:
        if username:
            rows = conn.execute(
                "SELECT tenant_id, username, resource_type, can_read, can_write"
                " FROM resource_acls WHERE tenant_id=? AND username=? ORDER BY resource_type",
                (tenant_id, username),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT tenant_id, username, resource_type, can_read, can_write"
                " FROM resource_acls WHERE tenant_id=? ORDER BY username, resource_type",
                (tenant_id,),
            ).fetchall()
    return [dict(r) for r in rows]


def delete_acl(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    tenant_id: str,
    username: str,
    resource_type: str,
) -> None:
    with lock:
        conn.execute(
            "DELETE FROM resource_acls WHERE tenant_id=? AND username=? AND resource_type=?",
            (tenant_id, username, resource_type),
        )
        conn.commit()


class _RBACMixin:
    def set_acl(self, tenant_id: str, username: str, resource_type: str,
                can_read: bool, can_write: bool) -> None:
        set_acl(self._get_conn(), self._lock, tenant_id, username, resource_type,
                can_read, can_write)

    def get_acl(self, tenant_id: str, username: str,
                resource_type: str) -> dict | None:
        return get_acl(self._get_read_conn(), self._read_lock, tenant_id, username,
                       resource_type)

    def list_acls(self, tenant_id: str, username: str | None = None) -> list[dict]:
        return list_acls(self._get_read_conn(), self._read_lock, tenant_id,
                         username=username)

    def delete_acl(self, tenant_id: str, username: str, resource_type: str) -> None:
        delete_acl(self._get_conn(), self._lock, tenant_id, username, resource_type)
```

- [ ] **Step 4: Run tests**

```bash
PYTHONPATH=share/noba-web pytest tests/test_rbac.py -v
```

Expected: 5 tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add share/noba-web/server/db/rbac.py tests/test_rbac.py
git commit -m "feat(rbac): resource_acls table — set/get/list/delete ACLs"
```

---

### Task 2: Register RBAC in `db/core.py`

**Files:**
- Modify: `share/noba-web/server/db/core.py`

- [ ] **Step 1: Add import and mixin**

In `share/noba-web/server/db/core.py`:

Add to the `from . import (...)` block (alphabetically):
```python
    rbac,
```

Add below the existing mixin imports:
```python
from .rbac import _RBACMixin
```

Add `rbac` to `_SCHEMA_MODULES` list (after `network`, before closing bracket):
```python
_SCHEMA_MODULES = [
    metrics, audit, automations, alerts, api_keys, tokens,
    notifications, user_dashboards, user_preferences, agents,
    endpoints, dashboards, status_page, security, dependencies,
    baselines, network, webhooks, backup_verify, healing,
    integrations, linked_providers, saml, scim, webauthn, rbac,
]
```

Add `_RBACMixin` to the `Database` class inheritance:
```python
class Database(
    DatabaseBase,
    _MetricsMixin, _AuditMixin, _AutomationsMixin, _AlertsMixin,
    _ApiKeysMixin, _TokensMixin, _NotificationsMixin, _UserDashboardsMixin,
    _UserPreferencesMixin, _AgentsMixin, _EndpointsMixin,
    _DashboardsMixin, _StatusPageMixin, _SecurityMixin, _DependenciesMixin,
    _BaselinesMixin, _WebhooksMixin, _BackupVerifyMixin,
    _ApprovalsMixin, _HealingMixin, _IntegrationsMixin, _LinkedProvidersMixin,
    _SamlMixin, _ScimMixin, _WebAuthnMixin, _TenantsMixin, _RBACMixin,
):
```

- [ ] **Step 2: Lint**

```bash
ruff check --fix share/noba-web/server/db/core.py
```

- [ ] **Step 3: Verify schema initialises**

```bash
PYTHONPATH=share/noba-web python -c "from server.db import db; print('ok')"
```

Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add share/noba-web/server/db/core.py
git commit -m "feat(rbac): register _RBACMixin in Database"
```

---

### Task 3: RBAC guard dependency in `deps.py`

**Files:**
- Modify: `share/noba-web/server/deps.py`

- [ ] **Step 1: Add `check_resource_acl` factory**

Add after the `check_tenant_quota` function (around line 272):

```python
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
```

- [ ] **Step 2: Lint**

```bash
ruff check --fix share/noba-web/server/deps.py
```

- [ ] **Step 3: Commit**

```bash
git add share/noba-web/server/deps.py
git commit -m "feat(rbac): check_resource_acl() dependency factory"
```

---

### Task 4: RBAC API endpoints in `enterprise.py`

**Files:**
- Modify: `share/noba-web/server/routers/enterprise.py`

- [ ] **Step 1: Add imports and models**

Add to existing imports at the top of `enterprise.py`:
```python
from ..db.rbac import VALID_RESOURCE_TYPES
from ..deps import check_resource_acl
```

Add Pydantic model after `TenantLimitsBody`:
```python
class AclBody(BaseModel):
    username: str
    resource_type: str
    can_read: bool = True
    can_write: bool = True
```

- [ ] **Step 2: Add RBAC endpoints**

Append to `enterprise.py` before the `_count_by` helper:

```python
# ── RBAC ACLs ────────────────────────────────────────────────────────────────

@router.get("/api/enterprise/rbac/acls")
@handle_errors
async def list_rbac_acls(
    _auth: tuple = Depends(_require_admin),
    tenant_id: str = Depends(get_tenant_id),
    username: str = Query(default=""),
):
    return db.list_acls(tenant_id, username=username or None)


@router.put("/api/enterprise/rbac/acls")
@handle_errors
async def upsert_rbac_acl(
    body: AclBody,
    _auth: tuple = Depends(_require_admin),
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
    _auth: tuple = Depends(_require_admin),
    tenant_id: str = Depends(get_tenant_id),
):
    db.delete_acl(tenant_id, username, resource_type)
    return {"ok": True}
```

- [ ] **Step 3: Lint**

```bash
ruff check --fix share/noba-web/server/routers/enterprise.py
```

- [ ] **Step 4: Commit**

```bash
git add share/noba-web/server/routers/enterprise.py
git commit -m "feat(rbac): GET/PUT/DELETE /api/enterprise/rbac/acls endpoints"
```

---

### Task 5: `RBACTab.vue` — ACL management UI

**Files:**
- Create: `share/noba-web/frontend/src/components/settings/RBACTab.vue`

- [ ] **Step 1: Create the component**

```vue
<!-- share/noba-web/frontend/src/components/settings/RBACTab.vue -->
<script setup>
import { ref, computed, onMounted } from 'vue'
import { useAuthStore } from '../../stores/auth'
import { useApi } from '../../composables/useApi'

const authStore = useAuthStore()
const { get, put, del } = useApi()

const acls = ref([])
const loading = ref(false)
const error = ref('')
const msg = ref('')

// New ACL form
const form = ref({ username: '', resource_type: 'automations', can_read: true, can_write: false })
const saving = ref(false)

const RESOURCE_TYPES = [
  'api_keys', 'audit', 'automations', 'integrations', 'users', 'webhooks',
]

async function load() {
  if (!authStore.isAdmin) return
  loading.value = true
  error.value = ''
  try {
    acls.value = await get('/api/enterprise/rbac/acls')
  } catch (e) {
    error.value = e.message || 'Failed to load ACLs'
  }
  loading.value = false
}

async function saveAcl() {
  saving.value = true
  msg.value = ''
  error.value = ''
  try {
    await put('/api/enterprise/rbac/acls', form.value)
    msg.value = 'ACL saved.'
    form.value = { username: '', resource_type: 'automations', can_read: true, can_write: false }
    await load()
  } catch (e) {
    error.value = e.message || 'Save failed'
  }
  saving.value = false
}

async function removeAcl(username, resource_type) {
  error.value = ''
  try {
    await del(`/api/enterprise/rbac/acls?username=${encodeURIComponent(username)}&resource_type=${encodeURIComponent(resource_type)}`)
    await load()
  } catch (e) {
    error.value = e.message || 'Delete failed'
  }
}

onMounted(load)
</script>

<template>
  <div>
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem">
      <h3 style="margin:0">Resource Access Control</h3>
      <button class="btn btn-sm" @click="load" :disabled="loading">
        <i class="fas fa-sync" :class="loading ? 'fa-spin' : ''"></i> Refresh
      </button>
    </div>

    <div v-if="error" class="alert alert-danger">{{ error }}</div>
    <div v-if="msg" class="alert alert-success">{{ msg }}</div>

    <!-- Add ACL form -->
    <div class="card" style="padding:1rem;margin-bottom:1rem">
      <h5 style="margin:0 0 .75rem 0">Add / Update Restriction</h5>
      <div style="display:grid;grid-template-columns:1fr 1fr auto auto auto;gap:.5rem;align-items:end">
        <div>
          <label style="font-size:.8rem;display:block;margin-bottom:.2rem">Username</label>
          <input v-model="form.username" class="form-control form-control-sm" placeholder="alice" />
        </div>
        <div>
          <label style="font-size:.8rem;display:block;margin-bottom:.2rem">Resource Type</label>
          <select v-model="form.resource_type" class="form-control form-control-sm">
            <option v-for="rt in RESOURCE_TYPES" :key="rt" :value="rt">{{ rt }}</option>
          </select>
        </div>
        <div style="text-align:center">
          <label style="font-size:.8rem;display:block;margin-bottom:.2rem">Can Read</label>
          <input type="checkbox" v-model="form.can_read" style="width:1.1rem;height:1.1rem" />
        </div>
        <div style="text-align:center">
          <label style="font-size:.8rem;display:block;margin-bottom:.2rem">Can Write</label>
          <input type="checkbox" v-model="form.can_write" style="width:1.1rem;height:1.1rem" />
        </div>
        <button class="btn btn-sm btn-primary" @click="saveAcl"
          :disabled="saving || !form.username">
          <i class="fas fa-save"></i> Save
        </button>
      </div>
      <div style="font-size:.75rem;color:var(--text-muted);margin-top:.5rem">
        No row = full access. A row with can_read=off denies all access. Admins always bypass ACLs.
      </div>
    </div>

    <!-- ACL table -->
    <div v-if="loading" style="text-align:center;padding:2rem;color:var(--text-muted)">
      <i class="fas fa-spinner fa-spin"></i>
    </div>
    <div v-else-if="acls.length" class="card" style="padding:0;overflow:hidden">
      <table class="table" style="margin:0;font-size:.85rem">
        <thead>
          <tr>
            <th>Username</th>
            <th>Resource Type</th>
            <th style="text-align:center">Read</th>
            <th style="text-align:center">Write</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in acls" :key="`${row.username}:${row.resource_type}`">
            <td><strong>{{ row.username }}</strong></td>
            <td><code>{{ row.resource_type }}</code></td>
            <td style="text-align:center">
              <i :class="row.can_read ? 'fas fa-check text-success' : 'fas fa-times text-danger'"></i>
            </td>
            <td style="text-align:center">
              <i :class="row.can_write ? 'fas fa-check text-success' : 'fas fa-times text-danger'"></i>
            </td>
            <td>
              <button class="btn btn-xs btn-danger"
                @click="removeAcl(row.username, row.resource_type)">
                <i class="fas fa-trash"></i>
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-else style="text-align:center;padding:2rem;color:var(--text-muted)">
      No restrictions configured. All users have full access within their role.
    </div>
  </div>
</template>
```

- [ ] **Step 2: Register the tab in `SettingsView.vue`**

In `share/noba-web/frontend/src/views/SettingsView.vue`, add `rbac` to the tabs array (inside the admin-only section), and add to `tabComponents`:

```js
// In the tabs computed / array — add after 'compliance':
{ id: 'rbac', label: 'Access Control', icon: 'fa-shield-alt', adminOnly: true }

// In tabComponents:
rbac: defineAsyncComponent(() => import('../components/settings/RBACTab.vue')),
```

- [ ] **Step 3: Build frontend**

```bash
cd share/noba-web/frontend && npm run build
```

Expected: build succeeds with no errors.

- [ ] **Step 4: Commit**

```bash
cd ../ && git add share/noba-web/frontend/src/components/settings/RBACTab.vue \
  share/noba-web/frontend/src/views/SettingsView.vue \
  share/noba-web/static/dist/
git commit -m "feat(rbac): RBACTab.vue — resource access control UI"
```

---

## ── FEATURE 2: Change Freeze Windows ────────────────────────────────────

### Task 6: `db/freeze.py` — schema + CRUD + active-check

**Files:**
- Create: `share/noba-web/server/db/freeze.py`
- Create: `tests/test_freeze.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_freeze.py
"""Tests for db.freeze: freeze_windows table and is_frozen logic."""
from __future__ import annotations
import sqlite3
import threading
import time
import pytest
from server.db.freeze import init_schema, add_window, list_windows, delete_window, is_frozen


@pytest.fixture()
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    lock = threading.Lock()
    init_schema(conn)
    return conn, lock


class TestFreezeWindows:
    def test_add_and_list(self, db):
        conn, lock = db
        now = int(time.time())
        add_window(conn, lock, tenant_id="default", name="Release freeze",
                   start_ts=now - 100, end_ts=now + 3600, created_by="admin",
                   reason="Planned release window")
        rows = list_windows(conn, lock, "default")
        assert len(rows) == 1
        assert rows[0]["name"] == "Release freeze"

    def test_is_frozen_true(self, db):
        conn, lock = db
        now = int(time.time())
        add_window(conn, lock, "default", "Active freeze",
                   now - 60, now + 3600, "admin", "test")
        assert is_frozen(conn, lock, "default") is True

    def test_is_frozen_false_outside_window(self, db):
        conn, lock = db
        now = int(time.time())
        add_window(conn, lock, "default", "Past freeze",
                   now - 7200, now - 3600, "admin", "expired")
        assert is_frozen(conn, lock, "default") is False

    def test_is_frozen_false_no_windows(self, db):
        conn, lock = db
        assert is_frozen(conn, lock, "default") is False

    def test_delete_window(self, db):
        conn, lock = db
        now = int(time.time())
        window_id = add_window(conn, lock, "default", "Temp",
                               now - 10, now + 60, "admin", "")
        delete_window(conn, lock, window_id)
        assert is_frozen(conn, lock, "default") is False

    def test_different_tenants_isolated(self, db):
        conn, lock = db
        now = int(time.time())
        add_window(conn, lock, "tenant-a", "Freeze A",
                   now - 60, now + 3600, "admin", "")
        assert is_frozen(conn, lock, "tenant-a") is True
        assert is_frozen(conn, lock, "tenant-b") is False
```

- [ ] **Step 2: Run to verify it fails**

```bash
PYTHONPATH=share/noba-web pytest tests/test_freeze.py -v 2>&1 | head -10
```

Expected: `ModuleNotFoundError: No module named 'server.db.freeze'`

- [ ] **Step 3: Implement `db/freeze.py`**

```python
# share/noba-web/server/db/freeze.py
"""Noba – Change freeze window DB functions."""
from __future__ import annotations

import logging
import sqlite3
import threading
import time
import uuid

logger = logging.getLogger("noba")


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS freeze_windows (
            id          TEXT PRIMARY KEY,
            tenant_id   TEXT NOT NULL DEFAULT 'default',
            name        TEXT NOT NULL,
            start_ts    INTEGER NOT NULL,
            end_ts      INTEGER NOT NULL,
            created_by  TEXT NOT NULL,
            created_at  INTEGER NOT NULL,
            reason      TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_freeze_tenant_ts
            ON freeze_windows(tenant_id, start_ts, end_ts);
    """)


def add_window(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    tenant_id: str,
    name: str,
    start_ts: int,
    end_ts: int,
    created_by: str,
    reason: str = "",
) -> str:
    """Insert a freeze window, return its id."""
    window_id = str(uuid.uuid4())
    with lock:
        conn.execute(
            "INSERT INTO freeze_windows (id, tenant_id, name, start_ts, end_ts,"
            " created_by, created_at, reason) VALUES (?,?,?,?,?,?,?,?)",
            (window_id, tenant_id, name, start_ts, end_ts,
             created_by, int(time.time()), reason),
        )
        conn.commit()
    return window_id


def list_windows(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    tenant_id: str,
) -> list[dict]:
    with lock:
        rows = conn.execute(
            "SELECT id, tenant_id, name, start_ts, end_ts, created_by, created_at, reason"
            " FROM freeze_windows WHERE tenant_id=? ORDER BY start_ts DESC",
            (tenant_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def delete_window(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    window_id: str,
) -> None:
    with lock:
        conn.execute("DELETE FROM freeze_windows WHERE id=?", (window_id,))
        conn.commit()


def is_frozen(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    tenant_id: str,
) -> bool:
    """Return True if the current time falls within any active freeze window."""
    now = int(time.time())
    with lock:
        row = conn.execute(
            "SELECT 1 FROM freeze_windows"
            " WHERE tenant_id=? AND start_ts <= ? AND end_ts >= ? LIMIT 1",
            (tenant_id, now, now),
        ).fetchone()
    return row is not None


class _FreezeMixin:
    def add_freeze_window(self, tenant_id: str, name: str, start_ts: int,
                          end_ts: int, created_by: str, reason: str = "") -> str:
        from .freeze import add_window
        return add_window(self._get_conn(), self._lock, tenant_id, name,
                          start_ts, end_ts, created_by, reason)

    def list_freeze_windows(self, tenant_id: str) -> list[dict]:
        from .freeze import list_windows
        return list_windows(self._get_read_conn(), self._read_lock, tenant_id)

    def delete_freeze_window(self, window_id: str) -> None:
        from .freeze import delete_window
        delete_window(self._get_conn(), self._lock, window_id)

    def is_frozen(self, tenant_id: str) -> bool:
        from .freeze import is_frozen
        return is_frozen(self._get_read_conn(), self._read_lock, tenant_id)
```

- [ ] **Step 4: Run tests**

```bash
PYTHONPATH=share/noba-web pytest tests/test_freeze.py -v
```

Expected: 6 tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add share/noba-web/server/db/freeze.py tests/test_freeze.py
git commit -m "feat(freeze): freeze_windows table — add/list/delete/is_frozen"
```

---

### Task 7: Register freeze in `db/core.py`

**Files:**
- Modify: `share/noba-web/server/db/core.py`

- [ ] **Step 1: Add import and mixin**

In `share/noba-web/server/db/core.py`:

Add `freeze,` to the `from . import (...)` block (alphabetically after `endpoints`).

Add mixin import:
```python
from .freeze import _FreezeMixin
```

Add `freeze` to `_SCHEMA_MODULES` after `rbac`:
```python
_SCHEMA_MODULES = [
    metrics, audit, automations, alerts, api_keys, tokens,
    notifications, user_dashboards, user_preferences, agents,
    endpoints, dashboards, status_page, security, dependencies,
    baselines, network, webhooks, backup_verify, healing,
    integrations, linked_providers, saml, scim, webauthn, rbac, freeze,
]
```

Add `_FreezeMixin` to `Database` class:
```python
class Database(
    DatabaseBase,
    _MetricsMixin, _AuditMixin, _AutomationsMixin, _AlertsMixin,
    _ApiKeysMixin, _TokensMixin, _NotificationsMixin, _UserDashboardsMixin,
    _UserPreferencesMixin, _AgentsMixin, _EndpointsMixin,
    _DashboardsMixin, _StatusPageMixin, _SecurityMixin, _DependenciesMixin,
    _BaselinesMixin, _WebhooksMixin, _BackupVerifyMixin,
    _ApprovalsMixin, _HealingMixin, _IntegrationsMixin, _LinkedProvidersMixin,
    _SamlMixin, _ScimMixin, _WebAuthnMixin, _TenantsMixin,
    _RBACMixin, _FreezeMixin,
):
```

- [ ] **Step 2: Lint + smoke test**

```bash
ruff check --fix share/noba-web/server/db/core.py
PYTHONPATH=share/noba-web python -c "from server.db import db; print(db.is_frozen('default'))"
```

Expected: `False`

- [ ] **Step 3: Commit**

```bash
git add share/noba-web/server/db/core.py
git commit -m "feat(freeze): register _FreezeMixin in Database"
```

---

### Task 8: `check_not_frozen` dependency + wire into automations

**Files:**
- Modify: `share/noba-web/server/deps.py`
- Modify: `share/noba-web/server/routers/automations.py`

- [ ] **Step 1: Add `check_not_frozen` to `deps.py`**

Add after `check_resource_acl`:

```python
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
```

- [ ] **Step 2: Wire into automation create/update/delete**

In `share/noba-web/server/routers/automations.py`, add `check_not_frozen` to the import from `..deps`:

```python
from ..deps import (
    _get_auth, _require_operator, _require_admin,
    check_tenant_quota, get_tenant_id, handle_errors,
    check_not_frozen,
)
```

Add `_frozen=Depends(check_not_frozen)` to the three mutating endpoints:

```python
# api_automations_create (line ~126):
async def api_automations_create(
    request: Request,
    auth=Depends(_require_operator),
    tenant_id: str = Depends(get_tenant_id),
    _frozen=Depends(check_not_frozen),
):

# api_automations_update (line ~158):
async def api_automations_update(
    auto_id: str,
    request: Request,
    auth=Depends(_require_operator),
    _frozen=Depends(check_not_frozen),
):

# api_automations_delete (line ~191):
async def api_automations_delete(
    auto_id: str,
    auth=Depends(_require_operator),
    _frozen=Depends(check_not_frozen),
):
```

Find the webhook create endpoint (`api_webhooks_create`) and add `_frozen=Depends(check_not_frozen)` there as well.

- [ ] **Step 3: Lint**

```bash
ruff check --fix share/noba-web/server/deps.py share/noba-web/server/routers/automations.py
```

- [ ] **Step 4: Commit**

```bash
git add share/noba-web/server/deps.py share/noba-web/server/routers/automations.py
git commit -m "feat(freeze): check_not_frozen dependency; wire into automation+webhook writes"
```

---

### Task 9: Freeze Window API endpoints

**Files:**
- Modify: `share/noba-web/server/routers/enterprise.py`

- [ ] **Step 1: Add Pydantic model and endpoints**

Add `FreezeWindowBody` model after `AclBody`:

```python
class FreezeWindowBody(BaseModel):
    name: str
    start_ts: int
    end_ts: int
    reason: str = ""
```

Append endpoints in the enterprise router (before `_count_by`):

```python
# ── Change Freeze Windows ─────────────────────────────────────────────────────

@router.get("/api/enterprise/freeze-windows")
@handle_errors
async def list_freeze_windows(
    _auth: tuple = Depends(_require_admin),
    tenant_id: str = Depends(get_tenant_id),
):
    return db.list_freeze_windows(tenant_id)


@router.post("/api/enterprise/freeze-windows")
@handle_errors
async def create_freeze_window(
    body: FreezeWindowBody,
    auth: tuple = Depends(_require_admin),
    tenant_id: str = Depends(get_tenant_id),
):
    if body.end_ts <= body.start_ts:
        raise HTTPException(status_code=422, detail="end_ts must be after start_ts")
    username, _ = auth
    window_id = db.add_freeze_window(
        tenant_id, body.name, body.start_ts, body.end_ts, username, body.reason
    )
    return {"ok": True, "id": window_id}


@router.delete("/api/enterprise/freeze-windows/{window_id}")
@handle_errors
async def delete_freeze_window(
    window_id: str,
    _auth: tuple = Depends(_require_admin),
):
    db.delete_freeze_window(window_id)
    return {"ok": True}


@router.get("/api/enterprise/freeze-windows/status")
@handle_errors
async def freeze_window_status(
    _auth: tuple = Depends(_get_auth),
    tenant_id: str = Depends(get_tenant_id),
):
    """Lightweight status check — used by UI to show freeze banner."""
    return {"frozen": db.is_frozen(tenant_id)}
```

Note: `_get_auth` must be imported in enterprise.py. Add to the `from ..deps import` line:
```python
from ..deps import _require_admin, get_tenant_id, db, handle_errors, _get_auth
```

- [ ] **Step 2: Lint**

```bash
ruff check --fix share/noba-web/server/routers/enterprise.py
```

- [ ] **Step 3: Commit**

```bash
git add share/noba-web/server/routers/enterprise.py
git commit -m "feat(freeze): GET/POST/DELETE /api/enterprise/freeze-windows endpoints"
```

---

### Task 10: `FreezeTab.vue` — freeze window UI

**Files:**
- Create: `share/noba-web/frontend/src/components/settings/FreezeTab.vue`

- [ ] **Step 1: Create the component**

```vue
<!-- share/noba-web/frontend/src/components/settings/FreezeTab.vue -->
<script setup>
import { ref, onMounted } from 'vue'
import { useAuthStore } from '../../stores/auth'
import { useApi } from '../../composables/useApi'

const authStore = useAuthStore()
const { get, post, del } = useApi()

const windows = ref([])
const frozen = ref(false)
const loading = ref(false)
const error = ref('')
const msg = ref('')

// Form state
const form = ref({ name: '', reason: '', start_iso: '', end_iso: '' })
const saving = ref(false)

function isoToTs(iso) {
  return iso ? Math.floor(new Date(iso).getTime() / 1000) : 0
}
function formatTs(ts) {
  return ts ? new Date(ts * 1000).toLocaleString() : '—'
}
function isActive(w) {
  const now = Math.floor(Date.now() / 1000)
  return w.start_ts <= now && w.end_ts >= now
}

async function load() {
  if (!authStore.isAdmin) return
  loading.value = true
  error.value = ''
  try {
    windows.value = await get('/api/enterprise/freeze-windows')
    const status = await get('/api/enterprise/freeze-windows/status')
    frozen.value = status.frozen
  } catch (e) {
    error.value = e.message || 'Failed to load'
  }
  loading.value = false
}

async function createWindow() {
  saving.value = true
  msg.value = ''
  error.value = ''
  try {
    const start_ts = isoToTs(form.value.start_iso)
    const end_ts = isoToTs(form.value.end_iso)
    await post('/api/enterprise/freeze-windows', {
      name: form.value.name,
      start_ts,
      end_ts,
      reason: form.value.reason,
    })
    msg.value = 'Freeze window created.'
    form.value = { name: '', reason: '', start_iso: '', end_iso: '' }
    await load()
  } catch (e) {
    error.value = e.message || 'Create failed'
  }
  saving.value = false
}

async function removeWindow(id) {
  error.value = ''
  try {
    await del(`/api/enterprise/freeze-windows/${id}`)
    await load()
  } catch (e) {
    error.value = e.message || 'Delete failed'
  }
}

onMounted(load)
</script>

<template>
  <div>
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem">
      <h3 style="margin:0">Change Freeze Windows</h3>
      <button class="btn btn-sm" @click="load" :disabled="loading">
        <i class="fas fa-sync" :class="loading ? 'fa-spin' : ''"></i> Refresh
      </button>
    </div>

    <!-- Freeze status banner -->
    <div v-if="frozen" class="alert"
         style="background:var(--warning,#ff9800);color:#fff;font-weight:600;margin-bottom:1rem">
      <i class="fas fa-lock" style="margin-right:.5rem"></i>
      FREEZE ACTIVE — operator writes are currently locked.
    </div>

    <div v-if="error" class="alert alert-danger">{{ error }}</div>
    <div v-if="msg" class="alert alert-success">{{ msg }}</div>

    <!-- Create form -->
    <div class="card" style="padding:1rem;margin-bottom:1rem">
      <h5 style="margin:0 0 .75rem 0">Schedule Freeze Window</h5>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:.5rem">
        <div>
          <label style="font-size:.8rem;display:block;margin-bottom:.2rem">Name</label>
          <input v-model="form.name" class="form-control form-control-sm" placeholder="Release freeze" />
        </div>
        <div>
          <label style="font-size:.8rem;display:block;margin-bottom:.2rem">Reason (optional)</label>
          <input v-model="form.reason" class="form-control form-control-sm" placeholder="v2.5 release window" />
        </div>
        <div>
          <label style="font-size:.8rem;display:block;margin-bottom:.2rem">Start</label>
          <input v-model="form.start_iso" type="datetime-local" class="form-control form-control-sm" />
        </div>
        <div>
          <label style="font-size:.8rem;display:block;margin-bottom:.2rem">End</label>
          <input v-model="form.end_iso" type="datetime-local" class="form-control form-control-sm" />
        </div>
      </div>
      <button class="btn btn-sm btn-primary"
        style="margin-top:.75rem"
        @click="createWindow"
        :disabled="saving || !form.name || !form.start_iso || !form.end_iso">
        <i class="fas fa-lock"></i> Schedule Freeze
      </button>
    </div>

    <!-- Windows table -->
    <div v-if="loading" style="text-align:center;padding:2rem;color:var(--text-muted)">
      <i class="fas fa-spinner fa-spin"></i>
    </div>
    <div v-else-if="windows.length" class="card" style="padding:0;overflow:hidden">
      <table class="table" style="margin:0;font-size:.85rem">
        <thead>
          <tr>
            <th>Name</th>
            <th>Start</th>
            <th>End</th>
            <th>Status</th>
            <th>Created By</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="w in windows" :key="w.id">
            <td>
              <strong>{{ w.name }}</strong>
              <div v-if="w.reason" style="font-size:.75rem;color:var(--text-muted)">{{ w.reason }}</div>
            </td>
            <td style="font-size:.8rem;color:var(--text-muted)">{{ formatTs(w.start_ts) }}</td>
            <td style="font-size:.8rem;color:var(--text-muted)">{{ formatTs(w.end_ts) }}</td>
            <td>
              <span v-if="isActive(w)" class="badge" style="background:var(--warning,#ff9800)">Active</span>
              <span v-else-if="w.end_ts < Date.now() / 1000" class="badge" style="background:var(--text-muted)">Expired</span>
              <span v-else class="badge" style="background:var(--info,#2196f3)">Scheduled</span>
            </td>
            <td style="font-size:.8rem">{{ w.created_by }}</td>
            <td>
              <button class="btn btn-xs btn-danger" @click="removeWindow(w.id)">
                <i class="fas fa-trash"></i>
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-else style="text-align:center;padding:2rem;color:var(--text-muted)">
      No freeze windows configured.
    </div>
  </div>
</template>
```

- [ ] **Step 2: Register in `SettingsView.vue`**

```js
// tabs array:
{ id: 'freeze', label: 'Freeze Windows', icon: 'fa-snowflake', adminOnly: true }

// tabComponents:
freeze: defineAsyncComponent(() => import('../components/settings/FreezeTab.vue')),
```

- [ ] **Step 3: Build frontend**

```bash
cd share/noba-web/frontend && npm run build
```

- [ ] **Step 4: Commit**

```bash
cd ../ && git add share/noba-web/frontend/src/components/settings/FreezeTab.vue \
  share/noba-web/frontend/src/views/SettingsView.vue \
  share/noba-web/static/dist/
git commit -m "feat(freeze): FreezeTab.vue — schedule and manage change freeze windows"
```

---

## ── FEATURE 3: Secrets Vault ─────────────────────────────────────────────

### Task 11: `db/vault.py` — schema + AES-256-GCM encrypt/decrypt

**Files:**
- Create: `share/noba-web/server/db/vault.py`
- Create: `tests/test_vault.py`

The vault uses AES-256-GCM with a key derived from an admin-set passphrase in `config.yaml` (`vaultPassphrase`). If no passphrase is configured, a random 32-byte key is auto-generated and stored as a hex string in `config.yaml` on first use. Encrypted values are stored as `base64(salt[16] + nonce[12] + ciphertext + tag[16])`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_vault.py
"""Tests for db.vault: AES-256-GCM encrypt/decrypt and secret CRUD."""
from __future__ import annotations
import sqlite3
import threading
import pytest
from server.db.vault import (
    init_schema, derive_key, encrypt_value, decrypt_value,
    store_secret, get_secret, list_secrets, delete_secret,
)

TEST_PASSPHRASE = "test-passphrase-for-unit-tests"


@pytest.fixture()
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    lock = threading.Lock()
    init_schema(conn)
    return conn, lock


class TestEncryption:
    def test_encrypt_decrypt_round_trip(self):
        key = derive_key(TEST_PASSPHRASE)
        ciphertext = encrypt_value(key, "super-secret-value")
        assert decrypt_value(key, ciphertext) == "super-secret-value"

    def test_different_encryptions_of_same_value_differ(self):
        key = derive_key(TEST_PASSPHRASE)
        c1 = encrypt_value(key, "value")
        c2 = encrypt_value(key, "value")
        assert c1 != c2  # random salt + nonce

    def test_wrong_key_raises(self):
        key1 = derive_key("passphrase-1")
        key2 = derive_key("passphrase-2")
        ciphertext = encrypt_value(key1, "secret")
        with pytest.raises(Exception):
            decrypt_value(key2, ciphertext)

    def test_derive_key_is_32_bytes(self):
        key = derive_key(TEST_PASSPHRASE)
        assert len(key) == 32


class TestVaultCRUD:
    def test_store_and_retrieve(self, db):
        conn, lock = db
        key = derive_key(TEST_PASSPHRASE)
        store_secret(conn, lock, "default", "db-password", "s3cr3t", key)
        row = get_secret(conn, lock, "default", "db-password")
        assert row is not None
        assert decrypt_value(key, row["encrypted_value"]) == "s3cr3t"

    def test_list_shows_names_only(self, db):
        conn, lock = db
        key = derive_key(TEST_PASSPHRASE)
        store_secret(conn, lock, "default", "key-a", "val-a", key)
        store_secret(conn, lock, "default", "key-b", "val-b", key)
        rows = list_secrets(conn, lock, "default")
        assert len(rows) == 2
        assert all("encrypted_value" not in r for r in rows)
        assert {r["name"] for r in rows} == {"key-a", "key-b"}

    def test_tenant_isolation(self, db):
        conn, lock = db
        key = derive_key(TEST_PASSPHRASE)
        store_secret(conn, lock, "t1", "secret", "value-t1", key)
        store_secret(conn, lock, "t2", "secret", "value-t2", key)
        assert list_secrets(conn, lock, "t1") == [{"name": "secret", "tenant_id": "t1"}]

    def test_delete_secret(self, db):
        conn, lock = db
        key = derive_key(TEST_PASSPHRASE)
        store_secret(conn, lock, "default", "temp", "value", key)
        delete_secret(conn, lock, "default", "temp")
        assert get_secret(conn, lock, "default", "temp") is None

    def test_upsert_overwrites(self, db):
        conn, lock = db
        key = derive_key(TEST_PASSPHRASE)
        store_secret(conn, lock, "default", "pw", "old", key)
        store_secret(conn, lock, "default", "pw", "new", key)
        row = get_secret(conn, lock, "default", "pw")
        assert decrypt_value(key, row["encrypted_value"]) == "new"
```

- [ ] **Step 2: Run to verify it fails**

```bash
PYTHONPATH=share/noba-web pytest tests/test_vault.py -v 2>&1 | head -10
```

Expected: `ModuleNotFoundError: No module named 'server.db.vault'`

- [ ] **Step 3: Implement `db/vault.py`**

```python
# share/noba-web/server/db/vault.py
"""Noba – Secrets vault: AES-256-GCM encryption + DB CRUD."""
from __future__ import annotations

import base64
import logging
import os
import sqlite3
import threading
import time

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

logger = logging.getLogger("noba")

_PBKDF2_ITERATIONS = 600_000


def derive_key(passphrase: str) -> bytes:
    """Derive a 32-byte AES-256 key from *passphrase* using PBKDF2-HMAC-SHA256.

    The passphrase acts as both password and a fixed salt prefix so that the
    same passphrase always produces the same key (no per-key salt here — the
    per-value randomness lives in the encryption nonce + salt stored with the
    ciphertext).
    """
    salt = b"noba-vault-v1" + passphrase.encode()[:16].ljust(16, b"\x00")
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=_PBKDF2_ITERATIONS,
    )
    return kdf.derive(passphrase.encode())


def encrypt_value(key: bytes, plaintext: str) -> str:
    """AES-256-GCM encrypt *plaintext*. Returns base64(nonce[12] + ciphertext+tag)."""
    nonce = os.urandom(12)
    aesgcm = AESGCM(key)
    ct_and_tag = aesgcm.encrypt(nonce, plaintext.encode(), None)
    return base64.b64encode(nonce + ct_and_tag).decode()


def decrypt_value(key: bytes, blob: str) -> str:
    """AES-256-GCM decrypt *blob* produced by encrypt_value. Raises on wrong key/tamper."""
    raw = base64.b64decode(blob)
    nonce, ct_and_tag = raw[:12], raw[12:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ct_and_tag, None).decode()


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS vault_secrets (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id   TEXT NOT NULL DEFAULT 'default',
            name        TEXT NOT NULL,
            encrypted_value TEXT NOT NULL,
            created_at  INTEGER NOT NULL,
            updated_at  INTEGER NOT NULL,
            UNIQUE(tenant_id, name)
        );
        CREATE INDEX IF NOT EXISTS idx_vault_tenant
            ON vault_secrets(tenant_id);
    """)


def store_secret(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    tenant_id: str,
    name: str,
    plaintext: str,
    key: bytes,
) -> None:
    """Encrypt *plaintext* and upsert into vault_secrets."""
    encrypted = encrypt_value(key, plaintext)
    now = int(time.time())
    with lock:
        conn.execute(
            "INSERT INTO vault_secrets (tenant_id, name, encrypted_value, created_at, updated_at)"
            " VALUES (?,?,?,?,?)"
            " ON CONFLICT(tenant_id, name)"
            " DO UPDATE SET encrypted_value=excluded.encrypted_value, updated_at=excluded.updated_at",
            (tenant_id, name, encrypted, now, now),
        )
        conn.commit()


def get_secret(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    tenant_id: str,
    name: str,
) -> dict | None:
    """Return the raw DB row (including encrypted_value) for a single secret."""
    with lock:
        row = conn.execute(
            "SELECT tenant_id, name, encrypted_value, created_at, updated_at"
            " FROM vault_secrets WHERE tenant_id=? AND name=?",
            (tenant_id, name),
        ).fetchone()
    return dict(row) if row else None


def list_secrets(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    tenant_id: str,
) -> list[dict]:
    """Return secret names only — never exposes encrypted_value."""
    with lock:
        rows = conn.execute(
            "SELECT tenant_id, name FROM vault_secrets"
            " WHERE tenant_id=? ORDER BY name",
            (tenant_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def delete_secret(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    tenant_id: str,
    name: str,
) -> None:
    with lock:
        conn.execute(
            "DELETE FROM vault_secrets WHERE tenant_id=? AND name=?",
            (tenant_id, name),
        )
        conn.commit()


def _get_vault_key() -> bytes:
    """Resolve the vault encryption key.

    Reads ``vaultPassphrase`` from config.yaml. If absent, auto-generates a
    random hex passphrase and persists it back so the key is stable across
    restarts.
    """
    from ..yaml_config import read_yaml_settings, write_yaml_settings
    cfg = read_yaml_settings()
    passphrase = cfg.get("vaultPassphrase", "")
    if not passphrase:
        passphrase = os.urandom(32).hex()
        write_yaml_settings({"vaultPassphrase": passphrase})
        logger.info("vault: auto-generated vaultPassphrase and saved to config")
    return derive_key(passphrase)


class _VaultMixin:
    def vault_store(self, tenant_id: str, name: str, plaintext: str) -> None:
        store_secret(self._get_conn(), self._lock, tenant_id, name, plaintext,
                     _get_vault_key())

    def vault_list(self, tenant_id: str) -> list[dict]:
        return list_secrets(self._get_read_conn(), self._read_lock, tenant_id)

    def vault_get_plaintext(self, tenant_id: str, name: str) -> str | None:
        row = get_secret(self._get_read_conn(), self._read_lock, tenant_id, name)
        if row is None:
            return None
        return decrypt_value(_get_vault_key(), row["encrypted_value"])

    def vault_delete(self, tenant_id: str, name: str) -> None:
        delete_secret(self._get_conn(), self._lock, tenant_id, name)
```

- [ ] **Step 4: Run tests**

```bash
PYTHONPATH=share/noba-web pytest tests/test_vault.py -v
```

Expected: 9 tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add share/noba-web/server/db/vault.py tests/test_vault.py
git commit -m "feat(vault): AES-256-GCM secrets vault — encrypt/decrypt + CRUD"
```

---

### Task 12: Register vault in `db/core.py`

**Files:**
- Modify: `share/noba-web/server/db/core.py`

- [ ] **Step 1: Add import and mixin**

Add `vault,` to the `from . import (...)` block.

Add:
```python
from .vault import _VaultMixin
```

Add `vault` to `_SCHEMA_MODULES`:
```python
_SCHEMA_MODULES = [
    metrics, audit, automations, alerts, api_keys, tokens,
    notifications, user_dashboards, user_preferences, agents,
    endpoints, dashboards, status_page, security, dependencies,
    baselines, network, webhooks, backup_verify, healing,
    integrations, linked_providers, saml, scim, webauthn,
    rbac, freeze, vault,
]
```

Add `_VaultMixin` to `Database`:
```python
class Database(
    DatabaseBase,
    _MetricsMixin, _AuditMixin, _AutomationsMixin, _AlertsMixin,
    _ApiKeysMixin, _TokensMixin, _NotificationsMixin, _UserDashboardsMixin,
    _UserPreferencesMixin, _AgentsMixin, _EndpointsMixin,
    _DashboardsMixin, _StatusPageMixin, _SecurityMixin, _DependenciesMixin,
    _BaselinesMixin, _WebhooksMixin, _BackupVerifyMixin,
    _ApprovalsMixin, _HealingMixin, _IntegrationsMixin, _LinkedProvidersMixin,
    _SamlMixin, _ScimMixin, _WebAuthnMixin, _TenantsMixin,
    _RBACMixin, _FreezeMixin, _VaultMixin,
):
```

- [ ] **Step 2: Lint + smoke test**

```bash
ruff check --fix share/noba-web/server/db/core.py
PYTHONPATH=share/noba-web python -c "from server.db import db; print(db.vault_list('default'))"
```

Expected: `[]`

- [ ] **Step 3: Commit**

```bash
git add share/noba-web/server/db/core.py
git commit -m "feat(vault): register _VaultMixin in Database"
```

---

### Task 13: Vault API endpoints

**Files:**
- Modify: `share/noba-web/server/routers/enterprise.py`

- [ ] **Step 1: Add Pydantic model and endpoints**

Add model after `FreezeWindowBody`:
```python
class VaultSecretBody(BaseModel):
    name: str
    value: str
```

Append endpoints (before `_count_by`):

```python
# ── Secrets Vault ─────────────────────────────────────────────────────────────

@router.get("/api/enterprise/vault/secrets")
@handle_errors
async def list_vault_secrets(
    _auth: tuple = Depends(_require_admin),
    tenant_id: str = Depends(get_tenant_id),
):
    """Return secret names only — values are never sent to the client."""
    return db.vault_list(tenant_id)


@router.post("/api/enterprise/vault/secrets")
@handle_errors
async def create_vault_secret(
    body: VaultSecretBody,
    _auth: tuple = Depends(_require_admin),
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
    _auth: tuple = Depends(_require_admin),
    tenant_id: str = Depends(get_tenant_id),
):
    db.vault_delete(tenant_id, name)
    return {"ok": True}
```

- [ ] **Step 2: Lint**

```bash
ruff check --fix share/noba-web/server/routers/enterprise.py
```

- [ ] **Step 3: Commit**

```bash
git add share/noba-web/server/routers/enterprise.py
git commit -m "feat(vault): GET/POST/DELETE /api/enterprise/vault/secrets endpoints"
```

---

### Task 14: `VaultTab.vue` — secrets vault UI

**Files:**
- Create: `share/noba-web/frontend/src/components/settings/VaultTab.vue`

- [ ] **Step 1: Create the component**

```vue
<!-- share/noba-web/frontend/src/components/settings/VaultTab.vue -->
<script setup>
import { ref, onMounted } from 'vue'
import { useAuthStore } from '../../stores/auth'
import { useApi } from '../../composables/useApi'

const authStore = useAuthStore()
const { get, post, del } = useApi()

const secrets = ref([])
const loading = ref(false)
const error = ref('')
const msg = ref('')

const form = ref({ name: '', value: '' })
const saving = ref(false)

async function load() {
  if (!authStore.isAdmin) return
  loading.value = true
  error.value = ''
  try {
    secrets.value = await get('/api/enterprise/vault/secrets')
  } catch (e) {
    error.value = e.message || 'Failed to load secrets'
  }
  loading.value = false
}

async function saveSecret() {
  saving.value = true
  msg.value = ''
  error.value = ''
  try {
    await post('/api/enterprise/vault/secrets', form.value)
    msg.value = `Secret "${form.value.name}" stored.`
    form.value = { name: '', value: '' }
    await load()
  } catch (e) {
    error.value = e.message || 'Save failed'
  }
  saving.value = false
}

async function removeSecret(name) {
  error.value = ''
  try {
    await del(`/api/enterprise/vault/secrets/${encodeURIComponent(name)}`)
    await load()
  } catch (e) {
    error.value = e.message || 'Delete failed'
  }
}

onMounted(load)
</script>

<template>
  <div>
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem">
      <h3 style="margin:0">Secrets Vault</h3>
      <button class="btn btn-sm" @click="load" :disabled="loading">
        <i class="fas fa-sync" :class="loading ? 'fa-spin' : ''"></i> Refresh
      </button>
    </div>

    <div class="alert" style="background:var(--surface-2);border:1px solid var(--border);font-size:.83rem;margin-bottom:1rem">
      <i class="fas fa-info-circle" style="margin-right:.4rem"></i>
      Secrets are encrypted at rest with AES-256-GCM. Values are <strong>never</strong> returned by the API — only names are listed.
    </div>

    <div v-if="error" class="alert alert-danger">{{ error }}</div>
    <div v-if="msg" class="alert alert-success">{{ msg }}</div>

    <!-- Add secret form -->
    <div class="card" style="padding:1rem;margin-bottom:1rem">
      <h5 style="margin:0 0 .75rem 0">Add / Overwrite Secret</h5>
      <div style="display:grid;grid-template-columns:1fr 1fr auto;gap:.5rem;align-items:end">
        <div>
          <label style="font-size:.8rem;display:block;margin-bottom:.2rem">Name</label>
          <input v-model="form.name" class="form-control form-control-sm"
            placeholder="db-password" />
        </div>
        <div>
          <label style="font-size:.8rem;display:block;margin-bottom:.2rem">Value</label>
          <input v-model="form.value" type="password" class="form-control form-control-sm"
            placeholder="••••••••" autocomplete="new-password" />
        </div>
        <button class="btn btn-sm btn-primary" @click="saveSecret"
          :disabled="saving || !form.name || !form.value">
          <i class="fas fa-lock"></i> Store
        </button>
      </div>
      <div style="font-size:.75rem;color:var(--text-muted);margin-top:.5rem">
        Name: alphanumeric, dashes, underscores only. Storing a secret with an existing name overwrites it.
      </div>
    </div>

    <!-- Secrets list -->
    <div v-if="loading" style="text-align:center;padding:2rem;color:var(--text-muted)">
      <i class="fas fa-spinner fa-spin"></i>
    </div>
    <div v-else-if="secrets.length" class="card" style="padding:0;overflow:hidden">
      <table class="table" style="margin:0;font-size:.85rem">
        <thead>
          <tr>
            <th>Name</th>
            <th>Value</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="s in secrets" :key="s.name">
            <td><strong><code>{{ s.name }}</code></strong></td>
            <td style="color:var(--text-muted);font-size:.8rem">
              <i class="fas fa-lock" style="margin-right:.3rem"></i>encrypted
            </td>
            <td>
              <button class="btn btn-xs btn-danger" @click="removeSecret(s.name)">
                <i class="fas fa-trash"></i>
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-else style="text-align:center;padding:2rem;color:var(--text-muted)">
      No secrets stored.
    </div>
  </div>
</template>
```

- [ ] **Step 2: Register in `SettingsView.vue`**

```js
// tabs array:
{ id: 'vault', label: 'Secrets Vault', icon: 'fa-vault', adminOnly: true }

// tabComponents:
vault: defineAsyncComponent(() => import('../components/settings/VaultTab.vue')),
```

- [ ] **Step 3: Build frontend**

```bash
cd share/noba-web/frontend && npm run build
```

- [ ] **Step 4: Commit**

```bash
cd ../ && git add share/noba-web/frontend/src/components/settings/VaultTab.vue \
  share/noba-web/frontend/src/views/SettingsView.vue \
  share/noba-web/static/dist/
git commit -m "feat(vault): VaultTab.vue — encrypted secrets management UI"
```

---

### Task 15: Run full test suite + push

- [ ] **Step 1: Backend tests**

```bash
cd /home/raizen/noba/.worktrees/enterprise-v2
PYTHONPATH=share/noba-web pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: no failures.

- [ ] **Step 2: Frontend tests**

```bash
cd share/noba-web/frontend && npm test -- --run
```

Expected: all tests pass.

- [ ] **Step 3: Lint check**

```bash
ruff check share/noba-web/server/
```

Expected: `All checks passed!`

- [ ] **Step 4: Push**

```bash
cd /home/raizen/noba/.worktrees/enterprise-v2
git push enterprise HEAD:main
git push origin enterprise-v2
```

- [ ] **Step 5: Verify CI goes green**

```bash
sleep 120 && gh run list --repo raizenica/noba-enterprise --limit 2
```

Expected: latest CI Tests run = `success`.
