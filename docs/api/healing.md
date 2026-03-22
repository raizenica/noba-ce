# Healing API

API endpoints for the self-healing pipeline — ledger, trust states, and suggestions.

## Endpoints

### GET `/api/healing/ledger`

Returns recent heal outcomes.

**Auth:** Any authenticated user

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | int | 50 | Max results to return |
| `rule_id` | string | — | Filter by rule ID |
| `target` | string | — | Filter by target (hostname/container) |

**Response:** Array of outcome objects

```json
[
  {
    "id": 1,
    "correlation_key": "nginx:cpu_high",
    "rule_id": "cpu_high",
    "condition": "cpu_percent > 90",
    "target": "nginx",
    "action_type": "restart_container",
    "action_params": "{\"container\": \"nginx\"}",
    "escalation_step": 0,
    "action_success": 1,
    "verified": 1,
    "duration_s": 12.5,
    "trust_level": "execute",
    "source": "alert",
    "created_at": 1711100000
  }
]
```

### GET `/api/healing/effectiveness`

Returns success rate for a specific action/condition pair.

**Auth:** Any authenticated user

**Query Parameters (required):**
| Parameter | Type | Description |
|-----------|------|-------------|
| `action_type` | string | Action type (e.g., `restart_container`) |
| `condition` | string | Condition string (e.g., `cpu_percent > 90`) |
| `target` | string | Optional target filter |

**Response:**
```json
{
  "action_type": "restart_container",
  "condition": "cpu_percent > 90",
  "success_rate": 87.5
}
```

### GET `/api/healing/suggestions`

Returns active (non-dismissed) suggestions.

**Auth:** Any authenticated user

**Response:** Array of suggestion objects

```json
[
  {
    "id": 1,
    "category": "recurring_issue",
    "severity": "warning",
    "message": "Target 'nginx' healed 15 times for rule 'cpu_high'.",
    "rule_id": "cpu_high",
    "dismissed": 0,
    "created_at": 1711100000
  }
]
```

### POST `/api/healing/suggestions/{suggestion_id}/dismiss`

Dismiss a suggestion.

**Auth:** Operator or Admin

**Response:**
```json
{ "success": true }
```

### GET `/api/healing/trust`

Returns trust state for all rules.

**Auth:** Any authenticated user

**Response:** Array of trust state objects

```json
[
  {
    "rule_id": "cpu_high",
    "current_level": "approve",
    "ceiling": "execute",
    "promoted_at": 1711100000,
    "demoted_at": null,
    "promotion_count": 1,
    "demotion_count": 0,
    "last_evaluated": 1711100000
  }
]
```

### POST `/api/healing/trust/{rule_id}/promote`

Manually promote a rule's trust level.

**Auth:** Admin only

**Body:**
```json
{ "level": "approve" }
```

`level` must be `"approve"` or `"execute"`.

**Response:**
```json
{
  "success": true,
  "rule_id": "cpu_high",
  "new_level": "approve"
}
```
