# Phase 5: Predictive Intelligence + Workflow Orchestration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enhance capacity planning with multi-metric regression, seasonal decomposition, and confidence intervals. Add a visual workflow builder with conditional branching and approval gates. Ship pre-built maintenance playbook templates.

**Architecture:** Backend: new `prediction.py` module replaces simple linear regression with multi-metric analysis + seasonal decomposition (pure Python, no numpy/scipy). Enhanced `health_score.py` with weighted per-service scoring. Workflow builder: new Vue component with canvas-based node editor, stored as JSON in existing automation config. Playbooks: seed data in DB + template API.

**Tech Stack:** Python stdlib (math, statistics), FastAPI, SQLite, Vue 3 canvas/SVG, existing Chart.js

**Spec:** `docs/superpowers/specs/2026-03-21-noba-v3-roadmap-design.md` (Phase 5 section, lines 274-312)

**No new Python dependencies** — all prediction math uses stdlib `math` and `statistics`. No numpy/scipy.

---

## Current State

| Feature | Current | Phase 5 Target |
|---------|---------|----------------|
| Capacity planning | Simple linear regression in `db/metrics.py:get_trend()` (50 lines) | Multi-metric regression, seasonal decomposition, confidence intervals |
| Health scoring | Category-based 0-100 score in `health_score.py` (280 lines) | Enhanced per-service weighted composite |
| Workflows | Sequential + parallel via `workflow_engine.py`, JSON step list | Visual drag-and-drop builder, conditional branching, approval gates |
| Playbooks | None | 4 pre-built templates, customizable |

## File Structure

```
share/noba-web/server/
  prediction.py                          # NEW: multi-metric prediction engine
  health_score.py                        # MODIFY: add per-service weighted scoring
  db/
    metrics.py                           # MODIFY: extend get_trend with confidence intervals
    automations.py                       # MODIFY: add playbook template CRUD
    core.py                              # MODIFY: add playbook_templates table + wrappers
  routers/
    intelligence.py                      # MODIFY: add prediction API endpoints
    automations.py                       # MODIFY: add playbook template endpoints
  workflow_engine.py                     # MODIFY: add conditional + approval gate node types

share/noba-web/frontend/src/
  components/
    automations/
      WorkflowBuilder.vue               # NEW: visual drag-and-drop workflow editor
      WorkflowNode.vue                  # NEW: individual node component
      PlaybookLibrary.vue               # NEW: playbook template picker
    cards/
      PredictionCard.vue                # NEW: capacity prediction dashboard card
  views/
    InfrastructureView.vue              # MODIFY: add prediction panel

tests/
  test_prediction.py                    # NEW: prediction engine tests
  test_playbooks.py                     # NEW: playbook template tests
  test_workflow_builder.py              # NEW: conditional/approval gate tests
```

---

### Task 1: Prediction Engine — Multi-Metric Regression

Create the core prediction module with multi-metric regression and confidence intervals.

**Files:**
- Create: `share/noba-web/server/prediction.py`
- Create: `tests/test_prediction.py`

- [ ] **Step 1: Create `prediction.py`**

The prediction engine computes capacity forecasts using multiple metrics. It uses pure Python (no numpy).

