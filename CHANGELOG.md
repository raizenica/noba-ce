# Changelog

All notable changes to NOBA Command Center are documented in this file.

## [Unreleased]

### Added
- **556 new backend tests** — Auth router (136), automations router (137), integration drivers (178), healing modules (115), db/core (65). Total test count: 3,143.
- **21 new Vue sub-components** — Split 5 oversized views (AutomationsView, InfrastructureView, MonitoringView, LogsView, DashboardView) into focused tab components.
- **Backend constants module** (`server/constants.py`) — Centralized 16 magic numbers from routers and healing modules.
- **Frontend constants module** (`constants.js`) — Centralized 15 timing/limit values from stores and components.
- **14 CSS utility classes** — Table cell, border, spacing, and typography utilities replacing 208 inline style attributes.
- **`.dockerignore`** — Excludes `.git`, `node_modules`, `__pycache__`, `tests/`, `.venv` from Docker build context.

### Improved
- **`api_agent_report()` refactored** — 173-line blob handler decomposed into 10 focused helpers; WebSocket handlers also split. Shared helpers between HTTP and WS paths.
- **Dockerfile hardened** — Added `SHELL` directive for `bash -euo pipefail`, OCI metadata labels, pinned pip versions from pyproject.toml.
- **Shell script portability** — Hardcoded `/tmp` paths replaced with `${TMPDIR:-/tmp}` across 6 scripts (24 replacements). Log libraries consolidated into `noba-lib.sh` with portable `printf` (no `echo -e`).
- **Return type hints** — Added to 11 router functions across 6 files.
- **Accessibility** — 8 fixes: clickable divs get `role="button"` + keyboard handlers, icon-only buttons get `aria-label`.
- **Dependency sync** — `requirements.txt` now includes `websocket-client>=1.7` matching pyproject.toml.

### Fixed
- **`linked_providers` read-connection crash** — `get_linked_providers()` called `CREATE TABLE` via the read-only connection, causing `OperationalError: attempt to write a readonly database`. Table now created during schema init; read functions handle missing table gracefully.
- **IntegrationsTab broken HTML** — 4 social provider `<div>` tags missing closing `>` brackets, causing build failures.
- **3 `console.error` calls** left in production Vue code (LogsView, LogStreamModal, CommandPalette) — removed.

### Added (continued)
- **Bulk Agent Management** — Selection system for agent cards with bulk update (self-update) and bulk remove capabilities.
- **Bulk Automation Management** — Multi-select for automations with bulk enable, disable, and delete actions.
- **Terminal Fullscreen Mode** — Added a maximize toggle to the Terminal modal and `Alt+Enter` keyboard shortcut for better visibility of dense command outputs.
- **Log Stream Flow Control** — Added Pause/Resume functionality to the live log stream and a floating "Jump to Bottom" indicator that appears when new logs arrive while auto-scroll is disabled.
- **Trust state initialization** — `PUT /api/healing/trust/{rule_id}` endpoint to seed trust states directly. Previously only promote/demote existed, requiring a pre-existing state.
- **IaC export auto-discovery** — `?discover=true` query parameter on all 3 export endpoints (Ansible, Docker Compose, shell script). Dispatches `discover_services` + `container_list` to the target agent, waits for WebSocket results, and merges into agent data before generating output. Warnings returned via `X-Noba-Discovery-Warning` header.
- **Remote agent healing** — Healing executor now dispatches actions to remote agents via WebSocket when the alert rule specifies a `target` hostname. Maps `restart_container` → `container_control` and `restart_service` → agent commands. Falls back to local execution if target is not an online agent.
- **First-run onboarding** — New users see a guided setup checklist instead of an unconfigured dashboard. Steps: Core Monitoring (auto-complete), Connect Services (integration wizard modal), Set Up Notifications (channel picker modal), Deploy Agents (deploy modal), Add Users (user creation modal). Progress tracked with checkmarks. Dismissible with "Continue to Dashboard".
- **Docker update flow** — Update check detects Docker containers and shows pull/recreate instructions instead of the bare-metal apply button. GHCR workflow publishes images on push to main and tags.
- **Zero CDN dependencies** — Font Awesome, Chakra Petch, and JetBrains Mono are now bundled locally via npm. No external requests needed — works fully offline and fixes font/icon rendering issues in Docker.
- **Self-update system** — Check for updates and apply them from the UI (Settings → General). Backend: `GET /api/system/update/check` compares local version to remote via git, `POST /api/system/update/apply` pulls, rebuilds frontend, re-installs, and restarts the service.
- Agent v2.1.0 with new commands: `security_scan`, `network_discover`, `discover_services`, `follow_logs`, `stop_stream`, `get_stream`, `endpoint_check`, `verify_backup`, `dns_lookup`, `network_config`, `network_stats`
- Risk-tiered command authorization (low/medium/high) with role-based permissions
- Agent capability registry with version-aware command validation
- Parameter validation for all 32+ command types with regex, length, and denylist checks
- Agent registry SQLite table for persistence across server restarts
- Bulk command support (send to multiple agents at once)
- Command history persistence in SQLite with status tracking

