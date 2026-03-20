# Sidebar Navigation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the modal-heavy navigation with a persistent left sidebar, compact header with global search, hash-based page routing, and an SVG favicon — transforming the UI into a proper ops center.

**Architecture:** CSS Grid layout (`sidebar | header+content`), Alpine.js hash-based routing via `currentPage` state, sidebar with icon-only collapse persisted in localStorage, modals converted to page-level `x-show` blocks. Existing card grid, SSE, themes, and all 445 backend tests unchanged.

**Tech Stack:** Alpine.js, vanilla CSS (existing theme variables), hash-based routing (no dependencies)

**Spec:** `docs/superpowers/specs/2026-03-20-sidebar-nav-design.md`

---

## File Structure

### Modify:
- `share/noba-web/static/style.css` — New `.app-layout` grid, sidebar styles, header shrink, collapse mode, remove `.page` max-width
- `share/noba-web/index.html` — Wrap in grid layout, add sidebar HTML, shrink header, wrap content sections in `x-show` page blocks, move modals to pages
- `share/noba-web/static/app.js` — Add `currentPage`, `sidebarCollapsed`, `sidebarSettingsExpanded`, `searchOpen`, routing in `init()`, `navigateTo()`, expose CMD constants, Ctrl+K handler, masonry re-trigger
- `share/noba-web/static/auth-mixin.js` — `logout()` clears hash route
- `share/noba-web/static/system-actions.js` — Modal flags become page navigation where applicable
- `share/noba-web/static/integration-actions.js` — Agent modal flag becomes page navigation
- `share/noba-web/static/automation-actions.js` — Automation modal becomes page navigation
- `share/noba-web/service-worker.js` — Update `STATIC_ASSETS` cache list

### Create:
- `share/noba-web/static/favicon.svg` — NOBA branded favicon

---

### Task 1: CSS Layout Foundation

**Files:**
- Modify: `share/noba-web/static/style.css`

- [ ] **Step 1: Add CSS custom properties and app-layout grid**

Add to the `:root` section (after existing token definitions):

```css
:root {
    --sidebar-width: 220px;
    --sidebar-collapsed-width: 56px;
    --header-height: 48px;
}
```

Add new layout layer styles (in the `layout` layer):

```css
/* ── App Layout Grid ── */
.app-layout {
    display: grid;
    grid-template-columns: var(--sidebar-width) 1fr;
    grid-template-rows: var(--header-height) 1fr;
    height: 100vh;
    overflow: hidden;
}
.app-layout.sidebar-collapsed {
    grid-template-columns: var(--sidebar-collapsed-width) 1fr;
}
.app-layout.no-sidebar {
    grid-template-columns: 1fr;
}
```

- [ ] **Step 2: Add sidebar styles**

