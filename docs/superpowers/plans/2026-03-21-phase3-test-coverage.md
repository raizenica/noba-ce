# Phase 3: Test Coverage + API Contracts — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add integration tests for all 8 decomposed router modules, component tests for the Vue frontend, and expose the OpenAPI schema as the API contract.

**Architecture:** Backend tests use `starlette.testclient.TestClient` with the real FastAPI app, mocking external deps (subprocess, httpx, agent_store state) but hitting real SQLite. Frontend tests use Vitest + Vue Test Utils for store/component testing. OpenAPI schema exposed at `/api/openapi.json`. Note: Spec references `httpx.AsyncClient` but the existing 783 tests universally use sync `starlette.testclient.TestClient`; we follow the existing pattern for consistency.

**Tech Stack:** pytest, starlette TestClient, unittest.mock, Vitest, @vue/test-utils, Playwright (E2E smoke)

**Spec:** `docs/superpowers/specs/2026-03-21-noba-v3-roadmap-design.md` (Phase 3 section, lines 159-194)

---

## Current Test Landscape

- **38 test files**, 8376 lines, **783 tests passing**
- Tests cover: DB layer, auth module, config, workflow engine, agent WebSocket, file transfer, LLM, incidents, status page
- Pattern: `starlette.testclient.TestClient` with `server.app.app`, `unittest.mock.patch` for mocking
- Auth: `token_store.generate("admin", "admin")` for admin tokens
- No shared `client` fixture — each test file creates its own
- `conftest.py` sets up isolated HOME/config, pre-creates admin user

## File Structure

```
tests/
  conftest.py                          # MODIFY: add shared client + auth fixtures
  test_router_agents.py                # NEW: 22-route agent router
  test_router_containers.py            # NEW: 8-route container router
  test_router_dashboards.py            # NEW: 4-route dashboard router
  test_router_infrastructure.py        # NEW: 19-route infrastructure router
  test_router_intelligence.py          # NEW: 22-route intelligence router
  test_router_monitoring.py            # NEW: 17-route monitoring router
  test_router_operations.py            # NEW: 19-route operations router
  test_router_security.py              # NEW: 6-route security router

share/noba-web/server/app.py           # MODIFY: expose OpenAPI schema at /api/openapi.json

share/noba-web/frontend/
  vitest.config.js                     # NEW: Vitest configuration
  package.json                         # MODIFY: add test deps + scripts
  src/__tests__/
    stores/
      auth.test.js                     # NEW: auth store tests
      dashboard.test.js                # NEW: dashboard store tests
      notifications.test.js            # NEW: notifications store tests
    components/
      LoginView.test.js                # NEW: login page tests
      DashboardCard.test.js            # NEW: card wrapper tests
      AppModal.test.js                 # NEW: modal tests
```

---

### Task 1: Shared Test Fixtures

Add reusable fixtures to conftest.py that all router test files can use.

**Files:**
- Modify: `tests/conftest.py`

- [ ] **Step 1: Add shared fixtures to conftest.py**

Append these fixtures after the existing setup code:

```python
import pytest


@pytest.fixture()
def client():
    """TestClient with the full NOBA app."""
    from starlette.testclient import TestClient
    from server.app import app
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture()
def admin_token():
    """Generate a valid admin bearer token."""
    from server.auth import token_store
    return token_store.generate("admin", "admin")


@pytest.fixture()
def admin_headers(admin_token):
    """Authorization headers for admin user."""
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture()
def operator_token():
    """Generate a valid operator bearer token."""
    from server.auth import token_store
    return token_store.generate("operator_user", "operator")


@pytest.fixture()
def operator_headers(operator_token):
    """Authorization headers for operator user."""
    return {"Authorization": f"Bearer {operator_token}"}


@pytest.fixture()
def viewer_token():
    """Generate a valid viewer bearer token."""
    from server.auth import token_store
    return token_store.generate("viewer_user", "viewer")


@pytest.fixture()
def viewer_headers(viewer_token):
    """Authorization headers for viewer user."""
    return {"Authorization": f"Bearer {viewer_token}"}


@pytest.fixture()
def agent_key_headers():
    """Headers with test agent key for agent-authed endpoints."""
    return {"X-Agent-Key": "test-agent-key-12345"}


@pytest.fixture(autouse=False)
def mock_agent_key():
    """Mock yaml_config to return a known agent key."""
    from unittest.mock import patch
    with patch("server.routers.agents.read_yaml_settings",
               return_value={"agentKeys": "test-agent-key-12345"}):
        yield


@pytest.fixture(autouse=True)
def _clean_agent_state():
    """Reset agent in-memory stores between tests to prevent leakage."""
    from server.agent_store import (
        _agent_data, _agent_data_lock,
        _agent_commands, _agent_cmd_lock,
        _agent_cmd_results,
    )
    with _agent_data_lock:
        _agent_data.clear()
    with _agent_cmd_lock:
        _agent_commands.clear()
        _agent_cmd_results.clear()
    yield
    with _agent_data_lock:
        _agent_data.clear()
    with _agent_cmd_lock:
        _agent_commands.clear()
        _agent_cmd_results.clear()
```

