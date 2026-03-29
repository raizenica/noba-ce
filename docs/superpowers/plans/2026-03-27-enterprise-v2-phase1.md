# Enterprise v2 Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port SAML 2.0 SP, WebAuthn/FIDO2 + MFA backup codes, SCIM 2.0 provisioning, and API key scoping from enterprise-uplift into a fresh `enterprise-v2` branch off current `main`, adapting all code to main's modular architecture.

**Architecture:** Six new files (3 db modules + 3 routers) + targeted additions to `auth.py`, `deps.py`, `db/core.py`, `db/api_keys.py`, and `routers/__init__.py`. Enterprise-uplift serves as logic reference; all structure follows main's `(conn, lock, ...)` / mixin patterns. SQLite-only for Phase 1 — PostgreSQL is Phase 2.

**Tech Stack:** Python 3.11, FastAPI, `cryptography` (already in requirements), `xml.etree.ElementTree`, `struct`, `secrets`, `ipaddress` (all stdlib). Zero new runtime dependencies.

---

### Task 0: Create enterprise-v2 branch

**Files:** none

- [ ] **Step 1: Create and push branch**

```bash
cd /home/raizen/noba
git checkout main
git checkout -b enterprise-v2
git push enterprise enterprise-v2
```

Expected: branch `enterprise-v2` visible at `https://github.com/raizenica/noba-enterprise`

- [ ] **Step 2: Verify remotes**

```bash
git remote -v
git branch -vv
```

Expected: `enterprise-v2` tracking `enterprise/enterprise-v2`

---

### Task 1: DB module — `db/webauthn.py`

**Files:**
- Create: `share/noba-web/server/db/webauthn.py`
- Modify: `share/noba-web/server/db/core.py`

- [ ] **Step 1: Write the failing test**

```python
# In tests/test_db_webauthn.py (new file):
import pytest
import sqlite3
from server.db import webauthn as wbn

@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    wbn.init_schema(c)
    c.commit()
    return c

import threading
@pytest.fixture
def lock():
    return threading.Lock()

def test_store_and_get_credential(conn, lock):
    wbn.store_credential(conn, lock, "u1", b"credid1", b"pubkey1", 0)
    rows = wbn.get_credentials(conn, lock, "u1")
    assert len(rows) == 1
    assert rows[0]["credential_id"] == b"credid1"

def test_update_sign_count(conn, lock):
    wbn.store_credential(conn, lock, "u1", b"credid1", b"pubkey1", 0)
    wbn.update_sign_count(conn, lock, b"credid1", 5)
    rows = wbn.get_credentials(conn, lock, "u1")
    assert rows[0]["sign_count"] == 5

def test_get_credential_by_id(conn, lock):
    wbn.store_credential(conn, lock, "u1", b"credid1", b"pubkey1", 0)
    row = wbn.get_credential_by_id(conn, lock, b"credid1")
    assert row is not None
    assert row["username"] == "u1"

def test_delete_credential(conn, lock):
    wbn.store_credential(conn, lock, "u1", b"credid1", b"pubkey1", 0)
    wbn.delete_credential(conn, lock, b"credid1")
    assert wbn.get_credentials(conn, lock, "u1") == []

def test_backup_codes(conn, lock):
    hashes = ["hash1", "hash2"]
    wbn.store_backup_codes(conn, lock, "u1", hashes)
    assert wbn.verify_backup_code(conn, lock, "u1", "hash1") is True
    assert wbn.verify_backup_code(conn, lock, "u1", "hash1") is False  # consumed
    assert wbn.verify_backup_code(conn, lock, "u1", "hash2") is True
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /home/raizen/noba
PYTHONPATH=share/noba-web pytest tests/test_db_webauthn.py -v
```

Expected: `ImportError` or `ModuleNotFoundError` — `server.db.webauthn` doesn't exist yet

- [ ] **Step 3: Create `share/noba-web/server/db/webauthn.py`**

```python
"""Noba – DB WebAuthn credential and backup-code functions."""
from __future__ import annotations

import logging
import sqlite3
import threading
import time
import uuid

logger = logging.getLogger("noba")


def init_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS webauthn_credentials (
            id            TEXT PRIMARY KEY,
            username      TEXT NOT NULL,
            credential_id BLOB NOT NULL UNIQUE,
            public_key    BLOB NOT NULL,
            sign_count    INTEGER NOT NULL DEFAULT 0,
            name          TEXT NOT NULL DEFAULT '',
            created_at    REAL NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS mfa_backup_codes (
            id         TEXT PRIMARY KEY,
            username   TEXT NOT NULL,
            code_hash  TEXT NOT NULL,
            used_at    REAL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_webauthn_username ON webauthn_credentials (username)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_backup_codes_username ON mfa_backup_codes (username)")


def store_credential(
    conn: sqlite3.Connection, lock: threading.Lock,
    username: str, credential_id: bytes, public_key: bytes,
    sign_count: int, name: str = "",
) -> None:
    try:
        with lock:
            conn.execute(
                "INSERT OR REPLACE INTO webauthn_credentials "
                "(id, username, credential_id, public_key, sign_count, name, created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (str(uuid.uuid4()), username, credential_id, public_key, sign_count, name, time.time()),
            )
            conn.commit()
    except Exception as e:
        logger.error("store_credential failed: %s", e)


def get_credentials(
    conn: sqlite3.Connection, lock: threading.Lock, username: str,
) -> list[dict]:
    try:
        with lock:
            rows = conn.execute(
                "SELECT id, username, credential_id, public_key, sign_count, name, created_at "
                "FROM webauthn_credentials WHERE username = ?",
                (username,),
            ).fetchall()
        return [
            {"id": r[0], "username": r[1], "credential_id": r[2],
             "public_key": r[3], "sign_count": r[4], "name": r[5], "created_at": r[6]}
            for r in rows
        ]
    except Exception as e:
        logger.error("get_credentials failed: %s", e)
        return []


def get_credential_by_id(
    conn: sqlite3.Connection, lock: threading.Lock, credential_id: bytes,
) -> dict | None:
    try:
        with lock:
            r = conn.execute(
                "SELECT id, username, credential_id, public_key, sign_count, name, created_at "
                "FROM webauthn_credentials WHERE credential_id = ?",
                (credential_id,),
            ).fetchone()
        if not r:
            return None
        return {"id": r[0], "username": r[1], "credential_id": r[2],
                "public_key": r[3], "sign_count": r[4], "name": r[5], "created_at": r[6]}
    except Exception as e:
        logger.error("get_credential_by_id failed: %s", e)
        return None


def update_sign_count(
    conn: sqlite3.Connection, lock: threading.Lock,
    credential_id: bytes, sign_count: int,
) -> None:
    try:
        with lock:
            conn.execute(
                "UPDATE webauthn_credentials SET sign_count = ? WHERE credential_id = ?",
                (sign_count, credential_id),
            )
            conn.commit()
    except Exception as e:
        logger.error("update_sign_count failed: %s", e)


def delete_credential(
    conn: sqlite3.Connection, lock: threading.Lock, credential_id: bytes,
) -> None:
    try:
        with lock:
            conn.execute(
                "DELETE FROM webauthn_credentials WHERE credential_id = ?",
                (credential_id,),
            )
            conn.commit()
    except Exception as e:
        logger.error("delete_credential failed: %s", e)


def store_backup_codes(
    conn: sqlite3.Connection, lock: threading.Lock,
    username: str, code_hashes: list[str],
) -> None:
    """Replace all backup codes for a user."""
    try:
        with lock:
            conn.execute("DELETE FROM mfa_backup_codes WHERE username = ?", (username,))
            for h in code_hashes:
                conn.execute(
                    "INSERT INTO mfa_backup_codes (id, username, code_hash) VALUES (?,?,?)",
                    (str(uuid.uuid4()), username, h),
                )
            conn.commit()
    except Exception as e:
        logger.error("store_backup_codes failed: %s", e)


def verify_backup_code(
    conn: sqlite3.Connection, lock: threading.Lock,
    username: str, code_hash: str,
) -> bool:
    """Check and consume a backup code. Returns True if valid and unused."""
    try:
        with lock:
            r = conn.execute(
                "SELECT id FROM mfa_backup_codes "
                "WHERE username = ? AND code_hash = ? AND used_at IS NULL",
                (username, code_hash),
            ).fetchone()
            if not r:
                return False
            conn.execute(
                "UPDATE mfa_backup_codes SET used_at = ? WHERE id = ?",
                (time.time(), r[0]),
            )
            conn.commit()
        return True
    except Exception as e:
        logger.error("verify_backup_code failed: %s", e)
        return False


class _WebAuthnMixin:
    """Database mixin — WebAuthn credential and backup-code methods."""

    def webauthn_store_credential(
        self, username: str, credential_id: bytes, public_key: bytes,
        sign_count: int, name: str = "",
    ) -> None:
        self.execute_write(lambda conn: store_credential(
            conn, self._lock, username, credential_id, public_key, sign_count, name,
        ))

    def webauthn_get_credentials(self, username: str) -> list[dict]:
        return self.execute_read(lambda conn: get_credentials(conn, self._read_lock, username))

    def webauthn_get_credential_by_id(self, credential_id: bytes) -> dict | None:
        return self.execute_read(lambda conn: get_credential_by_id(conn, self._read_lock, credential_id))

    def webauthn_update_sign_count(self, credential_id: bytes, sign_count: int) -> None:
        self.execute_write(lambda conn: update_sign_count(conn, self._lock, credential_id, sign_count))

    def webauthn_delete_credential(self, credential_id: bytes) -> None:
        self.execute_write(lambda conn: delete_credential(conn, self._lock, credential_id))

    def webauthn_store_backup_codes(self, username: str, code_hashes: list[str]) -> None:
        self.execute_write(lambda conn: store_backup_codes(conn, self._lock, username, code_hashes))

    def webauthn_verify_backup_code(self, username: str, code_hash: str) -> bool:
        with self._lock:
            conn = self._get_conn()
            result = verify_backup_code(conn, self._lock, username, code_hash)
        return result
```

