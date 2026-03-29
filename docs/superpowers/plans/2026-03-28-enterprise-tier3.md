# Enterprise Tier 3 — Operational Security & Lifecycle

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add five enterprise operational security features: configurable password policies, admin session management, tenant-scoped login IP allowlists, configurable data retention policies, and outbound webhook HMAC signing.

**Architecture:** Each feature follows the established enterprise pattern: DB module (`db/<feature>.py`) with `_*Mixin` registered in `core.py`, router endpoints in `routers/enterprise.py`, and Vue 3 settings tab. Password policies and session management modify existing `auth.py` and `routers/auth.py`. Data retention extends existing `prune_*` functions with configurable per-tenant policies. Webhook signing hooks into `_do_http_request` in `workflow_engine.py`.

**Tech Stack:** FastAPI, SQLite/PostgreSQL, Vue 3 `<script setup>`, `useApi()` composable, `hmac` + `hashlib` (stdlib), pytest.

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `share/noba-web/server/db/password_policy.py` | `password_policies` schema, CRUD, history check, `_PasswordPolicyMixin` |
| Create | `share/noba-web/server/db/login_restrict.py` | `login_ip_allowlists` schema, CRUD, check, `_LoginRestrictMixin` |
| Create | `share/noba-web/server/db/retention.py` | `retention_policies` schema, CRUD, run-purge, `_RetentionMixin` |
| Modify | `share/noba-web/server/db/core.py` | Import + register 3 new mixins; add to `_SCHEMA_MODULES` |
| Modify | `share/noba-web/server/auth.py` | Use password policy in `check_password_strength`; add password history tracking |
| Modify | `share/noba-web/server/routers/auth.py` | Enforce login IP allowlist; add admin session management endpoints |
| Modify | `share/noba-web/server/routers/enterprise.py` | Password policy, login IP, retention, webhook signing CRUD endpoints |
| Modify | `share/noba-web/server/workflow_engine.py` | Add HMAC-SHA256 signing to `_do_http_request` |
| Create | `share/noba-web/frontend/src/components/settings/PasswordPolicyTab.vue` | Password policy config UI |
| Create | `share/noba-web/frontend/src/components/settings/SessionsTab.vue` | Admin session management UI |
| Create | `share/noba-web/frontend/src/components/settings/RetentionTab.vue` | Data retention policy UI |
| Modify | `share/noba-web/frontend/src/views/SettingsView.vue` | Register 3 new tabs |
| Create | `tests/test_password_policy.py` | Unit tests for password policy DB layer |
| Create | `tests/test_login_restrict.py` | Unit tests for login IP allowlist |
| Create | `tests/test_retention.py` | Unit tests for retention policy DB layer |
| Create | `tests/test_webhook_signing.py` | Unit tests for outbound HMAC signing |

---

## ── FEATURE 1: Configurable Password Policies ────────────────────────────

### Task 1: `db/password_policy.py` — schema + CRUD + history

**Files:**
- Create: `share/noba-web/server/db/password_policy.py`
- Create: `tests/test_password_policy.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_password_policy.py
"""Tests for db.password_policy: configurable password rules + history."""
from __future__ import annotations
import sqlite3
import threading
import pytest
from server.db.password_policy import (
    init_schema, get_policy, set_policy, add_password_history,
    check_password_history, DEFAULT_POLICY,
)


@pytest.fixture()
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    lock = threading.Lock()
    init_schema(conn)
    return conn, lock


class TestPasswordPolicy:
    def test_default_policy(self, db):
        conn, lock = db
        policy = get_policy(conn, lock, "default")
        assert policy["min_length"] == DEFAULT_POLICY["min_length"]
        assert policy["require_uppercase"] is True
        assert policy["max_age_days"] == 0  # 0 = no expiry

    def test_set_and_get_policy(self, db):
        conn, lock = db
        set_policy(conn, lock, "default", min_length=12, require_uppercase=True,
                   require_digit=True, require_special=True, max_age_days=90,
                   history_count=5)
        policy = get_policy(conn, lock, "default")
        assert policy["min_length"] == 12
        assert policy["max_age_days"] == 90
        assert policy["history_count"] == 5

    def test_tenant_isolation(self, db):
        conn, lock = db
        set_policy(conn, lock, "t1", min_length=16)
        set_policy(conn, lock, "t2", min_length=8)
        assert get_policy(conn, lock, "t1")["min_length"] == 16
        assert get_policy(conn, lock, "t2")["min_length"] == 8

    def test_password_history_blocks_reuse(self, db):
        conn, lock = db
        set_policy(conn, lock, "default", history_count=3)
        add_password_history(conn, lock, "default", "alice", "hash1")
        add_password_history(conn, lock, "default", "alice", "hash2")
        add_password_history(conn, lock, "default", "alice", "hash3")
        assert check_password_history(conn, lock, "default", "alice", "hash2") is True
        assert check_password_history(conn, lock, "default", "alice", "hash_new") is False

    def test_password_history_respects_count(self, db):
        conn, lock = db
        set_policy(conn, lock, "default", history_count=2)
        add_password_history(conn, lock, "default", "alice", "hash1")
        add_password_history(conn, lock, "default", "alice", "hash2")
        add_password_history(conn, lock, "default", "alice", "hash3")
        # hash1 should have been evicted (only 2 kept)
        assert check_password_history(conn, lock, "default", "alice", "hash1") is False
        assert check_password_history(conn, lock, "default", "alice", "hash3") is True

    def test_zero_history_count_disables_check(self, db):
        conn, lock = db
        set_policy(conn, lock, "default", history_count=0)
        add_password_history(conn, lock, "default", "alice", "hash1")
        # With history_count=0, check always returns False (not in history)
        assert check_password_history(conn, lock, "default", "alice", "hash1") is False
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd /home/raizen/noba/.worktrees/enterprise-v2
PYTHONPATH=share/noba-web pytest tests/test_password_policy.py -v 2>&1 | head -10
```

Expected: `ModuleNotFoundError: No module named 'server.db.password_policy'`

- [ ] **Step 3: Implement `db/password_policy.py`**