```python
"""Noba -- Predictive capacity planning engine.

Multi-metric regression with seasonal decomposition and confidence intervals.
Uses only Python stdlib (math, statistics). No numpy/scipy dependency.
"""
from __future__ import annotations

import math
import statistics
import time
from typing import Any

from .db import db


def predict_capacity(metric_keys: list[str], range_hours: int = 168,
                     projection_hours: int = 720) -> dict:
    """Multi-metric capacity prediction with confidence intervals.

    Combines multiple related metrics (e.g., disk_percent + inode_percent + io_rate)
    for more accurate predictions than single-metric linear regression.

    Returns:
        {
            "metrics": {key: {trend, projection, r_squared, slope}},
            "combined_prediction": {full_at, confidence_68, confidence_95},
            "seasonal_pattern": {period_hours, amplitude, phase},
            "confidence_intervals": [{time, lower_68, upper_68, lower_95, upper_95, predicted}],
        }
    """
    results = {}
    for key in metric_keys:
        points = db.get_history(key, range_hours=range_hours, resolution=300, raw=True)
        if len(points) < 10:
            results[key] = {"error": "Insufficient data"}
            continue
        xs = [p["time"] for p in points]
        ys = [p["value"] for p in points]
        reg = _linear_regression(xs, ys)
        detrended = _remove_trend(xs, ys, reg["slope"], reg["intercept"])
        seasonal = _detect_seasonality(xs, detrended)  # detect on detrended residuals
        residual_std = _residual_std(xs, ys, reg["slope"], reg["intercept"])
        projection = _project_with_confidence(
            xs, reg, seasonal, residual_std, projection_hours
        )
        results[key] = {
            "regression": reg,
            "seasonal": seasonal,
            "projection": projection,
            "residual_std": round(residual_std, 4),
        }

    # Combined prediction: use the metric with highest R² for full_at estimate
    combined = _combine_predictions(results, projection_hours)
    return {"metrics": results, "combined": combined}


def _linear_regression(xs: list, ys: list) -> dict:
    """Simple linear regression. Returns slope, intercept, r_squared."""
    n = len(xs)
    sum_x = sum(xs)
    sum_y = sum(ys)
    sum_xy = sum(x * y for x, y in zip(xs, ys))
    sum_x2 = sum(x * x for x in xs)
    denom = n * sum_x2 - sum_x ** 2
    if denom == 0:
        return {"slope": 0, "intercept": 0, "r_squared": 0}
    slope = (n * sum_xy - sum_x * sum_y) / denom
    intercept = (sum_y - slope * sum_x) / n
    y_mean = sum_y / n
    ss_tot = sum((y - y_mean) ** 2 for y in ys)
    ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(xs, ys))
    r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0
    return {"slope": round(slope, 10), "intercept": round(intercept, 4), "r_squared": round(r_squared, 4)}


def _detect_seasonality(xs: list, ys: list, max_period_hours: int = 168) -> dict | None:
    """Detect weekly/daily seasonal patterns via autocorrelation.

    Checks periods at 24h and 168h (weekly). Returns the strongest
    detected pattern or None if no significant seasonality.
    """
    if len(xs) < 48:  # Need at least 2 days of data
        return None

    # Compute mean and variance
    y_mean = statistics.mean(ys)
    y_var = statistics.variance(ys) if len(ys) > 1 else 0
    if y_var < 0.01:
        return None

    step = xs[1] - xs[0] if len(xs) > 1 else 300
    best_period = None
    best_corr = 0

    for period_hours in [24, 168]:
        lag = int(period_hours * 3600 / step)
        if lag >= len(ys) - 1:
            continue
        # Autocorrelation at this lag (standard formula: divide by total sum of squares)
        pairs = [(ys[i] - y_mean, ys[i + lag] - y_mean) for i in range(len(ys) - lag)]
        if not pairs:
            continue
        num = sum(a * b for a, b in pairs)
        ss_total = sum((y - y_mean) ** 2 for y in ys)
        if ss_total == 0:
            continue
        corr = num / ss_total
        if corr > best_corr and corr > 0.3:  # Threshold for significance
            best_corr = corr
            best_period = period_hours

    if best_period is None:
        return None

    # Estimate amplitude: half the range of the seasonal component
    lag = int(best_period * 3600 / step)
    chunk_size = min(lag, len(ys))
    chunks = [ys[i:i+chunk_size] for i in range(0, len(ys) - chunk_size + 1, chunk_size)]
    if chunks:
        avg_range = statistics.mean(max(c) - min(c) for c in chunks if c)
        amplitude = avg_range / 2
    else:
        amplitude = 0

    return {
        "period_hours": best_period,
        "correlation": round(best_corr, 4),
        "amplitude": round(amplitude, 2),
    }


def _remove_trend(xs, ys, slope, intercept):
    """Remove linear trend, return detrended residuals."""
    return [y - (slope * x + intercept) for x, y in zip(xs, ys)]


def _residual_std(xs, ys, slope, intercept):
    """Standard deviation of residuals from the regression line."""
    residuals = [y - (slope * x + intercept) for x, y in zip(xs, ys)]
    if len(residuals) < 2:
        return 0
    return statistics.stdev(residuals)


def _project_with_confidence(xs, regression, seasonal, residual_std,
                             projection_hours):
    """Generate projection points with 68% and 95% confidence intervals."""
    slope = regression["slope"]
    intercept = regression["intercept"]
    last_t = xs[-1]
    step = 3600  # 1-hour steps for projection
    n_points = int(projection_hours)

    # Compute proper prediction interval parameters
    n = len(xs)
    x_mean = sum(xs) / n if n else 0
    s_xx = sum((x - x_mean) ** 2 for x in xs) if n else 1

    # Seasonal adjustment parameters
    has_season = seasonal is not None
    period_s = seasonal["period_hours"] * 3600 if has_season else 0
    amplitude = seasonal["amplitude"] if has_season else 0

    points = []
    for i in range(1, n_points + 1):
        t = last_t + i * step
        trend_val = slope * t + intercept

        # Add seasonal component (sinusoidal approximation)
        seasonal_adj = 0
        if has_season and period_s > 0:
            seasonal_adj = amplitude * math.sin(2 * math.pi * t / period_s)

        predicted = trend_val + seasonal_adj

        # Proper prediction interval: SE = s * sqrt(1 + 1/n + (x-x_mean)^2/S_xx)
        x_dev = (t - x_mean) ** 2 / s_xx if s_xx > 0 else 0
        se = residual_std * math.sqrt(1 + 1/max(n, 1) + x_dev)

        points.append({
            "time": t,
            "predicted": round(predicted, 2),
            "lower_68": round(predicted - se, 2),
            "upper_68": round(predicted + se, 2),
            "lower_95": round(predicted - 1.96 * se, 2),
            "upper_95": round(predicted + 1.96 * se, 2),
        })

    return points


def _combine_predictions(results: dict, projection_hours: int) -> dict:
    """Combine multiple metric predictions into a single forecast."""
    best_key = None
    best_r2 = -1
    for key, data in results.items():
        if "error" in data:
            continue
        r2 = data["regression"]["r_squared"]
        if r2 > best_r2:
            best_r2 = r2
            best_key = key

    if best_key is None:
        return {"full_at": None, "primary_metric": None, "confidence": "low"}

    reg = results[best_key]["regression"]
    slope = reg["slope"]
    intercept = reg["intercept"]

    full_at = None
    if slope > 0:
        t_full = (100 - intercept) / slope
        now = time.time()
        if t_full > now:
            from datetime import datetime, timezone
            full_at = datetime.fromtimestamp(t_full, tz=timezone.utc).isoformat()

    confidence = "high" if best_r2 > 0.8 else "medium" if best_r2 > 0.5 else "low"

    return {
        "full_at": full_at,
        "primary_metric": best_key,
        "r_squared": best_r2,
        "confidence": confidence,
        "slope_per_day": round(slope * 86400, 4) if slope else 0,
    }
```