```css
/* ── Sidebar ── */
.app-sidebar {
    grid-row: 1 / -1;
    background: var(--surface);
    border-right: 1px solid var(--border);
    display: flex;
    flex-direction: column;
    overflow: hidden;
    transition: width 0.2s ease;
    z-index: 45;
}
.app-sidebar-logo {
    padding: 12px 16px;
    display: flex;
    align-items: center;
    gap: 10px;
    border-bottom: 1px solid var(--border);
    height: var(--header-height);
    flex-shrink: 0;
}
.app-sidebar-logo .logo-icon {
    width: 28px; height: 28px; border-radius: 6px;
    background: linear-gradient(135deg, var(--accent), var(--success));
    display: flex; align-items: center; justify-content: center;
    font-weight: 800; font-size: 12px; color: var(--bg); flex-shrink: 0;
}
.app-sidebar-logo .logo-text { font-weight: 700; font-size: 14px; white-space: nowrap; }
.app-sidebar-logo .logo-ver { font-size: 9px; opacity: .4; margin-left: auto; }
.sidebar-collapsed .app-sidebar .logo-text,
.sidebar-collapsed .app-sidebar .logo-ver { display: none; }

.app-sidebar-nav {
    flex: 1; padding: 8px; overflow-y: auto; overflow-x: hidden;
}
.sidebar-nav-item {
    display: flex; align-items: center; gap: 10px;
    padding: 8px 12px; border-radius: 6px;
    color: var(--text-muted); cursor: pointer;
    font-size: 13px; white-space: nowrap;
    transition: background 0.15s, color 0.15s;
    margin-bottom: 2px;
}
.sidebar-nav-item:hover { background: color-mix(in srgb, var(--accent) 8%, transparent); color: var(--text); }
.sidebar-nav-item.active { background: color-mix(in srgb, var(--accent) 12%, transparent); color: var(--accent); font-weight: 600; }
.sidebar-nav-item .nav-icon { width: 20px; text-align: center; font-size: 13px; flex-shrink: 0; }
.sidebar-nav-item .nav-label { overflow: hidden; text-overflow: ellipsis; }
.sidebar-nav-item .nav-badge {
    margin-left: auto; background: var(--success); color: var(--bg);
    padding: 1px 6px; border-radius: 10px; font-size: 10px; font-weight: 600; flex-shrink: 0;
}
.sidebar-collapsed .sidebar-nav-item .nav-label,
.sidebar-collapsed .sidebar-nav-item .nav-badge { display: none; }
.sidebar-collapsed .sidebar-nav-item { justify-content: center; padding: 8px; }

.sidebar-divider { border-top: 1px solid var(--border); margin: 8px 4px; }

/* Settings sub-items */
.sidebar-sub-items { padding-left: 20px; }
.sidebar-sub-item {
    display: block; padding: 5px 12px; border-radius: 4px;
    font-size: 12px; color: var(--text-muted); cursor: pointer;
    white-space: nowrap; margin-bottom: 1px;
}
.sidebar-sub-item:hover { color: var(--text); background: color-mix(in srgb, var(--accent) 6%, transparent); }
.sidebar-sub-item.active { color: var(--accent); font-weight: 600; }
.sidebar-collapsed .sidebar-sub-items { display: none; }

/* User section */
.sidebar-user {
    padding: 12px 16px; border-top: 1px solid var(--border);
    display: flex; align-items: center; gap: 10px; flex-shrink: 0;
}
.sidebar-user-avatar {
    width: 28px; height: 28px; border-radius: 50%; background: var(--surface-2);
    display: flex; align-items: center; justify-content: center;
    font-size: 11px; font-weight: 600; flex-shrink: 0;
}
.sidebar-user-info { flex: 1; min-width: 0; overflow: hidden; }
.sidebar-user-name { font-size: 12px; font-weight: 600; }
.sidebar-user-role { font-size: 10px; opacity: .4; }
.sidebar-collapsed .sidebar-user-info { display: none; }
.sidebar-collapsed .sidebar-user { justify-content: center; padding: 12px 8px; }
```

- [ ] **Step 3: Add compact header styles**

```css
/* ── Compact Header ── */
.app-header {
    grid-column: 2;
    height: var(--header-height);
    padding: 0 16px;
    display: flex; align-items: center; gap: 12px;
    border-bottom: 1px solid var(--border);
    background: var(--surface);
    z-index: 40;
}
.app-header .header-search {
    flex: 1; max-width: 400px; position: relative;
}
.app-header .header-search input {
    width: 100%; padding: 6px 12px 6px 32px;
    background: var(--bg); border: 1px solid var(--border);
    border-radius: 6px; color: var(--text); font-size: 12px;
}
.app-header .header-search .search-icon {
    position: absolute; left: 10px; top: 50%; transform: translateY(-50%);
    opacity: .3; font-size: 11px;
}
.app-header .header-search .search-kbd {
    position: absolute; right: 8px; top: 50%; transform: translateY(-50%);
    font-size: 9px; opacity: .3; padding: 1px 5px;
    border: 1px solid var(--border); border-radius: 3px;
}
```

- [ ] **Step 4: Add content area and mobile sidebar styles**

```css
/* ── Content Area ── */
.app-content {
    grid-column: 2; overflow-y: auto; padding: 16px 20px;
}
.app-content .page-section { display: none; }
.app-content .page-section.active { display: block; }

/* ── Mobile: sidebar slide-over ── */
@media (max-width: 640px) {
    .app-layout { grid-template-columns: 1fr; }
    .app-sidebar {
        position: fixed; top: 0; left: 0; bottom: 0;
        width: var(--sidebar-width); z-index: 1100;
        transform: translateX(-100%);
        transition: transform 0.25s ease;
    }
    .app-sidebar.mobile-open { transform: translateX(0); }
    .sidebar-backdrop {
        display: none; position: fixed; inset: 0;
        background: rgba(0,0,0,.5); z-index: 1099;
    }
    .sidebar-backdrop.show { display: block; }
    .app-header { grid-column: 1; }
    .app-content { grid-column: 1; padding-bottom: 80px; }
}
```

- [ ] **Step 5: Verify and commit**

```bash
node -e "require('fs').readFileSync('share/noba-web/static/style.css','utf8')" && echo "CSS OK"
git add share/noba-web/static/style.css
git commit -m "feat(ui): add sidebar navigation CSS foundation"
```