```python
# share/noba-web/server/db/password_policy.py
"""Noba – Configurable password policy + password history DB functions."""
from __future__ import annotations

import logging
import sqlite3
import threading
import time

logger = logging.getLogger("noba")

DEFAULT_POLICY = {
    "min_length": 8,
    "require_uppercase": True,
    "require_digit": True,
    "require_special": False,
    "max_age_days": 0,       # 0 = no expiry
    "history_count": 0,      # 0 = no history check
}


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS password_policies (
            tenant_id       TEXT PRIMARY KEY,
            min_length      INTEGER NOT NULL DEFAULT 8,
            require_uppercase INTEGER NOT NULL DEFAULT 1,
            require_digit   INTEGER NOT NULL DEFAULT 1,
            require_special INTEGER NOT NULL DEFAULT 0,
            max_age_days    INTEGER NOT NULL DEFAULT 0,
            history_count   INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS password_history (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id   TEXT NOT NULL DEFAULT 'default',
            username    TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            created_at  INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_pw_history_user
            ON password_history(tenant_id, username, created_at DESC);
    """)


def get_policy(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    tenant_id: str,
) -> dict:
    """Return the password policy for a tenant, or defaults if none set."""
    with lock:
        row = conn.execute(
            "SELECT min_length, require_uppercase, require_digit, require_special,"
            " max_age_days, history_count"
            " FROM password_policies WHERE tenant_id=?",
            (tenant_id,),
        ).fetchone()
    if row is None:
        return dict(DEFAULT_POLICY)
    return {
        "min_length": row[0],
        "require_uppercase": bool(row[1]),
        "require_digit": bool(row[2]),
        "require_special": bool(row[3]),
        "max_age_days": row[4],
        "history_count": row[5],
    }


def set_policy(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    tenant_id: str,
    min_length: int = 8,
    require_uppercase: bool = True,
    require_digit: bool = True,
    require_special: bool = False,
    max_age_days: int = 0,
    history_count: int = 0,
) -> None:
    with lock:
        conn.execute(
            "INSERT INTO password_policies"
            " (tenant_id, min_length, require_uppercase, require_digit,"
            "  require_special, max_age_days, history_count)"
            " VALUES (?,?,?,?,?,?,?)"
            " ON CONFLICT(tenant_id)"
            " DO UPDATE SET min_length=excluded.min_length,"
            " require_uppercase=excluded.require_uppercase,"
            " require_digit=excluded.require_digit,"
            " require_special=excluded.require_special,"
            " max_age_days=excluded.max_age_days,"
            " history_count=excluded.history_count",
            (tenant_id, min_length, int(require_uppercase), int(require_digit),
             int(require_special), max_age_days, history_count),
        )
        conn.commit()


def add_password_history(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    tenant_id: str,
    username: str,
    password_hash: str,
) -> None:
    """Record a password hash and evict oldest entries beyond history_count."""
    policy = get_policy(conn, lock, tenant_id)
    now = int(time.time())
    with lock:
        conn.execute(
            "INSERT INTO password_history (tenant_id, username, password_hash, created_at)"
            " VALUES (?,?,?,?)",
            (tenant_id, username, password_hash, now),
        )
        # Evict old entries if history_count > 0
        limit = policy["history_count"]
        if limit > 0:
            conn.execute(
                "DELETE FROM password_history WHERE id NOT IN ("
                "  SELECT id FROM password_history"
                "  WHERE tenant_id=? AND username=?"
                "  ORDER BY created_at DESC LIMIT ?"
                ") AND tenant_id=? AND username=?",
                (tenant_id, username, limit, tenant_id, username),
            )
        conn.commit()


def check_password_history(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    tenant_id: str,
    username: str,
    password_hash: str,
) -> bool:
    """Return True if password_hash is in the user's recent history (reuse blocked)."""
    policy = get_policy(conn, lock, tenant_id)
    if policy["history_count"] == 0:
        return False  # history check disabled
    with lock:
        row = conn.execute(
            "SELECT 1 FROM password_history"
            " WHERE tenant_id=? AND username=? AND password_hash=? LIMIT 1",
            (tenant_id, username, password_hash),
        ).fetchone()
    return row is not None


class _PasswordPolicyMixin:
    def get_password_policy(self, tenant_id: str) -> dict:
        return get_policy(self._get_read_conn(), self._read_lock, tenant_id)

    def set_password_policy(self, tenant_id: str, **kwargs) -> None:
        set_policy(self._get_conn(), self._lock, tenant_id, **kwargs)

    def add_password_history(self, tenant_id: str, username: str, pw_hash: str) -> None:
        add_password_history(self._get_conn(), self._lock, tenant_id, username, pw_hash)

    def check_password_history(self, tenant_id: str, username: str, pw_hash: str) -> bool:
        return check_password_history(
            self._get_read_conn(), self._read_lock, tenant_id, username, pw_hash)
```

- [ ] **Step 4: Run tests**

```bash
PYTHONPATH=share/noba-web pytest tests/test_password_policy.py -v
```

Expected: 7 tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add share/noba-web/server/db/password_policy.py tests/test_password_policy.py
git commit -m "feat(password-policy): configurable password rules + history tracking"
```

---

### Task 2: Register password_policy in `db/core.py`

**Files:**
- Modify: `share/noba-web/server/db/core.py`

- [ ] **Step 1: Add import, mixin, and schema module**

In `share/noba-web/server/db/core.py`:

Add `password_policy,` to the `from . import (...)` block (alphabetically after `notifications`).

Add mixin import (alphabetically after `_NotificationsMixin`):
```python
from .password_policy import _PasswordPolicyMixin
```

Add `password_policy` to `_SCHEMA_MODULES` after `vault`:
```python
    integrations, linked_providers, saml, scim, webauthn, rbac, freeze, vault,
    password_policy,
```

Add `_PasswordPolicyMixin` to `Database` class after `_VaultMixin`:
```python
    _RBACMixin, _FreezeMixin, _VaultMixin, _PasswordPolicyMixin,
```

**IMPORTANT:** All four changes (module import, mixin import, schema module list, Database class) must be applied before running ruff, or unused imports will be stripped.

- [ ] **Step 2: Lint + smoke test**

```bash
ruff check --fix share/noba-web/server/db/core.py
PYTHONPATH=share/noba-web python3 -c "from server.db.core import Database; print('_PasswordPolicyMixin OK')"
```

Expected: `_PasswordPolicyMixin OK`

- [ ] **Step 3: Commit**

```bash
git add share/noba-web/server/db/core.py
git commit -m "feat(password-policy): register _PasswordPolicyMixin in Database"
```

---

### Task 3: Password policy API endpoints + wire into auth

**Files:**
- Modify: `share/noba-web/server/routers/enterprise.py`
- Modify: `share/noba-web/server/auth.py`
- Modify: `share/noba-web/server/routers/auth.py`

- [ ] **Step 1: Add Pydantic model and endpoints to enterprise.py**

Add model after `VaultSecretBody`:

```python
class PasswordPolicyBody(BaseModel):
    min_length: int = 8
    require_uppercase: bool = True
    require_digit: bool = True
    require_special: bool = False
    max_age_days: int = 0
    history_count: int = 0
```

Add endpoints before `_count_by`:

```python
# ── Password Policies ────────────────────────────────────────────────────────

@router.get("/api/enterprise/password-policy")
@handle_errors
async def get_password_policy(
    _auth: tuple = Depends(_require_admin),
    tenant_id: str = Depends(get_tenant_id),
):
    return db.get_password_policy(tenant_id)


@router.put("/api/enterprise/password-policy")
@handle_errors
async def set_password_policy(
    body: PasswordPolicyBody,
    _auth: tuple = Depends(_require_admin),
    tenant_id: str = Depends(get_tenant_id),
):
    if body.min_length < 6 or body.min_length > 128:
        raise HTTPException(status_code=422, detail="min_length must be between 6 and 128")
    if body.max_age_days < 0:
        raise HTTPException(status_code=422, detail="max_age_days must be >= 0")
    if body.history_count < 0 or body.history_count > 50:
        raise HTTPException(status_code=422, detail="history_count must be between 0 and 50")
    db.set_password_policy(
        tenant_id,
        min_length=body.min_length,
        require_uppercase=body.require_uppercase,
        require_digit=body.require_digit,
        require_special=body.require_special,
        max_age_days=body.max_age_days,
        history_count=body.history_count,
    )
    return {"ok": True}