- [ ] **Step 2: Write tests**

Create `tests/test_prediction.py`:
- `_linear_regression`: known slope/intercept, perfect fit (R²=1), flat data (slope=0)
- `_detect_seasonality`: sinusoidal data with 24h period, flat data (no season)
- `_residual_std`: known residuals
- `_project_with_confidence`: verify intervals widen over time, 95% wider than 68%
- `_combine_predictions`: picks highest R², handles all-error case
- `predict_capacity`: integration test with mocked `db.get_history`

- [ ] **Step 3: Run tests**

```bash
ruff check share/noba-web/server/prediction.py
pytest tests/test_prediction.py -v --tb=short
```

- [ ] **Step 4: Commit**

```bash
git add share/noba-web/server/prediction.py tests/test_prediction.py
git commit -m "feat(v3): add multi-metric prediction engine with confidence intervals"
```

---

### Task 2: Prediction API Endpoints

Expose the prediction engine via REST endpoints and update the disk prediction route.

**Files:**
- Modify: `share/noba-web/server/routers/intelligence.py`
- Modify: `share/noba-web/server/routers/infrastructure.py`

- [ ] **Step 1: Add prediction endpoints to intelligence router**

Read `share/noba-web/server/routers/intelligence.py`. Add:

```python
@router.get("/api/predict/capacity")
def api_predict_capacity(request: Request, auth=Depends(_get_auth)):
    """Multi-metric capacity prediction."""
    from ..prediction import predict_capacity
    metrics = request.query_params.get("metrics", "disk_percent").split(",")
    range_h = min(int(request.query_params.get("range", "168")), 720)
    proj_h = min(int(request.query_params.get("projection", "720")), 2160)
    return predict_capacity(metrics, range_hours=range_h, projection_hours=proj_h)


@router.get("/api/predict/health")
def api_predict_health(auth=Depends(_get_auth)):
    """Per-service health scoring with weighted composite."""
    from ..health_score import compute_service_health_scores
    return compute_service_health_scores(db)
```

- [ ] **Step 2: Enhance the disk prediction endpoint**

In `share/noba-web/server/routers/infrastructure.py`, update `api_disk_prediction` to use the new prediction engine alongside the existing `get_trend`:

```python
@router.get("/api/disks/prediction")
def api_disk_prediction(request: Request, auth=Depends(_get_auth)):
    """Disk capacity prediction with confidence intervals."""
    from ..prediction import predict_capacity
    try:
        result = predict_capacity(
            ["disk_percent"],
            range_hours=168,
            projection_hours=720,
        )
        # Also include per-mount predictions from agent data
        # ... keep existing bg_collector logic as fallback
        return result
    except Exception:
        # Fallback to simple trend, normalized to match predict_capacity shape
        trend = db.get_trend("disk_percent", range_hours=168, projection_hours=720)
        return {
            "metrics": {"disk_percent": {"regression": {"slope": trend.get("slope", 0), "r_squared": trend.get("r_squared", 0)}, "projection": trend.get("projection", [])}},
            "combined": {"full_at": trend.get("full_at"), "confidence": "low", "primary_metric": "disk_percent"},
        }
```

- [ ] **Step 3: Write API tests**

