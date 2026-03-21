# Phase 1: Backend Decomposition — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decompose `routers/system.py` (3190 lines, 122 routes) into 8 focused domain router files and delete the original.

**Architecture:** Each new router file owns one domain, imports its own dependencies, and exposes an `APIRouter`. The `routers/__init__.py` consolidates all routers into a single `api_router` that `app.py` mounts. Every API URL stays identical — no frontend changes needed.

**Tech Stack:** Python 3.11+, FastAPI, SQLite WAL, psutil, httpx

**Spec:** `docs/superpowers/specs/2026-03-21-noba-v3-roadmap-design.md` (Phase 1 section)

---

## File Structure

### Files to Create

| File | Responsibility | Approx Lines |
|------|---------------|-------------|
| `share/noba-web/server/routers/agents.py` | Agent CRUD, report, WebSocket, commands, streams, deploy, file transfer, SLA | ~800 |
| `share/noba-web/server/routers/containers.py` | Docker/Podman control, inspect, stats, pull, compose, TrueNAS VM | ~220 |
| `share/noba-web/server/routers/monitoring.py` | Endpoint monitors CRUD, uptime dashboard, SLA summary, status page (public + admin), incident war room | ~500 |
| `share/noba-web/server/routers/infrastructure.py` | Network analysis, service map, K8s, Proxmox, disks, service control, terminal | ~380 |
| `share/noba-web/server/routers/security.py` | Security score, findings, history, scan, scan-all, record | ~160 |
| `share/noba-web/server/routers/intelligence.py` | AI/LLM endpoints, config drift/baselines, service dependencies, incidents | ~500 |
| `share/noba-web/server/routers/operations.py` | Recovery actions, journal viewer, system info/health, health-score, CPU governor, processes, backups, SMART, IaC export | ~420 |
| `share/noba-web/server/routers/dashboards.py` | Custom dashboard CRUD | ~100 |

### Files to Modify

| File | Change |
|------|--------|
| `share/noba-web/server/routers/__init__.py` | Import and register all 8 new routers, remove `system` import |

### Files to Delete

| File | Reason |
|------|--------|
| `share/noba-web/server/routers/system.py` | Fully replaced by 8 new files |

### Files Unchanged

- `share/noba-web/server/routers/admin.py` (880 lines — already clean)
- `share/noba-web/server/routers/auth.py` (458 lines)
- `share/noba-web/server/routers/automations.py` (684 lines)
- `share/noba-web/server/routers/integrations.py` (366 lines)
- `share/noba-web/server/routers/stats.py` (360 lines)
- `share/noba-web/server/agent_store.py` — shared agent state (untouched)
- `share/noba-web/server/deps.py` — auth dependencies (untouched)
- Most test files (they test via DB/mocks, not direct router imports)

### Test Files to Modify

| File | Change |
|------|--------|
| `tests/test_agent_websocket.py` | Change `from server.routers.system import _validate_agent_key` → `from server.routers.agents import _validate_agent_key` |
| `tests/test_agent_file_transfer.py` | Change `patch("server.routers.system.read_yaml_settings"` → `patch("server.routers.agents.read_yaml_settings"` (and any other `server.routers.system` patch targets) |

---

## Domain-to-Route Mapping

This is the definitive assignment of every route in `system.py` to its target file. **Reference this when extracting routes.**

### `agents.py` — 24 routes + 2 helpers

```
_validate_agent_key()                          helper — shared by report, WS, update, install-script, file-upload, file-download
POST   /api/agent/report                       L1068  api_agent_report
WS     /api/agent/ws                           L1181  agent_websocket
GET    /api/agents/{hostname}/stream/{cmd_id}  L1296  api_agent_stream
GET    /api/agents                              L1328  api_agents
GET    /api/agents/command-history              L1344  api_command_history
GET    /api/agents/{hostname}                   L1352  api_agent_detail
POST   /api/agents/bulk-command                 L1370  api_bulk_command
POST   /api/agents/{hostname}/command           L1406  api_agent_command
POST   /api/agents/{hostname}/uninstall         L1460  api_agent_uninstall
GET    /api/agents/{hostname}/results           L1474  api_agent_results
GET    /api/agents/{hostname}/history           L1481  api_agent_history
GET    /api/agents/{hostname}/network-stats     L1492  api_agent_network_stats
POST   /api/agents/{hostname}/stream-logs       L1573  api_agent_stream_logs
DELETE /api/agents/{hostname}/stream-logs/{id}  L1596  api_agent_stop_stream
GET    /api/agents/{hostname}/streams           L1617  api_agent_active_streams
GET    /api/sla/summary                         L1625  api_sla_summary
GET    /api/agent/update                        L1652  api_agent_update
GET    /api/agent/install-script                L1668  api_agent_install_script
POST   /api/agents/deploy                       L1729  api_agent_deploy
POST   /api/agent/file-upload                   L1829  api_agent_file_upload
GET    /api/agent/file-download/{transfer_id}   L1918  api_agent_file_download
POST   /api/agents/{hostname}/transfer          L1944  api_agent_transfer
_ws_logger                                      module-level logger for WS
_WEB_DIR                                        needed for agent file path
```

### `containers.py` — 8 routes

