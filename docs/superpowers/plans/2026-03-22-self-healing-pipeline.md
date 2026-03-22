# Self-Healing Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace NOBA's inline self-healing in alerts.py with a layered pipeline: correlation, adaptive planning, verified execution, outcome ledger, trust governor, and agent-autonomous healing.

**Architecture:** Six modules in a new `server/healing/` package, each with one responsibility. A shared `condition_eval.py` is extracted first to break circular imports. DB operations go in `db/healing.py` following the existing `(conn, lock)` pattern. The pipeline entry point `handle_heal_event()` is non-blocking — all execution runs in daemon threads.

**Tech Stack:** Python 3.11+, SQLite WAL, threading, dataclasses, pytest

**Spec:** `docs/superpowers/specs/2026-03-22-self-healing-pipeline-design.md`

---

## File Map

### New files
| File | Responsibility |
|------|---------------|
| `server/healing/__init__.py` | Pipeline entry point: `handle_heal_event()` |
| `server/healing/models.py` | Shared dataclasses: HealEvent, HealRequest, HealPlan, HealOutcome, etc. |
| `server/healing/condition_eval.py` | Extracted `safe_eval`, `flatten_metrics` — no deps on alerts.py |
| `server/healing/correlation.py` | Immediate-on-first correlation with absorption window |
| `server/healing/planner.py` | Escalation chains, adaptive scoring, predictive triggers |
| `server/healing/executor.py` | Async action execution + condition-based verification |
| `server/healing/ledger.py` | Outcome recording, effectiveness queries, suggestion engine |
| `server/healing/governor.py` | Trust state management, promotion/demotion |
| `server/healing/agent_runtime.py` | Agent policy builder, report ingestion |
| `server/db/healing.py` | DB functions: `(conn, lock, ...)` pattern |
| `server/routers/healing.py` | API endpoints for ledger, suggestions, trust |
| `tests/test_condition_eval.py` | Tests for extracted condition evaluator |
| `tests/test_heal_correlation.py` | Tests for correlation layer |
| `tests/test_heal_planner.py` | Tests for planner + escalation |
| `tests/test_heal_executor.py` | Tests for executor + verification |
| `tests/test_heal_ledger.py` | Tests for ledger + suggestions |
| `tests/test_heal_governor.py` | Tests for trust governor |
| `tests/test_heal_pipeline.py` | Integration tests for full pipeline |
| `tests/test_router_healing.py` | Tests for healing API endpoints |

### Modified files
| File | Change |
|------|--------|
| `server/alerts.py` | Replace `_execute_heal` block with `handle_heal_event()`, remove `_safe_eval*` (import from condition_eval) |
| `server/workflow_engine.py` | Import `safe_eval` from `healing.condition_eval` instead of `alerts._safe_eval` |
| `server/routers/stats.py` | Import `safe_eval` from `healing.condition_eval` instead of `alerts._safe_eval` |
| `server/remediation.py` | Add 4 action types: `run`, `webhook`, `automation`, `agent_command` |
| `server/db/core.py` | Add `heal_ledger`, `trust_state`, `heal_suggestions` tables + delegation wrappers |
| `server/scheduler.py` | Add hourly suggestion/promotion evaluation |
| `server/routers/agents.py` | Include heal policy in heartbeat response, ingest heal reports |
| `server/routers/__init__.py` | Register healing router |
| `server/app.py` | Register healing router |

---

## Task 1: Extract condition_eval module

**Files:**
- Create: `share/noba-web/server/healing/__init__.py` (empty for now)
- Create: `share/noba-web/server/healing/condition_eval.py`
- Create: `tests/test_condition_eval.py`
- Modify: `share/noba-web/server/alerts.py`
- Modify: `share/noba-web/server/workflow_engine.py`
- Modify: `share/noba-web/server/routers/stats.py`
- Modify: `tests/test_alerts.py`
- Modify: `tests/test_alerts_composite.py`

- [ ] **Step 1: Create empty healing package**

Create `share/noba-web/server/healing/__init__.py` with a docstring only:
```python
"""Noba -- Self-healing pipeline."""
from __future__ import annotations
```

- [ ] **Step 2: Write failing tests for condition_eval**

Create `tests/test_condition_eval.py`:
```python
"""Tests for healing.condition_eval: safe_eval and flatten_metrics."""
from __future__ import annotations


class TestSafeEvalSingle:
    def test_greater_than_true(self):
        from server.healing.condition_eval import safe_eval_single
        assert safe_eval_single("cpu_percent > 90", {"cpu_percent": 95.0})

    def test_greater_than_false(self):
        from server.healing.condition_eval import safe_eval_single
        assert not safe_eval_single("cpu_percent > 90", {"cpu_percent": 80.0})

    def test_missing_metric(self):
        from server.healing.condition_eval import safe_eval_single
        assert not safe_eval_single("nonexistent > 0", {})

    def test_injection_attempt(self):
        from server.healing.condition_eval import safe_eval_single
        assert not safe_eval_single('import os; os.system("evil")', {})
        assert not safe_eval_single("", {})


class TestSafeEval:
    def test_single_condition(self):
        from server.healing.condition_eval import safe_eval
        assert safe_eval("cpu_percent > 80", {"cpu_percent": 90.0})

    def test_and_both_true(self):
        from server.healing.condition_eval import safe_eval
        assert safe_eval(
            "cpu_percent > 80 AND mem_percent > 70",
            {"cpu_percent": 90.0, "mem_percent": 80.0},
        )

    def test_and_one_false(self):
        from server.healing.condition_eval import safe_eval
        assert not safe_eval(
            "cpu_percent > 80 AND mem_percent > 70",
            {"cpu_percent": 90.0, "mem_percent": 50.0},
        )

    def test_or_one_true(self):
        from server.healing.condition_eval import safe_eval
        assert safe_eval(
            "cpu_percent > 80 OR mem_percent > 70",
            {"cpu_percent": 90.0, "mem_percent": 50.0},
        )


class TestFlattenMetrics:
    def test_scalar_values(self):
        from server.healing.condition_eval import flatten_metrics
        stats = {"cpuPercent": 85, "memPercent": 70, "hostname": "noba-1"}
        flat = flatten_metrics(stats)
        assert flat["cpuPercent"] == 85
        assert flat["memPercent"] == 70
        assert flat["hostname"] == "noba-1"

    def test_nested_list_of_dicts(self):
        from server.healing.condition_eval import flatten_metrics
        stats = {
            "disks": [
                {"mount": "/", "percent": 45},
                {"mount": "/data", "percent": 88},
            ]
        }
        flat = flatten_metrics(stats)
        assert flat["disks[0].percent"] == 45
        assert flat["disks[1].percent"] == 88

    def test_non_numeric_nested_skipped(self):
        from server.healing.condition_eval import flatten_metrics
        stats = {"disks": [{"mount": "/", "label": "root"}]}
        flat = flatten_metrics(stats)
        assert "disks[0].label" not in flat

    def test_empty_stats(self):
        from server.healing.condition_eval import flatten_metrics
        assert flatten_metrics({}) == {}
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_condition_eval.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'server.healing.condition_eval'`

- [ ] **Step 4: Implement condition_eval.py**

Create `share/noba-web/server/healing/condition_eval.py`:
```python
"""Noba -- Condition evaluation and metric flattening.

Standalone module with NO imports from alerts.py or other healing modules.
Used by: alerts.py, workflow_engine.py, routers/stats.py, healing/executor.py.
"""
from __future__ import annotations

import logging
import operator
import re

logger = logging.getLogger("noba")

_OPS = {
    ">": operator.gt, "<": operator.lt,
    ">=": operator.ge, "<=": operator.le,
    "==": operator.eq, "!=": operator.ne,
}


def flatten_metrics(stats: dict) -> dict:
    """Flatten nested collector stats into a flat dict for condition evaluation.

    Scalar values pass through. List-of-dict structures are expanded:
    ``disks[0].percent``, ``services[1].status``, etc.
    Only int/float nested values are included (strings at top level are kept).
    """
    flat: dict = {}
    for k, v in stats.items():
        if isinstance(v, (int, float, str)):
            flat[k] = v
        elif isinstance(v, list):
            for i, item in enumerate(v):
                if isinstance(item, dict):
                    for sk, sv in item.items():
                        if isinstance(sv, (int, float)):
                            flat[f"{k}[{i}].{sk}"] = sv
    return flat


def safe_eval_single(condition_str: str, flat: dict) -> bool:
    """Evaluate a single metric comparison (e.g. 'cpu_percent > 90')."""
    s = (condition_str
         .replace("flat['", "").replace('flat["', "")
         .replace("']", "").replace('"]', ""))
    m = re.match(
        r"^\s*([a-zA-Z0-9_\[\]\.]+)\s*(>|<|>=|<=|==|!=)\s*([0-9\.-]+)\s*$", s,
    )
    if not m:
        logger.warning("Malformed alert condition (parse failed): %s", condition_str)
        return False
    metric, op, val = m.groups()
    if metric not in flat:
        return False
    try:
        return _OPS[op](float(flat[metric]), float(val))
    except (ValueError, TypeError):
        logger.warning("Malformed alert condition (bad value): %s=%r", metric, flat[metric])
        return False


def safe_eval(condition_str: str, flat: dict) -> bool:
    """Evaluate a condition string, supporting AND/OR composite conditions."""
    if " AND " in condition_str:
        return all(safe_eval_single(part.strip(), flat)
                   for part in condition_str.split(" AND "))
    if " OR " in condition_str:
        return any(safe_eval_single(part.strip(), flat)
                   for part in condition_str.split(" OR "))
    return safe_eval_single(condition_str, flat)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_condition_eval.py -v`
Expected: All PASS

- [ ] **Step 6: Update alerts.py to delegate to condition_eval**

In `share/noba-web/server/alerts.py`:
- Remove the `_OPS` dict, `_safe_eval_single`, and `_safe_eval` functions (lines 88-116)
- Remove the `import operator` and `import re` imports (only if no longer used elsewhere in the file — `re` is still used in `_execute_heal` target validation, so keep `re`)
- Add near top: `from .healing.condition_eval import safe_eval as _safe_eval, safe_eval_single as _safe_eval_single`
- This preserves backward compatibility for any internal callers using the underscore names

- [ ] **Step 7: Update workflow_engine.py imports**

In `share/noba-web/server/workflow_engine.py`, replace the two late imports of `_safe_eval`:
- Line 236: `from .alerts import _safe_eval` → `from .healing.condition_eval import safe_eval as _safe_eval`
- Line 502: `from .alerts import _safe_eval` → `from .healing.condition_eval import safe_eval as _safe_eval`

- [ ] **Step 8: Update routers/stats.py import**

In `share/noba-web/server/routers/stats.py` line 295:
- `from ..alerts import _safe_eval` → `from ..healing.condition_eval import safe_eval as _safe_eval`