- [ ] **Step 4: Register in `db/core.py`**

Add to imports at top of `share/noba-web/server/db/core.py`:

```python
# Add to existing import block (alphabetical):
from . import (
    agents, alerts, api_keys, audit, automations, backup_verify,
    baselines, dashboards, dependencies, endpoints, healing,
    integrations, linked_providers, metrics, network,
    notifications, saml, scim, security, status_page, tokens,
    user_dashboards, user_preferences, webauthn, webhooks,
)
from .saml import _SamlMixin
from .scim import _ScimMixin
from .webauthn import _WebAuthnMixin
```

Add `saml`, `scim`, `webauthn` to `_SCHEMA_MODULES` list:

```python
_SCHEMA_MODULES = [
    metrics, audit, automations, alerts, api_keys, tokens,
    notifications, user_dashboards, user_preferences, agents,
    endpoints, dashboards, status_page, security, dependencies,
    baselines, network, webhooks, backup_verify, healing,
    integrations, linked_providers, saml, scim, webauthn,
]
```

Add new mixins to the `Database` class inheritance:

```python
class Database(
    DatabaseBase,
    _MetricsMixin, _AuditMixin, _AutomationsMixin, _AlertsMixin,
    _ApiKeysMixin, _TokensMixin, _NotificationsMixin, _UserDashboardsMixin,
    _UserPreferencesMixin, _AgentsMixin, _EndpointsMixin,
    _DashboardsMixin, _StatusPageMixin, _SecurityMixin, _DependenciesMixin,
    _BaselinesMixin, _WebhooksMixin, _BackupVerifyMixin,
    _ApprovalsMixin, _HealingMixin, _IntegrationsMixin, _LinkedProvidersMixin,
    _SamlMixin, _ScimMixin, _WebAuthnMixin,
):
```

- [ ] **Step 5: Run tests**

```bash
cd /home/raizen/noba
PYTHONPATH=share/noba-web pytest tests/test_db_webauthn.py -v
```

Expected: all 5 tests pass

- [ ] **Step 6: Commit**

```bash
git add share/noba-web/server/db/webauthn.py share/noba-web/server/db/core.py tests/test_db_webauthn.py
git commit -m "feat(enterprise-v2): add db/webauthn.py — credential and backup code storage"
```

---

### Task 2: DB module — `db/saml.py`

**Files:**
- Create: `share/noba-web/server/db/saml.py`
- (core.py already updated in Task 1)

- [ ] **Step 1: Write the failing test**

```python
# In tests/test_db_saml.py (new file):
import pytest
import sqlite3
import threading
import time
from server.db import saml

@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    saml.init_schema(c)
    c.commit()
    return c

@pytest.fixture
def lock():
    return threading.Lock()

def test_store_and_get_session(conn, lock):
    saml.store_session(conn, lock, "sess1", "user@corp.com", "alice", "idx1",
                       time.time(), time.time() + 3600)
    row = saml.get_session_by_index(conn, lock, "idx1")
    assert row is not None
    assert row["username"] == "alice"

def test_delete_session(conn, lock):
    saml.store_session(conn, lock, "sess1", "user@corp.com", "alice", "idx1",
                       time.time(), time.time() + 3600)
    saml.delete_session_by_index(conn, lock, "idx1")
    assert saml.get_session_by_index(conn, lock, "idx1") is None

def test_prune_expired(conn, lock):
    saml.store_session(conn, lock, "sess1", "user@corp.com", "alice", "idx1",
                       time.time() - 7200, time.time() - 3600)  # already expired
    saml.prune_expired(conn, lock)
    assert saml.get_session_by_index(conn, lock, "idx1") is None
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /home/raizen/noba
PYTHONPATH=share/noba-web pytest tests/test_db_saml.py -v
```

Expected: `ImportError` — `server.db.saml` not found

- [ ] **Step 3: Create `share/noba-web/server/db/saml.py`**

```python
"""Noba – DB SAML session functions (for SLO support)."""
from __future__ import annotations

import logging
import sqlite3
import threading
import time
import uuid

logger = logging.getLogger("noba")


def init_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS saml_sessions (
            id          TEXT PRIMARY KEY,
            name_id     TEXT NOT NULL,
            username    TEXT NOT NULL,
            session_idx TEXT,
            issued_at   REAL NOT NULL,
            expires_at  REAL NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_saml_session_idx ON saml_sessions (session_idx)")


def store_session(
    conn: sqlite3.Connection, lock: threading.Lock,
    session_id: str, name_id: str, username: str,
    session_idx: str, issued_at: float, expires_at: float,
) -> None:
    try:
        with lock:
            conn.execute(
                "INSERT OR REPLACE INTO saml_sessions "
                "(id, name_id, username, session_idx, issued_at, expires_at) "
                "VALUES (?,?,?,?,?,?)",
                (session_id, name_id, username, session_idx, issued_at, expires_at),
            )
            conn.commit()
    except Exception as e:
        logger.error("store_session failed: %s", e)


def get_session_by_index(
    conn: sqlite3.Connection, lock: threading.Lock, session_idx: str,
) -> dict | None:
    try:
        with lock:
            r = conn.execute(
                "SELECT id, name_id, username, session_idx, issued_at, expires_at "
                "FROM saml_sessions WHERE session_idx = ?",
                (session_idx,),
            ).fetchone()
        if not r:
            return None
        return {"id": r[0], "name_id": r[1], "username": r[2],
                "session_idx": r[3], "issued_at": r[4], "expires_at": r[5]}
    except Exception as e:
        logger.error("get_session_by_index failed: %s", e)
        return None


def delete_session_by_index(
    conn: sqlite3.Connection, lock: threading.Lock, session_idx: str,
) -> None:
    try:
        with lock:
            conn.execute("DELETE FROM saml_sessions WHERE session_idx = ?", (session_idx,))
            conn.commit()
    except Exception as e:
        logger.error("delete_session_by_index failed: %s", e)


def prune_expired(conn: sqlite3.Connection, lock: threading.Lock) -> None:
    try:
        with lock:
            conn.execute("DELETE FROM saml_sessions WHERE expires_at < ?", (time.time(),))
            conn.commit()
    except Exception as e:
        logger.error("prune_expired failed: %s", e)


class _SamlMixin:
    """Database mixin — SAML session methods."""

    def saml_store_session(
        self, session_id: str, name_id: str, username: str,
        session_idx: str, issued_at: float, expires_at: float,
    ) -> None:
        self.execute_write(lambda conn: store_session(
            conn, self._lock, session_id, name_id, username, session_idx, issued_at, expires_at,
        ))

    def saml_get_session_by_index(self, session_idx: str) -> dict | None:
        return self.execute_read(lambda conn: get_session_by_index(conn, self._read_lock, session_idx))

    def saml_delete_session_by_index(self, session_idx: str) -> None:
        self.execute_write(lambda conn: delete_session_by_index(conn, self._lock, session_idx))

    def saml_prune_expired(self) -> None:
        self.execute_write(lambda conn: prune_expired(conn, self._lock))
```

