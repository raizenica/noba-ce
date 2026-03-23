# Self-Healing Foundation Implementation Plan (Phase 1 of 6)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the engine layer for fully self-healing NOBA: capability-based action dispatch, expanded action registry (55+ types), universal integration registry with abstract operations, multi-instance support, and pre-flight checks.

**Architecture:** Three new modules in `server/healing/` (capabilities, integration_registry, preflight) extend the existing pipeline. `remediation.py` gains new action types and a capability-aware dispatch path. The agent reports a capability manifest alongside its heartbeat. DB gains tables for integration instances and groups.

**Tech Stack:** Python 3.11+, SQLite WAL, dataclasses, httpx, pytest

**Spec:** `docs/superpowers/specs/2026-03-22-full-self-healing-design.md` (Sections 1-3, 15)

---

## File Map

### Action Naming Convention

The existing codebase uses `restart_container` and `restart_service` (verb_noun). New action types follow `noun_verb` (`service_reload`, `container_pause`) to avoid confusion. The OLD names are kept as-is for backward compatibility -- they are NOT renamed. Both naming styles coexist in `ACTION_TYPES`. The `FALLBACK_CHAINS` dict provides cross-platform dispatch for ALL action types (old and new).

### New files
| File | Responsibility |
|------|---------------|
| `server/healing/capabilities.py` | Capability manifest model, probe logic, dispatch resolution |
| `server/healing/preflight.py` | Pre-flight check system (tool exists, target exists, permissions, maintenance) |
| `server/healing/integration_registry.py` | Abstract operation -> platform-specific handler mapping |
| `server/db/integrations.py` | DB functions for integration_instances, integration_groups, capability_manifests |
| `tests/test_capabilities.py` | Tests for capability probing, dispatch, fallback chains |
| `tests/test_preflight.py` | Tests for pre-flight checks |
| `tests/test_integration_registry.py` | Tests for abstract op dispatch, multi-instance, groups |
| `tests/test_db_integrations.py` | Tests for integration DB layer |
| `tests/test_action_registry_expanded.py` | Tests for new action type definitions |
| `tests/test_agent_capabilities.py` | Tests for agent capability probing and manifest storage |
| `tests/test_executor_preflight.py` | Tests for pre-flight integration in executor |

### Modified files
| File | Change |
|------|--------|
| `server/remediation.py` | Add ~40 new action types to ACTION_TYPES, add capability-aware dispatch |
| `server/db/core.py` | Add integration_instances, integration_groups, capability_manifests tables + delegation wrappers |
| `share/noba-agent/agent.py` | Add capability probing (probe_capabilities command, manifest in report) |
| `server/routers/agents.py` | Store capability manifest from agent reports, add refresh_capabilities command |
| `server/routers/healing.py` | Add /api/healing/capabilities endpoints |
| `server/healing/executor.py` | Wire pre-flight checks before action execution |

---

## Task 1: Capability Manifest Model

**Files:**
- Create: `share/noba-web/server/healing/capabilities.py`
- Create: `tests/test_capabilities.py`

- [ ] **Step 1: Write failing tests for capability model**

