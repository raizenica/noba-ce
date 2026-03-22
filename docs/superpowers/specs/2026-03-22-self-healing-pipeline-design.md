# Self-Healing Pipeline Design

**Date:** 2026-03-22
**Status:** Draft
**Approach:** Layered Heal Pipeline (Approach B)

## Overview

Overhaul NOBA's self-healing capabilities from a reactive, inline alert handler into a composable, layered pipeline with:

- Post-heal verification against the original alert condition (not just "is it running?")
- Escalation chains that progress through increasingly aggressive actions
- Alert correlation to prevent duplicate healing for the same root cause
- Outcome-based learning that tracks effectiveness and adapts behavior
- Predictive/proactive healing using the existing prediction and anomaly engines
- Agent-autonomous healing for local fast-path actions when the server is unreachable
- Graduated trust where new rules start conservative and earn autonomy

## Module Structure

```
server/healing/
├── __init__.py          # exports handle_heal_event pipeline entry point
├── models.py            # shared dataclasses
├── correlation.py       # HealEvent → HealRequest grouping
├── planner.py           # HealRequest → HealPlan (escalation + adaptive)
├── executor.py          # HealPlan → HealOutcome (action + verification)
├── ledger.py            # outcome recording, effectiveness queries, suggestions
├── governor.py          # trust state, promotion/demotion
└── agent_runtime.py     # policy builder, agent report ingestion
```

## Data Models

Shared dataclasses in `models.py`:

```python
@dataclass
class HealEvent:
    source: str          # "alert", "prediction", "agent", "anomaly"
    rule_id: str
    condition: str
    target: str          # container name, service, hostname
    severity: str
    timestamp: float
    metrics: dict        # snapshot of relevant metrics at trigger time

@dataclass
class HealRequest:
    correlation_key: str
    events: list[HealEvent]
    primary_target: str
    severity: str        # highest severity from grouped events
    created_at: float

@dataclass
class HealPlan:
    request: HealRequest
    action_type: str
    action_params: dict
    escalation_step: int
    trust_level: str       # "execute", "approve", "notify"
    reason: str            # human-readable explanation of why this action was chosen
    skipped_actions: list  # actions skipped due to low effectiveness

@dataclass
class HealOutcome:
    plan: HealPlan
    action_success: bool     # did the action itself complete without error?
    verified: bool           # did the original condition resolve?
    verification_detail: str # "cpu_percent dropped from 94 to 62"
    duration_s: float
    metrics_before: dict     # snapshot at trigger time (from HealEvent)
    metrics_after: dict      # snapshot after settle time

@dataclass
class HealSuggestion:
    category: str        # "recurring_issue", "low_effectiveness", "trust_promotion", "new_rule"
    severity: str        # "info", "warning"
    message: str
    rule_id: str | None
    suggested_action: dict | None   # optional config change to apply
    evidence: dict       # stats backing the suggestion

@dataclass
class AgentHealPolicy:
    rules: list[AgentHealRule]
    version: int              # bumped on change, agent skips re-parse if same
    fallback_mode: str        # "execute_local", "queue_for_server", "notify_only"

@dataclass
class AgentHealRule:
    rule_id: str
    condition: str            # simple metric comparison, same syntax as alert rules
    action_type: str          # limited to low-risk: restart_service, restart_container, clear_cache
    action_params: dict
    max_retries: int
    cooldown_s: int
    trust_level: str
```

## Layer 1: Heal Correlation

**Module:** `correlation.py`

**Purpose:** Prevent the same root issue from triggering multiple independent heal actions. If a container is dying, a CPU alert, a service-down alert, and an endpoint-down alert should not each try to heal independently.

**Mechanism:**

- Each alert/prediction event is tagged with a correlation key derived from the target (container name, service name, hostname) and a configurable time window (default 60s).
- Events within the same correlation group are merged into a single `HealRequest`.
- Correlation state is held in-memory with a dict of `{correlation_key: HealRequest}`.

**Interface:**

```python
def correlate(event: HealEvent) -> HealRequest | None:
```

