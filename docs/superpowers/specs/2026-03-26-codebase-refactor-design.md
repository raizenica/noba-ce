# NOBA Codebase Refactor Design

**Date:** 2026-03-26
**Branch:** `refactor/codebase-split`
**Status:** Approved for implementation

## Overview

NOBA has grown substantially across several major feature rounds. This sprint addresses
seven concrete structural problems: one god-class database facade, one mixed-concern
integration file, two oversized frontend components, one oversized automation component,
one oversized workflow builder component, a cross-cutting error handling duplication
pattern, and a monolithic agent file constrained by its single-file distribution model.

No new features are added. External APIs, caller signatures, and WebSocket protocols
are unchanged unless explicitly noted.

---

## Target 1: `db/core.py` — Mixin co-location

### Problem

`db/core.py` is 1,681 lines split across three concerns:
- ~220 lines: import block re-importing from 25 already-split domain modules
- ~570 lines: `_init_schema()` — raw DDL SQL for every table in one method
- ~900 lines: 184 delegation wrapper methods, each forwarding to a domain function

The domain logic is already correctly split. The bulk comes from centralised DDL
and mechanical boilerplate wrappers.

### Design

Each of the 25 domain modules gains two additions at the bottom of the file:

1. `def init_schema(conn: sqlite3.Connection) -> None` — the DDL `CREATE TABLE IF
   NOT EXISTS` statements that belong to that domain, extracted verbatim from
   `_init_schema`.

2. `class _XMixin` — the wrapper methods currently in `Database` that forward to
   functions in that module. Example:

```python
# db/metrics.py (bottom section, added during refactor)

def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS metrics (...);
        CREATE INDEX IF NOT EXISTS idx_metric_time ON metrics(metric, timestamp);
        ...
    """)

class _MetricsMixin:
    def insert_metrics(self, metrics: list[tuple]) -> None:
        insert_metrics(self._get_conn(), self._lock, metrics)

    def get_history(self, metric: str, range_hours: int = 24, ...) -> list[dict]:
        return get_history(self._get_read_conn(), self._read_lock, metric, ...)
    ...
```

`db/core.py` becomes:

```python
# db/core.py — ~150 lines total

class DatabaseBase:
    """Connection management only."""
    def __init__(self, path): ...
    def _get_conn(self): ...
    def _get_read_conn(self): ...
    def execute_read(self, fn): ...
    def execute_write(self, fn): ...
    def transaction(self, fn): ...
    def _init_schema(self):
        conn = self._get_conn()
        for mod in _SCHEMA_MODULES:
            mod.init_schema(conn)
        conn.commit()
    def wal_checkpoint(self): ...
    def rollup_to_1m(self): ...  # metrics-specific, stays here
    ...

class Database(
    DatabaseBase,
    _MetricsMixin, _AuditMixin, _AutomationsMixin, _AlertsMixin,
    _ApiKeysMixin, _TokensMixin, _NotificationsMixin, _UserDashboardsMixin,
    _UserPreferencesMixin, _IncidentsMixin, _AgentsMixin, _EndpointsMixin,
    _DashboardsMixin, _StatusPageMixin, _SecurityMixin, _DependenciesMixin,
    _BaselinesMixin, _NetworkMixin, _WebhooksMixin, _BackupVerifyMixin,
    _ApprovalsMixin, _HealingMixin, _IntegrationsMixin, _LinkedProvidersMixin,
):
    pass
```

**Caller impact:** Zero. `from .db import db` and `db.method(...)` are unchanged.

**Result:** `core.py` 1,681 → ~150 lines. Each domain module grows by ~20–60 lines.
Total line count across `db/` is unchanged; distribution is dramatically better.

---

## Target 2: `integrations/simple.py` — Category split

### Problem

`integrations/simple.py` is 1,118 lines mixing integration handlers from six
distinct functional categories (network, media, infrastructure, monitoring, IoT,
communications) with no internal organisation.

### Design

Split into category files. `simple.py` becomes a thin re-exporter:

```
integrations/
  simple_network.py      — pihole, adguard, unifi, cloudflare, traefik, npm (~200 lines)
  simple_media.py        — plex, jellyfin, sonarr, radarr, qbittorrent, tautulli,
                           overseerr, prowlarr, lidarr, readarr, bazarr (~250 lines)
  simple_infra.py        — truenas, proxmox, omv, xcpng, k8s, gitea, gitlab,
                           github, paperless, vaultwarden (~200 lines)
  simple_monitoring.py   — uptime-kuma, scrutiny, speedtest, frigate,
                           graylog, influxdb (~150 lines)
  simple_iot.py          — hass, homebridge, z2m, esphome, pikvm,
                           unifi-protect, n8n (~150 lines)
  simple_comms.py        — gotify, pushover, ntfy, authentik, speedtest (~100 lines)
  simple.py              — imports and re-exports all of the above (~50 lines)
```

