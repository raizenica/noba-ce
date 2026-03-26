# ADR-002: Short-Lived One-Time Tokens for WebSocket Authentication

**Status:** Accepted
**Date:** 2026-01-20
**Deciders:** Raizen

---

## Context

FastAPI's `WebSocket` upgrade endpoint cannot receive custom HTTP headers — the browser's `WebSocket` constructor only accepts a URL and optional `protocols` array. This makes standard Bearer token authentication impossible for WebSocket connections initiated from the frontend.

Three approaches were considered:

1. **Query-parameter token** — append `?token=<api_key>` to the URL. Simple, but the API key appears in server access logs and browser history, creating a persistent credential leak.
2. **Cookie-based auth** — set a session cookie; the browser sends it automatically on upgrade. Requires CSRF protection and complicates the stateless API design.
3. **Short-lived handshake token** — issue a one-time token via a normal authenticated REST endpoint, then use that token in the WebSocket URL. The token is valid for seconds, not hours.

## Decision

Implement a `WsTokenStore` in `auth.py` that issues single-use tokens with a 30-second TTL:

```python
class WsTokenStore:
    def __init__(self):
        self._tokens: dict[str, tuple[str, float]] = {}  # token → (username, expiry)
        self._lock = threading.Lock()

    def issue(self, username: str) -> str:
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._tokens[token] = (username, time.time() + 30)
        return token

    def consume(self, token: str) -> str | None:
        with self._lock:
            entry = self._tokens.pop(token, None)
        if entry and entry[1] > time.time():
            return entry[0]  # username
        return None
```

Flow:
1. Frontend calls `POST /api/auth/ws-token` (requires valid session)
2. Server issues a 30-second single-use token
3. Frontend opens `ws://host/api/agent/ws?ws_token=<token>`
4. Server calls `consume()` — if valid, upgrades; token is immediately deleted
5. Long-term connection is authenticated by the established session, not the token

## Consequences

**Positive:**
- API key never appears in WebSocket URLs or access logs
- Token is useless after first use — replay attacks cannot succeed
- 30-second window is short enough that log-scraped tokens expire before they can be exploited
- No cookie complexity; compatible with cross-origin setups

**Negative:**
- Extra round-trip (REST → WebSocket) vs a direct upgrade
- In-memory store: tokens are lost on server restart (acceptable — clients reconnect)
- Periodic cleanup of expired-but-unconsumed tokens needed to avoid memory growth (handled by a background sweep on issue)

**Alternatives rejected:**
- Query-parameter API key: permanent credential in logs — not acceptable for a production deployment
- Protocols header trick: non-standard, breaks on some proxies
