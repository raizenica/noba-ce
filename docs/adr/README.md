# Architectural Decision Records

This directory documents significant architectural decisions made during NOBA's development.
Each ADR captures the context, the decision, and its consequences — the *why*, not just the *what*.

## Index

| ADR | Title | Status |
|-----|-------|--------|
| [ADR-001](ADR-001-sqlite-dual-connection-pattern.md) | Dual-Connection SQLite with Explicit `(conn, lock, ...)` Pattern | Accepted |
| [ADR-002](ADR-002-websocket-handshake-tokens.md) | Short-Lived One-Time Tokens for WebSocket Authentication | Accepted |
| [ADR-003](ADR-003-agent-as-zipapp.md) | Agent Distributed as Python Zipapp (`.pyz`) | Accepted |
| [ADR-004](ADR-004-sse-telemetry-with-polling-fallback.md) | Server-Sent Events for Live Telemetry with Polling Fallback | Accepted |
| [ADR-005](ADR-005-rdp-frame-fanout-via-asyncio-queue.md) | RDP Frame Fan-Out via Per-Subscriber `asyncio.Queue` | Accepted |
| [ADR-006](ADR-006-risk-tiered-agent-commands.md) | Risk-Tiered Agent Commands (Low / Medium / High) | Accepted |
| [ADR-007](ADR-007-centralized-error-handling-decorator.md) | Centralized Exception Handling via `@handle_errors` Decorator | Accepted |

## Format

Each ADR follows this structure:
- **Status**: `Proposed` → `Accepted` → `Superseded` (with link to replacement)
- **Context**: The forces and constraints that drove the decision
- **Decision**: What was chosen and why
- **Consequences**: Trade-offs, both positive and negative
