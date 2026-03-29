"""Pytest fixtures for NOBA backend tests."""
from __future__ import annotations

import hashlib
import logging
import os
import sys
import tempfile

import pytest

# Redirect HOME to an isolated temp tree BEFORE importing any noba modules
_tmp = tempfile.mkdtemp(prefix="noba_test_")
_fake_home = os.path.join(_tmp, "home")
os.makedirs(_fake_home, exist_ok=True)
os.environ["HOME"] = _fake_home
os.environ["NOBA_CONFIG"] = os.path.join(_fake_home, ".config", "noba", "config.yaml")
os.environ["PID_FILE"] = os.path.join(_tmp, "noba.pid")

# Pre-create users.conf so UserStore doesn't generate a random password
_salt = "testsalt"
_dk = hashlib.pbkdf2_hmac("sha256", b"Admin1234!", _salt.encode(), 200_000)
_hash = f"pbkdf2:{_salt}:{_dk.hex()}"
_cfg_dir = os.path.join(_fake_home, ".config", "noba-web")
os.makedirs(_cfg_dir, exist_ok=True)
with open(os.path.join(_cfg_dir, "users.conf"), "w") as f:
    f.write(f"admin:{_hash}:admin\n")

# Ensure the server package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "share", "noba-web"))

# Suppress logging
logging.disable(logging.CRITICAL)


@pytest.fixture()
def client():
    """TestClient with the full NOBA app."""
    from starlette.testclient import TestClient
    from server.app import app
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture()
def admin_token():
    """Generate a valid admin bearer token."""
    from server.auth import token_store
    return token_store.generate("admin", "admin")


@pytest.fixture()
def admin_headers(admin_token):
    """Authorization headers for admin user."""
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture()
def operator_token():
    """Generate a valid operator bearer token."""
    from server.auth import token_store
    return token_store.generate("operator_user", "operator")


@pytest.fixture()
def operator_headers(operator_token):
    """Authorization headers for operator user."""
    return {"Authorization": f"Bearer {operator_token}"}


@pytest.fixture()
def viewer_token():
    """Generate a valid viewer bearer token."""
    from server.auth import token_store
    return token_store.generate("viewer_user", "viewer")


@pytest.fixture()
def viewer_headers(viewer_token):
    """Authorization headers for viewer user."""
    return {"Authorization": f"Bearer {viewer_token}"}


@pytest.fixture()
def agent_key_headers():
    """Headers with test agent key for agent-authed endpoints."""
    return {"X-Agent-Key": "test-agent-key-12345"}


@pytest.fixture(autouse=False)
def mock_agent_key():
    """Mock yaml_config to return a known agent key."""
    from unittest.mock import patch
    with patch("server.routers.agents.read_yaml_settings",
               return_value={"agentKeys": "test-agent-key-12345"}):
        yield


@pytest.fixture(autouse=True)
def _clear_saml_states():
    """Ensure SAML relay-state store is clean between tests."""
    from server.routers.saml import _saml_states, _saml_states_lock
    with _saml_states_lock:
        _saml_states.clear()
    yield
    with _saml_states_lock:
        _saml_states.clear()


@pytest.fixture(autouse=True)
def _clear_webauthn_challenges():
    """Ensure WebAuthn challenge store is clean between tests."""
    from server.routers.webauthn import _challenges
    _challenges.clear()
    yield
    _challenges.clear()


@pytest.fixture(autouse=True)
def _clean_agent_state():
    """Reset agent in-memory stores between tests to prevent leakage."""
    from server.agent_store import (
        _agent_data, _agent_data_lock,
        _agent_commands, _agent_cmd_lock,
        _agent_cmd_results,
    )
    with _agent_data_lock:
        _agent_data.clear()
    with _agent_cmd_lock:
        _agent_commands.clear()
        _agent_cmd_results.clear()
    yield
    with _agent_data_lock:
        _agent_data.clear()
    with _agent_cmd_lock:
        _agent_commands.clear()
        _agent_cmd_results.clear()


import os as _os


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "postgres: requires DATABASE_URL env var pointing to a live PostgreSQL instance",
    )


def pytest_collection_modifyitems(items):
    if not _os.environ.get("DATABASE_URL", "").lower().startswith("postgres"):
        skip = pytest.mark.skip(reason="DATABASE_URL not set to a PostgreSQL URL")
        for item in items:
            if "postgres" in item.keywords:
                item.add_marker(skip)
