# ADR-007: Centralized Exception Handling via `@handle_errors` Decorator

**Status:** Accepted
**Date:** 2026-01-30
**Deciders:** Raizen

---

## Context

NOBA's 19 FastAPI routers each contain dozens of route handlers. Early implementations had try/except blocks repeated in every handler:

```python
# repeated ~80 times across routers
@router.get("/api/something")
async def get_something(auth=Depends(_get_auth)):
    try:
        result = do_work()
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in get_something: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
```

This pattern had several failure modes in practice:
- Some handlers forgot to re-raise `HTTPException` before the generic catch, returning 500 for intentional 404s
- Error messages sometimes leaked internal exception strings (stack traces, file paths) to API clients
- Inconsistent logging format made log aggregation harder
- Adding cross-cutting concerns (metrics, tracing) would require touching every handler

## Decision

Implement a `@handle_errors` decorator in a shared utilities module:

```python
def handle_errors(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except HTTPException:
            raise  # pass through intentional HTTP errors unchanged
        except Exception as e:
            logger.error(f"[{func.__name__}] Unhandled error: {type(e).__name__}: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")
    return wrapper
```

Key properties:
- `HTTPException` is always re-raised unchanged — 404s, 403s, and 422s pass through
- Generic exceptions produce a generic `500` with `"Internal server error"` — no internal details leak
- The decorator logs the function name and exception type for debugging without exposing it to clients
- Applied at the router level so all handlers in a module inherit it

## Consequences

**Positive:**
- Consistent 500 response format across all 19 routers — clients can handle errors uniformly
- No internal exception strings leaked to API consumers
- Single place to add observability (metrics counters, tracing spans) in future
- Route handlers read cleanly — no boilerplate try/except

**Negative:**
- Hides exceptions from the call site — handlers that intentionally use exceptions for control flow must use `HTTPException`
- Async-only implementation — sync routes (if added) would need a separate decorator
- Error context is limited to function name + exception type; stack traces go to the server log only

**Test implications:**
Tests must assert against the generic `"Internal server error"` detail string, not the raw exception message. This is intentional — any test that asserts raw exception text would be testing implementation details that callers should never see. See `test_handle_errors.py` for the canonical pattern.