Test:
- GET /api/predict/capacity — auth, returns structure with metrics + combined
- GET /api/predict/capacity?metrics=cpu_percent,mem_percent — multi-metric
- GET /api/predict/health — auth, returns scores
- GET /api/disks/prediction — still works (backward compat)

- [ ] **Step 4: Run tests + commit**

```bash
pytest tests/ --tb=short 2>&1 | tail -5
git add share/noba-web/server/routers/ tests/
git commit -m "feat(v3): add prediction API endpoints with multi-metric support"
```

---

### Task 3: Enhanced Per-Service Health Scoring

Add weighted per-service health scoring to the health score module. Requires a new `endpoint_check_history` table since the current `endpoint_monitors` table only stores the last check result.

**Files:**
- Modify: `share/noba-web/server/db/core.py` (add endpoint_check_history table)
- Modify: `share/noba-web/server/db/endpoints.py` or `db/metrics.py` (add record + query functions)
- Modify: `share/noba-web/server/scheduler.py` (write check history on each endpoint check)
- Modify: `share/noba-web/server/health_score.py`

- [ ] **Step 0: Add `endpoint_check_history` table**

In `db/core.py` executescript block:

```sql
CREATE TABLE IF NOT EXISTS endpoint_check_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    monitor_id  INTEGER NOT NULL,
    timestamp   INTEGER NOT NULL,
    status      TEXT NOT NULL,
    response_ms INTEGER,
    error       TEXT
);
CREATE INDEX IF NOT EXISTS idx_ech_monitor_ts ON endpoint_check_history(monitor_id, timestamp);
```

Add CRUD functions following `(conn, lock)` pattern:
- `_record_endpoint_check(conn, lock, monitor_id, status, response_ms, error=None)` — INSERT
- `_get_endpoint_check_history(conn, lock, monitor_id, hours=720)` — SELECT for uptime/latency calculation
- `_prune_endpoint_check_history(conn, lock, days=90)` — DELETE old records

Modify the scheduler's `EndpointChecker._tick()` to call `db.record_endpoint_check()` after each check.

Add `import statistics` to `health_score.py` imports.

- [ ] **Step 1: Add `compute_service_health_scores`**

Read `share/noba-web/server/health_score.py`. Add a new function that computes per-service health with the weighted formula from the spec:

```python
def compute_service_health_scores(db) -> dict:
    """Per-service health scoring with weighted composite.

    Weights: uptime (40%) + latency trend (25%) + error rate (20%) + resource headroom (15%)
    """
    monitors = db.get_endpoint_monitors(enabled_only=True)
    services = []
    for m in monitors:
        uptime_score = _calc_uptime_score(db, m)         # 0-100
        latency_score = _calc_latency_score(db, m)       # 0-100
        error_score = _calc_error_rate_score(db, m)      # 0-100
        headroom_score = _calc_headroom_score(db, m)     # 0-100

        composite = (
            uptime_score * 0.40 +
            latency_score * 0.25 +
            error_score * 0.20 +
            headroom_score * 0.15
        )

        services.append({
            "name": m["name"],
            "url": m.get("url", ""),
            "composite_score": round(composite, 1),
            "breakdown": {
                "uptime": round(uptime_score, 1),
                "latency": round(latency_score, 1),
                "error_rate": round(error_score, 1),
                "headroom": round(headroom_score, 1),
            },
            "grade": _score_to_grade(composite),
        })

    services.sort(key=lambda s: s["composite_score"])
    overall = round(statistics.mean(s["composite_score"] for s in services), 1) if services else 100
    return {
        "overall": overall,
        "grade": _score_to_grade(overall),
        "services": services,
    }
```

Helper functions:
- `_calc_uptime_score(db, monitor)` — Percentage of successful checks in last 30 days
- `_calc_latency_score(db, monitor)` — Inverse of latency trend (lower latency = higher score)
- `_calc_error_rate_score(db, monitor)` — Inverse of error rate
- `_calc_headroom_score(db, monitor)` — Based on response time headroom vs timeout
- `_score_to_grade(score)` — A/B/C/D/F grading

- [ ] **Step 2: Write tests**

Test each scoring function + the composite. Mock DB to return known monitor data.

- [ ] **Step 3: Run tests + commit**

```bash
pytest tests/ --tb=short 2>&1 | tail -5
git add share/noba-web/server/health_score.py tests/
git commit -m "feat(v3): add per-service weighted health scoring"
```

---

### Task 4: Workflow Engine — Conditional Branching + Approval Gates

Extend the workflow engine with new node types: condition (branching), approval gate, and parallel split with join.

**Files:**
- Modify: `share/noba-web/server/workflow_engine.py`
- Modify: `share/noba-web/server/db/automations.py`
- Create: `tests/test_workflow_builder.py`

