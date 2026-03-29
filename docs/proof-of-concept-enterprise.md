# NOBA Enterprise — Proof of Concept

**Date:** 2026-03-29
**Version:** 2.0.0
**Duration:** 16+ hour continuous session — stabilization, development, security hardening, live testing
**Tested by:** Raizen (infrastructure owner) + Claude (development)

---

## Starting Point

The session began with a corrupted enterprise-v2 branch containing 55 untested self-evolving platform commits. Decision: burn everything back to the last stable commit (`0d2fbc8` — Tier 2-3 enterprise features), reset, and rebuild properly.

---

## Infrastructure

### Test Environment

| Host | IP | Site | Hardware | Role |
|------|-----|------|----------|------|
| pve | 192.168.100.70 | Site A (Dendermonde) | 32 threads (8c/4t), 64GB RAM | Primary PVE, Ollama (llama3:8b) |
| proxmoxa01 | 192.168.101.116 | Site A (Dendermonde) | Debian 13, Python 3.13 | Secondary PVE |
| pve-siteb | 192.168.50.70 | Site B (Remote) | 32GB RAM | Primary PVE |
| proxmoxb01 | 192.168.50.71 | Site B (Remote) | Debian 13, Python 3.13 | Secondary PVE |

### Additional Infrastructure Used

| Service | Location | Purpose |
|---------|----------|---------|
| Keycloak | localhost:8180 (Docker) | SAML IdP for SSO testing |
| Pi-hole v6 | 192.168.100.111 (dnsa01) | Integration testing |
| License Server | localhost:7777 | Ed25519 license signing |
| LXC 201 | 192.168.100.70 (PVE) | PostgreSQL + MySQL migration testing |

---

## What Was Built This Session

### SAML SSO (8 hours of iterative development)

The SAML implementation went through multiple architectural iterations before arriving at the correct pattern:

**Failed approaches (and why):**
1. Direct redirect with query param — hash routing lost the code
2. Inline script HTML response — blocked by CSP `script-src 'self'`
3. Non-httpOnly cookie with raw token — XSS vulnerability (caught by user)
4. httpOnly cookie with exchange code — `SameSite=lax` rejected on cross-origin POST
5. Server-side cookie exchange endpoint — stale browser cache served old JS
6. Full-page redirect to sso-callback — `App.vue` onMounted redirect to `/login` overrode it

**Working implementation:**
- Popup window pattern — login page stays put, SSO happens in popup
- Exchange code flow — ACS generates single-use 30s TTL code
- Intermediate `/api/saml/complete` endpoint handles cross-origin to same-origin transition
- SsoCallbackView exchanges code via POST, writes token to localStorage
- Main window polls localStorage, does full page reload on token detection
- SAML config requires admin password re-confirmation (`X-Confirm-Password` header)

**Tested with:** Keycloak (realm: noba, client: noba-enterprise, SAML protocol)
- Full browser flow: click SSO → Keycloak popup → authenticate → popup closes → dashboard loads
- Configured entirely through the Settings UI (not API injection)
- Test Connection button verified (requires host networking for Docker)

### OIDC / Social Login

Unified to same popup + exchange code pattern as SAML. Google, GitHub, Microsoft, Facebook presets plus generic OIDC — all route through `/api/saml/complete` → `/#/sso-callback?code=xxx`.

### Enterprise Feature Gating

- `_require_enterprise` dependency on all enterprise endpoints — returns 402 when unlicensed
- `_require_feature("saml")` and `_require_feature("webauthn")` for feature-specific gating
- Sidebar shows lock icons on enterprise tabs when unlicensed, redirects to License tab
- Freeze status endpoint (`_get_auth`) remains accessible to viewers

### SCIM 2.0 Completeness

- PATCH `displayName` — stored in UserStore 5-tuple, returned in SCIM responses
- PATCH `active=false` — disables user account, blocks login with 403 + audit log
- UserStore extended from 3-tuple `(hash, role, totp)` to 5-tuple `(hash, role, totp, display_name, disabled)` with backward-compatible file parsing

### License Management

