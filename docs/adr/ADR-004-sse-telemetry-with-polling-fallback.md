# ADR-004: Server-Sent Events for Live Telemetry with Polling Fallback

**Status:** Accepted
**Date:** 2026-01-25
**Deciders:** Raizen

---

## Context

The NOBA dashboard displays live CPU, memory, network, and process data that updates every 30 seconds. Users expect near-real-time feedback without manual page refreshes.

Options considered:
1. **Client polling** — frontend `setInterval` calling `GET /api/stats` every N seconds. Simple but wastes bandwidth and creates N×M server load (N clients × M metric endpoints).
2. **WebSockets** — full duplex, bidirectional. Necessary for interactive features (terminal, RDP) but adds complexity (upgrade handshake, connection management) for a one-way data stream.
3. **Server-Sent Events (SSE)** — HTTP-based, one-way push. Browser has native `EventSource` API; automatic reconnect; works through HTTP/1.1 proxies; no upgrade handshake.
4. **Long-polling** — server holds request open until data is available. Heavier on server resources and harder to implement correctly.

## Decision

Use **SSE** (`text/event-stream`) for all live dashboard data streams:

```python
# FastAPI SSE endpoint pattern
@router.get("/api/stats/stream")
async def stats_stream(auth=Depends(_get_auth_sse)):
    async def event_generator():
        while True:
            data = collect_current_stats()
            yield f"data: {json.dumps(data)}\n\n"
            await asyncio.sleep(STREAM_INTERVAL)
    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

`_get_auth_sse` is a special auth dependency that accepts the API key as a query parameter (`?token=...`) because `EventSource` cannot set custom headers. This is the only place query-parameter auth is permitted.

**Polling fallback** is implemented in the frontend: if `EventSource` construction fails or the connection is lost for >30 seconds, the dashboard silently switches to `setInterval`-based polling until SSE reconnects.

## Consequences

**Positive:**
- Persistent HTTP connection — no per-update handshake overhead
- Browser handles reconnection automatically (with `EventSource.onerror`)
- Works through nginx reverse proxies (with `proxy_buffering off`)
- Server pushes only when data changes — no wasted round-trips
- Simpler than WebSocket for unidirectional streams

**Negative:**
- `EventSource` cannot set `Authorization` headers — requires the `_get_auth_sse` query-param fallback (see CLAUDE.md pitfalls)
- HTTP/1.1 has a 6-connection-per-host limit; each SSE stream consumes one. Mitigated by multiplexing multiple event types onto a single stream.
- nginx must be configured with `proxy_buffering off` or data sits in the proxy buffer

**Why not WebSocket for telemetry:**
WebSocket is used for agent communication (commands, terminal, RDP) where bidirectional messaging is required. Using it for simple telemetry would conflate the two channels and require message-type routing on both ends.
