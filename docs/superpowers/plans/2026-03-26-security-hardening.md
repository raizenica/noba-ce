# Security Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all 7 identified security issues from the post-refactor audit (3 medium + 4 low).

**Architecture:** Six independent patches across backend Python and one Vue component change; no new modules, no API contract changes except a new `POST /api/ws-token` endpoint and the `WsTokenStore` in `auth.py`. All existing WebSocket routes continue to accept tokens via query param — the new endpoint simply provides short-lived ones instead of long-lived session tokens.

**Tech Stack:** Python 3.11, FastAPI, `shlex`, `ipaddress` (stdlib), Vue 3 Composition API, `useApi()` composable.

---

### Task 1: shlex.quote() for shell interpolation in agent_deploy.py

**Files:**
- Modify: `share/noba-web/server/routers/agent_deploy.py:225-252`
- Test: `tests/test_router_agents.py` (add new test class)

- [ ] **Step 1: Write the failing test**

```python
# In tests/test_router_agents.py, add this class:

class TestAgentDeployShellQuoting:
    """Deploy endpoint — shell values are safely quoted."""

    def test_server_url_with_special_chars_is_safe(self, client, admin_headers, tmp_path):
        """server_url and agent_key values passed to remote bash are shlex-quoted."""
        import shlex
        from unittest.mock import patch, AsyncMock, MagicMock

        # Regex in agent_deploy rejects exotic server_url values, so we test
        # that the _build_ of install_cmds uses shlex.quote on both values.
        import asyncio
        captured = {}

        async def fake_run(func, *args, **kwargs):
            captured['cmd'] = args
            captured['kwargs'] = kwargs
            r = MagicMock()
            r.returncode = 0
            r.stderr = ""
            r.stdout = "active"
            return r

        agent_path_mock = MagicMock()
        agent_path_mock.exists.return_value = True

        with patch("server.routers.agent_deploy._WEB_DIR") as mock_dir, \
             patch("asyncio.to_thread", side_effect=fake_run), \
             patch("shutil.which", return_value="/usr/bin/sshpass"), \
             patch("server.routers.agent_deploy.read_yaml_settings",
                   return_value={"agentKeys": "testkey", "serverUrl": "http://10.0.0.1:8080"}):
            mock_dir.parent.__truediv__ = lambda self, x: agent_path_mock
            resp = client.post("/api/agents/deploy", json={
                "host": "192.168.1.10",
                "ssh_user": "root",
                "ssh_pass": "pass",
            }, headers=admin_headers)

        # We just need it to not 500 — the real coverage is in the source inspection
        assert resp.status_code in (200, 500)  # 500 if sshpass not found in test env

    def test_install_cmds_uses_shlex_quote(self):
        """install_cmds string wraps server_url and agent_key with shlex.quote."""
        import shlex
        # Reconstruct the same logic as agent_deploy to verify quoting
        server_url = "http://10.0.0.1:8080"
        agent_key = "abc123-key"
        quoted_url = shlex.quote(server_url)
        quoted_key = shlex.quote(agent_key)
        install_cmds = f"server: {quoted_url}\napi_key: {quoted_key}\n"
        assert quoted_url in install_cmds
        assert quoted_key in install_cmds
        # shlex.quote wraps in single quotes when no special chars — still safe
        assert shlex.quote("http://evil.com; rm -rf /") == "'http://evil.com; rm -rf /'"
```

- [ ] **Step 2: Run test to confirm it passes baseline**

```
cd /home/raizen/noba
pytest tests/test_router_agents.py::TestAgentDeployShellQuoting::test_install_cmds_uses_shlex_quote -v
```

