# NOBA Command Center -- Full Audit Report

**Date:** 2026-03-23
**Version:** 2.0.0 (commit cf42536)
**Scope:** Security, API Consistency, Code Quality, Test Coverage, Architecture, Static Analysis

---

## Executive Summary

| Domain | CRITICAL | HIGH | MEDIUM | LOW |
|--------|----------|------|--------|-----|
| Security | 3 | 5 | 7 | 5 |
| API Consistency | 0 | 3 | 8 | 5 |
| Code Quality | 0 | 5 | 7 | 7 |
| Test Coverage | 0 | 3 | 4 | 2 |
| Architecture | 0 | 1 | 4 | 3 |
| Static Analysis | 0 | 0 | 0 | 0 |
| **Total** | **3** | **17** | **30** | **22** |

**Ruff lint: 0 issues. All 2187 backend tests pass. All 91 frontend tests pass.**

The codebase is well-structured with strong conventions, but has 3 critical security vulnerabilities in the OAuth/OIDC flows and healing pipeline that need immediate attention.

---

## CRITICAL Findings (Fix Immediately)

### C1. OAuth2/OIDC Missing CSRF State Parameter
- **Domain:** Security
- **Location:** `routers/auth.py:233-252` (social login), `:447-462` (OIDC)
- **Issue:** Authorization redirects do not generate or validate a `state` parameter -- the primary CSRF defense in OAuth2.
- **Impact:** Attacker can craft a URL that links their social account to a victim's NOBA session, or force login as the attacker's account.
- **Fix:** Generate a cryptographically random `state`, store server-side, include in redirect, validate in callback.

### C2. Auth Token Leaked to OAuth Providers via State Parameter
- **Domain:** Security
- **Location:** `routers/auth.py:347-358`
- **Issue:** Account linking passes the user's NOBA session token as the OAuth2 `state` parameter: `"state": token`. This token is visible in URLs, browser history, server logs, and referrer headers.
- **Impact:** Third-party OAuth provider (Google, GitHub, etc.) receives the active session token. Any intermediary can hijack the session.
- **Fix:** Use a random nonce as `state`. Store a nonce-to-token mapping server-side and look it up in the callback.

### C3. Healing `run` Action Executes Arbitrary Shell Commands
- **Domain:** Security
- **Location:** `remediation.py:719-725`
- **Issue:** `_handle_run` takes a `command` parameter and passes it through `shlex.split()` to `subprocess.run()`. No allowlist or validation. The healing pipeline can auto-invoke this when trust level is "execute."
- **Impact:** Path from alert rule configuration to arbitrary RCE on the host as the NOBA service user.
- **Fix:** Remove `run` action type entirely, or require explicit admin approval for every invocation regardless of trust level. Add a command allowlist.

---

## HIGH Findings (Fix Soon)

### H1. API Key Expiry Not Enforced
- **Domain:** Security
- **Location:** `auth.py:655-662`
- **Issue:** `authenticate()` retrieves API key data but never checks `expires_at`. Expired keys continue to authenticate.
- **Fix:** Add `if key_data.get('expires_at') and key_data['expires_at'] < int(time.time()): return None, None`

### H2. Webhook SSRF in Remediation Handler
- **Domain:** Security
- **Location:** `remediation.py:728-742`
- **Issue:** `_handle_webhook` makes HTTP requests to URLs from action parameters with no SSRF protection. Internal/private network addresses are not blocked.
- **Fix:** Apply `_is_safe_url()` check or create a shared SSRF protection utility.

### H3. SSRF Bypass via DNS Resolution in Integration Instances
- **Domain:** Security
- **Location:** `routers/integration_instances.py:18-40`
- **Issue:** `_is_safe_url` only blocks IPs it can parse. Hostnames resolving to private IPs (e.g., `internal.local` -> `10.0.0.1`) pass validation. DNS rebinding also bypasses.
- **Fix:** Resolve hostname to IP before making request. Validate resolved IP against private ranges. Disable redirect following.

### H4. Agent Install Script Embeds Agent Key in Query Parameters
- **Domain:** Security
- **Location:** `routers/agents.py:876-878`
- **Issue:** Agent key passed via `?key=...` -- logged by proxies, visible in browser history.
- **Fix:** Generate single-use time-limited deployment tokens instead.

### H5. Terminal WebSocket Runs Unaudited Shell
- **Domain:** Security
- **Location:** `terminal.py:28-144`
- **Issue:** PTY spawns a login shell as the NOBA service user. Admin-only, but no command audit logging, no command blocklist, 30-minute default timeout.
- **Fix:** Log all terminal I/O to audit trail. Consider running shell as a lower-privilege user.

### H6. `POST /api/auth/totp/setup` Under-Protected
- **Domain:** API Consistency
- **Location:** `routers/auth.py:101`
- **Issue:** TOTP setup (generates cryptographic secret) uses `_get_auth` instead of `_require_operator`.
- **Fix:** Change to `Depends(_require_operator)`.