- Full lifecycle tested: trial (60d) → upload signed `.noba-license` → licensed (363d) → remove → trial → re-upload
- License signing server at localhost:7777, n8n automation flow, offline CLI tool
- Perpetual model: features work forever after license support expires

### Pi-hole v6 Integration

- Auto-refresh: authenticate with password per request instead of storing static SID
- SID expires after 30 minutes — no longer an issue
- Tested: disable blocking for 5 seconds → auto re-enable confirmed

### RFC1918 Private IP Support

- Removed private IP block from `BaseIntegration.validate_url()` and `_is_safe_url()` in integration test-connection
- NOBA is designed for on-premises deployments — blocking 192.168.x.x broke the core use case
- Discovered during first-time setup with TrueNAS on private network

### Setup Wizard Polish

- Integration modal stays open after saving — user can add multiple services
- All completed steps remain clickable with "Edit" button (not grayed out "Done")
- Re-run wizard from Settings properly forces wizard display regardless of existing integrations
- IntegrationSetup form resets after each save for clean next-integration flow

---

## Bugs Found and Fixed

### Upgrade Path (9 bugs)

| Bug | Root Cause | Impact |
|-----|-----------|--------|
| Compliance report 500 | `db.get_latest_scores()` — wrong method name | API crash |
| Startup crash on upgrade | `tenant_id` index created before column exists | Server won't start |
| Missing tenant_id on 4 tables | No migration v7 for existing installs | Enterprise queries fail |
| Vault list 500 | `dict(row)` on raw tuples (no row_factory) | Vault unusable |
| Freeze list crash | Same `dict(r)` pattern | Freeze windows broken |
| Login restrict crash | Same `dict(r)` pattern | IP allowlist broken |
| Password policy crash | Same `dict(row)` pattern | Password policy broken |
| Alembic env.py | Raw psycopg2 instead of SQLAlchemy engine | PG migrations fail |
| Maintenance window 500 | str/ISO timestamp comparison | Active check crashes |

### UI/Frontend (4 bugs)

| Bug | Root Cause | Impact |
|-----|-----------|--------|
| Login page 500 flash | `auth/providers` return type `-> dict` but returns list | Page flashes on every load |
| HealingView crash | `addInterval` → `register` API mismatch | Healing page broken |
| SAML browser flow | App.vue redirect, missing public route, popup architecture | SSO unusable |
| License trial pill missing | AppHeader mounts before auth.isAdmin resolves | No trial countdown on bare metal |

### Security (7 findings)

| Finding | Severity | Fix |
|---------|----------|-----|
| SAML assertion signature not verified | Medium | Certificate comparison against configured IdP cert |
| Exchange endpoint not rate-limited | Medium | Rate limiter applied to `/api/auth/exchange` |
| SAML users get random password | Low | Changed to `!saml:disabled` (no password login) |
| Orphaned `_oidc_codes` dict | Low | Removed — OIDC uses shared exchange dict |
| Exchange codes unbounded growth | Low | Pruning on each new code generation |
| Debug logging in ACS | Info | Removed |
| Docker missing python-multipart | Build | Added to Dockerfile |

---

## Test Results

### Automated Tests

| Suite | Count | Result |
|-------|-------|--------|
| Backend (pytest) | 3,373 | All passing |
| Frontend (vitest) | 91 | All passing |
| Linting (ruff) | All files | Clean |
| GitHub CI (Tests + Docker + CodeQL) | 3 workflows | All green |

### Live Infrastructure Tests

**4-host cross-site test (final run):**

| Category | Tests | Result |
|----------|-------|--------|
| Cross-site connectivity matrix (all pairs) | 12 | All reachable |
| Per-host enterprise endpoints (20 each) | 80 | All 200 |
| Vault isolation (per-host secrets) | 4 | Confirmed isolated |
| License state verification | 4 | Correct (1 licensed, 3 trial) |
| **Total** | **100** | **0 failures** |

**Earlier session tests (2-site, before proxmoxa01/proxmoxb01):**