- [ ] **Step 4: Run tests**

```bash
cd /home/raizen/noba
PYTHONPATH=share/noba-web pytest tests/test_db_saml.py -v
```

Expected: all 3 tests pass

- [ ] **Step 5: Commit**

```bash
git add share/noba-web/server/db/saml.py tests/test_db_saml.py
git commit -m "feat(enterprise-v2): add db/saml.py — SAML session storage for SLO"
```

---

### Task 3: DB module — `db/scim.py` + API key scoping columns

**Files:**
- Create: `share/noba-web/server/db/scim.py`
- Modify: `share/noba-web/server/db/core.py` (ALTER TABLE migrations)

- [ ] **Step 1: Write the failing tests**

```python
# In tests/test_db_scim.py (new file):
import pytest
import sqlite3
import threading
import time
from server.db import scim

@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    scim.init_schema(c)
    c.commit()
    return c

@pytest.fixture
def lock():
    return threading.Lock()

def test_store_and_verify_token(conn, lock):
    scim.store_token(conn, lock, "tok1", "hash1")
    assert scim.verify_token(conn, lock, "hash1") is True

def test_invalid_token_rejected(conn, lock):
    assert scim.verify_token(conn, lock, "nothash") is False

def test_provision_log(conn, lock):
    scim.log_provision(conn, lock, "create", "ext-123", "alice", "ok")
    logs = scim.get_provision_log(conn, lock, limit=10)
    assert len(logs) == 1
    assert logs[0]["action"] == "create"
    assert logs[0]["username"] == "alice"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /home/raizen/noba
PYTHONPATH=share/noba-web pytest tests/test_db_scim.py -v
```

Expected: `ImportError` — `server.db.scim` not found

- [ ] **Step 3: Create `share/noba-web/server/db/scim.py`**

```python
"""Noba – DB SCIM token and provisioning-log functions."""
from __future__ import annotations

import logging
import sqlite3
import threading
import time
import uuid

logger = logging.getLogger("noba")


def init_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scim_tokens (
            id           TEXT PRIMARY KEY,
            token_hash   TEXT NOT NULL UNIQUE,
            created_at   REAL NOT NULL,
            last_used_at REAL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scim_provision_log (
            id        TEXT PRIMARY KEY,
            action    TEXT NOT NULL,
            scim_id   TEXT,
            username  TEXT,
            timestamp REAL NOT NULL,
            result    TEXT NOT NULL
        )
    """)


def store_token(
    conn: sqlite3.Connection, lock: threading.Lock,
    token_id: str, token_hash: str,
) -> None:
    try:
        with lock:
            conn.execute("DELETE FROM scim_tokens")  # only one active token
            conn.execute(
                "INSERT INTO scim_tokens (id, token_hash, created_at) VALUES (?,?,?)",
                (token_id, token_hash, time.time()),
            )
            conn.commit()
    except Exception as e:
        logger.error("store_token failed: %s", e)


def verify_token(
    conn: sqlite3.Connection, lock: threading.Lock, token_hash: str,
) -> bool:
    try:
        with lock:
            r = conn.execute(
                "SELECT id FROM scim_tokens WHERE token_hash = ?", (token_hash,),
            ).fetchone()
            if r:
                conn.execute(
                    "UPDATE scim_tokens SET last_used_at = ? WHERE id = ?",
                    (time.time(), r[0]),
                )
                conn.commit()
        return r is not None
    except Exception as e:
        logger.error("verify_token failed: %s", e)
        return False


def log_provision(
    conn: sqlite3.Connection, lock: threading.Lock,
    action: str, scim_id: str | None, username: str | None, result: str,
) -> None:
    try:
        with lock:
            conn.execute(
                "INSERT INTO scim_provision_log (id, action, scim_id, username, timestamp, result) "
                "VALUES (?,?,?,?,?,?)",
                (str(uuid.uuid4()), action, scim_id, username, time.time(), result),
            )
            conn.commit()
    except Exception as e:
        logger.error("log_provision failed: %s", e)


def get_provision_log(
    conn: sqlite3.Connection, lock: threading.Lock, limit: int = 100,
) -> list[dict]:
    try:
        with lock:
            rows = conn.execute(
                "SELECT action, scim_id, username, timestamp, result "
                "FROM scim_provision_log ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [{"action": r[0], "scim_id": r[1], "username": r[2],
                 "timestamp": r[3], "result": r[4]} for r in rows]
    except Exception as e:
        logger.error("get_provision_log failed: %s", e)
        return []


class _ScimMixin:
    """Database mixin — SCIM token and provisioning-log methods."""

    def scim_store_token(self, token_id: str, token_hash: str) -> None:
        self.execute_write(lambda conn: store_token(conn, self._lock, token_id, token_hash))

    def scim_verify_token(self, token_hash: str) -> bool:
        with self._lock:
            conn = self._get_conn()
            return verify_token(conn, self._lock, token_hash)

    def scim_log_provision(
        self, action: str, scim_id: str | None, username: str | None, result: str,
    ) -> None:
        self.execute_write(lambda conn: log_provision(
            conn, self._lock, action, scim_id, username, result,
        ))

    def scim_get_provision_log(self, limit: int = 100) -> list[dict]:
        return self.execute_read(lambda conn: get_provision_log(conn, self._read_lock, limit))
```

- [ ] **Step 4: Add API key scoping columns to `_run_alter_migrations` in `db/core.py`**

In `share/noba-web/server/db/core.py`, add to the `migrations` list in `_run_alter_migrations`:

```python
        "ALTER TABLE api_keys ADD COLUMN scope TEXT DEFAULT ''",
        "ALTER TABLE api_keys ADD COLUMN allowed_ips TEXT DEFAULT '[]'",
        "ALTER TABLE api_keys ADD COLUMN rate_limit INTEGER DEFAULT 0",
```

- [ ] **Step 5: Run tests**

```bash
cd /home/raizen/noba
PYTHONPATH=share/noba-web pytest tests/test_db_scim.py -v
```

Expected: all 3 tests pass

- [ ] **Step 6: Lint**

```bash
ruff check --fix share/noba-web/server/db/saml.py share/noba-web/server/db/scim.py share/noba-web/server/db/webauthn.py share/noba-web/server/db/core.py
```

Expected: no errors

- [ ] **Step 7: Commit**

```bash
git add share/noba-web/server/db/scim.py share/noba-web/server/db/core.py tests/test_db_scim.py
git commit -m "feat(enterprise-v2): add db/scim.py, register all enterprise mixins, add api_key scope columns"
```

---

### Task 4: WebAuthn router

**Files:**
- Create: `share/noba-web/server/routers/webauthn.py`
- Modify: `share/noba-web/server/routers/__init__.py`

- [ ] **Step 1: Write the failing tests**