Returns `None` if the event was absorbed into an existing group (already being handled). Returns a `HealRequest` when the group is ready to be planned.

## Layer 2: Heal Planner

**Module:** `planner.py`

**Purpose:** Given a correlated `HealRequest`, decide what action to take. Owns escalation chains, adaptive scoring, and predictive trigger handling.

### Escalation Chains

A rule can define an ordered list of actions with increasing severity:

```yaml
escalation_chain:
  - action: restart_container
    params: { container: "frigate" }
    verify_timeout: 30
  - action: scale_container
    params: { container: "frigate", mem_limit: "4g" }
    verify_timeout: 30
  - action: run_playbook
    params: { playbook_id: "frigate-full-recovery" }
    verify_timeout: 120
```

The planner tracks which escalation step is active per correlation key. If the executor reports verification failed, the planner advances to the next step.

### Adaptive Scoring

For each candidate action, the planner queries the ledger for historical success rate on this condition+target pair. If an action's success rate drops below a configurable threshold (default 30%), it is skipped in favor of the next action in the chain. The chain is advisory — the planner reorders based on effectiveness.

### Predictive Triggers

Events with `source="prediction"` come from the prediction engine when a metric is trending toward a threshold. Predictive heal plans are always one trust level more conservative than the rule's current trust level.

**Interface:**

```python
def select_action(request: HealRequest, ledger: HealLedger, governor: TrustGovernor) -> HealPlan:
def advance(plan: HealPlan, outcome: HealOutcome) -> HealPlan | None:
```

`advance()` returns `None` when the escalation chain is exhausted.

### HealPlan.reason

The `reason` field carries a human-readable explanation: "Skipped restart_container (18% success rate), selected scale_container (step 2 of 3)". This feeds into notifications and the UI.

## Layer 3: Heal Executor

**Module:** `executor.py`

**Purpose:** Run the planned action and verify it actually fixed the problem by re-evaluating the original alert condition, not just checking process state.

### Execution Flow

```
execute(plan) → run action → wait settle_time → re-evaluate original conditions → report outcome
```

### Verification Strategy

- `action_success=True, verified=True`: the heal resolved the root issue.
- `action_success=True, verified=False`: the action ran but the problem persists — triggers escalation back to the planner.
- `action_success=False`: the action itself failed.

Settle time is configurable per action type:
- `restart_container`, `restart_service`: 15s
- `scale_container`, `clear_cache`, `flush_dns`: 15s
- `run_playbook`: 120s
- `trigger_backup`: 60s

### Verification Mechanism

After the settle time, the executor:
1. Fetches a fresh metrics snapshot from `bg_collector.get()`
2. Re-evaluates each original condition from the `HealRequest.events` using `_safe_eval`
3. If all conditions are now `False` (no longer firing), the heal is verified
4. Records `metrics_before` (from the HealEvent) and `metrics_after` (fresh snapshot) for ledger analysis

### Integration

The executor delegates the actual action to `remediation.execute_action()` — no duplication of action handlers. It wraps the call with before/after metrics capture and condition re-evaluation.

### Escalation Callback

When `verified=False` and the escalation chain has remaining steps:

```python
if not outcome.verified and plan.escalation_step < chain_length - 1:
    next_plan = planner.advance(plan, outcome)
    if next_plan:
        executor.execute(next_plan)
```

Bounded by chain length and circuit breaker via the Trust Governor.

## Layer 4: Heal Ledger

**Module:** `ledger.py`

**Purpose:** Record every healing outcome and compute effectiveness scores. Powers the adaptive planner and the suggestion engine.

### Storage

New SQLite table:

```sql
CREATE TABLE heal_ledger (
    id INTEGER PRIMARY KEY,
    correlation_key TEXT,
    rule_id TEXT,
    condition TEXT,
    target TEXT,
    action_type TEXT,
    action_params TEXT,       -- JSON
    escalation_step INTEGER,
    action_success INTEGER,
    verified INTEGER,
    duration_s REAL,
    metrics_before TEXT,      -- JSON snapshot
    metrics_after TEXT,       -- JSON snapshot
    trust_level TEXT,
    source TEXT,              -- "alert", "prediction", "agent"
    created_at INTEGER
);
```