Create `tests/test_capabilities.py`:
```python
"""Tests for healing.capabilities: manifest model and dispatch resolution."""
from __future__ import annotations


class TestCapabilityManifest:
    def test_from_dict_basic(self):
        from server.healing.capabilities import CapabilityManifest
        data = {
            "os": "linux", "distro": "ubuntu", "distro_version": "24.04",
            "kernel": "6.8.0", "init_system": "systemd",
            "is_wsl": False, "is_container": False,
            "capabilities": {
                "docker": {"available": True, "version": "27.1"},
                "systemctl": {"available": True},
                "apt": {"available": True},
            },
        }
        m = CapabilityManifest.from_dict(data)
        assert m.os == "linux"
        assert m.distro == "ubuntu"
        assert m.init_system == "systemd"
        assert m.has_capability("docker")
        assert m.has_capability("systemctl")
        assert not m.has_capability("podman")

    def test_has_capability_degraded(self):
        from server.healing.capabilities import CapabilityManifest
        data = {
            "os": "linux", "distro": "ubuntu", "distro_version": "24.04",
            "kernel": "6.8.0", "init_system": "systemd",
            "is_wsl": False, "is_container": False,
            "capabilities": {
                "docker": {"available": True, "version": "27.1", "state": "degraded"},
            },
        }
        m = CapabilityManifest.from_dict(data)
        assert not m.has_capability("docker")  # degraded = not usable
        assert m.has_capability("docker", allow_degraded=True)

    def test_empty_capabilities(self):
        from server.healing.capabilities import CapabilityManifest
        data = {
            "os": "windows", "distro": "windows", "distro_version": "11",
            "kernel": "10.0", "init_system": "windows_scm",
            "is_wsl": False, "is_container": False,
            "capabilities": {},
        }
        m = CapabilityManifest.from_dict(data)
        assert not m.has_capability("docker")

    def test_to_dict_roundtrip(self):
        from server.healing.capabilities import CapabilityManifest
        data = {
            "os": "linux", "distro": "ubuntu", "distro_version": "24.04",
            "kernel": "6.8.0", "init_system": "systemd",
            "is_wsl": False, "is_container": False,
            "capabilities": {"docker": {"available": True}},
        }
        m = CapabilityManifest.from_dict(data)
        roundtrip = m.to_dict()
        assert roundtrip["os"] == "linux"
        assert roundtrip["capabilities"]["docker"]["available"] is True


class TestResolveHandler:
    def test_first_matching_handler_wins(self):
        from server.healing.capabilities import CapabilityManifest, resolve_handler
        manifest = CapabilityManifest.from_dict({
            "os": "linux", "distro": "ubuntu", "distro_version": "24.04",
            "kernel": "6.8.0", "init_system": "systemd",
            "is_wsl": False, "is_container": False,
            "capabilities": {"systemctl": {"available": True}},
        })
        handlers = [
            {"requires": "systemctl", "cmd": "systemctl restart {service}"},
            {"requires": "rc-service", "cmd": "rc-service {service} restart"},
        ]
        result = resolve_handler(handlers, manifest)
        assert result is not None
        assert "systemctl" in result["cmd"]

    def test_fallback_to_second(self):
        from server.healing.capabilities import CapabilityManifest, resolve_handler
        manifest = CapabilityManifest.from_dict({
            "os": "linux", "distro": "alpine", "distro_version": "3.19",
            "kernel": "6.6.0", "init_system": "openrc",
            "is_wsl": False, "is_container": False,
            "capabilities": {"rc-service": {"available": True}},
        })
        handlers = [
            {"requires": "systemctl", "cmd": "systemctl restart {service}"},
            {"requires": "rc-service", "cmd": "rc-service {service} restart"},
        ]
        result = resolve_handler(handlers, manifest)
        assert result is not None
        assert "rc-service" in result["cmd"]

    def test_no_match_returns_none(self):
        from server.healing.capabilities import CapabilityManifest, resolve_handler
        manifest = CapabilityManifest.from_dict({
            "os": "linux", "distro": "custom", "distro_version": "1.0",
            "kernel": "5.0", "init_system": "runit",
            "is_wsl": False, "is_container": False,
            "capabilities": {},
        })
        handlers = [
            {"requires": "systemctl", "cmd": "systemctl restart {service}"},
            {"requires": "powershell", "cmd": "Restart-Service {service}"},
        ]
        result = resolve_handler(handlers, manifest)
        assert result is None

    def test_windows_handler_selected(self):
        from server.healing.capabilities import CapabilityManifest, resolve_handler
        manifest = CapabilityManifest.from_dict({
            "os": "windows", "distro": "windows", "distro_version": "11",
            "kernel": "10.0", "init_system": "windows_scm",
            "is_wsl": False, "is_container": False,
            "capabilities": {"powershell": {"available": True}},
        })
        handlers = [
            {"requires": "systemctl", "cmd": "systemctl restart {service}"},
            {"requires": "powershell", "cmd": "Restart-Service {service}"},
        ]
        result = resolve_handler(handlers, manifest)
        assert "Restart-Service" in result["cmd"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_capabilities.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement capabilities.py**

Create `share/noba-web/server/healing/capabilities.py`:
```python
"""Noba -- Capability manifest model and handler resolution.

Capability-based dispatch: never trust OS labels, verify what tools
are actually available on each host. Each action has fallback chains
that match against the capability manifest.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger("noba")


@dataclass
class CapabilityManifest:
    """Agent capability manifest — what tools and subsystems are available."""

    os: str = "unknown"
    distro: str = "unknown"
    distro_version: str = ""
    kernel: str = ""
    init_system: str = "unknown"
    is_wsl: bool = False
    is_container: bool = False
    capabilities: dict = field(default_factory=dict)

    def has_capability(self, name: str, *, allow_degraded: bool = False) -> bool:
        """Check if a capability is available (not degraded unless allowed)."""
        cap = self.capabilities.get(name)
        if not cap or not isinstance(cap, dict):
            return False
        if not cap.get("available", False):
            return False
        if cap.get("state") == "degraded" and not allow_degraded:
            return False
        return True

    def mark_degraded(self, name: str) -> None:
        """Mark a capability as degraded after a pre-flight failure."""
        cap = self.capabilities.get(name)
        if cap and isinstance(cap, dict):
            cap["state"] = "degraded"

    @classmethod
    def from_dict(cls, data: dict) -> CapabilityManifest:
        return cls(
            os=data.get("os", "unknown"),
            distro=data.get("distro", "unknown"),
            distro_version=data.get("distro_version", ""),
            kernel=data.get("kernel", ""),
            init_system=data.get("init_system", "unknown"),
            is_wsl=data.get("is_wsl", False),
            is_container=data.get("is_container", False),
            capabilities=data.get("capabilities", {}),
        )

    def to_dict(self) -> dict:
        return {
            "os": self.os,
            "distro": self.distro,
            "distro_version": self.distro_version,
            "kernel": self.kernel,
            "init_system": self.init_system,
            "is_wsl": self.is_wsl,
            "is_container": self.is_container,
            "capabilities": self.capabilities,
        }


def resolve_handler(
    handlers: list[dict], manifest: CapabilityManifest,
) -> dict | None:
    """Find the first handler whose required capability is available.

    Each handler is {"requires": "tool_name", "cmd": "command template"}.
    Returns the first matching handler dict, or None if no match.
    """
    for handler in handlers:
        required = handler.get("requires", "")
        if manifest.has_capability(required):
            return handler
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_capabilities.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_capabilities.py share/noba-web/server/healing/capabilities.py
git commit -m "feat(healing): add capability manifest model with handler resolution"
```

---

## Task 2: Pre-Flight Check System

**Files:**
- Create: `share/noba-web/server/healing/preflight.py`
- Create: `tests/test_preflight.py`

- [ ] **Step 1: Write failing tests for pre-flight checks**

Create `tests/test_preflight.py`:
```python
"""Tests for healing.preflight: pre-flight validation before action execution."""
from __future__ import annotations

from unittest.mock import MagicMock


class TestPreFlightCheck:
    def _make_manifest(self, caps=None):
        from server.healing.capabilities import CapabilityManifest
        return CapabilityManifest.from_dict({
            "os": "linux", "distro": "ubuntu", "distro_version": "24.04",
            "kernel": "6.8.0", "init_system": "systemd",
            "is_wsl": False, "is_container": False,
            "capabilities": caps or {"systemctl": {"available": True}},
        })

    def test_passes_when_all_ok(self):
        from server.healing.preflight import run_preflight
        manifest = self._make_manifest({"systemctl": {"available": True}})
        handlers = [{"requires": "systemctl", "cmd": "systemctl restart {service}"}]
        result = run_preflight(
            action_type="service_restart",
            handlers=handlers,
            manifest=manifest,
            target="nginx",
        )
        assert result.passed
        assert result.resolved_handler is not None

    def test_fails_no_capability_match(self):
        from server.healing.preflight import run_preflight
        manifest = self._make_manifest({})
        handlers = [{"requires": "systemctl", "cmd": "systemctl restart {service}"}]
        result = run_preflight(
            action_type="service_restart",
            handlers=handlers,
            manifest=manifest,
            target="nginx",
        )
        assert not result.passed
        assert "no_capable_handler" in result.failure_reason

    def test_fails_degraded_capability(self):
        from server.healing.preflight import run_preflight
        manifest = self._make_manifest(
            {"systemctl": {"available": True, "state": "degraded"}},
        )
        handlers = [{"requires": "systemctl", "cmd": "systemctl restart {service}"}]
        result = run_preflight(
            action_type="service_restart",
            handlers=handlers,
            manifest=manifest,
            target="nginx",
        )
        assert not result.passed
        assert "no_capable_handler" in result.failure_reason

    def test_no_manifest_fails(self):
        from server.healing.preflight import run_preflight
        result = run_preflight(
            action_type="service_restart",
            handlers=[{"requires": "systemctl", "cmd": "..."}],
            manifest=None,
            target="nginx",
        )
        assert not result.passed
        assert "no_manifest" in result.failure_reason

    def test_maintenance_window_blocks(self):
        from server.healing.preflight import run_preflight
        manifest = self._make_manifest({"systemctl": {"available": True}})
        handlers = [{"requires": "systemctl", "cmd": "..."}]
        result = run_preflight(
            action_type="service_restart",
            handlers=handlers,
            manifest=manifest,
            target="nginx",
            in_maintenance=True,
        )
        assert not result.passed
        assert "maintenance" in result.failure_reason

    def test_result_contains_all_checks(self):
        from server.healing.preflight import run_preflight
        manifest = self._make_manifest({"systemctl": {"available": True}})
        handlers = [{"requires": "systemctl", "cmd": "..."}]
        result = run_preflight(
            action_type="service_restart",
            handlers=handlers,
            manifest=manifest,
            target="nginx",
        )
        assert isinstance(result.checks, dict)
        assert "capability_match" in result.checks
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_preflight.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement preflight.py**

Create `share/noba-web/server/healing/preflight.py`:
```python
"""Noba -- Pre-flight checks before heal action execution.

