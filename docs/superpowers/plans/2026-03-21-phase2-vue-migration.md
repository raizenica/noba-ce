# Phase 2: Vue.js Frontend Migration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate NOBA's Alpine.js frontend (6945-line `index.html` + 6 JS mixins) to Vue 3 with component-based architecture, lazy-loaded routing, and mobile responsive layout.

**Architecture:** Incremental page-by-page migration. Vue project lives alongside the existing Alpine.js frontend during development. Vite dev server proxies API calls to the FastAPI backend. At the end, FastAPI switches to serving the Vue build output and the old frontend is deleted.

**Tech Stack:** Vue 3.5+, Vite 6, Vue Router 4, Pinia 2, Chart.js 4, plain JavaScript (no TypeScript)

**Spec:** `docs/superpowers/specs/2026-03-21-noba-v3-roadmap-design.md` (Phase 2 section)

---

## Current Frontend (Alpine.js) — Reference

| File | Lines | Role |
|------|-------|------|
| `share/noba-web/index.html` | 6945 | All pages + modals in one file |
| `share/noba-web/static/app.js` | 1984 | Core Alpine component, SSE, settings |
| `share/noba-web/static/system-actions.js` | 2696 | History, audit, SMART, backup, health, profiles |
| `share/noba-web/static/integration-actions.js` | 869 | Services, containers, K8s, Proxmox, agents |
| `share/noba-web/static/automation-actions.js` | 430 | Automation CRUD, workflows, job polling |
| `share/noba-web/static/auth-mixin.js` | 266 | Login/logout, token, user management |
| `share/noba-web/static/actions-mixin.js` | 245 | Log viewer, script execution, confirmations |
| `share/noba-web/static/style.css` | 1681 | Themes, layout, all component styles |
| `share/noba-web/service-worker.js` | 158 | PWA caching, notifications |

**Page boundaries in index.html:**

| Page | Lines | Size |
|------|-------|------|
| Dashboard | 224–2167 | 1943 |
| Agents | 2168–2340 | 172 |
| Monitoring | 2341–2733 | 392 |
| Infrastructure | 2734–3235 | 501 |
| Automations | 3236–3351 | 115 |
| Logs | 3352–3497 | 145 |
| Security | 3498–3619 | 121 |
| Settings | 3622–5840 | ~2218 |
| Modals | 3640–6945 | scattered |

---

## Vue File Structure

```
share/noba-web/frontend/
  package.json
  vite.config.js
  index.html                          # Vite entry point
  public/
    favicon.ico
    favicon.svg
  src/
    main.js                           # App bootstrap
    App.vue                           # Root layout: sidebar + header + router-view
    router/
      index.js                        # Vue Router with lazy-loaded routes
    stores/
      auth.js                         # Token, user info, role, login/logout
      dashboard.js                    # SSE connection, live data, polling
      settings.js                     # App settings, visibility, preferences
      notifications.js                # Toast queue, push notifications
    composables/
      useApi.js                       # Fetch wrapper with auth + 401 handling
      useIntervals.js                 # Named interval registry with auto-cleanup
    components/
      layout/
        AppSidebar.vue                # Navigation sidebar
        AppHeader.vue                 # Top bar: search, refresh, theme, status
        SearchModal.vue               # Global search overlay
      ui/
        AppModal.vue                  # Reusable modal wrapper
        ToastContainer.vue            # Toast notification stack
        ConfirmDialog.vue             # Two-step confirmation
        Badge.vue                     # Status badge (success/info/warning/danger)
        ChartWrapper.vue              # Chart.js canvas lifecycle wrapper
        DataTable.vue                 # Sortable/paginated table
      cards/                          # Dashboard card components (one per integration)
        SystemHealthCard.vue          # CPU, memory, load, temp
        DiskCard.vue                  # Disk usage, ZFS pools
        ServicesCard.vue              # systemd services
        ContainersCard.vue            # Docker containers
        AlertsCard.vue                # Active alerts
        PiholeCard.vue
        PlexCard.vue
        RadarrCard.vue
        SonarrCard.vue
        QbitCard.vue
        TruenasCard.vue
        ProxmoxCard.vue
        UnifiCard.vue
        AdguardCard.vue
        JellyfinCard.vue
        HassCard.vue
        SpeedtestCard.vue
        WeatherCard.vue
        ... (one per integration)
      modals/
        HistoryModal.vue              # Metric history chart
        AuditModal.vue                # Audit log table
        SmartModal.vue                # SMART disk health
        BackupExplorerModal.vue       # Snapshot browser + diff
        SystemInfoModal.vue           # OS/hardware details
        ProcessModal.vue              # Process list
        NetworkModal.vue              # Connections + ports
        MultiMetricModal.vue          # Multi-metric chart
        RunHistoryModal.vue           # Script run history
        TerminalModal.vue             # Web terminal (xterm.js)
        ProfileModal.vue              # User profile + password + TOTP + API keys
    views/
      LoginView.vue                   # Full-screen login form
      DashboardView.vue               # Card grid + custom dashboards
      AgentsView.vue                  # Agent list, commands, detail, streams
      MonitoringView.vue              # Endpoints, uptime, health, status page
      InfrastructureView.vue          # Services, network, K8s, Proxmox, topology
      AutomationsView.vue             # CRUD, run, templates, workflow trace
      LogsView.vue                    # Log viewer, journal, command history
      SecurityView.vue                # Security scans, findings, history
      SettingsView.vue                # 9 sub-tabs (general, visibility, etc.)
    assets/
      styles/
        global.css                    # Ported from style.css (themes, layout, components)
```

---

## Alpine.js → Vue Pattern Reference

| Alpine.js | Vue 3 Equivalent |
|-----------|-------------------|
| `x-data="dashboard()"` | `<script setup>` + Pinia stores |
| `x-show="condition"` | `v-show="condition"` |
| `x-if="condition"` | `v-if="condition"` |
| `x-for="item in items"` | `v-for="item in items" :key="item.id"` |
| `x-text="value"` | `{{ value }}` or `v-text="value"` |
| `x-html="html"` | `v-html="html"` |
| `x-model="field"` | `v-model="field"` |
| `x-model.number` | `v-model.number` |
| `@click="fn()"` | `@click="fn()"` |
| `@click.stop` | `@click.stop` |
| `@click.self` | `@click.self` |
| `@keydown.escape.window` | `@keydown.escape` (on element) |
| `:class="{ active: cond }"` | `:class="{ active: cond }"` (same) |
| `:style="{ ... }"` | `:style="{ ... }"` (same) |
| `x-init="fn()"` | `onMounted(() => fn())` |
| `x-effect="expr"` | `watch(() => expr, ...)` or `watchEffect` |
| `x-cloak` | Not needed (Vue handles) |
| `x-ref="name"` | `const name = ref(null)` + `ref="name"` |
| `this.prop` (in Alpine methods) | `prop.value` (ref) or `store.prop` (Pinia) |
| `...authMixin()` (spread) | `const auth = useAuthStore()` |
| `$nextTick` | `nextTick()` from vue |
| `localStorage.getItem(...)` | Same, or Pinia persisted state |
| `fetch(url, { headers: { Authorization } })` | `useApi().get(url)` (auto-adds token) |

---

### Task 1: Vue Project Scaffolding

Create the Vue project with Vite, install all dependencies, verify the dev server starts.

**Files:**
- Create: `share/noba-web/frontend/package.json`
- Create: `share/noba-web/frontend/vite.config.js`
- Create: `share/noba-web/frontend/index.html`
- Create: `share/noba-web/frontend/src/main.js`
- Create: `share/noba-web/frontend/src/App.vue` (placeholder)

- [ ] **Step 1: Create `package.json`**

```json
{
  "name": "noba-web",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "chart.js": "^4.4.0",
    "chartjs-plugin-zoom": "^2.2.0",
    "pinia": "^2.3.0",
    "vue": "^3.5.0",
    "vue-router": "^4.5.0"
  },
  "devDependencies": {
    "@vitejs/plugin-vue": "^5.2.0",
    "vite": "^6.0.0"
  }
}
```

- [ ] **Step 2: Create `vite.config.js`**

```js
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  root: '.',
  base: '/',
  build: {
    outDir: '../static/dist',
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8080',
        ws: true,
      },
      '/static': 'http://localhost:8080',
    },
  },
})
```

- [ ] **Step 3: Create `index.html`** (Vite entry point)

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>NOBA Command Center</title>
  <link rel="icon" type="image/svg+xml" href="/favicon.svg">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Chakra+Petch:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
</head>
<body>
  <div id="app"></div>
  <script type="module" src="/src/main.js"></script>
