#!/usr/bin/env python3
"""smoke.py — API smoke test that hits every endpoint.

Rapidly validates that all API routes respond without 500 errors.
Unlike e2e.py (which tests UI rendering), this tests the API layer directly.

Usage:
    python dev/smoke.py                  # Hit all endpoints
    python dev/smoke.py --filter stats   # Only endpoints matching 'stats'
    python dev/smoke.py --verbose        # Show response bodies
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import httpx

DEFAULT_PORT = int(os.environ.get("NOBA_DEV_PORT", "8099"))
DEFAULT_HOST = os.environ.get("NOBA_DEV_HOST", "127.0.0.1")
DEFAULT_USER = os.environ.get("NOBA_DEV_USER", "raizen")
DEFAULT_PASS = os.environ.get("NOBA_DEV_PASS", "")

# Colors
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
NC = "\033[0m"


def extract_routes(app_py_path: Path) -> list[dict]:
    """Parse app.py to find all route definitions."""
    content = app_py_path.read_text()
    routes = []
    # Match @app.get/post/put/delete("/path")
    for match in re.finditer(
        r'@app\.(get|post|put|delete|patch)\("(/api/[^"]+)"', content
    ):
        method = match.group(1).upper()
        path = match.group(2)
        # Skip SSE streams (they hang)
        if "stream" in path.lower():
            continue
        # Skip websocket
        if "ws" in path.lower() and "terminal" in path.lower():
            continue
        routes.append({"method": method, "path": path})
    return routes


def login(base_url: str, username: str, password: str) -> str | None:
    """Login and return token."""
    try:
        r = httpx.post(
            f"{base_url}/api/login",
            json={"username": username, "password": password},
            timeout=5,
        )
        if r.status_code == 200:
            return r.json().get("token")
    except Exception as e:
        print(f"Login failed: {e}")
    return None


def smoke_test(
    base_url: str,
    token: str,
    routes: list[dict],
    verbose: bool = False,
    filter_str: str | None = None,
):
    """Hit every route and report results."""
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    if filter_str:
        routes = [r for r in routes if filter_str.lower() in r["path"].lower()]

    results = {"pass": 0, "fail": 0, "skip": 0, "errors": []}

    print(f"\nSmoke testing {len(routes)} endpoint(s)...\n")

    for route in routes:
        method = route["method"]
        path = route["path"]

        # Skip routes with path params (need real IDs)
        if "{" in path:
            print(f"  {YELLOW}SKIP{NC} {method:6} {path} (needs path params)")
            results["skip"] += 1
            continue

        # Skip destructive endpoints
        if method in ("DELETE", "PUT", "PATCH") and "test" not in path:
            print(f"  {YELLOW}SKIP{NC} {method:6} {path} (destructive)")
            results["skip"] += 1
            continue

        # Skip POST endpoints that need bodies (except specific safe ones)
        safe_posts = ["/api/smart", "/api/auth/logout"]
        if method == "POST" and path not in safe_posts:
            print(f"  {YELLOW}SKIP{NC} {method:6} {path} (needs body)")
            results["skip"] += 1
            continue

        try:
            start = time.time()
            r = httpx.request(
                method, f"{base_url}{path}", headers=headers, timeout=10
            )
            elapsed = (time.time() - start) * 1000

            if r.status_code < 500:
                print(f"  {GREEN}PASS{NC} {method:6} {path} → {r.status_code} ({elapsed:.0f}ms)")
                results["pass"] += 1
                if verbose and r.headers.get("content-type", "").startswith("application/json"):
                    try:
                        body = r.json()
                        preview = json.dumps(body, indent=2)[:200]
                        print(f"         {preview}")
                    except Exception:
                        pass
            else:
                print(f"  {RED}FAIL{NC} {method:6} {path} → {r.status_code} ({elapsed:.0f}ms)")
                results["fail"] += 1
                results["errors"].append((method, path, r.status_code, r.text[:200]))
                if verbose:
                    print(f"         {r.text[:200]}")

        except Exception as e:
            print(f"  {RED}FAIL{NC} {method:6} {path} → {e}")
            results["fail"] += 1
            results["errors"].append((method, path, 0, str(e)))

    # Summary
    print(f"\n{'─' * 50}")
    print(
        f"  {GREEN}{results['pass']} passed{NC}, "
        f"{RED}{results['fail']} failed{NC}, "
        f"{YELLOW}{results['skip']} skipped{NC}"
    )

    if results["errors"]:
        print(f"\n{RED}Errors:{NC}")
        for method, path, status, detail in results["errors"]:
            print(f"  {method} {path} → {status}")
            print(f"    {detail[:120]}")

    print(f"{'─' * 50}\n")
    return results["fail"] == 0


def main():
    parser = argparse.ArgumentParser(description="NOBA API Smoke Tester")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--user", default=DEFAULT_USER)
    parser.add_argument("--password", default=DEFAULT_PASS)
    parser.add_argument("--filter", help="Filter routes by path substring")
    parser.add_argument("--verbose", "-v", action="store_true")

    args = parser.parse_args()
    base_url = f"http://{args.host}:{args.port}"

    # Check server
    try:
        httpx.get(f"{base_url}/api/health", timeout=3)
    except Exception:
        print(f"Server not reachable at {base_url}")
        sys.exit(1)

    # Parse routes from source
    app_py = Path(__file__).resolve().parent.parent / "share" / "noba-web" / "server" / "app.py"
    routes = extract_routes(app_py)
    print(f"Found {len(routes)} API routes in app.py")

    # Login
    token = ""
    if args.password:
        token = login(base_url, args.user, args.password) or ""
        if token:
            print(f"Authenticated as {args.user}")
        else:
            print("Login failed — testing without auth")

    success = smoke_test(base_url, token, routes, args.verbose, args.filter)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