### Improved
- **Dashboard Layout Persistence** — Reordered cards are now saved to backend user preferences using SortableJS `store` sync. Layouts persist across different browsers and devices.
- **Keyboard-First Command Palette** — Enhanced `Ctrl+K` search with full keyboard navigation (ArrowUp/Down to highlight, Enter to select).
- **Global Dialog Accessibility** — Implemented `Enter` key listener for all global confirmation dialogs to streamline destructive workflows.
- **Persistent Sidebar State** — Manual sidebar collapse/expand states are now synced to user preferences and restored on login.
- **Log Stream Stability** — Optimized line buffering logic to prevent memory bloat during high-volume log ingest.
- **SQLite read/write lock separation** — Read operations now use a separate connection with its own lock, allowing concurrent reads under WAL mode without blocking writers. Write operations keep the existing exclusive lock. ~60 read-only methods switched to the read path. `PRAGMA query_only=ON` on the read connection prevents accidental writes.
- **Linked providers persisted to DB** — Social login account links (Google, GitHub, etc.) are now stored in a `linked_providers` table instead of an in-memory dict. Links survive service restarts.
- **Credential encryption at rest** — Integration secrets in `config.yaml` (passwords, tokens, API keys) are now encrypted using Fernet symmetric encryption. Master key stored separately at `~/.config/noba/.master.key` (mode 0600). Existing plaintext configs are transparently encrypted on next save. `cryptography` added as a required dependency.
- **Agent sidebar badge** — Now shows `online/total` count instead of hiding when all agents are offline. Warning color when some are down.
- **API failure visibility** — Header shows a banner when background API requests are silently failing, with failure count and last error. Prevents the "everything looks fine but nothing is updating" trap.
- **Setup wizard reset** — "Re-run Setup Wizard" button in Settings → General clears the welcome dismissal so onboarding can be re-triggered.
- **Integration card empty states** — "configure in Settings" messages are now clickable links that navigate directly to the Integrations settings tab.
- **Maintenance badge clickable** — Header maintenance window indicator now navigates to Settings → Maintenance on click.
- **Theme-safe colors** — WorkflowBuilder node type colors and RunOutput console now use CSS theme variables instead of hardcoded hex values.
- Agent reports now trigger persistence on every report cycle (not just on command completion)