- [ ] **Step 9: Update existing test imports**

In `tests/test_alerts.py` line 2: `from server.alerts import _safe_eval` — keep as-is (alerts re-exports it).
In `tests/test_alerts_composite.py` line 8: `from server.alerts import ... _safe_eval, _safe_eval_single ...` — keep as-is (alerts re-exports them).

- [ ] **Step 10: Run full test suite to confirm no regressions**

Run: `pytest tests/ -v`
Expected: All existing tests PASS

- [ ] **Step 11: Lint and commit**

```bash
ruff check --fix share/noba-web/server/healing/condition_eval.py share/noba-web/server/alerts.py share/noba-web/server/workflow_engine.py share/noba-web/server/routers/stats.py
git add share/noba-web/server/healing/ tests/test_condition_eval.py share/noba-web/server/alerts.py share/noba-web/server/workflow_engine.py share/noba-web/server/routers/stats.py
git commit -m "refactor: extract condition_eval from alerts.py into healing package"
```

---

## Task 2: Data models

**Files:**
- Create: `share/noba-web/server/healing/models.py`

- [ ] **Step 1: Write models.py**

Create `share/noba-web/server/healing/models.py` with all dataclasses from the spec:
```python
"""Noba -- Self-healing pipeline data models."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class HealEvent:
    source: str          # "alert", "prediction", "agent", "anomaly"
    rule_id: str
    condition: str
    target: str          # container name, service, hostname
    severity: str
    timestamp: float
    metrics: dict = field(default_factory=dict)


@dataclass
class HealRequest:
    correlation_key: str
    events: list[HealEvent] = field(default_factory=list)
    primary_target: str = ""
    severity: str = "warning"
    created_at: float = 0.0


@dataclass
class HealPlan:
    request: HealRequest
    action_type: str
    action_params: dict = field(default_factory=dict)
    escalation_step: int = 0
    trust_level: str = "notify"
    reason: str = ""
    skipped_actions: list = field(default_factory=list)


@dataclass
class HealOutcome:
    plan: HealPlan
    action_success: bool | None = None
    verified: bool | None = None
    verification_detail: str = ""
    duration_s: float = 0.0
    metrics_before: dict = field(default_factory=dict)
    metrics_after: dict | None = None
    approval_id: int | None = None


@dataclass
class HealSuggestion:
    category: str        # "recurring_issue", "low_effectiveness", "trust_promotion", "new_rule"
    severity: str = "info"
    message: str = ""
    rule_id: str | None = None
    suggested_action: dict | None = None
    evidence: dict = field(default_factory=dict)


@dataclass
class AgentHealPolicy:
    rules: list[AgentHealRule] = field(default_factory=list)
    version: int = 0
    fallback_mode: str = "queue_for_server"


@dataclass
class AgentHealRule:
    rule_id: str
    condition: str
    action_type: str
    action_params: dict = field(default_factory=dict)
    max_retries: int = 3
    cooldown_s: int = 300
    trust_level: str = "notify"
    fallback_mode: str | None = None
```

- [ ] **Step 2: Verify import works**

Run: `python -c "from server.healing.models import HealEvent, HealPlan; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Lint and commit**

```bash
ruff check --fix share/noba-web/server/healing/models.py
git add share/noba-web/server/healing/models.py
git commit -m "feat(healing): add pipeline data models"
```

---

## Task 3: DB layer for healing

**Files:**
- Create: `share/noba-web/server/db/healing.py`
- Modify: `share/noba-web/server/db/core.py`
- Create: `tests/test_heal_ledger.py`

- [ ] **Step 1: Write failing tests for DB operations**

Create `tests/test_heal_ledger.py`:
```python
"""Tests for healing DB operations: ledger, trust_state, suggestions."""
from __future__ import annotations

import json
import time


class TestHealLedger:
    def _db(self):
        from server.db.core import Database
        db = Database(":memory:")
        db.init()
        return db

    def test_insert_and_get_outcomes(self):
        db = self._db()
        db.insert_heal_outcome(
            correlation_key="test:nginx",
            rule_id="cpu_high",
            condition="cpu_percent > 90",
            target="nginx",
            action_type="restart_container",
            action_params=json.dumps({"container": "nginx"}),
            escalation_step=0,
            action_success=1,
            verified=1,
            duration_s=2.5,
            metrics_before=json.dumps({"cpu_percent": 95}),
            metrics_after=json.dumps({"cpu_percent": 40}),
            trust_level="execute",
            source="alert",
            approval_id=None,
        )
        rows = db.get_heal_outcomes(limit=10)
        assert len(rows) == 1
        assert rows[0]["rule_id"] == "cpu_high"
        assert rows[0]["verified"] == 1

    def test_success_rate(self):
        db = self._db()
        for verified in [1, 1, 1, 0]:
            db.insert_heal_outcome(
                correlation_key="test:x", rule_id="r1",
                condition="cpu > 90", target="nginx",
                action_type="restart_container",
                action_params="{}",
                escalation_step=0, action_success=1,
                verified=verified, duration_s=1.0,
                metrics_before="{}", metrics_after="{}",
                trust_level="execute", source="alert",
                approval_id=None,
            )
        rate = db.get_heal_success_rate("restart_container", "cpu > 90")
        assert rate == 75.0  # 3/4

    def test_success_rate_no_data(self):
        db = self._db()
        rate = db.get_heal_success_rate("restart_container", "cpu > 90")
        assert rate == 0.0


class TestTrustState:
    def _db(self):
        from server.db.core import Database
        db = Database(":memory:")
        db.init()
        return db

    def test_upsert_and_get(self):
        db = self._db()
        db.upsert_trust_state("rule1", "notify", "execute")
        state = db.get_trust_state("rule1")
        assert state is not None
        assert state["current_level"] == "notify"
        assert state["ceiling"] == "execute"

    def test_get_nonexistent(self):
        db = self._db()
        assert db.get_trust_state("nope") is None

    def test_update_promotion(self):
        db = self._db()
        db.upsert_trust_state("rule1", "notify", "execute")
        db.upsert_trust_state("rule1", "approve", "execute")
        state = db.get_trust_state("rule1")
        assert state["current_level"] == "approve"


class TestHealSuggestions:
    def _db(self):
        from server.db.core import Database
        db = Database(":memory:")
        db.init()
        return db

    def test_insert_and_list(self):
        db = self._db()
        db.insert_heal_suggestion(
            category="low_effectiveness",
            severity="warning",
            message="restart has 15% success rate",
            rule_id="r1",
        )
        suggestions = db.list_heal_suggestions()
        assert len(suggestions) == 1
        assert suggestions[0]["category"] == "low_effectiveness"

    def test_dismiss(self):
        db = self._db()
        db.insert_heal_suggestion(
            category="recurring_issue", severity="info",
            message="test", rule_id="r2",
        )
        suggestions = db.list_heal_suggestions()
        db.dismiss_heal_suggestion(suggestions[0]["id"])
        assert db.list_heal_suggestions() == []

    def test_upsert_deduplication(self):
        db = self._db()
        db.insert_heal_suggestion(
            category="low_effectiveness", severity="warning",
            message="old message", rule_id="r1",
        )
        db.insert_heal_suggestion(
            category="low_effectiveness", severity="warning",
            message="updated message", rule_id="r1",
        )
        suggestions = db.list_heal_suggestions()
        assert len(suggestions) == 1
        assert suggestions[0]["message"] == "updated message"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_heal_ledger.py -v`
Expected: FAIL — missing DB methods

- [ ] **Step 3: Implement db/healing.py**

Create `share/noba-web/server/db/healing.py`:
```python
"""Noba -- Healing pipeline DB functions (ledger, trust, suggestions)."""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time

logger = logging.getLogger("noba")


# ── Heal Ledger ───────────────────────────────────────────────────────────────

def insert_heal_outcome(
    conn: sqlite3.Connection, lock: threading.Lock, *,
    correlation_key: str, rule_id: str, condition: str, target: str,
    action_type: str, action_params: str, escalation_step: int,
    action_success: int | None, verified: int | None,
    duration_s: float, metrics_before: str, metrics_after: str | None,
    trust_level: str, source: str, approval_id: int | None,
) -> int:
    now = int(time.time())
    with lock:
        cur = conn.execute(
            "INSERT INTO heal_ledger "
            "(correlation_key, rule_id, condition, target, action_type, "
            "action_params, escalation_step, action_success, verified, "
            "duration_s, metrics_before, metrics_after, trust_level, "
            "source, approval_id, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (correlation_key, rule_id, condition, target, action_type,
             action_params, escalation_step, action_success, verified,
             duration_s, metrics_before, metrics_after, trust_level,
             source, approval_id, now),
        )
        conn.commit()
        return cur.lastrowid or 0


def get_heal_outcomes(
    conn: sqlite3.Connection, lock: threading.Lock, *,
    limit: int = 50, rule_id: str | None = None,
    target: str | None = None,
) -> list[dict]:
    sql = "SELECT * FROM heal_ledger WHERE 1=1"
    params: list = []
    if rule_id:
        sql += " AND rule_id = ?"
        params.append(rule_id)
    if target:
        sql += " AND target = ?"
        params.append(target)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    with lock:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def get_heal_success_rate(
    conn: sqlite3.Connection, lock: threading.Lock,
    action_type: str, condition: str,
    target: str | None = None, window_hours: int = 720,
) -> float:
    cutoff = int(time.time()) - window_hours * 3600
    sql = (
        "SELECT COUNT(*) as total, "
        "SUM(CASE WHEN verified = 1 THEN 1 ELSE 0 END) as successes "
        "FROM heal_ledger "
        "WHERE action_type = ? AND condition = ? AND created_at >= ? "
        "AND action_success IS NOT NULL"
    )
    params: list = [action_type, condition, cutoff]
    if target:
        sql += " AND target = ?"
        params.append(target)
    with lock:
        row = conn.execute(sql, params).fetchone()
    total = row["total"] if row else 0
    successes = row["successes"] if row else 0
    return round((successes / total) * 100, 1) if total > 0 else 0.0


def get_mean_time_to_resolve(
    conn: sqlite3.Connection, lock: threading.Lock,
    condition: str, target: str | None = None,
    window_hours: int = 720,
) -> float | None:
    cutoff = int(time.time()) - window_hours * 3600
    sql = (
        "SELECT AVG(duration_s) as avg_duration "
        "FROM heal_ledger "
        "WHERE condition = ? AND verified = 1 AND created_at >= ?"
    )
    params: list = [condition, cutoff]
    if target:
        sql += " AND target = ?"
        params.append(target)
    with lock:
        row = conn.execute(sql, params).fetchone()
    return round(row["avg_duration"], 2) if row and row["avg_duration"] is not None else None


