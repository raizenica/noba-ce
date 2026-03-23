# Self-Healing Controls Implementation Plan (Phase 3 of 6)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add safety controls to the healing pipeline: tiered approvals with escalation, maintenance windows, state snapshots with rollback, and enriched audit trails. These ensure the system never takes destructive action without appropriate authorization and can undo mistakes.

**Architecture:** New modules `server/healing/approval_manager.py`, `server/healing/maintenance.py`, `server/healing/snapshots.py`. Approval manager integrates with existing `approval_queue` table. Maintenance windows use a new `maintenance_windows` table checked by the pipeline before execution. Snapshots are captured pre-action by the executor and stored in `heal_snapshots` table.

**Tech Stack:** Python 3.11+, SQLite WAL, threading, dataclasses, pytest

**Spec:** `docs/superpowers/specs/2026-03-22-full-self-healing-design.md` (Sections 5, 7, 8)

**Predecessor:** Phase 2 (`feature/heal-intelligence`) — dependency graph, root cause, site isolation

---

## File Map

### New files
| File | Responsibility |
|------|---------------|
| `server/healing/approval_manager.py` | Tiered approval flow, escalation, cooldown, emergency override |
| `server/healing/maintenance.py` | Maintenance window evaluation, scheduling, event queuing |
| `server/healing/snapshots.py` | Pre-heal state capture, rollback execution |
| `tests/test_approval_manager.py` | Tests for approval flow, escalation, adaptive staffing |
| `tests/test_maintenance.py` | Tests for window evaluation, ad-hoc, post-maintenance |
| `tests/test_snapshots.py` | Tests for snapshot capture and rollback |
| `tests/test_rollback_api.py` | Tests for rollback API endpoint |

### Modified files
| File | Change |
|------|--------|
| `server/healing/__init__.py` | Integrate risk-based approval check and maintenance window check |
| `server/healing/executor.py` | Capture snapshot before execution, rollback on verified-failure |
| `server/db/core.py` | Add `maintenance_windows`, `heal_snapshots` tables |
| `server/db/integrations.py` | Add maintenance and snapshot DB functions |
| `server/routers/healing.py` | Add maintenance CRUD + rollback endpoints |
| `server/healing/preflight.py` | Check maintenance windows in pre-flight |

---

## Task 1: Maintenance Windows

**Files:**
- Create: `share/noba-web/server/healing/maintenance.py`
- Create: `tests/test_maintenance.py`
- Modify: `share/noba-web/server/db/integrations.py`
- Modify: `share/noba-web/server/db/core.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_maintenance.py` with tests for:
- `MaintenanceManager.is_in_maintenance(target)` returns False when no windows active
- Creating an ad-hoc window marks target as in maintenance
- Window expires after duration
- Global window (`target="all"`) blocks all targets
- Per-target window only blocks that target
- `get_active_windows()` lists active windows
- `end_window(id)` ends a window early
- Queued events are stored and retrievable
- `evaluate_queued_events()` returns events whose conditions are still true

- [ ] **Step 2: Add DB tables**

Add `maintenance_windows` table to `db/core.py`:
```sql
CREATE TABLE IF NOT EXISTS maintenance_windows (
    id INTEGER PRIMARY KEY,
    target TEXT NOT NULL,
    cron_expr TEXT,
    duration_s INTEGER NOT NULL,
    reason TEXT,
    action TEXT NOT NULL DEFAULT 'suppress',
    active INTEGER NOT NULL DEFAULT 1,
    created_by TEXT,
    created_at INTEGER NOT NULL,
    expires_at INTEGER
);
```

Add DB functions to `db/integrations.py`: `insert_maintenance_window`, `list_maintenance_windows`, `get_maintenance_window`, `delete_maintenance_window`, `update_maintenance_window`.

- [ ] **Step 3: Implement maintenance.py**

`MaintenanceManager` class (thread-safe):
- `is_in_maintenance(target)` — checks DB for active windows matching target or "all"
- `create_window(target, duration_s, reason, action, created_by)` — ad-hoc window
- `end_window(window_id)` — end early
- `get_active_windows()` — list active
- `queue_event(event)` — store event for post-maintenance evaluation
- `evaluate_queued_events()` — return stale/still-valid queued events

- [ ] **Step 4: Run tests, commit**

```bash
git commit -m "feat(healing): add maintenance window system with ad-hoc and scheduled support"
```

---

## Task 2: Approval Manager

**Files:**
- Create: `share/noba-web/server/healing/approval_manager.py`
- Create: `tests/test_approval_manager.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_approval_manager.py` with tests for:
- `determine_approval_requirement(action_type, risk, trust_level)` returns "auto" for low-risk, "required" for high-risk
- `create_approval_request(plan, context)` returns an approval with timeout
- `get_approval_context(plan)` returns enriched context dict
- Adaptive staffing: with 0 approvers, auto-deny; with 1 admin, no escalation; with operators+admins, escalation available
- Defer increments defer count, max 3 defers
- Emergency override triggers when conditions met
- Timeout stage 1 escalates from operator to admin
- Timeout stage 2 auto-denies

- [ ] **Step 2: Implement approval_manager.py**