### Security
- **SSRF via redirect** — Shared httpx client now uses `follow_redirects=False` to prevent integration endpoints from being redirected to internal/cloud metadata IPs.
- **Webhook DNS rebinding** — `_is_safe_webhook_url()` now resolves hostnames via `socket.getaddrinfo()` and checks all resulting IPs against private/loopback/link-local ranges. Previously only checked string-based IP parsing.
- **Run command argument validation** — `_handle_run` now validates all arguments after the allowed prefix against `[a-zA-Z0-9@._/:-]` to prevent abuse of the allowlisted command prefixes.
- **OpenAPI docs disabled by default** — `/api/docs`, `/api/redoc`, and `/api/openapi.json` are now hidden unless `NOBA_DEV=1` is set, preventing API schema disclosure to unauthenticated users.
- **CSP tightened** — Removed `unsafe-eval` and `unsafe-inline` from `script-src`, stripped all external CDN allowances (fonts/icons already bundled). Service worker registration moved from inline script to the main JS bundle.
- **TLS verification configurable** — All integration HTTP calls (K8s, Proxmox, UniFi, UniFi Protect) now respect per-integration `verifySsl` settings instead of hardcoded `verify=False`. Integration instances have a `verify_ssl` DB column and UI checkbox. Supports CA bundle file paths for custom certificates.
- **Script automation shell escalation blocked** — Automations with custom `command` fields now require admin role, preventing operator→shell privilege escalation.
- **Automation variable injection blocked** — Operator-supplied variables substituted into `command` strings via `format_map` are now sanitized with `shlex.quote()`, preventing shell metacharacter injection.
- **Agent key timing attack mitigated** — Agent key validation now uses `secrets.compare_digest` for constant-time comparison.
- **Prometheus label injection prevented** — Service names and mount points in `/api/prometheus` metrics are now escaped per the exposition format spec.
- **OAuth2/OIDC CSRF protection** — All social login and OIDC flows now generate and validate a cryptographic `state` parameter, preventing login CSRF attacks.
- **OAuth token leak fixed** — Account linking no longer passes the NOBA session token as the OAuth `state` parameter. Tokens are stored server-side with a random nonce.
- **Healing `run` action restricted** — Command execution via the healing pipeline is now restricted to an allowlist of safe prefixes (systemctl, docker, podman, restic, rclone, certbot).
- **API key expiry enforced** — Expired API keys are now rejected at authentication time.
- **Webhook SSRF protection** — Remediation webhook handler blocks requests to private networks, loopback, link-local, reserved ranges, and cloud metadata endpoints.
- **SSRF DNS resolution validation** — Integration instance URL validation now resolves hostnames and checks resolved IPs against private ranges.
- **LDAP filter injection fix** — Username escaping now uses proper RFC 4515 encoding instead of partial character replacement.
- **Terminal audit logging** — PTY sessions now log start/end events with user, role, IP, and duration to the audit trail.
- **SSH key validation** — Rejects authorized_keys entries with embedded options (`command=`, `from=`, etc.).
- **SQL column allowlist** — Integration instance updates validate field names against an explicit allowlist.
- **HTTPException guards** — Added `except HTTPException: raise` across all routers to prevent HTTP errors from being swallowed as 500s.
- **Journal regex validation** — Grep patterns are pre-validated with `re.compile()` before passing to `journalctl`.
- **Auth level corrections** — TOTP setup upgraded to operator, stream-logs downgraded from admin to operator, update check upgraded to operator, social link endpoint validates tokens.
- **Async event loop safety** — 20+ `subprocess.run()` calls in async routes wrapped in `asyncio.to_thread()` to prevent blocking the event loop.