```
POST   /api/container-control                   L134   api_container_control
GET    /api/containers/{name}/logs              L162   api_container_logs
GET    /api/containers/{name}/inspect           L182   api_container_inspect
GET    /api/containers/stats                    L227   api_container_stats
POST   /api/containers/{name}/pull              L258   api_container_pull
GET    /api/compose/projects                    L286   api_compose_projects
POST   /api/compose/{project}/{action}          L298   api_compose_action
POST   /api/truenas/vm                          L317   api_truenas_vm
```

### `monitoring.py` — 17 routes

```
GET    /api/endpoints                            L2353  api_list_endpoints
POST   /api/endpoints                            L2359  api_create_endpoint
PUT    /api/endpoints/{monitor_id}               L2393  api_update_endpoint
DELETE /api/endpoints/{monitor_id}               L2428  api_delete_endpoint
POST   /api/endpoints/{monitor_id}/check         L2440  api_check_endpoint_now
GET    /api/uptime                               L489   api_uptime_dashboard
GET    /status                                   L2087  public_status_page
GET    /api/status/public                        L2093  api_public_status
GET    /api/status/incidents                     L2173  api_public_status_incidents
POST   /api/status/components                    L2184  api_create_status_component
PUT    /api/status/components/{comp_id}          L2204  api_update_status_component
DELETE /api/status/components/{comp_id}          L2219  api_delete_status_component
GET    /api/status/components                    L2230  api_list_status_components
POST   /api/status/incidents/create              L2236  api_create_status_incident
POST   /api/status/incidents/{id}/update         L2257  api_add_status_update
PUT    /api/status/incidents/{id}/resolve        L2277  api_resolve_status_incident
GET    /api/health-score                         L701   api_health_score
```

### `infrastructure.py` — 14 routes + 1 helper

```
POST   /api/service-control                      L352   api_service_control
GET    /api/network/connections                   L384   api_network_connections
GET    /api/network/ports                         L390   api_network_ports
GET    /api/network/interfaces                    L396   api_network_interfaces
GET    /api/services/map                          L419   api_service_map
GET    /api/disks/prediction                      L470   api_disk_prediction
GET    /api/network/devices                       L2024  api_network_devices
POST   /api/network/discover/{hostname}           L2030  api_network_discover
DELETE /api/network/devices/{device_id}           L2074  api_delete_network_device
GET    /api/k8s/namespaces                        L762   api_k8s_namespaces
GET    /api/k8s/pods                              L783   api_k8s_pods
GET    /api/k8s/pods/{ns}/{name}/logs             L826   api_k8s_pod_logs
GET    /api/k8s/deployments                       L848   api_k8s_deployments
POST   /api/k8s/deployments/{ns}/{name}/scale     L875   api_k8s_scale
GET    /api/proxmox/nodes/{node}/vms              L911   api_pmx_node_vms
GET    /api/proxmox/nodes/{node}/vms/{id}/snaps   L941   api_pmx_snapshots
POST   /api/proxmox/nodes/{node}/vms/{id}/snap    L962   api_pmx_create_snapshot
GET    /api/proxmox/nodes/{node}/vms/{id}/console L989   api_pmx_console_url
WS     /api/terminal                              L1002  ws_terminal
_pmx_headers()                                    helper for Proxmox auth
```

### `security.py` — 6 routes

```
GET    /api/security/score                       L2955  api_security_score
GET    /api/security/findings                    L2961  api_security_findings
GET    /api/security/history                     L2970  api_security_history
POST   /api/security/scan/{hostname}             L2978  api_security_scan
POST   /api/security/scan-all                    L3019  api_security_scan_all
POST   /api/security/record                      L3066  api_security_record
```

### `intelligence.py` — 16 routes + 2 helpers

```
GET    /api/incidents                            L2008  api_incidents
POST   /api/incidents/{id}/resolve               L2014  api_resolve_incident
GET    /api/incidents/{id}/messages               L2289  api_get_incident_messages
POST   /api/incidents/{id}/messages               L2299  api_post_incident_message
PUT    /api/incidents/{id}/assign                 L2322  api_assign_incident
GET    /api/dependencies                          L2543  api_list_dependencies
POST   /api/dependencies                          L2583  api_create_dependency
DELETE /api/dependencies/{dep_id}                 L2606  api_delete_dependency
GET    /api/dependencies/impact/{service}         L2618  api_impact_analysis
POST   /api/dependencies/discover/{hostname}      L2625  api_discover_services
GET    /api/baselines                             L2653  api_list_baselines
POST   /api/baselines                             L2659  api_create_baseline
DELETE /api/baselines/{baseline_id}               L2680  api_delete_baseline
POST   /api/baselines/{id}/set-from/{hostname}    L2693  api_baseline_set_from_agent
POST   /api/baselines/check                       L2757  api_trigger_drift_check
GET    /api/baselines/{baseline_id}/results       L2771  api_baseline_results
GET    /api/ai/status                             L2803  api_ai_status
POST   /api/ai/chat                               L2814  api_ai_chat
POST   /api/ai/analyze-alert/{alert_id}           L2846  api_ai_analyze_alert
POST   /api/ai/analyze-logs                       L2884  api_ai_analyze_logs
POST   /api/ai/summarize-incident/{incident_id}   L2915  api_ai_summarize_incident
POST   /api/ai/test                               L3174  api_ai_test
_get_llm_client()                                 helper
_build_ai_context()                               helper
```

