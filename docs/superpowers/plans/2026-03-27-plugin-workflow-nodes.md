# Plugin Workflow Nodes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow installed plugins to declare workflow action nodes that appear in the builder's action palette and execute via the existing job runner.

**Architecture:** Four new files bridge the plugin system and workflow engine: a backend bridge module (`workflow_nodes.py`) scans loaded plugins and registers their builders into a new `_PLUGIN_BUILDERS` dict in the engine; a router exposes all node descriptors at `GET /api/workflow-nodes`; a frontend composable fetches and caches them; and a generic `PluginNodeConfig.vue` renders dynamic field forms. Existing `WorkflowNodeConfig.vue` delegates unknown action types to the new component.

**Tech Stack:** FastAPI, Python 3.11+, Vue 3 `<script setup>`, Pinia-style composable (plain `ref`/`computed`), pytest, Vite.

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Create | `share/noba-web/server/workflow_nodes.py` | Scan plugins → register builders; expose node descriptor list |
| Create | `share/noba-web/server/routers/workflow_nodes.py` | `GET /api/workflow-nodes` endpoint |
| Create | `frontend/src/composables/useWorkflowNodes.js` | Fetch + cache node descriptors; merge with built-ins |
| Create | `frontend/src/components/automations/workflow/PluginNodeConfig.vue` | Generic field-form renderer for plugin nodes |
| Modify | `share/noba-web/server/workflow_engine.py` | Add `_PLUGIN_BUILDERS` dict + `register_plugin_builder()` |
| Modify | `share/noba-web/server/plugins.py` | `Plugin.__init__` reads `WORKFLOW_NODE` + `workflow_node_run` |
| Modify | `share/noba-web/server/routers/__init__.py` | Include `workflow_nodes` router in `api_router` |
| Modify | `share/noba-web/server/app.py` | Call `workflow_nodes.scan(plugin_manager)` after plugin load |
| Modify | `frontend/src/.../WorkflowNodeConfig.vue` | Merge hardcoded catalog with plugin nodes; delegate plugin types |
| Modify | `share/noba-web/plugins/catalog/mqtt_listener.py` | Add `WORKFLOW_NODE` + `workflow_node_run` as reference example |
| Create | `tests/test_workflow_nodes.py` | Tests for bridge module + registry + endpoint |

All frontend paths relative to `share/noba-web/frontend/src/`.

---

### Task 1: Dynamic builder registry in workflow_engine.py

**Files:**
- Modify: `share/noba-web/server/workflow_engine.py`
- Test: `tests/test_workflow_nodes.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_workflow_nodes.py`:

```python
"""Tests for plugin workflow node registration and execution bridge."""
from __future__ import annotations

import subprocess
import textwrap
import types

import pytest


def test_register_plugin_builder_adds_to_registry():
    import server.workflow_engine as we
    we._PLUGIN_BUILDERS.clear()
    fn = lambda cfg: None
    we.register_plugin_builder("my_plugin_type", fn)
    assert "my_plugin_type" in we._PLUGIN_BUILDERS
    assert we._PLUGIN_BUILDERS["my_plugin_type"] is fn
    we._PLUGIN_BUILDERS.clear()


def test_register_plugin_builder_skips_builtin_conflict(caplog):
    import server.workflow_engine as we
    import logging
    we._PLUGIN_BUILDERS.clear()
    fn = lambda cfg: None
    with caplog.at_level(logging.WARNING, logger="noba"):
        we.register_plugin_builder("service", fn)  # "service" is a builtin
    assert "service" not in we._PLUGIN_BUILDERS
    assert "conflicts with a built-in" in caplog.text
    we._PLUGIN_BUILDERS.clear()


def test_register_plugin_builder_warns_on_duplicate(caplog):
    import server.workflow_engine as we
    import logging
    we._PLUGIN_BUILDERS.clear()
    fn1 = lambda cfg: None
    fn2 = lambda cfg: None
    we.register_plugin_builder("my_type", fn1)
    with caplog.at_level(logging.WARNING, logger="noba"):
        we.register_plugin_builder("my_type", fn2)
    assert we._PLUGIN_BUILDERS["my_type"] is fn2  # last write wins
    assert "already registered" in caplog.text
    we._PLUGIN_BUILDERS.clear()
```

- [ ] **Step 2: Run tests — expect failure**

