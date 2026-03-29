#!/usr/bin/env python3
"""Noba Command Center – server launcher.

Requires FastAPI and uvicorn. Install with:
    pip install fastapi 'uvicorn[standard]' psutil pyyaml
"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))


def _load_yaml_web_config() -> dict:
    """Load the 'web' section from YAML config."""
    try:
        import yaml
        config_path = os.environ.get(
            "NOBA_CONFIG",
            os.path.expanduser("~/.config/noba/config.yaml"),
        )
        if os.path.isfile(config_path):
            with open(config_path) as f:
                cfg = yaml.safe_load(f) or {}
            return cfg.get("web", {})
    except Exception:
        pass
    return {}


def _resolve_network() -> tuple[str, int, dict]:
    """Resolve host, port, and SSL config from env vars with YAML fallback."""
    web = _load_yaml_web_config()
    host = os.environ.get("HOST", "") or web.get("host", "0.0.0.0")
    # YAML config takes priority for port (GUI-managed), env var is fallback
    yaml_port = web.get("port")
    port = int(yaml_port) if yaml_port else int(os.environ.get("PORT", 8080))
    # SSL: env vars take priority, then YAML config
    cert = os.environ.get("SSL_CERT", "") or web.get("sslCertPath", "")
    key = os.environ.get("SSL_KEY", "") or web.get("sslKeyPath", "")
    ssl_kwargs = {}
    if cert and key and os.path.isfile(cert) and os.path.isfile(key):
        ssl_kwargs["ssl_certfile"] = cert
        ssl_kwargs["ssl_keyfile"] = key
    return host, port, ssl_kwargs


if __name__ == "__main__":
    # Ensure the package directory is on sys.path so `from server.app import app` works
    if _HERE not in sys.path:
        sys.path.insert(0, _HERE)

    try:
        import uvicorn  # noqa: F401
        from server.app import app  # noqa: F401
    except ImportError as e:
        print(f"[noba] Missing dependency: {e}", file=sys.stderr, flush=True)
        print("[noba] Install with:  pip install fastapi 'uvicorn[standard]' psutil pyyaml",
              file=sys.stderr, flush=True)
        sys.exit(1)

    os.chdir(_HERE)
    _host, _port, _ssl = _resolve_network()
    uvicorn.run(app, host=_host, port=_port, log_config=None, access_log=False, **_ssl)