The existing `action_audit` table stays for general audit logging.

### Effectiveness Queries

```python
def success_rate(action_type: str, condition: str, target: str | None,
                 window_hours: int = 720) -> float:
    """Percentage of times this action verified-resolved this condition."""

def mean_time_to_resolve(condition: str, target: str | None,
                         window_hours: int = 720) -> float | None:
    """Average seconds from heal trigger to verified resolution."""

def escalation_frequency(rule_id: str, window_hours: int = 720) -> dict:
    """How often each escalation step gets reached.
    Returns {step_0: 45, step_1: 12, step_2: 3}."""
```

### Suggestion Engine

Runs hourly (via scheduler) or on-demand via API. Produces `HealSuggestion` entries:

- **recurring_issue**: "Container `frigate` has been restarted 18 times in 30 days for `mem_percent > 85`. Consider a scheduled restart or memory limit increase."
- **low_effectiveness**: "Action `restart_service` has a 15% success rate for `cpu_percent > 90` on host `proxmox-1`. Consider removing it from the escalation chain."
- **trust_promotion**: "Rule `disk-cleanup` has been auto-healed 40 times with 95% effectiveness. Eligible for promotion to `execute`."
- **new_rule**: Pattern-based detection of recurring issues without heal rules configured.

Suggestions are stored in a `heal_suggestions` table and surfaced via API and notifications. They are informational — the operator decides whether to act.

```sql
CREATE TABLE heal_suggestions (
    id INTEGER PRIMARY KEY,
    category TEXT,
    severity TEXT,
    message TEXT,
    rule_id TEXT,
    suggested_action TEXT,    -- JSON
    evidence TEXT,            -- JSON
    dismissed INTEGER DEFAULT 0,
    created_at INTEGER
);
```

## Layer 5: Agent Heal Runtime

**Module:** `agent_runtime.py`

**Purpose:** Allow agents to heal locally and autonomously when the NOBA server is unreachable, or for fast-path actions that should not wait for a server round-trip.

### Rule Distribution

The server pushes a lightweight heal policy to each agent during the regular heartbeat/poll cycle. The policy is a subset of full heal rules, filtered to what is relevant for that host.

Policy is delivered as part of the existing agent command/heartbeat flow — no new transport.

### Safety Constraints

- Only **low-risk** action types are eligible for agent-side execution: `restart_container`, `restart_service`, `clear_cache`, `flush_dns`.
- High-risk actions (`failover_dns`, `run_playbook`, `scale_container`) always go through the server.
- Agents report every local heal outcome back to the server on next successful connection — the ledger stays complete.
- `fallback_mode` controls behavior when server is unreachable:
  - `execute_local`: evaluate and act on the pushed policy
  - `queue_for_server`: record the event, submit when reconnected
  - `notify_only`: send notification only

### Server-Side Management

```python
def build_agent_policy(hostname: str, rules: list, ledger: HealLedger) -> AgentHealPolicy:
    """Filter and simplify heal rules for a specific agent."""

def ingest_agent_heal_reports(hostname: str, reports: list[dict]) -> None:
    """Process heal outcomes reported by agents, feed into ledger."""
```

Policy version is bumped on rule changes; agents skip re-parse if version matches.

## Layer 6: Trust Governor

**Module:** `governor.py`

**Purpose:** Manage graduated trust. New rules and adaptive suggestions start conservative and earn autonomy based on track record.

### Trust Lifecycle

```
notify → approve → execute
```

Every heal rule has an effective trust level that the governor can override. The rule's configured autonomy is the ceiling — the governor can only downgrade or promote up to that ceiling.

### Promotion Criteria

```python
@dataclass
class TrustPolicy:
    min_executions: int = 10        # minimum sample size
    min_success_rate: float = 0.85  # 85% verified success rate
    min_age_hours: int = 168        # 7 days at current level
    auto_promote: bool = False      # if True, promote silently; if False, create suggestion
```