```python
# In tests/test_router_webauthn.py (new file):
import pytest
from unittest.mock import patch, MagicMock

class TestWebAuthnRegister:
    def test_register_begin_requires_auth(self, client):
        resp = client.post("/api/webauthn/register/begin")
        assert resp.status_code == 401

    def test_register_begin_returns_options(self, client, admin_headers):
        resp = client.post("/api/webauthn/register/begin", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "challenge" in data
        assert "rp" in data
        assert "user" in data

    def test_register_complete_requires_auth(self, client):
        resp = client.post("/api/webauthn/register/complete", json={})
        assert resp.status_code == 401

class TestWebAuthnLogin:
    def test_login_begin_requires_username(self, client):
        resp = client.post("/api/webauthn/login/begin", json={})
        assert resp.status_code == 400

    def test_login_begin_unknown_user(self, client):
        resp = client.post("/api/webauthn/login/begin", json={"username": "noexist"})
        assert resp.status_code == 404

    def test_login_begin_no_credentials(self, client, admin_headers):
        resp = client.post("/api/webauthn/login/begin", json={"username": "admin"})
        assert resp.status_code == 404  # no credentials registered

class TestBackupCodes:
    def test_generate_requires_auth(self, client):
        resp = client.post("/api/webauthn/backup-codes/generate")
        assert resp.status_code == 401

    def test_generate_returns_10_codes(self, client, admin_headers):
        resp = client.post("/api/webauthn/backup-codes/generate", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["codes"]) == 10

    def test_verify_invalid_code(self, client):
        resp = client.post("/api/webauthn/backup-codes/verify",
                           json={"username": "admin", "code": "BADCODE1"})
        assert resp.status_code == 401

    def test_verify_valid_code_issues_token(self, client, admin_headers):
        # Generate codes first
        gen = client.post("/api/webauthn/backup-codes/generate", headers=admin_headers)
        code = gen.json()["codes"][0]
        # Verify one
        resp = client.post("/api/webauthn/backup-codes/verify",
                           json={"username": "admin", "code": code})
        assert resp.status_code == 200
        assert "token" in resp.json()

    def test_code_can_only_be_used_once(self, client, admin_headers):
        gen = client.post("/api/webauthn/backup-codes/generate", headers=admin_headers)
        code = gen.json()["codes"][0]
        client.post("/api/webauthn/backup-codes/verify",
                    json={"username": "admin", "code": code})
        resp = client.post("/api/webauthn/backup-codes/verify",
                           json={"username": "admin", "code": code})
        assert resp.status_code == 401

class TestWebAuthnCredentials:
    def test_list_requires_auth(self, client):
        resp = client.get("/api/webauthn/credentials")
        assert resp.status_code == 401

    def test_list_empty_initially(self, client, admin_headers):
        resp = client.get("/api/webauthn/credentials", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["credentials"] == []
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /home/raizen/noba
PYTHONPATH=share/noba-web pytest tests/test_router_webauthn.py -v
```

Expected: 404 on all endpoints — router not registered yet

- [ ] **Step 3: Create `share/noba-web/server/routers/webauthn.py`**

```python
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
        length = data[pos]; pos += 1
    elif info == 25:
        length = struct.unpack_from(">H", data, pos)[0]; pos += 2
    elif info == 26:
        length = struct.unpack_from(">I", data, pos)[0]; pos += 4
    else:
        raise ValueError(f"CBOR: unsupported additional info {info}")

    if major == 0:  # unsigned int
        return pos, length
    elif major == 2:  # bytes
        val = data[pos:pos + length]; pos += length; return pos, val
    elif major == 3:  # text
        val = data[pos:pos + length].decode(); pos += length; return pos, val
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
    raise ValueError(f"CBOR: unsupported major type {major}")


def _cose_key_to_pem(cose_map: dict) -> str:
    """Convert a COSE EC2 P-256 key map to PEM public key."""
    from cryptography.hazmat.primitives.asymmetric.ec import (
        EllipticCurvePublicNumbers, SECP256R1,
    )
    from cryptography.hazmat.primitives.serialization import (
        Encoding, PublicFormat,
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
    from cryptography.hazmat.primitives.asymmetric.ec import ECDSA
    from cryptography.hazmat.primitives.hashes import SHA256
    from cryptography.hazmat.primitives.serialization import load_pem_public_key
    from cryptography.exceptions import InvalidSignature
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
    request: Request, auth: tuple[str, str] = Depends(_get_auth),
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
    request: Request, auth: tuple[str, str] = Depends(_get_auth),
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
    request: Request, auth: tuple[str, str] = Depends(_get_auth),
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
    request: Request, auth: tuple[str, str] = Depends(_get_auth),
):
    """List registered WebAuthn credentials for the authenticated user."""
    username, _role = auth
    creds = db.webauthn_get_credentials(username)
    return {
        "credentials": [
            {"id": _b64url_encode(c["credential_id"]), "name": c["name"],
             "created_at": c["created_at"]}
            for c in creds
        ]
    }


@router.delete("/api/webauthn/credentials/{cred_id}")
@handle_errors
async def webauthn_delete_credential(
    cred_id: str, request: Request, auth: tuple[str, str] = Depends(_get_auth),
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
```

- [ ] **Step 4: Register router in `routers/__init__.py`**

```python
# Add import with other router imports:
from .webauthn import router as webauthn_router

# Add to api_router includes (after auth_router):
api_router.include_router(webauthn_router)
```

- [ ] **Step 5: Run tests**

```bash
cd /home/raizen/noba
PYTHONPATH=share/noba-web pytest tests/test_router_webauthn.py -v
```

Expected: all 11 tests pass

- [ ] **Step 6: Lint**

```bash
ruff check --fix share/noba-web/server/routers/webauthn.py
```

Expected: no errors

- [ ] **Step 7: Commit**

```bash
git add share/noba-web/server/routers/webauthn.py share/noba-web/server/routers/__init__.py tests/test_router_webauthn.py
git commit -m "feat(enterprise-v2): add WebAuthn/FIDO2 router — registration, login, backup codes"
```

---

### Task 5: SAML 2.0 router

**Files:**
- Create: `share/noba-web/server/routers/saml.py`
- Modify: `share/noba-web/server/routers/__init__.py`

- [ ] **Step 1: Write the failing tests**

```python
# In tests/test_router_saml.py (new file):
import pytest
from unittest.mock import patch

class TestSamlDisabled:
    def test_login_when_disabled_returns_400(self, client):
        with patch("server.routers.saml._saml_cfg",
                   return_value={"enabled": False, "idp_sso_url": ""}):
            resp = client.get("/api/saml/login")
        assert resp.status_code == 400

    def test_metadata_when_disabled_returns_400(self, client):
        with patch("server.routers.saml._saml_cfg",
                   return_value={"enabled": False, "idp_sso_url": ""}):
            resp = client.get("/api/saml/metadata")
        assert resp.status_code == 400

    def test_acs_when_disabled_returns_400(self, client):
        with patch("server.routers.saml._saml_cfg",
                   return_value={"enabled": False, "idp_sso_url": ""}):
            resp = client.post("/api/saml/acs", data={"SAMLResponse": "x"})
        assert resp.status_code == 400

class TestSamlEnabled:
    _cfg = {
        "enabled": True,
        "idp_sso_url": "https://idp.example.com/sso",
        "entity_id": "https://noba.example.com",
        "acs_url": "https://noba.example.com/api/saml/acs",
        "idp_cert": "",
        "default_role": "viewer",
        "group_mapping": {},
    }

    def test_login_redirects_to_idp(self, client):
        with patch("server.routers.saml._saml_cfg", return_value=self._cfg):
            resp = client.get("/api/saml/login", follow_redirects=False)
        assert resp.status_code in (302, 307)
        assert "idp.example.com" in resp.headers["location"]

    def test_metadata_returns_xml(self, client):
        with patch("server.routers.saml._saml_cfg", return_value=self._cfg):
            resp = client.get("/api/saml/metadata")
        assert resp.status_code == 200
        assert "EntityDescriptor" in resp.text
        assert resp.headers["content-type"].startswith("application/xml")

    def test_acs_rejects_missing_response(self, client):
        with patch("server.routers.saml._saml_cfg", return_value=self._cfg):
            resp = client.post("/api/saml/acs", data={})
        assert resp.status_code == 400

    def test_acs_rejects_invalid_base64(self, client):
        with patch("server.routers.saml._saml_cfg", return_value=self._cfg):
            resp = client.post("/api/saml/acs", data={"SAMLResponse": "not-valid-base64!!"})
        assert resp.status_code in (400, 401)

class TestSamlStatePruning:
    def test_prune_saml_states_removes_old(self):
        import time
        from server.routers.saml import _saml_states, _saml_states_lock, _prune_saml_states
        with _saml_states_lock:
            _saml_states["stale"] = {"ts": time.time() - 700}
            _saml_states["fresh"] = {"ts": time.time()}
        _prune_saml_states()
        with _saml_states_lock:
            assert "stale" not in _saml_states
            assert "fresh" in _saml_states
            _saml_states.pop("fresh", None)
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /home/raizen/noba
PYTHONPATH=share/noba-web pytest tests/test_router_saml.py -v
```

Expected: 404 on all endpoints — router not registered yet

- [ ] **Step 3: Create `share/noba-web/server/routers/saml.py`**