Key functions:
- `determine_approval_requirement(action_type, trust_level, db)` — checks risk level from `ACTION_TYPES`, considers trust governor override
- `create_approval_request(plan, event, db)` — builds enriched context, inserts into `approval_queue`, returns approval_id
- `get_approval_context(plan, event, db)` — builds the full context dict (action, risk, evidence, escalation step, dependency info, rollback availability, expires)
- `check_escalation(approval_id, db)` — checks if timeout stage 1 reached, escalates
- `check_expiry(approval_id, db)` — checks if timeout stage 2 reached, auto-denies
- `count_approvers(db)` — counts users by role for adaptive staffing
- `check_emergency_override(rule_id, db)` — checks if emergency conditions met

Configuration read from YAML:
```yaml
healing:
  approval:
    stage1_timeout_m: 10
    stage2_timeout_m: 30
    max_defers: 3
    cooldown_m: 5
```

- [ ] **Step 3: Run tests, commit**

```bash
git commit -m "feat(healing): add tiered approval manager with escalation and emergency override"
```

---

## Task 3: State Snapshots & Rollback

**Files:**
- Create: `share/noba-web/server/healing/snapshots.py`
- Create: `tests/test_snapshots.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_snapshots.py` with tests for:
- `capture_snapshot(target, action_type)` returns a snapshot dict
- Snapshot contains action-appropriate fields (container config for container actions, service status for service actions)
- `execute_rollback(snapshot, action_type)` returns success/failure
- Irreversible actions return `cannot_rollback`
- `get_snapshot(ledger_id)` retrieves stored snapshot

- [ ] **Step 2: Add DB table**

Add `heal_snapshots` table to `db/core.py`:
```sql
CREATE TABLE IF NOT EXISTS heal_snapshots (
    id INTEGER PRIMARY KEY,
    ledger_id INTEGER,
    target TEXT NOT NULL,
    action_type TEXT NOT NULL,
    state TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
```

Add DB functions: `insert_snapshot`, `get_snapshot`, `get_snapshot_by_ledger`.

- [ ] **Step 3: Implement snapshots.py**

Key functions:
- `capture_snapshot(target, action_type, params)` — captures pre-action state based on action category. For container actions: query docker inspect. For service actions: query systemctl status. Returns dict.
- `execute_rollback(snapshot, action_type)` — looks up `REVERSE_ACTIONS` from remediation.py, executes reverse action with snapshot state as params
- `is_reversible(action_type)` — checks ACTION_TYPES for reversible flag

Since actual state capture requires docker/systemd access (not available in tests), the snapshot module uses a pluggable capture strategy that can be mocked.

- [ ] **Step 4: Run tests, commit**

```bash
git commit -m "feat(healing): add state snapshots with rollback for reversible actions"
```

---

## Task 4: Wire Controls into Pipeline

**Files:**
- Modify: `share/noba-web/server/healing/__init__.py`
- Modify: `share/noba-web/server/healing/executor.py`

- [ ] **Step 1: Write integration tests**

Create `tests/test_pipeline_controls.py` testing:
- High-risk action goes to approval instead of immediate execution
- Action during maintenance window is suppressed
- Low-risk action executes immediately
- Snapshot captured before action execution

- [ ] **Step 2: Integrate into pipeline**

In `handle_heal_event()`, after dependency check but before execution:

1. Check maintenance window: `if self._maintenance.is_in_maintenance(event.target)` → queue or suppress based on window action
2. Check risk-based approval: if action is high-risk and trust level requires approval, create approval request instead of executing

In executor, before action execution:
1. Capture snapshot via `snapshots.capture_snapshot()`
2. Store snapshot in DB
3. On verified-failure with reversible action: auto-rollback if configured

- [ ] **Step 3: Run all tests, commit**

```bash
git commit -m "feat(healing): integrate approval, maintenance, and rollback into pipeline"
```

---

## Task 5: Maintenance & Rollback API Endpoints

**Files:**
- Modify: `share/noba-web/server/routers/healing.py`
- Create: `tests/test_rollback_api.py`

- [ ] **Step 1: Write failing tests**

- [ ] **Step 2: Add endpoints**

- `GET /api/healing/maintenance` (read) — list active/scheduled windows
- `POST /api/healing/maintenance` (operator) — create ad-hoc window
- `DELETE /api/healing/maintenance/{id}` (operator) — end window early
- `POST /api/healing/rollback/{ledger_id}` (admin) — manual rollback

- [ ] **Step 3: Run tests, commit**

```bash
git commit -m "feat(api): add maintenance window CRUD and rollback endpoints"
```

---

## Task 6: Extended Audit Trail

**Files:**
- Modify: `share/noba-web/server/db/healing.py`
- Modify: `share/noba-web/server/healing/ledger.py`

- [ ] **Step 1: Extend heal_ledger schema**

Add columns to `heal_ledger` (via ALTER TABLE in migration):
- `risk_level TEXT`
- `snapshot_id INTEGER`
- `rollback_status TEXT` (NULL, "rolled_back", "irreversible")
- `dependency_root TEXT`
- `suppressed_by TEXT`
- `maintenance_window_id INTEGER`
- `instance_id TEXT`

- [ ] **Step 2: Update ledger.record() to populate new fields**

- [ ] **Step 3: Run tests, commit**

```bash
git commit -m "feat(healing): extend audit trail with risk, rollback, dependency context"
```

---

## Task 7: Lint + Final Integration

- [ ] **Step 1: Run ruff on all modified files**
- [ ] **Step 2: Run full test suite**
- [ ] **Step 3: Update CHANGELOG.md**
- [ ] **Step 4: Commit**

```bash
git commit -m "chore: update CHANGELOG for heal controls phase"
```