```

- [ ] **Step 2: Update `check_password_strength` in auth.py to use tenant policy**

In `share/noba-web/server/auth.py`, replace the existing `check_password_strength` function:

```python
def check_password_strength(password: str, tenant_id: str = "default") -> str | None:
    """Validate password against the tenant's configured policy.

    Falls back to DEFAULT_POLICY if no tenant policy is configured.
    """
    try:
        db = _get_db()
        policy = db.get_password_policy(tenant_id)
    except Exception:
        # Fallback to hardcoded defaults if DB not ready
        from .db.password_policy import DEFAULT_POLICY
        policy = dict(DEFAULT_POLICY)

    if len(password) < policy["min_length"]:
        return f"Password must be at least {policy['min_length']} characters"
    if policy["require_uppercase"] and not re.search(r"[A-Z]", password):
        return "Password must contain at least one uppercase letter"
    if policy["require_digit"] and not re.search(r"[0-9]", password):
        return "Password must contain at least one digit"
    if policy["require_special"] and not re.search(r"[!@#$%^&*()_+\-=\[\]{};':\",./<>?\\|`~]", password):
        return "Password must contain at least one special character"
    return None
```

- [ ] **Step 3: Wire password history into the password change endpoint**

In `share/noba-web/server/routers/auth.py`, update `api_profile_password` (around line 661). After `check_password_strength` succeeds and before `update_password`, add the history check:

```python
    # Password history check
    tenant_id = db.get_user_tenant(username) or "default"
    pw_err = check_password_strength(new_pw, tenant_id=tenant_id)
    if pw_err:
        raise HTTPException(400, pw_err)
    new_hash = pbkdf2_hash(new_pw)
    if db.check_password_history(tenant_id, username, new_hash):
        raise HTTPException(400, "Password was recently used. Choose a different password.")
    if not users.update_password(username, new_hash):
        raise HTTPException(500, "Failed to update password")
    db.add_password_history(tenant_id, username, new_hash)
```

Note: `check_password_strength` now takes an optional `tenant_id` parameter. Existing callers that don't pass it will use `"default"`.

- [ ] **Step 4: Lint**

```bash
ruff check --fix share/noba-web/server/routers/enterprise.py share/noba-web/server/auth.py share/noba-web/server/routers/auth.py
```

- [ ] **Step 5: Commit**

```bash
git add share/noba-web/server/routers/enterprise.py share/noba-web/server/auth.py share/noba-web/server/routers/auth.py
git commit -m "feat(password-policy): API endpoints + wire into auth strength check and history"
```

---

### Task 4: `PasswordPolicyTab.vue`

**Files:**
- Create: `share/noba-web/frontend/src/components/settings/PasswordPolicyTab.vue`
- Modify: `share/noba-web/frontend/src/views/SettingsView.vue`

- [ ] **Step 1: Create the component**

```vue
<!-- share/noba-web/frontend/src/components/settings/PasswordPolicyTab.vue -->
<script setup>
import { ref, onMounted } from 'vue'
import { useAuthStore } from '../../stores/auth'
import { useApi } from '../../composables/useApi'

const authStore = useAuthStore()
const { get, put } = useApi()

const policy = ref({
  min_length: 8, require_uppercase: true, require_digit: true,
  require_special: false, max_age_days: 0, history_count: 0,
})
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const msg = ref('')

async function load() {
  if (!authStore.isAdmin) return
  loading.value = true
  error.value = ''
  try {
    policy.value = await get('/api/enterprise/password-policy')
  } catch (e) {
    error.value = e.message || 'Failed to load policy'
  }
  loading.value = false
}

async function save() {
  saving.value = true
  msg.value = ''
  error.value = ''
  try {
    await put('/api/enterprise/password-policy', policy.value)
    msg.value = 'Password policy saved.'
  } catch (e) {
    error.value = e.message || 'Save failed'
  }
  saving.value = false
}

onMounted(load)
</script>

<template>
  <div>
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem">
      <h3 style="margin:0">Password Policy</h3>
      <button class="btn btn-sm" @click="load" :disabled="loading">
        <i class="fas fa-sync" :class="loading ? 'fa-spin' : ''"></i> Refresh
      </button>
    </div>

    <div v-if="error" class="alert alert-danger">{{ error }}</div>
    <div v-if="msg" class="alert alert-success">{{ msg }}</div>

    <div v-if="loading" style="text-align:center;padding:2rem;color:var(--text-muted)">
      <i class="fas fa-spinner fa-spin"></i>
    </div>
    <div v-else class="card" style="padding:1rem">
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem">
        <div>
          <label style="font-size:.8rem;display:block;margin-bottom:.2rem">Minimum Length</label>
          <input v-model.number="policy.min_length" type="number" min="6" max="128"
            class="form-control form-control-sm" />
        </div>
        <div>
          <label style="font-size:.8rem;display:block;margin-bottom:.2rem">Max Age (days, 0=never)</label>
          <input v-model.number="policy.max_age_days" type="number" min="0"
            class="form-control form-control-sm" />
        </div>
        <div>
          <label style="font-size:.8rem;display:block;margin-bottom:.2rem">History Count (0=disabled)</label>
          <input v-model.number="policy.history_count" type="number" min="0" max="50"
            class="form-control form-control-sm" />
        </div>
        <div></div>
        <div style="display:flex;gap:1.5rem;align-items:center">
          <label style="font-size:.85rem">
            <input type="checkbox" v-model="policy.require_uppercase" style="margin-right:.4rem" />
            Require uppercase
          </label>
        </div>
        <div style="display:flex;gap:1.5rem;align-items:center">
          <label style="font-size:.85rem">
            <input type="checkbox" v-model="policy.require_digit" style="margin-right:.4rem" />
            Require digit
          </label>
        </div>
        <div style="display:flex;gap:1.5rem;align-items:center">
          <label style="font-size:.85rem">
            <input type="checkbox" v-model="policy.require_special" style="margin-right:.4rem" />
            Require special character
          </label>
        </div>
      </div>
      <div style="margin-top:1rem;display:flex;gap:.5rem">
        <button class="btn btn-sm btn-primary" @click="save" :disabled="saving">
          <i class="fas fa-save"></i> Save Policy
        </button>
      </div>
      <div style="font-size:.75rem;color:var(--text-muted);margin-top:.75rem">
        Changes apply to new passwords immediately. Set max_age_days > 0 to enforce password rotation.
        History count prevents reuse of the N most recent passwords.
      </div>
    </div>
  </div>
</template>
```

- [ ] **Step 2: Register in SettingsView.vue**

In `share/noba-web/frontend/src/views/SettingsView.vue`:

Add to tabs array (after `vault`, before `license`):
```js
{ key: 'password-policy', label: 'Password Policy', icon: 'fa-key', admin: true },
```

Add to tabComponents:
```js
'password-policy': defineAsyncComponent(() => import('../components/settings/PasswordPolicyTab.vue')),
```

- [ ] **Step 3: Build frontend**

```bash
cd share/noba-web/frontend && npm run build
```

- [ ] **Step 4: Commit**

```bash
cd /home/raizen/noba/.worktrees/enterprise-v2
git add share/noba-web/frontend/src/components/settings/PasswordPolicyTab.vue \
  share/noba-web/frontend/src/views/SettingsView.vue \
  share/noba-web/static/dist/