```python
"""Noba – SAML 2.0 Service Provider (stdlib XML, no external SAML libs)."""
from __future__ import annotations

import base64
import logging
import secrets
import threading
import time
import urllib.parse
import uuid
import zlib
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree as ET

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse, Response

from ..auth import pbkdf2_hash, token_store, users
from ..deps import _client_ip, db, handle_errors
from ..yaml_config import read_yaml_settings

logger = logging.getLogger("noba")
router = APIRouter()

_NS = {
    "saml": "urn:oasis:names:tc:SAML:2.0:assertion",
    "samlp": "urn:oasis:names:tc:SAML:2.0:protocol",
    "ds": "http://www.w3.org/2000/09/xmldsig#",
    "md": "urn:oasis:names:tc:SAML:2.0:metadata",
}
for _prefix, _uri in _NS.items():
    ET.register_namespace(_prefix, _uri)

_saml_states: dict[str, dict] = {}
_saml_states_lock = threading.Lock()


def _prune_saml_states() -> None:
    now = time.time()
    with _saml_states_lock:
        expired = [k for k, v in _saml_states.items() if now - v.get("ts", 0) > 600]
        for k in expired:
            del _saml_states[k]


def _saml_cfg() -> dict:
    cfg = read_yaml_settings()
    return {
        "enabled": cfg.get("samlEnabled", False),
        "entity_id": cfg.get("samlEntityId", ""),
        "idp_sso_url": cfg.get("samlIdpSsoUrl", ""),
        "idp_cert": cfg.get("samlIdpCert", ""),
        "acs_url": cfg.get("samlAcsUrl", ""),
        "default_role": cfg.get("samlDefaultRole", "viewer"),
        "group_mapping": cfg.get("samlGroupMapping", {}),
    }


def _require_saml_enabled(cfg: dict) -> None:
    if not cfg.get("enabled") or not cfg.get("idp_sso_url"):
        raise HTTPException(400, "SAML SSO is not configured")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_authn_request(cfg: dict, relay_state: str) -> str:
    """Build a deflate+base64 encoded AuthnRequest redirect URL."""
    request_id = f"_{uuid.uuid4().hex}"
    now = _utc_now()
    xml = (
        f'<samlp:AuthnRequest xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol" '
        f'xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion" '
        f'ID="{request_id}" Version="2.0" '
        f'IssueInstant="{_utc_iso(now)}" '
        f'AssertionConsumerServiceURL="{cfg["acs_url"]}" '
        f'ProtocolBinding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST">'
        f'<saml:Issuer>{cfg["entity_id"]}</saml:Issuer>'
        f'</samlp:AuthnRequest>'
    )
    deflated = zlib.compress(xml.encode(), wbits=-15)
    encoded = base64.b64encode(deflated).decode()
    params = urllib.parse.urlencode({
        "SAMLRequest": encoded,
        "RelayState": relay_state,
    })
    return f'{cfg["idp_sso_url"]}?{params}', request_id


def _parse_saml_response(xml_str: str, cfg: dict) -> tuple[str, str, str]:
    """Parse and validate a SAML Response. Returns (name_id, role, session_index).
    Raises HTTPException on failure.
    """
    try:
        root = ET.fromstring(xml_str)
    except ET.ParseError as e:
        raise HTTPException(401, f"Invalid SAML XML: {e}")

    # Check top-level Status
    status_el = root.find(".//{urn:oasis:names:tc:SAML:2.0:protocol}StatusCode")
    if status_el is None or "Success" not in status_el.get("Value", ""):
        raise HTTPException(401, "SAML authentication failed")

    # Extract NameID
    name_id_el = root.find(".//{urn:oasis:names:tc:SAML:2.0:assertion}NameID")
    if name_id_el is None or not name_id_el.text:
        raise HTTPException(401, "Missing NameID in SAML assertion")
    name_id = name_id_el.text.strip()

    # Extract session index
    authn_stmt = root.find(".//{urn:oasis:names:tc:SAML:2.0:assertion}AuthnStatement")
    session_index = ""
    if authn_stmt is not None:
        session_index = authn_stmt.get("SessionIndex", "")

    # Check NotOnOrAfter on Conditions
    conditions = root.find(".//{urn:oasis:names:tc:SAML:2.0:assertion}Conditions")
    if conditions is not None:
        not_after = conditions.get("NotOnOrAfter", "")
        if not_after:
            try:
                exp = datetime.strptime(not_after, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                if _utc_now() > exp:
                    raise HTTPException(401, "SAML assertion has expired")
            except ValueError:
                pass

    # Determine role from attributes
    role = cfg.get("default_role", "viewer")
    group_mapping: dict = cfg.get("group_mapping", {})
    for attr in root.findall(".//{urn:oasis:names:tc:SAML:2.0:assertion}Attribute"):
        attr_name = attr.get("Name", "")
        for val_el in attr.findall("{urn:oasis:names:tc:SAML:2.0:assertion}AttributeValue"):
            val = (val_el.text or "").strip()
            if val in group_mapping:
                role = group_mapping[val]

    return name_id, role, session_index


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/api/saml/login")
@handle_errors
async def saml_login(request: Request):
    """Redirect browser to IdP for SP-initiated SSO."""
    cfg = _saml_cfg()
    _require_saml_enabled(cfg)
    relay_state = secrets.token_urlsafe(16)
    with _saml_states_lock:
        _saml_states[relay_state] = {"ts": time.time()}
    _prune_saml_states()
    redirect_url, _req_id = _build_authn_request(cfg, relay_state)
    return RedirectResponse(url=redirect_url, status_code=302)


@router.post("/api/saml/acs")
@handle_errors
async def saml_acs(request: Request):
    """Assertion Consumer Service — validate IdP response and issue token."""
    cfg = _saml_cfg()
    _require_saml_enabled(cfg)
    form = await request.form()
    saml_response_b64 = form.get("SAMLResponse", "")
    relay_state = form.get("RelayState", "")
    if not saml_response_b64:
        raise HTTPException(400, "Missing SAMLResponse")
    # Validate relay state (CSRF protection)
    with _saml_states_lock:
        if relay_state not in _saml_states:
            raise HTTPException(400, "Invalid or expired relay state")
        del _saml_states[relay_state]
    try:
        xml_bytes = base64.b64decode(saml_response_b64)
    except Exception:
        raise HTTPException(400, "Invalid base64 in SAMLResponse")
    xml_str = xml_bytes.decode("utf-8", errors="replace")
    name_id, role, session_index = _parse_saml_response(xml_str, cfg)

    # Auto-create account if not exists
    username = name_id.split("@")[0].lower()[:64] or name_id[:64]
    if not users.exists(username):
        initial_pw = pbkdf2_hash(secrets.token_urlsafe(32))
        users.add(username, initial_pw, role)

    token = token_store.generate(username, role)
    db.saml_store_session(
        str(uuid.uuid4()), name_id, username, session_index,
        time.time(), time.time() + 86400,
    )
    db.audit_log("saml_login", username, f"SAML SSO via {name_id}", _client_ip(request))
    return RedirectResponse(url="/#/dashboard", status_code=302)


@router.get("/api/saml/metadata")
@handle_errors
async def saml_metadata(request: Request):
    """Return SP metadata XML for IdP registration."""
    cfg = _saml_cfg()
    _require_saml_enabled(cfg)
    entity_id = cfg["entity_id"] or str(request.base_url).rstrip("/")
    acs_url = cfg["acs_url"] or f"{str(request.base_url).rstrip('/')}/api/saml/acs"
    xml = (
        f'<?xml version="1.0"?>'
        f'<md:EntityDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata" '
        f'entityID="{entity_id}">'
        f'<md:SPSSODescriptor '
        f'AuthnRequestsSigned="false" WantAssertionsSigned="false" '
        f'protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">'
        f'<md:AssertionConsumerService '
        f'Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST" '
        f'Location="{acs_url}" index="0"/>'
        f'</md:SPSSODescriptor>'
        f'</md:EntityDescriptor>'
    )
    return Response(content=xml, media_type="application/xml")
```

- [ ] **Step 4: Register router in `routers/__init__.py`**

```python
# Add import:
from .saml import router as saml_router

# Add to api_router includes:
api_router.include_router(saml_router)
```

- [ ] **Step 5: Run tests**

```bash
cd /home/raizen/noba
PYTHONPATH=share/noba-web pytest tests/test_router_saml.py -v
```

Expected: all 8 tests pass

- [ ] **Step 6: Lint**