| Category | Tests |
|----------|-------|
| Core platform (dashboard, agents, healing, monitoring, security) | 30+ |
| Enterprise CRUD (vault, freeze, PW policy, IP allowlist, retention, RBAC, webhooks) | 21 |
| SCIM lifecycle (create, list, get, patch displayName, patch active, delete) | 10 |
| Exports (Ansible, Docker Compose, Shell) | 3 |
| Audit export | 1 |
| Pi-hole v6 toggle (disable/re-enable) | 1 |
| AI chat (4 prompts with llama3:8b) | 4 |
| Cross-site webhook, agent reporting, endpoint monitoring | 18 |
| Database migrations (PG stamp+upgrade, MySQL 60/60 tables) | 7 |

### SAML SSO Browser Test

Tested end-to-end through actual browser (not API):

1. Admin login via username/password — **Live** status confirmed
2. Navigate to Settings → SAML SSO — configure through UI form
3. Password confirmation prompt on save — verified
4. Test Connection button — green (host networking)
5. Logout → click "Sign in with SSO" → popup opens to Keycloak
6. Authenticate as `testuser` / `test123` in Keycloak popup
7. Popup processes exchange, writes token to localStorage, closes
8. Main window detects token, reloads to dashboard
9. `testuser` / `viewer` shown in sidebar — **correct**

---

## Security Posture

### Headers

```
Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self' data:; img-src 'self' data: blob: https: http:; connect-src 'self' wss: ws:
X-Content-Type-Options: nosniff
X-Frame-Options: SAMEORIGIN
Referrer-Policy: same-origin
Permissions-Policy: geolocation=(), microphone=(), camera=()
```

### Authentication

- PBKDF2-HMAC-SHA256 password hashing
- Per-IP rate limiting with automatic lockout
- Three-tier RBAC: viewer / operator / admin
- Enterprise endpoints require active license
- SAML config changes require password re-confirmation
- SSO users flagged with `!saml:disabled` — no password login
- Exchange codes: single-use, 30s TTL, rate-limited

### What's NOT Vulnerable

- No `shell=True` in subprocess calls
- No `eval()` or `exec()` — alert conditions use regex-only `safe_eval`
- No SQL injection — all queries parameterized
- No inline scripts — CSP enforced
- No tokens in cookies or URLs (exchange codes only)
- Secrets masked in settings API responses
- CORS defaults to no allowed origins

### Dependabot

- 0 open alerts (2 dismissed as false positives with documented reasoning)

---

## Deployment

NOBA Enterprise runs on:
- Python 3.10+ (tested 3.13, 3.14)
- Debian 12/13, Ubuntu 24.04, Fedora 43, Raspberry Pi OS
- SQLite (default), PostgreSQL 15+, MySQL/MariaDB 10.6+
- Docker (python:3.13-slim, ~309MB)

No external runtime dependencies beyond Python packages. Frontend is pre-built and committed — no Node.js needed in production.

---

## Lessons Learned

1. **Test in the actual browser** — API curl tests prove backend works but don't prove frontend integration. SAML SSO was declared "working" 3 times before actual browser testing revealed it wasn't.

2. **Browser caching kills deployments** — every Docker rebuild served correct assets but the browser loaded old `index.html`. Must verify asset hash matches between container and browser.

3. **SSO requires popup pattern** — full-page redirects through cross-origin IdPs break Vue Router state. The popup + localStorage + polling pattern is the correct architecture for SPAs.

4. **Never introduce known-vulnerable patterns** — non-httpOnly cookies for tokens, inline scripts for auth handoff. Under NIS2, any known vulnerability pattern is unacceptable.

5. **Private IPs are the norm for SMB** — blocking RFC1918 addresses broke the core on-premises use case. SSRF protection should guard against scheme abuse, not network topology.

6. **First-user experience matters most** — the setup wizard closing after one integration, grayed-out completed steps, and missing trial pill were all discovered during actual first-run testing on a fresh install.

---

## Conclusion

NOBA Enterprise is commercially ready. Every enterprise feature has been implemented, tested on live infrastructure across 4 Proxmox hosts at 2 physical sites, hardened through a manual security review, and validated through 3,373 automated tests plus 100+ live API tests. The SAML SSO flow works end-to-end through an actual browser with Keycloak as the IdP. All CI pipelines pass. Zero Dependabot alerts. Zero test failures.