### H7. `GET /api/auth/social/{provider}/link` Has No Auth Dependency
- **Domain:** API Consistency
- **Location:** `routers/auth.py:338`
- **Issue:** No auth dependency. Manual token validation via query param bypasses the standard auth system.
- **Fix:** Add `Depends(_get_auth)` or use `_get_auth_sse` pattern.

### H8. `POST /api/reports/custom` Is a POST That Only Reads Data
- **Domain:** API Consistency
- **Location:** `routers/admin.py:721`
- **Issue:** POST method for a read-only report generation. No operator auth.
- **Fix:** Change to GET with query params, or add `_require_operator`.

### H9. `db/automations.py` Mixes 10 Unrelated Concerns (1468 lines)
- **Domain:** Code Quality
- **Location:** `db/automations.py`
- **Issue:** Automation CRUD, job runs, API keys, notifications, user dashboards, approval queue, maintenance windows, action audit, playbook templates, token persistence -- all in one file.
- **Fix:** Split into at least 4 files by domain.

### H10. `routers/agents.py` Covers 6 Domains (1224 lines)
- **Domain:** Code Quality
- **Location:** `routers/agents.py`
- **Issue:** Agent endpoints, WebSocket, terminal, log streaming, file transfer, network analysis.
- **Fix:** Split file transfer and terminal into separate routers.

### H11. Dead Modules: `approval_manager.py` and `agent_verify.py`
- **Domain:** Code Quality
- **Location:** `healing/approval_manager.py`, `healing/agent_verify.py`
- **Issue:** Neither module is imported anywhere in the codebase. Completely orphaned.
- **Fix:** Either wire them into the pipeline or remove them.

### H12. 69 `except Exception` Blocks Without `except HTTPException` Guard
- **Domain:** Code Quality
- **Location:** Across all routers (29 in `agents.py`, 4 in `admin.py`, 3 in `automations.py`, etc.)
- **Issue:** Convention says catch `HTTPException` before `Exception`. Without this, 401/403/404 errors are swallowed and returned as 500.
- **Fix:** Add `except HTTPException: raise` before every `except Exception` in route handlers.

### H13. `routers/admin.py` Router Has Zero Tests
- **Domain:** Test Coverage
- **Location:** `tests/` (missing `test_router_admin.py`)
- **Issue:** Admin router handles user management, system configuration, backup/restore -- all privileged operations. Zero test coverage.
- **Fix:** Add comprehensive test file covering auth levels and all admin operations.

### H14. 5 Complex Integrations Have Zero Tests
- **Domain:** Test Coverage
- **Location:** `integrations/hass.py`, `proxmox.py`, `truenas_ws.py`, `qbittorrent.py`, `pihole.py`
- **Issue:** These use cookies, WebSocket, and multi-step auth. No tests means credential handling and session management are unvalidated.
- **Fix:** Add test files for each with mocked HTTP/WS clients.

### H15. Healing Executor Has Only 4 Tests
- **Domain:** Test Coverage
- **Location:** `tests/test_heal_executor.py`
- **Issue:** The core self-healing execution pipeline has 4 tests. No timeout, concurrency, or exception propagation coverage.
- **Fix:** Expand to cover error paths, concurrent execution, timeout handling.

### H16. Blocking `subprocess.run()` in Async Routes
- **Domain:** Architecture
- **Location:** `routers/containers.py` (7 calls), `routers/operations.py` (12+ calls, includes `time.sleep(2)`), `routers/infrastructure.py`, `routers/integrations.py`, `routers/admin.py`
- **Issue:** Synchronous `subprocess.run()` in `async def` handlers blocks the entire asyncio event loop. A slow `docker compose up` freezes the web UI for all users.
- **Fix:** Wrap in `asyncio.to_thread()` or `loop.run_in_executor()`.

### H17. `users.role()` Method Does Not Exist -- Social Login Broken
- **Domain:** Security
- **Location:** `routers/auth.py:312-313`
- **Issue:** Social login callback calls `users.role(email)` but `UserStore` has no `role()` method. Would cause `AttributeError` at runtime.
- **Fix:** Change to `users.get(email)[1]` or add a `role()` method to `UserStore`.

---

## MEDIUM Findings

### API Consistency (8)
- `GET /api/settings` (admin.py:32) -- leaks partial config to non-admins via `_get_auth`
- `GET /api/backup/snapshots/{name}/browse` (admin.py:312) -- backup browsing open to viewers
- `GET /api/backup/snapshots/diff` (admin.py:345) -- snapshot diff open to viewers
- `GET /api/backup/file-versions` (admin.py:398) -- file versions open to viewers
- `GET /api/containers/stats` (containers.py:117) -- over-protected with `_require_operator` for read-only data
- `GET /api/compose/projects` (containers.py:176) -- over-protected with `_require_operator`
- `GET /api/system/update/check` (operations.py:505) -- performs `git fetch` side effect under `_get_auth`
- `POST /api/agents/{hostname}/stream-logs` (agents.py:780) -- over-protected with `_require_admin`

