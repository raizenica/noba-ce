# ADR-005: RDP Frame Fan-Out via Per-Subscriber `asyncio.Queue`

**Status:** Accepted
**Date:** 2026-03-01
**Deciders:** Raizen

---

## Context

The Remote Desktop feature streams JPEG frames from an agent (via a single persistent WebSocket) to one or more browser clients. Multiple operators may watch the same machine simultaneously.

The agent produces frames on its own thread and sends them over the agent WebSocket. The server must distribute each frame to all currently connected browser clients.

Constraints:
- The agent WebSocket handler is a single async task — it cannot block waiting for slow clients
- Browser WebSocket connections may be slow or briefly stalled (e.g. mobile)
- A slow client must not delay frames for fast clients
- Frame delivery is best-effort: dropping stale frames is acceptable, losing connection is not

## Decision

Maintain a **per-subscriber `asyncio.Queue`** in `agent_store.py`:

```python
# agent_store.py
_rdp_subscribers: dict[str, list[asyncio.Queue]] = {}

def subscribe_rdp(hostname: str) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=10)
    _rdp_subscribers.setdefault(hostname, []).append(q)
    return q

def unsubscribe_rdp(hostname: str, q: asyncio.Queue) -> None:
    subs = _rdp_subscribers.get(hostname, [])
    with contextlib.suppress(ValueError):
        subs.remove(q)

def notify_rdp_subscribers(hostname: str, msg: dict) -> None:
    for q in list(_rdp_subscribers.get(hostname, [])):
        try:
            q.put_nowait(msg)
        except asyncio.QueueFull:
            pass  # drop stale frame for this subscriber
```

Each browser session calls `subscribe_rdp()` on connect and `unsubscribe_rdp()` on disconnect. The agent WebSocket handler calls `notify_rdp_subscribers()` for every incoming frame — it never blocks.

**Clipboard correlation** uses the same infrastructure but with a dedicated one-shot queue registered via `register_clipboard_request(req_id, q)` and consumed via `pop_clipboard_request(req_id)`, ensuring clipboard responses are routed only to the requesting client.

## Consequences

**Positive:**
- Agent handler never blocks on slow clients — `put_nowait` either enqueues or drops
- `maxsize=10` caps per-subscriber memory at ~10 frames (~500 KB typical) — slow clients shed load automatically
- Clean subscriber lifecycle: `subscribe` on connect, `unsubscribe` in `finally` block
- Fan-out is O(N subscribers) per frame — acceptable at homelab/SMB scale

**Negative:**
- Subscribers that fall behind drop frames silently — visible as momentary freezes in the viewer
- In-memory only: server restart drops all active sessions (clients reconnect)
- No flow control toward the agent — it produces at its configured FPS regardless of subscriber count

**Alternatives rejected:**
- asyncio pubsub libraries (e.g. `aioredis` channels): adds a dependency and a process boundary for a single-server deployment
- Shared list with asyncio locks: equivalent complexity, no clear benefit over Queue's built-in thread safety