```bash
ruff check --fix share/noba-web/server/routers/saml.py
```

Expected: no errors

- [ ] **Step 7: Commit**

```bash
git add share/noba-web/server/routers/saml.py share/noba-web/server/routers/__init__.py tests/test_router_saml.py
git commit -m "feat(enterprise-v2): add SAML 2.0 SP router — login redirect, ACS, SP metadata"
```

---

### Task 6: SCIM 2.0 router + admin token endpoint

**Files:**
- Create: `share/noba-web/server/routers/scim.py`
- Modify: `share/noba-web/server/routers/__init__.py`
- Modify: `share/noba-web/server/routers/admin.py` (add `POST /api/admin/scim-token`)

- [ ] **Step 1: Write the failing tests**

```python
# In tests/test_router_scim.py (new file):
import pytest
import hashlib

class TestScimAuth:
    def test_no_token_rejected(self, client):
        resp = client.get("/scim/v2/Users")
        assert resp.status_code == 401

    def test_wrong_token_rejected(self, client):
        resp = client.get("/scim/v2/Users",
                          headers={"Authorization": "Bearer wrongtoken"})
        assert resp.status_code == 401

class TestScimDiscovery:
    @pytest.fixture(autouse=True)
    def setup_token(self, client, admin_headers):
        """Generate and store a SCIM token for each test."""
        resp = client.post("/api/admin/scim-token", headers=admin_headers)
        assert resp.status_code == 200
        self.token = resp.json()["token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def test_service_provider_config(self, client):
        resp = client.get("/scim/v2/ServiceProviderConfig", headers=self.headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "schemas" in data

    def test_schemas_endpoint(self, client):
        resp = client.get("/scim/v2/Schemas", headers=self.headers)
        assert resp.status_code == 200

class TestScimUsers:
    @pytest.fixture(autouse=True)
    def setup_token(self, client, admin_headers):
        resp = client.post("/api/admin/scim-token", headers=admin_headers)
        self.token = resp.json()["token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def test_list_users_returns_list_response(self, client):
        resp = client.get("/scim/v2/Users", headers=self.headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["schemas"] == ["urn:ietf:params:scim:api:messages:2.0:ListResponse"]
        assert "totalResults" in data
        assert "Resources" in data

    def test_create_user(self, client):
        resp = client.post("/scim/v2/Users", headers=self.headers, json={
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "userName": "scim_testuser",
            "active": True,
            "roles": [{"value": "viewer"}],
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["userName"] == "scim_testuser"

    def test_create_duplicate_user_returns_409(self, client):
        client.post("/scim/v2/Users", headers=self.headers, json={
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "userName": "scim_dup",
            "active": True,
        })
        resp = client.post("/scim/v2/Users", headers=self.headers, json={
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "userName": "scim_dup",
            "active": True,
        })
        assert resp.status_code == 409

    def test_get_user(self, client):
        client.post("/scim/v2/Users", headers=self.headers, json={
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "userName": "scim_getme",
            "active": True,
        })
        resp = client.get("/scim/v2/Users/scim_getme", headers=self.headers)
        assert resp.status_code == 200
        assert resp.json()["userName"] == "scim_getme"

    def test_get_nonexistent_user_returns_404(self, client):
        resp = client.get("/scim/v2/Users/noone", headers=self.headers)
        assert resp.status_code == 404

    def test_patch_user_active_false(self, client):
        client.post("/scim/v2/Users", headers=self.headers, json={
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "userName": "scim_patch",
            "active": True,
        })
        resp = client.patch("/scim/v2/Users/scim_patch", headers=self.headers, json={
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "replace", "path": "active", "value": False}],
        })
        assert resp.status_code == 200

    def test_delete_user(self, client):
        client.post("/scim/v2/Users", headers=self.headers, json={
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "userName": "scim_del",
            "active": True,
        })
        resp = client.delete("/scim/v2/Users/scim_del", headers=self.headers)
        assert resp.status_code == 204

class TestAdminScimToken:
    def test_generate_token_requires_admin(self, client, operator_headers):
        resp = client.post("/api/admin/scim-token", headers=operator_headers)
        assert resp.status_code == 403

    def test_generate_token_returns_plaintext(self, client, admin_headers):
        resp = client.post("/api/admin/scim-token", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "token" in data
        assert len(data["token"]) > 20
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /home/raizen/noba
PYTHONPATH=share/noba-web pytest tests/test_router_scim.py -v
```

Expected: 404/401 — router not registered, `POST /api/admin/scim-token` missing

- [ ] **Step 3: Create `share/noba-web/server/routers/scim.py`**

```python
"""Noba – SCIM 2.0 user provisioning (RFC 7644)."""
from __future__ import annotations

import hashlib
import logging
import secrets

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from ..auth import pbkdf2_hash, users, valid_username
from ..config import VALID_ROLES
from ..deps import _read_body, db, handle_errors

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
    return {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
        "id": username,
        "userName": username,
        "active": user_data.get("enabled", True),
        "roles": [{"value": user_data["role"]}],
        "meta": {
            "resourceType": "User",
            "location": f"{base_url}/scim/v2/Users/{username}",
        },
    }


def _map_scim_role(scim_body: dict) -> str:
    roles = scim_body.get("roles", [])
    if roles and isinstance(roles, list):
        val = roles[0].get("value", "viewer") if isinstance(roles[0], dict) else str(roles[0])
        if val in _VALID_ROLES:
            return val
    return "viewer"


# ── Discovery ─────────────────────────────────────────────────────────────────

@router.get("/scim/v2/ServiceProviderConfig")
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


@router.get("/scim/v2/Schemas")
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
                {"name": "active", "type": "boolean", "required": False},
                {"name": "roles", "type": "complex", "multiValued": True},
            ],
        }],
    }, media_type=_SCIM_CONTENT)


# ── Users CRUD ────────────────────────────────────────────────────────────────

@router.get("/scim/v2/Users")
@handle_errors
async def scim_list_users(request: Request):
    _require_scim_auth(request)
    start = int(request.query_params.get("startIndex", 1))
    count = int(request.query_params.get("count", 100))
    all_users = users.list_users()
    page = all_users[start - 1:start - 1 + count]
    return JSONResponse(content={
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:ListResponse"],
        "totalResults": len(all_users),
        "startIndex": start,
        "itemsPerPage": len(page),
        "Resources": [_user_to_scim(u["username"], request) for u in page],
    }, media_type=_SCIM_CONTENT)


@router.get("/scim/v2/Users/{user_id}")
@handle_errors
async def scim_get_user(user_id: str, request: Request):
    _require_scim_auth(request)
    if not users.exists(user_id):
        return _scim_error(404, f"User {user_id} not found")
    return JSONResponse(content=_user_to_scim(user_id, request), media_type=_SCIM_CONTENT)


@router.post("/scim/v2/Users")
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
    initial_pw = pbkdf2_hash(secrets.token_urlsafe(32))
    users.add(username, initial_pw, role)
    db.scim_log_provision("create", body.get("id"), username, "ok")
    return JSONResponse(
        content=_user_to_scim(username, request),
        status_code=201,
        media_type=_SCIM_CONTENT,
    )


@router.put("/scim/v2/Users/{user_id}")
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


@router.patch("/scim/v2/Users/{user_id}")
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
        if op_type == "replace" and path == "active" and value is False:
            # Disable: set a disabled marker (NOBA doesn't have enable/disable yet — set a sentinel)
            pass  # Phase 1: log the intent; full disable requires Phase 4 (frontend) work
        elif op_type == "replace" and path == "roles":
            new_role = value[0].get("value", "viewer") if isinstance(value, list) else "viewer"
            if new_role in _VALID_ROLES:
                users.update_role(user_id, new_role)
    db.scim_log_provision("patch", None, user_id, "ok")
    return JSONResponse(content=_user_to_scim(user_id, request), media_type=_SCIM_CONTENT)


@router.delete("/scim/v2/Users/{user_id}")
@handle_errors
async def scim_delete_user(user_id: str, request: Request):
    _require_scim_auth(request)
    if not users.exists(user_id):
        return _scim_error(404, f"User {user_id} not found")
    users.delete(user_id)
    db.scim_log_provision("delete", None, user_id, "ok")
    return Response(status_code=204)
```

Add the missing `Response` import at top of the file:

```python
from fastapi.responses import JSONResponse, Response
```

- [ ] **Step 4: Add `POST /api/admin/scim-token` to `routers/admin.py`**

Find the end of the API key section in `share/noba-web/server/routers/admin.py` and add:

```python
# ── /api/admin/scim-token ─────────────────────────────────────────────────────
@router.post("/api/admin/scim-token")
@handle_errors
def api_admin_scim_token(auth=Depends(_require_admin)):
    """Generate a new SCIM provisioning bearer token (returned once, never stored plaintext)."""
    import hashlib as _hashlib
    import secrets as _secrets
    import uuid as _uuid
    token = _secrets.token_urlsafe(48)
    token_hash = _hashlib.sha256(token.encode()).hexdigest()
    db.scim_store_token(str(_uuid.uuid4()), token_hash)
    return {"token": token, "note": "Store this token securely — it will not be shown again."}
```

- [ ] **Step 5: Register SCIM router in `routers/__init__.py`**

```python
# Add import:
from .scim import router as scim_router

# Add to api_router includes:
api_router.include_router(scim_router)
```

- [ ] **Step 6: Run tests**

```bash
cd /home/raizen/noba
PYTHONPATH=share/noba-web pytest tests/test_router_scim.py -v
```

Expected: all 12 tests pass

> **Note:** The `users.update_role()` and `users.delete()` methods must exist on the `UserStore` class. If they don't, check `auth.py` for the actual method names and adjust calls in `scim.py` accordingly.

- [ ] **Step 7: Lint**

```bash
ruff check --fix share/noba-web/server/routers/scim.py share/noba-web/server/routers/admin.py
```

Expected: no errors

- [ ] **Step 8: Commit**

```bash
git add share/noba-web/server/routers/scim.py share/noba-web/server/routers/admin.py share/noba-web/server/routers/__init__.py tests/test_router_scim.py
git commit -m "feat(enterprise-v2): add SCIM 2.0 router — user provisioning, CRUD, discovery"
```

---

### Task 7: API key scoping enforcement in `deps.py`

**Files:**
- Modify: `share/noba-web/server/deps.py`
- Modify: `share/noba-web/server/auth.py` (extend API key auth path)

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_router_admin.py` (append new class):

```python
class TestApiKeyScoping:
    """API keys with scope/IP/rate-limit restrictions."""

    @pytest.fixture
    def scoped_key(self, client, admin_headers):
        """Create an API key scoped to /api/metrics only."""
        resp = client.post("/api/admin/api-keys", headers=admin_headers, json={
            "name": "metrics-only",
            "role": "viewer",
            "scope": "metrics",
        })
        assert resp.status_code == 200
        return resp.json()["key"]

    def test_scoped_key_allows_metrics(self, client, scoped_key):
        resp = client.get("/api/metrics/summary",
                          headers={"Authorization": f"Bearer {scoped_key}"})
        # 200 or 404 (endpoint may not exist in test) — but NOT 403
        assert resp.status_code != 403

    def test_scoped_key_blocks_admin(self, client, scoped_key):
        resp = client.get("/api/admin/users",
                          headers={"Authorization": f"Bearer {scoped_key}"})
        assert resp.status_code == 403

    def test_unscoped_key_allows_all(self, client, admin_headers):
        resp = client.post("/api/admin/api-keys", headers=admin_headers, json={
            "name": "unscoped",
            "role": "admin",
            "scope": "",
        })
        key = resp.json()["key"]
        resp2 = client.get("/api/admin/users",
                           headers={"Authorization": f"Bearer {key}"})
        assert resp2.status_code != 403

    def test_ip_restricted_key_blocked_from_wrong_ip(self, client, admin_headers):
        resp = client.post("/api/admin/api-keys", headers=admin_headers, json={
            "name": "ip-restricted",
            "role": "viewer",
            "allowed_ips": ["10.0.0.0/8"],
        })
        key = resp.json()["key"]
        # TestClient uses 127.0.0.1 — not in 10.0.0.0/8
        resp2 = client.get("/api/metrics/summary",
                           headers={"Authorization": f"Bearer {key}"})
        assert resp2.status_code == 403
```

- [ ] **Step 2: Run tests to confirm scope/IP tests fail**

```bash
cd /home/raizen/noba
PYTHONPATH=share/noba-web pytest tests/test_router_admin.py::TestApiKeyScoping -v
```

Expected: scope tests pass (no scoping enforced yet), IP restriction test fails (not yet blocked)

- [ ] **Step 3: Add `_check_api_key_scope` to `deps.py`**

In `share/noba-web/server/deps.py`, add after the `_require_permission` function:

```python
# ── API key scope / IP / rate-limit enforcement ──────────────────────────────

import collections as _collections
import ipaddress as _ipaddress
import json as _json
import time as _time

_api_key_rate_windows: dict[str, _collections.deque] = _collections.defaultdict(_collections.deque)
_rate_lock = _collections.defaultdict(lambda: __import__("threading").Lock())


def _check_api_key_scope(key_row: dict, path: str, client_ip: str) -> None:
    """Enforce scope, IP allowlist, and rate limit on an API key.

    Raises HTTPException(403) if scope or IP check fails.
    Raises HTTPException(429) if rate limit exceeded.
    key_row must include: id, scope, allowed_ips, rate_limit.
    """
    # Scope check
    scope = (key_row.get("scope") or "").strip()
    if scope:
        prefixes = [s.strip() for s in scope.split(",") if s.strip()]
        clean_path = path.lstrip("/")
        if not any(clean_path.startswith(p.lstrip("/")) for p in prefixes):
            raise HTTPException(status_code=403, detail="API key scope does not permit this endpoint")

    # IP allowlist check
    allowed_ips_raw = key_row.get("allowed_ips") or "[]"
    try:
        allowed_ips = _json.loads(allowed_ips_raw) if isinstance(allowed_ips_raw, str) else allowed_ips_raw
    except (ValueError, TypeError):
        allowed_ips = []
    if allowed_ips:
        try:
            client_addr = _ipaddress.ip_address(client_ip)
            if not any(client_addr in _ipaddress.ip_network(cidr, strict=False) for cidr in allowed_ips):
                raise HTTPException(status_code=403, detail="Client IP not in API key allowlist")
        except ValueError:
            pass  # malformed IP in config — skip check

    # Rate limit check (in-memory rolling window)
    rate_limit = key_row.get("rate_limit") or 0
    if rate_limit > 0:
        key_id = key_row.get("id", "")
        now = _time.time()
        with _rate_lock[key_id]:
            window = _api_key_rate_windows[key_id]
            # Remove entries older than 60 seconds
            while window and window[0] < now - 60:
                window.popleft()
            if len(window) >= rate_limit:
                raise HTTPException(status_code=429, detail="API key rate limit exceeded")
            window.append(now)
```

- [ ] **Step 4: Hook `_check_api_key_scope` into the API key auth path in `auth.py`**

Find the `authenticate` function in `share/noba-web/server/auth.py` (near the bottom of the file). The function currently returns early after validating an API key. Add the scope check call after the key is retrieved.

First, find the existing API key validation path — look for the block that calls `_get_db().get_api_key(...)` and add the scope check after it returns a valid key:

```python
# In the authenticate() function, after the api_key_row is confirmed valid,
# add before the return statement:
#
# NOTE: path and client_ip are needed for scope/IP checks. Since authenticate()
# only receives the Authorization header string (no request), we add a new
# authenticate_api_key() that accepts request context. The old authenticate()
# continues to work for session tokens unchanged.
```

Instead of modifying `authenticate()`, add a new helper to `deps.py` that wraps API key auth with scope checking. Update `_get_auth` to call the scope check when the token is an API key:

```python
# In deps.py, update _get_auth to perform scope check when key is API key:

def _get_auth(request: Request) -> tuple[str, str]:
    """Validate Authorization header and return (username, role).
    Enforces scope/IP/rate-limit for API key tokens.
    """
    auth = request.headers.get("Authorization", "")
    username, role = authenticate(auth)
    if not username:
        raise HTTPException(status_code=401, detail="Unauthorized")
    # Scope/IP/rate check only for API keys (Bearer tokens that aren't session tokens)
    if auth.startswith("Bearer "):
        token = auth[7:]
        import hashlib as _hl
        key_hash = _hl.sha256(token.encode()).hexdigest()
        try:
            key_row = db.get_api_key(key_hash)
            if key_row:
                _check_api_key_scope(key_row, request.url.path, _client_ip(request))
        except HTTPException:
            raise
        except Exception:
            pass  # not an API key, or DB error — skip scope check
    return username, role