```bash
pytest tests/test_workflow_nodes.py::test_register_plugin_builder_adds_to_registry \
       tests/test_workflow_nodes.py::test_register_plugin_builder_skips_builtin_conflict \
       tests/test_workflow_nodes.py::test_register_plugin_builder_warns_on_duplicate -v
```

Expected: `AttributeError: module 'server.workflow_engine' has no attribute '_PLUGIN_BUILDERS'`

- [ ] **Step 3: Add `_PLUGIN_BUILDERS` and `register_plugin_builder` to workflow_engine.py**

Find the line `_AUTO_TYPES = ALLOWED_AUTO_TYPES  # from config` (after `_AUTO_BUILDERS` dict) and add immediately after it:

```python
# Plugin-contributed action builders — populated at startup by workflow_nodes.scan()
_PLUGIN_BUILDERS: dict = {}


def register_plugin_builder(type_key: str, fn) -> None:
    """Register a workflow action builder contributed by a plugin.

    Built-in types in ``_AUTO_BUILDERS`` cannot be overridden.
    Duplicate plugin keys log a warning and the last registration wins.
    """
    if type_key in _AUTO_BUILDERS:
        logger.warning(
            "Plugin tried to register workflow node type '%s' which conflicts with a built-in type — skipping",
            type_key,
        )
        return
    if type_key in _PLUGIN_BUILDERS:
        logger.warning("Plugin workflow node type '%s' already registered — overwriting", type_key)
    _PLUGIN_BUILDERS[type_key] = fn
    logger.info("Registered plugin workflow node type: %s", type_key)
```

- [ ] **Step 4: Update `_execute_action_node` to fall through to `_PLUGIN_BUILDERS`**

Find this existing line in `_execute_action_node` (around line 483):
```python
    builder = _AUTO_BUILDERS.get(action_type)
```
Replace it with:
```python
    builder = _AUTO_BUILDERS.get(action_type) or _PLUGIN_BUILDERS.get(action_type)
```

- [ ] **Step 5: Run tests — expect pass**

```bash
pytest tests/test_workflow_nodes.py::test_register_plugin_builder_adds_to_registry \
       tests/test_workflow_nodes.py::test_register_plugin_builder_skips_builtin_conflict \
       tests/test_workflow_nodes.py::test_register_plugin_builder_warns_on_duplicate -v
```

Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add share/noba-web/server/workflow_engine.py tests/test_workflow_nodes.py
git commit -m "feat: add _PLUGIN_BUILDERS registry and register_plugin_builder() to workflow engine"
```

---

### Task 2: Plugin class reads WORKFLOW_NODE

**Files:**
- Modify: `share/noba-web/server/plugins.py` (Plugin.__init__, around line 185-197)
- Test: `tests/test_workflow_nodes.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_workflow_nodes.py`:

```python
def test_plugin_reads_workflow_node_attrs(tmp_path):
    """Plugin.__init__ should pick up WORKFLOW_NODE and workflow_node_run."""
    import importlib.util, types
    from server.plugins import Plugin

    mod = types.ModuleType("test_wf_plugin")
    mod.PLUGIN_NAME = "WF Test"
    mod.PLUGIN_VERSION = "1.0.0"
    mod.WORKFLOW_NODE = {
        "type": "wf_test_action",
        "label": "WF Test Action",
        "icon": "fa-star",
        "description": "A test workflow node",
        "fields": [{"key": "msg", "type": "string", "label": "Message"}],
    }
    mod.workflow_node_run = lambda cfg: None

    plugin = Plugin(mod, "/fake/path.py", enabled=True)

    assert plugin.workflow_node == mod.WORKFLOW_NODE
    assert plugin.workflow_node_run is mod.workflow_node_run


def test_plugin_workflow_node_defaults_to_none(tmp_path):
    """Plugins without WORKFLOW_NODE have None for both attrs."""
    import types
    from server.plugins import Plugin

    mod = types.ModuleType("plain_plugin")
    mod.PLUGIN_NAME = "Plain"
    mod.PLUGIN_VERSION = "1.0.0"

    plugin = Plugin(mod, "/fake/plain.py", enabled=True)

    assert plugin.workflow_node is None
    assert plugin.workflow_node_run is None
```

- [ ] **Step 2: Run tests — expect failure**

```bash
pytest tests/test_workflow_nodes.py::test_plugin_reads_workflow_node_attrs \
       tests/test_workflow_nodes.py::test_plugin_workflow_node_defaults_to_none -v
