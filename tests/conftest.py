"""Pytest fixtures for NOBA backend tests."""
import os
import sys
import tempfile

# Redirect HOME to an isolated temp tree BEFORE importing any noba modules
_tmp = tempfile.mkdtemp(prefix="noba_test_")
_fake_home = os.path.join(_tmp, "home")
os.makedirs(_fake_home, exist_ok=True)
os.environ["HOME"] = _fake_home
os.environ["NOBA_CONFIG"] = os.path.join(_fake_home, ".config", "noba", "config.yaml")
os.environ["PID_FILE"] = os.path.join(_tmp, "noba.pid")

# Pre-create users.conf so UserStore doesn't generate a random password
import hashlib
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
import logging
logging.disable(logging.CRITICAL)