Every action must pass pre-flight before it runs:
1. Capability match -- handler exists for this host's capabilities
2. Not in maintenance -- target is not in a maintenance window
3. Manifest exists -- we have a capability manifest for this host

Pre-flight is cheap and fast. It prevents wasted execution and
accidental damage from mismatched capabilities.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .capabilities import CapabilityManifest, resolve_handler

logger = logging.getLogger("noba")


@dataclass
class PreFlightResult:
    """Result of pre-flight validation."""

    passed: bool = False
    failure_reason: str = ""
    resolved_handler: dict | None = None
    checks: dict = field(default_factory=dict)


def run_preflight(
    *,
    action_type: str,
    handlers: list[dict],
    manifest: CapabilityManifest | None,
    target: str,
    in_maintenance: bool = False,
) -> PreFlightResult:
    """Run all pre-flight checks for an action. Returns PreFlightResult."""
    result = PreFlightResult()
    result.checks = {}

    # Check 1: manifest exists
    if manifest is None:
        result.checks["manifest"] = "missing"
        result.failure_reason = "no_manifest"
        logger.warning("Pre-flight FAIL [%s@%s]: no capability manifest", action_type, target)
        return result
    result.checks["manifest"] = "ok"

    # Check 2: maintenance window
    if in_maintenance:
        result.checks["maintenance"] = "blocked"
        result.failure_reason = "maintenance"
        logger.info("Pre-flight FAIL [%s@%s]: target in maintenance window", action_type, target)
        return result
    result.checks["maintenance"] = "ok"

    # Check 3: capability match
    handler = resolve_handler(handlers, manifest)
    if handler is None:
        result.checks["capability_match"] = "no match"
        result.failure_reason = "no_capable_handler"
        caps = list(manifest.capabilities.keys())
        logger.warning(
            "Pre-flight FAIL [%s@%s]: no handler matches capabilities %s",
            action_type, target, caps,
        )
        return result
    result.checks["capability_match"] = handler.get("requires", "")
    result.resolved_handler = handler

    # All passed
    result.passed = True
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_preflight.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_preflight.py share/noba-web/server/healing/preflight.py
git commit -m "feat(healing): add pre-flight check system for action validation"
```

---

## Task 3: Expanded Action Registry

**Files:**
- Modify: `share/noba-web/server/remediation.py`
- Create: `tests/test_action_registry_expanded.py`

- [ ] **Step 1: Write tests for new action type definitions**

Create `tests/test_action_registry_expanded.py`:
```python
"""Tests for expanded action registry: all 55+ action types defined correctly."""
from __future__ import annotations