- [ ] **Step 1: Define the enhanced workflow schema**

Currently, workflows are a flat list of step IDs (automation IDs). Enhance to support a node graph:

```python
# Enhanced workflow config schema:
{
    "nodes": [
        {"id": "n1", "type": "action", "automation_id": "abc123"},
        {"id": "n2", "type": "condition", "expression": "disk_percent > 90",
         "true_next": "n3", "false_next": "n4"},
        {"id": "n3", "type": "action", "automation_id": "cleanup_script"},
        {"id": "n4", "type": "notification", "message": "Disk OK, no action needed"},
        {"id": "n5", "type": "approval_gate", "timeout_minutes": 15,
         "approved_next": "n6", "denied_next": "n7"},
        {"id": "n6", "type": "action", "automation_id": "deploy_fix"},
        {"id": "n7", "type": "notification", "message": "Action denied by operator"},
        {"id": "n8", "type": "parallel", "branches": [["n9", "n10"], ["n11"]], "join": "n12"},
        {"id": "n9", "type": "delay", "seconds": 30},
    ],
    "entry": "n1",
    "edges": [
        {"from": "n1", "to": "n2"},
        // ... explicit edges for non-conditional flows
    ]
}
```

- [ ] **Step 2: Add `_run_graph_workflow` function**

A new execution function that traverses the node graph:

```python
def _run_graph_workflow(auto_id, config, triggered_by):
    """Execute a graph-based workflow with branching and approval gates."""
    nodes = {n["id"]: n for n in config.get("nodes", [])}
    edges = config.get("edges", [])
    entry = config.get("entry", "")

    if not entry or entry not in nodes:
        logger.error("Workflow %s has no valid entry node", auto_id)
        return

    _execute_node(auto_id, nodes, edges, entry, triggered_by)
```

For each node type:
- **action**: Run the referenced automation (existing behavior)
- **condition**: Evaluate expression against current metrics, follow true_next or false_next
- **approval_gate**: Insert into approval_queue, pause workflow until approved/denied/timeout
- **parallel**: Fan out to branches, wait for all to complete (join point)
- **delay**: Sleep for N seconds
- **notification**: Dispatch notification, continue

**Edge traversal logic:** Condition and approval nodes use their inline `true_next`/`false_next` (or `approved_next`/`denied_next`) fields. All other node types (action, delay, notification) look up the `edges` array for `{"from": current_id}` to find the next node. Add a helper `_get_next_node(node, edges, branch=None)` that encapsulates this logic.

For backward compatibility, if the config has `"steps"` (old format) instead of `"nodes"`, use the existing `_run_workflow()`.

- [ ] **Step 3: Add approval gate support**

When a workflow hits an approval gate:
1. Insert approval into DB with `trigger_type="workflow_gate"`
2. Store the workflow state (current node, remaining graph) so it can resume
3. When approved, continue from `approved_next`
4. When denied, continue from `denied_next`
5. On timeout, auto-approve or deny based on gate config

Store workflow state in a `workflow_context` TEXT column on the `approval_queue` table (added as part of this task):

```sql
ALTER TABLE approval_queue ADD COLUMN workflow_context TEXT;
```

Or if creating fresh (Phase 4 table already exists), add the column via a migration check in `_init_schema`.

The `workflow_context` stores JSON: `{"auto_id": "...", "config": {...}, "approved_next": "n6", "denied_next": "n7", "triggered_by": "..."}`.

**Resume flow:** When `api_decide_approval()` is called and the approval has `workflow_context`:
1. Deserialize the context
2. Determine next node based on decision (`approved_next` or `denied_next`)
3. Call `_execute_node(auto_id, nodes, edges, next_node_id, triggered_by)`

Add to `db/automations.py` (following `(conn, lock)` pattern):
```python
def _save_workflow_context(conn, lock, approval_id, context_json):
    """Store workflow graph state on an approval record for later resumption."""
    # UPDATE approval_queue SET workflow_context = ? WHERE id = ?

def _get_workflow_context(conn, lock, approval_id):
    """Retrieve workflow context for resuming after approval decision."""
    # SELECT workflow_context FROM approval_queue WHERE id = ?
```

Modify `api_decide_approval()` in `routers/automations.py`: after deciding, check if `workflow_context` exists. If so, resume the workflow instead of calling `remediation.execute_action()`.

- [ ] **Step 4: Write tests**

Create `tests/test_workflow_builder.py`:
- Graph workflow with linear path (action → action → action)
- Conditional branching (true path vs false path)
- Approval gate (mock approval, verify pause + resume)
- Parallel branches (verify all execute)
- Backward compat: old "steps" format still works
- Invalid graph (missing entry, broken edge) returns error

- [ ] **Step 5: Run tests + commit**