def get_escalation_frequency(
    conn: sqlite3.Connection, lock: threading.Lock,
    rule_id: str, window_hours: int = 720,
) -> dict:
    cutoff = int(time.time()) - window_hours * 3600
    with lock:
        rows = conn.execute(
            "SELECT escalation_step, COUNT(*) as cnt "
            "FROM heal_ledger WHERE rule_id = ? AND created_at >= ? "
            "AND action_success IS NOT NULL "
            "GROUP BY escalation_step ORDER BY escalation_step",
            (rule_id, cutoff),
        ).fetchall()
    return {f"step_{r['escalation_step']}": r["cnt"] for r in rows}


# ── Trust State ───────────────────────────────────────────────────────────────

def upsert_trust_state(
    conn: sqlite3.Connection, lock: threading.Lock,
    rule_id: str, current_level: str, ceiling: str,
) -> None:
    now = int(time.time())
    with lock:
        existing = conn.execute(
            "SELECT current_level FROM trust_state WHERE rule_id = ?",
            (rule_id,),
        ).fetchone()
        if existing:
            old_level = existing["current_level"]
            sets = "current_level = ?, ceiling = ?, last_evaluated = ?"
            params: list = [current_level, ceiling, now]
            if current_level != old_level:
                lvl_order = {"notify": 0, "approve": 1, "execute": 2}
                if lvl_order.get(current_level, 0) > lvl_order.get(old_level, 0):
                    sets += ", promoted_at = ?, promotion_count = promotion_count + 1"
                    params.append(now)
                else:
                    sets += ", demoted_at = ?, demotion_count = demotion_count + 1"
                    params.append(now)
            params.append(rule_id)
            conn.execute(
                f"UPDATE trust_state SET {sets} WHERE rule_id = ?", params,
            )
        else:
            conn.execute(
                "INSERT INTO trust_state "
                "(rule_id, current_level, ceiling, last_evaluated) "
                "VALUES (?,?,?,?)",
                (rule_id, current_level, ceiling, now),
            )
        conn.commit()


def get_trust_state(
    conn: sqlite3.Connection, lock: threading.Lock,
    rule_id: str,
) -> dict | None:
    with lock:
        row = conn.execute(
            "SELECT * FROM trust_state WHERE rule_id = ?", (rule_id,),
        ).fetchone()
    return dict(row) if row else None


def list_trust_states(
    conn: sqlite3.Connection, lock: threading.Lock,
) -> list[dict]:
    with lock:
        rows = conn.execute(
            "SELECT * FROM trust_state ORDER BY rule_id",
        ).fetchall()
    return [dict(r) for r in rows]


# ── Heal Suggestions ──────────────────────────────────────────────────────────

def insert_heal_suggestion(
    conn: sqlite3.Connection, lock: threading.Lock, *,
    category: str, severity: str, message: str,
    rule_id: str | None = None,
    suggested_action: str | None = None,
    evidence: str | None = None,
) -> int:
    now = int(time.time())
    with lock:
        cur = conn.execute(
            "INSERT OR REPLACE INTO heal_suggestions "
            "(category, severity, message, rule_id, suggested_action, "
            "evidence, dismissed, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,0,?,?)",
            (category, severity, message, rule_id, suggested_action,
             evidence, now, now),
        )
        conn.commit()
        return cur.lastrowid or 0


def list_heal_suggestions(
    conn: sqlite3.Connection, lock: threading.Lock,
    include_dismissed: bool = False,
) -> list[dict]:
    sql = "SELECT * FROM heal_suggestions"
    if not include_dismissed:
        sql += " WHERE dismissed = 0"
    sql += " ORDER BY created_at DESC"
    with lock:
        rows = conn.execute(sql).fetchall()
    return [dict(r) for r in rows]


def dismiss_heal_suggestion(
    conn: sqlite3.Connection, lock: threading.Lock,
    suggestion_id: int,
) -> None:
    with lock:
        conn.execute(
            "UPDATE heal_suggestions SET dismissed = 1, updated_at = ? WHERE id = ?",
            (int(time.time()), suggestion_id),
        )
        conn.commit()
```

- [ ] **Step 4: Add tables to db/core.py init and add delegation wrappers**

In `share/noba-web/server/db/core.py`:

Add to the `init()` method's `CREATE TABLE IF NOT EXISTS` block:
```sql
CREATE TABLE IF NOT EXISTS heal_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    correlation_key TEXT,
    rule_id TEXT,
    condition TEXT,
    target TEXT,
    action_type TEXT,
    action_params TEXT,
    escalation_step INTEGER,
    action_success INTEGER,
    verified INTEGER,
    duration_s REAL,
    metrics_before TEXT,
    metrics_after TEXT,
    trust_level TEXT,
    source TEXT,
    approval_id INTEGER,
    created_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_heal_ledger_lookup
    ON heal_ledger(rule_id, condition, target, created_at);

CREATE TABLE IF NOT EXISTS trust_state (
    rule_id TEXT PRIMARY KEY,
    current_level TEXT DEFAULT 'notify',
    ceiling TEXT DEFAULT 'execute',
    promoted_at INTEGER,
    demoted_at INTEGER,
    promotion_count INTEGER DEFAULT 0,
    demotion_count INTEGER DEFAULT 0,
    last_evaluated INTEGER
);

CREATE TABLE IF NOT EXISTS heal_suggestions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT,
    severity TEXT,
    message TEXT,
    rule_id TEXT,
    suggested_action TEXT,
    evidence TEXT,
    dismissed INTEGER DEFAULT 0,
    created_at INTEGER,
    updated_at INTEGER,
    UNIQUE(category, rule_id)
);
```

Add import at top of `db/core.py`:
```python
from .healing import (
    insert_heal_outcome as _insert_heal_outcome,
    get_heal_outcomes as _get_heal_outcomes,
    get_heal_success_rate as _get_heal_success_rate,
    get_mean_time_to_resolve as _get_mean_time_to_resolve,
    get_escalation_frequency as _get_escalation_frequency,
    upsert_trust_state as _upsert_trust_state,
    get_trust_state as _get_trust_state,
    list_trust_states as _list_trust_states,
    insert_heal_suggestion as _insert_heal_suggestion,
    list_heal_suggestions as _list_heal_suggestions,
    dismiss_heal_suggestion as _dismiss_heal_suggestion,
)
```

Add delegation methods to the `Database` class:
```python
# ── Healing Pipeline ──────────────────────────────────────────────────────
def insert_heal_outcome(self, **kw) -> int:
    return _insert_heal_outcome(self._get_conn(), self._lock, **kw)

def get_heal_outcomes(self, **kw) -> list[dict]:
    return _get_heal_outcomes(self._get_conn(), self._lock, **kw)

def get_heal_success_rate(self, action_type, condition, **kw) -> float:
    return _get_heal_success_rate(self._get_conn(), self._lock, action_type, condition, **kw)

def get_mean_time_to_resolve(self, condition, **kw) -> float | None:
    return _get_mean_time_to_resolve(self._get_conn(), self._lock, condition, **kw)

def get_escalation_frequency(self, rule_id, **kw) -> dict:
    return _get_escalation_frequency(self._get_conn(), self._lock, rule_id, **kw)

def upsert_trust_state(self, rule_id, current_level, ceiling) -> None:
    _upsert_trust_state(self._get_conn(), self._lock, rule_id, current_level, ceiling)

def get_trust_state(self, rule_id) -> dict | None:
    return _get_trust_state(self._get_conn(), self._lock, rule_id)

def list_trust_states(self) -> list[dict]:
    return _list_trust_states(self._get_conn(), self._lock)

def insert_heal_suggestion(self, **kw) -> int:
    return _insert_heal_suggestion(self._get_conn(), self._lock, **kw)

def list_heal_suggestions(self, **kw) -> list[dict]:
    return _list_heal_suggestions(self._get_conn(), self._lock, **kw)

def dismiss_heal_suggestion(self, suggestion_id) -> None:
    _dismiss_heal_suggestion(self._get_conn(), self._lock, suggestion_id)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_heal_ledger.py -v`
Expected: All PASS

- [ ] **Step 6: Run full test suite**

Run: `pytest tests/ -v`
Expected: All PASS

- [ ] **Step 7: Lint and commit**

```bash
ruff check --fix share/noba-web/server/db/healing.py share/noba-web/server/db/core.py
git add share/noba-web/server/db/healing.py share/noba-web/server/db/core.py
git commit -m "feat(healing): add DB layer — ledger, trust_state, suggestions tables"
```

---

## Task 4: Correlation layer

**Files:**
- Create: `share/noba-web/server/healing/correlation.py`
- Create: `tests/test_heal_correlation.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_heal_correlation.py`:
```python
"""Tests for healing correlation: immediate-on-first with absorption."""
from __future__ import annotations

import time


class TestCorrelation:
    def _make_event(self, target="nginx", rule_id="r1", source="alert"):
        from server.healing.models import HealEvent
        return HealEvent(
            source=source, rule_id=rule_id, condition="cpu > 90",
            target=target, severity="warning",
            timestamp=time.time(), metrics={"cpu": 95},
        )

    def _correlator(self, window=60):
        from server.healing.correlation import HealCorrelator
        return HealCorrelator(absorption_window=window)

    def test_first_event_emits_request(self):
        c = self._correlator()
        result = c.correlate(self._make_event())
        assert result is not None
        assert result.primary_target == "nginx"
        assert len(result.events) == 1

    def test_second_event_same_target_absorbed(self):
        c = self._correlator()
        c.correlate(self._make_event())
        result = c.correlate(self._make_event(rule_id="r2"))
        assert result is None

    def test_different_target_not_absorbed(self):
        c = self._correlator()
        c.correlate(self._make_event(target="nginx"))
        result = c.correlate(self._make_event(target="postgres"))
        assert result is not None
        assert result.primary_target == "postgres"

    def test_expired_window_allows_new_request(self):
        c = self._correlator(window=0)  # 0s window = immediate expiry
        c.correlate(self._make_event())
        time.sleep(0.01)
        result = c.correlate(self._make_event())
        assert result is not None

    def test_highest_severity_wins(self):
        c = self._correlator()
        e = self._make_event()
        e.severity = "critical"
        result = c.correlate(e)
        assert result.severity == "critical"

    def test_thread_safety(self):
        import threading
        c = self._correlator()
        results = []

        def worker(i):
            r = c.correlate(self._make_event(target=f"svc-{i}"))
            results.append(r)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # Each unique target should get its own request
        non_none = [r for r in results if r is not None]
        assert len(non_none) == 10
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_heal_correlation.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement correlation.py**