```

Expected: `AttributeError: 'Plugin' object has no attribute 'workflow_node'`

- [ ] **Step 3: Add two lines to Plugin.__init__ in plugins.py**

Find the existing block ending with `self.enabled: bool = enabled` (around line 194) and add after it:

```python
        self.workflow_node: dict | None     = getattr(mod, "WORKFLOW_NODE", None)
        self.workflow_node_run              = getattr(mod, "workflow_node_run", None)
```

- [ ] **Step 4: Run tests — expect pass**

```bash
pytest tests/test_workflow_nodes.py::test_plugin_reads_workflow_node_attrs \
       tests/test_workflow_nodes.py::test_plugin_workflow_node_defaults_to_none -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add share/noba-web/server/plugins.py tests/test_workflow_nodes.py
git commit -m "feat: Plugin reads WORKFLOW_NODE and workflow_node_run attributes"
```

---

### Task 3: workflow_nodes.py bridge module

**Files:**
- Create: `share/noba-web/server/workflow_nodes.py`
- Test: `tests/test_workflow_nodes.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_workflow_nodes.py`:

```python
def _make_plugin(type_key, label, has_run_fn=True):
    """Helper: create a minimal Plugin with a WORKFLOW_NODE declared."""
    import types
    from server.plugins import Plugin

    mod = types.ModuleType(f"plugin_{type_key}")
    mod.PLUGIN_NAME = label
    mod.PLUGIN_VERSION = "1.0.0"
    mod.WORKFLOW_NODE = {
        "type": type_key,
        "label": label,
        "icon": "fa-star",
        "description": f"{label} description",
        "fields": [{"key": "param", "type": "string", "label": "Param"}],
    }
    if has_run_fn:
        mod.workflow_node_run = lambda cfg: None
    return Plugin(mod, f"/fake/{type_key}.py", enabled=True)


def test_scan_registers_builders(monkeypatch):
    import server.workflow_engine as we
    import server.workflow_nodes as wn

    we._PLUGIN_BUILDERS.clear()
    wn._plugin_descriptors.clear()

    class FakePM:
        _plugins = [_make_plugin("slack_notify", "Slack Notify")]

    wn.scan(FakePM())

    assert "slack_notify" in we._PLUGIN_BUILDERS
    we._PLUGIN_BUILDERS.clear()
    wn._plugin_descriptors.clear()


def test_scan_skips_plugin_without_run_fn(caplog):
    import logging
    import server.workflow_engine as we
    import server.workflow_nodes as wn

    we._PLUGIN_BUILDERS.clear()
    wn._plugin_descriptors.clear()

    class FakePM:
        _plugins = [_make_plugin("no_fn_type", "No Fn", has_run_fn=False)]

    with caplog.at_level(logging.WARNING, logger="noba"):
        wn.scan(FakePM())

    assert "no_fn_type" not in we._PLUGIN_BUILDERS
    assert "no workflow_node_run" in caplog.text
    we._PLUGIN_BUILDERS.clear()
    wn._plugin_descriptors.clear()


def test_scan_skips_disabled_plugin():
    import server.workflow_engine as we
    import server.workflow_nodes as wn
    from server.plugins import Plugin
    import types

    we._PLUGIN_BUILDERS.clear()
    wn._plugin_descriptors.clear()

    mod = types.ModuleType("disabled_plugin")
    mod.PLUGIN_NAME = "Disabled"
    mod.PLUGIN_VERSION = "1.0.0"
    mod.WORKFLOW_NODE = {"type": "disabled_type", "label": "Disabled", "icon": "fa-ban",
                          "description": "", "fields": []}
    mod.workflow_node_run = lambda cfg: None
    plugin = Plugin(mod, "/fake/disabled.py", enabled=False)

    class FakePM:
        _plugins = [plugin]

    wn.scan(FakePM())

    assert "disabled_type" not in we._PLUGIN_BUILDERS
    we._PLUGIN_BUILDERS.clear()
    wn._plugin_descriptors.clear()


def test_get_node_descriptors_includes_builtins_and_plugins():
    import server.workflow_engine as we
    import server.workflow_nodes as wn

    we._PLUGIN_BUILDERS.clear()
    wn._plugin_descriptors.clear()

    class FakePM:
        _plugins = [_make_plugin("custom_node", "Custom Node")]

    wn.scan(FakePM())
    descriptors = wn.get_node_descriptors()

    types_found = [d["type"] for d in descriptors]
    assert "service" in types_found        # builtin
    assert "custom_node" in types_found    # plugin

    plugin_desc = next(d for d in descriptors if d["type"] == "custom_node")
    assert plugin_desc["category"] == "plugin"
    assert plugin_desc["label"] == "Custom Node"

    builtin_desc = next(d for d in descriptors if d["type"] == "service")
    assert builtin_desc["category"] == "builtin"

    we._PLUGIN_BUILDERS.clear()
    wn._plugin_descriptors.clear()