---

### Task 2: Alpine.js State + Hash Routing

**Files:**
- Modify: `share/noba-web/static/app.js`

- [ ] **Step 1: Add routing state variables**

Add to the component state (around line 274, near `settingsTab`):

```javascript
// Sidebar navigation (Phase: sidebar-nav)
currentPage: location.hash.replace('#/', '') || 'dashboard',
sidebarCollapsed: localStorage.getItem('noba-sidebar-collapsed') === 'true',
sidebarSettingsExpanded: false,
searchOpen: false,
searchQuery: '',
```

- [ ] **Step 2: Add navigateTo() method and hashchange listener**

Add in the `init()` method (around line 598), after existing init calls:

```javascript
// Hash-based page routing
window.addEventListener('hashchange', () => {
    this.currentPage = location.hash.replace('#/', '') || 'dashboard';
});
// Sidebar collapse persistence
this.$watch('sidebarCollapsed', (val) => {
    localStorage.setItem('noba-sidebar-collapsed', val);
});
```

Add a new method `navigateTo` (near the other navigation methods):

```javascript
navigateTo(page) {
    location.hash = '#/' + page;
    // Auto-close sidebar on mobile
    if (window.innerWidth < 640) this.sidebarCollapsed = true;
},
```

- [ ] **Step 3: Update initKeyboard() for Ctrl+K**

In `initKeyboard()` (line 707), add a modifier-key handler BEFORE the existing early return:

```javascript
// Global search: Ctrl+K
if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
    e.preventDefault();
    this.searchOpen = !this.searchOpen;
    return;
}
```

Update the `s` shortcut to navigate instead of opening modal:
```javascript
// Change: 's': () => { this.showSettings = true; this.settingsTab = 'visibility'; }
// To:     's': () => { this.navigateTo('settings/general'); }
```

- [ ] **Step 4: Add masonry re-trigger on dashboard navigation**

In the `hashchange` listener or in a `$watch` on `currentPage`:

```javascript
this.$watch('currentPage', (page) => {
    if (page === 'dashboard') {
        this.$nextTick(() => { try { this.initMasonry(); } catch(e) {} });
    }
});
```

- [ ] **Step 5: Verify and commit**

```bash
node -e "new Function(require('fs').readFileSync('share/noba-web/static/app.js','utf8'))"
git add share/noba-web/static/app.js
git commit -m "feat(ui): add hash routing, sidebar state, Ctrl+K handler"
```

---

### Task 3: HTML Layout Shell — Sidebar + Header + Content Wrapper

**Files:**
- Modify: `share/noba-web/index.html`

This is the core structural change. The existing `<div class="page">` becomes the content area inside a CSS Grid layout.

- [ ] **Step 1: Add app-layout grid wrapper**

Replace the `<div class="page">` wrapper (line 51) with the new grid layout. Add sidebar HTML and shrink the header. The structure becomes:

```html
<div class="app-layout" :class="{ 'sidebar-collapsed': sidebarCollapsed, 'no-sidebar': !authenticated }">
    <!-- Sidebar -->
    <aside class="app-sidebar" :class="{ 'mobile-open': !sidebarCollapsed }" x-show="authenticated" x-cloak>
        <!-- Logo -->
        <div class="app-sidebar-logo">
            <div class="logo-icon">N</div>
            <span class="logo-text">NOBA</span>
            <span class="logo-ver">v2.0</span>
        </div>
        <!-- Navigation -->
        <nav class="app-sidebar-nav">
            <div class="sidebar-nav-item" :class="{ active: currentPage === 'dashboard' }" @click="navigateTo('dashboard')">
                <i class="fas fa-th-large nav-icon"></i><span class="nav-label">Dashboard</span>
            </div>
            <div class="sidebar-nav-item" :class="{ active: currentPage === 'agents' }" @click="navigateTo('agents')">
                <i class="fas fa-robot nav-icon"></i><span class="nav-label">Agents</span>
                <span class="nav-badge" x-show="(agents||[]).filter(a=>a.online).length" x-text="(agents||[]).filter(a=>a.online).length"></span>
            </div>
            <div class="sidebar-nav-item" :class="{ active: currentPage.startsWith('monitoring') }" @click="navigateTo('monitoring')">
                <i class="fas fa-chart-line nav-icon"></i><span class="nav-label">Monitoring</span>
            </div>
            <div class="sidebar-nav-item" :class="{ active: currentPage.startsWith('infrastructure') }" @click="navigateTo('infrastructure')">
                <i class="fas fa-server nav-icon"></i><span class="nav-label">Infrastructure</span>
            </div>
            <div class="sidebar-nav-item" :class="{ active: currentPage === 'automations' }" @click="navigateTo('automations')">
                <i class="fas fa-bolt nav-icon"></i><span class="nav-label">Automations</span>
            </div>
            <div class="sidebar-nav-item" :class="{ active: currentPage === 'logs' }" @click="navigateTo('logs')">
                <i class="fas fa-scroll nav-icon"></i><span class="nav-label">Logs</span>
            </div>
            <div class="sidebar-divider"></div>
            <!-- Settings expandable -->
            <div class="sidebar-nav-item" :class="{ active: currentPage.startsWith('settings') }" @click="sidebarSettingsExpanded = !sidebarSettingsExpanded; if(!currentPage.startsWith('settings')) navigateTo('settings/general')">
                <i class="fas fa-cog nav-icon"></i><span class="nav-label">Settings</span>
                <i class="fas nav-label" :class="sidebarSettingsExpanded ? 'fa-chevron-down' : 'fa-chevron-right'" style="font-size:9px;opacity:.4;margin-left:auto"></i>
            </div>
            <div class="sidebar-sub-items" x-show="sidebarSettingsExpanded" x-collapse>
                <span class="sidebar-sub-item" :class="{ active: currentPage === 'settings/general' }" @click="navigateTo('settings/general')">General</span>
                <span class="sidebar-sub-item" :class="{ active: currentPage === 'settings/visibility' }" @click="navigateTo('settings/visibility')">Visibility</span>
                <span class="sidebar-sub-item" :class="{ active: currentPage === 'settings/integrations' }" @click="navigateTo('settings/integrations')">Integrations</span>
                <span class="sidebar-sub-item" :class="{ active: currentPage === 'settings/backup' }" @click="navigateTo('settings/backup')">Backup</span>
                <span class="sidebar-sub-item" x-show="userRole==='admin'" :class="{ active: currentPage === 'settings/users' }" @click="navigateTo('settings/users')">Users</span>
                <span class="sidebar-sub-item" :class="{ active: currentPage === 'settings/alerts' }" @click="navigateTo('settings/alerts')">Alerts</span>
                <span class="sidebar-sub-item" :class="{ active: currentPage === 'settings/shortcuts' }" @click="navigateTo('settings/shortcuts')">Shortcuts</span>
            </div>
        </nav>
        <!-- User -->
        <div class="sidebar-user">
            <div class="sidebar-user-avatar" x-text="(username||'?')[0].toUpperCase()"></div>
            <div class="sidebar-user-info">
                <div class="sidebar-user-name" x-text="username"></div>
                <div class="sidebar-user-role" x-text="userRole"></div>
            </div>
            <button class="icon-btn" style="opacity:.4" @click="logout()" title="Logout"><i class="fas fa-sign-out-alt"></i></button>
        </div>
    </aside>
    <!-- Mobile sidebar backdrop -->
    <div class="sidebar-backdrop" :class="{ show: !sidebarCollapsed && authenticated }" @click="sidebarCollapsed = true" x-show="authenticated"></div>

    <!-- Compact Header -->
    <header class="app-header" x-show="authenticated">
        <button class="icon-btn" @click="sidebarCollapsed = !sidebarCollapsed" title="Toggle sidebar"><i class="fas fa-bars"></i></button>
        <div class="header-search">
            <i class="fas fa-search search-icon"></i>
            <input type="text" placeholder="Search commands, agents, settings..." @focus="searchOpen = true" @click="searchOpen = true" readonly>
            <span class="search-kbd">Ctrl+K</span>
        </div>
        <div style="flex:1"></div>
        <button class="icon-btn" @click="refreshStats()" title="Refresh (r)"><i class="fas fa-sync-alt"></i></button>
        <button class="icon-btn" x-show="currentPage==='dashboard'" @click="glanceMode=!glanceMode" :title="glanceMode ? 'Expand cards' : 'Compact cards'"><i class="fas" :class="glanceMode ? 'fa-expand' : 'fa-compress'"></i></button>
        <!-- Theme selector -->
        <select class="field-select" style="width:auto;font-size:11px;padding:3px 6px" x-model="theme" @change="saveSettings()">
            <option value="default">Default</option>
            <option value="dracula">Dracula</option>
            <option value="nord">Nord</option>
            <option value="tokyo">Tokyo</option>
            <option value="catppuccin">Catppuccin</option>
            <option value="gruvbox">Gruvbox</option>
        </select>
        <!-- Notifications -->
        <button class="icon-btn" style="position:relative" @click="toggleNotifCenter()">
            <i class="fas fa-bell"></i>
            <span x-show="unreadNotifs > 0" class="notif-badge" x-text="unreadNotifs"></span>
        </button>
        <!-- Live status -->
        <span class="conn-pill" :class="connClass" x-text="connLabel"></span>
    </header>

    <!-- Content Area -->
    <main class="app-content">
        <!-- Login overlay (full viewport when !authenticated) -->
        <!-- ... existing login form, shown when !authenticated ... -->

        <!-- Dashboard page -->
        <div x-show="currentPage === 'dashboard' && authenticated">
            <!-- Health bar + sortable grid go here (moved from current position) -->
        </div>

        <!-- Agents page -->
        <div x-show="currentPage === 'agents' && authenticated">
            <!-- Agents modal content moved here (without modal-overlay wrapper) -->
        </div>

        <!-- Monitoring page -->
        <div x-show="currentPage === 'monitoring' && authenticated">
            <!-- SLA, Incidents, Correlation, Graylog, InfluxDB as tabs -->
        </div>

        <!-- Infrastructure page -->
        <div x-show="currentPage === 'infrastructure' && authenticated">
            <!-- Service Map, Tailscale, Cross-Site Sync as tabs -->
        </div>

        <!-- Automations page -->
        <div x-show="currentPage === 'automations' && authenticated">
            <!-- Automation deck content -->
        </div>

        <!-- Logs page -->
        <div x-show="currentPage === 'logs' && authenticated">
            <!-- Command history, audit log, journal -->
        </div>

        <!-- Settings sub-pages -->
        <div x-show="currentPage === 'settings/general' && authenticated">
            <!-- Data sources, network watchdog, config backup -->
        </div>
        <div x-show="currentPage === 'settings/visibility' && authenticated">
            <!-- Card visibility toggles -->
        </div>
        <div x-show="currentPage === 'settings/integrations' && authenticated">
            <!-- All integrations with category tabs -->
        </div>
        <div x-show="currentPage === 'settings/backup' && authenticated">
            <!-- Cloud backup config -->
        </div>
        <div x-show="currentPage === 'settings/users' && authenticated">
            <!-- User management -->
        </div>
        <div x-show="currentPage === 'settings/alerts' && authenticated">
            <!-- Alert rules -->
        </div>
        <div x-show="currentPage === 'settings/shortcuts' && authenticated">
            <!-- Keyboard shortcuts -->
        </div>
    </main>
</div>
```