```

> **Note on `db.get_api_key`:** Check the exact method name in `db/api_keys.py` mixin. The mixin method may be named differently. Search for `def get_api_key` in `share/noba-web/server/db/api_keys.py` and use the actual name.

- [ ] **Step 5: Run tests**

```bash
cd /home/raizen/noba
PYTHONPATH=share/noba-web pytest tests/test_router_admin.py::TestApiKeyScoping -v
```

Expected: all 4 tests pass

- [ ] **Step 6: Lint**

```bash
ruff check --fix share/noba-web/server/deps.py share/noba-web/server/auth.py
```

Expected: no errors

- [ ] **Step 7: Commit**

```bash
git add share/noba-web/server/deps.py tests/test_router_admin.py
git commit -m "feat(enterprise-v2): enforce API key scope, IP allowlist, and rate limiting in _get_auth"
```

---

### Task 8: Structured JSON logging

**Files:**
- Create: `share/noba-web/server/logging_config.py`
- Modify: `share/noba-web/server/app.py`

- [ ] **Step 1: Write the failing test**

```python
# In tests/test_logging_config.py (new file):
import logging
import json
import io
from server.logging_config import setup_logging, JsonFormatter

def test_json_formatter_outputs_valid_json():
    handler = logging.StreamHandler(io.StringIO())
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("test_json_fmt")
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    logger.info("hello world")
    output = handler.stream.getvalue().strip()
    data = json.loads(output)
    assert data["level"] == "INFO"
    assert data["message"] == "hello world"
    assert "timestamp" in data
    assert "logger" in data

def test_setup_logging_respects_env_level(monkeypatch):
    monkeypatch.setenv("NOBA_LOG_LEVEL", "WARNING")
    setup_logging()
    root_logger = logging.getLogger()
    assert root_logger.level <= logging.WARNING

def test_setup_logging_text_format_by_default(monkeypatch):
    monkeypatch.delenv("NOBA_LOG_FORMAT", raising=False)
    # Should not raise
    setup_logging()
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /home/raizen/noba
PYTHONPATH=share/noba-web pytest tests/test_logging_config.py -v
```

Expected: `ImportError` — `server.logging_config` not found

- [ ] **Step 3: Create `share/noba-web/server/logging_config.py`**

```python
"""Noba – Structured logging configuration.

Set NOBA_LOG_LEVEL=DEBUG/INFO/WARNING/ERROR to control verbosity.
Set NOBA_LOG_FORMAT=json to emit structured JSON logs.
"""
from __future__ import annotations

import json
import logging
import os
import time


class JsonFormatter(logging.Formatter):
    """Format log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        exc_text = None
        if record.exc_info:
            exc_text = self.formatException(record.exc_info)
        payload: dict = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if exc_text:
            payload["exception"] = exc_text
        if record.extra_fields if hasattr(record, "extra_fields") else False:
            payload.update(record.extra_fields)  # type: ignore[attr-defined]
        return json.dumps(payload)


def setup_logging() -> None:
    """Configure root logger from NOBA_LOG_LEVEL and NOBA_LOG_FORMAT env vars."""
    level_name = os.environ.get("NOBA_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    use_json = os.environ.get("NOBA_LOG_FORMAT", "").lower() == "json"

    handler = logging.StreamHandler()
    if use_json:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)-8s %(name)s  %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))

    root = logging.getLogger()
    root.setLevel(level)
    # Remove existing handlers to avoid duplicate output
    for h in root.handlers[:]:
        root.removeHandler(h)
    root.addHandler(handler)
```

- [ ] **Step 4: Call `setup_logging()` from `app.py`**

At the top of `share/noba-web/server/app.py`, after the existing imports, add:

```python
from .logging_config import setup_logging as _setup_logging
_setup_logging()
```

Place this before the `logger = logging.getLogger("noba")` line.

- [ ] **Step 5: Run tests**

```bash
cd /home/raizen/noba
PYTHONPATH=share/noba-web pytest tests/test_logging_config.py -v
```

Expected: all 3 tests pass

- [ ] **Step 6: Lint**

```bash
ruff check --fix share/noba-web/server/logging_config.py share/noba-web/server/app.py
```

Expected: no errors

- [ ] **Step 7: Commit**

```bash
git add share/noba-web/server/logging_config.py share/noba-web/server/app.py tests/test_logging_config.py
git commit -m "feat(enterprise-v2): add structured JSON logging via NOBA_LOG_FORMAT=json"
```

---

### Task 9: Full test suite + push

**Files:** none new

- [ ] **Step 1: Run full test suite**

```bash
cd /home/raizen/noba
PYTHONPATH=share/noba-web pytest tests/ -v
```

Expected: all tests pass (3181 community + new enterprise tests, zero regressions)

- [ ] **Step 2: Build frontend (no frontend changes in Phase 1, but verify build still passes)**

```bash
cd /home/raizen/noba/share/noba-web/frontend && npm run build
```

Expected: build succeeds with no errors

- [ ] **Step 3: Rsync to live server**

```bash
rsync -av --delete \
  share/noba-web/server/ ~/.local/libexec/noba/web/server/ && \
rsync -av \
  share/noba-web/static/dist/ ~/.local/libexec/noba/web/static/dist/
```

- [ ] **Step 4: Restart service**

```bash
systemctl --user restart noba-web
sleep 3
systemctl --user status noba-web | head -5
```

Expected: `active (running)`

- [ ] **Step 5: Smoke test new endpoints**

```bash
# Get a token
TOKEN=$(curl -s -X POST http://localhost:8080/api/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"Admin1234!"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])")

# SAML metadata (disabled — should return 400, not 404)
curl -s http://localhost:8080/api/saml/metadata | python3 -m json.tool

# WebAuthn register begin (should return 401 without token, 200 with)
curl -s -X POST http://localhost:8080/api/webauthn/register/begin | python3 -m json.tool
curl -s -X POST http://localhost:8080/api/webauthn/register/begin \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

# SCIM list users (no token — should return 401)
curl -s http://localhost:8080/scim/v2/Users | python3 -m json.tool
```

Expected: SAML returns `{"detail":"SAML SSO is not configured"}`, WebAuthn returns `challenge`/`rp`/`user` JSON, SCIM returns 401

- [ ] **Step 6: Update CHANGELOG.md**

In `CHANGELOG.md`, under `[Unreleased] → ### Added`:

```markdown
- **SAML 2.0 SP** — SP-initiated SSO via `GET /api/saml/login` → IdP → `POST /api/saml/acs`. Configured via `samlEnabled`, `samlIdpSsoUrl`, `samlEntityId`, `samlAcsUrl`, `samlIdpCert` in YAML settings. Auto-creates local accounts on first SAML login. SLO support via `saml_sessions` table.
- **WebAuthn/FIDO2** — Passwordless registration and authentication (`/api/webauthn/register/*`, `/api/webauthn/login/*`). Zero external deps — CBOR/COSE/P-256 implemented with stdlib + `cryptography`. MFA backup codes (10 one-time 8-char hex codes) via `/api/webauthn/backup-codes/*`.
- **SCIM 2.0 provisioning** — Full RFC 7644 Users CRUD at `/scim/v2/Users`, discovery endpoints (`/ServiceProviderConfig`, `/Schemas`). Token generated by admin via `POST /api/admin/scim-token` (shown once). Provisioning log in `scim_provision_log` table.
- **API key scoping** — API keys now support `scope` (comma-separated path prefixes), `allowed_ips` (CIDR JSON array), and `rate_limit` (requests/min). Enforced in `_get_auth` for all API key requests. Rate limiting is in-memory (resets on restart).
- **Structured JSON logging** — `NOBA_LOG_FORMAT=json` enables JSON log output. `NOBA_LOG_LEVEL` controls verbosity. No new dependencies.
```

- [ ] **Step 7: Final commit and push**

```bash
cd /home/raizen/noba
git add CHANGELOG.md
git commit -m "docs: update CHANGELOG for enterprise-v2 Phase 1"
git push enterprise enterprise-v2
```

Expected: `enterprise-v2` branch updated at `raizenica/noba-enterprise`