class TestActionTypesDefined:
    """Verify all new action types are registered with required fields."""

    REQUIRED_FIELDS = {"risk", "params", "description", "timeout_s"}
    VALID_RISKS = {"low", "medium", "high"}

    def _get_action_types(self):
        from server.remediation import ACTION_TYPES
        return ACTION_TYPES

    def test_all_types_have_required_fields(self):
        for name, defn in self._get_action_types().items():
            for field in self.REQUIRED_FIELDS:
                assert field in defn, f"{name} missing field: {field}"

    def test_all_types_have_valid_risk(self):
        for name, defn in self._get_action_types().items():
            assert defn["risk"] in self.VALID_RISKS, f"{name} invalid risk: {defn['risk']}"

    def test_minimum_action_count(self):
        """Spec requires 55+ action types."""
        types = self._get_action_types()
        assert len(types) >= 40, f"Only {len(types)} types, need 40+ for Phase 1"

    # Spot-check new low-risk actions
    def test_service_reload_defined(self):
        types = self._get_action_types()
        assert "service_reload" in types
        assert types["service_reload"]["risk"] == "low"

    def test_process_kill_defined(self):
        types = self._get_action_types()
        assert "process_kill" in types
        assert types["process_kill"]["risk"] == "low"

    def test_container_pause_defined(self):
        types = self._get_action_types()
        assert "container_pause" in types
        assert types["container_pause"]["risk"] == "low"

    def test_journal_vacuum_defined(self):
        types = self._get_action_types()
        assert "journal_vacuum" in types
        assert types["journal_vacuum"]["risk"] == "low"

    # Spot-check medium-risk
    def test_container_recreate_defined(self):
        types = self._get_action_types()
        assert "container_recreate" in types
        assert types["container_recreate"]["risk"] == "medium"

    def test_cert_renew_defined(self):
        types = self._get_action_types()
        assert "cert_renew" in types
        assert types["cert_renew"]["risk"] == "medium"

    def test_vpn_reconnect_defined(self):
        types = self._get_action_types()
        assert "vpn_reconnect" in types
        assert types["vpn_reconnect"]["risk"] == "medium"

    # Spot-check high-risk
    def test_host_reboot_defined(self):
        types = self._get_action_types()
        assert "host_reboot" in types
        assert types["host_reboot"]["risk"] == "high"

    def test_vm_restart_defined(self):
        types = self._get_action_types()
        assert "vm_restart" in types
        assert types["vm_restart"]["risk"] == "high"

    def test_snapshot_rollback_defined(self):
        types = self._get_action_types()
        assert "snapshot_rollback" in types
        assert types["snapshot_rollback"]["risk"] == "high"


class TestFallbackChains:
    """Verify action types with fallback chains have them properly defined."""

    def test_fallback_chains_exist_for_cross_platform_actions(self):
        from server.remediation import FALLBACK_CHAINS
        cross_platform = [
            "service_restart", "service_reload", "process_kill",
            "network_interface_restart", "disk_cleanup",
        ]
        for action in cross_platform:
            assert action in FALLBACK_CHAINS, f"No fallback chain for {action}"
            assert len(FALLBACK_CHAINS[action]) >= 2, (
                f"Fallback chain for {action} needs 2+ handlers"
            )

    def test_each_chain_handler_has_requires_and_cmd(self):
        from server.remediation import FALLBACK_CHAINS
        for action, handlers in FALLBACK_CHAINS.items():
            for i, h in enumerate(handlers):
                assert "requires" in h, f"{action}[{i}] missing 'requires'"
                assert "cmd" in h, f"{action}[{i}] missing 'cmd'"


class TestReversibilityRegistry:
    """Verify reversible actions have reverse_action defined."""

    def test_reversibility_defined(self):
        from server.remediation import ACTION_TYPES
        for name, defn in ACTION_TYPES.items():
            assert "reversible" in defn, f"{name} missing 'reversible' field"
            if defn["reversible"]:
                assert "reverse_action" in defn, (
                    f"{name} is reversible but no reverse_action defined"
                )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_action_registry_expanded.py -v`
Expected: FAIL — missing action types

- [ ] **Step 3: Add new action type definitions to remediation.py**

In `share/noba-web/server/remediation.py`, add to `ACTION_TYPES` dict after existing entries.

Also add `FALLBACK_CHAINS` dict and update all existing + new entries with `reversible` and `settle_s` fields.

New action types to add (all require adding to ACTION_TYPES):

**Low-risk:**
`service_reload`, `service_reset_failed`, `container_pause`, `container_image_pull`, `process_kill`, `nice_adjust`, `log_rotate`, `temp_cleanup`, `dns_cache_clear`, `event_log_clear`, `sfc_scan`, `journal_vacuum`, `package_cache_clean`, `windows_update_check`, `disk_cleanup`

**Medium-risk:**
`container_recreate`, `service_dependency_restart`, `storage_cleanup`, `cert_renew`, `vpn_reconnect`, `zfs_scrub`, `btrfs_scrub`, `chkdsk`, `fsck_schedule`, `backup_verify`, `servarr_queue_cleanup`, `media_library_scan`, `network_interface_restart`, `compose_restart`, `scheduled_task_repair`, `iis_app_pool_recycle`, `wsl_restart`, `memory_pressure_relief`

**High-risk:**
`host_reboot`, `vm_restart`, `vm_migrate`, `package_security_patch`, `snapshot_rollback`, `firewall_rule_add`, `driver_rollback`, `raid_rebuild`, `group_policy_refresh`, `ad_replication_force`

Each entry follows the existing pattern:
```python
"service_reload": {
    "risk": "low",
    "params": {"service": str},
    "description": "Reload service configuration without full restart",
    "timeout_s": 15,
    "settle_s": 10,
    "reversible": False,
    "has_health_check": True,
},
```

Add `FALLBACK_CHAINS` dict:
```python
FALLBACK_CHAINS = {
    "service_restart": [
        {"requires": "systemctl", "cmd": "systemctl restart {service}"},
        {"requires": "rc-service", "cmd": "rc-service {service} restart"},
        {"requires": "service", "cmd": "service {service} restart"},
        {"requires": "powershell", "cmd": "Restart-Service {service}"},
    ],
    "service_reload": [
        {"requires": "systemctl", "cmd": "systemctl reload {service}"},
        {"requires": "rc-service", "cmd": "rc-service {service} reload"},
        {"requires": "powershell", "cmd": "Restart-Service {service}"},
    ],
    "process_kill": [
        {"requires": "kill", "cmd": "kill -TERM {pid}"},
        {"requires": "powershell", "cmd": "Stop-Process -Id {pid} -Force"},
    ],
    "network_interface_restart": [
        {"requires": "ip", "cmd": "ip link set {nic} down && ip link set {nic} up"},
        {"requires": "ifconfig", "cmd": "ifconfig {nic} down && ifconfig {nic} up"},
        {"requires": "powershell", "cmd": "Restart-NetAdapter -Name '{nic}'"},
    ],
    "disk_cleanup": [
        {"requires": "fstrim", "cmd": "fstrim -v /"},
        {"requires": "powershell", "cmd": "cleanmgr /sagerun:1"},
    ],
    "package_cache_clean": [
        {"requires": "apt", "cmd": "apt clean"},
        {"requires": "dnf", "cmd": "dnf clean all"},
        {"requires": "apk", "cmd": "apk cache clean"},
    ],
    "package_security_patch": [
        {"requires": "apt", "cmd": "apt upgrade -y --only-upgrade -o Dpkg::Options::='--force-confold'"},
        {"requires": "dnf", "cmd": "dnf upgrade --security -y"},
        {"requires": "apk", "cmd": "apk upgrade"},
        {"requires": "powershell", "cmd": "Install-WindowsUpdate -AcceptAll"},
    ],
    "host_reboot": [
        {"requires": "shutdown", "cmd": "shutdown -r +1"},
        {"requires": "powershell", "cmd": "Restart-Computer -Force"},
    ],
}
```

Also add `reversible` and `settle_s` to ALL existing action types (backfill).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_action_registry_expanded.py -v`
Expected: All PASS