**Caller impact:** Zero. All external imports of `from .integrations.simple import X`
continue to resolve through `simple.py`'s re-exports.

---

## Target 3: `IntegrationsTab.vue` — Sub-component decomposition

### Problem

`IntegrationsTab.vue` is 1,532 lines handling list rendering, search/filter,
instance management, health display, group management, and action dispatch in a
single component.

### Design

```
frontend/src/components/settings/
  IntegrationsTab.vue                 — coordinator, ~150 lines
  integrations/
    IntegrationCategoryList.vue       — grouped list rendering by category (~200 lines)
    IntegrationInstanceCard.vue       — single instance row: status badge, health
                                        indicator, edit/delete actions (~150 lines)
    IntegrationSearchFilter.vue       — search input + category filter bar (~80 lines)
    IntegrationEmptyState.vue         — empty/onboarding state with call-to-action (~60 lines)
```

`IntegrationSetup.vue` (the setup wizard, 330 lines) is already a separate
component and remains unchanged.

**Data flow:** `IntegrationsTab` owns the instances list and search state.
It passes filtered data down as props. `IntegrationInstanceCard` emits
`edit` and `delete` events up. No Pinia store changes required.

---

## Target 4: `AutomationListTab.vue` — Sub-component decomposition

### Problem

`AutomationListTab.vue` is 967 lines handling list rendering, status badges,
run history display, trigger controls, and the automation detail drawer in one file.

### Design

```
frontend/src/components/automations/
  AutomationListTab.vue               — coordinator, ~150 lines
  AutomationRow.vue                   — single automation row: name, type, schedule,
                                        status badge, run/disable/delete actions (~150 lines)
  AutomationRunHistory.vue            — run history table with status + output (~150 lines)
  AutomationStatusBadge.vue           — reusable status chip (queued/running/done/failed)
                                        (~40 lines, reusable across the app)
```

`AutomationFormModal.vue` (460 lines) is already separate and unchanged.

---

## Target 5: `WorkflowBuilder.vue` — Sub-component decomposition

### Problem

`WorkflowBuilder.vue` is 784 lines combining the canvas drag surface, node palette,
node configuration panel, and connection rendering in one component.

### Design

```
frontend/src/components/automations/
  WorkflowBuilder.vue                 — coordinator + canvas event handling, ~200 lines
  workflow/
    WorkflowNodePalette.vue           — left sidebar: draggable node types (~150 lines)
    WorkflowNodeConfig.vue            — right panel: selected node configuration form
                                        (step type, params, conditions) (~200 lines)
    WorkflowNodeCard.vue              — individual node on the canvas: label, type icon,
                                        connection handles (~100 lines)
```

Canvas SVG connection rendering stays in `WorkflowBuilder.vue` as it is tightly
coupled to the drag-and-drop state.

---

## Target 6: Router error handling decorator

### Problem

135 try/except blocks across all 19 routers follow an identical pattern:

```python
try:
    ...
except HTTPException:
    raise
except Exception as e:
    raise HTTPException(status_code=500, detail=str(e))
```

This is copy-pasted boilerplate with no standardisation of error response format.

### Design

Add `server/utils.py` (or extend `server/deps.py`) with a decorator:

```python
def handle_errors(func):
    """Wrap a FastAPI route handler to catch unhandled exceptions and return
    a consistent 500 response. HTTPException passes through unchanged."""
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except HTTPException:
            raise
        except Exception as e:
            logger.exception("Unhandled error in %s", func.__name__)
            raise HTTPException(status_code=500, detail=str(e))
    return wrapper
```

Applied to all route handlers:

```python
@router.get("/agents")
@handle_errors
async def list_agents(...):
    ...  # no try/except needed
```

**Sync route support:** The decorator detects sync vs async with
`asyncio.iscoroutinefunction` and wraps appropriately.

**Rollout:** Apply to all routers in one pass. Each router's try/except blocks
are removed. Net change: ~200 lines removed across the codebase.

---

## Target 7: `agent.py` → zipapp package

### Problem