The key structural changes:
1. Replace `<div class="page">` with `<div class="app-layout">`
2. Add the sidebar `<aside>` as the first child
3. Shrink the old `<header>` into the compact `<header class="app-header">`
4. Wrap the health bar + card grid in `<div x-show="currentPage === 'dashboard'">`
5. Remove the settings modal wrapper — its tab contents become direct `x-show` blocks
6. Remove the agents modal wrapper — its content becomes the agents page block

- [ ] **Step 2: Move the health bar and card grid into the dashboard page block**

Cut the health bar (line 193-201) and the `#sortable-grid` div (line 249 to its closing tag) from their current positions. Paste them inside the `<div x-show="currentPage === 'dashboard'">` block.

- [ ] **Step 3: Move agents modal content to agents page block**

Take the inner content of the agents modal (line 5066+, everything inside the `modal-box`) and move it into the `<div x-show="currentPage === 'agents'">` block. Remove the `modal-overlay` and `modal-box` wrappers. Remove the `showAgentsModal` close button.

- [ ] **Step 4: Move settings modal tab contents to settings sub-pages**

For each of the 7 settings tabs (visibility line ~2693, data line ~2761, backup line ~3603, integrations line ~2839, users line ~3779, alerts line ~3839, shortcuts line ~4002):
- Cut the tab's content
- Paste into the corresponding `<div x-show="currentPage === 'settings/XXX'">` block
- Add a page header: `<h2 style="margin-bottom:1rem"><i class="fas fa-XXX" style="margin-right:.5rem"></i> Settings — XXX</h2>`
- Remove the old settings modal entirely (the tab bar, modal-overlay, modal-box)

- [ ] **Step 5: Move monitoring modals to monitoring page tabs**

