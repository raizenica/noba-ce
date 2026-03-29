# Enterprise Frontend — Design Spec

**Date:** 2026-03-27
**Branch:** `enterprise-v2`
**Scope:** Four new admin-only Settings tabs (SAML, SCIM, WebAuthn, Database) + enterprise setup documentation

---

## Goal

Surface all enterprise backend features (SAML SSO, SCIM provisioning, WebAuthn passkeys, PostgreSQL backend) as fully manageable UI panels inside the existing Settings view. Admins configure everything from the browser — no SSH, no env file editing for runtime config.

---

## Architecture

### Frontend

Four new tab components added to `SettingsView.vue`, each following the exact existing pattern (`field-input`, `btn`, `actionMsg`, `useApi`, `useAuthStore`). All four are `admin: true`.

```
src/components/settings/
  SamlTab.vue        — SAML SSO config form + test connection
  ScimTab.vue        — SCIM token management + provisioning status
  WebAuthnTab.vue    — Passkey list per user, admin revoke
  DatabaseTab.vue    — Backend status (SQLite/PostgreSQL), pool info, migration snippet
```

### Backend

One new router `routers/enterprise.py` handles all enterprise-specific read/write endpoints. Registered in `routers/__init__.py`. SAML config keys added to `WEB_KEYS` in `config.py` so `write_yaml_settings` persists them.

Existing endpoints already sufficient: `POST /api/admin/scim-token` (token generation), `DELETE /api/webauthn/credential` (passkey delete) — extended or reused.

---

## Tab Designs

### SAML Tab

**Reads/writes via:** `GET/PUT /api/enterprise/saml` (reads/writes YAML config keys)

**Form fields:**
- `samlEnabled` — toggle checkbox, "Enable SAML SSO"
- `samlIdpSsoUrl` — text, "IdP SSO URL"
- `samlIdpCert` — textarea, "IdP Certificate (PEM)", monospace font
- `samlEntityId` — text, "SP Entity ID" (defaults to server origin)
- `samlAcsUrl` — text, "Assertion Consumer Service URL" (auto-filled, editable)
- `samlDefaultRole` — select: viewer / operator / admin, "Default role for new SAML users"
- `samlGroupMapping` — textarea (JSON), "Role mapping (JSON): `{"Admins": "admin"}`"

**Read-only info section:**
- SP Metadata URL: `<origin>/api/saml/metadata` — copy button
- SP ACS URL: same as samlAcsUrl — copy button

**Actions:**
- "Save" → `PUT /api/enterprise/saml`
- "Test Connection" → `POST /api/enterprise/saml/test` — sends HEAD to IdP SSO URL, returns `{ok: bool, status: int, latency_ms: int}`

**State:** `actionMsg` for save/test feedback. Inline error if test fails.

---

### SCIM Tab

**Reads via:** `GET /api/enterprise/scim/status`
**Token generation:** `POST /api/admin/scim-token` (already exists)

**Display:**
- Status badge: Active / No token
- Token expiry date (from `scim_tokens` table)
- Token value: masked (`••••••••`), show-once after generation (displayed in yellow banner, dismissed on close)
- SCIM Base URL: `<origin>/api/scim/v2` — copy button (for pasting into Okta / Azure AD)
- Supported resources: Users (read-only list)
- Last provisioning activity: timestamp of most recent SCIM request (from audit log, or N/A)

**Actions:**
- "Generate Token" (if no active token) / "Rotate Token" (if active) → `POST /api/admin/scim-token`
- Show new token in a dismissable banner with copy button; never shown again after dismiss

---

### WebAuthn Tab

**Reads via:** `GET /api/enterprise/webauthn/credentials` — returns all users' passkeys
**Revoke via:** `DELETE /api/enterprise/webauthn/credentials/{username}/{credential_id}`

**Display:**
- Table: Username | Passkey Name | Registered | Last Used | Action
- Grouped by user (collapsible rows optional, simple flat list acceptable)
- "Revoke" button per row → confirm modal → DELETE

**Empty state:** "No passkeys registered. Users can register passkeys from the login screen."

**Note:** Users register their own passkeys via `POST /api/webauthn/register/begin|complete`. This tab is management/audit only.

---

### Database Tab

**Reads via:** `GET /api/enterprise/db/status`

**SQLite response:**
```json
{"backend": "sqlite", "path": "~/.local/share/noba-history.db", "wal_mode": true}
```