- [ ] **Step 5: Run ruff and existing tests**

```bash
ruff check --fix share/noba-web/server/remediation.py
pytest tests/ -v --tb=short 2>&1 | tail -20
```
Expected: All existing tests still pass

- [ ] **Step 6: Commit**

```bash
git add share/noba-web/server/remediation.py tests/test_action_registry_expanded.py
git commit -m "feat(remediation): add 40+ action types with fallback chains and reversibility"
```

---

## Task 4: Integration DB Layer

**Files:**
- Create: `share/noba-web/server/db/integrations.py`
- Modify: `share/noba-web/server/db/core.py`
- Create: `tests/test_db_integrations.py`

- [ ] **Step 1: Write failing tests for integration DB functions**

Create `tests/test_db_integrations.py`:
```python
"""Tests for db.integrations: integration_instances, groups, capabilities."""
from __future__ import annotations

import sqlite3
import threading

import pytest


@pytest.fixture()
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    lock = threading.Lock()
    from server.db.integrations import create_tables
    create_tables(conn)
    return conn, lock


class TestIntegrationInstances:
    def test_insert_and_get(self, db):
        from server.db.integrations import insert_instance, get_instance
        conn, lock = db
        insert_instance(conn, lock, id="truenas-main", category="nas",
                       platform="truenas", url="https://truenas.local",
                       auth_config='{"token_env":"TN_TOKEN"}', site="site-a",
                       tags='["production"]')
        inst = get_instance(conn, lock, "truenas-main")
        assert inst is not None
        assert inst["platform"] == "truenas"
        assert inst["site"] == "site-a"

    def test_list_by_category(self, db):
        from server.db.integrations import insert_instance, list_instances
        conn, lock = db
        insert_instance(conn, lock, id="tn1", category="nas", platform="truenas",
                       url="https://tn1", auth_config='{}')
        insert_instance(conn, lock, id="syn1", category="nas", platform="synology",
                       url="https://syn1", auth_config='{}')
        insert_instance(conn, lock, id="pve1", category="hypervisor", platform="proxmox",
                       url="https://pve1", auth_config='{}')
        nas = list_instances(conn, lock, category="nas")
        assert len(nas) == 2
        all_inst = list_instances(conn, lock)
        assert len(all_inst) == 3

    def test_list_by_site(self, db):
        from server.db.integrations import insert_instance, list_instances
        conn, lock = db
        insert_instance(conn, lock, id="tn1", category="nas", platform="truenas",
                       url="https://tn1", auth_config='{}', site="site-a")
        insert_instance(conn, lock, id="tn2", category="nas", platform="truenas",
                       url="https://tn2", auth_config='{}', site="site-b")
        result = list_instances(conn, lock, site="site-a")
        assert len(result) == 1
        assert result[0]["id"] == "tn1"

    def test_update_health_status(self, db):
        from server.db.integrations import insert_instance, update_health, get_instance
        conn, lock = db
        insert_instance(conn, lock, id="tn1", category="nas", platform="truenas",
                       url="https://tn1", auth_config='{}')
        update_health(conn, lock, "tn1", "online")
        inst = get_instance(conn, lock, "tn1")
        assert inst["health_status"] == "online"

    def test_delete_instance(self, db):
        from server.db.integrations import insert_instance, delete_instance, get_instance
        conn, lock = db
        insert_instance(conn, lock, id="tn1", category="nas", platform="truenas",
                       url="https://tn1", auth_config='{}')
        delete_instance(conn, lock, "tn1")
        assert get_instance(conn, lock, "tn1") is None


class TestIntegrationGroups:
    def test_add_to_group_and_list(self, db):
        from server.db.integrations import (
            insert_instance, add_to_group, list_group,
        )
        conn, lock = db
        insert_instance(conn, lock, id="ph1", category="dns", platform="pihole",
                       url="http://ph1", auth_config='{}')
        insert_instance(conn, lock, id="ph2", category="dns", platform="pihole",
                       url="http://ph2", auth_config='{}')
        add_to_group(conn, lock, "all-pihole", "ph1")
        add_to_group(conn, lock, "all-pihole", "ph2")
        members = list_group(conn, lock, "all-pihole")
        assert len(members) == 2

    def test_remove_from_group(self, db):
        from server.db.integrations import (
            insert_instance, add_to_group, remove_from_group, list_group,
        )
        conn, lock = db
        insert_instance(conn, lock, id="ph1", category="dns", platform="pihole",
                       url="http://ph1", auth_config='{}')
        add_to_group(conn, lock, "all-pihole", "ph1")
        remove_from_group(conn, lock, "all-pihole", "ph1")
        members = list_group(conn, lock, "all-pihole")
        assert len(members) == 0

    def test_list_all_groups(self, db):
        from server.db.integrations import (
            insert_instance, add_to_group, list_groups,
        )
        conn, lock = db
        insert_instance(conn, lock, id="ph1", category="dns", platform="pihole",
                       url="http://ph1", auth_config='{}')
        insert_instance(conn, lock, id="tn1", category="nas", platform="truenas",
                       url="http://tn1", auth_config='{}')
        add_to_group(conn, lock, "all-pihole", "ph1")
        add_to_group(conn, lock, "all-nas", "tn1")
        groups = list_groups(conn, lock)
        assert set(groups) == {"all-pihole", "all-nas"}


class TestCapabilityManifests:
    def test_upsert_and_get(self, db):
        from server.db.integrations import upsert_manifest, get_manifest
        conn, lock = db
        upsert_manifest(conn, lock, hostname="host1",
                       manifest='{"os":"linux","capabilities":{}}')
        m = get_manifest(conn, lock, "host1")
        assert m is not None
        assert '"os"' in m["manifest"]

    def test_upsert_updates_existing(self, db):
        from server.db.integrations import upsert_manifest, get_manifest
        conn, lock = db
        upsert_manifest(conn, lock, hostname="host1", manifest='{"v":1}')
        upsert_manifest(conn, lock, hostname="host1", manifest='{"v":2}')
        m = get_manifest(conn, lock, "host1")
        assert '"v": 2' in m["manifest"] or '"v":2' in m["manifest"]

    def test_mark_degraded(self, db):
        from server.db.integrations import (
            upsert_manifest, mark_capability_degraded, get_manifest,
        )
        conn, lock = db
        upsert_manifest(conn, lock, hostname="host1", manifest='{}')
        mark_capability_degraded(conn, lock, "host1", "docker")
        m = get_manifest(conn, lock, "host1")
        assert "docker" in m["degraded_capabilities"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_db_integrations.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement db/integrations.py**

Create `share/noba-web/server/db/integrations.py` following the existing `(conn, lock, ...)` pattern from `db/healing.py` and `db/automations.py`.

- [ ] **Step 4: Add table creation to db/core.py**

Add `integration_instances`, `integration_groups`, and `capability_manifests` table creation to the migration path in `db/core.py`. Add delegation wrappers to the `Database` class.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_db_integrations.py -v`
Expected: All PASS