### `operations.py` — 11 routes

```
POST   /api/recovery/tailscale-reconnect         L52    api_recovery_tailscale
POST   /api/recovery/dns-flush                   L67    api_recovery_dns
POST   /api/recovery/service-restart             L83    api_recovery_service
GET    /api/sites/sync-status                    L104   api_sync_status
GET    /api/smart                                L128   api_smart
GET    /api/journal                              L528   api_journal
GET    /api/journal/units                        L561   api_journal_units
GET    /api/system/info                          L580   api_system_info
GET    /api/system/health                        L616   api_system_health
POST   /api/system/cpu-governor                  L712   api_cpu_governor
GET    /api/processes/history                    L731   api_process_history
GET    /api/processes/current                    L738   api_processes_current
GET    /api/backup/verifications                 L3081  api_backup_verifications
POST   /api/backup/verify                        L3089  api_backup_verify
GET    /api/backup/321-status                    L3146  api_backup_321_status
PUT    /api/backup/321-status                    L3152  api_backup_321_update
GET    /api/export/ansible                       L1016  api_export_ansible
GET    /api/export/docker-compose                L1028  api_export_docker_compose
GET    /api/export/shell                         L1042  api_export_shell
```

### `dashboards.py` — 4 routes

```
GET    /api/dashboards                           L2457  api_list_dashboards
POST   /api/dashboards                           L2464  api_create_dashboard
PUT    /api/dashboards/{dashboard_id}            L2491  api_update_dashboard
DELETE /api/dashboards/{dashboard_id}            L2525  api_delete_dashboard
```

---

## Import Reference Per Router

Each new file needs specific imports. This table prevents missing imports.

### Common imports (all files)

```python
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from ..deps import _client_ip, _get_auth, _read_body, _require_admin, _require_operator, db
```

### Per-file additional imports

| File | Extra Imports |
|------|---------------|
| `agents.py` | `hashlib, json, os, re, secrets, time` from stdlib; `Response, WebSocket, WebSocketDisconnect` from fastapi; `FileResponse` from fastapi.responses; `from ..agent_config import RISK_LEVELS, check_role_permission, get_agent_capabilities, validate_command_params`; `from ..agent_store import _agent_cmd_lock, _agent_cmd_results, _agent_commands, _agent_data, _agent_data_lock, _AGENT_MAX_AGE, _agent_stream_lines, _agent_stream_lines_lock, _STREAM_LINES_MAX, _agent_streams, _agent_streams_lock, _agent_websockets, _agent_ws_lock, _CHUNK_SIZE, _MAX_TRANSFER_SIZE, _TRANSFER_DIR, _transfer_lock, _transfers`; `from ..auth import token_store`; `from ..deps import _safe_int`; `from ..yaml_config import read_yaml_settings` |
| `containers.py` | `json, os, re, subprocess` from stdlib; `from ..config import ALLOWED_ACTIONS`; `from ..metrics import bust_container_cache, strip_ansi`; `from ..runner import job_runner`; `from ..yaml_config import read_yaml_settings` |
| `monitoring.py` | `time` from stdlib; `FileResponse` from fastapi.responses; `from .. import deps as _deps`; `from ..deps import _safe_int`; `from ..yaml_config import read_yaml_settings`; `from pathlib import Path` |
| `infrastructure.py` | `json, os, re, secrets, subprocess, time` from stdlib; `WebSocket, WebSocketDisconnect` from fastapi; `PlainTextResponse` from fastapi.responses; `from .. import deps as _deps`; `from ..agent_config import RISK_LEVELS, check_role_permission`; `from ..agent_store import _agent_cmd_lock, _agent_commands, _agent_data, _agent_data_lock, _AGENT_MAX_AGE, _agent_websockets, _agent_ws_lock`; `from ..auth import token_store`; `from ..config import ALLOWED_ACTIONS`; `from ..metrics import get_listening_ports, get_network_connections, strip_ansi, validate_service_name`; `from ..yaml_config import read_yaml_settings` |
| `security.py` | `secrets, time` from stdlib; `from ..agent_config import RISK_LEVELS, check_role_permission`; `from ..agent_store import _agent_cmd_lock, _agent_commands, _agent_data, _agent_data_lock, _AGENT_MAX_AGE, _agent_websockets, _agent_ws_lock`; `from ..deps import _safe_int` |
| `intelligence.py` | `secrets, threading, time` from stdlib; `from ..agent_store import _agent_cmd_lock, _agent_cmd_results, _agent_commands, _agent_data, _agent_data_lock, _AGENT_MAX_AGE, _agent_websockets, _agent_ws_lock`; `from ..deps import _safe_int`; `from ..yaml_config import read_yaml_settings` |
| `operations.py` | `os, re, subprocess, time` from stdlib; `from pathlib import Path`; `PlainTextResponse` from fastapi.responses; `from .. import deps as _deps`; `from ..agent_store import _agent_cmd_lock, _agent_commands, _agent_data, _agent_data_lock, _AGENT_MAX_AGE, _agent_websockets, _agent_ws_lock`; `from ..agent_config import RISK_LEVELS, check_role_permission`; `from ..config import VERSION`; `from ..deps import _int_param, _safe_int`; `from ..metrics import collect_smart, strip_ansi`; `from ..yaml_config import read_yaml_settings` |
| `dashboards.py` | `json` from stdlib |

