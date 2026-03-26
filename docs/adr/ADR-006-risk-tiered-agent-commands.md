# ADR-006: Risk-Tiered Agent Commands (Low / Medium / High)

**Status:** Accepted
**Date:** 2026-02-15
**Deciders:** Raizen

---

## Context

The agent supports 42 command types spanning a wide risk spectrum — from reading a log file (harmless) to rebooting a machine (disruptive) to wiping a disk (destructive). All commands are dispatched by the server in response to operator actions or autonomous healing rules.

Early design allowed any operator to trigger any command. This created two problems:
1. **Accidental harm**: an operator troubleshooting a service could inadvertently trigger a reboot
2. **Healing autonomy**: the self-healing engine needed to execute remediation actions without human approval, but only for safe, reversible operations

A flat permission model (all-or-nothing) was too coarse. A per-command ACL would be maintenance-heavy.

## Decision

Classify every agent command into one of three risk tiers, enforced at two layers:

| Tier | Examples | Server enforcement | Healing autonomy |
|------|----------|--------------------|------------------|
| **Low** | `get_logs`, `service_status`, `list_processes`, `network_info` | Any operator | Fully autonomous |
| **Medium** | `service_restart`, `service_stop`, `kill_process`, `clear_cache` | Operator + confirmation | Autonomous with policy gate |
| **High** | `reboot`, `shutdown`, `disk_format`, `package_remove` | Admin only | Never autonomous |

The tier is encoded in `commands.py` as a metadata constant alongside the handler:

```python
COMMAND_REGISTRY = {
    "get_logs":        {"handler": _get_logs,        "risk": "low"},
    "service_restart": {"handler": _service_restart, "risk": "medium"},
    "reboot":          {"handler": _reboot,           "risk": "high"},
    ...
}
```

The server checks the tier before dispatching:
- **Low**: dispatch immediately to any operator
- **Medium**: require operator role + optional approval workflow
- **High**: require admin role; blocked entirely from healing engine

The self-healing engine's `HealRuntime` references these tiers when evaluating rules — it will only auto-execute low-tier commands and medium-tier commands explicitly whitelisted in the heal policy.

## Consequences

**Positive:**
- Clear, auditable contract for what healing can and cannot do autonomously
- Operators cannot accidentally trigger destructive commands
- Adding a new command requires a conscious tier assignment — the registry makes risk visible
- Tier appears in the capability manifest the agent reports on registration

**Negative:**
- Tier assignment is a judgment call — the line between medium and high is debatable
- No per-user override mechanism (intentional: simplicity over granularity)
- Operators with legitimate need for high-risk actions must escalate to admin

**Design note on approval_manager:**
An `approval_manager` module exists for potential future use but is intentionally unwired. The healing engine is designed for autonomy — adding an approval gate would negate its purpose for the common case (low/medium remediation). High-risk actions simply do not run autonomously.