### Security (7)
- Journal regex allows partial ReDoS (operations.py:139)
- Settings endpoint leaks infrastructure URLs to non-admins (admin.py:32)
- LDAP injection partial mitigation -- missing `=` escape (auth.py:627)
- Integration instance update uses dynamic SQL column building (integration_instances.py:141)
- Webhook endpoint has no rate limiting (automations.py:821)
- Public status page leaks infrastructure component names (monitoring.py:84)
- Social login `users.role()` bug breaks social auth entirely (auth.py:312)

### Architecture (4)
- SQLite single-lock serialization negates WAL concurrent-read benefit (db/core.py)
- Foreign keys declared but never enforced -- `PRAGMA foreign_keys` never set ON (db/core.py)
- `_linked_providers` dict is memory-only, lost on restart (routers/auth.py:334)
- Plaintext credentials in YAML auto-backed up to 10 copies on disk

### Code Quality (7)
- `IntegrationsTab.vue` (1459 lines) -- 1263-line template of repeated form patterns
- `InfrastructureView.vue` (1094 lines) and `AutomationsView.vue` (1049 lines) oversized
- 35 integration functions in `simple.py` repeat identical httpx boilerplate
- 4 Vue components use raw `fetch()` instead of `useApi()` composable
- Duplicate reactive keys in `dashboard.js` store
- 5 shell scripts missing `set -e` error handling
- `noba-dashboard.sh` temp file without cleanup trap

### Test Coverage (4)
- `routers/stats.py` and `routers/integration_instances.py` have zero tests
- `collector.py` (data collection engine) untested
- Healing governor (5 tests) and planner (6 tests) too thin for safety-critical modules
- Frontend: 9 of 10 views have no tests

---

## LOW Findings

### Security (5)
- Token stored in localStorage (XSS exfiltration risk if XSS found)
- Kubernetes API calls disable TLS verification (`verify=False`)
- Proxmox API calls disable TLS verification
- Default admin password logged to console (recoverable from log aggregation)
- SSH key validation only checks prefix, not format or embedded commands

### API Consistency (5)
- `GET /api/alert-rules/test/{rule_id}` over-protected with `_require_admin`
- `POST /api/auth/totp/enable` uses `_get_auth` for self-service mutation
- Response pattern inconsistency (`{"status":"ok"}` vs `{"success":true}`)
- `/status` endpoint violates `/api/` prefix convention
- `DELETE /api/automations/{auto_id}` stricter than create/update (intentional)

### Code Quality (7)
- `main.py` missing `from __future__ import annotations`
- `db/core.py` 123 mechanical delegation wrappers
- `_register_category` skips lock (safe but inconsistent)
- 8 unused Vue imports
- `useIntervals()` composable exists but only used in 1 component
- 9 duplicated save-message timeout patterns across settings tabs
- `routers/admin.py` (920 lines) borderline oversized

### Architecture (3)
- Large frontend views (InfrastructureView 1094, AutomationsView 1049)
- Thread spawning without pool in healing executor and workflow engine
- Notification failure opacity -- no health check for broken notification channels

### Test Coverage (2)
- `deps.py`, `config.py`, `terminal.py` utility modules untested
- `healing/agent_runtime.py` has no test file

---

## Positive Findings

- **Ruff: 0 lint issues** across 29,696 lines of Python
- **Zero bare `except:` blocks** -- all exceptions are typed
- **Zero TODO/FIXME/HACK markers** -- clean codebase
- **All 2187 backend tests pass** in 53.57s
- **All 91 frontend tests pass** in 3.45s
- **No circular imports** detected
- **Condition evaluator is safe** -- uses strict regex parsing, not `eval()`
- **Subprocess calls generally well-protected** -- list-form arguments, no `shell=True`, service names validated with regex
- **Integration clients use dedicated httpx instances** -- no cookie leakage
- **All 111 Vue components use `<script setup>`** -- perfect consistency
- **Pinia stores have clean separation** -- no state duplication between stores
- **`install.sh` is well-written** -- `set -euo pipefail`, proper trap, mktemp
- **Test isolation is well-managed** -- conftest.py provides isolated HOME, agent state cleanup

---

## Recommended Fix Priority

### Phase 1: Critical Security (immediate)
1. Fix OAuth2/OIDC state parameter (C1, C2)
2. Restrict healing `run` action (C3)
3. Fix `users.role()` bug breaking social login (H17)
4. Enforce API key expiry (H1)

### Phase 2: High Security + Architecture (this week)
5. Add SSRF protection to webhook handler (H2)
6. Strengthen SSRF validation with DNS resolution (H3)
7. Wrap `subprocess.run()` in `asyncio.to_thread()` (H16)
8. Add `except HTTPException: raise` guards (H12)
9. Fix TOTP setup auth level (H6)
10. Fix social link auth dependency (H7)

### Phase 3: Test Coverage + Code Quality (next sprint)
11. Add tests for admin router (H13)
12. Add tests for complex integrations (H14)
13. Expand healing executor tests (H15)
14. Split `db/automations.py` (H9)
15. Split `routers/agents.py` (H10)
16. Wire or remove dead modules (H11)

### Phase 4: Medium Findings (ongoing)
17. Address remaining API auth level adjustments
18. Refactor `IntegrationsTab.vue` to data-driven approach
19. Enable `PRAGMA foreign_keys`
20. Add terminal audit logging
