# NOBA Sidebar Navigation — Design Spec

**Date:** 2026-03-20
**Goal:** Replace the modal-heavy, header-cluttered navigation with a persistent left sidebar, compact header with global search, and page-based content routing — transforming the UI from a single-page dashboard into a proper ops center.

---

## Current State

The dashboard has outgrown its original pattern:
- **31+ modals** for everything from agents to InfluxDB queries
- **20+ header buttons** competing for space in a single row
- **7 settings tabs** with 50+ integration fields crammed into one modal
- Navigation is: click button → modal opens → close modal → click different button
- Agent management, monitoring tools, and infrastructure views all fight for attention in the same flat space

## Design Principles

- **Keep existing theme system** — all 6 themes (Default, Dracula, Nord, Tokyo, Catppuccin, Gruvbox) continue working via CSS custom properties
- **Keep existing styling** — cards, health bars, badges, meters stay visually the same
- **No new dependencies** — Alpine.js, vanilla CSS, Chart.js remain the stack
- **Progressive enhancement** — the card grid is one "page" among several; existing card code barely changes

---

## Layout Architecture

### Three-zone layout

```
+----------+--------------------------------------------------+
| Sidebar  | Header (search, quick actions, notifications)    |
| (220px)  +--------------------------------------------------+
|          |                                                    |
| Nav      |  Content Area                                     |
| items    |  (page-based: dashboard grid, agents, settings…)  |
|          |                                                    |
| ...      |                                                    |
|          |                                                    |
| User     |                                                    |
+----------+--------------------------------------------------+
```

**CSS structure:**
```css
.app-layout {
    display: grid;
    grid-template-columns: var(--sidebar-width) 1fr;
    grid-template-rows: auto 1fr;
    height: 100vh;
}
.app-sidebar { grid-row: 1 / -1; }
.app-header  { grid-column: 2; }
.app-content { grid-column: 2; overflow-y: auto; }
```

### Sidebar (220px expanded, 56px collapsed)

**Structure top to bottom:**
1. **Logo** — NOBA icon + wordmark, version badge. Wordmark hides when collapsed.
2. **Nav items** — icon + label + optional badge. Scrollable if needed.
3. **Divider** — visual separator before settings.
4. **Settings** — expandable section with sub-items (General, Visibility, Integrations, Backup, Users, Alerts, Shortcuts). Sub-items hide when sidebar collapsed.
5. **User** — avatar initial + username + role badge. Collapses to avatar only. Click opens profile; logout button.

**Collapse behavior (icon-only mode):**
- Sidebar shrinks to 56px showing only icons
- Hover over collapsed sidebar temporarily expands with a floating overlay (no layout shift)
- Collapse state persisted in localStorage (`noba-sidebar-collapsed`)
- Toggled via hamburger button in the header
- CSS transition: `width 0.2s ease`

**Nav items:**

| Icon | Label | Badge | Page/Action |
|------|-------|-------|-------------|
| `fa-th-large` | Dashboard | — | Card grid (current main view) |
| `fa-robot` | Agents | online count | Agent list + command palette + output |
| `fa-chart-line` | Monitoring | — | SLA, Incidents, Correlation, Graylog, InfluxDB |
| `fa-server` | Infrastructure | — | Service Map, Tailscale, Cross-Site Sync |
| `fa-bolt` | Automations | — | Workflows, schedules, triggers |
| `fa-scroll` | Logs | — | Command history, audit log, journal viewer |
| `fa-cog` | Settings | — | Expandable sub-items (see below) |

**Settings sub-items:**

| Label | Content |
|-------|---------|
| General | Data sources, network watchdog, layout backup, config backup/restore |
| Visibility | Card toggle grid (51 toggles) |
| Integrations | All 30+ integrations, organized by category tabs |
| Backup | Cloud backup config, remotes, retention |
| Users | User management (admin only) |
| Alerts | Alert rule configuration |
| Shortcuts | Keyboard shortcut help and customization |