</body>
</html>
```

- [ ] **Step 4: Create placeholder `src/main.js`**

```js
import { createApp } from 'vue'
import App from './App.vue'

const app = createApp(App)
app.mount('#app')
```

- [ ] **Step 5: Create placeholder `src/App.vue`**

```vue
<template>
  <div>NOBA Vue — it works!</div>
</template>
```

- [ ] **Step 6: Copy favicons to `public/`**

```bash
mkdir -p share/noba-web/frontend/public
cp share/noba-web/static/favicon.ico share/noba-web/frontend/public/
cp share/noba-web/static/favicon.svg share/noba-web/frontend/public/
```

- [ ] **Step 7: Create `.gitignore` before installing**

```bash
cat > share/noba-web/frontend/.gitignore << 'EOF'
node_modules/
static/dist/
EOF
```

- [ ] **Step 8: Install dependencies and verify dev server**

```bash
cd share/noba-web/frontend && npm install
npm run dev -- --host 0.0.0.0 &
sleep 3
curl -s http://localhost:5173 | head -5
kill %1
```

Expected: HTML containing `<div id="app"></div>`

- [ ] **Step 9: Verify production build**

```bash
cd share/noba-web/frontend && npm run build
ls -la ../static/dist/
```

Expected: `index.html` + `assets/` directory with JS/CSS bundles

- [ ] **Step 10: Commit**

```bash
git add share/noba-web/frontend/
git commit -m "feat(v3): scaffold Vue project with Vite"
```

Note: `.gitignore` was created in Step 7, so `node_modules/` and `static/dist/` are excluded.

---

### Task 2: Build Integration

Configure FastAPI to serve the Vue build output alongside the existing frontend. Create a build script.

**Files:**
- Create: `scripts/build-frontend.sh`
- Modify: `share/noba-web/server/app.py` (add dist/ serving)

- [ ] **Step 1: Create build script**

Create `scripts/build-frontend.sh`:

```bash
#!/bin/bash
set -e
cd "$(dirname "$0")/../share/noba-web/frontend"
echo "[build] Installing dependencies..."
npm ci --silent
echo "[build] Building Vue frontend..."
npm run build
echo "[build] Done. Output in share/noba-web/static/dist/"
```

```bash
chmod +x scripts/build-frontend.sh
```

- [ ] **Step 2: Add Vue dist serving to FastAPI**

In `share/noba-web/server/app.py`, add a route that serves the Vue app's `index.html` for a `/v3` path (for testing during migration). Read the current file first, then:

1. Add `PlainTextResponse` to the import from `fastapi.responses` if not already present
2. Add after the existing root route:

```python
# Vue frontend (Phase 2) — serves built SPA
_VUE_DIST = _WEB_DIR / "static" / "dist"

@app.get("/v3/{rest:path}")
@app.get("/v3")
async def vue_app(rest: str = ""):
    index = _VUE_DIST / "index.html"
    if index.exists():
        return FileResponse(index)
    return PlainTextResponse("Vue build not found. Run scripts/build-frontend.sh", status_code=404)

if (_VUE_DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(_VUE_DIST / "assets")), name="vue-assets")
```

- [ ] **Step 3: Keep Vite base as `/` — serve Vue at `/v3` via catch-all**

Keep `base: '/'` in `vite.config.js`. The `/v3` FastAPI route serves the same `index.html`; since we use hash-based routing (`/#/dashboard`), the browser path before `#` doesn't matter for Vue Router. The assets are mounted at `/assets` which matches the Vite default.

Update the FastAPI mount to serve assets from the dist directory:

```python
if (_VUE_DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(_VUE_DIST / "assets")), name="vue-assets")
```

Note: Import `PlainTextResponse` from `fastapi.responses` if not already imported in `app.py`.

- [ ] **Step 4: Build and verify end-to-end**

```bash
cd /home/raizen/noba && scripts/build-frontend.sh
ls share/noba-web/static/dist/index.html
```

Then verify FastAPI can serve it (start the backend and check `/v3`).

- [ ] **Step 5: Commit**

```bash
git add scripts/build-frontend.sh share/noba-web/server/app.py share/noba-web/frontend/vite.config.js
git commit -m "feat(v3): add build script and FastAPI Vue serving at /v3"
```

---

### Task 3: Global CSS Migration

Port the existing `style.css` (1681 lines) as a global stylesheet for the Vue app. The CSS variables, theme system, and component classes all transfer directly.

**Files:**
- Create: `share/noba-web/frontend/src/assets/styles/global.css`

- [ ] **Step 1: Copy and adapt style.css**

Copy the existing `share/noba-web/static/style.css` to `share/noba-web/frontend/src/assets/styles/global.css`.

Apply these minimal changes:
1. Remove `[x-cloak] { display: none !important; }` (Alpine-specific, not needed in Vue)
2. Add Vue transition classes at the end:

```css
/* Vue transitions */
.fade-enter-active, .fade-leave-active { transition: opacity .2s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }

.slide-enter-active, .slide-leave-active { transition: transform .2s ease; }
.slide-enter-from { transform: translateY(10px); }
.slide-leave-to { transform: translateY(-10px); }
```

- [ ] **Step 2: Import in main.js**

Update `share/noba-web/frontend/src/main.js`:

```js
import { createApp } from 'vue'
import App from './App.vue'
import './assets/styles/global.css'

const app = createApp(App)
app.mount('#app')
```

- [ ] **Step 3: Verify themes render correctly**

```bash
cd share/noba-web/frontend && npm run build
```

Check the built CSS includes all theme variants (dracula, nord, tokyo, catppuccin, gruvbox).

- [ ] **Step 4: Commit**

```bash
git add share/noba-web/frontend/src/assets/styles/global.css share/noba-web/frontend/src/main.js
git commit -m "feat(v3): port global CSS with themes to Vue"
```

---

### Task 4: Composables and Pinia Stores

Create the shared composables and Pinia stores that all views will use.

**Files:**
- Create: `share/noba-web/frontend/src/composables/useApi.js`
- Create: `share/noba-web/frontend/src/composables/useIntervals.js`
- Create: `share/noba-web/frontend/src/stores/auth.js`
- Create: `share/noba-web/frontend/src/stores/dashboard.js`
- Create: `share/noba-web/frontend/src/stores/settings.js`
- Create: `share/noba-web/frontend/src/stores/notifications.js`
- Modify: `share/noba-web/frontend/src/main.js` (add Pinia)

- [ ] **Step 1: Create `useApi.js`**

```js
import { ref } from 'vue'
import { useAuthStore } from '../stores/auth'

export function useApi() {
  const loading = ref(false)
  const error = ref(null)

  async function request(url, options = {}) {
    const auth = useAuthStore()
    loading.value = true
    error.value = null
    try {
      const headers = { ...options.headers }
      if (auth.token) headers['Authorization'] = `Bearer ${auth.token}`
      if (options.body && typeof options.body === 'object' && !(options.body instanceof FormData) && !(options.body instanceof Uint8Array)) {
        headers['Content-Type'] = 'application/json'
        options.body = JSON.stringify(options.body)
      }
      const res = await fetch(url, { ...options, headers })
      if (res.status === 401) {
        auth.clearAuth()
        return null
      }
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data.detail || `HTTP ${res.status}`)
      }
      const ct = res.headers.get('content-type') || ''
      if (ct.includes('application/json')) return await res.json()
      return await res.text()
    } catch (e) {
      error.value = e.message
      throw e
    } finally {
      loading.value = false
    }
  }

  const get = (url) => request(url)
  const post = (url, body) => request(url, { method: 'POST', body })
  const put = (url, body) => request(url, { method: 'PUT', body })
  const del = (url) => request(url, { method: 'DELETE' })
  const download = async (url) => {
    const auth = useAuthStore()
    const headers = {}
    if (auth.token) headers['Authorization'] = `Bearer ${auth.token}`
    const res = await fetch(url, { headers })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return res
  }

  return { request, get, post, put, del, download, loading, error }
}
```

- [ ] **Step 2: Create `useIntervals.js`**

```js
import { onUnmounted } from 'vue'

export function useIntervals() {
  const intervals = new Map()

  function register(name, fn, ms) {
    clear(name)
    intervals.set(name, setInterval(fn, ms))
  }

  function clear(name) {
    const id = intervals.get(name)
    if (id) { clearInterval(id); intervals.delete(name) }
  }

  function clearAll() {
    for (const id of intervals.values()) clearInterval(id)
    intervals.clear()
  }

  onUnmounted(clearAll)

  return { register, clear, clearAll }
}
```