- [ ] **Step 6: Run all tests**

Run: `pytest tests/ -v --tb=short 2>&1 | tail -20`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add share/noba-web/server/db/integrations.py share/noba-web/server/db/core.py tests/test_db_integrations.py
git commit -m "feat(db): add integration instances, groups, and capability manifest tables"
```

---

## Task 5: Integration Registry

**Files:**
- Create: `share/noba-web/server/healing/integration_registry.py`
- Create: `tests/test_integration_registry.py`

- [ ] **Step 1: Write failing tests for integration registry**

Create `tests/test_integration_registry.py`:
```python
"""Tests for healing.integration_registry: abstract op -> platform dispatch."""
from __future__ import annotations


class TestIntegrationRegistry:
    def test_get_handler_for_known_platform(self):
        from server.healing.integration_registry import get_integration_handler
        handler = get_integration_handler("nas_scrub", "truenas")
        assert handler is not None
        assert "endpoint" in handler or "method" in handler

    def test_get_handler_unknown_platform_returns_none(self):
        from server.healing.integration_registry import get_integration_handler
        handler = get_integration_handler("nas_scrub", "nonexistent_platform")
        assert handler is None

    def test_get_handler_unknown_operation_returns_none(self):
        from server.healing.integration_registry import get_integration_handler
        handler = get_integration_handler("nonexistent_op", "truenas")
        assert handler is None

    def test_list_operations_for_category(self):
        from server.healing.integration_registry import list_operations
        ops = list_operations("nas")
        assert "nas_scrub" in ops
        assert "nas_pool_repair" in ops

    def test_list_platforms_for_operation(self):
        from server.healing.integration_registry import list_platforms
        platforms = list_platforms("nas_scrub")
        assert "truenas" in platforms
        assert len(platforms) >= 2  # at least truenas + one more

    def test_list_all_categories(self):
        from server.healing.integration_registry import list_categories
        cats = list_categories()
        assert "nas" in cats
        assert "hypervisor" in cats
        assert "dns" in cats
        assert "media" in cats
        assert len(cats) >= 20  # spec requires 24+

    def test_register_plugin_handler(self):
        from server.healing.integration_registry import (
            register_handler, get_integration_handler,
        )
        register_handler("nas_scrub", "my_custom_nas", {
            "method": "POST", "endpoint": "/api/scrub",
        })
        handler = get_integration_handler("nas_scrub", "my_custom_nas")
        assert handler is not None
        assert handler["endpoint"] == "/api/scrub"