```bash
pytest tests/test_workflow_builder.py -v --tb=short
pytest tests/ --tb=short 2>&1 | tail -5
git add share/noba-web/server/ tests/
git commit -m "feat(v3): add conditional branching and approval gates to workflow engine"
```

---

### Task 5: Maintenance Playbook Templates

Create pre-built playbook templates that users can install as workflows.

**Files:**
- Modify: `share/noba-web/server/db/core.py`
- Modify: `share/noba-web/server/db/automations.py`
- Modify: `share/noba-web/server/routers/automations.py`
- Create: `tests/test_playbooks.py`

- [ ] **Step 1: Add playbook templates table**

In `db/core.py` executescript block:

```sql
CREATE TABLE IF NOT EXISTS playbook_templates (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT,
    category    TEXT,
    config      TEXT NOT NULL,
    version     INTEGER NOT NULL DEFAULT 1
);
```

- [ ] **Step 2: Seed default playbooks**

In `db/automations.py`, add a `_seed_playbook_templates` function called from schema init:

```python
_DEFAULT_PLAYBOOKS = [
    {
        "id": "playbook-update-agents",
        "name": "Update All Agents",
        "description": "Queue update → rolling restart → verify versions → report",
        "category": "maintenance",
        "config": {
            "nodes": [
                {"id": "n1", "type": "action", "label": "Queue agent updates",
                 "config": {"type": "agent_command", "config": {"hostname": "__all__", "command": "check_updates"}}},
                {"id": "n2", "type": "delay", "label": "Wait for updates", "seconds": 60},
                {"id": "n3", "type": "action", "label": "Verify agent versions",
                 "config": {"type": "agent_command", "config": {"hostname": "__all__", "command": "check_updates"}}},
                {"id": "n4", "type": "notification", "label": "Report results",
                 "message": "Agent update complete"},
            ],
            "entry": "n1",
            "edges": [{"from": "n1", "to": "n2"}, {"from": "n2", "to": "n3"}, {"from": "n3", "to": "n4"}],
        },
    },
    {
        "id": "playbook-rolling-dns",
        "name": "Rolling DNS Restart",
        "description": "Restart primary → verify resolution → restart secondary → verify",
        "category": "maintenance",
        "config": {
            "nodes": [
                {"id": "n1", "type": "action", "label": "Restart primary DNS",
                 "config": {"type": "remediation", "config": {"remediation_type": "restart_service", "params": {"service": "pihole-FTL"}}}},
                {"id": "n2", "type": "delay", "label": "Wait for DNS propagation", "seconds": 30},
                {"id": "n3", "type": "condition", "label": "Verify DNS resolution",
                 "expression": "dns_ok", "true_next": "n4", "false_next": "n5"},
                {"id": "n4", "type": "notification", "label": "DNS OK", "message": "Primary DNS restarted successfully"},
                {"id": "n5", "type": "notification", "label": "DNS Failed", "message": "DNS verification failed after restart", "level": "danger"},
            ],
            "entry": "n1",
            "edges": [{"from": "n1", "to": "n2"}, {"from": "n2", "to": "n3"}],
        },
    },
    {
        "id": "playbook-backup-verify",
        "name": "Backup Verification",
        "description": "Trigger backup → wait → verify checksum → verify restore test → report",
        "category": "backup",
        "config": {
            "nodes": [
                {"id": "n1", "type": "action", "label": "Trigger backup",
                 "config": {"type": "remediation", "config": {"remediation_type": "trigger_backup", "params": {"source": "default"}}}},
                {"id": "n2", "type": "delay", "label": "Wait for backup", "seconds": 300},
                {"id": "n3", "type": "notification", "label": "Report results", "message": "Backup verification complete"},
            ],
            "entry": "n1",
            "edges": [{"from": "n1", "to": "n2"}, {"from": "n2", "to": "n3"}],
        },
    },
    {
        "id": "playbook-disk-cleanup",
        "name": "Disk Cleanup",
        "description": "Check thresholds → identify large files → notify for approval → delete → verify space",
        "category": "maintenance",
        "config": {
            "nodes": [
                {"id": "n1", "type": "condition", "label": "Check disk threshold",
                 "expression": "disk_percent > 85", "true_next": "n2", "false_next": "n5"},
                {"id": "n2", "type": "action", "label": "Find large/old files",
                 "config": {"type": "agent_command", "config": {"command": "disk_usage"}}},
                {"id": "n3", "type": "approval_gate", "label": "Approve cleanup",
                 "timeout_minutes": 30, "approved_next": "n4", "denied_next": "n6"},
                {"id": "n4", "type": "action", "label": "Execute cleanup",
                 "config": {"type": "remediation", "config": {"remediation_type": "clear_cache", "params": {"target": "system"}}}},
                {"id": "n5", "type": "notification", "label": "Cleanup complete", "message": "Disk cleanup executed, verifying space"},
                {"id": "n6", "type": "notification", "label": "No action needed", "message": "Disk usage within acceptable limits or cleanup denied"},
            ],
            "entry": "n1",
            "edges": [{"from": "n2", "to": "n3"}, {"from": "n4", "to": "n5"}],
        },
    },
]
```