**PostgreSQL response:**
```json
{"backend": "postgresql", "connected": true, "server_version": "15.2",
 "database": "noba", "host": "localhost", "pool_min": 1, "pool_max": 10}
```

**Display:**
- Backend badge: "SQLite" (grey) or "PostgreSQL" (green)
- SQLite: file path, WAL mode status
- PostgreSQL: host, database, server version, pool min/max, connection status (green/red dot)
- Migration section (shown only when backend is SQLite): collapsible "Migrate to PostgreSQL" panel showing the pre-filled shell command:
  ```bash
  DATABASE_URL=postgresql://user:pass@host/noba \
    python3 scripts/migrate-to-postgres.py ~/.local/share/noba-history.db
  ```
- `DATABASE_URL` is read-only (env var — displayed if set, masked if contains password, requires restart to change — shown as info note)

---

## New Backend Endpoints

All in `routers/enterprise.py`, all `Depends(_require_admin)`:

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/enterprise/saml` | Read SAML config from YAML |
| `PUT` | `/api/enterprise/saml` | Write SAML config to YAML |
| `POST` | `/api/enterprise/saml/test` | Test IdP SSO URL connectivity |
| `GET` | `/api/enterprise/scim/status` | SCIM token status + expiry |
| `GET` | `/api/enterprise/webauthn/credentials` | All users' passkeys |
| `DELETE` | `/api/enterprise/webauthn/credentials/{username}/{cred_id}` | Admin revoke passkey |
| `GET` | `/api/enterprise/db/status` | Database backend status |

---

## Config Keys (WEB_KEYS additions)

Add to `config.py` WEB_KEYS frozenset:

```python
"samlEnabled", "samlIdpSsoUrl", "samlIdpCert",
"samlEntityId", "samlAcsUrl", "samlDefaultRole", "samlGroupMapping",
```

---

## SettingsView.vue Changes

Add to `tabs` array (all `admin: true`):
```js
{ key: 'saml',     label: 'SAML SSO',  icon: 'fa-id-card',   admin: true },
{ key: 'scim',     label: 'SCIM',      icon: 'fa-sync-alt',  admin: true },
{ key: 'webauthn', label: 'WebAuthn',  icon: 'fa-fingerprint', admin: true },
{ key: 'database', label: 'Database',  icon: 'fa-server',    admin: true },
```

Add to `tabComponents`:
```js
saml:     defineAsyncComponent(() => import('../components/settings/SamlTab.vue')),
scim:     defineAsyncComponent(() => import('../components/settings/ScimTab.vue')),
webauthn: defineAsyncComponent(() => import('../components/settings/WebAuthnTab.vue')),
database: defineAsyncComponent(() => import('../components/settings/DatabaseTab.vue')),
```

---

## Documentation

### `docs/enterprise-setup.md`
Sections:
1. Prerequisites
2. SAML SSO setup (step-by-step: configure IdP → paste cert → test → enable)
3. SCIM provisioning (generate token → paste base URL into Okta/Azure AD)
4. PostgreSQL backend (set DATABASE_URL → start NOBA → run migration script)
5. WebAuthn passkeys (user enrollment flow, admin revoke)

### `README.md`
Add one line under a new `## Enterprise Edition` heading pointing to `docs/enterprise-setup.md`.

---

## Multi-Backend Extensibility Note

The `DATABASE_URL` adapter pattern supports additional backends without touching any domain module. MySQL would follow the identical pattern via a future `db/mysql_adapter.py`:

| Construct | PostgreSQL | MySQL (future) |
|---|---|---|
| Upsert | `ON CONFLICT (...) DO UPDATE SET` | `ON DUPLICATE KEY UPDATE` |
| Insert-or-ignore | `ON CONFLICT DO NOTHING` | `INSERT IGNORE` |
| Auto-increment | `SERIAL` | `INT AUTO_INCREMENT PRIMARY KEY` |
| lastrowid | `RETURNING id` | native `cursor.lastrowid` |
| Binary | `BYTEA` | `BLOB` (unchanged) |

`DatabaseBase._get_conn()` adds one `elif self._is_mysql` branch. The Database tab badge already shows the backend name from `DATABASE_URL` — MySQL would display as a third option automatically.

---

## What This Does NOT Include

- SAML signature verification with IdP cert (cert stored but verification deferred)
- Group/role mapping UI editor (JSON textarea — parsed on save)
- SCIM Groups resource (not implemented in backend)
- PostgreSQL DATABASE_URL inline editing (env var by design, requires restart)
- Multi-tenancy / org management (future phase)