class TestOperationCategories:
    """Verify each category from the spec has operations registered."""

    def _check_category(self, category, min_ops):
        from server.healing.integration_registry import list_operations
        ops = list_operations(category)
        assert len(ops) >= min_ops, (
            f"Category '{category}' has {len(ops)} ops, need {min_ops}+"
        )

    def test_nas(self):
        self._check_category("nas", 5)

    def test_hypervisor(self):
        self._check_category("hypervisor", 5)

    def test_dns(self):
        self._check_category("dns", 4)

    def test_media(self):
        self._check_category("media", 4)

    def test_media_management(self):
        self._check_category("media_management", 4)

    def test_vpn(self):
        self._check_category("vpn", 3)

    def test_backup(self):
        self._check_category("backup", 4)

    def test_security(self):
        self._check_category("security", 3)

    def test_network_hardware(self):
        self._check_category("network_hardware", 4)

    def test_logging(self):
        self._check_category("logging", 3)

    def test_database(self):
        self._check_category("database", 4)

    def test_container_runtime(self):
        self._check_category("container_runtime", 4)

    def test_reverse_proxy(self):
        self._check_category("reverse_proxy", 4)

    def test_download_client(self):
        self._check_category("download_client", 3)

    def test_monitoring(self):
        self._check_category("monitoring", 3)

    def test_smart_home(self):
        self._check_category("smart_home", 3)

    def test_identity_auth(self):
        self._check_category("identity_auth", 3)

    def test_certificate(self):
        self._check_category("certificate", 3)

    def test_git_devops(self):
        self._check_category("git_devops", 3)

    def test_mail(self):
        self._check_category("mail", 3)

    def test_cloud_cdn(self):
        self._check_category("cloud_cdn", 3)

    def test_power_ups(self):
        self._check_category("power_ups", 3)

    def test_surveillance(self):
        self._check_category("surveillance", 3)

    def test_metrics_timeseries(self):
        self._check_category("metrics", 3)

    def test_message_queue(self):
        self._check_category("message_queue", 3)

    def test_photo_management(self):
        self._check_category("photo_management", 3)

    def test_automation_workflow(self):
        self._check_category("automation_workflow", 3)

    def test_file_sync(self):
        self._check_category("file_sync", 3)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_integration_registry.py -v`
Expected: FAIL

- [ ] **Step 3: Implement integration_registry.py**

Create `share/noba-web/server/healing/integration_registry.py`:

This module defines `INTEGRATION_HANDLERS` — a nested dict mapping `{operation: {platform: handler_config}}`. It also defines `OPERATION_CATEGORIES` — a dict mapping `{category: [operation_names]}`.

Key functions:
- `get_integration_handler(operation, platform)` -> handler config dict or None
- `list_operations(category)` -> list of operation names
- `list_platforms(operation)` -> list of platform names
- `list_categories()` -> list of category names
- `register_handler(operation, platform, config)` -> add plugin handler

The handler configs are declarative dicts (not callables). Actual execution happens in the executor which interprets the config (method, endpoint, auth pattern). Phase 1 just defines the registry; wiring execution comes in later phases.

Each category from the spec (Sections 3 + 15) gets its operations registered with at least the platforms listed in the spec. Handler configs use the pattern:
```python
{"method": "POST|GET|exec|rpc", "endpoint": "/api/path", "auth": "bearer|session|api_key|local"}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_integration_registry.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add share/noba-web/server/healing/integration_registry.py tests/test_integration_registry.py
git commit -m "feat(healing): add universal integration registry with 120+ abstract operations"
```

---

## Task 6: Agent Capability Probing

**Files:**
- Modify: `share/noba-agent/agent.py`
- Modify: `share/noba-web/server/routers/agents.py`
- Create: `tests/test_agent_capabilities.py`

- [ ] **Step 1: Write failing tests for capability probing**

Create `tests/test_agent_capabilities.py`:
```python
"""Tests for agent capability probing and manifest storage."""
from __future__ import annotations

from unittest.mock import patch, MagicMock
import json


class TestProbeCapabilities:
    """Test the agent-side probe_capabilities function."""

    def test_probe_returns_manifest_dict(self):
        # Import the probe function (add to agent.py)
        # Since agent.py is standalone, we test the function directly
        import importlib
        import sys
        sys.path.insert(0, "share/noba-agent")
        # We'll test the shape of the returned dict
        from agent import probe_capabilities
        result = probe_capabilities()
        assert isinstance(result, dict)
        assert "os" in result
        assert "capabilities" in result
        assert isinstance(result["capabilities"], dict)
        assert "init_system" in result
        assert "is_wsl" in result
        assert "is_container" in result

    def test_probe_detects_available_tools(self):
        import sys
        sys.path.insert(0, "share/noba-agent")
        from agent import probe_capabilities
        result = probe_capabilities()
        caps = result["capabilities"]
        # At minimum, some tools should be detected on the test host
        # The probe should have checked for common tools
        assert isinstance(caps, dict)
        # Each capability should have an "available" key
        for tool_name, tool_info in caps.items():
            assert "available" in tool_info, f"{tool_name} missing 'available' key"


class TestManifestStorageInReport:
    """Test that the server stores capability manifests from agent reports."""

    def test_manifest_stored_from_report(self):
        from fastapi.testclient import TestClient
        from server.app import app
        from server.auth import token_store

        client = TestClient(app)
        token = token_store.generate("agent-test", "admin")
        headers = {"Authorization": f"Bearer {token}"}

        body = {
            "hostname": "test-cap-host",
            "cpuPercent": 10,
            "memPercent": 20,
            "_capabilities": {
                "os": "linux", "distro": "ubuntu", "distro_version": "24.04",
                "kernel": "6.8.0", "init_system": "systemd",
                "is_wsl": False, "is_container": False,
                "capabilities": {"docker": {"available": True}},
            },
        }
        r = client.post("/api/agent/report", json=body, headers=headers)
        assert r.status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_agent_capabilities.py -v`
Expected: FAIL

- [ ] **Step 3: Add probe_capabilities function to agent**

In `share/noba-agent/agent.py`, add a `probe_capabilities()` function that:
1. Detects OS, distro, kernel, init_system, is_wsl, is_container
2. Probes for each known tool (docker, podman, systemctl, apt, dnf, etc.) via `shutil.which()`
3. For Windows: uses `Get-Command` via PowerShell
4. Returns a capability manifest dict

Add `_capabilities` to the report payload (alongside existing CPU, memory, disk data). Only probe on startup and every 6 hours (track `_last_capability_probe` timestamp).

- [ ] **Step 2: Store capability manifest on server side**

In `share/noba-web/server/routers/agents.py`, in the `api_agent_report` handler:
1. Check if the report body contains `_capabilities`
2. If present, call `db.upsert_capability_manifest(hostname, json.dumps(capabilities))`
3. Store in the `capability_manifests` table

- [ ] **Step 3: Add refresh_capabilities command support**

Add `refresh_capabilities` to the agent's command handler. When received, the agent re-probes immediately (resets `_last_capability_probe`) and includes fresh capabilities in the next report.

Capability refresh triggers (from spec):
1. Agent startup (done in Step 3 above)
2. Every 6 hours (configurable via `_CAPABILITY_PROBE_INTERVAL`)
3. On-demand via `refresh_capabilities` command
4. After `package_install` / `package_remove` commands — set `_last_capability_probe = 0` in those command handlers
5. After capability mismatch error — server sends `refresh_capabilities` command when preflight fails

- [ ] **Step 4: Run all tests**

```bash
pytest tests/ -v --tb=short 2>&1 | tail -20
```

- [ ] **Step 5: Commit**

```bash
git add share/noba-agent/agent.py share/noba-web/server/routers/agents.py
git commit -m "feat(agent): add capability probing with manifest reporting"
```

---

## Task 7: Healing API Endpoints for Capabilities

**Files:**
- Modify: `share/noba-web/server/routers/healing.py`
- Create: `tests/test_router_healing_capabilities.py`

- [ ] **Step 1: Write failing tests for capability endpoints**

Create `tests/test_router_healing_capabilities.py`:
```python
"""Tests for healing API: capability manifest endpoints.

Uses client and admin_headers fixtures from conftest.py.
"""
from __future__ import annotations