**Active state:** The current page gets a highlighted background (`rgba(accent, 0.12)`) and accent text color. Settings sub-items also highlight when active.

### Header (compact, 48px)

Replaces the current 20+ button header. Contains only global-scope actions:

| Position | Element | Behavior |
|----------|---------|----------|
| Left | Hamburger toggle | Collapses/expands sidebar |
| Left | Global search | `Ctrl+K` shortcut, searches commands/agents/settings/cards |
| Right | Refresh button | Refreshes current page data |
| Right | Glance mode toggle | Compacts card grid (dashboard page only) |
| Right | Theme selector | Dropdown, same 6 themes |
| Right | Notifications bell | Badge with unread count, opens notification center |
| Right | Live status pill | SSE/polling/offline indicator |

The header does NOT change per page — it's truly global.

### Content Area

Fills the remaining space. The `currentPage` Alpine state variable determines what renders:

| Page | Content | Source |
|------|---------|--------|
| `dashboard` | Health bar + sortable card grid | Existing code, minimal changes |
| `agents` | Agent list + command palette + output panel + command history | Currently in agents modal |
| `monitoring` | Sub-tabs: SLA, Incidents, Correlation, Graylog, InfluxDB | Currently individual modals |
| `infrastructure` | Sub-tabs: Service Map, Tailscale, Cross-Site Sync | Currently individual modals |
| `automations` | Automation deck | Currently in automation modal |
| `logs` | Command history, audit log, journal viewer | Currently spread across modals |
| `settings/*` | Settings sub-pages (general, visibility, integrations, etc.) | Currently settings modal tabs |

**Page routing:** Hash-based (`#/agents`, `#/settings/integrations`). No server-side routing needed. Alpine watches `window.location.hash` and sets `currentPage`. Back button works.

---

## What Moves Where

### Header buttons → Sidebar or page content

| Current Header Button | New Location |
|-----------------------|-------------|
| Settings gear | Sidebar "Settings" expandable |
| Terminal | Stays as floating modal (accessible from any page via keyboard shortcut `t`) |
| Service Map | Infrastructure page |
| Tailscale | Infrastructure page |
| InfluxDB Query | Monitoring page |
| Graylog Logs | Monitoring page (or Logs page) |
| Incident Timeline | Monitoring page |
| Metrics Correlation | Monitoring page |
| SLA Dashboard | Monitoring page |
| Cross-Site Status | Infrastructure page |
| Custom Dashboard | Monitoring page |
| Refresh | Stays in header |
| Glance mode | Stays in header |
| Theme | Stays in header |
| Notifications | Stays in header |
| Profile/user | Sidebar bottom user section |
| Logout | Sidebar bottom user section |
| Site filter | Header (if multi-site) or Infrastructure page |
| Now Playing | Dashboard page only (chip on Plex card) |

### Modals that become pages

| Modal | Becomes |
|-------|---------|
| Settings modal (7 tabs) | Settings sub-pages |
| Agents modal | Agents page |
| SLA modal | Monitoring > SLA tab |
| Incident modal | Monitoring > Incidents tab |
| Correlation modal | Monitoring > Correlation tab |
| Graylog modal | Monitoring > Logs tab (or Logs page) |
| InfluxDB modal | Monitoring > Query tab |
| Service Map modal | Infrastructure > Service Map tab |
| Tailscale modal | Infrastructure > Tailscale tab |
| Cross-Site Sync modal | Infrastructure > Sync tab |
| Custom Dashboard modal | Monitoring > Custom tab |

### Modals that stay as modals

These are contextual overlays that don't need their own page:
- Terminal (floating, any page)
- Container logs/inspect/stats
- K8s pod logs
- Proxmox snapshots
- Home Assistant
- Profile
- Keyboard shortcuts help
- Confirmation/password dialogs
- Diff viewer, file browser, backup explorer
- Agent detail modal

---

## Mobile Behavior