Create a tab bar inside the monitoring page block:
```html
<div x-show="currentPage === 'monitoring' && authenticated">
    <div class="tab-bar" style="margin-bottom:1rem">
        <button class="tab-btn" :class="{'active': !monitoringTab || monitoringTab==='sla'}" @click="monitoringTab='sla'; fetchSla()">SLA</button>
        <button class="tab-btn" :class="{'active': monitoringTab==='incidents'}" @click="monitoringTab='incidents'; fetchIncidents()">Incidents</button>
        <button class="tab-btn" :class="{'active': monitoringTab==='correlation'}" @click="monitoringTab='correlation'">Correlation</button>
        <button class="tab-btn" :class="{'active': monitoringTab==='graylog'}" @click="monitoringTab='graylog'">Graylog</button>
        <button class="tab-btn" :class="{'active': monitoringTab==='influxdb'}" @click="monitoringTab='influxdb'">InfluxDB</button>
        <button class="tab-btn" :class="{'active': monitoringTab==='charts'}" @click="monitoringTab='charts'; fetchAvailableMetrics()">Custom Charts</button>
    </div>
    <!-- Tab content: move inner content from each modal -->
    <div x-show="!monitoringTab || monitoringTab==='sla'"><!-- SLA modal content --></div>
    <div x-show="monitoringTab==='incidents'"><!-- Incident modal content --></div>
    <!-- etc. -->
</div>
```

Move inner content from `showSlaModal`, `showIncidentModal`, `showCorrelateModal`, `showGraylogModal`, `showInfluxModal`, `showMultiChartModal` modals. Add `monitoringTab: 'sla'` to app.js state.

- [ ] **Step 6: Move infrastructure modals to infrastructure page tabs**

Same pattern — tab bar with Service Map, Tailscale, Cross-Site Sync. Move content from `showServiceMapModal`, `showTailscaleModal`, `showSyncModal`. Add `infrastructureTab: 'servicemap'` to state.

- [ ] **Step 7: Move automations and logs**

Move automation modal content to automations page. Move journal/audit content to logs page. Add `logsTab: 'history'` to state with tabs: Command History, Audit Log, Journal.

- [ ] **Step 8: Update mobile bottom nav**

Update the existing mobile nav (line 2138-2151) to use `navigateTo()`:

```html
<nav class="mobile-nav" x-show="authenticated" x-cloak>
    <a class="mobile-nav-item" :class="{ active: currentPage === 'dashboard' }" @click="navigateTo('dashboard')">
        <i class="fas fa-th-large"></i><span>Dashboard</span>
    </a>
    <a class="mobile-nav-item" :class="{ active: currentPage === 'agents' }" @click="navigateTo('agents')">
        <i class="fas fa-robot"></i><span>Agents</span>
    </a>
    <a class="mobile-nav-item" :class="{ active: currentPage.startsWith('monitoring') }" @click="navigateTo('monitoring')">
        <i class="fas fa-chart-line"></i><span>Monitor</span>
    </a>
    <a class="mobile-nav-item" :class="{ active: currentPage.startsWith('settings') }" @click="navigateTo('settings/general')">
        <i class="fas fa-cog"></i><span>Settings</span>
    </a>
</nav>
```

- [ ] **Step 9: Update OIDC callback to preserve hash**

In the OIDC callback script (line 19-28), change:
```javascript
// Old: window.history.replaceState({}, '', '/');
// New:
window.history.replaceState({}, '', '/' + window.location.hash);
```

- [ ] **Step 10: Update login overlay**

The login form (line 4024-4062) should render OUTSIDE the `app-layout` or as a full-viewport overlay that covers the sidebar too. Since `.no-sidebar` class hides the sidebar column when `!authenticated`, the login overlay can stay in `.app-content` but must be styled to cover the full viewport:

```css
.login-fullscreen { position: fixed; inset: 0; z-index: 2000; }
```

- [ ] **Step 11: Remove old header, old modals, old page wrapper**

- Delete the old `<header class="header">` (lines 53-191) — replaced by `<header class="app-header">`
- Delete the settings modal wrapper (`modal-overlay` at line ~2656) and its tab bar — content moved to pages
- Delete the agents modal wrapper at line ~5066 — content moved to agents page
- Delete the monitoring modals (SLA, Incidents, Correlation, Graylog, InfluxDB, Custom Charts) — content moved to monitoring page
- Delete the infrastructure modals (Service Map, Tailscale, Cross-Site Sync) — content moved
- Keep all modals that stay as modals (Terminal, Container logs, K8s pods, Profile, etc.)

- [ ] **Step 12: Verify and commit**

```bash
node -e "new Function(require('fs').readFileSync('share/noba-web/static/app.js','utf8'))" && echo "JS OK"
git add share/noba-web/index.html share/noba-web/static/app.js
git commit -m "feat(ui): add sidebar layout, hash routing, page-based content"
```

---

### Task 4: Auth + Logout + Modal Flag Cleanup