Create `share/noba-web/server/healing/correlation.py`:
```python
"""Noba -- Heal event correlation: immediate-on-first with absorption window."""
from __future__ import annotations

import threading
import time

from .models import HealEvent, HealRequest


class HealCorrelator:
    """Correlate heal events by target.

    First event for a target emits a HealRequest immediately.
    Subsequent events for the same target within the absorption window
    are absorbed (return None).
    """

    def __init__(self, absorption_window: float = 60.0) -> None:
        self._window = absorption_window
        self._lock = threading.Lock()
        self._active: dict[str, float] = {}  # correlation_key -> expiry timestamp

    def correlate(self, event: HealEvent) -> HealRequest | None:
        key = self._make_key(event)
        now = time.time()

        with self._lock:
            # Purge expired entries
            expired = [k for k, exp in self._active.items() if now >= exp]
            for k in expired:
                del self._active[k]

            # Check if absorbed
            if key in self._active:
                return None

            # First event — register and emit
            self._active[key] = now + self._window

        return HealRequest(
            correlation_key=key,
            events=[event],
            primary_target=event.target,
            severity=event.severity,
            created_at=now,
        )

    @staticmethod
    def _make_key(event: HealEvent) -> str:
        return f"{event.target}:{event.rule_id}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_heal_correlation.py -v`
Expected: All PASS

- [ ] **Step 5: Lint and commit**

```bash
ruff check --fix share/noba-web/server/healing/correlation.py
git add share/noba-web/server/healing/correlation.py tests/test_heal_correlation.py
git commit -m "feat(healing): add correlation layer with absorption window"
```

---

## Task 5: Migrate action types to remediation.py

**Files:**
- Modify: `share/noba-web/server/remediation.py`
- Create: `tests/test_remediation_extended.py`

- [ ] **Step 1: Write failing tests for new action types**

Create `tests/test_remediation_extended.py`:
```python
"""Tests for migrated action types: run, webhook, automation, agent_command."""
from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestRunAction:
    def test_validate_run(self):
        from server.remediation import validate_action
        err = validate_action("run", {"command": "echo hello"})
        assert err is None

    def test_validate_run_missing(self):
        from server.remediation import validate_action
        err = validate_action("run", {})
        assert err is not None

    @patch("server.remediation.subprocess.run")
    def test_execute_run_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        from server.remediation import _handle_run
        result = _handle_run({"command": "echo hello"})
        assert result["success"] is True


class TestWebhookAction:
    def test_validate_webhook(self):
        from server.remediation import validate_action
        err = validate_action("webhook", {"url": "http://example.com/hook"})
        assert err is None

    def test_validate_webhook_missing(self):
        from server.remediation import validate_action
        err = validate_action("webhook", {})
        assert err is not None


class TestAutomationAction:
    def test_validate_automation(self):
        from server.remediation import validate_action
        err = validate_action("automation", {"automation_id": "my-auto"})
        assert err is None

    def test_validate_automation_missing(self):
        from server.remediation import validate_action
        err = validate_action("automation", {})
        assert err is not None


class TestAgentCommandAction:
    def test_validate_agent_command(self):
        from server.remediation import validate_action
        err = validate_action("agent_command", {"hostname": "host1", "command": "restart"})
        assert err is None

    def test_validate_agent_command_missing(self):
        from server.remediation import validate_action
        err = validate_action("agent_command", {})
        assert err is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_remediation_extended.py -v`
Expected: FAIL — unknown action types

- [ ] **Step 3: Add 4 action types to remediation.py**

In `share/noba-web/server/remediation.py`:

Add to `ACTION_TYPES` dict:
```python
"run": {
    "risk": "medium",
    "params": {"command": str},
    "description": "Execute a shell command",
    "timeout_s": 60,
},
"webhook": {
    "risk": "low",
    "params": {"url": str},
    "description": "Fire an HTTP webhook",
    "timeout_s": 10,
},
"automation": {
    "risk": "medium",
    "params": {"automation_id": str},
    "description": "Trigger a stored automation by ID",
    "timeout_s": 300,
},
"agent_command": {
    "risk": "medium",
    "params": {"hostname": str, "command": str},
    "description": "Send command to a remote agent",
    "timeout_s": 30,
},
```

Add handler functions (migrate from `alerts._execute_heal`):
```python
def _handle_run(params):
    import shlex
    command = params.get("command", "")
    if not command:
        return {"success": False, "output": "No command specified"}
    r = subprocess.run(shlex.split(command), timeout=60, capture_output=True, text=True)
    return {"success": r.returncode == 0, "output": (r.stdout + r.stderr)[:500]}


def _handle_webhook(params):
    import urllib.request
    url = params.get("url", "")
    method = params.get("method", "POST").upper()
    if not url or not url.startswith(("http://", "https://")):
        return {"success": False, "output": "Invalid URL"}
    req = urllib.request.Request(url, method=method)
    for k, v in (params.get("headers") or {}).items():
        req.add_header(str(k).replace("\n", ""), str(v).replace("\n", ""))
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            ok = 200 <= r.getcode() < 300
            return {"success": ok, "output": f"HTTP {r.getcode()}"}
    except Exception as e:
        return {"success": False, "output": str(e)}


def _handle_automation(params):
    auto_id = params.get("automation_id", "")
    if not auto_id:
        return {"success": False, "output": "No automation_id"}
    from .db import db as _db
    auto = _db.get_automation(auto_id)
    if not auto:
        return {"success": False, "output": f"Automation not found: {auto_id}"}
    from .workflow_engine import _AUTO_BUILDERS, _run_workflow
    from .runner import job_runner
    if auto["type"] == "workflow":
        steps = auto["config"].get("steps", [])
        if steps:
            _run_workflow(auto["id"], steps, "remediation")
            return {"success": True, "output": f"Workflow started: {auto['name']}"}
        return {"success": False, "output": "Workflow has no steps"}
    builder = _AUTO_BUILDERS.get(auto["type"])
    if not builder:
        return {"success": False, "output": f"Unknown automation type: {auto['type']}"}
    config = auto["config"]
    try:
        job_runner.submit(
            lambda _rid: builder(config),
            automation_id=auto["id"],
            trigger="remediation",
            triggered_by="remediation",
        )
        return {"success": True, "output": f"Automation triggered: {auto['name']}"}
    except RuntimeError as exc:
        return {"success": False, "output": str(exc)}


def _handle_agent_command(params):
    from .agent_store import queue_agent_command_and_wait
    hostname = params.get("hostname", "")
    cmd_type = params.get("command", "")
    cmd_params = params.get("params", {})
    timeout = int(params.get("timeout", 30))
    if not hostname or not cmd_type:
        return {"success": False, "output": "Missing hostname or command"}
    result = queue_agent_command_and_wait(
        hostname, cmd_type, cmd_params, timeout=timeout, queued_by="remediation",
    )
    if result is None:
        return {"success": False, "output": f"Agent command timed out"}
    status = result.get("status", "error")
    return {"success": status != "error", "output": f"Agent command: {status}"}
```

Add to `_HANDLERS`:
```python
"run": _handle_run,
"webhook": _handle_webhook,
"automation": _handle_automation,
"agent_command": _handle_agent_command,
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_remediation_extended.py tests/test_remediation.py -v`
Expected: All PASS

- [ ] **Step 5: Run full test suite**

Run: `pytest tests/ -v`
Expected: All PASS

- [ ] **Step 6: Lint and commit**

```bash
ruff check --fix share/noba-web/server/remediation.py
git add share/noba-web/server/remediation.py tests/test_remediation_extended.py
git commit -m "feat(remediation): migrate run/webhook/automation/agent_command action types"
```

---

## Task 6: Trust Governor

**Files:**
- Create: `share/noba-web/server/healing/governor.py`
- Create: `tests/test_heal_governor.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_heal_governor.py`:
```python
"""Tests for healing trust governor: promotion, demotion, effective trust."""
from __future__ import annotations

import json
import time
from unittest.mock import MagicMock


class TestEffectiveTrust:
    def _db(self):
        from server.db.core import Database
        db = Database(":memory:")
        db.init()
        return db

    def test_no_state_returns_notify(self):
        from server.healing.governor import effective_trust
        db = self._db()
        assert effective_trust("rule1", "alert", db) == "notify"

    def test_returns_stored_level(self):
        from server.healing.governor import effective_trust
        db = self._db()
        db.upsert_trust_state("rule1", "approve", "execute")
        assert effective_trust("rule1", "alert", db) == "approve"

    def test_prediction_source_caps_one_below(self):
        from server.healing.governor import effective_trust
        db = self._db()
        db.upsert_trust_state("rule1", "execute", "execute")
        assert effective_trust("rule1", "prediction", db) == "approve"

    def test_prediction_at_notify_stays_notify(self):
        from server.healing.governor import effective_trust
        db = self._db()
        db.upsert_trust_state("rule1", "notify", "execute")
        assert effective_trust("rule1", "prediction", db) == "notify"


class TestCircuitBreaker:
    def _db(self):
        from server.db.core import Database
        db = Database(":memory:")
        db.init()
        return db

    def test_three_failures_demotes(self):
        from server.healing.governor import check_circuit_breaker
        db = self._db()
        db.upsert_trust_state("rule1", "execute", "execute")
        now = int(time.time())
        for _ in range(3):
            db.insert_heal_outcome(
                correlation_key="test", rule_id="rule1",
                condition="cpu > 90", target="nginx",
                action_type="restart_container",
                action_params="{}", escalation_step=0,
                action_success=1, verified=0,
                duration_s=1.0, metrics_before="{}",
                metrics_after="{}", trust_level="execute",
                source="alert", approval_id=None,
            )
        tripped = check_circuit_breaker("rule1", db)
        assert tripped is True
        state = db.get_trust_state("rule1")
        assert state["current_level"] == "notify"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_heal_governor.py -v`
Expected: FAIL — ImportError

- [ ] **Step 3: Implement governor.py**