---

## Tasks

### Task 1: Create `containers.py`

The simplest domain — 8 routes, no agent store dependencies, mostly subprocess calls.

**Files:**
- Create: `share/noba-web/server/routers/containers.py`

- [ ] **Step 1: Create the router file with all 8 routes**

Copy lines 133–349 from `system.py` (container-control through TrueNAS VM) into a new file with proper imports:

```python
"""Noba – Container and VM management endpoints."""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess

from fastapi import APIRouter, Depends, HTTPException, Request

from ..config import ALLOWED_ACTIONS
from ..deps import _client_ip, _get_auth, _read_body, _require_admin, _require_operator, db
from ..metrics import bust_container_cache, strip_ansi
from ..runner import job_runner
from ..yaml_config import read_yaml_settings

logger = logging.getLogger("noba")

router = APIRouter(tags=["containers"])
```

Then paste all 8 route functions verbatim from `system.py`:
- `api_container_control` (L134–158)
- `api_container_logs` (L162–179)
- `api_container_inspect` (L182–224)
- `api_container_stats` (L227–255)
- `api_container_pull` (L258–282)
- `api_compose_projects` (L286–295)
- `api_compose_action` (L298–314)
- `api_truenas_vm` (L317–348)

- [ ] **Step 2: Verify syntax**

Run: `ruff check share/noba-web/server/routers/containers.py`
Expected: All checks passed!

- [ ] **Step 3: Run existing tests**