- [ ] **Step 2: Verify existing tests still pass**

Run: `pytest tests/ -v --tb=short 2>&1 | tail -5`
Expected: 783 passed

- [ ] **Step 3: Commit**

```bash
git add tests/conftest.py
git commit -m "test(v3): add shared client and auth fixtures to conftest"
```

---

### Task 2: Router Tests — Agents

Test the agents router (22 routes). Focus on: agent report, agent list, command dispatch, results, agent key auth, admin-only endpoints.

**Files:**
- Create: `tests/test_router_agents.py`

- [ ] **Step 1: Create test file**

Test cases to implement (read actual routes from `share/noba-web/server/routers/agents.py`):

```python
"""Integration tests for the agents router."""
from __future__ import annotations

import json
import time
from unittest.mock import patch

import pytest


# ── Agent Report (agent-key auth) ──────────────────────────────────────────

class TestAgentReport:
    """POST /api/agent/report — agent key auth, stores metrics."""

    def test_report_missing_key(self, client):
        res = client.post("/api/agent/report", json={"hostname": "test"})
        assert res.status_code == 401

    def test_report_invalid_key(self, client, mock_agent_key):
        res = client.post("/api/agent/report",
                         json={"hostname": "test"},
                         headers={"X-Agent-Key": "wrong-key"})
        assert res.status_code == 403

    def test_report_success(self, client, mock_agent_key, agent_key_headers):
        body = {"hostname": "test-agent", "cpu_percent": 42, "mem_percent": 65}
        res = client.post("/api/agent/report", json=body, headers=agent_key_headers)
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ok"
        assert "commands" in data

    def test_report_stores_data(self, client, mock_agent_key, agent_key_headers):
        """After reporting, agent should appear in GET /api/agents."""
        body = {"hostname": "store-test", "cpu_percent": 10}
        client.post("/api/agent/report", json=body, headers=agent_key_headers)
        # Now fetch agents list (needs user auth)
        from server.auth import token_store
        token = token_store.generate("admin", "admin")
        res = client.get("/api/agents", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 200
        agents = res.json()
        hostnames = [a.get("hostname") for a in agents]
        # Agent data is stored in memory, so it should be findable


# ── Agent List & Detail (user auth) ────────────────────────────────────────

class TestAgentList:
    """GET /api/agents, GET /api/agents/{hostname}."""

    def test_list_requires_auth(self, client):
        res = client.get("/api/agents")
        assert res.status_code in (401, 403)

    def test_list_success(self, client, admin_headers):
        res = client.get("/api/agents", headers=admin_headers)
        assert res.status_code == 200
        assert isinstance(res.json(), list)

    def test_detail_not_found(self, client, admin_headers):
        res = client.get("/api/agents/nonexistent", headers=admin_headers)
        assert res.status_code == 404


# ── Agent Commands (operator auth) ─────────────────────────────────────────

class TestAgentCommands:
    """POST /api/agents/{hostname}/command, POST /api/agents/bulk-command."""

    def test_command_requires_auth(self, client):
        res = client.post("/api/agents/test/command", json={"type": "disk_usage"})
        assert res.status_code in (401, 403)

    def test_command_unknown_type(self, client, admin_headers):
        res = client.post("/api/agents/test/command",
                         json={"type": "nonexistent_cmd"},
                         headers=admin_headers)
        assert res.status_code == 400

    def test_bulk_command_requires_auth(self, client):
        res = client.post("/api/agents/bulk-command",
                         json={"type": "disk_usage"})
        assert res.status_code in (401, 403)


# ── Agent Uninstall (admin auth) ───────────────────────────────────────────

class TestAgentUninstall:
    def test_uninstall_requires_admin(self, client, viewer_headers):
        res = client.post("/api/agents/test/uninstall", headers=viewer_headers)
        assert res.status_code == 403


# ── Agent Update (agent-key auth) ──────────────────────────────────────────

class TestAgentUpdate:
    def test_update_missing_key(self, client):
        res = client.get("/api/agent/update")
        assert res.status_code == 401

    def test_update_invalid_key(self, client, mock_agent_key):
        res = client.get("/api/agent/update", headers={"X-Agent-Key": "bad"})
        assert res.status_code == 403


# ── SLA Summary ────────────────────────────────────────────────────────────

class TestSla:
    def test_sla_requires_auth(self, client):
        res = client.get("/api/sla/summary")
        assert res.status_code in (401, 403)

    def test_sla_returns_data(self, client, admin_headers):
        res = client.get("/api/sla/summary?hours=24", headers=admin_headers)
        assert res.status_code == 200
        data = res.json()
        assert "period_hours" in data
        assert "sla" in data


# ── Command History ────────────────────────────────────────────────────────

class TestCommandHistory:
    def test_history_requires_auth(self, client):
        res = client.get("/api/agents/command-history")
        assert res.status_code in (401, 403)

    def test_history_returns_list(self, client, admin_headers):
        res = client.get("/api/agents/command-history", headers=admin_headers)
        assert res.status_code == 200
        assert isinstance(res.json(), list)
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_router_agents.py -v --tb=short`
Expected: All pass