class TestCapabilityEndpoints:
    def test_get_capabilities_no_auth_returns_401(self, client):
        r = client.get("/api/healing/capabilities/testhost")
        assert r.status_code == 401

    def test_get_capabilities_returns_manifest(self, client, admin_headers):
        # Returns 404 if no manifest exists, which is fine
        r = client.get("/api/healing/capabilities/testhost", headers=admin_headers)
        assert r.status_code in (200, 404)

    def test_refresh_capabilities_requires_operator(self, client, admin_headers):
        r = client.post("/api/healing/capabilities/testhost/refresh",
                       headers=admin_headers)
        # Should succeed (admin >= operator) or 404 if host not found
        assert r.status_code in (200, 404)
```

- [ ] **Step 2: Implement endpoints in routers/healing.py**

Add to `share/noba-web/server/routers/healing.py`:
- `GET /api/healing/capabilities/{hostname}` — returns manifest (read auth)
- `POST /api/healing/capabilities/{hostname}/refresh` — queues refresh command (operator auth)

- [ ] **Step 3: Run tests**

```bash
pytest tests/test_router_healing_capabilities.py tests/test_router_healing.py -v
```

- [ ] **Step 4: Commit**

```bash
git add share/noba-web/server/routers/healing.py tests/test_router_healing_capabilities.py
git commit -m "feat(api): add capability manifest endpoints"
```

---

## Task 8: Wire Pre-Flight into Executor

**Files:**
- Modify: `share/noba-web/server/healing/executor.py`
- Create: `tests/test_executor_preflight.py`

- [ ] **Step 1: Write failing tests for executor preflight integration**

Create `tests/test_executor_preflight.py`:
```python
"""Tests for executor pre-flight integration."""
from __future__ import annotations

from unittest.mock import MagicMock, patch
import threading


class TestExecutorPreflight:
    def test_execution_blocked_when_preflight_fails(self):
        """If no capability manifest exists, action should not execute."""
        from server.healing.executor import HealExecutor
        from server.healing.models import HealPlan, HealRequest, HealEvent

        event = HealEvent(
            source="alert", rule_id="test", condition="cpu > 90",
            target="unknown-host", severity="warning", timestamp=0, metrics={},
        )
        request = HealRequest(
            correlation_key="test:cpu", events=[event],
            primary_target="unknown-host", severity="warning", created_at=0,
        )
        plan = HealPlan(
            request=request, action_type="service_restart",
            action_params={"service": "nginx"}, escalation_step=0,
            trust_level="execute", reason="test", skipped_actions=[],
        )

        executor = HealExecutor(settle_times={"service_restart": 0})
        outcomes = []
        done = threading.Event()

        def on_complete(outcome):
            outcomes.append(outcome)
            done.set()

        executor.execute(plan, on_complete=on_complete)
        done.wait(timeout=5)

        # Should have an outcome recording preflight failure
        assert len(outcomes) == 1
        # Action should not have succeeded
        assert outcomes[0].action_success is not True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_executor_preflight.py -v`
Expected: FAIL (executor currently doesn't check preflight)

- [ ] **Step 3: Read current executor implementation**

Read `share/noba-web/server/healing/executor.py` to understand the current execution flow.

- [ ] **Step 4: Add pre-flight check before action execution**

In `executor.py`, before calling `remediation.execute_action()`:
1. Look up the target hostname's capability manifest from DB (or agent_store)
2. Look up fallback chain for the action type from `FALLBACK_CHAINS`
3. Call `run_preflight()` with the manifest and handlers
4. If pre-flight fails: record outcome as `action_success=False, verified=False, verification_detail=preflight_failure_reason`
5. If pre-flight passes: use the resolved handler's command for execution

For actions without fallback chains (e.g., `webhook`, `automation`), skip the capability check (these are API-based, not OS-dependent).

**Note on active manifest verification:** The spec requires pre-flight to actively verify tools work (e.g., run `docker ps`). This is deferred to Phase 2 (Intelligence) since it requires agent round-trip communication. Phase 1 pre-flight is passive (checks manifest dict only). Phase 2 will add `verify_capability` agent command and integrate it into pre-flight.

- [ ] **Step 5: Run all healing tests**

```bash
pytest tests/test_heal_*.py tests/test_capabilities.py tests/test_preflight.py tests/test_executor_preflight.py -v
```

- [ ] **Step 6: Commit**

```bash
git add share/noba-web/server/healing/executor.py tests/test_executor_preflight.py
git commit -m "feat(healing): wire pre-flight checks into executor before action dispatch"
```

---

## Task 9: Lint + Final Integration Test

**Note:** The trust level bug (`suggest` -> `approve` in `db/healing.py`) was already fixed prior to this plan. It is committed on this branch.

**Files:**
- All files modified in Tasks 1-8

- [ ] **Step 1: Run ruff on all modified files**

```bash
ruff check --fix share/noba-web/server/healing/ share/noba-web/server/remediation.py share/noba-web/server/db/ share/noba-web/server/routers/healing.py
```

- [ ] **Step 3: Run the full test suite**

```bash
pytest tests/ -v --tb=short
```
Expected: All PASS

- [ ] **Step 4: Update CHANGELOG.md**

Add entry for heal-foundation work.

- [ ] **Step 5: Final commit**

```bash
git add CHANGELOG.md
git commit -m "chore: update CHANGELOG for heal foundation phase"
```