Create `share/noba-web/server/healing/governor.py`:
```python
"""Noba -- Trust governor: graduated trust with promotion and demotion."""
from __future__ import annotations

import logging
import threading
import time

logger = logging.getLogger("noba")

_LEVEL_ORDER = {"notify": 0, "approve": 1, "execute": 2}
_LEVEL_BELOW = {"execute": "approve", "approve": "notify", "notify": "notify"}

CIRCUIT_BREAKER_THRESHOLD = 3
CIRCUIT_BREAKER_WINDOW_S = 3600

_lock = threading.Lock()


def effective_trust(rule_id: str, source: str, db) -> str:
    """Resolve the actual trust level for a rule, considering source caps."""
    state = db.get_trust_state(rule_id)
    if not state:
        return "notify"
    level = state["current_level"]
    if source == "prediction":
        level = _LEVEL_BELOW.get(level, "notify")
    return level


def check_circuit_breaker(rule_id: str, db) -> bool:
    """Check if circuit breaker should trip. Returns True if tripped (demoted)."""
    cutoff = int(time.time()) - CIRCUIT_BREAKER_WINDOW_S
    outcomes = db.get_heal_outcomes(rule_id=rule_id, limit=CIRCUIT_BREAKER_THRESHOLD)
    recent_failures = [
        o for o in outcomes
        if o["created_at"] >= cutoff
        and o["action_success"] is not None
        and o["verified"] == 0
    ]
    if len(recent_failures) >= CIRCUIT_BREAKER_THRESHOLD:
        with _lock:
            state = db.get_trust_state(rule_id)
            if state and state["current_level"] != "notify":
                db.upsert_trust_state(rule_id, "notify", state["ceiling"])
                logger.warning(
                    "Circuit breaker tripped for rule %s — demoted to notify",
                    rule_id,
                )
                return True
    return False


def evaluate_promotions(db) -> list[dict]:
    """Check all rules for promotion eligibility. Returns list of suggestions."""
    from .models import HealSuggestion

    suggestions: list[dict] = []
    states = db.list_trust_states()
    now = int(time.time())
    min_executions = 10
    min_success_rate = 85.0
    min_age_s = 168 * 3600  # 7 days

    for state in states:
        rule_id = state["rule_id"]
        current = state["current_level"]
        ceiling = state["ceiling"]

        if _LEVEL_ORDER.get(current, 0) >= _LEVEL_ORDER.get(ceiling, 0):
            continue  # already at ceiling

        last_change = state.get("promoted_at") or state.get("demoted_at") or state.get("last_evaluated") or 0
        if now - last_change < min_age_s:
            continue  # too soon

        outcomes = db.get_heal_outcomes(rule_id=rule_id, limit=200)
        at_current = [o for o in outcomes if o["trust_level"] == current]
        if len(at_current) < min_executions:
            continue

        if current == "notify":
            # For notify->approve: just need enough trigger count
            next_level = "approve"
        elif current == "approve":
            # For approve->execute: need verified success rate
            with_action = [o for o in at_current if o["action_success"] is not None]
            if len(with_action) < min_executions:
                continue
            verified = sum(1 for o in with_action if o["verified"] == 1)
            rate = (verified / len(with_action)) * 100
            if rate < min_success_rate:
                continue
            next_level = "execute"
        else:
            continue

        suggestions.append({
            "category": "trust_promotion",
            "severity": "info",
            "message": f"Rule '{rule_id}' eligible for promotion: {current} -> {next_level}",
            "rule_id": rule_id,
            "suggested_action": {"promote_to": next_level},
            "evidence": {"total_outcomes": len(at_current)},
        })

    return suggestions
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_heal_governor.py -v`
Expected: All PASS

- [ ] **Step 5: Lint and commit**

```bash
ruff check --fix share/noba-web/server/healing/governor.py
git add share/noba-web/server/healing/governor.py tests/test_heal_governor.py
git commit -m "feat(healing): add trust governor with circuit breaker and promotion"
```

---

## Task 7: Heal Planner

**Files:**
- Create: `share/noba-web/server/healing/planner.py`
- Create: `tests/test_heal_planner.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_heal_planner.py`:
```python
"""Tests for healing planner: escalation chains, adaptive scoring."""
from __future__ import annotations

import time
from unittest.mock import MagicMock


def _make_request(target="nginx"):
    from server.healing.models import HealEvent, HealRequest
    event = HealEvent(
        source="alert", rule_id="cpu_high",
        condition="cpu_percent > 90", target=target,
        severity="warning", timestamp=time.time(),
        metrics={"cpu_percent": 95},
    )
    return HealRequest(
        correlation_key=target, events=[event],
        primary_target=target, severity="warning",
        created_at=time.time(),
    )


def _chain():
    return [
        {"action": "restart_container", "params": {"container": "nginx"}, "verify_timeout": 30},
        {"action": "scale_container", "params": {"container": "nginx", "mem_limit": "4g"}, "verify_timeout": 30},
    ]


class TestSelectAction:
    def test_selects_first_step(self):
        from server.healing.planner import HealPlanner
        db = MagicMock()
        db.get_heal_success_rate = MagicMock(return_value=80.0)
        db.get_trust_state = MagicMock(return_value={"current_level": "execute", "ceiling": "execute"})
        planner = HealPlanner()
        plan = planner.select_action(
            _make_request(), _chain(), db,
            effective_trust="execute",
        )
        assert plan.action_type == "restart_container"
        assert plan.escalation_step == 0

    def test_skips_low_effectiveness_action(self):
        from server.healing.planner import HealPlanner
        db = MagicMock()
        # First action has 10% success rate (below 30% threshold)
        db.get_heal_success_rate = MagicMock(side_effect=[10.0, 80.0])
        planner = HealPlanner()
        plan = planner.select_action(
            _make_request(), _chain(), db,
            effective_trust="execute",
        )
        assert plan.action_type == "scale_container"
        assert plan.escalation_step == 1
        assert len(plan.skipped_actions) == 1


class TestAdvance:
    def test_advances_step(self):
        from server.healing.planner import HealPlanner
        from server.healing.models import HealOutcome
        db = MagicMock()
        db.get_heal_success_rate = MagicMock(return_value=80.0)
        planner = HealPlanner()
        plan = planner.select_action(
            _make_request(), _chain(), db,
            effective_trust="execute",
        )
        outcome = HealOutcome(
            plan=plan, action_success=True, verified=False,
            verification_detail="still failing", duration_s=15.0,
        )
        next_plan = planner.advance(outcome, _chain(), db, effective_trust="execute")
        assert next_plan is not None
        assert next_plan.escalation_step == 1
        assert next_plan.action_type == "scale_container"

    def test_returns_none_when_exhausted(self):
        from server.healing.planner import HealPlanner
        from server.healing.models import HealOutcome, HealPlan
        planner = HealPlanner()
        plan = HealPlan(
            request=_make_request(), action_type="scale_container",
            action_params={}, escalation_step=1, trust_level="execute",
        )
        outcome = HealOutcome(
            plan=plan, action_success=True, verified=False,
        )
        next_plan = planner.advance(outcome, _chain(), db=MagicMock(), effective_trust="execute")
        assert next_plan is None


class TestEscalationGuard:
    def test_rejects_duplicate_escalation(self):
        from server.healing.planner import HealPlanner
        db = MagicMock()
        db.get_heal_success_rate = MagicMock(return_value=80.0)
        planner = HealPlanner()
        planner.select_action(
            _make_request("nginx"), _chain(), db,
            effective_trust="execute",
        )
        # Same target while escalation is in progress
        plan2 = planner.select_action(
            _make_request("nginx"), _chain(), db,
            effective_trust="execute",
        )
        assert plan2 is None

    def test_max_depth_enforced(self):
        from server.healing.planner import HealPlanner, MAX_ESCALATION_DEPTH
        assert MAX_ESCALATION_DEPTH == 6
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_heal_planner.py -v`
Expected: FAIL — ImportError

- [ ] **Step 3: Implement planner.py**

Create `share/noba-web/server/healing/planner.py`:
```python
"""Noba -- Heal planner: escalation chains with adaptive scoring."""
from __future__ import annotations

import logging
import threading

from .models import HealOutcome, HealPlan, HealRequest

logger = logging.getLogger("noba")

MAX_ESCALATION_DEPTH = 6
_MIN_EFFECTIVENESS = 30.0  # skip actions below this success rate


class HealPlanner:
    """Select heal actions with escalation chain support and adaptive scoring."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active_escalations: dict[str, int] = {}  # correlation_key -> current step

    def select_action(
        self, request: HealRequest, chain: list[dict], db,
        effective_trust: str,
    ) -> HealPlan | None:
        key = request.correlation_key

        with self._lock:
            if key in self._active_escalations:
                logger.debug("Planner: escalation already in progress for %s", key)
                return None
            self._active_escalations[key] = 0

        return self._pick_step(request, chain, db, effective_trust, start_step=0)

    def advance(
        self, outcome: HealOutcome, chain: list[dict], db,
        effective_trust: str,
    ) -> HealPlan | None:
        key = outcome.plan.request.correlation_key
        next_step = outcome.plan.escalation_step + 1

        if next_step >= len(chain) or next_step >= MAX_ESCALATION_DEPTH:
            self._clear_escalation(key)
            logger.info("Planner: escalation chain exhausted for %s", key)
            return None

        with self._lock:
            self._active_escalations[key] = next_step

        plan = self._pick_step(
            outcome.plan.request, chain, db, effective_trust,
            start_step=next_step,
        )
        if plan is None:
            self._clear_escalation(key)
        return plan

    def clear_escalation(self, key: str) -> None:
        """Public method to clear escalation state (e.g., on success)."""
        self._clear_escalation(key)

    def _clear_escalation(self, key: str) -> None:
        with self._lock:
            self._active_escalations.pop(key, None)

    def _pick_step(
        self, request: HealRequest, chain: list[dict], db,
        effective_trust: str, start_step: int,
    ) -> HealPlan | None:
        skipped: list[dict] = []

        for step_idx in range(start_step, min(len(chain), MAX_ESCALATION_DEPTH)):
            step = chain[step_idx]
            action_type = step["action"]
            condition = request.events[0].condition if request.events else ""

            # Adaptive scoring: skip low-effectiveness actions
            rate = db.get_heal_success_rate(action_type, condition, target=request.primary_target)
            if rate > 0 and rate < _MIN_EFFECTIVENESS:
                skipped.append({"action": action_type, "success_rate": rate, "step": step_idx})
                logger.info(
                    "Planner: skipping %s (%.1f%% success rate) for %s",
                    action_type, rate, request.correlation_key,
                )
                continue

            reason_parts = [f"Selected {action_type} (step {step_idx + 1}/{len(chain)})"]
            if skipped:
                skip_strs = [f"{s['action']} ({s['success_rate']:.0f}%)" for s in skipped]
                reason_parts.append(f"Skipped: {', '.join(skip_strs)}")

            return HealPlan(
                request=request,
                action_type=action_type,
                action_params=step.get("params", {}),
                escalation_step=step_idx,
                trust_level=effective_trust,
                reason=". ".join(reason_parts),
                skipped_actions=skipped,
            )

        # All steps skipped or exhausted
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_heal_planner.py -v`
Expected: All PASS

- [ ] **Step 5: Lint and commit**

```bash
ruff check --fix share/noba-web/server/healing/planner.py
git add share/noba-web/server/healing/planner.py tests/test_heal_planner.py
git commit -m "feat(healing): add planner with escalation chains and adaptive scoring"
```

---

## Task 8: Heal Executor