```

- [ ] **Step 2: Run tests — expect failure**

```bash
pytest tests/test_workflow_nodes.py::test_scan_registers_builders \
       tests/test_workflow_nodes.py::test_scan_skips_plugin_without_run_fn \
       tests/test_workflow_nodes.py::test_scan_skips_disabled_plugin \
       tests/test_workflow_nodes.py::test_get_node_descriptors_includes_builtins_and_plugins -v
```

Expected: `ModuleNotFoundError: No module named 'server.workflow_nodes'`

- [ ] **Step 3: Create `share/noba-web/server/workflow_nodes.py`**

```python
"""Noba -- Plugin workflow node bridge.

Scans loaded plugins for ``WORKFLOW_NODE`` declarations and registers their
builders into the workflow engine.  Also exposes a descriptor list for the
frontend palette / config UI.
"""
from __future__ import annotations

import logging

from . import workflow_engine

logger = logging.getLogger("noba")

# ── Built-in action type descriptors (metadata only — execution in workflow_engine) ──

_BUILTIN_DESCRIPTORS: list[dict] = [
    {"type": "service",       "label": "Service",      "icon": "fa-cog",
     "description": "Start/stop/restart a systemd service",   "category": "builtin", "fields": []},
    {"type": "script",        "label": "Script",       "icon": "fa-terminal",
     "description": "Run a built-in or custom script",        "category": "builtin", "fields": []},
    {"type": "webhook",       "label": "Webhook",      "icon": "fa-link",
     "description": "Fire an outbound HTTP webhook",           "category": "builtin", "fields": []},
    {"type": "http",          "label": "HTTP",         "icon": "fa-globe",
     "description": "Generic HTTP request with auth support",  "category": "builtin", "fields": []},
    {"type": "agent_command", "label": "Agent Cmd",    "icon": "fa-satellite-dish",
     "description": "Run a command on a remote agent",         "category": "builtin", "fields": []},
    {"type": "remediation",   "label": "Remediation",  "icon": "fa-medkit",
     "description": "Execute a healing/remediation action",    "category": "builtin", "fields": []},
]

_plugin_descriptors: list[dict] = []


def scan(plugin_manager) -> None:
    """Scan all enabled plugins and register workflow node builders.

    Called once from ``app.py`` after plugins are loaded.
    Safe to call multiple times (re-scans on each call).
    """
    global _plugin_descriptors
    _plugin_descriptors = []

    for plugin in plugin_manager._plugins:
        if not plugin.enabled:
            continue
        node_meta: dict | None = plugin.workflow_node
        node_fn = plugin.workflow_node_run

        if node_meta is None:
            continue

        if node_fn is None:
            logger.warning(
                "Plugin '%s' declares WORKFLOW_NODE but has no workflow_node_run — skipping",
                plugin.id,
            )
            continue

        type_key: str = node_meta.get("type", "")
        if not type_key:
            logger.warning("Plugin '%s' WORKFLOW_NODE missing 'type' key — skipping", plugin.id)
            continue

        # Wrap the synchronous run function in the builder contract.
        # Built-in builders return subprocess.Popen | None; plugins return None.
        def _make_builder(fn):
            def _builder(config: dict):
                fn(config)
                return None
            return _builder

        workflow_engine.register_plugin_builder(type_key, _make_builder(node_fn))

        _plugin_descriptors.append({
            "type":        type_key,
            "label":       node_meta.get("label", type_key),
            "icon":        node_meta.get("icon", "fa-puzzle-piece"),
            "description": node_meta.get("description", ""),
            "category":    "plugin",
            "fields":      node_meta.get("fields", []),
        })
        logger.info("Registered plugin workflow node: %s (%s)", node_meta.get("label", type_key), type_key)


def get_node_descriptors() -> list[dict]:
    """Return all workflow node descriptors: built-in types first, then plugins."""
    return _BUILTIN_DESCRIPTORS + _plugin_descriptors