`agent.py` is 4,949 lines in a single file. The single-file constraint exists
because the auto-update mechanism distributes one file. The file now contains:
the WebSocket client, metric collection, 42 command handlers, PTY management,
a healing runtime, RDP orchestration for three platforms, and a 200-line Mutter
subprocess script embedded as a Python string.

### Design

#### Package structure

```
share/noba-agent/
  __main__.py          — argparse entry point, main() loop, _ws_thread() (~300 lines)
  websocket.py         — custom RFC 6455 WebSocket client (~250 lines)
  metrics.py           — CPU/mem/disk/net/temp/process/uptime collection (~400 lines)
  commands.py          — all 42 _cmd_* handlers + execute_commands() (~800 lines)
  terminal.py          — PTY management, _pty_* functions (~250 lines)
  healing.py           — HealRuntime class + _heal_eval* condition engine (~300 lines)
  rdp.py               — RDP capture loop, X11/Windows/macOS inject, orchestration (~600 lines)
  rdp_session.py       — Mutter D-Bus subprocess script (real .py, not embedded string)
  utils.py             — path validation, subprocess safety, platform detection (~200 lines)
```

#### `rdp_session.py` loading

`rdp.py` loads the session script at runtime using `importlib.resources`,
so it remains a real editable Python file but still runs as a subprocess string:

```python
# rdp.py
import importlib.resources
_MUTTER_SESSION_SCRIPT = (
    importlib.resources.files("noba_agent")
    .joinpath("rdp_session.py")
    .read_text(encoding="utf-8")
)
```

This is identical in runtime behaviour to the current embedded string —
the subprocess is still started with `python3 -c <script>` — but the
source is now a real, syntax-highlighted, navigable Python file.

#### Build step

`scripts/build-agent.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
python3 -m zipapp share/noba-agent \
    -o share/noba-agent.pyz \
    -p "/usr/bin/env python3"
echo "Built share/noba-agent.pyz ($(du -sh share/noba-agent.pyz | cut -f1))"
```

The `.pyz` file is a standard Python zipapp — `python3 agent.pyz` works on any
Python 3.6+ system with no changes to how agents are invoked.

#### VERSION

`__main__.py` contains `VERSION = "3.0.0"`. The server reads it via zipfile
inspection (already knows the path):

```python
# routers/agents.py
import zipfile, re
with zipfile.ZipFile(agent_pyz_path) as zf:
    src = zf.read("__main__.py").decode()
VERSION_RE = re.compile(r'^VERSION\s*=\s*["\']([^"\']+)["\']', re.M)
server_version = VERSION_RE.search(src).group(1)
```

#### Update mechanism

The server currently reads `agent.py` text and sends it to agents.
With zipapp:

- Server reads `agent.pyz` as **bytes** and base64-encodes for transport
- Agent's `_cmd_update_agent` writes the decoded bytes to `agent.pyz` and restarts
- `install.sh` installs `agent.pyz` to `~/.local/libexec/noba/noba-agent.pyz`
- Systemd unit runs `python3 agent.pyz` instead of `python3 agent.py`

The binary transport is already supported — the existing update mechanism
sends the file content as a string field. Switching to base64 bytes is a
one-line change on both sides.

#### Zero-dependency guarantee

The zipapp contains only stdlib code. No pip packages are bundled.
`Pillow` (used for RDP JPEG encoding) remains an optional host-installed
dependency detected at runtime — unchanged.

#### Test targets

Proxmox VE nodes (pve01, pve02) — full agent functionality including
metric reporting, command execution, and terminal. dnsa01 (Raspberry Pi 5) —
RDP capture and input injection via Mutter D-Bus.

---

## Implementation order

1. Router error handling decorator — cross-cutting, low risk, establishes patterns
2. `db/core.py` mixin split — backend, no frontend impact
3. `integrations/simple.py` category split — isolated, no caller changes
4. `IntegrationsTab.vue` decomposition — largest frontend component
5. `AutomationListTab.vue` decomposition
6. `WorkflowBuilder.vue` decomposition
7. Agent zipapp — most structural change, tested on PVE nodes last

## Success criteria

- `pytest tests/ -v` passes with zero regressions after each step
- `ruff check share/noba-web/server/` passes after Python changes
- `npm run build` succeeds after frontend changes
- Agent zipapp runs on PVE test nodes with full functionality
- `db/core.py` ≤ 200 lines
- `integrations/simple.py` ≤ 60 lines
- All refactored Vue components ≤ 200 lines
- No new files created unless strictly necessary
