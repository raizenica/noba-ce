# NOBA Command Center

## Stack
- **Backend**: FastAPI (Python 3.11+), SQLite WAL, psutil, httpx
- **Frontend**: Alpine.js, vanilla CSS, Chart.js
- **Scripts**: Bash (libexec/)
- **No build step** — static files served directly

## Project Layout
```
share/noba-web/server/   → Python backend modules
share/noba-web/static/   → JS (app.js, auth-mixin.js, actions-mixin.js)
share/noba-web/index.html → Full UI (Alpine.js template)
share/noba-web/service-worker.js → PWA service worker
libexec/                 → Shell scripts
install.sh               → Installer
tests/                   → pytest test suite
```

## Coding Conventions

### Python
- Run `ruff check --fix` after editing `.py` files
- Use `from __future__ import annotations` in all modules
- Threading: always use locks when mutating module-level state
- Auth: `Depends(_get_auth)` for read, `Depends(_require_operator)` for controls, `Depends(_require_admin)` for admin
- Catch `HTTPException` before generic `Exception` in route handlers
- Keep integration functions self-contained (no shared mutable state between them)
- Use dedicated httpx clients for integrations that set cookies (UniFi, qBittorrent)

### JavaScript
- Alpine.js component pattern: `dashboard()` returns state + methods
- Mixins via spread: `...authMixin()`, `...actionsMixin()`
- Always clear intervals before setting new ones
- Use `||0` guards on numeric values from API that could be null/undefined
- Use `x-model.number` for numeric select inputs

### HTML/CSS
- Modal structure: `modal-overlay` > `modal-box` > `modal-title` + content + `modal-footer`
- Role gating: wrap operator/admin controls with `x-show="userRole !== 'viewer'"`
- Use existing CSS classes — check `style.css` before inventing new ones

### Shell Scripts
- Never `source` untrusted files — use safe key-value parsing
- Always add cleanup traps for temp files
- Use `--verbose` flag pattern (default quiet)

## Testing
```bash
# Run all tests
pytest tests/ -v

# Run specific test file
pytest tests/test_auth.py -v

# Syntax check all Python
ruff check share/noba-web/server/

# Syntax check JS
node -e "new Function(require('fs').readFileSync('share/noba-web/static/app.js','utf8'))"
```

## Protected Files — DO NOT EDIT
- `~/.config/noba-web/auth.conf` — legacy auth credentials
- `~/.config/noba-web/users.conf` — user database
- `~/.local/share/noba-history.db` — SQLite database
- `.env` files, `*.db` files, credential files

## Common Pitfalls
- SSE (EventSource) cannot set custom headers — use `_get_auth_sse` which falls back to query param token
- `sys.stdout.reconfigure` crashes in non-standard environments — always wrap in try/except
- SQLite VACUUM must run outside any transaction — acquire lock separately after commit
- localStorage `select` values are strings — use `x-model.number` or parseInt