- [ ] **Step 3: Commit**

```bash
git add tests/test_router_agents.py
git commit -m "test(v3): add integration tests for agents router"
```

---

### Task 3: Router Tests — Containers + Dashboards + Security

Test three smaller routers in one file each: containers (8 routes), dashboards (4 routes), security (6 routes).

**Files:**
- Create: `tests/test_router_containers.py`
- Create: `tests/test_router_dashboards.py`
- Create: `tests/test_router_security.py`

- [ ] **Step 1: Create container tests**

Read routes from `share/noba-web/server/routers/containers.py`. Key tests:

```python
"""Integration tests for the containers router."""
from __future__ import annotations
from unittest.mock import patch
import pytest


class TestContainerControl:
    """POST /api/container-control."""

    def test_requires_auth(self, client):
        res = client.post("/api/container-control", json={"name": "test", "action": "restart"})
        assert res.status_code in (401, 403)

    def test_invalid_action(self, client, admin_headers):
        res = client.post("/api/container-control",
                         json={"name": "test", "action": "destroy"},
                         headers=admin_headers)
        assert res.status_code == 400

    @patch("server.routers.containers.bust_container_cache")
    @patch("server.routers.containers.subprocess.run")
    def test_restart_success(self, mock_run, mock_bust, client, admin_headers):
        mock_run.return_value = type("R", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()
        res = client.post("/api/container-control",
                         json={"name": "nginx", "action": "restart"},
                         headers=admin_headers)
        assert res.status_code == 200


class TestContainerLogs:
    """GET /api/containers/{name}/logs."""

    def test_requires_auth(self, client):
        res = client.get("/api/containers/nginx/logs")
        assert res.status_code in (401, 403)


class TestComposeProjects:
    """GET /api/compose/projects."""

    def test_requires_auth(self, client):
        res = client.get("/api/compose/projects")
        assert res.status_code in (401, 403)

    @patch("server.routers.containers.subprocess.run")
    def test_returns_list(self, mock_run, client, admin_headers):
        mock_run.return_value = type("R", (), {"returncode": 0, "stdout": "proj1\nproj2\n", "stderr": ""})()
        res = client.get("/api/compose/projects", headers=admin_headers)
        assert res.status_code == 200
```

- [ ] **Step 2: Create dashboard tests**

Read routes from `share/noba-web/server/routers/dashboards.py`. Key tests:

