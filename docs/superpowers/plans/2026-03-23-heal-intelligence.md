# Self-Healing Intelligence Implementation Plan (Phase 2 of 6)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add dependency graph with root cause analysis, site isolation, agent-verified healing, and co-failure auto-discovery to the healing pipeline. When multiple things fail, NOBA identifies the root cause, heals upward, and suppresses downstream noise.

**Architecture:** New `server/healing/dependency_graph.py` module builds an in-memory DAG from YAML config + DB. Integrated into `HealPipeline.handle_heal_event()` between correlation and planning. A new `connectivity_monitor.py` tracks site reachability state. Agent verification uses existing `agent_command` infrastructure. Auto-discovery runs hourly alongside suggestion generation.

**Tech Stack:** Python 3.11+, SQLite WAL, threading, dataclasses, pytest

**Spec:** `docs/superpowers/specs/2026-03-22-full-self-healing-design.md` (Section 4)

**Predecessor:** Phase 1 (`feature/heal-foundation`) — capability manifest, expanded actions, integration registry

---

## File Map

### New files
| File | Responsibility |
|------|---------------|
| `server/healing/dependency_graph.py` | DAG model, YAML loader, root cause resolution, graph queries |
| `server/healing/connectivity_monitor.py` | Site reachability tracking, connectivity-suspect state |
| `server/healing/agent_verify.py` | Ask agent to verify target state before healing |
| `server/healing/auto_discovery.py` | Co-failure pattern detection, dependency suggestions |
| `tests/test_dependency_graph.py` | Tests for DAG operations and root cause algorithm |
| `tests/test_connectivity_monitor.py` | Tests for site isolation logic |
| `tests/test_agent_verify.py` | Tests for agent verification flow |
| `tests/test_auto_discovery.py` | Tests for co-failure detection |

### Modified files
| File | Change |
|------|--------|
| `server/healing/__init__.py` | Integrate dependency check into `handle_heal_event()` |
| `server/db/core.py` | Add `dependency_graph` table |
| `server/db/integrations.py` | Add dependency graph DB functions |
| `server/routers/healing.py` | Add `/api/healing/dependencies` endpoint |
| `server/scheduler.py` | Add hourly auto-discovery run |
| `server/yaml_config.py` | Parse `dependencies` section from settings |

---

## Task 1: Dependency Graph Model

**Files:**
- Create: `share/noba-web/server/healing/dependency_graph.py`
- Create: `tests/test_dependency_graph.py`

- [ ] **Step 1: Write failing tests for dependency graph**