git commit -m "feat(password-policy): PasswordPolicyTab.vue — configurable password rules UI"
```

---

## ── FEATURE 2: Admin Session Management ──────────────────────────────────

### Task 5: Admin session management endpoints

**Files:**
- Modify: `share/noba-web/server/routers/auth.py`

The session list and revoke primitives already exist in `auth.py` (`token_store.list_sessions()`, `token_store.revoke_by_prefix()`). We need admin endpoints to view all sessions and revoke any session.

- [ ] **Step 1: Add admin session endpoints to routers/auth.py**

Add after the existing `api_profile_sessions` endpoint (around line 686):

```python
@router.get("/api/admin/sessions")
@handle_errors
def api_admin_sessions(auth=Depends(_require_admin)):
    """List all active sessions across all users."""
    return token_store.list_sessions()


@router.delete("/api/admin/sessions/{prefix}")
@handle_errors
def api_admin_revoke_session(prefix: str, auth=Depends(_require_admin)):
    """Revoke a session by its token prefix (first 8 chars)."""
    username, _ = auth
    if not token_store.revoke_by_prefix(prefix):
        raise HTTPException(404, "Session not found or already expired")
    db.audit_log("session_revoke", username, f"Revoked session {prefix}…",
                 "admin-action")
    return {"ok": True}
```

- [ ] **Step 2: Lint**

```bash
ruff check --fix share/noba-web/server/routers/auth.py
```

- [ ] **Step 3: Commit**

```bash
git add share/noba-web/server/routers/auth.py
git commit -m "feat(sessions): admin session list + revoke endpoints"
```

---

### Task 6: `SessionsTab.vue` — admin session management UI

**Files:**
- Create: `share/noba-web/frontend/src/components/settings/SessionsTab.vue`
- Modify: `share/noba-web/frontend/src/views/SettingsView.vue`

- [ ] **Step 1: Create the component**

```vue
<!-- share/noba-web/frontend/src/components/settings/SessionsTab.vue -->
<script setup>
import { ref, onMounted } from 'vue'
import { useAuthStore } from '../../stores/auth'
import { useApi } from '../../composables/useApi'

const authStore = useAuthStore()
const { get, del } = useApi()

const sessions = ref([])
const loading = ref(false)
const error = ref('')
const msg = ref('')

async function load() {
  if (!authStore.isAdmin) return
  loading.value = true
  error.value = ''
  try {
    sessions.value = await get('/api/admin/sessions')
  } catch (e) {
    error.value = e.message || 'Failed to load sessions'
  }
  loading.value = false
}

async function revoke(prefix) {
  error.value = ''
  msg.value = ''
  try {
    await del(`/api/admin/sessions/${encodeURIComponent(prefix.replace('…', ''))}`)
    msg.value = 'Session revoked.'
    await load()
  } catch (e) {
    error.value = e.message || 'Revoke failed'
  }
}

function timeLeft(expires) {
  const diff = new Date(expires) - Date.now()
  if (diff <= 0) return 'expired'
  const h = Math.floor(diff / 3600000)
  const m = Math.floor((diff % 3600000) / 60000)
  return h > 0 ? `${h}h ${m}m` : `${m}m`
}

onMounted(load)
</script>

<template>
  <div>
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem">
      <h3 style="margin:0">Active Sessions</h3>
      <button class="btn btn-sm" @click="load" :disabled="loading">
        <i class="fas fa-sync" :class="loading ? 'fa-spin' : ''"></i> Refresh
      </button>
    </div>

    <div v-if="error" class="alert alert-danger">{{ error }}</div>
    <div v-if="msg" class="alert alert-success">{{ msg }}</div>

    <div v-if="loading" style="text-align:center;padding:2rem;color:var(--text-muted)">
      <i class="fas fa-spinner fa-spin"></i>
    </div>
    <div v-else-if="sessions.length" class="card" style="padding:0;overflow:hidden">
      <table class="table" style="margin:0;font-size:.85rem">
        <thead>
          <tr>
            <th>User</th>
            <th>Role</th>
            <th>Token</th>
            <th>Expires In</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="s in sessions" :key="s.prefix">
            <td><strong>{{ s.username }}</strong></td>
            <td><code>{{ s.role }}</code></td>
            <td style="font-family:monospace;font-size:.8rem;color:var(--text-muted)">{{ s.prefix }}</td>
            <td>{{ timeLeft(s.expires) }}</td>
            <td>
              <button class="btn btn-xs btn-danger" @click="revoke(s.prefix)">
                <i class="fas fa-times"></i> Revoke
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-else style="text-align:center;padding:2rem;color:var(--text-muted)">
      No active sessions.
    </div>
  </div>
</template>
```

- [ ] **Step 2: Register in SettingsView.vue**

Add to tabs array (after `password-policy`, before `license`):
```js
{ key: 'sessions', label: 'Sessions', icon: 'fa-clock', admin: true },
```

Add to tabComponents:
```js
sessions: defineAsyncComponent(() => import('../components/settings/SessionsTab.vue')),
```

- [ ] **Step 3: Build frontend**

```bash
cd share/noba-web/frontend && npm run build
```

- [ ] **Step 4: Commit**

```bash
cd /home/raizen/noba/.worktrees/enterprise-v2
git add share/noba-web/frontend/src/components/settings/SessionsTab.vue \
  share/noba-web/frontend/src/views/SettingsView.vue \
  share/noba-web/static/dist/
git commit -m "feat(sessions): SessionsTab.vue — admin session management UI"
```

---

## ── FEATURE 3: Login IP Allowlist ────────────────────────────────────────

### Task 7: `db/login_restrict.py` — schema + CRUD + check

**Files:**
- Create: `share/noba-web/server/db/login_restrict.py`
- Create: `tests/test_login_restrict.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_login_restrict.py
"""Tests for db.login_restrict: tenant-scoped login IP allowlists."""
from __future__ import annotations
import sqlite3
import threading
import pytest
from server.db.login_restrict import (
    init_schema, add_allowed_cidr, list_allowed_cidrs,
    delete_allowed_cidr, is_ip_allowed,
)


@pytest.fixture()
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    lock = threading.Lock()
    init_schema(conn)
    return conn, lock