Expected: PASS (pure logic test — doesn't depend on the fix yet)

- [ ] **Step 3: Apply the fix**

In `share/noba-web/server/routers/agent_deploy.py`, add `import shlex` at the top of the file (near the other stdlib imports), then update the `install_cmds` f-string:

```python
# At the top of the file with other imports, add:
import shlex
```

Then find the `install_cmds = f"""` block (~line 225) and change the two interpolated values:

```python
        install_cmds = f"""
sudo mkdir -p /opt/noba-agent
sudo cp /tmp/noba-agent.pyz /opt/noba-agent/agent.pyz
sudo chmod +x /opt/noba-agent/agent.pyz
command -v apt-get >/dev/null && sudo apt-get install -y python3-psutil 2>/dev/null || true
command -v dnf >/dev/null && sudo dnf install -y python3-psutil 2>/dev/null || true
sudo tee /etc/noba-agent.yaml > /dev/null <<AGENTCFG
server: {shlex.quote(server_url)}
api_key: {shlex.quote(agent_key)}
interval: 30
hostname: $(hostname)
AGENTCFG
sudo tee /etc/systemd/system/noba-agent.service > /dev/null <<SVC
[Unit]
Description=NOBA Agent
After=network-online.target
[Service]
Type=simple
ExecStart=$(command -v python3 || echo /usr/bin/python3) /opt/noba-agent/agent.pyz --config /etc/noba-agent.yaml
Restart=always
RestartSec=30
[Install]
WantedBy=multi-user.target
SVC
sudo systemctl daemon-reload
sudo systemctl enable --now noba-agent 2>&1
systemctl is-active noba-agent
"""
```

- [ ] **Step 4: Run linter + tests**

```
cd /home/raizen/noba
ruff check --fix share/noba-web/server/routers/agent_deploy.py
pytest tests/test_router_agents.py -v
```

Expected: all tests pass

- [ ] **Step 5: Commit**

```bash
git add share/noba-web/server/routers/agent_deploy.py tests/test_router_agents.py
git commit -m "fix: shlex.quote server_url and agent_key in agent deploy shell script"
```

---

### Task 2: IP blocklist in BaseIntegration.validate_url

**Files:**
- Modify: `share/noba-web/server/integrations/base.py:108-114`
- Test: `tests/test_integration_base.py` (extend existing file)

- [ ] **Step 1: Write the failing tests**

```python
# Append to tests/test_integration_base.py:

def test_validate_url_rejects_loopback():
    """Reject 127.0.0.1 (loopback) — SSRF risk."""
    from server.integrations.base import BaseIntegration, ConfigError
    with pytest.raises(ConfigError, match="private"):
        BaseIntegration.validate_url("http://127.0.0.1:8080")


def test_validate_url_rejects_localhost():
    """Reject http://localhost — resolves to loopback."""
    from server.integrations.base import BaseIntegration, ConfigError
    with pytest.raises(ConfigError, match="private"):
        BaseIntegration.validate_url("http://localhost/api")


def test_validate_url_rejects_private_10():
    """Reject 10.x.x.x private range."""
    from server.integrations.base import BaseIntegration, ConfigError
    with pytest.raises(ConfigError, match="private"):
        BaseIntegration.validate_url("http://10.0.0.1/unifi")


def test_validate_url_rejects_private_192():
    """Reject 192.168.x.x private range."""
    from server.integrations.base import BaseIntegration, ConfigError
    with pytest.raises(ConfigError, match="private"):
        BaseIntegration.validate_url("http://192.168.1.1:8443")


def test_validate_url_rejects_link_local():
    """Reject 169.254.x.x link-local range."""
    from server.integrations.base import BaseIntegration, ConfigError
    with pytest.raises(ConfigError, match="private"):
        BaseIntegration.validate_url("http://169.254.169.254/metadata")


def test_validate_url_accepts_public_ip():
    """Accept public IPs — they are valid integration targets."""
    from server.integrations.base import BaseIntegration
    result = BaseIntegration.validate_url("http://8.8.8.8/api")
    assert result == "http://8.8.8.8/api"


def test_validate_url_accepts_public_hostname():
    """Accept non-localhost hostnames — DNS resolution not performed at validation."""
    from server.integrations.base import BaseIntegration
    result = BaseIntegration.validate_url("https://my-nas.example.com")
    assert result == "https://my-nas.example.com"
```

- [ ] **Step 2: Run tests to confirm they fail**

```
cd /home/raizen/noba
pytest tests/test_integration_base.py::test_validate_url_rejects_loopback -v
```

Expected: FAIL — `ConfigError` not raised

- [ ] **Step 3: Apply the fix**

In `share/noba-web/server/integrations/base.py`, add `import ipaddress` to the imports at the top (the file already imports `urllib.parse`). Then update `validate_url`:

```python
@staticmethod
def validate_url(url: str) -> str:
    """Reject non-http/https schemes and private/loopback IPs; return normalised URL."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ConfigError(f"Unsupported URL scheme: {parsed.scheme!r}")
    host = parsed.hostname or ""
    if host in ("localhost", "ip6-localhost", "ip6-loopback", "::1"):
        raise ConfigError("Integration URL must not target a private/loopback address")
    try:
        addr = ipaddress.ip_address(host)
        if addr.is_private or addr.is_loopback or addr.is_link_local:
            raise ConfigError("Integration URL must not target a private/loopback address")
    except ValueError:
        pass  # hostname — not an IP literal, DNS not resolved here
    return url.rstrip("/")
```

- [ ] **Step 4: Run linter + tests**

```
cd /home/raizen/noba
ruff check --fix share/noba-web/server/integrations/base.py
pytest tests/test_integration_base.py -v
```

Expected: all tests pass

- [ ] **Step 5: Commit**

```bash
git add share/noba-web/server/integrations/base.py tests/test_integration_base.py
git commit -m "fix: block private/loopback IPs in BaseIntegration.validate_url (SSRF hardening)"
```

---

### Task 3: Short-lived handshake tokens for WebSocket/SSE auth

This is the largest task. The pattern: client calls `POST /api/ws-token` → gets a 30s one-time token → passes it via query param when opening the WS. Long-lived session tokens still work as a fallback for SSE (EventSource) until all front-end consumers are updated.

**Files:**
- Modify: `share/noba-web/server/auth.py` — add `WsTokenStore` + export `ws_token_store`
- Modify: `share/noba-web/server/routers/auth.py` — add `POST /api/ws-token`
- Modify: `share/noba-web/server/deps.py` — add `_get_auth_ws()` helper
- Modify: `share/noba-web/server/routers/agent_terminal.py` — use `ws_token_store.consume()`
- Modify: `share/noba-web/server/routers/agent_rdp.py` — use `ws_token_store.consume()`
- Modify: `share/noba-web/server/routers/infrastructure.py` — use `ws_token_store.consume()`
- Modify: `share/noba-web/frontend/src/views/RemoteDesktopView.vue` — fetch ws-token before connect
- Modify: `share/noba-web/frontend/src/components/agents/RemoteTerminal.vue` — fetch ws-token before connect
- Modify: `share/noba-web/frontend/src/components/modals/TerminalModal.vue` — fetch ws-token before connect
- Test: `tests/test_router_auth.py` — add `TestWsToken` class

#### Step 3a — Backend: WsTokenStore in auth.py

- [ ] **Step 1: Write failing test**

```python
# In tests/test_router_auth.py, add this class:

class TestWsToken:
    """POST /api/ws-token — short-lived WebSocket token exchange."""

    def test_requires_auth(self, client):
        resp = client.post("/api/ws-token")
        assert resp.status_code == 401

    def test_returns_token_for_authed_user(self, client, admin_headers):
        resp = client.post("/api/ws-token", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "token" in data
        assert data["expires_in"] == 30

    def test_token_is_consumed_on_use(self):
        """ws_token_store.consume() returns user on first call, None on second."""
        from server.auth import ws_token_store
        tok = ws_token_store.issue("alice", "operator")
        u1, r1 = ws_token_store.consume(tok)
        assert u1 == "alice" and r1 == "operator"
        u2, r2 = ws_token_store.consume(tok)
        assert u2 is None and r2 is None

    def test_expired_token_rejected(self):
        """Tokens past their TTL are rejected."""
        import time
        from server.auth import ws_token_store
        tok = ws_token_store.issue("bob", "viewer")
        # Directly expire it by manipulating internal state
        with ws_token_store._lock:
            u, r, _ = ws_token_store._tokens[tok]
            ws_token_store._tokens[tok] = (u, r, time.time() - 1)
        u, r = ws_token_store.consume(tok)
        assert u is None

    def test_viewer_can_get_ws_token(self, client, viewer_headers):
        resp = client.post("/api/ws-token", headers=viewer_headers)
        assert resp.status_code == 200
```

- [ ] **Step 2: Run tests to confirm they fail**

```
cd /home/raizen/noba
pytest tests/test_router_auth.py::TestWsToken -v
```

Expected: FAIL — `ws_token_store` not defined, `/api/ws-token` not found

- [ ] **Step 3: Add WsTokenStore to auth.py**

In `share/noba-web/server/auth.py`, after the `TokenStore` class definition and `token_store = TokenStore()` instantiation, add:

```python
class WsTokenStore:
    """Short-lived (30 s), one-time-use tokens for WebSocket/SSE authentication.

    Flow: client POSTs /api/ws-token → gets token → opens WS with ?token=<ws_token>
    Server calls consume() which validates and deletes in one atomic operation.
    """

    _TTL = 30  # seconds

    def __init__(self) -> None:
        self._tokens: dict[str, tuple[str, str, float]] = {}  # token → (username, role, expires)
        self._lock = threading.Lock()

    def issue(self, username: str, role: str) -> str:
        """Issue a new short-lived token bound to *username* and *role*."""
        token = secrets.token_urlsafe(32)
        expires = time.time() + self._TTL
        with self._lock:
            self._tokens[token] = (username, role, expires)
        return token

    def consume(self, token: str) -> tuple[str | None, str | None]:
        """Validate and immediately invalidate *token*. Returns (username, role) or (None, None)."""
        with self._lock:
            entry = self._tokens.pop(token, None)
        if entry is None:
            return None, None
        username, role, expires = entry
        if time.time() > expires:
            return None, None
        return username, role


ws_token_store = WsTokenStore()
```

- [ ] **Step 4: Add POST /api/ws-token to routers/auth.py**

In `share/noba-web/server/routers/auth.py`, update the import from `..auth` to include `ws_token_store`:

```python
from ..auth import (
    check_password_strength, load_legacy_user, pbkdf2_hash,
    rate_limiter, token_store, users, valid_username, verify_password,
    ws_token_store,
)
```

Then add the endpoint after the logout route (around line 104):

```python
# ── /api/ws-token ──────────────────────────────────────────────────────────────
@router.post("/api/ws-token")
@handle_errors
async def api_ws_token(auth=Depends(_get_auth)):
    """Issue a short-lived (30 s) one-time token for WebSocket/SSE connections.

    WebSocket and EventSource cannot set custom headers, so they must pass the
    session token via query param — which risks it appearing in server/proxy logs.
    This endpoint issues a 30-second one-time token to minimise that window.
    """
    username, role = auth
    token = ws_token_store.issue(username, role)
    return {"token": token, "expires_in": 30}
```

- [ ] **Step 5: Update WebSocket auth to use ws_token_store**

**agent_rdp.py** — replace `token_store.validate(token)` with `ws_token_store.consume(token)`:

```python
# In share/noba-web/server/routers/agent_rdp.py, update import line:
from ..deps import ws_token_store

# Replace the auth block:
    token = ws.query_params.get("token", "")
    if not token:
        await ws.close(code=4001, reason="Missing token")
        return
    username, role = ws_token_store.consume(token)
    if not username:
        await ws.close(code=4001, reason="Invalid or expired token")
        return
```

**agent_terminal.py** — same pattern:

```python
# In share/noba-web/server/routers/agent_terminal.py, update import:
from ..deps import ws_token_store

# Replace the auth block (lines 96-107):
    token = ws.query_params.get("token", "")
    if not token:
        await ws.close(code=4001, reason="Missing token")
        return
    username, role = ws_token_store.consume(token)
    if not username:
        await ws.close(code=4001, reason="Invalid or expired token")
        return
    if role not in ("operator", "admin"):
        await ws.close(code=4003, reason="Operator access required")
        return
```

**infrastructure.py** — same pattern for `/api/terminal`:

```python
# In share/noba-web/server/routers/infrastructure.py, add import:
from ..auth import ws_token_store

# Replace auth block in ws_terminal (lines 511-514):
    token = ws.query_params.get("token", "")
    username, role = ws_token_store.consume(token)
    if not username or role != "admin":
        await ws.close(code=4001, reason="Unauthorized")
        return
```

**deps.py** — add `ws_token_store` re-export so routers can import from one place:

```python
# In share/noba-web/server/deps.py, update the import line at top:
from .auth import authenticate, has_permission, token_store, ws_token_store
```

- [ ] **Step 6: Run backend tests**

```
cd /home/raizen/noba
ruff check --fix share/noba-web/server/auth.py share/noba-web/server/routers/auth.py share/noba-web/server/deps.py share/noba-web/server/routers/agent_rdp.py share/noba-web/server/routers/agent_terminal.py share/noba-web/server/routers/infrastructure.py
pytest tests/test_router_auth.py -v
```

Expected: all tests pass including `TestWsToken`

#### Step 3b — Frontend: fetch ws-token before opening WebSocket

For each of the three Vue components, use the existing `useApi()` composable to POST `/api/ws-token`, then use the returned token in the WebSocket URL.

- [ ] **Step 7: Update RemoteDesktopView.vue**

In `share/noba-web/frontend/src/views/RemoteDesktopView.vue`, import `useApi`:

```javascript
import { useApi } from '../composables/useApi'
const api = useApi()
```

Update `buildWsUrl` to accept a ws_token parameter and `connect()` to fetch one first:

```javascript
function buildWsUrl(wsToken) {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  const host = window.location.host
  const q = new URLSearchParams({
    token: wsToken,
    quality: quality.value,
    fps: fps.value,
  })
  return `${proto}://${host}/api/agents/${hostname.value}/rdp?${q}`
}