**Files:**
- Modify: `share/noba-web/static/auth-mixin.js`
- Modify: `share/noba-web/static/system-actions.js`
- Modify: `share/noba-web/static/integration-actions.js`
- Modify: `share/noba-web/static/automation-actions.js`

- [ ] **Step 1: Update logout() to clear hash**

In `auth-mixin.js`, add to the `logout()` function (line ~108):
```javascript
location.hash = '#/dashboard';
```

- [ ] **Step 2: Update keyboard shortcut and button references**

Search all JS files for `showSettings = true`, `showAgentsModal = true`, `showSlaModal = true`, `showIncidentModal = true`, etc. and replace with `navigateTo()` calls where those modals are now pages:

```javascript
// system-actions.js: replace modal opens with navigation
// showSlaModal = true      → navigateTo('monitoring'); monitoringTab = 'sla'
// showIncidentModal = true → navigateTo('monitoring'); monitoringTab = 'incidents'
// showCorrelateModal = true → navigateTo('monitoring'); monitoringTab = 'correlation'
// showGraylogModal = true  → navigateTo('monitoring'); monitoringTab = 'graylog'
// showServiceMapModal = true → navigateTo('infrastructure'); infrastructureTab = 'servicemap'
// showSyncModal = true     → navigateTo('infrastructure'); infrastructureTab = 'sync'

// integration-actions.js:
// showAgentsModal = true   → navigateTo('agents')

// automation-actions.js:
// showAutoModal = true     → navigateTo('automations')
```

Note: Keep the `show*Modal` state variables in place for now — some may still be referenced. Set them to `false` in addition to navigating, so any remaining UI that checks them doesn't break.

- [ ] **Step 3: Verify JS syntax and commit**

```bash
for f in share/noba-web/static/*.js; do node -e "new Function(require('fs').readFileSync('$f','utf8'))" && echo "$f OK"; done
git add share/noba-web/static/
git commit -m "feat(ui): update modal flags to page navigation, hash on logout"
```

---

### Task 5: SVG Favicon

**Files:**
- Create: `share/noba-web/static/favicon.svg`
- Modify: `share/noba-web/index.html`
- Modify: `share/noba-web/service-worker.js`

- [ ] **Step 1: Create SVG favicon**

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
  <defs>
    <linearGradient id="g" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#58a6ff"/>
      <stop offset="100%" stop-color="#3fb950"/>
    </linearGradient>
  </defs>
  <rect width="32" height="32" rx="6" fill="url(#g)"/>
  <text x="16" y="23" text-anchor="middle" font-family="system-ui,-apple-system,sans-serif" font-weight="800" font-size="20" fill="#0d1117">N</text>
</svg>
```

- [ ] **Step 2: Update index.html favicon link**

Replace the existing favicon `<link>` in `<head>` with:
```html
<link rel="icon" type="image/svg+xml" href="/static/favicon.svg">
```

- [ ] **Step 3: Update service worker STATIC_ASSETS**

In `service-worker.js` (line 4-13), add `/static/favicon.svg` to the array.

- [ ] **Step 4: Commit**

```bash
git add share/noba-web/static/favicon.svg share/noba-web/index.html share/noba-web/service-worker.js
git commit -m "feat(ui): add NOBA SVG favicon"
```

---

### Task 6: Global Search Modal

**Files:**
- Modify: `share/noba-web/index.html`
- Modify: `share/noba-web/static/app.js`

- [ ] **Step 1: Add search modal HTML**

Add a search overlay (above all page content, inside `.app-content` or as a floating overlay):

```html
<!-- Global Search -->
<div class="modal-overlay" x-show="searchOpen" @click.self="searchOpen=false" @keydown.escape.window="searchOpen=false" style="z-index:2000" x-cloak>
    <div class="modal-box" style="max-width:540px;margin-top:15vh">
        <input type="text" class="field-input" style="font-size:1rem;padding:.75rem 1rem"
               placeholder="Search commands, agents, settings..."
               x-model="searchQuery" @input.debounce.150ms="filterSearch()"
               x-ref="searchInput" x-init="$watch('searchOpen', v => { if(v) $nextTick(() => $refs.searchInput.focus()) })">
        <div style="max-height:300px;overflow-y:auto;margin-top:.5rem">
            <template x-for="result in searchResults" :key="result.id">
                <div class="sidebar-nav-item" @click="result.action(); searchOpen=false; searchQuery=''">
                    <i class="fas nav-icon" :class="result.icon"></i>
                    <span class="nav-label" x-text="result.label"></span>
                    <span style="font-size:10px;opacity:.4;margin-left:auto" x-text="result.category"></span>
                </div>
            </template>
            <div x-show="searchQuery && searchResults.length === 0" style="padding:1rem;text-align:center;opacity:.4">No results</div>
        </div>
    </div>