**Files:**
- Create: `share/noba-web/server/healing/executor.py`
- Create: `tests/test_heal_executor.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_heal_executor.py`:
```python
"""Tests for healing executor: async execution + condition verification."""
from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch


def _make_plan(action_type="restart_container", condition="cpu_percent > 90"):
    from server.healing.models import HealEvent, HealRequest, HealPlan
    event = HealEvent(
        source="alert", rule_id="r1", condition=condition,
        target="nginx", severity="warning",
        timestamp=time.time(), metrics={"cpu_percent": 95},
    )
    request = HealRequest(
        correlation_key="nginx", events=[event],
        primary_target="nginx", severity="warning",
        created_at=time.time(),
    )
    return HealPlan(
        request=request, action_type=action_type,
        action_params={"container": "nginx"},
        escalation_step=0, trust_level="execute",
    )


class TestExecutor:
    @patch("server.healing.executor._get_fresh_metrics")
    @patch("server.remediation.execute_action")
    def test_successful_heal(self, mock_exec, mock_metrics):
        from server.healing.executor import HealExecutor
        mock_exec.return_value = {"success": True, "output": "OK", "duration_s": 1.0}
        # After heal, cpu drops below threshold
        mock_metrics.return_value = {"cpu_percent": 40}

        results = []
        done = threading.Event()

        def on_complete(outcome):
            results.append(outcome)
            done.set()

        executor = HealExecutor(settle_times={"restart_container": 0.01})
        executor.execute(_make_plan(), on_complete)
        done.wait(timeout=5)

        assert len(results) == 1
        assert results[0].action_success is True
        assert results[0].verified is True

    @patch("server.healing.executor._get_fresh_metrics")
    @patch("server.remediation.execute_action")
    def test_unverified_heal(self, mock_exec, mock_metrics):
        from server.healing.executor import HealExecutor
        mock_exec.return_value = {"success": True, "output": "OK", "duration_s": 1.0}
        # After heal, cpu still above threshold
        mock_metrics.return_value = {"cpu_percent": 95}

        results = []
        done = threading.Event()

        def on_complete(outcome):
            results.append(outcome)
            done.set()

        executor = HealExecutor(settle_times={"restart_container": 0.01})
        executor.execute(_make_plan(), on_complete)
        done.wait(timeout=5)

        assert len(results) == 1
        assert results[0].action_success is True
        assert results[0].verified is False

    @patch("server.remediation.execute_action")
    def test_failed_action(self, mock_exec):
        from server.healing.executor import HealExecutor
        mock_exec.return_value = {"success": False, "error": "boom", "duration_s": 0.5}

        results = []
        done = threading.Event()

        def on_complete(outcome):
            results.append(outcome)
            done.set()

        executor = HealExecutor(settle_times={"restart_container": 0.01})
        executor.execute(_make_plan(), on_complete)
        done.wait(timeout=5)

        assert len(results) == 1
        assert results[0].action_success is False

    def test_execute_is_nonblocking(self):
        from server.healing.executor import HealExecutor
        executor = HealExecutor(settle_times={"restart_container": 10})
        start = time.time()
        with patch("server.remediation.execute_action", return_value={"success": True}):
            executor.execute(_make_plan(), lambda o: None)
        elapsed = time.time() - start
        assert elapsed < 1.0  # Must return immediately
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_heal_executor.py -v`
Expected: FAIL — ImportError

- [ ] **Step 3: Implement executor.py**

Create `share/noba-web/server/healing/executor.py`:
```python
"""Noba -- Heal executor: async action execution with condition verification."""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from .condition_eval import flatten_metrics, safe_eval
from .models import HealOutcome, HealPlan

logger = logging.getLogger("noba")

_DEFAULT_SETTLE_TIMES: dict[str, float] = {
    "restart_container": 15, "restart_service": 15,
    "scale_container": 15, "clear_cache": 15, "flush_dns": 15,
    "run_playbook": 120, "trigger_backup": 60,
    "run": 15, "webhook": 15, "automation": 15, "agent_command": 30,
    "failover_dns": 30,
}


def _get_fresh_metrics() -> dict:
    """Fetch current metrics from the background collector."""
    try:
        from ..collector import bg_collector
        return bg_collector.get() or {}
    except Exception:
        return {}


class HealExecutor:
    """Execute heal actions asynchronously with condition-based verification."""

    def __init__(self, settle_times: dict[str, float] | None = None) -> None:
        self._settle_times = settle_times or _DEFAULT_SETTLE_TIMES

    def execute(
        self, plan: HealPlan,
        on_complete: Callable[[HealOutcome], None],
    ) -> None:
        """Non-blocking: spawns a daemon thread to run action + verify."""
        threading.Thread(
            target=self._execute_and_verify,
            args=(plan, on_complete),
            daemon=True,
            name=f"heal-{plan.request.correlation_key}:{plan.escalation_step}",
        ).start()

    def _execute_and_verify(
        self, plan: HealPlan,
        on_complete: Callable[[HealOutcome], None],
    ) -> None:
        from ..remediation import execute_action

        start = time.time()
        metrics_before = {}
        if plan.request.events:
            metrics_before = plan.request.events[0].metrics

        try:
            result = execute_action(
                plan.action_type, plan.action_params,
                triggered_by=f"heal:{plan.request.correlation_key}",
                trigger_type="healing_pipeline",
            )
        except Exception as exc:
            logger.error("Heal executor action failed: %s", exc)
            outcome = HealOutcome(
                plan=plan, action_success=False, verified=False,
                verification_detail=f"Exception: {exc}",
                duration_s=round(time.time() - start, 2),
                metrics_before=metrics_before,
            )
            on_complete(outcome)
            return

        action_ok = result.get("success", False)

        if not action_ok:
            outcome = HealOutcome(
                plan=plan, action_success=False, verified=False,
                verification_detail=result.get("error", "Action failed"),
                duration_s=round(time.time() - start, 2),
                metrics_before=metrics_before,
            )
            on_complete(outcome)
            return

        # Wait settle time
        settle = self._settle_times.get(plan.action_type, 15)
        time.sleep(settle)

        # Verify: re-evaluate original conditions
        raw_metrics = _get_fresh_metrics()
        flat = flatten_metrics(raw_metrics)
        metrics_after = flat

        all_resolved = True
        details: list[str] = []
        for event in plan.request.events:
            still_firing = safe_eval(event.condition, flat)
            if still_firing:
                all_resolved = False
                details.append(f"{event.condition} still true")
            else:
                details.append(f"{event.condition} resolved")

        outcome = HealOutcome(
            plan=plan,
            action_success=True,
            verified=all_resolved,
            verification_detail="; ".join(details),
            duration_s=round(time.time() - start, 2),
            metrics_before=metrics_before,
            metrics_after=metrics_after,
        )
        on_complete(outcome)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_heal_executor.py -v`
Expected: All PASS

- [ ] **Step 5: Lint and commit**

```bash
ruff check --fix share/noba-web/server/healing/executor.py
git add share/noba-web/server/healing/executor.py tests/test_heal_executor.py
git commit -m "feat(healing): add async executor with condition-based verification"
```

---

## Task 9: Heal Ledger business logic

**Files:**
- Create: `share/noba-web/server/healing/ledger.py`

- [ ] **Step 1: Implement ledger.py**

Create `share/noba-web/server/healing/ledger.py`:
```python
"""Noba -- Heal ledger: record outcomes and generate suggestions."""
from __future__ import annotations

import json
import logging
import time

from .models import HealOutcome

logger = logging.getLogger("noba")

_RECURRING_THRESHOLD = 10  # triggers in 30 days
_LOW_EFFECTIVENESS_THRESHOLD = 30.0  # percent


def record(outcome: HealOutcome, db) -> int:
    """Record a HealOutcome to the DB."""
    plan = outcome.plan
    event = plan.request.events[0] if plan.request.events else None
    return db.insert_heal_outcome(
        correlation_key=plan.request.correlation_key,
        rule_id=event.rule_id if event else "",
        condition=event.condition if event else "",
        target=plan.request.primary_target,
        action_type=plan.action_type,
        action_params=json.dumps(plan.action_params),
        escalation_step=plan.escalation_step,
        action_success=1 if outcome.action_success is True else (0 if outcome.action_success is False else None),
        verified=1 if outcome.verified is True else (0 if outcome.verified is False else None),
        duration_s=outcome.duration_s,
        metrics_before=json.dumps(outcome.metrics_before),
        metrics_after=json.dumps(outcome.metrics_after) if outcome.metrics_after else None,
        trust_level=plan.trust_level,
        source=event.source if event else "unknown",
        approval_id=outcome.approval_id,
    )


def generate_suggestions(db) -> list[dict]:
    """Analyze ledger data and produce actionable suggestions."""
    suggestions: list[dict] = []
    outcomes = db.get_heal_outcomes(limit=500)

    # Group by rule_id + target
    groups: dict[str, list[dict]] = {}
    for o in outcomes:
        key = f"{o['rule_id']}:{o['target']}"
        groups.setdefault(key, []).append(o)

    for key, items in groups.items():
        rule_id = items[0]["rule_id"]
        target = items[0]["target"]
        executed = [i for i in items if i["action_success"] is not None]

        # Recurring issue detection
        if len(executed) >= _RECURRING_THRESHOLD:
            suggestions.append({
                "category": "recurring_issue",
                "severity": "warning",
                "message": (
                    f"Target '{target}' healed {len(executed)} times for "
                    f"rule '{rule_id}'. Consider investigating root cause."
                ),
                "rule_id": rule_id,
            })

        # Low effectiveness detection
        if executed:
            verified = sum(1 for i in executed if i["verified"] == 1)
            rate = (verified / len(executed)) * 100
            if rate < _LOW_EFFECTIVENESS_THRESHOLD and len(executed) >= 5:
                action = items[0]["action_type"]
                suggestions.append({
                    "category": "low_effectiveness",
                    "severity": "warning",
                    "message": (
                        f"Action '{action}' has {rate:.0f}% success rate for "
                        f"rule '{rule_id}' on '{target}'."
                    ),
                    "rule_id": rule_id,
                })

    # Persist suggestions
    for s in suggestions:
        db.insert_heal_suggestion(**s)

    return suggestions
```

- [ ] **Step 2: Lint and commit**

```bash
ruff check --fix share/noba-web/server/healing/ledger.py
git add share/noba-web/server/healing/ledger.py
git commit -m "feat(healing): add ledger business logic with suggestion engine"
```

---

## Task 10: Pipeline entry point and alerts.py integration

**Files:**
- Modify: `share/noba-web/server/healing/__init__.py`
- Modify: `share/noba-web/server/alerts.py`
- Create: `tests/test_heal_pipeline.py`

- [ ] **Step 1: Write failing integration test**