class TestLoginRestrict:
    def test_no_rules_allows_all(self, db):
        conn, lock = db
        assert is_ip_allowed(conn, lock, "default", "192.168.1.100") is True

    def test_add_and_list(self, db):
        conn, lock = db
        add_allowed_cidr(conn, lock, "default", "10.0.0.0/24", "Office network")
        rows = list_allowed_cidrs(conn, lock, "default")
        assert len(rows) == 1
        assert rows[0]["cidr"] == "10.0.0.0/24"

    def test_ip_in_cidr_allowed(self, db):
        conn, lock = db
        add_allowed_cidr(conn, lock, "default", "10.0.0.0/24", "")
        assert is_ip_allowed(conn, lock, "default", "10.0.0.50") is True

    def test_ip_outside_cidr_blocked(self, db):
        conn, lock = db
        add_allowed_cidr(conn, lock, "default", "10.0.0.0/24", "")
        assert is_ip_allowed(conn, lock, "default", "192.168.1.1") is False

    def test_multiple_cidrs(self, db):
        conn, lock = db
        add_allowed_cidr(conn, lock, "default", "10.0.0.0/24", "")
        add_allowed_cidr(conn, lock, "default", "172.16.0.0/16", "")
        assert is_ip_allowed(conn, lock, "default", "172.16.5.10") is True
        assert is_ip_allowed(conn, lock, "default", "8.8.8.8") is False

    def test_single_ip_cidr(self, db):
        conn, lock = db
        add_allowed_cidr(conn, lock, "default", "203.0.113.5/32", "VPN exit")
        assert is_ip_allowed(conn, lock, "default", "203.0.113.5") is True
        assert is_ip_allowed(conn, lock, "default", "203.0.113.6") is False

    def test_delete_cidr(self, db):
        conn, lock = db
        cid = add_allowed_cidr(conn, lock, "default", "10.0.0.0/8", "")
        delete_allowed_cidr(conn, lock, cid)
        assert is_ip_allowed(conn, lock, "default", "10.0.0.1") is True  # no rules = allow all

    def test_tenant_isolation(self, db):
        conn, lock = db
        add_allowed_cidr(conn, lock, "t1", "10.0.0.0/24", "")
        assert is_ip_allowed(conn, lock, "t1", "10.0.0.1") is True
        assert is_ip_allowed(conn, lock, "t1", "192.168.1.1") is False
        # t2 has no rules — all allowed
        assert is_ip_allowed(conn, lock, "t2", "192.168.1.1") is True
```

- [ ] **Step 2: Run to verify it fails**

```bash
PYTHONPATH=share/noba-web pytest tests/test_login_restrict.py -v 2>&1 | head -10
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement `db/login_restrict.py`**

```python
# share/noba-web/server/db/login_restrict.py
"""Noba – Tenant-scoped login IP allowlists."""
from __future__ import annotations

import ipaddress
import logging
import sqlite3
import threading

logger = logging.getLogger("noba")


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS login_ip_allowlists (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id   TEXT NOT NULL DEFAULT 'default',
            cidr        TEXT NOT NULL,
            label       TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_login_ip_tenant
            ON login_ip_allowlists(tenant_id);
    """)


def add_allowed_cidr(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    tenant_id: str,
    cidr: str,
    label: str = "",
) -> int:
    """Add a CIDR to the allowlist. Returns the row id."""
    # Validate CIDR
    ipaddress.ip_network(cidr, strict=False)
    with lock:
        cur = conn.execute(
            "INSERT INTO login_ip_allowlists (tenant_id, cidr, label) VALUES (?,?,?)",
            (tenant_id, cidr, label),
        )
        conn.commit()
        return cur.lastrowid


def list_allowed_cidrs(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    tenant_id: str,
) -> list[dict]:
    with lock:
        rows = conn.execute(
            "SELECT id, tenant_id, cidr, label FROM login_ip_allowlists"
            " WHERE tenant_id=? ORDER BY id",
            (tenant_id,),
        ).fetchall()
    return [{"id": r[0], "tenant_id": r[1], "cidr": r[2], "label": r[3]} for r in rows]


def delete_allowed_cidr(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    rule_id: int,
) -> None:
    with lock:
        conn.execute("DELETE FROM login_ip_allowlists WHERE id=?", (rule_id,))
        conn.commit()


def is_ip_allowed(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    tenant_id: str,
    ip_str: str,
) -> bool:
    """Return True if ip_str is allowed for the tenant.

    If the tenant has NO allowlist rules, all IPs are allowed (open by default).
    If rules exist, the IP must match at least one CIDR.
    """
    rules = list_allowed_cidrs(conn, lock, tenant_id)
    if not rules:
        return True  # no restrictions configured
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return False  # unparseable IP is never allowed
    return any(addr in ipaddress.ip_network(r["cidr"], strict=False) for r in rules)


class _LoginRestrictMixin:
    def add_login_cidr(self, tenant_id: str, cidr: str, label: str = "") -> int:
        return add_allowed_cidr(self._get_conn(), self._lock, tenant_id, cidr, label)

    def list_login_cidrs(self, tenant_id: str) -> list[dict]:
        return list_allowed_cidrs(self._get_read_conn(), self._read_lock, tenant_id)

    def delete_login_cidr(self, rule_id: int) -> None:
        delete_allowed_cidr(self._get_conn(), self._lock, rule_id)

    def is_login_ip_allowed(self, tenant_id: str, ip: str) -> bool:
        return is_ip_allowed(self._get_read_conn(), self._read_lock, tenant_id, ip)
```

- [ ] **Step 4: Run tests**

```bash
PYTHONPATH=share/noba-web pytest tests/test_login_restrict.py -v
```

Expected: 8 tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add share/noba-web/server/db/login_restrict.py tests/test_login_restrict.py
git commit -m "feat(login-restrict): tenant-scoped login IP allowlists"
```

---

### Task 8: Register login_restrict in `db/core.py` + wire into login

**Files:**
- Modify: `share/noba-web/server/db/core.py`
- Modify: `share/noba-web/server/routers/auth.py`

- [ ] **Step 1: Register in core.py**

Same pattern as Task 2. Add `login_restrict,` to module imports, `_LoginRestrictMixin` import, add to `_SCHEMA_MODULES` and `Database` class.

```python
# In from . import (...): add login_restrict after integrations
# Add: from .login_restrict import _LoginRestrictMixin
# In _SCHEMA_MODULES: add login_restrict after password_policy
# In Database class: add _LoginRestrictMixin after _PasswordPolicyMixin
```

- [ ] **Step 2: Wire into login endpoint**

In `share/noba-web/server/routers/auth.py`, in `api_login` (around line 92), add the IP check after rate limit check and before password verification:

```python
    # Login IP allowlist check
    login_tenant = db.get_user_tenant(username) or "default"
    if not db.is_login_ip_allowed(login_tenant, ip):
        db.audit_log("login_blocked", username, f"IP {ip} not in allowlist", ip)
        raise HTTPException(403, "Login not permitted from this IP address")
```

Insert this after `password = body.get("password", "")` (line 98) and before the user DB check (line 101). This means the IP check runs before any password verification, which is intentional — blocked IPs don't even get to try passwords.

- [ ] **Step 3: Lint**

```bash
ruff check --fix share/noba-web/server/db/core.py share/noba-web/server/routers/auth.py
```

- [ ] **Step 4: Commit**

```bash
git add share/noba-web/server/db/core.py share/noba-web/server/routers/auth.py
git commit -m "feat(login-restrict): register mixin + enforce IP allowlist on login"
```

---

### Task 9: Login IP allowlist API + inline UI in PasswordPolicyTab

**Files:**
- Modify: `share/noba-web/server/routers/enterprise.py`
- Modify: `share/noba-web/frontend/src/components/settings/PasswordPolicyTab.vue`

- [ ] **Step 1: Add API endpoints to enterprise.py**

Add after password policy endpoints, before `_count_by`:

```python
# ── Login IP Allowlist ───────────────────────────────────────────────────────