Create `tests/test_dependency_graph.py`:
```python
"""Tests for healing.dependency_graph: DAG model and root cause resolution."""
from __future__ import annotations


def _sample_graph():
    """Build a sample dependency graph for testing."""
    from server.healing.dependency_graph import DependencyGraph
    g = DependencyGraph()
    # External boundaries
    g.add_node("isp:site-a", node_type="external", site="site-a",
               health_check="ping 1.1.1.1")
    g.add_node("power:site-a", node_type="external", site="site-a",
               health_check="agent_reachable")
    # Infrastructure
    g.add_node("network:site-a", node_type="infrastructure", site="site-a",
               depends_on=["isp:site-a", "power:site-a"])
    # Services
    g.add_node("truenas", node_type="service", site="site-a",
               depends_on=["network:site-a"])
    g.add_node("plex", node_type="service", site="site-a",
               depends_on=["truenas", "network:site-a"])
    g.add_node("jellyfin", node_type="service", site="site-a",
               depends_on=["truenas"])
    # Independent service (no deps)
    g.add_node("pihole", node_type="service", site="site-a")
    return g


class TestDependencyGraph:
    def test_add_and_get_node(self):
        from server.healing.dependency_graph import DependencyGraph
        g = DependencyGraph()
        g.add_node("truenas", node_type="service", site="site-a")
        node = g.get_node("truenas")
        assert node is not None
        assert node.node_type == "service"
        assert node.site == "site-a"

    def test_get_nonexistent_returns_none(self):
        from server.healing.dependency_graph import DependencyGraph
        g = DependencyGraph()
        assert g.get_node("nope") is None

    def test_get_dependents(self):
        g = _sample_graph()
        # truenas depends_on network:site-a, so plex and jellyfin depend on truenas
        dependents = g.get_dependents("truenas")
        names = {d.target for d in dependents}
        assert "plex" in names
        assert "jellyfin" in names
        assert "pihole" not in names

    def test_get_ancestors(self):
        g = _sample_graph()
        ancestors = g.get_ancestors("plex")
        names = {a.target for a in ancestors}
        assert "truenas" in names
        assert "network:site-a" in names
        assert "isp:site-a" in names

    def test_get_site_targets(self):
        g = _sample_graph()
        targets = g.get_site_targets("site-a")
        names = {t.target for t in targets}
        assert "plex" in names
        assert "truenas" in names

    def test_node_count(self):
        g = _sample_graph()
        assert len(g.all_nodes()) == 7

    def test_load_from_yaml_config(self):
        from server.healing.dependency_graph import DependencyGraph
        config = [
            {"target": "isp:site-a", "type": "external", "site": "site-a"},
            {"target": "truenas", "type": "service", "depends_on": ["isp:site-a"]},
        ]
        g = DependencyGraph.from_config(config)
        assert g.get_node("isp:site-a") is not None
        assert g.get_node("truenas") is not None
        ancestors = g.get_ancestors("truenas")
        assert any(a.target == "isp:site-a" for a in ancestors)


class TestRootCauseResolution:
    def test_single_failure_is_its_own_root(self):
        from server.healing.dependency_graph import resolve_root_cause
        g = _sample_graph()
        root, suppressed = resolve_root_cause(g, failing_targets={"plex"})
        assert root == "plex"
        assert len(suppressed) == 0

    def test_nas_down_is_root_for_plex_and_jellyfin(self):
        from server.healing.dependency_graph import resolve_root_cause
        g = _sample_graph()
        root, suppressed = resolve_root_cause(
            g, failing_targets={"truenas", "plex", "jellyfin"},
        )
        assert root == "truenas"
        assert "plex" in suppressed
        assert "jellyfin" in suppressed

    def test_external_root_suppresses_everything(self):
        from server.healing.dependency_graph import resolve_root_cause
        g = _sample_graph()
        root, suppressed = resolve_root_cause(
            g, failing_targets={"isp:site-a", "network:site-a", "truenas", "plex"},
        )
        assert root == "isp:site-a"
        assert "plex" in suppressed
        assert "truenas" in suppressed

    def test_independent_failure_not_suppressed(self):
        from server.healing.dependency_graph import resolve_root_cause
        g = _sample_graph()
        root, suppressed = resolve_root_cause(
            g, failing_targets={"truenas", "pihole"},
        )
        # pihole has no deps on truenas, should not be suppressed
        assert "pihole" not in suppressed

    def test_no_failures_returns_none(self):
        from server.healing.dependency_graph import resolve_root_cause
        g = _sample_graph()
        root, suppressed = resolve_root_cause(g, failing_targets=set())
        assert root is None
        assert len(suppressed) == 0

    def test_external_root_flagged_as_unhealable(self):
        from server.healing.dependency_graph import resolve_root_cause
        g = _sample_graph()
        root, suppressed = resolve_root_cause(
            g, failing_targets={"isp:site-a", "truenas", "plex"},
        )
        node = g.get_node(root)
        assert node.node_type == "external"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_dependency_graph.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement dependency_graph.py**

Create `share/noba-web/server/healing/dependency_graph.py` with:

```python
"""Noba -- Dependency graph for root cause analysis.

DAG model where nodes are targets (services, infrastructure, external
boundaries) and edges represent dependencies. Used to resolve root cause
when multiple alerts fire: heal upward, suppress downward.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger("noba")


@dataclass
class DepNode:
    """A node in the dependency graph."""
    target: str
    node_type: str  # external, infrastructure, service, agent
    site: str = ""
    health_check: str = ""
    depends_on: list[str] = field(default_factory=list)
    auto_discovered: bool = False
    confirmed: bool = False


class DependencyGraph:
    """In-memory directed acyclic graph of service dependencies."""

    def __init__(self) -> None:
        self._nodes: dict[str, DepNode] = {}

    def add_node(self, target: str, *, node_type: str, site: str = "",
                 health_check: str = "", depends_on: list[str] | None = None,
                 auto_discovered: bool = False, confirmed: bool = False) -> None:
        self._nodes[target] = DepNode(
            target=target, node_type=node_type, site=site,
            health_check=health_check, depends_on=depends_on or [],
            auto_discovered=auto_discovered, confirmed=confirmed,
        )

    def get_node(self, target: str) -> DepNode | None:
        return self._nodes.get(target)

    def all_nodes(self) -> list[DepNode]:
        return list(self._nodes.values())

    def get_dependents(self, target: str) -> list[DepNode]:
        """Find all nodes that directly depend on this target."""
        return [n for n in self._nodes.values() if target in n.depends_on]

    def get_ancestors(self, target: str) -> list[DepNode]:
        """Walk UP the graph: all transitive dependencies of a target."""
        visited = set()
        result = []
        def _walk(t: str) -> None:
            node = self._nodes.get(t)
            if not node:
                return
            for dep in node.depends_on:
                if dep not in visited:
                    visited.add(dep)
                    dep_node = self._nodes.get(dep)
                    if dep_node:
                        result.append(dep_node)
                    _walk(dep)
        _walk(target)
        return result

    def get_all_descendants(self, target: str) -> set[str]:
        """Walk DOWN: all transitive dependents of a target."""
        visited = set()
        def _walk(t: str) -> None:
            for dep in self.get_dependents(t):
                if dep.target not in visited:
                    visited.add(dep.target)
                    _walk(dep.target)
        _walk(target)
        return visited

    def get_site_targets(self, site: str) -> list[DepNode]:
        return [n for n in self._nodes.values() if n.site == site]

    @classmethod
    def from_config(cls, config: list[dict]) -> DependencyGraph:
        """Build graph from YAML dependency config list."""
        g = cls()
        for entry in config:
            g.add_node(
                entry["target"],
                node_type=entry.get("type", "service"),
                site=entry.get("site", ""),
                health_check=entry.get("health_check", ""),
                depends_on=entry.get("depends_on", []),
            )
        return g

    def to_dict(self) -> list[dict]:
        """Serialize graph for API response."""
        return [
            {
                "target": n.target, "type": n.node_type, "site": n.site,
                "health_check": n.health_check, "depends_on": n.depends_on,
                "auto_discovered": n.auto_discovered, "confirmed": n.confirmed,
            }
            for n in self._nodes.values()
        ]


def resolve_root_cause(
    graph: DependencyGraph, *, failing_targets: set[str],
) -> tuple[str | None, set[str]]:
    """Find the root cause among failing targets.

    Returns (root_cause_target, set_of_suppressed_targets).
    The root cause is the highest failing ancestor in the graph.
    Suppressed targets are downstream of the root cause and should not
    be healed independently.
    """
    if not failing_targets:
        return None, set()

    # For each failing target, find the highest failing ancestor
    best_root = None
    best_depth = -1

    for target in failing_targets:
        ancestors = graph.get_ancestors(target)
        # Walk from deepest to shallowest: find the highest ancestor that is also failing
        failing_ancestors = [a for a in ancestors if a.target in failing_targets]
        if failing_ancestors:
            # The ancestor with the most ancestors of its own is the highest
            for anc in failing_ancestors:
                depth = len(graph.get_ancestors(anc.target))
                if depth > best_depth:
                    best_depth = depth
                    best_root = anc.target
        else:
            # This target has no failing ancestors — it might be the root
            depth = len(graph.get_ancestors(target))
            if best_root is None or depth > best_depth:
                best_depth = depth
                best_root = target

    if best_root is None:
        return None, set()

    # Everything downstream of root that is also failing gets suppressed
    descendants = graph.get_all_descendants(best_root)
    suppressed = failing_targets & descendants

    return best_root, suppressed
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_dependency_graph.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_dependency_graph.py share/noba-web/server/healing/dependency_graph.py
git commit -m "feat(healing): add dependency graph with root cause resolution"
```

---

## Task 2: Connectivity Monitor (Site Isolation)

**Files:**
- Create: `share/noba-web/server/healing/connectivity_monitor.py`
- Create: `tests/test_connectivity_monitor.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_connectivity_monitor.py`:
```python
"""Tests for healing.connectivity_monitor: site reachability tracking."""
from __future__ import annotations

import time


class TestConnectivityMonitor:
    def _make_monitor(self):
        from server.healing.connectivity_monitor import ConnectivityMonitor
        return ConnectivityMonitor()

    def test_site_starts_as_ok(self):
        mon = self._make_monitor()
        assert not mon.is_suspect("site-a")

    def test_mark_suspect(self):
        mon = self._make_monitor()
        mon.mark_suspect("site-a", reason="agent unreachable")
        assert mon.is_suspect("site-a")

    def test_clear_suspect(self):
        mon = self._make_monitor()
        mon.mark_suspect("site-a", reason="test")
        mon.clear_suspect("site-a")
        assert not mon.is_suspect("site-a")

    def test_get_suspect_sites(self):
        mon = self._make_monitor()
        mon.mark_suspect("site-a", reason="test")
        mon.mark_suspect("site-b", reason="test")
        suspects = mon.get_suspect_sites()
        assert "site-a" in suspects
        assert "site-b" in suspects

    def test_suspect_info_has_reason_and_timestamp(self):
        mon = self._make_monitor()
        mon.mark_suspect("site-a", reason="ISP down")
        info = mon.get_suspect_info("site-a")
        assert info is not None
        assert info["reason"] == "ISP down"
        assert "since" in info

    def test_should_suppress_healing_for_suspect_site(self):
        mon = self._make_monitor()
        mon.mark_suspect("site-a", reason="test")
        assert mon.should_suppress_healing("site-a")
        assert not mon.should_suppress_healing("site-b")

    def test_agent_reconnect_clears_suspect(self):
        mon = self._make_monitor()
        mon.mark_suspect("site-a", reason="test")
        mon.on_agent_reconnect("site-a")
        assert not mon.is_suspect("site-a")
```

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Implement connectivity_monitor.py**

Thread-safe in-memory state tracker. Tracks which sites are "connectivity-suspect".

- [ ] **Step 4: Run tests to verify they pass**

- [ ] **Step 5: Commit**

```bash
git add tests/test_connectivity_monitor.py share/noba-web/server/healing/connectivity_monitor.py
git commit -m "feat(healing): add connectivity monitor for site isolation"
```

---

## Task 3: Agent Verification

**Files:**
- Create: `share/noba-web/server/healing/agent_verify.py`
- Create: `tests/test_agent_verify.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_agent_verify.py`:
```python
"""Tests for healing.agent_verify: ask agent to confirm target state."""
from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestAgentVerify:
    def test_verify_returns_confirmed_down(self):
        from server.healing.agent_verify import verify_target_with_agent
        # Mock agent responding that service is down
        with patch("server.healing.agent_verify._query_agent") as mock_q:
            mock_q.return_value = {"status": "down", "detail": "container exited"}
            result = verify_target_with_agent("site-a-host", "plex")
            assert result.confirmed_down is True
            assert result.detail == "container exited"

    def test_verify_returns_confirmed_up(self):
        from server.healing.agent_verify import verify_target_with_agent
        with patch("server.healing.agent_verify._query_agent") as mock_q:
            mock_q.return_value = {"status": "up", "detail": "running"}
            result = verify_target_with_agent("site-a-host", "plex")
            assert result.confirmed_down is False

    def test_verify_agent_unreachable(self):
        from server.healing.agent_verify import verify_target_with_agent
        with patch("server.healing.agent_verify._query_agent") as mock_q:
            mock_q.return_value = None  # agent unreachable
            result = verify_target_with_agent("site-a-host", "plex")
            assert result.agent_reachable is False
            assert result.confirmed_down is None  # unknown

    def test_result_fields(self):
        from server.healing.agent_verify import VerifyResult
        r = VerifyResult(agent_reachable=True, confirmed_down=True, detail="stopped")
        assert r.agent_reachable
        assert r.confirmed_down
        assert r.detail == "stopped"
```

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Implement agent_verify.py**

Uses the existing agent command infrastructure to ask an agent to check a specific target. Returns a `VerifyResult` dataclass.

`_query_agent(hostname, target)` sends a `check_service` or `container_list` command to the agent and waits for the result (with timeout). If agent is unreachable, returns None.

- [ ] **Step 4: Run tests to verify they pass**

- [ ] **Step 5: Commit**

```bash
git add tests/test_agent_verify.py share/noba-web/server/healing/agent_verify.py
git commit -m "feat(healing): add agent verification for remote target state"
```

---

## Task 4: Dependency Graph DB Layer + API

**Files:**
- Modify: `share/noba-web/server/db/integrations.py`
- Modify: `share/noba-web/server/db/core.py`
- Modify: `share/noba-web/server/routers/healing.py`

- [ ] **Step 1: Add dependency_graph table to db/core.py**

```sql
CREATE TABLE IF NOT EXISTS dependency_graph (
    id INTEGER PRIMARY KEY,
    target TEXT NOT NULL UNIQUE,
    depends_on TEXT,
    node_type TEXT NOT NULL,
    health_check TEXT,
    site TEXT,
    auto_discovered INTEGER DEFAULT 0,
    confirmed INTEGER DEFAULT 0,
    created_at INTEGER NOT NULL
);
```

- [ ] **Step 2: Add DB functions to db/integrations.py**

Functions: `insert_dependency(conn, lock, ...)`, `list_dependencies(conn, lock)`, `delete_dependency(conn, lock, target)`, `update_dependency(conn, lock, target, ...)`. Plus delegation wrappers in core.py.

- [ ] **Step 3: Add API endpoint**

Add `GET /api/healing/dependencies` (read auth) to `routers/healing.py`. Reads from YAML config `dependencies` section, merges with DB (auto-discovered), returns the full graph.

Add `POST /api/healing/dependencies/validate` (operator auth) — validates a dependency config without saving.

- [ ] **Step 4: Run all tests**

- [ ] **Step 5: Commit**

```bash
git add share/noba-web/server/db/integrations.py share/noba-web/server/db/core.py share/noba-web/server/routers/healing.py
git commit -m "feat(healing): add dependency graph DB layer and API endpoint"
```

---

## Task 5: Wire Dependency Graph into Pipeline

**Files:**
- Modify: `share/noba-web/server/healing/__init__.py`

- [ ] **Step 1: Write failing integration tests**

Create `tests/test_pipeline_dependencies.py` testing that:
- When root cause is external, downstream healing is suppressed
- When agent is unreachable, site marked connectivity-suspect
- When agent confirms target is up, heal is suppressed as false positive

- [ ] **Step 2: Integrate into handle_heal_event()**

In `HealPipeline.__init__`, add `self._dep_graph` (loaded from YAML config) and `self._connectivity` (ConnectivityMonitor instance).

In `handle_heal_event()`, AFTER correlation but BEFORE planning:

```python
# Dependency check
if self._dep_graph:
    node = self._dep_graph.get_node(event.target)
    if node and node.site and self._connectivity.should_suppress_healing(node.site):
        logger.info("Healing suppressed for %s — site %s is connectivity-suspect",
                    event.target, node.site)
        return  # suppressed

    # Root cause check against currently firing alerts
    # (Check if this target's ancestors are also alerting)
```

- [ ] **Step 3: Run all tests**

- [ ] **Step 4: Commit**

```bash
git add share/noba-web/server/healing/__init__.py tests/test_pipeline_dependencies.py
git commit -m "feat(healing): integrate dependency graph into pipeline for root cause analysis"
```

---

## Task 6: Auto-Discovery Engine

**Files:**
- Create: `share/noba-web/server/healing/auto_discovery.py`
- Create: `tests/test_auto_discovery.py`

- [ ] **Step 1: Write failing tests**

Tests for co-failure detection: given a list of alert events with timestamps, detect pairs that co-fail 85%+ of the time within a 2-minute window.

- [ ] **Step 2: Implement auto_discovery.py**

Functions:
- `detect_co_failures(db, window_hours=720)` — queries heal_ledger for co-occurring failures
- `generate_dependency_suggestions(db, graph)` — produces HealSuggestion entries for discovered patterns

- [ ] **Step 3: Wire into scheduler**

Add to the hourly suggestion cycle in `scheduler.py`.

- [ ] **Step 4: Run all tests**

- [ ] **Step 5: Commit**

```bash
git add share/noba-web/server/healing/auto_discovery.py tests/test_auto_discovery.py share/noba-web/server/scheduler.py
git commit -m "feat(healing): add co-failure auto-discovery for dependency suggestions"
```

---

## Task 7: Lint + Final Integration Test

**Files:**
- All files modified in Tasks 1-6

- [ ] **Step 1: Run ruff on all modified files**

```bash
ruff check --fix share/noba-web/server/healing/ share/noba-web/server/db/ share/noba-web/server/routers/healing.py share/noba-web/server/scheduler.py
```

- [ ] **Step 2: Run the full test suite**

```bash
pytest tests/ -v --tb=short
```
Expected: All PASS

- [ ] **Step 3: Update CHANGELOG.md**

Add entry for Phase 2 intelligence work.

- [ ] **Step 4: Final commit**

```bash
git add CHANGELOG.md
git commit -m "chore: update CHANGELOG for heal intelligence phase"
```