```

- [ ] **Step 4: Run tests — expect pass**

```bash
pytest tests/test_workflow_nodes.py::test_scan_registers_builders \
       tests/test_workflow_nodes.py::test_scan_skips_plugin_without_run_fn \
       tests/test_workflow_nodes.py::test_scan_skips_disabled_plugin \
       tests/test_workflow_nodes.py::test_get_node_descriptors_includes_builtins_and_plugins -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add share/noba-web/server/workflow_nodes.py tests/test_workflow_nodes.py
git commit -m "feat: workflow_nodes bridge — scan plugins, register builders, expose descriptors"
```

---

### Task 4: GET /api/workflow-nodes endpoint

**Files:**
- Create: `share/noba-web/server/routers/workflow_nodes.py`
- Modify: `share/noba-web/server/routers/__init__.py`
- Modify: `share/noba-web/server/app.py`
- Test: `tests/test_workflow_nodes.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_workflow_nodes.py`:

```python
def test_workflow_nodes_endpoint_returns_descriptors(tmp_path, monkeypatch):
    """GET /api/workflow-nodes returns builtin + plugin descriptors."""
    import server.workflow_nodes as wn
    # Seed one plugin descriptor directly
    wn._plugin_descriptors = [{
        "type": "test_ep_node", "label": "EP Node", "icon": "fa-star",
        "description": "Endpoint test node", "category": "plugin", "fields": [],
    }]

    from fastapi.testclient import TestClient
    from server.app import app
    from server.auth import _get_auth

    app.dependency_overrides[_get_auth] = lambda: {"username": "admin", "role": "admin"}
    client = TestClient(app)
    resp = client.get("/api/workflow-nodes")
    app.dependency_overrides.clear()

    assert resp.status_code == 200
    data = resp.json()
    types = [d["type"] for d in data]
    assert "service" in types        # builtin
    assert "test_ep_node" in types   # plugin
    wn._plugin_descriptors.clear()