Create `tests/test_heal_pipeline.py`:
```python
"""Integration tests for the full healing pipeline."""
from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch


class TestHandleHealEvent:
    def _db(self):
        from server.db.core import Database
        db = Database(":memory:")
        db.init()
        return db

    def _event(self, target="nginx", source="alert"):
        from server.healing.models import HealEvent
        return HealEvent(
            source=source, rule_id="cpu_high",
            condition="cpu_percent > 90", target=target,
            severity="warning", timestamp=time.time(),
            metrics={"cpu_percent": 95},
        )

    @patch("server.healing.executor._get_fresh_metrics")
    @patch("server.remediation.execute_action")
    def test_full_pipeline_execute(self, mock_exec, mock_metrics):
        mock_exec.return_value = {"success": True, "output": "OK", "duration_s": 1.0}
        mock_metrics.return_value = {"cpu_percent": 40}

        db = self._db()
        db.upsert_trust_state("cpu_high", "execute", "execute")

        chain = [{"action": "restart_container", "params": {"container": "nginx"}, "verify_timeout": 30}]
        rules_cfg = {"cpu_high": {"escalation_chain": chain}}

        from server.healing import create_pipeline

        done = threading.Event()
        outcomes = []

        def on_outcome(outcome):
            outcomes.append(outcome)
            done.set()

        pipeline = create_pipeline(db, rules_cfg, settle_times={"restart_container": 0.01})
        pipeline.on_outcome = on_outcome
        pipeline.handle_heal_event(self._event())
        done.wait(timeout=5)

        assert len(outcomes) == 1
        assert outcomes[0].verified is True
        # Check ledger was written
        rows = db.get_heal_outcomes()
        assert len(rows) >= 1

    def test_notify_path_records_ledger(self):
        db = self._db()
        db.upsert_trust_state("cpu_high", "notify", "execute")

        chain = [{"action": "restart_container", "params": {"container": "nginx"}}]
        rules_cfg = {"cpu_high": {"escalation_chain": chain}}

        from server.healing import create_pipeline
        pipeline = create_pipeline(db, rules_cfg)

        with patch("server.healing.dispatch_notifications"):
            pipeline.handle_heal_event(self._event())

        rows = db.get_heal_outcomes()
        assert len(rows) == 1
        assert rows[0]["action_success"] is None  # notify = no action
        assert rows[0]["trust_level"] == "notify"

    def test_correlation_absorbs_duplicate(self):
        db = self._db()
        db.upsert_trust_state("cpu_high", "notify", "execute")

        chain = [{"action": "restart_container", "params": {"container": "nginx"}}]
        rules_cfg = {"cpu_high": {"escalation_chain": chain}}

        from server.healing import create_pipeline
        pipeline = create_pipeline(db, rules_cfg)

        with patch("server.healing.dispatch_notifications"):
            pipeline.handle_heal_event(self._event())
            pipeline.handle_heal_event(self._event())  # same target, absorbed

        rows = db.get_heal_outcomes()
        assert len(rows) == 1  # only one recorded
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_heal_pipeline.py -v`
Expected: FAIL — `create_pipeline` not found

- [ ] **Step 3: Implement pipeline entry point**

Update `share/noba-web/server/healing/__init__.py`:
```python
"""Noba -- Self-healing pipeline."""
from __future__ import annotations

import json
import logging
import threading

from .correlation import HealCorrelator
from .executor import HealExecutor
from .governor import check_circuit_breaker, effective_trust
from .models import HealEvent, HealOutcome, HealPlan
from .planner import HealPlanner

logger = logging.getLogger("noba")


def dispatch_notifications(severity: str, message: str, notif_cfg: dict | None = None, channels: list | None = None) -> None:
    """Dispatch notifications via the alerts module."""
    try:
        from ..alerts import dispatch_notifications as _dispatch
        from ..yaml_config import read_yaml_settings
        cfg = read_yaml_settings()
        nc = notif_cfg or cfg.get("notifications", {})
        _dispatch(severity, message, nc, channels)
    except Exception as exc:
        logger.error("Heal notification failed: %s", exc)


class HealPipeline:
    """Main pipeline orchestrator. Non-blocking, thread-safe."""

    def __init__(self, db, rules_cfg: dict, settle_times: dict | None = None) -> None:
        self._db = db
        self._rules_cfg = rules_cfg  # {rule_id: {escalation_chain: [...]}}
        self._correlator = HealCorrelator()
        self._planner = HealPlanner()
        self._executor = HealExecutor(settle_times=settle_times)
        self.on_outcome = None  # optional callback for testing

    def update_rule_config(self, rule_id: str, config: dict) -> None:
        """Update or add a rule's config (thread-safe)."""
        self._rules_cfg[rule_id] = config

    def handle_heal_event(self, event: HealEvent) -> None:
        """Non-blocking pipeline entry point. Safe to call from any thread."""
        request = self._correlator.correlate(event)
        if request is None:
            return  # absorbed

        rule_cfg = self._rules_cfg.get(event.rule_id, {})
        chain = rule_cfg.get("escalation_chain", [
            {"action": "restart_container", "params": {}, "verify_timeout": 30},
        ])

        trust = effective_trust(event.rule_id, event.source, self._db)

        # Check circuit breaker
        if check_circuit_breaker(event.rule_id, self._db):
            trust = "notify"

        plan = self._planner.select_action(request, chain, self._db, effective_trust=trust)
        if plan is None:
            return  # escalation in progress or chain exhausted

        if plan.trust_level == "notify":
            self._handle_notify(plan, event)
        elif plan.trust_level == "approve":
            self._handle_approve(plan, event)
        else:
            self._handle_execute(plan, chain)

    def _handle_notify(self, plan: HealPlan, event: HealEvent) -> None:
        from . import ledger
        outcome = HealOutcome(
            plan=plan, action_success=None, verified=None,
            verification_detail="notify only", duration_s=0,
            metrics_before=event.metrics,
        )
        ledger.record(outcome, self._db)
        dispatch_notifications(plan.request.severity, plan.reason)
        if self.on_outcome:
            self.on_outcome(outcome)
        self._planner.clear_escalation(plan.request.correlation_key)

    def _handle_approve(self, plan: HealPlan, event: HealEvent) -> None:
        from . import ledger
        approval_id = None
        try:
            approval_id = self._db.insert_approval(
                automation_id=event.rule_id,
                trigger=f"heal:{plan.request.correlation_key}",
                trigger_source="healing_pipeline",
                action_type=plan.action_type,
                action_params=plan.action_params,
                target=plan.request.primary_target,
                requested_by=f"heal:{event.source}",
            )
        except Exception as exc:
            logger.error("Heal approval insert failed: %s", exc)

        outcome = HealOutcome(
            plan=plan, action_success=None, verified=None,
            verification_detail="queued for approval", duration_s=0,
            metrics_before=event.metrics, approval_id=approval_id,
        )
        ledger.record(outcome, self._db)
        dispatch_notifications(
            plan.request.severity,
            f"[APPROVAL NEEDED] {plan.reason}",
        )
        if self.on_outcome:
            self.on_outcome(outcome)
        self._planner.clear_escalation(plan.request.correlation_key)

    def _handle_execute(self, plan: HealPlan, chain: list[dict]) -> None:
        from . import ledger

        def on_complete(outcome: HealOutcome) -> None:
            ledger.record(outcome, self._db)
            if self.on_outcome:
                self.on_outcome(outcome)

            if outcome.verified:
                self._planner.clear_escalation(plan.request.correlation_key)
                return

            # Escalation
            trust = effective_trust(
                plan.request.events[0].rule_id if plan.request.events else "",
                plan.request.events[0].source if plan.request.events else "alert",
                self._db,
            )
            next_plan = self._planner.advance(outcome, chain, self._db, effective_trust=trust)
            if next_plan:
                self._executor.execute(next_plan, on_complete=on_complete)

        self._executor.execute(plan, on_complete=on_complete)


_singleton: HealPipeline | None = None
_singleton_lock = threading.Lock()


def create_pipeline(db, rules_cfg: dict, settle_times: dict | None = None) -> HealPipeline:
    """Factory function for creating a pipeline instance (used in tests)."""
    return HealPipeline(db, rules_cfg, settle_times=settle_times)


def get_pipeline() -> HealPipeline:
    """Get or create the module-level singleton pipeline.

    Uses the shared DB instance from deps. Correlation and escalation state
    persist across calls — this is critical for correct behavior.
    """
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                from ..db import db as _db
                _singleton = HealPipeline(_db, {})
    return _singleton
```

- [ ] **Step 4: Run integration tests**

Run: `pytest tests/test_heal_pipeline.py -v`
Expected: All PASS

- [ ] **Step 5: Run full test suite**

Run: `pytest tests/ -v`
Expected: All PASS

- [ ] **Step 6: Lint and commit**

```bash
ruff check --fix share/noba-web/server/healing/__init__.py
git add share/noba-web/server/healing/__init__.py tests/test_heal_pipeline.py
git commit -m "feat(healing): add pipeline entry point with notify/approve/execute paths"
```

---

## Task 11: Wire alerts.py to healing pipeline

**Files:**
- Modify: `share/noba-web/server/alerts.py`

- [ ] **Step 1: Add healing pipeline integration to evaluate_alert_rules**

In `share/noba-web/server/alerts.py`, in the `evaluate_alert_rules` function, after the existing notification dispatch and incident creation block (around line 540), replace the `_execute_heal` section with:

```python
# ── Healing pipeline integration ──────────────────────────
try:
    from .healing import get_pipeline
    from .healing.models import HealEvent

    heal_event = HealEvent(
        source="alert",
        rule_id=rule_id,
        condition=condition,
        target=action_cfg.get("target", ""),
        severity=severity,
        timestamp=now,
        metrics=dict(flat),
    )
    # Build rules config from alert rule
    chain = rule.get("escalation_chain", [])
    if not chain and action_cfg:
        # Legacy: single action, wrap as chain
        chain = [{"action": action_cfg.get("type", ""), "params": {k: v for k, v in action_cfg.items() if k != "type"}}]

    pipeline = get_pipeline()  # module-level singleton
    pipeline.update_rule_config(rule_id, {"escalation_chain": chain})
    pipeline.handle_heal_event(heal_event)
except Exception as exc:
    logger.error("Healing pipeline error for rule %s: %s", rule_id, exc)
```

Remove the old `_execute_heal` call block and the inline retry/circuit-breaker logic (the `max_retries`, `circuit_break_after`, `_alert_state.append_trigger`, etc. block from ~line 565 onwards). Keep `_execute_heal` function itself for now as a fallback reference.

- [ ] **Step 2: Run full test suite**

Run: `pytest tests/ -v`
Expected: All PASS (existing alert tests should still work since notifications flow unchanged)

- [ ] **Step 3: Lint and commit**

```bash
ruff check --fix share/noba-web/server/alerts.py
git add share/noba-web/server/alerts.py
git commit -m "feat(healing): wire alert evaluator to healing pipeline"
```

---

## Task 12: Agent heal runtime

**Files:**
- Create: `share/noba-web/server/healing/agent_runtime.py`
- Modify: `share/noba-web/server/routers/agents.py`