- `notify → approve`: rule has fired 10+ times, operator has manually approved 85%+.
- `approve → execute`: 10+ approved executions with 85%+ verified success, at least 7 days at `approve`.

### Demotion Criteria

- Circuit breaker opens: immediate demotion to `notify`, create suggestion.
- Success rate drops below 40% over rolling 30-day window: demote one level.
- Predictive-sourced heals are always capped one level below the rule's current trust.

### Storage

```sql
CREATE TABLE trust_state (
    rule_id TEXT PRIMARY KEY,
    current_level TEXT DEFAULT 'notify',
    ceiling TEXT DEFAULT 'execute',
    promoted_at INTEGER,
    demoted_at INTEGER,
    promotion_count INTEGER DEFAULT 0,
    demotion_count INTEGER DEFAULT 0,
    last_evaluated INTEGER
);
```

### Interface

```python
def effective_trust(rule_id: str, source: str, ledger: HealLedger) -> str:
    """Resolve actual trust level considering promotions, demotions, and source."""

def evaluate_promotions(ledger: HealLedger) -> list[HealSuggestion]:
    """Check all rules for promotion/demotion eligibility."""
```

Evaluation runs during the ledger's hourly suggestion cycle — same schedule, no extra timers.

## Pipeline Entry Point

`healing/__init__.py` exports the main pipeline function:

```python
def handle_heal_event(event: HealEvent) -> None:
    request = correlation.correlate(event)
    if request is None:
        return  # absorbed into existing group
    plan = planner.select_action(request, ledger, governor)
    if plan.trust_level == "notify":
        notify_only(plan)
    elif plan.trust_level == "approve":
        queue_approval(plan)
    else:
        outcome = executor.execute(plan)
        ledger.record(outcome)
        if not outcome.verified:
            planner.advance(plan, outcome)  # escalation
```

## Changes to Existing Code

### alerts.py

Replace the inline `_execute_heal` block in `evaluate_alert_rules()` with a call to `handle_heal_event(HealEvent(...))`. Alert evaluation, condition parsing, and notification dispatch stay in `alerts.py`. The `AlertState` heal tracking (retries, circuit breaker) is superseded by the governor and ledger — can be removed once the pipeline is fully wired.

### prediction.py / check_anomalies()

Add a call to `handle_heal_event` with `source="prediction"` when anomalies or trending thresholds are detected.

### remediation.py

Stays as-is. The executor calls `remediation.execute_action()` for the actual action execution.

### scheduler.py

Add the hourly `ledger.generate_suggestions()` + `governor.evaluate_promotions()` call to the scheduler tick or as a separate periodic task.

### agent_store.py

Include policy delivery in the agent heartbeat response and report ingestion when agents reconnect.

### db/core.py

Add `heal_ledger`, `trust_state`, and `heal_suggestions` table creation to the migration path.

## New API Endpoints

Added to existing router pattern (new router or extension of operations/intelligence):

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/api/healing/ledger` | read | Recent outcomes with filtering |
| GET | `/api/healing/effectiveness` | read | Per-rule/action success rates |
| GET | `/api/healing/suggestions` | read | Active suggestions |
| POST | `/api/healing/suggestions/{id}/dismiss` | operator | Dismiss a suggestion |
| GET | `/api/healing/trust` | read | Trust state per rule |
| POST | `/api/healing/trust/{rule_id}/promote` | admin | Manual trust promotion |

## Success Criteria

1. An alert-triggered heal verifies the original condition resolved, not just process state.
2. Escalation chains progress automatically when verification fails.
3. Correlated alerts for the same target produce a single heal action, not duplicates.
4. The ledger tracks per-action effectiveness and surfaces suggestions for low-performing rules.
5. Predictive heal events from the anomaly/prediction engine flow through the pipeline.
6. Agents can execute low-risk heal actions locally when the server is unreachable.
7. New rules start at `notify`, earn promotion to `approve` then `execute` based on track record.
8. The existing `remediation.py` action handlers are reused, not duplicated.
