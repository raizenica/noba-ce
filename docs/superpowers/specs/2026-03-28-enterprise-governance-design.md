# Enterprise Governance Features — Design Spec
**Date:** 2026-03-28
**Branch:** enterprise-v2
**Status:** Approved → In Implementation

---

## Scope

Three tiers of enterprise differentiation features. This spec covers **Tier 1** in full detail. Tiers 2 and 3 are outlined for future implementation.

---

## Tier 1: Governance & Compliance (current sprint)

### 1. Audit Log UI + Export

**Goal:** Give admins a tenant-scoped, filterable, exportable view of all system actions.

**DB changes (v7 migration):**
- Add `tenant_id TEXT DEFAULT 'default'` to `audit` table
- Backfill existing rows to `'default'`
- Add index on `(tenant_id, timestamp DESC)`

**Backend:**
- `GET /api/enterprise/audit` — query params: `limit` (default 100, max 1000), `offset`, `username`, `action`, `from_ts`, `to_ts`. Returns tenant-scoped rows.
- `GET /api/enterprise/audit/export` — query params: `format=csv|json`, same filters. Streams full result as attachment.
- Both endpoints: `Depends(_require_admin)`, tenant-scoped via `get_tenant_id`.

**Frontend — `AuditTab.vue`:**
- Filter bar: username text input, action dropdown (populated from distinct values), date range (from/to)
- Results table: timestamp, username, action, details, IP, with row-level detail expand
- Pagination controls (offset-based)
- Export buttons: "Export CSV" / "Export JSON"
- Added to `SettingsView.vue` as `{ key: 'audit', label: 'Audit Log', icon: 'fa-history', admin: true }`

**Retention:** existing `AUDIT_RETENTION_DAYS` config respected; no change.

---

### 2. Per-tenant Resource Quotas

**Goal:** Allow tenant-level caps on API keys, automations, and webhook endpoints. Enables tiered plan enforcement.

**DB changes (v7 migration, same migration as audit):**
- Add `limits_json TEXT NOT NULL DEFAULT '{}'` to `tenants` table

**Quota schema (in `limits_json`):**
```json
{
  "max_api_keys": 0,
  "max_automations": 0,
  "max_webhooks": 0
}
```
Value `0` = unlimited.

**Backend:**
- `GET /api/enterprise/tenants/{tenant_id}/limits` — returns parsed limits + current counts
- `PUT /api/enterprise/tenants/{tenant_id}/limits` — updates limits_json
- Enforcement: thin check function `_check_quota(db, tenant_id, resource, max_field)` — raises HTTP 429 if limit exceeded. Called in:
  - `routers/auth.py` `api_keys_create` (max_api_keys)
  - `routers/automations.py` `api_automations_create` (max_automations)
  - `routers/webhooks.py` `webhook_create` (max_webhooks)

**Frontend:** Quota section added to `TenantsTab.vue` inline (no new tab). Shows current counts vs. limits with inline edit.

---

### 3. Compliance Report

**Goal:** Single-page compliance summary for admins — security posture, open incidents, audit activity, resource inventory.

**Backend:**
- `GET /api/enterprise/compliance/report` — aggregates:
  - Security scores: latest per host (from `security_scores`)
  - Overall score: weighted average across hosts
  - Open incidents: count from `incidents` where `status != 'resolved'`
  - Drift checks: count from `drift_checks` where `status = 'drifted'` (last 7 days)
  - Audit activity: event count by action category (last 7 days), scoped to tenant
  - Resource inventory: api_key count, automation count, webhook count, user count (tenant-scoped)
  - Report generated timestamp

**Frontend — `ComplianceTab.vue`:**
- Summary scorecard: overall security score (color-coded), open incidents badge, drifted configs badge
- Per-host security table: hostname, score, last scanned, top finding severity
- Audit activity summary: top 5 action categories with counts
- Resource inventory grid: users, API keys, automations, webhooks
- "Export Report" button: opens browser print dialog (CSS `@media print` hides nav)
- Added to `SettingsView.vue` as `{ key: 'compliance', label: 'Compliance', icon: 'fa-clipboard-check', admin: true }`

---

## Tier 2: Access Control & Security (next sprint)

1. **RBAC Policy Engine** — tenant-scoped resource ACLs (`resource_acls` table, policy middleware)
2. **Change Freeze Windows** — scheduled periods requiring admin approval for operator writes
3. **Secrets Vault** — AES-256 at-rest credential storage, tenant-scoped, referenced by integrations

---

## Tier 3: Network & Correlation (Sophos-ready sprint)

1. **Firewall Rules Abstraction** — `FirewallBackend` protocol, pfSense impl, Sophos-ready slot
2. **Security Event Correlation** — cross-source event correlation, "potential intrusion" composite incidents

---

## Implementation Order

1. v7 DB migration (audit tenant_id + tenants limits_json)
2. Audit log backend endpoints + AuditTab.vue
3. Quota enforcement backend + TenantsTab.vue quota section
4. Compliance report backend + ComplianceTab.vue
5. Build frontend, commit dist