@router.get("/api/enterprise/login-ip-rules")
@handle_errors
async def list_login_ip_rules(
    _auth: tuple = Depends(_require_admin),
    tenant_id: str = Depends(get_tenant_id),
):
    return db.list_login_cidrs(tenant_id)


@router.post("/api/enterprise/login-ip-rules")
@handle_errors
async def add_login_ip_rule(
    request: Request,
    _auth: tuple = Depends(_require_admin),
    tenant_id: str = Depends(get_tenant_id),
):
    import json
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
    _auth: tuple = Depends(_require_admin),
):
    db.delete_login_cidr(rule_id)
    return {"ok": True}
```

- [ ] **Step 2: Add IP allowlist section to PasswordPolicyTab.vue**

Append a second card section to `PasswordPolicyTab.vue` after the existing policy card, inside the template root div. Add the state and functions to the script block:

Script additions:
```js
const ipRules = ref([])
const ipForm = ref({ cidr: '', label: '' })
const ipSaving = ref(false)

async function loadIpRules() {
  try { ipRules.value = await get('/api/enterprise/login-ip-rules') } catch {}
}
async function addIpRule() {
  ipSaving.value = true
  error.value = ''
  try {
    await post('/api/enterprise/login-ip-rules', ipForm.value)
    ipForm.value = { cidr: '', label: '' }
    await loadIpRules()
  } catch (e) { error.value = e.message || 'Failed to add rule' }
  ipSaving.value = false
}
async function removeIpRule(id) {
  try { await del(`/api/enterprise/login-ip-rules/${id}`); await loadIpRules() }
  catch (e) { error.value = e.message || 'Delete failed' }
}
```

Update `onMounted` to also call `loadIpRules()`. Add `post, del` to the `useApi()` destructure.

Template addition (after the policy card's closing `</div>`):
```html
    <!-- Login IP Allowlist -->
    <div class="card" style="padding:1rem;margin-top:1rem">
      <h5 style="margin:0 0 .75rem 0">Login IP Allowlist</h5>
      <div style="font-size:.75rem;color:var(--text-muted);margin-bottom:.75rem">
        No rules = all IPs allowed. Adding rules restricts login to matching CIDRs only.
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr auto;gap:.5rem;align-items:end">
        <div>
          <label style="font-size:.8rem;display:block;margin-bottom:.2rem">CIDR</label>
          <input v-model="ipForm.cidr" class="form-control form-control-sm" placeholder="10.0.0.0/24" />
        </div>
        <div>
          <label style="font-size:.8rem;display:block;margin-bottom:.2rem">Label</label>
          <input v-model="ipForm.label" class="form-control form-control-sm" placeholder="Office" />
        </div>
        <button class="btn btn-sm btn-primary" @click="addIpRule"
          :disabled="ipSaving || !ipForm.cidr">
          <i class="fas fa-plus"></i> Add
        </button>
      </div>
      <div v-if="ipRules.length" style="margin-top:.75rem">
        <div v-for="r in ipRules" :key="r.id"
          style="display:flex;align-items:center;gap:.5rem;padding:.3rem 0;border-bottom:1px solid var(--border)">
          <code style="flex:1">{{ r.cidr }}</code>
          <span style="flex:1;font-size:.8rem;color:var(--text-muted)">{{ r.label }}</span>
          <button class="btn btn-xs btn-danger" @click="removeIpRule(r.id)">
            <i class="fas fa-trash"></i>
          </button>
        </div>
      </div>
    </div>
```

- [ ] **Step 3: Build frontend**

```bash
cd share/noba-web/frontend && npm run build
```

- [ ] **Step 4: Commit**

```bash
cd /home/raizen/noba/.worktrees/enterprise-v2
git add share/noba-web/server/routers/enterprise.py \
  share/noba-web/frontend/src/components/settings/PasswordPolicyTab.vue \
  share/noba-web/static/dist/
git commit -m "feat(login-restrict): IP allowlist API + UI in PasswordPolicyTab"
```

---

## ── FEATURE 4: Configurable Data Retention ──────────────────────────────

### Task 10: `db/retention.py` — schema + CRUD + purge runner

**Files:**
- Create: `share/noba-web/server/db/retention.py`
- Create: `tests/test_retention.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_retention.py
"""Tests for db.retention: configurable data retention policies."""
from __future__ import annotations
import sqlite3
import threading
import time
import pytest
from server.db.retention import (
    init_schema, get_retention, set_retention, DEFAULT_RETENTION,
)


@pytest.fixture()
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    lock = threading.Lock()
    init_schema(conn)
    return conn, lock


class TestRetention:
    def test_defaults(self, db):
        conn, lock = db
        ret = get_retention(conn, lock, "default")
        assert ret["metrics_days"] == DEFAULT_RETENTION["metrics_days"]
        assert ret["audit_days"] == DEFAULT_RETENTION["audit_days"]
        assert ret["alerts_days"] == DEFAULT_RETENTION["alerts_days"]
        assert ret["job_runs_days"] == DEFAULT_RETENTION["job_runs_days"]

    def test_set_and_get(self, db):
        conn, lock = db
        set_retention(conn, lock, "default",
                      metrics_days=7, audit_days=365, alerts_days=14, job_runs_days=30)
        ret = get_retention(conn, lock, "default")
        assert ret["metrics_days"] == 7
        assert ret["audit_days"] == 365
        assert ret["alerts_days"] == 14
        assert ret["job_runs_days"] == 30

    def test_tenant_isolation(self, db):
        conn, lock = db
        set_retention(conn, lock, "t1", metrics_days=7)
        set_retention(conn, lock, "t2", metrics_days=90)
        assert get_retention(conn, lock, "t1")["metrics_days"] == 7
        assert get_retention(conn, lock, "t2")["metrics_days"] == 90

    def test_upsert(self, db):
        conn, lock = db
        set_retention(conn, lock, "default", metrics_days=10)
        set_retention(conn, lock, "default", metrics_days=20)
        assert get_retention(conn, lock, "default")["metrics_days"] == 20
```

- [ ] **Step 2: Run to verify failure**

```bash
PYTHONPATH=share/noba-web pytest tests/test_retention.py -v 2>&1 | head -10
```

- [ ] **Step 3: Implement `db/retention.py`**

```python
# share/noba-web/server/db/retention.py
"""Noba – Configurable data retention policies."""
from __future__ import annotations

import logging
import sqlite3
import threading

logger = logging.getLogger("noba")