- [ ] **Step 3: Create `auth.js` store**

Reference: `share/noba-web/static/auth-mixin.js` (266 lines)

```js
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem('noba-token') || '')
  const username = ref('')
  const userRole = ref('viewer')
  const authenticated = ref(!!token.value)

  const isAdmin = computed(() => userRole.value === 'admin')
  const isOperator = computed(() => userRole.value === 'operator' || isAdmin.value)

  function setToken(t) {
    token.value = t
    localStorage.setItem('noba-token', t)
    authenticated.value = true
  }

  function clearAuth() {
    token.value = ''
    username.value = ''
    userRole.value = 'viewer'
    authenticated.value = false
    localStorage.removeItem('noba-token')
  }

  async function login(user, pass) {
    const res = await fetch('/api/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: user, password: pass }),
    })
    if (!res.ok) {
      const data = await res.json().catch(() => ({}))
      throw new Error(data.detail || 'Login failed')
    }
    const data = await res.json()
    setToken(data.token)
    await fetchUserInfo()
  }

  async function logout() {
    try {
      await fetch('/api/logout', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token.value}` },
      })
    } catch { /* ignore */ }
    clearAuth()
    if (navigator.serviceWorker?.controller) {
      navigator.serviceWorker.controller.postMessage({ type: 'LOGOUT' })
    }
  }

  async function fetchUserInfo() {
    if (!token.value) return
    try {
      const res = await fetch('/api/me', {
        headers: { Authorization: `Bearer ${token.value}` },
      })
      if (res.ok) {
        const data = await res.json()
        username.value = data.username || ''
        userRole.value = data.role || 'viewer'
      } else {
        clearAuth()
      }
    } catch {
      clearAuth()
    }
  }

  return {
    token, username, userRole, authenticated,
    isAdmin, isOperator,
    setToken, clearAuth, login, logout, fetchUserInfo,
  }
})
```

- [ ] **Step 4: Create `dashboard.js` store**

Reference: `share/noba-web/static/app.js` lines 1122–1305 (SSE, polling, mergeLiveData)

This store manages the SSE connection and all live data. The LIVE_DATA_KEYS whitelist from app.js (line 154) controls which fields are accepted from the server.

```js
import { defineStore } from 'pinia'
import { ref, reactive } from 'vue'
import { useAuthStore } from './auth'

export const useDashboardStore = defineStore('dashboard', () => {
  const connStatus = ref('offline')
  const offlineMode = ref(false)

  // Live data — all fields from SSE stream
  const live = reactive({
    timestamp: 0, uptime: '', loadavg: [], memory: {},
    cpuPercent: 0, cpuTemp: null, gpuTemp: null,
    disks: [], services: [], zfs: {},
    containers: [], alerts: [],
    pihole: null, adguard: null, plex: null, radarr: null,
    sonarr: null, qbit: null, truenas: null, proxmox: null,
    unifi: null, jellyfin: null, hass: null, speedtest: null,
    k8s: null, agents: [], weather: null,
    lidarr: null, readarr: null, bazarr: null, overseerr: null,
    prowlarr: null, tautulli: null, nextcloud: null,
    traefik: null, npm: null, authentik: null, cloudflare: null,
    omv: null, xcpng: null, homebridge: null, z2m: null,
    esphome: null, piKvm: null, gitea: null, gitlab: null,
    github: null, paperless: null, vaultwarden: null,
    unifiProtect: null,
  })

  let _es = null
  let _pollInterval = null
  let _heartbeatTimer = null

  function mergeLiveData(payload) {
    for (const [key, val] of Object.entries(payload)) {
      if (key in live) live[key] = val
    }
  }

  function connectSse() {
    disconnectSse()
    const auth = useAuthStore()
    if (!auth.token) return

    const url = `/api/stream?token=${encodeURIComponent(auth.token)}`
    _es = new EventSource(url)

    _es.onopen = () => {
      connStatus.value = 'sse'
      offlineMode.value = false
      _resetHeartbeat()
    }

    _es.onmessage = (event) => {
      _resetHeartbeat()
      try { mergeLiveData(JSON.parse(event.data)) } catch { /* ignore */ }
    }

    _es.onerror = () => {
      if (_es) _es.close()
      _es = null
      connStatus.value = 'polling'
      _startPolling()
    }
  }

  function _resetHeartbeat() {
    clearTimeout(_heartbeatTimer)
    _heartbeatTimer = setTimeout(() => {
      if (_es) _es.close()
      _es = null
      connStatus.value = 'polling'
      _startPolling()
    }, 15000)
  }

  function _startPolling() {
    if (_pollInterval) return
    _pollInterval = setInterval(() => refreshStats(), 5000)
  }

  async function refreshStats() {
    const auth = useAuthStore()
    try {
      const res = await fetch('/api/stats', {
        headers: { Authorization: `Bearer ${auth.token}` },
      })
      if (res.ok) {
        const data = await res.json()
        mergeLiveData(data)
        offlineMode.value = false
        // Try SSE reconnect
        if (connStatus.value !== 'sse') connectSse()
      }
    } catch {
      offlineMode.value = true
      connStatus.value = 'offline'
    }
  }

  function disconnectSse() {
    if (_es) { _es.close(); _es = null }
    if (_pollInterval) { clearInterval(_pollInterval); _pollInterval = null }
    if (_heartbeatTimer) { clearTimeout(_heartbeatTimer); _heartbeatTimer = null }
    connStatus.value = 'offline'
  }

  return {
    connStatus, offlineMode, live,
    connectSse, disconnectSse, refreshStats, mergeLiveData,
  }
})
```

- [ ] **Step 5: Create `settings.js` store**

Reference: `share/noba-web/static/app.js` lines 1307–1523 (fetchSettings, saveSettings)

```js
import { defineStore } from 'pinia'
import { ref, reactive } from 'vue'
import { useApi } from '../composables/useApi'

export const useSettingsStore = defineStore('settings', () => {
  const loaded = ref(false)
  const data = reactive({})
  const vis = reactive({})         // Card visibility
  const preferences = reactive({}) // User layout preferences

  async function fetchSettings() {
    const { get } = useApi()
    try {
      const settings = await get('/api/settings')
      Object.assign(data, settings)
      loaded.value = true
    } catch { /* ignore */ }
  }

  async function saveSettings(updates) {
    const { post } = useApi()
    Object.assign(data, updates)
    await post('/api/settings', data)
  }

  async function fetchPreferences() {
    const { get } = useApi()
    try {
      const prefs = await get('/api/user/preferences')
      Object.assign(preferences, prefs)
      if (prefs.vis) Object.assign(vis, prefs.vis)
    } catch { /* ignore */ }
  }

  async function savePreferences() {
    const { put } = useApi()
    await put('/api/user/preferences', { ...preferences, vis: { ...vis } })
  }

  return { loaded, data, vis, preferences, fetchSettings, saveSettings, fetchPreferences, savePreferences }
})
```

- [ ] **Step 6: Create `notifications.js` store**

```js
import { defineStore } from 'pinia'
import { ref } from 'vue'

let _nextId = 0

export const useNotificationsStore = defineStore('notifications', () => {
  const toasts = ref([])

  function addToast(message, type = 'info', duration = 4000) {
    const id = ++_nextId
    toasts.value.push({ id, message, type })
    if (duration > 0) {
      setTimeout(() => removeToast(id), duration)
    }
  }

  function removeToast(id) {
    toasts.value = toasts.value.filter(t => t.id !== id)
  }

  return { toasts, addToast, removeToast }
})
```

- [ ] **Step 7: Update `main.js` with Pinia**

```js
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import './assets/styles/global.css'