```

- [ ] **Step 2: Run test — expect failure**

```bash
pytest tests/test_workflow_nodes.py::test_workflow_nodes_endpoint_returns_descriptors -v
```

Expected: 404 (route not yet registered).

- [ ] **Step 3: Create `share/noba-web/server/routers/workflow_nodes.py`**

```python
"""Router: workflow node catalog endpoint."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ..auth import _get_auth
from .. import workflow_nodes as wn

router = APIRouter()


@router.get("/api/workflow-nodes")
def list_workflow_nodes(user=Depends(_get_auth)) -> list[dict]:
    """Return all available workflow action node descriptors (built-in + plugin)."""
    return wn.get_node_descriptors()
```

- [ ] **Step 4: Register the router in `share/noba-web/server/routers/__init__.py`**

Find the last `api_router.include_router(...)` line in the file and add after it:

```python
from .workflow_nodes import router as workflow_nodes_router
api_router.include_router(workflow_nodes_router)
```

- [ ] **Step 5: Call `workflow_nodes.scan()` in app.py**

Find the lines in `app.py`:
```python
        plugin_manager.discover(app=app, db=db)
        plugin_manager.start()
```
Add immediately after `plugin_manager.start()`:
```python
        from . import workflow_nodes as _wn
        _wn.scan(plugin_manager)
```

- [ ] **Step 6: Run test — expect pass**

```bash
pytest tests/test_workflow_nodes.py::test_workflow_nodes_endpoint_returns_descriptors -v
```

Expected: 1 passed.

- [ ] **Step 7: Run full test suite to check for regressions**

```bash
pytest tests/ -v --tb=short -q
```

Expected: all existing tests pass.

- [ ] **Step 8: Commit**

```bash
git add share/noba-web/server/routers/workflow_nodes.py \
        share/noba-web/server/routers/__init__.py \
        share/noba-web/server/app.py \
        tests/test_workflow_nodes.py
git commit -m "feat: GET /api/workflow-nodes endpoint — returns builtin + plugin node descriptors"
```

---

### Task 5: useWorkflowNodes.js composable

**Files:**
- Create: `share/noba-web/frontend/src/composables/useWorkflowNodes.js`

- [ ] **Step 1: Create the composable**

```javascript
// share/noba-web/frontend/src/composables/useWorkflowNodes.js
import { ref, computed } from 'vue'
import { useApi } from './useApi'

// Module-level cache — shared across all component instances
const _cache = ref(null)   // null = not yet fetched; [] = fetched (may be empty)
const _fetching = ref(false)

export function useWorkflowNodes() {
  const { get } = useApi()

  async function fetchNodeTypes() {
    if (_cache.value !== null || _fetching.value) return
    _fetching.value = true
    try {
      const data = await get('/api/workflow-nodes')
      _cache.value = Array.isArray(data) ? data : []
    } catch {
      // Graceful degradation: built-ins still work without the API
      _cache.value = []
    } finally {
      _fetching.value = false
    }
  }

  // All action node subtypes — built-ins and plugins combined.
  // Built-ins appear first (category === 'builtin'), then plugins.
  const actionCatalog = computed(() =>
    (_cache.value || []).map(n => ({
      type:     n.type,
      icon:     n.icon,
      label:    n.label,
      desc:     n.description,
      fields:   n.fields  || [],
      category: n.category || 'builtin',
    }))
  )

  const ready = computed(() => _cache.value !== null)

  return { fetchNodeTypes, actionCatalog, ready }
}
```

- [ ] **Step 2: Verify the composable follows the useApi pattern**

```bash
grep -n "export function useApi\|return.*get" share/noba-web/frontend/src/composables/useApi.js | head -5
```

Expected: see `export function useApi()` and a `get` function being returned — confirming the import works.

- [ ] **Step 3: Commit**

```bash
git add share/noba-web/frontend/src/composables/useWorkflowNodes.js
git commit -m "feat: useWorkflowNodes composable — fetches and caches workflow node catalog"
```

---

### Task 6: PluginNodeConfig.vue — generic field form

**Files:**
- Create: `share/noba-web/frontend/src/components/automations/workflow/PluginNodeConfig.vue`

- [ ] **Step 1: Create the component**

```vue
<!-- PluginNodeConfig.vue — renders a dynamic config form from a fields[] descriptor -->
<script setup>
const props = defineProps({
  // Array of field descriptors: { key, type, label, required?, default?, options? }
  fields:  { type: Array,  default: () => [] },
  // Current param values: { [key]: value }
  params:  { type: Object, default: () => ({}) },
})

const emit = defineEmits(['update'])

function val(key, defaultVal = '') {
  return props.params[key] ?? defaultVal
}

function set(key, value) {
  emit('update', { ...props.params, [key]: value })
}
</script>

<template>
  <div class="pnc-fields">
    <template v-for="field in fields" :key="field.key">
      <!-- String -->
      <div v-if="field.type === 'string' || !field.type" class="wnc-field">
        <label class="wnc-label">
          {{ field.label }}<span v-if="field.required" class="wnc-required">*</span>
        </label>
        <input
          class="wnc-input"
          type="text"
          :placeholder="field.label"
          :value="val(field.key, field.default ?? '')"
          @input="set(field.key, $event.target.value)"
        />
      </div>

      <!-- Number -->
      <div v-else-if="field.type === 'number'" class="wnc-field">
        <label class="wnc-label">{{ field.label }}</label>
        <input
          class="wnc-input"
          type="number"
          :value="val(field.key, field.default ?? 0)"
          @input="set(field.key, Number($event.target.value))"
        />
      </div>

      <!-- Boolean -->
      <div v-else-if="field.type === 'boolean'" class="wnc-field wnc-field--inline">
        <input
          type="checkbox"
          :id="`pnc-${field.key}`"
          :checked="val(field.key, field.default ?? false)"
          @change="set(field.key, $event.target.checked)"
        />
        <label :for="`pnc-${field.key}`" class="wnc-label">{{ field.label }}</label>
      </div>

      <!-- Select -->
      <div v-else-if="field.type === 'select'" class="wnc-field">
        <label class="wnc-label">{{ field.label }}</label>
        <select
          class="wnc-input"
          :value="val(field.key, field.default ?? '')"
          @change="set(field.key, $event.target.value)"
        >
          <option v-for="opt in (field.options || [])" :key="opt" :value="opt">{{ opt }}</option>
        </select>
      </div>

      <!-- List (comma-separated) -->
      <div v-else-if="field.type === 'list'" class="wnc-field">
        <label class="wnc-label">{{ field.label }} <span class="wnc-hint">(comma-separated)</span></label>
        <input
          class="wnc-input"
          type="text"
          :value="Array.isArray(val(field.key, [])) ? val(field.key, []).join(', ') : val(field.key, '')"
          @input="set(field.key, $event.target.value.split(',').map(s => s.trim()).filter(Boolean))"
        />
      </div>
    </template>

    <p v-if="!fields.length" class="wnc-hint">This node has no configurable parameters.</p>
  </div>
</template>
```

- [ ] **Step 2: Confirm the CSS classes exist — add them if missing**

```bash
grep -c "wnc-field\|wnc-label\|wnc-input\|wnc-hint" share/noba-web/frontend/src/components/automations/workflow/WorkflowNodeConfig.vue
```

Expected: number > 0. If the count is 0, add these styles inside `<style scoped>` in `WorkflowNodeConfig.vue` (since `PluginNodeConfig` is always a child of it and inherits non-deep scoped styles through slot rendering — but if styles are `scoped`, add `:deep(.wnc-field)` wrappers or add the styles to `PluginNodeConfig.vue`'s own `<style scoped>` block):

```css
.wnc-field { display: flex; flex-direction: column; gap: .25rem; margin-bottom: .5rem; }
.wnc-field--inline { flex-direction: row; align-items: center; gap: .5rem; }
.wnc-label { font-size: .7rem; color: var(--text-muted); text-transform: uppercase; letter-spacing: .04em; }
.wnc-input { background: var(--surface); border: 1px solid var(--border); border-radius: 4px; color: var(--text); padding: .3rem .5rem; font-size: .8rem; width: 100%; }
.wnc-hint  { font-size: .65rem; color: var(--text-dim); }
.wnc-required { color: var(--danger); margin-left: 2px; }
```

- [ ] **Step 3: Commit**

```bash
git add share/noba-web/frontend/src/components/automations/workflow/PluginNodeConfig.vue
git commit -m "feat: PluginNodeConfig — generic field-form renderer for plugin workflow nodes"
```

---

### Task 7: Wire plugin nodes into WorkflowNodeConfig.vue

**Files:**
- Modify: `share/noba-web/frontend/src/components/automations/workflow/WorkflowNodeConfig.vue`

The current file has a hardcoded `ACTION_CATALOG` array (6 entries). We replace it with a dynamic one from the composable, and add a `v-else` branch that renders `<PluginNodeConfig>` for unknown types.

- [ ] **Step 1: Add imports and composable call at the top of `<script setup>`**

Find the existing line:
```js
import { computed } from 'vue'
```
Replace with:
```js
import { computed, onMounted } from 'vue'
import PluginNodeConfig from './PluginNodeConfig.vue'
import { useWorkflowNodes } from '../../../composables/useWorkflowNodes'

const { fetchNodeTypes, actionCatalog, ready } = useWorkflowNodes()
onMounted(fetchNodeTypes)
```

- [ ] **Step 2: Replace the hardcoded ACTION_CATALOG with the dynamic one**

Find and remove the entire static `ACTION_CATALOG` constant:
```js
const ACTION_CATALOG = [
  { type: 'service',       icon: 'fa-cog',          label: 'Service',       desc: 'Start/stop/restart a systemd service' },
  { type: 'script',        icon: 'fa-terminal',      label: 'Script',        desc: 'Run a built-in or custom script' },
  { type: 'webhook',       icon: 'fa-link',          label: 'Webhook',       desc: 'Fire an outbound HTTP webhook' },
  { type: 'http',          icon: 'fa-globe',         label: 'HTTP',          desc: 'Generic HTTP request with auth support' },
  { type: 'agent_command', icon: 'fa-satellite-dish',label: 'Agent Cmd',     desc: 'Run a command on a remote agent' },
  { type: 'remediation',   icon: 'fa-medkit',        label: 'Remediation',   desc: 'Execute a healing/remediation action' },
]
```

Replace it with:
```js
// ACTION_CATALOG is now fetched from /api/workflow-nodes via useWorkflowNodes().
// Falls back to empty array until the fetch completes (built-ins always included server-side).
const ACTION_CATALOG = actionCatalog
```

- [ ] **Step 3: Add PluginNodeConfig delegation in the template**

In the template, find the remediation config block — it ends with a closing `</template>` or `</div>` tagged with `v-if` or `v-else-if="actionType === 'remediation'"`. Add immediately after that closing tag:

```vue
<!-- Plugin node config — renders dynamic fields from WORKFLOW_NODE descriptor -->
<template v-else-if="actionType && !['service','script','webhook','http','agent_command','remediation'].includes(actionType)">
  <PluginNodeConfig
    :fields="ACTION_CATALOG.find(n => n.type === actionType)?.fields || []"
    :params="actionParams"
    @update="p => emit('update', { ...node, config: { type: actionType, config: p } })"
  />
</template>
```

- [ ] **Step 4: Build the frontend**

```bash
cd share/noba-web/frontend && npm run build 2>&1 | tail -8
```

Expected: `✓ built in X.XXs` with no errors.

- [ ] **Step 5: Deploy to live server**

```bash
rsync -a share/noba-web/static/dist/ ~/.local/libexec/noba/web/static/dist/
```

- [ ] **Step 6: Commit**

```bash
git add share/noba-web/frontend/src/components/automations/workflow/WorkflowNodeConfig.vue \
        share/noba-web/static/dist/
git commit -m "feat: WorkflowNodeConfig loads action catalog from API, delegates plugin types to PluginNodeConfig"
```

---

### Task 8: Reference example — mqtt_listener.py

**Files:**
- Modify: `share/noba-web/plugins/catalog/mqtt_listener.py`

This gives plugin authors a working example to copy from in the bundled catalog.

- [ ] **Step 1: Add WORKFLOW_NODE and workflow_node_run to mqtt_listener.py**

Read the current end of the file:
```bash
tail -20 share/noba-web/plugins/catalog/mqtt_listener.py
```

Append the following (after the existing `register` function or at end of file):

```python
# ── Workflow node declaration ─────────────────────────────────────────────

WORKFLOW_NODE = {
    "type": "mqtt_publish",
    "label": "MQTT Publish",
    "icon": "fa-broadcast-tower",
    "description": "Publish a message to an MQTT topic via the configured broker",
    "fields": [
        {"key": "topic",   "type": "string",  "label": "Topic",   "required": True,  "default": "noba/events"},
        {"key": "payload", "type": "string",  "label": "Payload", "required": False, "default": "triggered"},
        {"key": "qos",     "type": "select",  "label": "QoS",     "options": ["0", "1", "2"], "default": "0"},
        {"key": "retain",  "type": "boolean", "label": "Retain",  "default": False},
    ],
}


def workflow_node_run(config: dict) -> None:
    """Publish an MQTT message. Requires paho-mqtt to be installed."""
    try:
        import paho.mqtt.publish as publish  # type: ignore
    except ImportError:
        raise RuntimeError("paho-mqtt is not installed. Run: pip install paho-mqtt")

    # In a real plugin use ctx.get_config(); here we fall back to environment vars
    import os
    broker = os.environ.get("MQTT_BROKER", "localhost")
    port   = int(os.environ.get("MQTT_PORT", "1883"))

    publish.single(
        topic    = config.get("topic",   "noba/events"),
        payload  = config.get("payload", "triggered"),
        qos      = int(config.get("qos", 0)),
        retain   = bool(config.get("retain", False)),
        hostname = broker,
        port     = port,
    )
```

- [ ] **Step 2: Verify the plugin file is still valid Python**

```bash
python3 -c "import ast; ast.parse(open('share/noba-web/plugins/catalog/mqtt_listener.py').read()); print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add share/noba-web/plugins/catalog/mqtt_listener.py
git commit -m "feat: mqtt_listener — add WORKFLOW_NODE and workflow_node_run as reference example"
```

---

### Task 9: Full verification

- [ ] **Step 1: Run the complete test suite**

```bash
pytest tests/ -v --tb=short -q
```

Expected: all tests pass, including the new `test_workflow_nodes.py` tests.

- [ ] **Step 2: Manual smoke test**

1. Open `http://localhost:8080/#/automations`
2. Click edit on any workflow automation
3. Click "Action" in the palette to add a new node, then click the new node
4. In the config panel, verify the action type tiles load (including any installed plugins)
5. Open browser DevTools → Network → filter `/api/workflow-nodes` — verify 200 response with `builtin` entries

- [ ] **Step 3: Verify ruff passes**

```bash
ruff check share/noba-web/server/workflow_nodes.py share/noba-web/server/routers/workflow_nodes.py share/noba-web/server/plugins.py share/noba-web/server/workflow_engine.py
```

Expected: no output (clean).

- [ ] **Step 4: Update CHANGELOG.md**

Add under `[Unreleased]`:
```markdown
### Added
- Plugin workflow nodes: plugins can declare `WORKFLOW_NODE` + `workflow_node_run` to contribute action nodes to the workflow builder palette
- `GET /api/workflow-nodes` endpoint returns built-in + plugin node descriptors
- `PluginNodeConfig` component renders dynamic field forms from plugin node schemas
- `mqtt_listener` bundled plugin now includes an MQTT Publish workflow node as a reference example
```

- [ ] **Step 5: Final commit**

```bash
git add CHANGELOG.md
git commit -m "docs: changelog — plugin workflow nodes"
```