- [ ] **Step 1: Implement agent_runtime.py**

Create `share/noba-web/server/healing/agent_runtime.py`:
```python
"""Noba -- Agent heal runtime: policy distribution and report ingestion."""
from __future__ import annotations

import json
import logging

from .models import AgentHealPolicy, AgentHealRule

logger = logging.getLogger("noba")

_LOW_RISK_TYPES = frozenset({"restart_container", "restart_service", "clear_cache", "flush_dns"})
_policy_version = 0


def build_agent_policy(hostname: str, rules_cfg: dict, db) -> dict:
    """Build a lightweight heal policy for a specific agent."""
    global _policy_version
    agent_rules: list[dict] = []

    for rule_id, cfg in rules_cfg.items():
        chain = cfg.get("escalation_chain", [])
        for step in chain:
            action = step.get("action", "")
            if action not in _LOW_RISK_TYPES:
                continue
            state = db.get_trust_state(rule_id)
            trust = state["current_level"] if state else "notify"
            agent_rules.append({
                "rule_id": rule_id,
                "condition": cfg.get("condition", ""),
                "action_type": action,
                "action_params": step.get("params", {}),
                "max_retries": 3,
                "cooldown_s": 300,
                "trust_level": trust,
                "fallback_mode": None,
            })

    return {
        "rules": agent_rules,
        "version": _policy_version,
        "fallback_mode": "queue_for_server",
    }


def ingest_agent_heal_reports(hostname: str, reports: list[dict], db) -> None:
    """Process heal outcomes reported by agents and feed into ledger."""
    for report in reports:
        try:
            db.insert_heal_outcome(
                correlation_key=f"agent:{hostname}:{report.get('rule_id', '')}",
                rule_id=report.get("rule_id", ""),
                condition=report.get("condition", ""),
                target=hostname,
                action_type=report.get("action_type", ""),
                action_params=json.dumps(report.get("action_params", {})),
                escalation_step=0,
                action_success=1 if report.get("success") else 0,
                verified=1 if report.get("verified") else (0 if report.get("verified") is False else None),
                duration_s=report.get("duration_s", 0),
                metrics_before=json.dumps(report.get("metrics_before", {})),
                metrics_after=json.dumps(report.get("metrics_after", {})),
                trust_level=report.get("trust_level", "execute"),
                source="agent",
                approval_id=None,
            )
        except Exception as exc:
            logger.error("Failed to ingest agent heal report from %s: %s", hostname, exc)
```

- [ ] **Step 2: Add heal policy to agent heartbeat response**

In `share/noba-web/server/routers/agents.py`, in `api_agent_report`, right before the `return {"status": "ok", "commands": pending}` line, add:

```python
    # Include heal policy if available
    heal_policy = {}
    try:
        from ..healing.agent_runtime import build_agent_policy
        from ..yaml_config import read_yaml_settings
        cfg = read_yaml_settings()
        alert_rules = cfg.get("alertRules", [])
        rules_cfg = {}
        for rule in alert_rules:
            rid = rule.get("id", "")
            if rid:
                rules_cfg[rid] = {
                    "escalation_chain": rule.get("escalation_chain", []),
                    "condition": rule.get("condition", ""),
                }
        heal_policy = build_agent_policy(hostname, rules_cfg, db)
    except Exception:
        pass

    # Ingest heal reports if present
    heal_reports = body.pop("_heal_reports", None)
    if heal_reports and isinstance(heal_reports, list):
        try:
            from ..healing.agent_runtime import ingest_agent_heal_reports
            ingest_agent_heal_reports(hostname, heal_reports, db)
        except Exception as exc:
            logger.warning("Failed to ingest heal reports from %s: %s", hostname, exc)

    return {"status": "ok", "commands": pending, "heal_policy": heal_policy}
```

- [ ] **Step 3: Run full test suite**

Run: `pytest tests/ -v`
Expected: All PASS

- [ ] **Step 4: Lint and commit**

```bash
ruff check --fix share/noba-web/server/healing/agent_runtime.py share/noba-web/server/routers/agents.py
git add share/noba-web/server/healing/agent_runtime.py share/noba-web/server/routers/agents.py
git commit -m "feat(healing): add agent heal runtime with policy distribution"
```

---

## Task 13: Healing API router

**Files:**
- Create: `share/noba-web/server/routers/healing.py`
- Modify: `share/noba-web/server/routers/__init__.py`
- Create: `tests/test_router_healing.py`

- [ ] **Step 1: Implement healing router**

Create `share/noba-web/server/routers/healing.py`:
```python
"""Noba -- Healing pipeline API endpoints."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from ..deps import _get_auth, _require_admin, _require_operator, db

logger = logging.getLogger("noba")

router = APIRouter()


@router.get("/api/healing/ledger")
def api_healing_ledger(request: Request, auth=Depends(_get_auth)):
    limit = int(request.query_params.get("limit", 50))
    rule_id = request.query_params.get("rule_id")
    target = request.query_params.get("target")
    return db.get_heal_outcomes(limit=limit, rule_id=rule_id, target=target)


@router.get("/api/healing/effectiveness")
def api_healing_effectiveness(request: Request, auth=Depends(_get_auth)):
    action_type = request.query_params.get("action_type", "")
    condition = request.query_params.get("condition", "")
    target = request.query_params.get("target")
    if not action_type or not condition:
        raise HTTPException(400, "action_type and condition required")
    rate = db.get_heal_success_rate(action_type, condition, target=target)
    return {"action_type": action_type, "condition": condition, "success_rate": rate}


@router.get("/api/healing/suggestions")
def api_healing_suggestions(auth=Depends(_get_auth)):
    return db.list_heal_suggestions()


@router.post("/api/healing/suggestions/{suggestion_id}/dismiss")
def api_dismiss_suggestion(suggestion_id: int, auth=Depends(_require_operator)):
    db.dismiss_heal_suggestion(suggestion_id)
    return {"success": True}


@router.get("/api/healing/trust")
def api_healing_trust(auth=Depends(_get_auth)):
    return db.list_trust_states()


@router.post("/api/healing/trust/{rule_id}/promote")
async def api_promote_trust(rule_id: str, request: Request, auth=Depends(_require_admin)):
    from ..deps import _read_body
    body = await _read_body(request)
    target_level = body.get("level", "approve")
    if target_level not in ("approve", "execute"):
        raise HTTPException(400, "level must be 'approve' or 'execute'")
    state = db.get_trust_state(rule_id)
    if not state:
        raise HTTPException(404, f"No trust state for rule: {rule_id}")
    db.upsert_trust_state(rule_id, target_level, state["ceiling"])
    username, _ = auth
    db.audit_log("trust_promote", username, f"{rule_id}: {state['current_level']} -> {target_level}")
    return {"success": True, "rule_id": rule_id, "new_level": target_level}
```

- [ ] **Step 2: Register router**

In `share/noba-web/server/routers/__init__.py`, add the import and include the healing router following the existing pattern.

- [ ] **Step 3: Write basic API tests**

Create `tests/test_router_healing.py`:
```python
"""Tests for healing API router."""
from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestHealingRouter:
    def _client(self):
        # Use the same test client pattern as other router tests
        from fastapi.testclient import TestClient
        from server.app import app
        return TestClient(app)

    @patch("server.deps._get_auth", return_value=("admin", "admin"))
    def test_ledger_endpoint(self, mock_auth):
        client = self._client()
        resp = client.get("/api/healing/ledger")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @patch("server.deps._get_auth", return_value=("admin", "admin"))
    def test_trust_endpoint(self, mock_auth):
        client = self._client()
        resp = client.get("/api/healing/trust")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @patch("server.deps._get_auth", return_value=("admin", "admin"))
    def test_suggestions_endpoint(self, mock_auth):
        client = self._client()
        resp = client.get("/api/healing/suggestions")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_router_healing.py -v`
Expected: All PASS

- [ ] **Step 5: Run full test suite**

Run: `pytest tests/ -v`
Expected: All PASS

- [ ] **Step 6: Lint and commit**

```bash
ruff check --fix share/noba-web/server/routers/healing.py
git add share/noba-web/server/routers/healing.py share/noba-web/server/routers/__init__.py tests/test_router_healing.py
git commit -m "feat(healing): add healing API router with ledger, trust, suggestions endpoints"
```

---

## Task 14: Scheduler integration

**Files:**
- Modify: `share/noba-web/server/scheduler.py`

- [ ] **Step 1: Add hourly suggestion generation to scheduler**

In `share/noba-web/server/scheduler.py`, in the `Scheduler._tick` method, add at the end (after `_process_auto_approvals`):

```python
        # Hourly: generate heal suggestions and evaluate trust promotions
        if now.minute == 0:  # once per hour
            try:
                from .healing.ledger import generate_suggestions
                from .healing.governor import evaluate_promotions
                generate_suggestions(db)
                promotion_suggestions = evaluate_promotions(db)
                for s in promotion_suggestions:
                    db.insert_heal_suggestion(**s)
                if promotion_suggestions:
                    logger.info("Trust governor: %d promotion suggestion(s)", len(promotion_suggestions))
            except Exception as exc:
                logger.error("Heal suggestion generation failed: %s", exc)
```

- [ ] **Step 2: Run full test suite**

Run: `pytest tests/ -v`
Expected: All PASS

- [ ] **Step 3: Lint and commit**

```bash
ruff check --fix share/noba-web/server/scheduler.py
git add share/noba-web/server/scheduler.py
git commit -m "feat(healing): wire hourly suggestion generation into scheduler"
```

---

## Task 15: Final integration test and cleanup

**Files:**
- All healing files

- [ ] **Step 1: Run full test suite**

Run: `pytest tests/ -v`
Expected: All PASS

- [ ] **Step 2: Run ruff on all modified files**

```bash
ruff check --fix share/noba-web/server/healing/ share/noba-web/server/db/healing.py share/noba-web/server/routers/healing.py share/noba-web/server/alerts.py share/noba-web/server/remediation.py share/noba-web/server/workflow_engine.py share/noba-web/server/routers/stats.py share/noba-web/server/scheduler.py share/noba-web/server/routers/agents.py
```

- [ ] **Step 3: Verify no circular imports**

```bash
python -c "from server.healing import create_pipeline; print('Pipeline OK')"
python -c "from server.alerts import evaluate_alert_rules; print('Alerts OK')"
python -c "from server.workflow_engine import _run_workflow; print('Workflow OK')"
python -c "from server.routers.stats import router; print('Stats OK')"
```
Expected: All print OK with no ImportError

- [ ] **Step 4: Final commit if any fixes needed**

```bash
git add -u
git commit -m "chore: final lint and import fixes for healing pipeline"
```

- [ ] **Step 5: Update CHANGELOG.md**

Add entry under a new section for the healing pipeline feature.