const app = createApp(App)
app.use(createPinia())
app.mount('#app')
```

- [ ] **Step 8: Verify build**

```bash
cd share/noba-web/frontend && npm run build
```

Expected: Clean build with no errors.

- [ ] **Step 9: Commit**

```bash
git add share/noba-web/frontend/src/
git commit -m "feat(v3): add composables and Pinia stores (auth, dashboard, settings, notifications)"
```

---

### Task 5: App Shell + Router + Layout Components

Build the root layout (sidebar + header + router-view) and configure Vue Router with lazy-loaded routes.

**Files:**
- Replace: `share/noba-web/frontend/src/App.vue`
- Create: `share/noba-web/frontend/src/router/index.js`
- Create: `share/noba-web/frontend/src/components/layout/AppSidebar.vue`
- Create: `share/noba-web/frontend/src/components/layout/AppHeader.vue`
- Modify: `share/noba-web/frontend/src/main.js`

- [ ] **Step 1: Create `router/index.js`**

```js
import { createRouter, createWebHashHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const routes = [
  { path: '/login', name: 'login', component: () => import('../views/LoginView.vue') },
  { path: '/', redirect: '/dashboard' },
  { path: '/dashboard', name: 'dashboard', component: () => import('../views/DashboardView.vue') },
  { path: '/agents', name: 'agents', component: () => import('../views/AgentsView.vue') },
  { path: '/monitoring', name: 'monitoring', component: () => import('../views/MonitoringView.vue') },
  { path: '/infrastructure', name: 'infrastructure', component: () => import('../views/InfrastructureView.vue') },
  { path: '/automations', name: 'automations', component: () => import('../views/AutomationsView.vue') },
  { path: '/logs', name: 'logs', component: () => import('../views/LogsView.vue') },
  { path: '/security', name: 'security', component: () => import('../views/SecurityView.vue') },
  { path: '/settings/:tab?', name: 'settings', component: () => import('../views/SettingsView.vue') },
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

router.beforeEach((to) => {
  const auth = useAuthStore()
  if (to.name !== 'login' && !auth.authenticated) return { name: 'login' }
  if (to.name === 'login' && auth.authenticated) return { name: 'dashboard' }
})

export default router
```

Note: Uses hash-based history (`#/dashboard`) to match the existing URL scheme. This means old bookmarks like `#/agents` still work.

- [ ] **Step 2: Create `AppSidebar.vue`**

Reference: `share/noba-web/index.html` lines 88–160 (sidebar HTML)

Build the sidebar with navigation items matching the existing structure. Include:
- Logo section (`.app-sidebar-logo`)
- Nav items: Dashboard, Agents, Monitoring, Infrastructure, Automations, Logs, Security
- Settings sub-menu (expandable): General, Visibility, Integrations, Backup, Users, Alerts, Status Page, Shortcuts, Plugins
- User section (`.sidebar-user`): avatar, username, role badge, logout button
- Sidebar collapse behavior (`.sidebar-collapsed`)

Use `<router-link>` instead of `@click="navigateTo('...')"`. The active state is automatic via Vue Router's `router-link-active` class.

- [ ] **Step 3: Create `AppHeader.vue`**

Reference: `share/noba-web/index.html` lines 118–170 (header HTML)

Build the header bar with:
- Sidebar toggle button (mobile)
- Search button (opens SearchModal)
- Refresh button (calls `dashboardStore.refreshStats()`)
- Theme selector dropdown
- Connection status pill (`.live-pill` with `.conn-sse`/`.conn-polling`/`.conn-offline`)
- Notification bell with badge count

- [ ] **Step 4: Build `App.vue`**

```vue
<script setup>
import { ref, provide, onMounted, watch } from 'vue'
import { useAuthStore } from './stores/auth'
import { useDashboardStore } from './stores/dashboard'
import { useSettingsStore } from './stores/settings'
import AppSidebar from './components/layout/AppSidebar.vue'
import AppHeader from './components/layout/AppHeader.vue'
import ToastContainer from './components/ui/ToastContainer.vue'

const auth = useAuthStore()
const dashboard = useDashboardStore()
const settings = useSettingsStore()

const sidebarCollapsed = ref(false)
provide('sidebarCollapsed', sidebarCollapsed)
provide('toggleSidebar', () => { sidebarCollapsed.value = !sidebarCollapsed.value })

onMounted(async () => {
  // Handle OIDC callback token from URL hash (SSO login flow)
  const hash = window.location.hash
  if (hash && hash.includes('token=')) {
    const token = new URLSearchParams(hash.substring(hash.indexOf('?'))).get('token')
    if (token) {
      auth.setToken(token)
      window.history.replaceState({}, '', '/#/dashboard')
    }
  }

  if (auth.token) {
    await auth.fetchUserInfo()
    if (auth.authenticated) {
      await settings.fetchSettings()
      await settings.fetchPreferences()
      dashboard.connectSse()
    }
  }
})

watch(() => auth.authenticated, (val) => {
  if (!val) dashboard.disconnectSse()
})
</script>

<template>
  <div class="app-layout" :class="{ 'sidebar-collapsed': sidebarCollapsed }"
       :data-theme="settings.preferences.theme || 'default'">
    <template v-if="auth.authenticated">
      <AppSidebar />
      <AppHeader />
      <main class="app-main">
        <router-view />
      </main>
    </template>
    <router-view v-else />
    <ToastContainer />
  </div>
</template>
```

- [ ] **Step 5: Create placeholder view files**

Create stub `.vue` files for all views so the router doesn't break:

```vue
<!-- Template for each view stub -->
<template>
  <div class="page-content">
    <h2>PAGE_NAME</h2>
    <p>Coming soon.</p>
  </div>
</template>
```

Create stubs for: `DashboardView.vue`, `AgentsView.vue`, `MonitoringView.vue`, `InfrastructureView.vue`, `AutomationsView.vue`, `LogsView.vue`, `SecurityView.vue`, `SettingsView.vue`, `LoginView.vue`.

- [ ] **Step 6: Update `main.js` with router**

```js
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import router from './router'
import App from './App.vue'
import './assets/styles/global.css'

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.mount('#app')
```

- [ ] **Step 7: Verify navigation works**

```bash
cd share/noba-web/frontend && npm run build
```

Verify the build succeeds and all routes resolve without errors.

- [ ] **Step 8: Commit**

```bash
git add share/noba-web/frontend/src/
git commit -m "feat(v3): add App shell with sidebar, header, and Vue Router"
```

---

### Task 6: Reusable UI Components

Build the shared UI components used across all pages: modal wrapper, toast container, confirmation dialog, badge, and Chart.js wrapper.

**Files:**
- Create: `share/noba-web/frontend/src/components/ui/AppModal.vue`
- Create: `share/noba-web/frontend/src/components/ui/ToastContainer.vue`
- Create: `share/noba-web/frontend/src/components/ui/ConfirmDialog.vue`
- Create: `share/noba-web/frontend/src/components/ui/Badge.vue`
- Create: `share/noba-web/frontend/src/components/ui/ChartWrapper.vue`
- Create: `share/noba-web/frontend/src/components/ui/DataTable.vue`

- [ ] **Step 1: Create `AppModal.vue`**

Reference: Modal pattern in `share/noba-web/index.html` (`.modal-overlay > .modal-box > .modal-title + content + .modal-footer`)

```vue
<script setup>
defineProps({
  show: Boolean,
  title: { type: String, default: '' },
  width: { type: String, default: '540px' },
})
const emit = defineEmits(['close'])
</script>

<template>
  <Teleport to="body">
    <Transition name="fade">
      <div v-if="show" class="modal-overlay" @click.self="emit('close')">
        <div class="modal-box" :style="{ maxWidth: width }">
          <div v-if="title" class="modal-title">
            {{ title }}
            <button class="modal-close" @click="emit('close')" aria-label="Close">&times;</button>
          </div>
          <slot />
          <div v-if="$slots.footer" class="modal-footer">
            <slot name="footer" />
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>
```

- [ ] **Step 2: Create `ToastContainer.vue`**

```vue
<script setup>
import { useNotificationsStore } from '../../stores/notifications'
const notifs = useNotificationsStore()
</script>

<template>
  <div class="toast-container">
    <TransitionGroup name="slide">
      <div v-for="toast in notifs.toasts" :key="toast.id"
           class="toast-item" :class="'toast-' + toast.type"
           @click="notifs.removeToast(toast.id)">
        {{ toast.message }}
      </div>
    </TransitionGroup>
  </div>
</template>

<style scoped>
.toast-container {
  position: fixed; bottom: 1rem; right: 1rem; z-index: 9999;
  display: flex; flex-direction: column-reverse; gap: .5rem;
}
</style>
```

- [ ] **Step 3: Create `ConfirmDialog.vue`**

Replaces the `requestConfirm()` / `runConfirmedAction()` pattern from `actions-mixin.js` (lines 67-80).

```vue
<script setup>
import { ref } from 'vue'
import AppModal from './AppModal.vue'

const show = ref(false)
const message = ref('')
let _resolve = null

function confirm(msg) {
  message.value = msg
  show.value = true
  return new Promise((resolve) => { _resolve = resolve })
}

function handleYes() { show.value = false; if (_resolve) _resolve(true) }
function handleNo() { show.value = false; if (_resolve) _resolve(false) }

defineExpose({ confirm })
</script>

<template>
  <AppModal :show="show" title="Confirm" @close="handleNo">
    <p style="padding:1rem">{{ message }}</p>
    <template #footer>
      <button class="btn" @click="handleNo">Cancel</button>
      <button class="btn btn-danger" @click="handleYes">Confirm</button>
    </template>
  </AppModal>
</template>
```

Usage: `const ok = await confirmRef.value.confirm('Delete this item?')`

- [ ] **Step 4: Create `Badge.vue`**

```vue
<script setup>
defineProps({
  type: { type: String, default: 'info' }, // success, info, warning, danger
})
</script>

<template>
  <span class="badge" :class="'b' + type[0]"><slot /></span>
</template>
```

- [ ] **Step 5: Create `ChartWrapper.vue`**

```vue
<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue'
import { Chart, registerables } from 'chart.js'

Chart.register(...registerables)

const props = defineProps({
  config: { type: Object, required: true },
})

const canvas = ref(null)
let chart = null

function render() {
  if (chart) chart.destroy()
  if (!canvas.value) return
  chart = new Chart(canvas.value.getContext('2d'), JSON.parse(JSON.stringify(props.config)))
}

onMounted(render)
watch(() => props.config, render, { deep: true })
onUnmounted(() => { if (chart) chart.destroy() })

defineExpose({ getChart: () => chart })
</script>

<template>
  <canvas ref="canvas"></canvas>
</template>
```

- [ ] **Step 6: Create `DataTable.vue`**

Sortable, paginated table used by audit log, agent list, endpoint monitors, etc.

```vue
<script setup>
import { ref, computed } from 'vue'

const props = defineProps({
  columns: { type: Array, required: true }, // [{ key, label, sortable? }]
  rows: { type: Array, default: () => [] },
  pageSize: { type: Number, default: 50 },
})

const sortField = ref('')
const sortDir = ref('asc')
const page = ref(1)

function toggleSort(key) {
  if (sortField.value === key) { sortDir.value = sortDir.value === 'asc' ? 'desc' : 'asc' }
  else { sortField.value = key; sortDir.value = 'asc' }
}

const sorted = computed(() => {
  if (!sortField.value) return props.rows
  return [...props.rows].sort((a, b) => {
    const va = a[sortField.value], vb = b[sortField.value]
    const cmp = va < vb ? -1 : va > vb ? 1 : 0
    return sortDir.value === 'asc' ? cmp : -cmp
  })
})

const paged = computed(() => {
  const start = (page.value - 1) * props.pageSize
  return sorted.value.slice(start, start + props.pageSize)
})

const totalPages = computed(() => Math.ceil(props.rows.length / props.pageSize) || 1)
</script>

<template>
  <div>
    <table class="audit-table" style="width:100%">
      <thead>
        <tr>
          <th v-for="col in columns" :key="col.key" @click="col.sortable !== false && toggleSort(col.key)"
              style="cursor:pointer">
            {{ col.label }}
            <span v-if="sortField === col.key">{{ sortDir === 'asc' ? '▲' : '▼' }}</span>
          </th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="(row, i) in paged" :key="i">
          <td v-for="col in columns" :key="col.key">
            <slot :name="'cell-' + col.key" :row="row" :value="row[col.key]">
              {{ row[col.key] }}
            </slot>
          </td>
        </tr>
      </tbody>
    </table>
    <div v-if="totalPages > 1" style="display:flex;gap:.5rem;margin-top:.5rem;align-items:center">
      <button class="btn btn-sm" :disabled="page <= 1" @click="page--">Prev</button>
      <span>{{ page }} / {{ totalPages }}</span>
      <button class="btn btn-sm" :disabled="page >= totalPages" @click="page++">Next</button>
    </div>
  </div>
</template>
```

- [ ] **Step 7: Verify build**

```bash
cd share/noba-web/frontend && npm run build
```

- [ ] **Step 8: Commit**

```bash
git add share/noba-web/frontend/src/components/
git commit -m "feat(v3): add reusable UI components (Modal, Toast, Confirm, Badge, Chart, DataTable)"
```

---

### Task 7: Login Page

Build the login view — the first fully functional page, validating the auth flow end-to-end.

**Files:**
- Replace: `share/noba-web/frontend/src/views/LoginView.vue`

- [ ] **Step 1: Build LoginView.vue**

Reference: `share/noba-web/index.html` lines 5841–5879 (login modal), `share/noba-web/static/auth-mixin.js` lines 63–105 (doLogin)

The login page is a full-screen centered card with username + password fields and a submit button. On success, it redirects to `/dashboard` and bootstraps the app (fetch settings, connect SSE).

Key elements to include:
- NOBA logo/title
- Username + password fields with `v-model`
- Login button with loading state
- Error message display
- `@submit.prevent` on form
- On success: call `auth.login()`, then `router.push('/dashboard')`
- Keyboard: Enter key submits

- [ ] **Step 2: Verify login flow**

Start the FastAPI backend on :8080, start Vite dev server on :5173, navigate to `http://localhost:5173/#/login`, and attempt login.

- [ ] **Step 3: Commit**

```bash
git add share/noba-web/frontend/src/views/LoginView.vue
git commit -m "feat(v3): add Vue login page with auth flow"
```

---

### Task 8: Dashboard View + Card Grid

Build the dashboard page shell with the card grid system and visibility controls.

**Files:**
- Replace: `share/noba-web/frontend/src/views/DashboardView.vue`

- [ ] **Step 1: Build DashboardView.vue**

Reference: `share/noba-web/index.html` lines 224–2167 (dashboard section)

The dashboard is a responsive CSS grid of card components. Each card's visibility is controlled by `settingsStore.vis[cardKey]`.

Structure:
```vue
<script setup>
import { computed } from 'vue'
import { useSettingsStore } from '../stores/settings'
import { useDashboardStore } from '../stores/dashboard'
// Import card components (added in Tasks 9-10)

const settings = useSettingsStore()
const dashboard = useDashboardStore()

const showCard = (key) => settings.vis[key] !== false
</script>

<template>
  <div class="dashboard-page">
    <div class="card-grid" id="sortable-grid">
      <!-- Cards rendered conditionally based on visibility -->
      <SystemHealthCard v-if="showCard('system')" />
      <ContainersCard v-if="showCard('containers')" />
      <!-- ... more cards ... -->
    </div>
  </div>
</template>
```

The card grid uses CSS grid with responsive breakpoints (existing `.card-grid` class from style.css). The masonry layout behavior from the Alpine version (ResizeObserver-based) should be replicated or simplified to pure CSS grid with `grid-auto-rows: min-content`.

- [ ] **Step 2: Create a base `DashboardCard.vue` wrapper**

A wrapper component that all dashboard cards use for consistent styling:

```vue
<script setup>
import { ref } from 'vue'
defineProps({
  title: String,
  icon: String,
  collapsible: { type: Boolean, default: true },
})
const collapsed = ref(false)
</script>

<template>
  <div class="card" :class="{ collapsed }">
    <div class="card-title" @click="collapsible && (collapsed = !collapsed)">
      <i v-if="icon" :class="icon"></i> {{ title }}
      <button v-if="collapsible" class="card-collapse-btn">
        <i :class="collapsed ? 'fas fa-chevron-down' : 'fas fa-chevron-up'"></i>
      </button>
    </div>
    <div v-show="!collapsed" class="card-content">
      <slot />
    </div>
  </div>
</template>
```

- [ ] **Step 3: Verify dashboard loads with empty cards**

```bash
cd share/noba-web/frontend && npm run build
```

- [ ] **Step 4: Commit**

```bash
git add share/noba-web/frontend/src/
git commit -m "feat(v3): add dashboard view with card grid and DashboardCard wrapper"
```

---

### Task 9: Dashboard System Cards

Create the core system metric cards that display live data from the SSE stream.

**Files:**
- Create: `share/noba-web/frontend/src/components/cards/SystemHealthCard.vue`
- Create: `share/noba-web/frontend/src/components/cards/DiskCard.vue`
- Create: `share/noba-web/frontend/src/components/cards/ServicesCard.vue`
- Create: `share/noba-web/frontend/src/components/cards/ContainersCard.vue`
- Create: `share/noba-web/frontend/src/components/cards/AlertsCard.vue`
- Modify: `share/noba-web/frontend/src/views/DashboardView.vue` (import cards)

- [ ] **Step 1: Create `SystemHealthCard.vue`**

Reference: `share/noba-web/index.html` lines ~230–400 (system health section)

Displays: CPU%, memory%, load average, CPU/GPU temps, uptime. Data comes from `dashboardStore.live` (cpuPercent, memory, loadavg, cpuTemp, gpuTemp, uptime).

Pattern for reading live data:
```vue
<script setup>
import { useDashboardStore } from '../../stores/dashboard'
import DashboardCard from './DashboardCard.vue'
const dashboard = useDashboardStore()
</script>

<template>
  <DashboardCard title="System Health" icon="fas fa-heartbeat">
    <div class="health-grid">
      <div class="health-item">
        <span class="health-label">CPU</span>
        <span class="health-value">{{ dashboard.live.cpuPercent || 0 }}%</span>
      </div>
      <!-- memory, load, temps, uptime -->
    </div>
  </DashboardCard>
</template>
```

- [ ] **Step 2: Create remaining system cards**

Follow the same pattern. Each card reads from `dashboardStore.live`:

- **DiskCard**: `dashboard.live.disks` array + `dashboard.live.zfs`
- **ServicesCard**: `dashboard.live.services` array — show running/stopped with action buttons (start/stop/restart)
- **ContainersCard**: `dashboard.live.containers` array — show status + action buttons
- **AlertsCard**: `dashboard.live.alerts` array — show active alerts with severity badges

For action buttons (service control, container control), use `useApi()` to POST to `/api/service-control` or `/api/container-control`.

- [ ] **Step 3: Wire cards into DashboardView**

Import all card components and add them to the grid with `v-if="showCard('key')"`.

- [ ] **Step 4: Verify with live backend**

Start both servers, login, verify dashboard shows live data.

- [ ] **Step 5: Commit**

```bash
git add share/noba-web/frontend/src/
git commit -m "feat(v3): add dashboard system cards (health, disks, services, containers, alerts)"
```

---

### Task 10: Dashboard Integration Cards

Create cards for all external integrations (Pi-hole, Plex, Radarr, etc.).

**Files:**
- Create one `.vue` file per integration in `share/noba-web/frontend/src/components/cards/`
- Modify: `share/noba-web/frontend/src/views/DashboardView.vue`

- [ ] **Step 1: Create integration cards**

Reference: `share/noba-web/index.html` lines ~400–2167 (remaining dashboard cards)

Each integration card follows the same pattern as system cards: read from `dashboardStore.live[integrationKey]` and render the relevant data.

**Cards to create (one file each):**

| Component | Store key | Shows |
|-----------|-----------|-------|
| `PiholeCard.vue` | `pihole` | Queries, blocked %, status, toggle |
| `AdguardCard.vue` | `adguard` | Queries, blocked %, rules |
| `PlexCard.vue` | `plex` / `tautulli` | Active streams, libraries |
| `RadarrCard.vue` | `radarr` | Queue, missing, disk space |
| `SonarrCard.vue` | `sonarr` | Queue, missing, calendar |
| `LidarrCard.vue` | `lidarr` | Queue, missing |
| `ReadarrCard.vue` | `readarr` | Queue, missing |
| `QbitCard.vue` | `qbit` | Torrents, speeds |
| `TruenasCard.vue` | `truenas` | Pools, VMs, alerts |
| `ProxmoxCard.vue` | `proxmox` | Nodes, VMs, CTs |
| `UnifiCard.vue` | `unifi` | Clients, APs, alerts |
| `JellyfinCard.vue` | `jellyfin` | Active sessions |
| `HassCard.vue` | `hass` | Entities, automations |
| `SpeedtestCard.vue` | `speedtest` | Download/upload/ping |
| `WeatherCard.vue` | `weather` | Temperature, conditions |
| `OverseerrCard.vue` | `overseerr` | Pending requests |
| `NextcloudCard.vue` | `nextcloud` | Storage, users |
| `HomeAutomationCards.vue` | `z2m`, `esphome`, `homebridge` | Device counts |

Each card should null-guard its data: `v-if="dashboard.live.pihole"` on the card-content section.

Many of these cards are simple: 3-5 data fields in a grid. Reference the exact HTML from the corresponding section of `index.html` to replicate the layout.

- [ ] **Step 2: Wire all cards into DashboardView**

- [ ] **Step 3: Verify all cards render with mock/live data**

- [ ] **Step 4: Commit**

```bash
git add share/noba-web/frontend/src/
git commit -m "feat(v3): add dashboard integration cards (18 integrations)"
```

---

### Task 11: Agents View

Migrate the agents page with agent list, command palette, agent detail modal, log streaming, and deploy.

**Files:**
- Replace: `share/noba-web/frontend/src/views/AgentsView.vue`
- Create: `share/noba-web/frontend/src/components/agents/AgentDetailModal.vue`
- Create: `share/noba-web/frontend/src/components/agents/CommandPalette.vue`
- Create: `share/noba-web/frontend/src/components/agents/LogStreamModal.vue`
- Create: `share/noba-web/frontend/src/components/agents/DeployModal.vue`

- [ ] **Step 1: Build AgentsView.vue**

Reference: `share/noba-web/index.html` lines 2168–2340 (agents page)
Reference: `share/noba-web/static/integration-actions.js` lines 525–855 (agent commands, streams, deploy)

The agents page shows:
- Agent card grid (hostname, OS, CPU, memory, online status, last seen)
- Click agent → open detail modal
- Command palette (select command type, target agents, send)
- Bulk command support
- Agent deploy button (SSH-based)

Key API endpoints:
- Agents data comes from `dashboardStore.live.agents` (SSE)
- `POST /api/agents/{hostname}/command` — send command
- `POST /api/agents/bulk-command` — bulk send
- `GET /api/agents/{hostname}` — detail
- `GET /api/agents/{hostname}/results` — command results
- `POST /api/agents/deploy` — SSH deploy
- `POST /api/agents/{hostname}/stream-logs` — start log stream
- `GET /api/agents/{hostname}/stream/{cmd_id}` — poll stream

- [ ] **Step 2: Build sub-components**

- **AgentDetailModal**: Agent metrics detail + command results + history chart
- **CommandPalette**: Command type dropdown, params input, target selection
- **LogStreamModal**: Live log output with auto-scroll, stop button
- **DeployModal**: Form with host, SSH user, SSH pass, port, deploy button

- [ ] **Step 3: Verify agent interactions**

- [ ] **Step 4: Commit**

```bash
git add share/noba-web/frontend/src/
git commit -m "feat(v3): add agents view with commands, detail, streams, deploy"
```

---

### Task 12: Monitoring View

Migrate the monitoring page with endpoint monitors, uptime dashboard, health score, and status page management.

**Files:**
- Replace: `share/noba-web/frontend/src/views/MonitoringView.vue`
- Create sub-components as needed in `share/noba-web/frontend/src/components/monitoring/`

- [ ] **Step 1: Build MonitoringView.vue**

Reference: `share/noba-web/index.html` lines 2341–2733 (monitoring page)
Reference: `share/noba-web/static/system-actions.js` lines 1731+ (endpoint CRUD)
Reference: `share/noba-web/static/integration-actions.js` lines 511–520 (alert history)

The monitoring page has tabs:
- **SLA**: SLA summary table (`GET /api/sla/summary`)
- **Incidents**: Incident list with war room (`GET /api/incidents`, message/assign endpoints)
- **Correlation**: Metric correlation chart
- **Graylog/InfluxDB**: External integration panels
- **Custom Charts**: Multi-metric dashboard
- **Endpoints**: HTTP endpoint monitor CRUD table

Key endpoints:
- `GET /api/endpoints` — list monitors
- `POST /api/endpoints` — create monitor
- `PUT /api/endpoints/{id}` — update
- `DELETE /api/endpoints/{id}` — delete
- `POST /api/endpoints/{id}/check` — manual check
- `GET /api/uptime` — uptime dashboard
- `GET /api/health-score` — composite health score
- `GET /api/status/components` — status page components (admin)
- `GET /api/status/public` — public status page

- [ ] **Step 2: Build tab sub-components**

Each tab as a separate component within `components/monitoring/`.

- [ ] **Step 3: Commit**

```bash
git add share/noba-web/frontend/src/
git commit -m "feat(v3): add monitoring view with endpoints, uptime, SLA, incidents"
```

---

### Task 13: Infrastructure View

Migrate the infrastructure page with services, network, K8s, Proxmox, topology, and traffic analysis.

**Files:**
- Replace: `share/noba-web/frontend/src/views/InfrastructureView.vue`
- Create sub-components in `share/noba-web/frontend/src/components/infrastructure/`

- [ ] **Step 1: Build InfrastructureView.vue**

Reference: `share/noba-web/index.html` lines 2734–3235 (infrastructure page)
Reference: `share/noba-web/static/integration-actions.js` lines 306–450 (K8s, Proxmox, compose)
Reference: `share/noba-web/static/system-actions.js` (service map, disk prediction, network)

The infrastructure page has tabs:
- **Services**: systemd service list with start/stop/restart
- **Service Map**: Auto-discovered service dependency graph
- **Topology**: Network topology SVG
- **Tailscale**: Tailscale devices
- **Cross-Site Sync**: Site sync status
- **Config Drift**: Baseline drift detection
- **Export**: IaC export (YAML/JSON)
- **Traffic**: Network traffic analysis per agent
- **Network Map**: Discovered network devices

Key endpoints:
- `GET /api/network/connections`, `GET /api/network/ports`, `GET /api/network/interfaces`
- `GET /api/services/map`, `GET /api/disks/prediction`
- `GET /api/k8s/namespaces`, `/api/k8s/pods`, `/api/k8s/deployments`
- `GET /api/proxmox/nodes/{node}/vms/{vmid}/snapshots`
- `GET /api/network/devices`, `POST /api/network/discover/{hostname}`

- [ ] **Step 2: Build tab sub-components**

- [ ] **Step 3: Commit**

```bash
git add share/noba-web/frontend/src/
git commit -m "feat(v3): add infrastructure view with services, K8s, Proxmox, network"
```

---

### Task 14: Automations View

Migrate the automations page with CRUD, run execution, templates, and workflow trace.

**Files:**
- Replace: `share/noba-web/frontend/src/views/AutomationsView.vue`
- Create sub-components in `share/noba-web/frontend/src/components/automations/`

- [ ] **Step 1: Build AutomationsView.vue**

Reference: `share/noba-web/index.html` lines 3236–3351 (automations page)
Reference: `share/noba-web/static/automation-actions.js` (430 lines — all automation logic)

Features:
- Automation list with filter (type, search) and CRUD
- Create/edit modal with form (name, type, config, schedule, enabled)
- Template picker (load from `/api/automations/templates`)
- Run automation with live output polling
- Workflow trace visualization
- Import/export YAML
- Webhook section (create, list, trigger)
- Job notification poller (background check for completed runs)

Key endpoints:
- `GET /api/automations` — list
- `POST /api/automations` — create
- `PUT /api/automations/{id}` — update
- `DELETE /api/automations/{id}` — delete
- `POST /api/automations/{id}/run` — execute
- `GET /api/automations/templates` — templates
- `GET /api/automations/export` / `POST /api/automations/import` — import/export

- [ ] **Step 2: Build AutomationFormModal sub-component**

- [ ] **Step 3: Commit**

```bash
git add share/noba-web/frontend/src/
git commit -m "feat(v3): add automations view with CRUD, run, templates, workflow"
```

---

### Task 15: Logs View + Security View

Migrate the two simpler pages: log viewer and security posture.

**Files:**
- Replace: `share/noba-web/frontend/src/views/LogsView.vue`
- Replace: `share/noba-web/frontend/src/views/SecurityView.vue`

- [ ] **Step 1: Build LogsView.vue**

Reference: `share/noba-web/index.html` lines 3352–3497 (logs page)
Reference: `share/noba-web/static/actions-mixin.js` lines 38–61 (fetchLog)

Tabs:
- **System Log**: Log type selector + log content display (`GET /api/log-viewer?type=`)
- **Command History**: Table of agent command history (`GET /api/agents/command-history`)
- **Audit Log**: Paginated audit table (`GET /api/audit`)
- **Journal**: systemd journal viewer (`GET /api/journal`)
- **Live Stream**: Agent log streaming (reuse LogStreamModal from Task 11)

- [ ] **Step 2: Build SecurityView.vue**

Reference: `share/noba-web/index.html` lines 3498–3619 (security page)
Reference: `share/noba-web/static/system-actions.js` (security score chart)

Features:
- Overall security score with Chart.js donut
- Per-agent scan results table
- Findings list with severity + remediation
- Security history chart
- Scan/scan-all buttons
- Security score drill-down

Key endpoints:
- `GET /api/security/score` — aggregate score
- `GET /api/security/findings` — finding list
- `GET /api/security/history` — score history
- `POST /api/security/scan/{hostname}` — trigger scan
- `POST /api/security/scan-all` — scan all agents

- [ ] **Step 3: Commit**

```bash
git add share/noba-web/frontend/src/views/
git commit -m "feat(v3): add logs and security views"
```

---

### Task 16: Settings View

Migrate the settings page with all 9 sub-tabs. This is the largest view due to the number of configuration forms.

**Files:**
- Replace: `share/noba-web/frontend/src/views/SettingsView.vue`
- Create tab components in `share/noba-web/frontend/src/components/settings/`

- [ ] **Step 1: Build SettingsView.vue shell**

Reference: `share/noba-web/index.html` lines 3622–5840 (settings sections)
Reference: `share/noba-web/static/app.js` lines 1307–1523 (settings management)

The settings view reads the `:tab` route param and renders the corresponding sub-component:

```vue
<script setup>
import { computed, defineAsyncComponent } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const tab = computed(() => route.params.tab || 'general')

const tabs = [
  { key: 'general', label: 'General', icon: 'fa-database' },
  { key: 'visibility', label: 'Visibility', icon: 'fa-eye' },
  { key: 'integrations', label: 'Integrations', icon: 'fa-plug' },
  { key: 'backup', label: 'Backup', icon: 'fa-archive' },
  { key: 'users', label: 'Users', icon: 'fa-users', admin: true },
  { key: 'alerts', label: 'Alerts', icon: 'fa-bell' },
  { key: 'statuspage', label: 'Status Page', icon: 'fa-signal' },
  { key: 'shortcuts', label: 'Shortcuts', icon: 'fa-keyboard' },
  { key: 'plugins', label: 'Plugins', icon: 'fa-puzzle-piece' },
]

const tabComponents = {
  general: defineAsyncComponent(() => import('../components/settings/GeneralTab.vue')),
  visibility: defineAsyncComponent(() => import('../components/settings/VisibilityTab.vue')),
  integrations: defineAsyncComponent(() => import('../components/settings/IntegrationsTab.vue')),
  backup: defineAsyncComponent(() => import('../components/settings/BackupTab.vue')),
  users: defineAsyncComponent(() => import('../components/settings/UsersTab.vue')),
  alerts: defineAsyncComponent(() => import('../components/settings/AlertsTab.vue')),
  statuspage: defineAsyncComponent(() => import('../components/settings/StatusPageTab.vue')),
  shortcuts: defineAsyncComponent(() => import('../components/settings/ShortcutsTab.vue')),
  plugins: defineAsyncComponent(() => import('../components/settings/PluginsTab.vue')),
}

const tabComponent = computed(() => tabComponents[tab.value])
</script>

<template>
  <div class="settings-page">
    <h2><i :class="'fas ' + (tabs.find(t=>t.key===tab)?.icon||'fa-cog')"></i> Settings — {{ tab }}</h2>
    <component :is="tabComponent" />
  </div>
</template>
```

- [ ] **Step 2: Create sub-tab components**

One component per tab in `components/settings/`:

| Component | Tab | Key features |
|-----------|-----|-------------|
| `GeneralTab.vue` | general | Host settings, monitored services, bookmarks, agent keys |
| `VisibilityTab.vue` | visibility | Toggle checkboxes for each dashboard card |
| `IntegrationsTab.vue` | integrations | URL/credential forms for all 40+ integrations |
| `BackupTab.vue` | backup | Backup sources, destinations, schedules, cloud remotes, 3-2-1 status |
| `UsersTab.vue` | users | User list, add/remove/change password (admin only) |
| `AlertsTab.vue` | alerts | Alert rule builder, test rules, notification channels |
| `StatusPageTab.vue` | statuspage | Status page component CRUD, incident management |
| `ShortcutsTab.vue` | shortcuts | Custom keyboard shortcut configuration |
| `PluginsTab.vue` | plugins | Plugin list with enable/disable |

The **IntegrationsTab** is the largest — it contains forms for ~40 integrations. Reference `share/noba-web/index.html` lines 4186+ for the integration form fields. Each integration is a collapsible section with URL + credential inputs.

- [ ] **Step 3: Commit**

```bash
git add share/noba-web/frontend/src/
git commit -m "feat(v3): add settings view with all 9 sub-tabs"
```

---

### Task 17: Global Modals

Migrate the shared modals that are used across multiple pages.

**Files:**
- Create modals in `share/noba-web/frontend/src/components/modals/`
- Modify: `share/noba-web/frontend/src/App.vue` (mount global modals)

- [ ] **Step 1: Create global modal components**

Reference: `share/noba-web/index.html` lines 3640–6945 (modal sections)
Reference: `share/noba-web/static/system-actions.js` (modal methods)

| Component | Reference | Features |
|-----------|-----------|----------|
| `HistoryModal.vue` | L3682–3745, system-actions L145–265 | Metric history Chart.js line chart, range selector, CSV export |
| `AuditModal.vue` | L3747–3805, system-actions L275–340 | Paginated audit table with sort, CSV export |
| `SmartModal.vue` | L3806–3887, system-actions L575–616 | SMART disk health table with risk scores |
| `BackupExplorerModal.vue` | system-actions L617–763 | Snapshot list, file browser, diff view, restore |
| `SystemInfoModal.vue` | system-actions | OS, hardware, CPU info |
| `ProcessModal.vue` | system-actions | Process list table |
| `NetworkModal.vue` | system-actions | Network connections + listening ports tables |
| `MultiMetricModal.vue` | system-actions L862–936 | Multi-metric Chart.js chart, metric picker |
| `RunHistoryModal.vue` | L3910–3951, actions-mixin L177–196 | Script execution history table |
| `TerminalModal.vue` | L3641–3649 | WebSocket terminal (xterm.js) |
| `ProfileModal.vue` | system-actions L1508–1643 | User profile, change password, TOTP setup, API keys |
| `RunOutputModal.vue` | actions-mixin L89–171 | Live script output with polling |
| `SearchModal.vue` | L174–220 | Global search overlay |

Global modals should be mounted in `App.vue` and their visibility controlled via a provide/inject pattern or a dedicated modal store.

- [ ] **Step 2: Build each modal**

Each modal uses `AppModal` as wrapper and implements its specific content. The `HistoryModal` and `MultiMetricModal` use `ChartWrapper` for Chart.js integration.

- [ ] **Step 3: Commit**

```bash
git add share/noba-web/frontend/src/
git commit -m "feat(v3): add global modals (history, audit, SMART, backup, terminal, profile)"
```

---

### Task 18: Service Worker + PWA

Update the service worker for Vite-built assets and configure PWA manifest.

**Files:**
- Create: `share/noba-web/frontend/public/service-worker.js`
- Create: `share/noba-web/frontend/public/manifest.json`
- Modify: `share/noba-web/frontend/index.html` (register SW + manifest link)

- [ ] **Step 1: Adapt service worker**

Reference: `share/noba-web/service-worker.js` (158 lines)

Port the existing service worker with these changes:
- Update `STATIC_ASSETS` list to match Vite build output (hashed filenames handled by cache-first strategy)
- Keep network-first strategy for `/api/*` endpoints
- Keep SSE bypass for `/api/stream`
- Keep LOGOUT message handler
- Keep push notification handler
- Update cache name to `noba-v4` to force cache refresh

- [ ] **Step 2: Add manifest.json**

```json
{
  "name": "NOBA Command Center",
  "short_name": "NOBA",
  "start_url": "/v3/",
  "display": "standalone",
  "background_color": "#060a10",
  "theme_color": "#00c8ff",
  "icons": [
    { "src": "/favicon.svg", "sizes": "any", "type": "image/svg+xml" }
  ]
}
```

- [ ] **Step 3: Register in index.html**

Add `<link rel="manifest" href="/manifest.json">` and service worker registration script.

- [ ] **Step 4: Commit**

```bash
git add share/noba-web/frontend/public/
git commit -m "feat(v3): add service worker and PWA manifest for Vue app"
```

---

### Task 19: Switchover — Remove Old Frontend + Final Build

The atomic switchover: update FastAPI to serve the Vue build as the default frontend, remove the `/v3` prefix, delete old Alpine.js files, and commit the production build.

**Files:**
- Modify: `share/noba-web/server/app.py` (switch root to Vue)
- Modify: `share/noba-web/frontend/vite.config.js` (set `base: '/'`)
- Delete: `share/noba-web/index.html`
- Delete: `share/noba-web/static/app.js`
- Delete: `share/noba-web/static/auth-mixin.js`
- Delete: `share/noba-web/static/actions-mixin.js`
- Delete: `share/noba-web/static/system-actions.js`
- Delete: `share/noba-web/static/integration-actions.js`
- Delete: `share/noba-web/static/automation-actions.js`
- Delete: `share/noba-web/service-worker.js`
- Commit: `share/noba-web/static/dist/` (production build)

- [ ] **Step 1: Verify Vite base path is `/`**

Confirm `vite.config.js` has `base: '/'` (should already be set from Task 2). Also update `manifest.json` start_url from `/v3/` to `/`:

```json
"start_url": "/"
```

- [ ] **Step 2: Run production build**

```bash
cd share/noba-web/frontend && npm run build
ls -la ../static/dist/
```

- [ ] **Step 3: Update FastAPI to serve Vue as root**

In `share/noba-web/server/app.py`:
- Change the root route (`/`) to serve `static/dist/index.html`
- Mount `static/dist/assets/` for JS/CSS bundles
- Remove the `/v3` temporary routes
- Keep existing `/static/` mount for non-JS assets (favicon, etc.) that may still be referenced

```python
_VUE_DIST = _WEB_DIR / "static" / "dist"

@app.get("/")
@app.get("/{rest:path}")
async def spa_fallback(rest: str = ""):
    # Serve API routes normally (they're mounted before this catch-all)
    # Serve static files normally
    # Everything else gets the SPA index.html
    return FileResponse(_VUE_DIST / "index.html")
```

Important: This catch-all route must be registered AFTER all API routes and static mounts.

- [ ] **Step 4: Delete old Alpine.js frontend files**

```bash
git rm share/noba-web/index.html
git rm share/noba-web/static/app.js
git rm share/noba-web/static/auth-mixin.js
git rm share/noba-web/static/actions-mixin.js
git rm share/noba-web/static/system-actions.js
git rm share/noba-web/static/integration-actions.js
git rm share/noba-web/static/automation-actions.js
git rm share/noba-web/service-worker.js
```

Keep: `style.css` (still referenced by old tests/service-worker if needed), `favicon.ico`, `favicon.svg`.

- [ ] **Step 5: Commit the Vue build output**

Remove `static/dist/` from `.gitignore` and commit the built files so end users don't need Node.js:

```bash
# Remove dist/ from gitignore
sed -i '/static\/dist/d' share/noba-web/frontend/.gitignore
git add share/noba-web/static/dist/
```

- [ ] **Step 6: Run full backend test suite**

```bash
pytest tests/ -v --tb=short 2>&1 | tail -10
```

Expected: All tests pass (some test fixtures may need updating if they reference old static files).

- [ ] **Step 7: Verify the app loads**

Start the FastAPI server and verify:
- `/` serves the Vue SPA
- `/#/login` shows the login page
- After login, `/#/dashboard` shows live data
- All pages navigate correctly
- SSE connection works
- Theme switching works

- [ ] **Step 8: Update CHANGELOG.md**

Add under `[Unreleased]`:

```markdown
### Changed
- **Vue.js migration (v3 Phase 2)** — Replaced Alpine.js frontend (6945-line index.html + 6 JS mixins) with Vue 3 + Vite SPA. 16 pages migrated to lazy-loaded Vue components with Pinia state management. Mobile responsive layout. Old frontend files deleted.
```

- [ ] **Step 9: Commit**

```bash
git add share/noba-web/ CHANGELOG.md
git commit -m "feat(v3): complete Vue.js migration, remove Alpine.js frontend

Phase 2 complete:
- Vue 3 + Vite + Vue Router + Pinia
- 16 pages as lazy-loaded Vue components
- Pinia stores: auth, dashboard (SSE), settings, notifications
- Reusable UI: Modal, Toast, Confirm, Badge, ChartWrapper
- 20+ dashboard cards, 13+ global modals
- Mobile responsive with collapsible sidebar
- PWA service worker updated
- Old Alpine.js files removed"
```

---

## Verification Checklist (Post-Migration)

After completing all tasks, verify:

- [ ] All 16 pages render correctly (dashboard, agents, monitoring, infrastructure, automations, logs, security, settings/*)
- [ ] Login/logout flow works
- [ ] SSE live data updates in real-time
- [ ] Polling fallback works when SSE disconnects
- [ ] All dashboard cards show data
- [ ] Service/container control actions work
- [ ] Agent commands send and results display
- [ ] Automation CRUD + run works
- [ ] Settings save and persist
- [ ] Theme switching works (all 6 themes)
- [ ] Mobile responsive layout (sidebar collapse, card stacking)
- [ ] Chart.js charts render (history, multi-metric, security score)
- [ ] Modals open/close correctly
- [ ] Toast notifications appear
- [ ] Keyboard shortcuts work
- [ ] `npm run build` produces clean output
- [ ] Backend tests still pass (783+)
- [ ] No console errors in browser