</div>
```

- [ ] **Step 2: Add search logic in app.js**

```javascript
searchResults: [],

filterSearch() {
    const q = (this.searchQuery || '').toLowerCase().trim();
    if (!q) { this.searchResults = []; return; }
    const results = [];

    // Pages
    const pages = [
        { label: 'Dashboard', icon: 'fa-th-large', action: () => this.navigateTo('dashboard'), category: 'Page' },
        { label: 'Agents', icon: 'fa-robot', action: () => this.navigateTo('agents'), category: 'Page' },
        { label: 'Monitoring', icon: 'fa-chart-line', action: () => this.navigateTo('monitoring'), category: 'Page' },
        { label: 'Infrastructure', icon: 'fa-server', action: () => this.navigateTo('infrastructure'), category: 'Page' },
        { label: 'Automations', icon: 'fa-bolt', action: () => this.navigateTo('automations'), category: 'Page' },
        { label: 'Logs', icon: 'fa-scroll', action: () => this.navigateTo('logs'), category: 'Page' },
        { label: 'Settings — General', icon: 'fa-cog', action: () => this.navigateTo('settings/general'), category: 'Settings' },
        { label: 'Settings — Visibility', icon: 'fa-eye', action: () => this.navigateTo('settings/visibility'), category: 'Settings' },
        { label: 'Settings — Integrations', icon: 'fa-plug', action: () => this.navigateTo('settings/integrations'), category: 'Settings' },
        { label: 'Settings — Backup', icon: 'fa-archive', action: () => this.navigateTo('settings/backup'), category: 'Settings' },
        { label: 'Settings — Users', icon: 'fa-users', action: () => this.navigateTo('settings/users'), category: 'Settings' },
        { label: 'Settings — Alerts', icon: 'fa-bell', action: () => this.navigateTo('settings/alerts'), category: 'Settings' },
    ];
    pages.forEach(p => { if (p.label.toLowerCase().includes(q)) results.push({ ...p, id: 'p_' + p.label }); });

    // Commands
    (this.CMD_CATALOG || []).forEach(c => {
        if (c.label.toLowerCase().includes(q) || c.type.includes(q)) {
            results.push({ label: c.label, icon: c.icon, action: () => { this.navigateTo('agents'); this.cmdPaletteType = c.type; }, category: 'Command', id: 'c_' + c.type });
        }
    });

    // Agents
    (this.agents || []).forEach(a => {
        if (a.hostname.toLowerCase().includes(q)) {
            results.push({ label: a.hostname, icon: 'fa-robot', action: () => { this.navigateTo('agents'); this.openAgentDetail(a.hostname); }, category: 'Agent', id: 'a_' + a.hostname });
        }
    });

    this.searchResults = results.slice(0, 15);
},
```

- [ ] **Step 3: Verify and commit**

```bash
node -e "new Function(require('fs').readFileSync('share/noba-web/static/app.js','utf8'))"
git add share/noba-web/index.html share/noba-web/static/app.js
git commit -m "feat(ui): add global search with Ctrl+K"
```

---

### Task 7: Final Verification + Cleanup

**Files:**
- All modified files

- [ ] **Step 1: Run full lint and syntax checks**

```bash
ruff check share/noba-web/server/ share/noba-agent/ --fix
for f in share/noba-web/static/*.js; do node -e "new Function(require('fs').readFileSync('$f','utf8'))" && echo "$f OK"; done
```

- [ ] **Step 2: Run full test suite**

```bash
pytest tests/ -v
```

Expected: All 445 tests pass (backend only, no frontend tests affected).

- [ ] **Step 3: Manual browser verification checklist**

- [ ] Sidebar renders with all nav items
- [ ] Clicking nav items changes the content area
- [ ] URL hash updates on navigation
- [ ] Back button works
- [ ] Sidebar collapse persists across refresh
- [ ] All 6 themes render correctly with sidebar
- [ ] Settings sub-pages show correct content
- [ ] Agent command palette works on agents page
- [ ] Mobile: sidebar hidden, bottom nav works
- [ ] Ctrl+K opens search, results navigate correctly
- [ ] Favicon visible in browser tab
- [ ] Login screen covers full viewport (no sidebar visible)
- [ ] Logout returns to dashboard

- [ ] **Step 4: Final commit if any cleanup needed**

```bash
git add -A
git commit -m "fix(ui): sidebar nav cleanup and polish"
```