Run: `pytest tests/ -v --tb=short 2>&1 | tail -5`
Expected: 783 passed (no regressions — `system.py` still exists, we haven't touched `__init__.py` yet)

- [ ] **Step 4: Commit**

```bash
git add share/noba-web/server/routers/containers.py
git commit -m "feat(v3): extract containers router from system.py (8 routes)"
```

---

### Task 2: Create `dashboards.py`

The smallest domain — 4 routes, no subprocess, no agent store.

**Files:**
- Create: `share/noba-web/server/routers/dashboards.py`

- [ ] **Step 1: Create the router file with all 4 routes**

```python
"""Noba – Custom dashboard endpoints."""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from ..deps import _client_ip, _get_auth, _require_admin, _read_body, db

logger = logging.getLogger("noba")

router = APIRouter(tags=["dashboards"])
```

Then paste all 4 route functions verbatim from `system.py`:
- `api_list_dashboards` (L2457–2461)
- `api_create_dashboard` (L2464–2488)
- `api_update_dashboard` (L2491–2522)
- `api_delete_dashboard` (L2525–2539)

- [ ] **Step 2: Verify syntax**

Run: `ruff check share/noba-web/server/routers/dashboards.py`
Expected: All checks passed!

- [ ] **Step 3: Run existing tests**

Run: `pytest tests/ -v --tb=short 2>&1 | tail -5`
Expected: 783 passed

- [ ] **Step 4: Commit**

```bash
git add share/noba-web/server/routers/dashboards.py
git commit -m "feat(v3): extract dashboards router from system.py (4 routes)"
```

---

### Task 3: Create `security.py`

6 routes focused on security posture scoring and agent scanning. Uses agent_store for scan dispatch.

**Files:**
- Create: `share/noba-web/server/routers/security.py`

- [ ] **Step 1: Create the router file with all 6 routes**

```python
"""Noba – Security posture scoring and scanning endpoints."""
from __future__ import annotations

import logging
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException, Request

from ..agent_config import RISK_LEVELS, check_role_permission
from ..agent_store import (
    _agent_cmd_lock, _agent_commands,
    _agent_data, _agent_data_lock, _AGENT_MAX_AGE,
    _agent_websockets, _agent_ws_lock,
)
from ..deps import _client_ip, _get_auth, _read_body, _require_operator, _safe_int, db

logger = logging.getLogger("noba")

router = APIRouter(tags=["security"])
```

Then paste all 6 route functions verbatim from `system.py`:
- `api_security_score` (L2955–2958)
- `api_security_findings` (L2961–2967)
- `api_security_history` (L2970–2975)
- `api_security_scan` (L2978–3016)
- `api_security_scan_all` (L3019–3063)
- `api_security_record` (L3066–3076)

- [ ] **Step 2: Verify syntax**

Run: `ruff check share/noba-web/server/routers/security.py`
Expected: All checks passed!

- [ ] **Step 3: Run existing tests**

Run: `pytest tests/ -v --tb=short 2>&1 | tail -5`
Expected: 783 passed

- [ ] **Step 4: Commit**

```bash
git add share/noba-web/server/routers/security.py
git commit -m "feat(v3): extract security router from system.py (6 routes)"
```

---

### Task 4: Create `operations.py`

19 routes covering recovery, journal, system info, health, processes, backups, SMART, IaC export. This is the "everything that operates on the local system" file.

**Files:**
- Create: `share/noba-web/server/routers/operations.py`

- [ ] **Step 1: Create the router file with all 19 routes**

```python
"""Noba – System operations, recovery, journal, backups, and IaC export endpoints."""
from __future__ import annotations

import logging
import os
import re
import secrets
import subprocess
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse

from .. import deps as _deps
from ..agent_config import RISK_LEVELS, check_role_permission
from ..agent_store import (
    _agent_cmd_lock, _agent_commands,
    _agent_data, _agent_data_lock, _AGENT_MAX_AGE,
    _agent_websockets, _agent_ws_lock,
)
from ..config import VERSION
from ..deps import (
    _client_ip, _get_auth, _int_param, _read_body,
    _require_admin, _require_operator, _safe_int, db,
)
from ..metrics import collect_smart, strip_ansi
from ..yaml_config import read_yaml_settings

logger = logging.getLogger("noba")

router = APIRouter(tags=["operations"])
```

Then paste these route functions verbatim from `system.py`:
- `api_recovery_tailscale` (L52–64)
- `api_recovery_dns` (L67–80)
- `api_recovery_service` (L83–100)
- `api_sync_status` (L104–124)
- `api_smart` (L128–130)
- `api_journal` (L528–558)
- `api_journal_units` (L561–576)
- `api_system_info` (L580–613) — note lazy imports: `platform`, `psutil`, `from ..metrics import get_cpu_governor`
- `api_system_health` (L616–697)
- `api_cpu_governor` (L712–727)
- `api_process_history` (L731–735) — lazy import: `from ..metrics import get_process_history`
- `api_processes_current` (L738–760) — lazy import: `psutil`
- `api_backup_verifications` (L3081–3086)
- `api_backup_verify` (L3089–3143)
- `api_backup_321_status` (L3146–3149)
- `api_backup_321_update` (L3152–3171)
- `api_export_ansible` (L1016–1025) — lazy import: `from ..iac_export import generate_ansible`
- `api_export_docker_compose` (L1028–1039) — lazy import: `from ..iac_export import generate_docker_compose`
- `api_export_shell` (L1042–1053) — lazy import: `from ..iac_export import generate_shell_script`

**Important:** The IaC export routes pass `_agent_data` and `_agent_data_lock` to the generator functions. Make sure these are imported from `agent_store`.

- [ ] **Step 2: Verify syntax**

Run: `ruff check share/noba-web/server/routers/operations.py`
Expected: All checks passed!

- [ ] **Step 3: Run existing tests**

Run: `pytest tests/ -v --tb=short 2>&1 | tail -5`
Expected: 783 passed

- [ ] **Step 4: Commit**

```bash
git add share/noba-web/server/routers/operations.py
git commit -m "feat(v3): extract operations router from system.py (19 routes)"
```

---

### Task 5: Create `monitoring.py`

17 routes: endpoint monitors, uptime dashboard, status page (public + admin), incident war room, health-score.

**Files:**
- Create: `share/noba-web/server/routers/monitoring.py`

- [ ] **Step 1: Create the router file with all 17 routes**

```python
"""Noba – Endpoint monitoring, uptime, status page, and health score endpoints."""
from __future__ import annotations

import logging
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from .. import deps as _deps
from ..agent_store import _agent_data, _agent_data_lock
from ..deps import (
    _client_ip, _get_auth, _read_body,
    _require_admin, _require_operator, _safe_int, db,
)
from ..yaml_config import read_yaml_settings

logger = logging.getLogger("noba")

_WEB_DIR = Path(__file__).resolve().parent.parent.parent  # share/noba-web/

router = APIRouter(tags=["monitoring"])
```

Then paste these route functions verbatim from `system.py`:
- `api_list_endpoints` (L2353–2356)
- `api_create_endpoint` (L2359–2390)
- `api_update_endpoint` (L2393–2425)
- `api_delete_endpoint` (L2428–2437)
- `api_check_endpoint_now` (L2440–2453) — lazy import: `from ..scheduler import _run_endpoint_check`
- `api_uptime_dashboard` (L489–524)
- `public_status_page` (L2087–2090) — uses `_WEB_DIR`
- `api_public_status` (L2093–2170)
- `api_public_status_incidents` (L2173–2180)
- `api_create_status_component` (L2184–2201)
- `api_update_status_component` (L2204–2216)
- `api_delete_status_component` (L2219–2227)
- `api_list_status_components` (L2230–2233)
- `api_create_status_incident` (L2236–2254)
- `api_add_status_update` (L2257–2274)
- `api_resolve_status_incident` (L2277–2285)
- `api_health_score` (L701–709) — lazy import: `from ..health_score import compute_health_score`

- [ ] **Step 2: Verify syntax**

Run: `ruff check share/noba-web/server/routers/monitoring.py`
Expected: All checks passed!

- [ ] **Step 3: Run existing tests**

Run: `pytest tests/ -v --tb=short 2>&1 | tail -5`
Expected: 783 passed

- [ ] **Step 4: Commit**

```bash
git add share/noba-web/server/routers/monitoring.py
git commit -m "feat(v3): extract monitoring router from system.py (17 routes)"
```

---

### Task 6: Create `infrastructure.py`

19 routes: service control, network, K8s, Proxmox, terminal, disks, network discovery.

**Files:**
- Create: `share/noba-web/server/routers/infrastructure.py`

- [ ] **Step 1: Create the router file with all routes + 1 helper**

```python
"""Noba – Infrastructure management: network, K8s, Proxmox, services, terminal."""
from __future__ import annotations

import json
import logging
import os
import re
import secrets
import subprocess
import time

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket
from fastapi.responses import PlainTextResponse

from .. import deps as _deps
from ..agent_config import RISK_LEVELS, check_role_permission
from ..agent_store import (
    _agent_cmd_lock, _agent_commands,
    _agent_data, _agent_data_lock, _AGENT_MAX_AGE,
    _agent_websockets, _agent_ws_lock,
)
from ..auth import token_store
from ..config import ALLOWED_ACTIONS
from ..deps import (
    _client_ip, _get_auth, _int_param, _read_body,
    _require_admin, _require_operator, _safe_int, db,
)
from ..metrics import get_listening_ports, get_network_connections, strip_ansi, validate_service_name
from ..yaml_config import read_yaml_settings

logger = logging.getLogger("noba")

router = APIRouter(tags=["infrastructure"])
```

Then paste these route functions verbatim from `system.py`:
- `api_service_control` (L352–380)
- `api_network_connections` (L384–387)
- `api_network_ports` (L390–393)
- `api_network_interfaces` (L396–415) — lazy import: `psutil`
- `api_service_map` (L419–466)
- `api_disk_prediction` (L470–485)
- `api_network_devices` (L2024–2027)
- `api_network_discover` (L2030–2071)
- `api_delete_network_device` (L2074–2083)
- `api_k8s_namespaces` (L762–782)
- `api_k8s_pods` (L783–825)
- `api_k8s_pod_logs` (L826–847)
- `api_k8s_deployments` (L848–874)
- `api_k8s_scale` (L875–900)
- `_pmx_headers` helper (L903–910)
- `api_pmx_node_vms` (L911–940)
- `api_pmx_snapshots` (L941–961)
- `api_pmx_create_snapshot` (L962–1000)
- `api_pmx_console_url` (L989–1000)
- `ws_terminal` (L1002–1011) — lazy import: `from ..terminal import terminal_handler`

- [ ] **Step 2: Verify syntax**

Run: `ruff check share/noba-web/server/routers/infrastructure.py`
Expected: All checks passed!

- [ ] **Step 3: Run existing tests**

Run: `pytest tests/ -v --tb=short 2>&1 | tail -5`
Expected: 783 passed

- [ ] **Step 4: Commit**

```bash
git add share/noba-web/server/routers/infrastructure.py
git commit -m "feat(v3): extract infrastructure router from system.py (19 routes)"
```

---

### Task 7: Create `intelligence.py`

22 routes: incidents, service dependencies, config drift/baselines, AI/LLM endpoints. The most import-heavy domain due to agent store usage + LLM lazy imports.

**Files:**
- Create: `share/noba-web/server/routers/intelligence.py`

- [ ] **Step 1: Create the router file with all routes + 2 helpers**

```python
"""Noba – AI ops, incident management, service dependencies, and config drift endpoints."""
from __future__ import annotations

import logging
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException, Request

from ..agent_store import (
    _agent_cmd_lock, _agent_cmd_results, _agent_commands,
    _agent_data, _agent_data_lock, _AGENT_MAX_AGE,
    _agent_websockets, _agent_ws_lock,
)
from ..deps import (
    _client_ip, _get_auth, _read_body,
    _require_admin, _require_operator, _safe_int, db,
)
from ..yaml_config import read_yaml_settings

logger = logging.getLogger("noba")

router = APIRouter(tags=["intelligence"])
```

Then paste these helpers and route functions verbatim from `system.py`:

**Helpers:**
- `_get_llm_client()` (L2786–2792) — lazy import: `from ..llm import LLMClient`
- `_build_ai_context()` (L2795–2800) — lazy import: `from ..llm import build_ops_context`

**Incident routes:**
- `api_incidents` (L2008–2011)
- `api_resolve_incident` (L2014–2019)

**Incident War Room routes:**
- `api_get_incident_messages` (L2289–2296)
- `api_post_incident_message` (L2299–2320)
- `api_assign_incident` (L2322–2349)

**Service dependency routes:**
- `api_list_dependencies` (L2543–2580)
- `api_create_dependency` (L2583–2603)
- `api_delete_dependency` (L2606–2615)
- `api_impact_analysis` (L2618–2622)
- `api_discover_services` (L2625–2649)

**Config drift / baseline routes:**
- `api_list_baselines` (L2653–2656)
- `api_create_baseline` (L2659–2677)
- `api_delete_baseline` (L2680–2690)
- `api_baseline_set_from_agent` (L2693–2754) — lazy import: `asyncio`
- `api_trigger_drift_check` (L2757–2768) — lazy imports: `from ..scheduler import drift_checker`, `threading`
- `api_baseline_results` (L2771–2781)

**AI/LLM routes:**
- `api_ai_status` (L2803–2811)
- `api_ai_chat` (L2814–2843) — lazy import: `from ..llm import extract_actions`
- `api_ai_analyze_alert` (L2846–2881) — lazy import: `from ..llm import extract_actions`
- `api_ai_analyze_logs` (L2884–2912) — lazy import: `from ..llm import extract_actions`
- `api_ai_summarize_incident` (L2915–2950) — lazy import: `from ..llm import extract_actions`
- `api_ai_test` (L3174–3190)

- [ ] **Step 2: Verify syntax**

Run: `ruff check share/noba-web/server/routers/intelligence.py`
Expected: All checks passed!

- [ ] **Step 3: Run existing tests**

Run: `pytest tests/ -v --tb=short 2>&1 | tail -5`
Expected: 783 passed

- [ ] **Step 4: Commit**

```bash
git add share/noba-web/server/routers/intelligence.py
git commit -m "feat(v3): extract intelligence router from system.py (22 routes)"
```

---

### Task 8: Create `agents.py`

The largest extraction — 24 routes + helpers. Agent report, WebSocket, commands, streams, deploy, file transfer, SLA.

**Files:**
- Create: `share/noba-web/server/routers/agents.py`

- [ ] **Step 1: Create the router file with all routes + helpers**

```python
"""Noba – Agent management: CRUD, commands, WebSocket, deploy, file transfer."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import secrets
import subprocess
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from ..agent_config import (
    RISK_LEVELS, check_role_permission, get_agent_capabilities,
    validate_command_params,
)
from ..agent_store import (
    _agent_cmd_lock, _agent_cmd_results, _agent_commands,
    _agent_data, _agent_data_lock, _AGENT_MAX_AGE,
    _agent_stream_lines, _agent_stream_lines_lock, _STREAM_LINES_MAX,
    _agent_streams, _agent_streams_lock,
    _agent_websockets, _agent_ws_lock,
    _CHUNK_SIZE, _MAX_TRANSFER_SIZE, _TRANSFER_DIR,
    _transfer_lock, _transfers,
)
from ..auth import token_store
from ..deps import (
    _client_ip, _get_auth, _read_body,
    _require_admin, _require_operator, _safe_int, db,
)
from ..yaml_config import read_yaml_settings

logger = logging.getLogger("noba")
_ws_logger = logging.getLogger("noba.agent.ws")

_WEB_DIR = Path(__file__).resolve().parent.parent.parent  # share/noba-web/

router = APIRouter(tags=["agents"])
```

Then paste these helpers and route functions verbatim from `system.py`:

**Helpers:**
- `_validate_agent_key()` (L1058–1064)

**Agent core:**
- `api_agent_report` (L1068–1173)
- `agent_websocket` (L1181–1295)
- `api_agent_stream` (L1296–1327)
- `api_agents` (L1328–1343)
- `api_command_history` (L1344–1351)
- `api_agent_detail` (L1352–1369)
- `api_bulk_command` (L1370–1405)
- `api_agent_command` (L1406–1459)
- `api_agent_uninstall` (L1460–1473)
- `api_agent_results` (L1474–1480)
- `api_agent_history` (L1481–1489)
- `api_agent_network_stats` (L1492–1570)

**Agent streaming:**
- `api_agent_stream_logs` (L1573–1595)
- `api_agent_stop_stream` (L1596–1616)
- `api_agent_active_streams` (L1617–1624)

**SLA:**
- `api_sla_summary` (L1625–1649)

**Agent update/deploy:**
- `api_agent_update` (L1652–1665)
- `api_agent_install_script` (L1668–1726)
- `api_agent_deploy` (L1729–1825)

**File transfer:**
- `api_agent_file_upload` (L1829–1915)
- `api_agent_file_download` (L1918–1941)
- `api_agent_transfer` (L1944–2004)

- [ ] **Step 2: Verify syntax**

Run: `ruff check share/noba-web/server/routers/agents.py`
Expected: All checks passed!

- [ ] **Step 3: Run existing tests**

Run: `pytest tests/ -v --tb=short 2>&1 | tail -5`
Expected: 783 passed

- [ ] **Step 4: Commit**

```bash
git add share/noba-web/server/routers/agents.py
git commit -m "feat(v3): extract agents router from system.py (24 routes)"
```

---

### Task 9: Wire up `__init__.py` and delete `system.py`

The switchover: replace the single `system_router` import with 8 new router imports. Then delete `system.py`.

**Files:**
- Modify: `share/noba-web/server/routers/__init__.py`
- Delete: `share/noba-web/server/routers/system.py`

- [ ] **Step 1: Update `__init__.py`**

Replace the entire file with:

```python
"""Noba – API router package."""
from __future__ import annotations

from fastapi import APIRouter

from .admin import router as admin_router
from .agents import router as agents_router
from .auth import router as auth_router
from .automations import router as automations_router
from .containers import router as containers_router
from .dashboards import router as dashboards_router
from .infrastructure import router as infrastructure_router
from .integrations import router as integrations_router
from .intelligence import router as intelligence_router
from .monitoring import router as monitoring_router
from .operations import router as operations_router
from .security import router as security_router
from .stats import router as stats_router

api_router = APIRouter()
api_router.include_router(stats_router)
api_router.include_router(auth_router)
api_router.include_router(admin_router)
api_router.include_router(automations_router)
api_router.include_router(integrations_router)
api_router.include_router(agents_router)
api_router.include_router(containers_router)
api_router.include_router(monitoring_router)
api_router.include_router(infrastructure_router)
api_router.include_router(security_router)
api_router.include_router(intelligence_router)
api_router.include_router(operations_router)
api_router.include_router(dashboards_router)
```

- [ ] **Step 2: Delete `system.py`**

```bash
git rm share/noba-web/server/routers/system.py
```

- [ ] **Step 3: Update test imports that referenced `system.py`**

Two test files import directly from `server.routers.system`. Update them to point at the new modules:

**`tests/test_agent_websocket.py`:** Replace all occurrences of `server.routers.system` with `server.routers.agents`:
```
server.routers.system import _validate_agent_key  →  server.routers.agents import _validate_agent_key
patch("server.routers.system.  →  patch("server.routers.agents.
```

**`tests/test_agent_file_transfer.py`:** Replace all occurrences of `server.routers.system` with `server.routers.agents`:
```
patch("server.routers.system.  →  patch("server.routers.agents.
```

Run: `grep -rn 'routers\.system' tests/`
Expected: No matches (all references updated)

- [ ] **Step 4: Verify no import errors — start the app**

Run: `cd /home/raizen/noba && python -c "import sys; sys.path.insert(0, 'share/noba-web'); from server.routers import api_router; print(f'Routes: {len(api_router.routes)}')" 2>&1`
Expected: No import errors, route count matches (should be same as before)

- [ ] **Step 5: Lint all new files**

Run: `ruff check share/noba-web/server/routers/`
Expected: All checks passed!

- [ ] **Step 6: Run the FULL test suite**

Run: `pytest tests/ -v 2>&1 | tail -10`
Expected: 783 passed, 0 failed

- [ ] **Step 7: Verify JS syntax (sanity check — nothing changed but just in case)**

Run: `node -e "new Function(require('fs').readFileSync('share/noba-web/static/app.js','utf8'))" && echo "JS OK"`
Expected: JS OK

- [ ] **Step 8: Commit**

```bash
git add share/noba-web/server/routers/__init__.py tests/test_agent_websocket.py tests/test_agent_file_transfer.py
git commit -m "feat(v3): wire 8 new routers, delete system.py

Phase 1 complete: system.py (3190 lines) decomposed into:
- agents.py (24 routes)
- containers.py (8 routes)
- monitoring.py (17 routes)
- infrastructure.py (19 routes)
- security.py (6 routes)
- intelligence.py (22 routes)
- operations.py (19 routes)
- dashboards.py (4 routes)"
```

---

### Task 10: Verify route count parity

Sanity check that no routes were lost or duplicated in the decomposition.

**Files:**
- None (verification only)

- [ ] **Step 1: Count routes in old system.py (from git history)**

Run: `git show HEAD~1:share/noba-web/server/routers/system.py | grep -c '^@router\.'`
Expected: A number (the total decorator count in old system.py)

- [ ] **Step 2: Count routes across all new files**

Run: `grep -c '^@router\.' share/noba-web/server/routers/{agents,containers,monitoring,infrastructure,security,intelligence,operations,dashboards}.py | tail -1`
Expected: Same total as Step 1

- [ ] **Step 3: Check for duplicate route paths**

Run: `grep '@router\.' share/noba-web/server/routers/{agents,containers,monitoring,infrastructure,security,intelligence,operations,dashboards}.py | grep -oP '"/[^"]*"' | sort | uniq -d`
Expected: No output (no duplicates)

- [ ] **Step 4: Final full test run**

Run: `pytest tests/ -v 2>&1 | tail -5`
Expected: 783 passed

- [ ] **Step 5: Line count comparison**

Run: `wc -l share/noba-web/server/routers/{agents,containers,monitoring,infrastructure,security,intelligence,operations,dashboards}.py`
Expected: ~3100 total lines (slightly more than 3190 due to per-file imports, slightly less due to removed redundant comments)

---

### Task 11: Update CHANGELOG.md

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Add Phase 1 entry to CHANGELOG**

Add under `[Unreleased]`:

```markdown
### Changed
- **Backend decomposition (Phase 1):** Split `routers/system.py` (3190 lines, 122 routes) into 8 focused domain modules:
  - `agents.py` — agent CRUD, commands, WebSocket, deploy, file transfer
  - `containers.py` — Docker/Podman control, compose, TrueNAS VM
  - `monitoring.py` — endpoint monitors, uptime, status page, health score
  - `infrastructure.py` — network, K8s, Proxmox, services, terminal
  - `security.py` — security scans, findings, scoring
  - `intelligence.py` — AI ops, incidents, dependencies, config drift
  - `operations.py` — recovery, journal, system info, backups, IaC export
  - `dashboards.py` — custom dashboard CRUD
```

- [ ] **Step 2: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs: add Phase 1 backend decomposition to CHANGELOG"
```

---

## Verification Checklist (Post-Implementation)

After all tasks are complete, verify:

1. `system.py` no longer exists: `ls share/noba-web/server/routers/system.py` → "No such file"
2. All 783 tests pass: `pytest tests/ -v`
3. Ruff clean: `ruff check share/noba-web/server/routers/`
4. No duplicate routes: grep check from Task 10
5. Route count matches: old system.py route count == sum of new file route counts
6. CHANGELOG updated