DEFAULT_RETENTION = {
    "metrics_days": 30,
    "audit_days": 90,
    "alerts_days": 30,
    "job_runs_days": 30,
}


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS retention_policies (
            tenant_id       TEXT PRIMARY KEY,
            metrics_days    INTEGER NOT NULL DEFAULT 30,
            audit_days      INTEGER NOT NULL DEFAULT 90,
            alerts_days     INTEGER NOT NULL DEFAULT 30,
            job_runs_days   INTEGER NOT NULL DEFAULT 30
        );
    """)


def get_retention(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    tenant_id: str,
) -> dict:
    with lock:
        row = conn.execute(
            "SELECT metrics_days, audit_days, alerts_days, job_runs_days"
            " FROM retention_policies WHERE tenant_id=?",
            (tenant_id,),
        ).fetchone()
    if row is None:
        return dict(DEFAULT_RETENTION)
    return {
        "metrics_days": row[0],
        "audit_days": row[1],
        "alerts_days": row[2],
        "job_runs_days": row[3],
    }


def set_retention(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    tenant_id: str,
    metrics_days: int = 30,
    audit_days: int = 90,
    alerts_days: int = 30,
    job_runs_days: int = 30,
) -> None:
    with lock:
        conn.execute(
            "INSERT INTO retention_policies"
            " (tenant_id, metrics_days, audit_days, alerts_days, job_runs_days)"
            " VALUES (?,?,?,?,?)"
            " ON CONFLICT(tenant_id)"
            " DO UPDATE SET metrics_days=excluded.metrics_days,"
            " audit_days=excluded.audit_days,"
            " alerts_days=excluded.alerts_days,"
            " job_runs_days=excluded.job_runs_days",
            (tenant_id, metrics_days, audit_days, alerts_days, job_runs_days),
        )
        conn.commit()


class _RetentionMixin:
    def get_retention(self, tenant_id: str) -> dict:
        return get_retention(self._get_read_conn(), self._read_lock, tenant_id)

    def set_retention(self, tenant_id: str, **kwargs) -> None:
        set_retention(self._get_conn(), self._lock, tenant_id, **kwargs)
```

- [ ] **Step 4: Run tests**

```bash
PYTHONPATH=share/noba-web pytest tests/test_retention.py -v
```

Expected: 4 tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add share/noba-web/server/db/retention.py tests/test_retention.py
git commit -m "feat(retention): configurable data retention policies — schema + CRUD"
```

---

### Task 11: Register retention in `db/core.py` + API endpoints + UI

**Files:**
- Modify: `share/noba-web/server/db/core.py`
- Modify: `share/noba-web/server/routers/enterprise.py`
- Create: `share/noba-web/frontend/src/components/settings/RetentionTab.vue`
- Modify: `share/noba-web/frontend/src/views/SettingsView.vue`

- [ ] **Step 1: Register in core.py**

Same pattern. Add `retention,` to module imports, `_RetentionMixin` import, `_SCHEMA_MODULES`, and `Database` class.

- [ ] **Step 2: Add API endpoints to enterprise.py**

Add `RetentionBody` model after `PasswordPolicyBody`:

```python
class RetentionBody(BaseModel):
    metrics_days: int = 30
    audit_days: int = 90
    alerts_days: int = 30
    job_runs_days: int = 30
```

Add endpoints before `_count_by`:

```python
# ── Data Retention Policies ──────────────────────────────────────────────────

@router.get("/api/enterprise/retention")
@handle_errors
async def get_retention(
    _auth: tuple = Depends(_require_admin),
    tenant_id: str = Depends(get_tenant_id),
):
    return db.get_retention(tenant_id)


@router.put("/api/enterprise/retention")
@handle_errors
async def set_retention(
    body: RetentionBody,
    _auth: tuple = Depends(_require_admin),
    tenant_id: str = Depends(get_tenant_id),
):
    for field in ["metrics_days", "audit_days", "alerts_days", "job_runs_days"]:
        val = getattr(body, field)
        if val < 1 or val > 3650:
            raise HTTPException(status_code=422, detail=f"{field} must be between 1 and 3650")
    db.set_retention(
        tenant_id,
        metrics_days=body.metrics_days,
        audit_days=body.audit_days,
        alerts_days=body.alerts_days,
        job_runs_days=body.job_runs_days,
    )
    return {"ok": True}
```

- [ ] **Step 3: Create RetentionTab.vue**

```vue
<!-- share/noba-web/frontend/src/components/settings/RetentionTab.vue -->
<script setup>
import { ref, onMounted } from 'vue'
import { useAuthStore } from '../../stores/auth'
import { useApi } from '../../composables/useApi'

const authStore = useAuthStore()
const { get, put } = useApi()

const ret = ref({ metrics_days: 30, audit_days: 90, alerts_days: 30, job_runs_days: 30 })
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const msg = ref('')

async function load() {
  if (!authStore.isAdmin) return
  loading.value = true
  error.value = ''
  try { ret.value = await get('/api/enterprise/retention') }
  catch (e) { error.value = e.message || 'Failed to load' }
  loading.value = false
}

async function save() {
  saving.value = true; msg.value = ''; error.value = ''
  try {
    await put('/api/enterprise/retention', ret.value)
    msg.value = 'Retention policy saved.'
  } catch (e) { error.value = e.message || 'Save failed' }
  saving.value = false
}

onMounted(load)
</script>

<template>
  <div>
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem">
      <h3 style="margin:0">Data Retention</h3>
      <button class="btn btn-sm" @click="load" :disabled="loading">
        <i class="fas fa-sync" :class="loading ? 'fa-spin' : ''"></i> Refresh
      </button>
    </div>

    <div v-if="error" class="alert alert-danger">{{ error }}</div>
    <div v-if="msg" class="alert alert-success">{{ msg }}</div>

    <div v-if="loading" style="text-align:center;padding:2rem;color:var(--text-muted)">
      <i class="fas fa-spinner fa-spin"></i>
    </div>
    <div v-else class="card" style="padding:1rem">
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem">
        <div>
          <label style="font-size:.8rem;display:block;margin-bottom:.2rem">Metrics (days)</label>
          <input v-model.number="ret.metrics_days" type="number" min="1" max="3650"
            class="form-control form-control-sm" />
        </div>
        <div>
          <label style="font-size:.8rem;display:block;margin-bottom:.2rem">Audit Log (days)</label>
          <input v-model.number="ret.audit_days" type="number" min="1" max="3650"
            class="form-control form-control-sm" />
        </div>
        <div>
          <label style="font-size:.8rem;display:block;margin-bottom:.2rem">Alerts (days)</label>
          <input v-model.number="ret.alerts_days" type="number" min="1" max="3650"
            class="form-control form-control-sm" />
        </div>
        <div>
          <label style="font-size:.8rem;display:block;margin-bottom:.2rem">Job Runs (days)</label>
          <input v-model.number="ret.job_runs_days" type="number" min="1" max="3650"
            class="form-control form-control-sm" />
        </div>
      </div>
      <button class="btn btn-sm btn-primary" style="margin-top:1rem" @click="save" :disabled="saving">
        <i class="fas fa-save"></i> Save
      </button>
      <div style="font-size:.75rem;color:var(--text-muted);margin-top:.75rem">
        Data older than the configured number of days is automatically purged during nightly maintenance.
      </div>
    </div>
  </div>
</template>
```

- [ ] **Step 4: Register in SettingsView.vue**

Add to tabs array (after `sessions`, before `license`):
```js
{ key: 'retention', label: 'Data Retention', icon: 'fa-database', admin: true },
```

Add to tabComponents:
```js
retention: defineAsyncComponent(() => import('../components/settings/RetentionTab.vue')),
```

- [ ] **Step 5: Build frontend**

```bash
cd share/noba-web/frontend && npm run build
```

- [ ] **Step 6: Lint + commit**

```bash
cd /home/raizen/noba/.worktrees/enterprise-v2
ruff check --fix share/noba-web/server/db/core.py share/noba-web/server/routers/enterprise.py
git add share/noba-web/server/db/core.py share/noba-web/server/routers/enterprise.py \
  share/noba-web/frontend/src/components/settings/RetentionTab.vue \
  share/noba-web/frontend/src/views/SettingsView.vue \
  share/noba-web/static/dist/
git commit -m "feat(retention): register mixin + API endpoints + RetentionTab.vue"
```

---

## ── FEATURE 5: Outbound Webhook HMAC Signing ────────────────────────────

### Task 12: Webhook signing in `_do_http_request`

**Files:**
- Modify: `share/noba-web/server/workflow_engine.py`
- Create: `tests/test_webhook_signing.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_webhook_signing.py
"""Tests for outbound webhook HMAC-SHA256 signing."""
from __future__ import annotations
import hashlib
import hmac
import json
import pytest


def compute_expected_signature(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class TestWebhookSigning:
    def test_sign_body_produces_valid_hmac(self):
        from server.workflow_engine import _sign_request_headers
        body = b'{"event": "test"}'
        secret = "my-webhook-secret"
        headers = _sign_request_headers(secret, body)
        assert "X-Noba-Signature" in headers
        expected = compute_expected_signature(secret, body)
        assert headers["X-Noba-Signature"] == expected

    def test_sign_empty_secret_returns_no_header(self):
        from server.workflow_engine import _sign_request_headers
        headers = _sign_request_headers("", b"body")
        assert headers == {}

    def test_sign_none_secret_returns_no_header(self):
        from server.workflow_engine import _sign_request_headers
        headers = _sign_request_headers(None, b"body")
        assert headers == {}

    def test_signature_changes_with_body(self):
        from server.workflow_engine import _sign_request_headers
        h1 = _sign_request_headers("secret", b"body1")
        h2 = _sign_request_headers("secret", b"body2")
        assert h1["X-Noba-Signature"] != h2["X-Noba-Signature"]

    def test_signature_changes_with_secret(self):
        from server.workflow_engine import _sign_request_headers
        h1 = _sign_request_headers("secret1", b"body")
        h2 = _sign_request_headers("secret2", b"body")
        assert h1["X-Noba-Signature"] != h2["X-Noba-Signature"]
```

- [ ] **Step 2: Run to verify failure**

```bash
PYTHONPATH=share/noba-web pytest tests/test_webhook_signing.py -v 2>&1 | head -10
```

Expected: `ImportError: cannot import name '_sign_request_headers'`

- [ ] **Step 3: Add `_sign_request_headers` to workflow_engine.py**

In `share/noba-web/server/workflow_engine.py`, add this function before `_do_http_request`:

```python
def _sign_request_headers(secret: str | None, body: bytes) -> dict:
    """Compute HMAC-SHA256 signature header for outbound webhooks.

    Returns a dict with 'X-Noba-Signature' header, or empty dict if no secret.
    """
    if not secret:
        return {}
    import hashlib
    import hmac as _hmac
    sig = "sha256=" + _hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return {"X-Noba-Signature": sig}
```

- [ ] **Step 4: Wire signing into `_do_http_request`**

Update `_do_http_request` to accept an optional `signing_secret` parameter and merge the signature headers:

```python
def _do_http_request(
    url: str,
    method: str = "GET",
    headers: dict | None = None,
    body: str | bytes | None = None,
    auth: tuple[str, str] | None = None,
    timeout: float = 30,
    signing_secret: str | None = None,
) -> _HttpResult:
```

Inside the function, before the `httpx.request` call, add:

```python
    merged_headers = dict(headers or {})
    if body is not None and signing_secret:
        raw = body.encode() if isinstance(body, str) else body
        merged_headers.update(_sign_request_headers(signing_secret, raw))
```

Then pass `headers=merged_headers` to `httpx.request` instead of `headers=headers`.

- [ ] **Step 5: Run tests**

```bash
PYTHONPATH=share/noba-web pytest tests/test_webhook_signing.py -v
```

Expected: 5 tests PASSED.

- [ ] **Step 6: Lint + commit**

```bash
ruff check --fix share/noba-web/server/workflow_engine.py
git add share/noba-web/server/workflow_engine.py tests/test_webhook_signing.py
git commit -m "feat(webhook-signing): HMAC-SHA256 outbound webhook signatures"
```

---

### Task 13: Webhook signing secret config in enterprise.py

**Files:**
- Modify: `share/noba-web/server/routers/enterprise.py`

- [ ] **Step 1: Add signing secret endpoints**

The signing secret is stored in the vault (Feature 3, Tier 2). Add a convenience endpoint that reads/sets the `webhook-signing-secret` vault entry:

```python
# ── Webhook Signing ──────────────────────────────────────────────────────────

@router.get("/api/enterprise/webhook-signing")
@handle_errors
async def get_webhook_signing_status(
    _auth: tuple = Depends(_require_admin),
    tenant_id: str = Depends(get_tenant_id),
):
    """Check if a webhook signing secret is configured (never returns the secret)."""
    has_secret = db.vault_get_plaintext(tenant_id, "webhook-signing-secret") is not None
    return {"configured": has_secret}


@router.put("/api/enterprise/webhook-signing")
@handle_errors
async def set_webhook_signing_secret(
    request: Request,
    _auth: tuple = Depends(_require_admin),
    tenant_id: str = Depends(get_tenant_id),
):
    """Store the webhook signing secret in the vault."""
    import json
    body = json.loads(await request.body())
    secret = body.get("secret", "").strip()
    if not secret or len(secret) < 16:
        raise HTTPException(status_code=422, detail="Secret must be at least 16 characters")
    db.vault_store(tenant_id, "webhook-signing-secret", secret)
    return {"ok": True}


@router.delete("/api/enterprise/webhook-signing")
@handle_errors
async def delete_webhook_signing_secret(
    _auth: tuple = Depends(_require_admin),
    tenant_id: str = Depends(get_tenant_id),
):
    db.vault_delete(tenant_id, "webhook-signing-secret")
    return {"ok": True}
```

- [ ] **Step 2: Lint + commit**

```bash
ruff check --fix share/noba-web/server/routers/enterprise.py
git add share/noba-web/server/routers/enterprise.py
git commit -m "feat(webhook-signing): signing secret config endpoints (stored in vault)"
```

---

### Task 14: Run full test suite + push

- [ ] **Step 1: Backend tests**

```bash
cd /home/raizen/noba/.worktrees/enterprise-v2
PYTHONPATH=share/noba-web pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: no failures.

- [ ] **Step 2: Lint check**

```bash
ruff check share/noba-web/server/
```

Expected: `All checks passed!`

- [ ] **Step 3: Push**

```bash
git push enterprise enterprise-v2
```
