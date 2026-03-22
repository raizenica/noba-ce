# Self-Healing Pipeline

NOBA's self-healing pipeline automatically detects, diagnoses, and resolves infrastructure issues through a layered architecture.

## Overview

When an alert fires, instead of just notifying you, NOBA can automatically take corrective action — restarting services, scaling containers, flushing DNS, running scripts, and more. The pipeline ensures actions are **verified** (did the fix actually work?) and **graduated** (start cautious, earn trust over time).

## Pipeline Architecture

Events flow through six stages:

1. **Correlation** — Deduplicates rapid-fire alerts for the same target using an absorption window (default 60s)
2. **Planning** — Selects the best action from an escalation chain, skipping actions with low historical success rates
3. **Execution** — Runs the action asynchronously, waits for settle time, then re-evaluates the original condition
4. **Verification** — Confirms the issue is actually resolved, not just that the action succeeded
5. **Ledger** — Records every outcome for effectiveness tracking and suggestion generation
6. **Trust Governor** — Manages graduated trust levels with automatic promotion and circuit breaker protection

## Trust Levels

Each healing rule starts at the lowest trust level and earns promotion based on track record:

| Level | Behavior | Promotion Criteria |
|-------|----------|-------------------|
| **Notify** | Alert only, no action taken | 10+ triggers over 7 days |
| **Approve** | Queued for operator approval | 85%+ verified success rate over 10+ executions |
| **Execute** | Fully automatic | — |

### Circuit Breaker

If 3 consecutive heal attempts fail verification within 1 hour, the trust governor automatically demotes the rule back to **notify** and creates a suggestion for review.

## Healing Dashboard

Navigate to **Healing** in the sidebar to access:

### Ledger Tab
View recent heal outcomes with filtering by rule and target. Each entry shows:
- Action type and escalation step
- Whether the action succeeded and was verified
- Duration and trust level at time of execution

### Trust Tab
View and manage trust states for all rules. Admins can manually promote rules.

### Suggestions Tab
The system automatically generates suggestions:
- **Recurring issues** — targets healed 10+ times (investigate root cause)
- **Low effectiveness** — actions with less than 30% success rate
- **Trust promotions** — rules eligible for the next trust level

## Escalation Chains

Configure multi-step escalation in alert rules:

```yaml
alertRules:
  - id: cpu_high
    condition: "cpu_percent > 90"
    severity: warning
    action:
      type: restart_service
      target: nginx
    escalation_chain:
      - action: restart_service
        params: { service: nginx }
      - action: scale_container
        params: { container: nginx, mem_limit: "4g" }
      - action: run
        params: { command: "systemctl restart docker" }
```

If the first action doesn't resolve the condition, the pipeline automatically escalates to the next step.

## Supported Action Types

| Action | Risk | Description |
|--------|------|-------------|
| `restart_container` | medium | Restart a Docker container |
| `restart_service` | medium | Restart a systemd/Windows service |
| `clear_cache` | low | Clear system caches |
| `flush_dns` | low | Flush DNS resolver cache |
| `scale_container` | medium | Adjust container resource limits |
| `run_playbook` | high | Execute an Ansible playbook |
| `trigger_backup` | medium | Trigger a backup job |
| `failover_dns` | high | Switch DNS to failover target |
| `run` | medium | Execute a shell command |
| `webhook` | low | Fire an HTTP webhook |
| `automation` | medium | Trigger a stored automation |
| `agent_command` | medium | Send command to a remote agent |

## Agent-Side Healing

Agents with trust level **execute** can heal locally without waiting for the server. The server distributes a lightweight heal policy to each agent containing only low-risk actions (`restart_container`, `restart_service`, `clear_cache`, `flush_dns`).

Agents evaluate rules against their own metrics each collection cycle, execute trusted actions with cooldown protection, and report outcomes back to the server's ledger on the next heartbeat.

## API Endpoints

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/api/healing/ledger` | read | Recent outcomes |
| GET | `/api/healing/effectiveness` | read | Per-action success rates |
| GET | `/api/healing/suggestions` | read | Active suggestions |
| POST | `/api/healing/suggestions/{id}/dismiss` | operator | Dismiss a suggestion |
| GET | `/api/healing/trust` | read | Trust states |
| POST | `/api/healing/trust/{rule_id}/promote` | admin | Manual promotion |
