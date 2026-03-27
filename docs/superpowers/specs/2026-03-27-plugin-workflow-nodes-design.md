# Plugin Workflow Nodes — Design Spec
**Date:** 2026-03-27
**Branch:** main (community edition)
**Status:** Approved

---

## Problem

The workflow builder's action palette is hardcoded to 9 built-in types (`_AUTO_BUILDERS` in `workflow_engine.py`). Plugins have no way to contribute workflow nodes. The community edition should allow any installed plugin to declare a workflow node that appears in the palette, has its own config form, and executes via the existing job runner.

Enterprise-v2 will require a separate design for the management layer, but the **plugin author API is intentionally identical** (`WORKFLOW_NODE` dict + `workflow_node_run` function). A plugin written for community works in enterprise without modification. Enterprise layers on top: marketplace UI, per-tenant node scoping, version pinning, and admin-approval before a node goes live.

---

## Solution Overview

Bridge the existing plugin system and workflow engine via 4 new files and small touches to 5 existing files. No new architectural patterns — everything follows conventions already in the codebase.

---

## New Files

### 1. `server/workflow_nodes.py`
Single-responsibility bridge module.

- `scan(plugin_manager)` — iterates `plugin_manager._plugins`, reads `WORKFLOW_NODE` + `workflow_node_run` from each enabled plugin, calls `register_plugin_builder(type, fn)` on the workflow engine.
- `get_node_descriptors()` — returns a list combining built-in action type descriptors (label, icon, description, fields) with plugin-contributed ones. Used by the API endpoint.
- Called from `app.py` once after plugins are loaded.

### 2. `server/routers/workflow_nodes.py`
One authenticated GET endpoint.

```
GET /api/workflow-nodes
→ 200 [{ type, label, icon, description, category, fields[] }]
```

`category` is `"builtin"` or `"plugin"`. `fields[]` mirrors `PLUGIN_CONFIG_SCHEMA` field shape: `{key, type, label, required?, default?, options?}`.

Registered in `app.py` alongside existing routers.

### 3. `frontend/src/composables/useWorkflowNodes.js`
Fetches `/api/workflow-nodes` on first call, caches result. Returns:
- `nodeTypes` — merged list of built-in + plugin node descriptors (used by `WorkflowNodePalette`)
- `actionCatalog` — plugin-contributed action tiles (used by `WorkflowNodeConfig`)

Built-in palette entries (Action, Condition, Approval, Parallel, Delay, Notify) stay hardcoded here as the fallback; the fetch only adds plugin-contributed action subtypes.

### 4. `frontend/src/components/automations/workflow/PluginNodeConfig.vue`
Generic config form renderer for plugin action nodes. Receives a `fields[]` descriptor and current `params` object, emits `update` events in the same shape as the built-in action config handlers. Supports field types: `string`, `number`, `boolean`, `select`, `list`. Keeps `WorkflowNodeConfig.vue` clean — it just delegates unknown action types here.

---

## Modified Files

| File | Change |
|---|---|
| `server/plugins.py` | `Plugin.__init__` reads `WORKFLOW_NODE` and stores `workflow_node` + `workflow_node_run` attrs (2 lines) |
| `server/workflow_engine.py` | Add `_PLUGIN_BUILDERS: dict = {}`; add `register_plugin_builder(type_key, fn)` function; `_execute_action_node` falls through to `_PLUGIN_BUILDERS` after `_AUTO_BUILDERS` miss |
| `server/app.py` | Include `workflow_nodes` router; call `workflow_nodes.scan(plugin_manager)` after plugin load |
| `frontend/.../WorkflowBuilder.vue` | Use `useWorkflowNodes()` composable to supply `nodeTypes` to `WorkflowNodePalette` |
| `frontend/.../WorkflowNodeConfig.vue` | Add `v-else` branch: unknown action type → `<PluginNodeConfig :fields="..." :params="...">` |

---

## Plugin Author API

Follows the exact same pattern as `PLUGIN_CONFIG_SCHEMA` and `collect()` today:

```python
WORKFLOW_NODE = {
    "type": "mqtt_publish",           # unique key, prefixed by convention: plugin_id__type
    "label": "MQTT Publish",
    "icon": "fa-broadcast-tower",     # FontAwesome class
    "description": "Publish a message to an MQTT topic",
    "fields": [
        {"key": "topic",   "type": "string", "label": "Topic",   "required": True},
        {"key": "payload", "type": "string", "label": "Payload", "default": ""},
        {"key": "qos",     "type": "select", "label": "QoS",
         "options": ["0", "1", "2"], "default": "0"},
    ],
}

def workflow_node_run(config: dict) -> None:
    """Synchronous execution. Return None (no subprocess). Raise on failure."""
    topic   = config.get("topic", "")
    payload = config.get("payload", "")
    # ... do the work
```

`workflow_node_run` wraps synchronously — the job runner handles threading. Plugins needing a subprocess return a `subprocess.Popen` instead (same contract as built-in builders).

---

## Data Flow

```
Plugin file                     Backend                        Frontend
──────────────────────────────────────────────────────────────────────────
WORKFLOW_NODE dict   ──→  plugins.py Plugin.__init__
workflow_node_run fn ──→  workflow_nodes.scan()
                          ├─ register_plugin_builder()  ──→  workflow_engine._PLUGIN_BUILDERS
                          └─ get_node_descriptors()     ──→  GET /api/workflow-nodes
                                                              ↓
                                                         useWorkflowNodes.js
                                                         ├─ nodeTypes ──→ WorkflowNodePalette
                                                         └─ actionCatalog ──→ WorkflowNodeConfig
                                                                              └─ PluginNodeConfig
```

---

## Error Handling

- Plugin missing `workflow_node_run`: `scan()` logs a warning and skips registration silently.
- Duplicate `type` key across plugins: last-loaded wins; a warning is logged.
- `/api/workflow-nodes` fetch fails: `useWorkflowNodes` falls back to built-in types only; no palette breakage.
- Plugin `workflow_node_run` raises: job runner catches it and marks the run as failed (existing behavior).

---

## Out of Scope

- Multiple workflow nodes per plugin (`WORKFLOW_NODES` list) — can be added later; single node covers all current use cases.
- Node versioning or migration.
- Enterprise-v2 management layer (separate spec): marketplace catalog, per-tenant node scoping, version pinning, admin approval gate before a node is available to workflow builders.
- Public community registry / remote catalog URL.