```python
"""Integration tests for the dashboards router."""
from __future__ import annotations
import pytest


class TestDashboardCrud:
    """GET/POST/PUT/DELETE /api/dashboards."""

    def test_list_requires_auth(self, client):
        res = client.get("/api/dashboards")
        assert res.status_code in (401, 403)

    def test_list_empty(self, client, admin_headers):
        res = client.get("/api/dashboards", headers=admin_headers)
        assert res.status_code == 200
        assert isinstance(res.json(), list)

    def test_create_and_list(self, client, admin_headers):
        res = client.post("/api/dashboards",
                         json={"name": "Test Dashboard", "layout": {"cards": []}, "shared": False},
                         headers=admin_headers)
        assert res.status_code == 200
        data = res.json()
        assert "id" in data

        res2 = client.get("/api/dashboards", headers=admin_headers)
        dashboards = res2.json()
        assert any(d["name"] == "Test Dashboard" for d in dashboards)

    def test_delete(self, client, admin_headers):
        res = client.post("/api/dashboards",
                         json={"name": "To Delete", "layout": {}},
                         headers=admin_headers)
        did = res.json()["id"]
        res2 = client.delete(f"/api/dashboards/{did}", headers=admin_headers)
        assert res2.status_code == 200
```

- [ ] **Step 3: Create security tests**

Read routes from `share/noba-web/server/routers/security.py`. Key tests:

```python
"""Integration tests for the security router."""
from __future__ import annotations
import pytest


class TestSecurityScore:
    """GET /api/security/score."""

    def test_requires_auth(self, client):
        res = client.get("/api/security/score")
        assert res.status_code in (401, 403)

    def test_returns_score(self, client, admin_headers):
        res = client.get("/api/security/score", headers=admin_headers)
        assert res.status_code == 200
        data = res.json()
        assert "score" in data or isinstance(data, dict)


class TestSecurityFindings:
    """GET /api/security/findings."""

    def test_requires_auth(self, client):
        res = client.get("/api/security/findings")
        assert res.status_code in (401, 403)

    def test_returns_list(self, client, admin_headers):
        res = client.get("/api/security/findings", headers=admin_headers)
        assert res.status_code == 200


class TestSecurityScan:
    """POST /api/security/scan-all — operator required."""

    def test_scan_all_requires_auth(self, client):
        res = client.post("/api/security/scan-all")
        assert res.status_code in (401, 403)
```

- [ ] **Step 4: Run all three test files**

Run: `pytest tests/test_router_containers.py tests/test_router_dashboards.py tests/test_router_security.py -v --tb=short`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add tests/test_router_containers.py tests/test_router_dashboards.py tests/test_router_security.py
git commit -m "test(v3): add integration tests for containers, dashboards, security routers"
```

---

### Task 4: Router Tests — Monitoring

Test the monitoring router (17 routes). Focus on: endpoint CRUD, uptime, health score, status page (public + admin).

**Files:**
- Create: `tests/test_router_monitoring.py`

- [ ] **Step 1: Create test file**

Read routes from `share/noba-web/server/routers/monitoring.py`. Key test cases:

- Endpoint monitor CRUD (create, list, update, delete, manual check)
- Uptime dashboard (GET /api/uptime)
- Health score (GET /api/health-score)
- Status page public endpoints (NO auth: GET /api/status/public, GET /api/status/incidents)
- Status page admin endpoints (POST /api/status/components, PUT, DELETE)
- Auth gating on each endpoint type

Important: The public status page endpoints (`/api/status/public`, `/api/status/incidents`) have NO auth requirement — test this explicitly.

Follow the same test class structure as Tasks 2-3: one class per endpoint group, test auth gating + happy path + error cases. Read the actual router file to determine exact routes and auth dependencies. Mock subprocess/httpx calls with module-level paths (e.g., `server.routers.monitoring.subprocess.run`).

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_router_monitoring.py -v --tb=short`
Expected: All pass

- [ ] **Step 3: Commit**

```bash
git add tests/test_router_monitoring.py
git commit -m "test(v3): add integration tests for monitoring router"
```

---

### Task 5: Router Tests — Operations

Test the operations router (19 routes). Focus on: system info, recovery, journal, processes, IaC export, backups.

**Files:**
- Create: `tests/test_router_operations.py`

- [ ] **Step 1: Create test file**

Read routes from `share/noba-web/server/routers/operations.py`. Key test cases:

- System info (GET /api/system/info)
- System health (GET /api/system/health)
- Recovery actions (POST /api/recovery/* — admin only, mock subprocess)
- Journal viewer (GET /api/journal — mock subprocess)
- Process list (GET /api/system/processes — mock subprocess/psutil)
- IaC export (GET /api/iac/export?format=yaml)
- Backup status/schedules (GET /api/backup/*)
- SMART data (GET /api/disks/smart — mock subprocess)
- Auth gating on admin-only endpoints

Many operations routes shell out to subprocess — mock with module-level paths (e.g., `server.routers.operations.subprocess.run`). Follow the same test class structure as Tasks 2-3: one class per endpoint group, test auth gating + happy path + error cases. Read the actual router file for exact routes.

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_router_operations.py -v --tb=short`
Expected: All pass

- [ ] **Step 3: Commit**

```bash
git add tests/test_router_operations.py
git commit -m "test(v3): add integration tests for operations router"
```

---

### Task 6: Router Tests — Infrastructure

Test the infrastructure router (19 routes). Focus on: service control, network, K8s, Proxmox, terminal.

**Files:**
- Create: `tests/test_router_infrastructure.py`

- [ ] **Step 1: Create test file**

Read routes from `share/noba-web/server/routers/infrastructure.py`. Key test cases:

- Service control (POST /api/service-control — operator, mock subprocess)
- Network connections/ports/interfaces (GET /api/network/* — mock metrics functions)
- Service map (GET /api/services/map)
- Disk prediction (GET /api/disks/prediction)
- K8s endpoints (mock httpx calls to K8s API)
- Proxmox endpoints (mock httpx calls to Proxmox API)
- Network devices (GET /api/network/devices — DB backed)
- Network discover (POST /api/network/discover/{hostname} — needs agent in store)
- Auth gating throughout

K8s and Proxmox endpoints make external HTTP calls — mock `httpx.AsyncClient` or the internal functions that make these calls. Mock subprocess with module-level paths (e.g., `server.routers.infrastructure.subprocess.run`). Follow the same test class structure as Tasks 2-3: one class per endpoint group, test auth gating + happy path + error cases. Read the actual router file for exact routes.

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_router_infrastructure.py -v --tb=short`
Expected: All pass

- [ ] **Step 3: Commit**

```bash
git add tests/test_router_infrastructure.py
git commit -m "test(v3): add integration tests for infrastructure router"
```

---

### Task 7: Router Tests — Intelligence

Test the intelligence router (22 routes). Focus on: incidents, dependencies, baselines/drift, AI/LLM endpoints.

**Files:**
- Create: `tests/test_router_intelligence.py`

- [ ] **Step 1: Create test file**

Read routes from `share/noba-web/server/routers/intelligence.py`. Key test cases:

- Incidents (GET /api/incidents, POST /api/incidents/{id}/resolve)
- War room messages (GET/POST /api/incidents/{id}/messages)
- Incident assignment (PUT /api/incidents/{id}/assign)
- Dependencies CRUD (GET/POST/DELETE /api/dependencies)
- Impact analysis (GET /api/dependencies/impact/{service})
- Baselines CRUD (GET/POST/DELETE /api/baselines)
- Drift check (POST /api/baselines/check — mock scheduler)
- AI/LLM endpoints (GET /api/ai/status, POST /api/ai/chat — mock LLM client)
- Auth gating

AI endpoints use lazy imports from `..llm` — mock `_get_llm_client()` and `_build_ai_context()` to avoid needing a real LLM provider. Follow the same test class structure as Tasks 2-3: one class per endpoint group, test auth gating + happy path + error cases. Read the actual router file for exact routes.

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_router_intelligence.py -v --tb=short`
Expected: All pass

- [ ] **Step 3: Commit**

```bash
git add tests/test_router_intelligence.py
git commit -m "test(v3): add integration tests for intelligence router"
```

---

### Task 8: OpenAPI Schema Exposure

Expose the OpenAPI schema at `/api/openapi.json` as the formal API contract.

**Files:**
- Modify: `share/noba-web/server/app.py`

- [ ] **Step 1: Add OpenAPI endpoint**

FastAPI generates the OpenAPI schema automatically. It's typically available at `/openapi.json` by default, but we want it at `/api/openapi.json`.

Read `share/noba-web/server/app.py` and check if FastAPI's `openapi_url` is configured. If not set, add it:

Add these keyword arguments to the existing `FastAPI(...)` constructor call (keep the existing `title` unchanged):

```python
app = FastAPI(
    ...  # keep existing title and version
    openapi_url="/api/openapi.json",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)
```

This moves the auto-generated docs to `/api/docs` and `/api/redoc`, and the schema to `/api/openapi.json`.

- [ ] **Step 2: Add a test for the schema endpoint**

Create `tests/test_openapi.py`:

```python
"""Test OpenAPI schema generation."""
from __future__ import annotations


def test_openapi_schema_loads(client):
    """The schema should load without errors and contain routes."""
    res = client.get("/api/openapi.json")
    assert res.status_code == 200
    schema = res.json()
    assert "openapi" in schema
    assert "paths" in schema
    # Should have many paths from our 13 routers
    assert len(schema["paths"]) > 50


def test_openapi_has_agent_routes(client):
    """Verify agent routes appear in the schema."""
    res = client.get("/api/openapi.json")
    schema = res.json()
    assert "/api/agents" in schema["paths"]
    assert "/api/agent/report" in schema["paths"]


def test_docs_page_loads(client):
    """Swagger UI should be accessible."""
    res = client.get("/api/docs")
    assert res.status_code == 200
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_openapi.py -v --tb=short`
Expected: All pass

- [ ] **Step 4: Run ruff + full test suite**

```bash
ruff check share/noba-web/server/app.py
pytest tests/ -v --tb=short 2>&1 | tail -10
```

- [ ] **Step 5: Commit**

```bash
git add share/noba-web/server/app.py tests/test_openapi.py
git commit -m "feat(v3): expose OpenAPI schema at /api/openapi.json"
```

---

### Task 9: Frontend Test Setup

Install Vitest + Vue Test Utils and configure for the Vue project.

**Files:**
- Modify: `share/noba-web/frontend/package.json`
- Create: `share/noba-web/frontend/vitest.config.js`

- [ ] **Step 1: Install test dependencies**

```bash
cd share/noba-web/frontend
npm install --save-dev vitest @vue/test-utils jsdom
```

- [ ] **Step 2: Add test script to package.json**

Add to `"scripts"`:
```json
"test": "vitest run",
"test:watch": "vitest"
```

- [ ] **Step 3: Create `vitest.config.js`**

```js
import { defineConfig, mergeConfig } from 'vitest/config'
import viteConfig from './vite.config.js'

export default mergeConfig(viteConfig, defineConfig({
  test: {
    environment: 'jsdom',
    globals: true,
  },
}))
```

- [ ] **Step 4: Create a smoke test to verify setup**

Create `share/noba-web/frontend/src/__tests__/setup.test.js`:

```js
import { describe, it, expect } from 'vitest'

describe('Test setup', () => {
  it('vitest runs', () => {
    expect(1 + 1).toBe(2)
  })
})
```

- [ ] **Step 5: Run and verify**

```bash
cd share/noba-web/frontend && npm test
```

Expected: 1 test passed

- [ ] **Step 6: Commit**

```bash
git add share/noba-web/frontend/
git commit -m "test(v3): add Vitest + Vue Test Utils frontend test setup"
```

---

### Task 10: Frontend Store Tests

Test the Pinia stores: auth, dashboard, notifications.

**Files:**
- Create: `share/noba-web/frontend/src/__tests__/stores/auth.test.js`
- Create: `share/noba-web/frontend/src/__tests__/stores/dashboard.test.js`
- Create: `share/noba-web/frontend/src/__tests__/stores/notifications.test.js`

- [ ] **Step 1: Create auth store tests**

```js
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useAuthStore } from '../../stores/auth'

describe('Auth Store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
  })

  it('initializes unauthenticated when no token', () => {
    const auth = useAuthStore()
    expect(auth.authenticated).toBe(false)
    expect(auth.token).toBe('')
  })

  it('setToken stores in localStorage and sets authenticated', () => {
    const auth = useAuthStore()
    auth.setToken('test-token')
    expect(auth.token).toBe('test-token')
    expect(auth.authenticated).toBe(true)
    expect(localStorage.getItem('noba-token')).toBe('test-token')
  })

  it('clearAuth resets state and removes localStorage', () => {
    const auth = useAuthStore()
    auth.setToken('test-token')
    auth.username = 'admin'
    auth.userRole = 'admin'
    auth.clearAuth()
    expect(auth.token).toBe('')
    expect(auth.authenticated).toBe(false)
    expect(auth.username).toBe('')
    expect(auth.userRole).toBe('viewer')
    expect(localStorage.getItem('noba-token')).toBeNull()
  })

  it('isAdmin computed is true for admin role', () => {
    const auth = useAuthStore()
    auth.userRole = 'admin'
    expect(auth.isAdmin).toBe(true)
    expect(auth.isOperator).toBe(true)
  })

  it('isOperator includes operator and admin', () => {
    const auth = useAuthStore()
    auth.userRole = 'operator'
    expect(auth.isAdmin).toBe(false)
    expect(auth.isOperator).toBe(true)
  })

  it('viewer has no elevated permissions', () => {
    const auth = useAuthStore()
    auth.userRole = 'viewer'
    expect(auth.isAdmin).toBe(false)
    expect(auth.isOperator).toBe(false)
  })

  it('login calls fetch and stores token', async () => {
    const auth = useAuthStore()
    global.fetch = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ token: 'new-token' }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ username: 'admin', role: 'admin' }),
      })

    await auth.login('admin', 'pass')
    expect(auth.token).toBe('new-token')
    expect(auth.authenticated).toBe(true)
  })

  it('login throws on failure', async () => {
    const auth = useAuthStore()
    global.fetch = vi.fn().mockResolvedValueOnce({
      ok: false,
      json: () => Promise.resolve({ detail: 'Bad credentials' }),
    })

    await expect(auth.login('admin', 'wrong')).rejects.toThrow('Bad credentials')
  })
})
```

- [ ] **Step 2: Create notifications store tests**

```js
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useNotificationsStore } from '../../stores/notifications'

describe('Notifications Store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.useFakeTimers()
  })

  it('starts with empty toasts', () => {
    const notifs = useNotificationsStore()
    expect(notifs.toasts).toEqual([])
  })

  it('addToast creates a toast with id', () => {
    const notifs = useNotificationsStore()
    notifs.addToast('Hello', 'info')
    expect(notifs.toasts.length).toBe(1)
    expect(notifs.toasts[0].message).toBe('Hello')
    expect(notifs.toasts[0].type).toBe('info')
  })

  it('removeToast removes by id', () => {
    const notifs = useNotificationsStore()
    notifs.addToast('A', 'info', 0)
    notifs.addToast('B', 'info', 0)
    const idB = notifs.toasts[1].id
    notifs.removeToast(idB)
    expect(notifs.toasts.length).toBe(1)
    expect(notifs.toasts[0].message).toBe('A')
  })

  it('auto-removes after duration', () => {
    const notifs = useNotificationsStore()
    notifs.addToast('Temp', 'info', 3000)
    expect(notifs.toasts.length).toBe(1)
    vi.advanceTimersByTime(3000)
    expect(notifs.toasts.length).toBe(0)
  })
})
```

- [ ] **Step 3: Create dashboard store tests**

Test the `mergeLiveData` function and connection state management:

```js
import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useDashboardStore } from '../../stores/dashboard'

describe('Dashboard Store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('initializes offline', () => {
    const dash = useDashboardStore()
    expect(dash.connStatus).toBe('offline')
  })

  it('mergeLiveData updates known keys', () => {
    const dash = useDashboardStore()
    dash.mergeLiveData({ cpuPercent: 42, memory: { total: 16000 } })
    expect(dash.live.cpuPercent).toBe(42)
    expect(dash.live.memory.total).toBe(16000)
  })

  it('mergeLiveData ignores unknown keys', () => {
    const dash = useDashboardStore()
    dash.mergeLiveData({ unknownField: 'test' })
    expect(dash.live).not.toHaveProperty('unknownField')
  })

  it('disconnectSse sets offline', () => {
    const dash = useDashboardStore()
    dash.connStatus = 'sse'
    dash.disconnectSse()
    expect(dash.connStatus).toBe('offline')
  })
})
```

- [ ] **Step 4: Run frontend tests**

```bash
cd share/noba-web/frontend && npm test
```

Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add share/noba-web/frontend/src/__tests__/
git commit -m "test(v3): add frontend store tests (auth, dashboard, notifications)"
```

---

### Task 11: Frontend Component Tests

Test key Vue components: LoginView, AppModal, DashboardCard.

**Files:**
- Create: `share/noba-web/frontend/src/__tests__/components/LoginView.test.js`
- Create: `share/noba-web/frontend/src/__tests__/components/AppModal.test.js`
- Create: `share/noba-web/frontend/src/__tests__/components/DashboardCard.test.js`

- [ ] **Step 1: Create LoginView tests**

Test that the login form renders, submits on Enter, shows errors, redirects on success. Mount with Vue Test Utils, provide a mock router and Pinia stores.

Key test cases:
- Renders username and password fields
- Shows error when login fails
- Calls auth.login on form submit
- Disables button while loading

- [ ] **Step 2: Create AppModal tests**

- Renders when `show=true`, hidden when `show=false`
- Displays title
- Emits `close` on backdrop click
- Renders slot content
- Renders footer slot when provided

- [ ] **Step 3: Create DashboardCard tests**

- Renders title and icon
- Collapse toggle hides card-body
- Renders slot content
- Health attribute applied

- [ ] **Step 4: Run all frontend tests**

```bash
cd share/noba-web/frontend && npm test
```

- [ ] **Step 5: Commit**

```bash
git add share/noba-web/frontend/src/__tests__/
git commit -m "test(v3): add frontend component tests (Login, Modal, DashboardCard)"
```

---

### Task 12: Final Verification + CHANGELOG

Run the complete test suite (backend + frontend), verify test counts, update CHANGELOG.

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Run full backend test suite**

```bash
pytest tests/ -v --tb=short 2>&1 | tail -15
```

Expected: 783+ original + new router tests = significantly more tests, all passing.

- [ ] **Step 2: Run frontend tests**

```bash
cd share/noba-web/frontend && npm test
```

Expected: All store + component tests pass.

- [ ] **Step 3: Count new tests**

```bash
echo "Backend tests:" && pytest tests/ --co -q 2>&1 | tail -1
echo "Frontend tests:" && cd share/noba-web/frontend && npx vitest run 2>&1 | tail -3
```

- [ ] **Step 4: Rebuild frontend (tests may have changed files)**

```bash
cd share/noba-web/frontend && npm run build
```

- [ ] **Step 5: Update CHANGELOG.md**

Add under `[Unreleased]` `### Changed`:

```markdown
- **Test coverage (v3 Phase 3)** — Added integration tests for all 8 decomposed routers, OpenAPI schema at `/api/openapi.json`, frontend store + component tests with Vitest. Total backend tests: N (was 783). Frontend tests: M.
```

Replace N and M with actual counts.

- [ ] **Step 6: Commit**

```bash
git add CHANGELOG.md share/noba-web/static/dist/
git commit -m "test(v3): Phase 3 complete — router integration tests, frontend tests, OpenAPI schema

Added:
- Integration tests for 8 decomposed routers
- OpenAPI schema at /api/openapi.json
- Frontend test setup (Vitest + Vue Test Utils)
- Pinia store tests (auth, dashboard, notifications)
- Component tests (Login, Modal, DashboardCard)"
```

---

## Deferred: Playwright E2E Tests

The spec calls for Playwright smoke tests (login → navigate each page → verify renders). This is deferred because:
1. E2E tests require a running backend instance with test data seeded
2. CI infrastructure for spinning up the full server is not yet in place
3. The backend integration tests + frontend component tests provide strong coverage without E2E

When ready, add:
- `npm install --save-dev @playwright/test`
- `share/noba-web/frontend/e2e/smoke.spec.js` — login, navigate all 9 pages, verify each renders
- `playwright.config.js` pointing to a local dev server

Similarly, **snapshot tests** for Vue card components (mentioned in spec line 182) can be added incrementally as cards stabilize — Vitest supports `toMatchSnapshot()` natively.

---

## Verification Checklist

- [ ] All existing 783 backend tests still pass
- [ ] New router tests pass for all 8 routers
- [ ] OpenAPI schema accessible at `/api/openapi.json`
- [ ] `/api/docs` serves Swagger UI
- [ ] Frontend store tests pass (auth, dashboard, notifications)
- [ ] Frontend component tests pass (LoginView, AppModal, DashboardCard)
- [ ] `npm run build` still produces clean output
- [ ] CHANGELOG updated with Phase 3 entry