### Fixed
- **Alert condition validation** — Malformed conditions (bare operators, missing thresholds, garbage strings) are now rejected at creation time with clear error messages. Validation applied to create, update, and batch save endpoints.
- **Heal action params double-nesting** — Legacy single-action alert rules were wrapping params inside an extra `params` key, causing heal execution to fail after approval. Fixed chain wrapper to extract params correctly.
- **Graylog user/password auth** — Graylog search integration now supports both API token (`token:token`) and user/password (`user:password`) Basic auth. Added `X-Requested-By: noba` header required by Graylog v7+. New settings: `graylogUser`, `graylogPassword`.
- **Agent capability fallback for newer versions** — Agents reporting a version not explicitly in the capability registry fell back to the v1.1.0 baseline. Now any agent ≥ v2.0.0 gets full v2 capabilities automatically.
- **Endpoint monitor self-referential deadlock** — Monitors targeting the same NOBA instance deadlocked the uvicorn process. Now detects self-referential URLs and returns `skipped` status.
- **Healing dry-run ignores maintenance windows** — The `/api/healing/dry-run` endpoint did not check active maintenance windows. Now queries the maintenance manager before simulation.
- **Proxmox API token double-prefix** — Detected full token IDs and uses them directly.
- **Healing effectiveness always 0%** — Endpoint queried non-existent `outcome` field; now uses `verified`/`action_success`.
- **Circuit breaker never tripped** — Query limit equalled threshold (3). Now looks back 50 entries.
- **LedgerTimeline timestamps** — Unix seconds passed to `new Date()` without ×1000.
- **Expired tokens accepted from DB** — Token fallback path promoted expired tokens to memory without checking expiry.
- **Double JSON encoding** — `evidence` field in health trigger suggestions was pre-serialized then re-serialized.
- **Dict passed as string** — Canary dry-run passed a dict to `suggested_action`.
- **`total_agents` NameError** — Variable undefined if monitoring coverage section threw.
- **Rollback bypassed DB write lock** — Used raw `_get_conn()` outside lock.
- **Dead code in `get_heal_outcomes`** — Redundant LIMIT 0 query + double lock acquire removed.
- **`_active_alerts` leak** — Targets added during suppressed paths stayed in the set forever. Split into TTL-based `_active_alerts` and `_active_heals` set.
- **Alert rules save was a no-op** — "Save Rules" in Settings sent the wrong payload. Added `PUT /api/alert-rules` batch endpoint.
- **Uptime card always showed 0%** — Backend now computes and returns percent.
- **Expired token crash** — DB fallback returned bare `None` instead of `(None, None)`.
- **Agent policy version always 0** — Now uses a SHA-256 content hash.
- **DNS flush hardcoded `pihole-FTL`** — Now reads `dnsService` from config.
- **Health score trigger** — Scheduler was passing Database object instead of health score categories.
- **Masonry grid after welcome dismiss** — Re-initializes ResizeObserver.
- **Self-update install step** — Added `--skip-deps` and `--no-restart` to install.sh invocation.
- **Trust level naming** — Fixed `"suggest"` to `"approve"` in `db/healing.py` trust level constants.

## [2.0.0] - 2026-03-19

### Added
- Full remote agent management platform (Phase 1 complete)
- WebSocket real-time communication with HTTP polling fallback
- 32 command types across system, service, file, container, network, and user management
- File transfer (push/pull) with chunked upload and SHA256 verification
- Streaming output for long-running commands via WebSocket
- One-click agent deployment from dashboard via SSH
- Windows agent support (PowerShell installer)
- Agent metric persistence with per-agent CPU/RAM/disk history
- SLA dashboard with 7d/30d/90d uptime percentages
- Sidebar navigation with global search (Ctrl+K)
- 10 standout features: network discovery, security scoring, IaC export, traffic analysis
- Ops center elevation: 11 features across 4 implementation waves
- Service dependency topology with impact analysis
- Configuration drift detection
- Predictive disk intelligence with SMART trend analysis
- AI Ops assistant (multi-provider LLM)
- Public status page (no auth required)
- Initial release: system monitoring dashboard with 40+ integrations
- Real-time SSE with polling fallback
- Multi-user RBAC (admin/operator/viewer)
- Plugin system for custom dashboard cards
- Alert rules with composite conditions and self-healing actions
- Anomaly detection with Z-score analysis
- PWA support with push notifications
- 6 color themes
- Automation engine with 9 action types
- Developer toolkit (screenshots, E2E tests, smoke tests, cross-reference validator)

## [1.0.0] - 2026-03-17

### Added
- Historical base release.