- **< 640px:** (matches existing mobile breakpoint) Sidebar fully hidden by default. Hamburger in header opens it as a slide-over overlay with backdrop.
- **Bottom nav bar:** Preserved — adapted to use `navigateTo()` instead of `showSettings`/`showAutoModal`. Active state determined by `currentPage` instead of modal flags.
- **Sidebar auto-closes** after navigation on mobile.

---

## Global Search

`Ctrl+K` (or clicking the search bar) opens a command-palette-style search:

- Searches across: page names, settings fields, agent hostnames, command types, integration names
- Results grouped by category with icons
- Selecting a result navigates to the relevant page/section
- Implementation: client-side filter over a static index built from CMD_CATALOG + settings keys + agent list

**Keyboard handler note:** The existing `initKeyboard()` returns early on `ctrlKey`/`altKey`/`metaKey` events. A separate `keydown` listener must be added *before* the early return to catch `Ctrl+K`. Alternatively, restructure the handler to process modifier combos first.

**Scope note:** Global search is a significant feature. The spec describes intent and UX; the implementation plan should detail the search index construction, fuzzy matching, result ranking, and keyboard navigation within results.

---

## Favicon

Delivered as a **separate micro-task** during implementation (not part of the sidebar layout work):
- Design: stylized "N" lettermark in a rounded square
- Gradient: accent blue (#58a6ff) to green (#3fb950) — matches the NOBA brand colors
- Format: SVG (inline in HTML `<link rel="icon">`) + PNG fallback (32x32, 16x16)

---

## Authentication & Login Overlay

- **When `!authenticated`:** Hide the sidebar entirely. The login overlay covers the full viewport (not just the content area). The `.app-layout` grid degrades to a single column.
- **OIDC callback:** The existing `replaceState({}, '', '/')` on OIDC callback must be changed to `replaceState({}, '', '/' + location.hash)` to preserve hash routes across login redirects.
- **Logout:** The `logout()` function must navigate to `#/dashboard` (or clear the hash) so the user doesn't return to a deep-linked page after re-login.

---

## State Management

New Alpine state in `app.js`:
```javascript
currentPage: 'dashboard',          // Active page
sidebarCollapsed: false,            // Persisted to localStorage
sidebarSettingsExpanded: false,     // Settings sub-menu open
searchOpen: false,                  // Global search modal
searchQuery: '',                    // Search input
```

Page routing:
```javascript
init() {
    // Read hash on load
    this.currentPage = (location.hash.replace('#/', '') || 'dashboard');
    // Watch hash changes
    window.addEventListener('hashchange', () => {
        this.currentPage = location.hash.replace('#/', '') || 'dashboard';
    });
}
```

Navigation:
```javascript
navigateTo(page) {
    location.hash = '#/' + page;
    // Auto-close sidebar on mobile
    if (window.innerWidth < 640) this.sidebarCollapsed = true;
}
```

**Settings save flow:** Since settings are now sub-pages (not a modal), `saveSettingsAndReconnect()` no longer sets `showSettings = false`. Instead it shows a success toast and stays on the current settings page. The user navigates away via the sidebar.

---

## Affected Files

### HTML
- `share/noba-web/index.html` — layout wrapping, sidebar HTML, modal-to-page migration, route guards, login overlay adjustment

### JavaScript (6 files)
- `share/noba-web/static/app.js` — routing state (`currentPage`, `sidebarCollapsed`), `init()` hash routing, `navigateTo()`, `Ctrl+K` handler, masonry re-trigger on page switch
- `share/noba-web/static/system-actions.js` — contains `showServiceMapModal`, `showSlaModal`, `showCorrelateModal`, `showIncidentModal`, `showGraylogModal` etc. — these flags become page navigation calls
- `share/noba-web/static/integration-actions.js` — agent modal flags become page routes
- `share/noba-web/static/automation-actions.js` — `showAutoModal` becomes `navigateTo('automations')`
- `share/noba-web/static/auth-mixin.js` — `logout()` must clear hash route
- `share/noba-web/static/actions-mixin.js` — minimal changes (core mixin)

### CSS
- `share/noba-web/static/style.css` — `.app-layout` grid, sidebar classes, header shrink, remove `.page` max-width (content area inherits), zero out header negative margins, mobile breakpoint cascade at 640px

### Service Worker
- `share/noba-web/service-worker.js` — update `STATIC_ASSETS` list if any new JS files are added. Hash-based routing does not trigger navigation requests, so no fetch handler changes needed.

---

## CSS Architecture

The sidebar and layout use existing CSS custom properties for full theme compatibility:
- `--bg`, `--surface`, `--surface-2` for backgrounds
- `--border` for dividers
- `--text`, `--text-muted` for labels
- `--accent` for active states
- All 6 themes work without any theme-specific sidebar code

New CSS custom properties:
```css
:root {
    --sidebar-width: 220px;
    --sidebar-collapsed-width: 56px;
    --header-height: 48px;
}
```

The current `.page` class (`max-width: 1600px; margin: 0 auto`) is replaced by the `.app-content` area. Max-width constraint moves to `.app-content` if desired, or is removed since the sidebar already bounds the layout. The current `.header` negative margins (`margin: 0 -1.5rem`) are removed — the header is a direct grid child.

---

## Masonry Re-trigger

The `initMasonry()` ResizeObserver watches `.card` elements. When navigating away from the dashboard (`display: none` via `x-show`), the observer is dormant. On navigating back, cards become visible and the observer fires. However, to avoid a layout flash, `navigateTo('dashboard')` should call `requestAnimationFrame(() => this.initMasonry())` after the page becomes visible.

---

## SSE Data Flow

The SSE connection (`EventSource`) is a single persistent stream that pushes all data continuously regardless of which page is visible. `_mergeLiveData()` updates all data fields on every event. This is unchanged — data stays fresh across all pages. No reconnection or subscription changes needed on page switch.

---

## Migration Strategy

This is a **layout refactor**, not a rewrite:
1. Wrap existing HTML in the new grid layout (sidebar + header + content)
2. Move card grid into a `x-show="currentPage==='dashboard'"` block
3. Move each modal's content into its page block, keeping the logic identical
4. Shrink the header, move buttons to sidebar nav items
5. Add hash routing
6. The existing modals that stay as modals need zero changes
7. Update login overlay to cover full viewport when `!authenticated`
8. Update OIDC callback to preserve hash
9. Update logout to clear hash route
10. Update bottom nav bar to use `navigateTo()` and `currentPage` for active state

The card grid, Alpine state, SSE data flow, all integration logic, and all 445 tests remain unchanged.

---

## Constraints

- **No new JS dependencies** — Alpine.js handles routing, state, transitions
- **No build step** — static files served directly
- **All 6 themes must work** — use existing CSS variables only
- **Existing keyboard shortcuts preserved** — `r` refresh, `s` settings, `t` terminal, etc. (keyboard shortcut `s` navigates to `#/settings/general` instead of opening modal)
- **Mobile bottom nav preserved** — adapted to use `navigateTo()` with `currentPage`-based active state
- **Mobile breakpoint stays at 640px** — matching existing CSS convention
- **All 445 tests still pass** — layout changes don't affect API or logic (all tests are backend Python)

---

## Success Criteria

- Sidebar with icon-only collapse, state persisted
- All 20+ header buttons relocated to organized sidebar/page structure
- Settings as sub-pages instead of a modal with 7 tabs
- Agents as a full page instead of a modal
- Monitoring tools (SLA, Incidents, etc.) grouped under one sidebar section
- Global search with `Ctrl+K`
- Hash-based routing with working back button
- Custom SVG favicon
- All 6 themes working with sidebar
- Mobile: slide-over sidebar (640px breakpoint) + bottom nav with `currentPage`
- Login overlay covers full viewport (sidebar hidden when !authenticated)
- OIDC callback preserves hash route
- Existing 445 tests pass unchanged