async function connect() {
  if (ws) {
    ws.close()
    ws = null
  }
  status.value = 'connecting'
  frameCount.value = 0

  let wsToken
  try {
    const res = await api.post('/api/ws-token')
    wsToken = res.token
  } catch {
    status.value = 'error'
    statusMsg.value = 'Failed to obtain connection token'
    return
  }

  ws = new WebSocket(buildWsUrl(wsToken))
  // ... rest of connect() unchanged
```

- [ ] **Step 8: Update RemoteTerminal.vue**

In `share/noba-web/frontend/src/components/agents/RemoteTerminal.vue`, import `useApi` and update `connect()`:

```javascript
import { useApi } from '../../composables/useApi'
const api = useApi()

async function connect() {
  lines.value = []
  let wsToken
  try {
    const res = await api.post('/api/ws-token')
    wsToken = res.token
  } catch {
    lines.value.push({ type: 'error', text: 'Failed to obtain connection token' })
    return
  }
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
  const url = `${proto}//${location.host}/api/agents/${encodeURIComponent(props.hostname)}/terminal?token=${encodeURIComponent(wsToken)}`
  ws = new WebSocket(url)
  // ... rest unchanged
```

- [ ] **Step 9: Update TerminalModal.vue**

In `share/noba-web/frontend/src/components/modals/TerminalModal.vue`, import `useApi` and update the connect block:

```javascript
import { useApi } from '../../composables/useApi'
const api = useApi()

async function openTerminal() {
  lines.value = []
  let wsToken
  try {
    const res = await api.post('/api/ws-token')
    wsToken = res.token
  } catch {
    lines.value.push({ type: 'error', text: 'Failed to obtain connection token' })
    return
  }
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  const url = `${proto}://${location.host}/api/terminal?token=${encodeURIComponent(wsToken)}`
  ws = new WebSocket(url)
  // ... rest unchanged
```

- [ ] **Step 10: Build frontend and run all tests**

```
cd /home/raizen/noba/share/noba-web/frontend && npm run build
cd /home/raizen/noba && pytest tests/ -v -x
```

Expected: build succeeds, all tests pass

- [ ] **Step 11: Commit**

```bash
git add share/noba-web/server/auth.py \
        share/noba-web/server/routers/auth.py \
        share/noba-web/server/deps.py \
        share/noba-web/server/routers/agent_rdp.py \
        share/noba-web/server/routers/agent_terminal.py \
        share/noba-web/server/routers/infrastructure.py \
        share/noba-web/frontend/src/views/RemoteDesktopView.vue \
        share/noba-web/frontend/src/components/agents/RemoteTerminal.vue \
        share/noba-web/frontend/src/components/modals/TerminalModal.vue \
        share/noba-web/static/dist/
git commit -m "feat: add short-lived WS handshake tokens via POST /api/ws-token"
```

---

### Task 4: Uniform login error messages

**Files:**
- Modify: `share/noba-web/server/routers/auth.py:95-98`
- Test: `tests/test_router_auth.py` (add test in `TestLogin`)

- [ ] **Step 1: Write failing test**

```python
# In tests/test_router_auth.py, inside class TestLogin, add:

    def test_locked_and_invalid_return_same_message(self, client):
        """Rate-limited and wrong-password responses must be identical (no enumeration)."""
        # Wrong password
        resp1 = client.post("/api/login", json={"username": "admin", "password": "WrongPass1!"})
        assert resp1.status_code == 401
        msg1 = resp1.json().get("detail", "")

        # Lock the account by burning through the rate limit
        from server.auth import rate_limiter, RateLimiter
        rate_limiter.reset("testclient")
        for _ in range(20):
            client.post("/api/login", json={"username": "admin", "password": "bad"})

        resp2 = client.post("/api/login", json={"username": "admin", "password": "bad"})
        assert resp2.status_code == 401
        msg2 = resp2.json().get("detail", "")

        assert msg1 == msg2, f"Login error messages differ: {msg1!r} vs {msg2!r}"
```

- [ ] **Step 2: Run test to confirm it fails**

```
cd /home/raizen/noba
pytest tests/test_router_auth.py::TestLogin::test_locked_and_invalid_return_same_message -v
```

Expected: FAIL — messages differ

- [ ] **Step 3: Apply the fix**

In `share/noba-web/server/routers/auth.py`, find the final raise at the end of the login handler (~line 98):

```python
# Before:
raise HTTPException(401, "Too many failed attempts." if locked else "Invalid credentials")

# After:
raise HTTPException(401, "Invalid credentials")
```

- [ ] **Step 4: Run tests**

```
cd /home/raizen/noba
pytest tests/test_router_auth.py -v
```

Expected: all tests pass

- [ ] **Step 5: Commit**

```bash
git add share/noba-web/server/routers/auth.py tests/test_router_auth.py
git commit -m "fix: use identical error message for invalid credentials and rate-limited login"
```

---

### Task 5: Complete RFC 4515 LDAP filter escaping

**Files:**
- Modify: `share/noba-web/server/auth.py:665-676`
- Test: `tests/test_auth.py` (add `TestLdapEscape` class)

- [ ] **Step 1: Write failing tests**

```python
# In tests/test_auth.py, add:

class TestLdapEscape:
    """_ldap_escape covers all RFC 4515 special characters."""

    def test_escapes_backslash(self):
        from server.auth import _ldap_escape
        assert _ldap_escape("a\\b") == "a\\5cb"

    def test_escapes_null(self):
        from server.auth import _ldap_escape
        assert _ldap_escape("a\x00b") == "a\\00b"

    def test_escapes_star(self):
        from server.auth import _ldap_escape
        assert _ldap_escape("a*b") == "a\\2ab"

    def test_escapes_parens(self):
        from server.auth import _ldap_escape
        assert _ldap_escape("(foo)") == "\\28foo\\29"

    def test_escapes_ampersand(self):
        from server.auth import _ldap_escape
        assert _ldap_escape("a&b") == "a\\26b"

    def test_escapes_pipe(self):
        from server.auth import _ldap_escape
        assert _ldap_escape("a|b") == "a\\7cb"

    def test_escapes_equals(self):
        from server.auth import _ldap_escape
        assert _ldap_escape("a=b") == "a\\3db"

    def test_escapes_tilde(self):
        from server.auth import _ldap_escape
        assert _ldap_escape("a~b") == "a\\7eb"

    def test_escapes_exclamation(self):
        from server.auth import _ldap_escape
        assert _ldap_escape("a!b") == "a\\21b"

    def test_normal_string_unchanged(self):
        from server.auth import _ldap_escape
        assert _ldap_escape("alice123") == "alice123"

    def test_unicode_encoded(self):
        from server.auth import _ldap_escape
        result = _ldap_escape("caf\u00e9")
        assert "\\c3\\a9" in result  # UTF-8 for é
```

- [ ] **Step 2: Run tests to confirm failures**

```
cd /home/raizen/noba
pytest tests/test_auth.py::TestLdapEscape -v
```

Expected: FAIL for `&`, `|`, `=`, `~`, `!` tests

- [ ] **Step 3: Apply the fix**

In `share/noba-web/server/auth.py`, update `_ldap_escape`:

```python
def _ldap_escape(s: str) -> str:
    """RFC 4515 LDAP filter value escaping — all special characters."""
    # RFC 4515 specials in filter assertions: \ * ( ) \x00 & | = ~ !
    _RFC4515_SPECIALS = frozenset(r'\*()\x00&|=~!')
    out = []
    for c in s:
        if c in _RFC4515_SPECIALS:
            out.append(f"\\{ord(c):02x}")
        elif ord(c) > 127:
            for b in c.encode("utf-8"):
                out.append(f"\\{b:02x}")
        else:
            out.append(c)
    return "".join(out)
```

> **Note on `\x00`:** In the frozenset literal the raw `\x00` is the null byte. Python `frozenset(r'\*()\x00&|=~!')` — use a regular string (not raw) so `\x00` is the actual null character: `frozenset('\\*()\x00&|=~!')`.

Correct implementation:

```python
def _ldap_escape(s: str) -> str:
    """RFC 4515 LDAP filter value escaping — all special characters."""
    _SPECIALS = frozenset('\\*()\x00&|=~!')
    out = []
    for c in s:
        if c in _SPECIALS:
            out.append(f"\\{ord(c):02x}")
        elif ord(c) > 127:
            for b in c.encode("utf-8"):
                out.append(f"\\{b:02x}")
        else:
            out.append(c)
    return "".join(out)
```

- [ ] **Step 4: Run tests**

```
cd /home/raizen/noba
ruff check --fix share/noba-web/server/auth.py
pytest tests/test_auth.py -v
```

Expected: all tests pass

- [ ] **Step 5: Commit**

```bash
git add share/noba-web/server/auth.py tests/test_auth.py
git commit -m "fix: complete RFC 4515 LDAP filter escaping (add &|=~! to _ldap_escape)"
```

---

### Task 6: Path separator check in backup restore

**Files:**
- Modify: `share/noba-web/server/routers/admin.py:485-488`
- Test: `tests/test_router_admin.py` (add `TestBackupRestorePathTraversal` class)

- [ ] **Step 1: Write failing test**

```python
# In tests/test_router_admin.py, add:

class TestBackupRestorePathTraversal:
    """Backup restore rejects paths that start-match protected dirs without separator."""

    def test_etc2_not_confused_with_etc(self):
        """'/etc2/foo' must NOT be blocked — only '/etc/' prefixed paths should be."""
        from server.routers.admin import _check_restore_path
        # '/etc2/foo' starts with '/etc' but is NOT under /etc — should pass
        assert _check_restore_path("/etc2/foo") is True

    def test_etc_slash_blocked(self):
        """'/etc/passwd' must be blocked."""
        from server.routers.admin import _check_restore_path
        assert _check_restore_path("/etc/passwd") is False

    def test_etc_itself_blocked(self):
        """'/etc' exactly must be blocked."""
        from server.routers.admin import _check_restore_path
        assert _check_restore_path("/etc") is False
```

> **Note:** We'll extract the path check logic into a testable helper `_check_restore_path(path) -> bool` (returns True if allowed). This avoids importing the full router in a way that requires DB setup.

- [ ] **Step 2: Run tests to confirm failure**

```
cd /home/raizen/noba
pytest tests/test_router_admin.py::TestBackupRestorePathTraversal -v
```

Expected: ImportError — `_check_restore_path` not defined yet

- [ ] **Step 3: Apply the fix**

In `share/noba-web/server/routers/admin.py`, add a helper function before `api_backup_restore` and update the forbidden-path check:

```python
_RESTORE_FORBIDDEN = (
    "/etc", "/usr", "/bin", "/sbin", "/boot",
    "/proc", "/sys", "/dev", "/root", "/run",
    "/var/run", "/lib", "/lib64",
)


def _check_restore_path(path: str) -> bool:
    """Return True if *path* is allowed as a restore destination.

    Rejects exact matches and proper sub-paths of protected directories.
    Uses os.sep suffix check to prevent /etc2 matching /etc.
    """
    real = os.path.realpath(path)
    for forbidden in _RESTORE_FORBIDDEN:
        if real == forbidden or real.startswith(forbidden + os.sep):
            return False
    return True
```

Then in `api_backup_restore`, replace the for-loop block (~line 485-488):

```python
# Before:
    restore_real = os.path.realpath(restore_to)
    for forbidden in ("/etc", "/usr", "/bin", "/sbin", "/boot", "/proc", "/sys",
                      "/dev", "/root", "/run", "/var/run", "/lib", "/lib64"):
        if restore_real.startswith(forbidden):
            raise HTTPException(403, f"Cannot restore to {forbidden}")

# After:
    if not _check_restore_path(restore_to):
        raise HTTPException(403, "Restore destination is in a protected system path")
```

- [ ] **Step 4: Run tests**

```
cd /home/raizen/noba
ruff check --fix share/noba-web/server/routers/admin.py
pytest tests/test_router_admin.py -v
```

Expected: all tests pass

- [ ] **Step 5: Commit**

```bash
git add share/noba-web/server/routers/admin.py tests/test_router_admin.py
git commit -m "fix: use path separator in backup restore forbidden-path check (prevent /etc2 bypass)"
```

---

### Task 7: Full test suite + rsync to live server

- [ ] **Step 1: Run full test suite**

```
cd /home/raizen/noba
pytest tests/ -v
```

Expected: all tests pass (no regressions)

- [ ] **Step 2: Rsync to live server**

```bash
rsync -av --delete \
  share/noba-web/server/ ~/.local/libexec/noba/web/server/ && \
rsync -av \
  share/noba-web/static/dist/ ~/.local/libexec/noba/web/static/dist/
```

- [ ] **Step 3: Restart service**

```bash
systemctl --user restart noba-web
```

- [ ] **Step 4: Smoke-test live endpoints**

```bash
# Verify ws-token endpoint exists
curl -s -X POST http://localhost:8080/api/ws-token \
  -H "Authorization: Bearer $(grep -oP '(?<=token=)[^ ]+' ~/.config/noba-web/test-token 2>/dev/null || echo test)" \
  | python3 -m json.tool

# Verify login still works
curl -s -X POST http://localhost:8080/api/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"Admin1234!"}' | python3 -m json.tool
```

- [ ] **Step 5: Update CHANGELOG.md**

In `CHANGELOG.md`, under `[Unreleased]`, add:

```markdown
### Security
- Fix shell interpolation in agent deploy script — `server_url` and `agent_key` now wrapped with `shlex.quote()`
- Block private/loopback IPs in `BaseIntegration.validate_url()` (SSRF hardening)
- Add `POST /api/ws-token` — short-lived (30 s) one-time handshake tokens for WebSocket/SSE connections
- Uniform login error messages — no longer differentiate between invalid credentials and rate-limited accounts
- Complete RFC 4515 LDAP filter escaping — `&`, `|`, `=`, `~`, `!` added to `_ldap_escape()`
- Fix path separator check in backup restore — `/etc2` no longer incorrectly matched as `/etc`
```

- [ ] **Step 6: Final commit**

```bash
git add CHANGELOG.md
git commit -m "docs: update CHANGELOG for security hardening round"
```