- [ ] **Step 3: Add playbook API endpoints**

```python
@router.get("/api/playbooks")
def api_list_playbooks(auth=Depends(_get_auth)):
    """List available playbook templates."""
    return db.list_playbook_templates()

@router.post("/api/playbooks/{playbook_id}/install")
async def api_install_playbook(playbook_id: str, request: Request, auth=Depends(_require_operator)):
    """Install a playbook template as a new automation."""
    username, _ = auth
    template = db.get_playbook_template(playbook_id)
    if not template:
        raise HTTPException(404, "Playbook not found")
    body = await _read_body(request)
    name = body.get("name", template["name"])
    # Create automation from template
    import secrets
    auto_id = secrets.token_hex(6)
    db.insert_automation(auto_id, name, "workflow", template["config"], enabled=False)
    db.audit_log("playbook_install", username, f"template={playbook_id} auto={auto_id}", _client_ip(request))
    return {"id": auto_id, "status": "ok"}
```

- [ ] **Step 4: Write tests + commit**

```bash
pytest tests/test_playbooks.py -v --tb=short
git add share/noba-web/server/ tests/
git commit -m "feat(v3): add maintenance playbook templates (4 pre-built)"
```

---

### Task 6: Vue — Prediction Dashboard Card

Add a capacity prediction card to the dashboard and prediction panel to Infrastructure.

**Files:**
- Create: `share/noba-web/frontend/src/components/cards/PredictionCard.vue`
- Modify: `share/noba-web/frontend/src/views/DashboardView.vue`
- Modify: `share/noba-web/frontend/src/views/InfrastructureView.vue`

- [ ] **Step 1: Create PredictionCard.vue**

Dashboard card showing:
- Disk capacity forecast with "full at" date
- Confidence level badge (high/medium/low)
- Mini chart with prediction line + confidence bands (68% shaded, 95% dashed)
- Slope indicator (GB/day or %/day)
- Uses ChartWrapper with line chart + fill between bands

Fetches `GET /api/predict/capacity?metrics=disk_percent` on mount and every 5 minutes.

- [ ] **Step 2: Add to DashboardView**

Import and render PredictionCard in the grid with `v-if="showCard('prediction')"`.

- [ ] **Step 3: Add prediction panel to InfrastructureView**

In the Infrastructure page, enhance the existing section or add a new tab "Predictions":
- Multi-metric selector (checkboxes for disk_percent, cpu_percent, mem_percent, inode_percent)
- Time range selector (7d, 30d, 90d)
- Projection range (30d, 90d, 180d)
- Full-size chart with confidence bands
- Per-service health score table from `GET /api/predict/health`

- [ ] **Step 4: Build and verify**

```bash
cd share/noba-web/frontend && npm run build && npm test
```

- [ ] **Step 5: Commit**

```bash
git add share/noba-web/frontend/src/
git commit -m "feat(v3): add prediction dashboard card and infrastructure prediction panel"
```

---

### Task 7: Vue — Visual Workflow Builder

Build the visual workflow editor. This is the most complex frontend component. **V1 scope:** Node rendering + edge rendering + basic interaction. Drag-to-reposition and connect-by-clicking (not drag-from-port). Canvas panning deferred.

**Files:**
- Create: `share/noba-web/frontend/src/components/automations/WorkflowBuilder.vue`
- Create: `share/noba-web/frontend/src/components/automations/WorkflowNode.vue`
- Modify: `share/noba-web/frontend/src/components/automations/AutomationFormModal.vue`

- [ ] **Step 1: Create WorkflowNode.vue**

Individual node component rendered on the builder canvas:

```vue
<script setup>
defineProps({
  node: Object,  // {id, type, label, x, y, ...}
  selected: Boolean,
})
defineEmits(['select', 'drag', 'connect', 'delete'])
</script>
```

Node types with distinct visual styles:
- **action** — Blue rounded rect with automation name
- **condition** — Diamond shape with expression text
- **approval_gate** — Orange rect with lock icon
- **parallel** — Purple rect with parallel-lines icon
- **delay** — Gray rect with clock icon
- **notification** — Green rect with bell icon

Each node has:
- Drag handle (move on canvas)
- Input port (top) — connection target
- Output port(s) (bottom) — connection source. Condition has two (true/false). Approval has two (approved/denied). Others have one.
- Delete button (x)

- [ ] **Step 2: Create WorkflowBuilder.vue**

The main workflow editor canvas:

```vue
<script setup>
import { ref, reactive, computed } from 'vue'
import WorkflowNode from './WorkflowNode.vue'

const props = defineProps({
  modelValue: Object,  // workflow config {nodes, edges, entry}
})
const emit = defineEmits(['update:modelValue'])
```

Features:
- SVG canvas for edges (lines connecting nodes)
- WorkflowNode components positioned absolutely on the canvas
- **Add node**: toolbar/palette at top with node type buttons
- **Drag to reposition**: mousedown on node → track mousemove → update x,y
- **Connect nodes**: drag from output port to input port creates an edge
- **Delete node**: remove node + connected edges
- **Delete edge**: click edge to select, press delete
- **Pan/zoom**: optional, nice to have (can omit for v1)
- **Entry node**: first node added becomes entry, highlighted with star icon
- **Validation**: check graph connectivity, no orphans
- **Import/Export**: JSON serialization matches the backend schema

The canvas renders:
1. SVG layer for edges (curved bezier paths between port positions)
2. HTML layer for nodes (absolute positioned WorkflowNode components)

Keep the implementation practical — SVG edges + absolutely positioned div nodes is the simplest approach. No need for a canvas library.

- [ ] **Step 3: Integrate into AutomationFormModal**

When the automation type is "workflow", show the WorkflowBuilder instead of the raw JSON step editor. The WorkflowBuilder's v-model binds to the automation config.

Keep the raw JSON editor as a "Code" tab for advanced users.

- [ ] **Step 4: Build and verify**

```bash
cd share/noba-web/frontend && npm run build
```

- [ ] **Step 5: Commit**

```bash
git add share/noba-web/frontend/src/
git commit -m "feat(v3): add visual workflow builder with drag-and-drop nodes"
```

---

### Task 8: Vue — Playbook Library

Build the playbook template picker.

**Files:**
- Create: `share/noba-web/frontend/src/components/automations/PlaybookLibrary.vue`
- Modify: `share/noba-web/frontend/src/views/AutomationsView.vue`

- [ ] **Step 1: Create PlaybookLibrary.vue**

A grid of playbook template cards:
- Each card shows: name, description, category badge, step count
- "Install" button opens a modal to name the automation and install it
- Uses `GET /api/playbooks` for template list
- Install calls `POST /api/playbooks/{id}/install` with custom name
- After install, navigates to the automation editor

- [ ] **Step 2: Add "Playbooks" tab to AutomationsView**

Add a 5th tab (after Audit Trail): "Playbooks" with the library grid.

- [ ] **Step 3: Build and verify**

```bash
cd share/noba-web/frontend && npm run build && npm test
```

- [ ] **Step 4: Commit**

```bash
git add share/noba-web/frontend/src/
git commit -m "feat(v3): add playbook template library with install flow"
```

---

### Task 9: Final Verification + CHANGELOG

Run all tests, rebuild frontend, update CHANGELOG.

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Run ruff**

```bash
ruff check share/noba-web/server/
```

- [ ] **Step 2: Run full backend test suite**

```bash
cd /home/raizen/noba && pytest tests/ -v --tb=short 2>&1 | tail -15
```

- [ ] **Step 3: Run frontend tests**

```bash
cd share/noba-web/frontend && npm test
```

- [ ] **Step 4: Rebuild frontend**

```bash
cd share/noba-web/frontend && npm run build
```

- [ ] **Step 5: Update CHANGELOG.md**

Add under `[Unreleased]` `### Changed`:

```markdown
- **Predictive intelligence + workflow orchestration (v3 Phase 5)** — Multi-metric capacity prediction with seasonal decomposition and 68%/95% confidence intervals. Per-service weighted health scoring (uptime 40%, latency 25%, error rate 20%, headroom 15%). Visual workflow builder with conditional branching, approval gates, parallel execution, and delay nodes. 4 pre-built maintenance playbook templates (agent update, DNS restart, backup verify, disk cleanup).
```

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(v3): Phase 5 complete — predictive intelligence + workflow orchestration

Added:
- Multi-metric prediction engine with confidence intervals
- Seasonal decomposition for workload patterns
- Per-service weighted health scoring
- Visual workflow builder (drag-and-drop, conditional, approval gates)
- 4 pre-built maintenance playbook templates
- Prediction dashboard card + infrastructure prediction panel
- Playbook library UI"
```

---

## Verification Checklist

- [ ] All backend tests pass (1629+ existing + new)
- [ ] All frontend tests pass
- [ ] `ruff check` clean
- [ ] `npm run build` clean
- [ ] Prediction API returns data with confidence intervals
- [ ] Health score includes per-service breakdown
- [ ] Workflow builder renders nodes and edges
- [ ] Conditional branching follows correct path
- [ ] Approval gates pause workflow execution
- [ ] 4 playbook templates available via API
- [ ] Playbooks installable as automations
- [ ] CHANGELOG updated
