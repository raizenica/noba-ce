#!/usr/bin/env python3
"""NOBA Enterprise — offline license issuance tool.

KEEP THIS SCRIPT AND YOUR PRIVATE KEY SECRET.
Never commit either to any repository.

Usage
-----
    # Interactive mode (recommended for single licenses):
    python3 scripts/issue_license.py

    # Non-interactive (for automation):
    python3 scripts/issue_license.py \\
        --private-key 5-KmsMgIJN27a7wp78yT81wtJT3irnvTAPQTgpKEEVI= \\
        --licensee "Acme Corp" \\
        --seats 25 \\
        --years 1 \\
        --out acme-corp.noba-license

Requirements
------------
    pip install cryptography
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path


# ── All enterprise features (keep in sync with license_manager.py) ────────────
ALL_FEATURES = [
    "saml", "scim", "webauthn", "branding",
    "multi_instance", "audit_export", "unlimited_seats",
]

PLAN_FEATURES = {
    "starter":    ["branding", "audit_export"],
    "pro":        ["branding", "audit_export", "saml", "webauthn", "unlimited_seats"],
    "enterprise": ALL_FEATURES,
}


def _sign(payload: dict, private_key_b64: str) -> str:
    """Sign *payload* with the Ed25519 private key and return base64url signature."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    priv_bytes = base64.urlsafe_b64decode(private_key_b64 + "==")
    priv_key = Ed25519PrivateKey.from_private_bytes(priv_bytes)

    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    sig_bytes = priv_key.sign(canonical.encode())
    return base64.urlsafe_b64encode(sig_bytes).decode().rstrip("=")


def issue(
    private_key_b64: str,
    licensee: str,
    plan: str,
    seats: int,
    years: float,
    license_id: str | None = None,
) -> dict:
    """Build and sign a license payload. Returns the complete license dict."""
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=365 * years)

    payload = {
        "license_id": license_id or str(uuid.uuid4()),
        "licensee":   licensee,
        "plan":       plan,
        "seats":      seats,
        "features":   PLAN_FEATURES.get(plan, ALL_FEATURES),
        "issued_at":  int(now.timestamp()),
        "expires_at": int(expires.timestamp()),
    }

    payload["signature"] = _sign(payload, private_key_b64)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Issue a NOBA Enterprise license")
    parser.add_argument("--private-key", help="Base64url Ed25519 private key")
    parser.add_argument("--licensee",    help="Customer / organization name")
    parser.add_argument("--plan",        choices=list(PLAN_FEATURES), default="enterprise",
                        help="License plan (default: enterprise)")
    parser.add_argument("--seats",       type=int, default=0,
                        help="Seat limit (0 = unlimited within plan)")
    parser.add_argument("--years",       type=float, default=1.0,
                        help="Support period in years (default: 1)")
    parser.add_argument("--out",         help="Output filename (default: <licensee>.noba-license)")
    args = parser.parse_args()

    # ── Collect missing values interactively ─────────────────────────────────
    private_key = args.private_key
    if not private_key:
        private_key = input("Private key (base64url): ").strip()
        if not private_key:
            print("ERROR: private key is required", file=sys.stderr)
            sys.exit(1)

    licensee = args.licensee
    if not licensee:
        licensee = input("Licensee name (e.g. 'Acme Corp'): ").strip()
        if not licensee:
            print("ERROR: licensee name is required", file=sys.stderr)
            sys.exit(1)

    plan = args.plan
    if not args.plan:
        plan_choices = "/".join(PLAN_FEATURES.keys())
        plan = input(f"Plan [{plan_choices}] (default: enterprise): ").strip() or "enterprise"

    seats_input = args.seats
    if seats_input == 0 and not args.private_key:  # only ask if interactive
        raw = input("Seat limit (0 = unlimited): ").strip()
        seats_input = int(raw) if raw.isdigit() else 0

    years = args.years
    if years == 1.0 and not args.private_key:
        raw = input("Support period in years (default: 1): ").strip()
        years = float(raw) if raw else 1.0

    # ── Build and sign ────────────────────────────────────────────────────────
    try:
        lic = issue(private_key, licensee, plan, seats_input, years)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    # ── Write output file ─────────────────────────────────────────────────────
    out_path = args.out or f"{licensee.lower().replace(' ', '-')}.noba-license"
    Path(out_path).write_text(json.dumps(lic, indent=2))

    expires_dt = datetime.fromtimestamp(lic["expires_at"], timezone.utc)
    print()
    print("=" * 56)
    print("  License issued successfully")
    print("=" * 56)
    print(f"  ID       : {lic['license_id']}")
    print(f"  Licensee : {lic['licensee']}")
    print(f"  Plan     : {lic['plan']}")
    print(f"  Seats    : {lic['seats'] or 'unlimited'}")
    print(f"  Expires  : {expires_dt.strftime('%Y-%m-%d')} (support period)")
    print(f"  Features : {', '.join(lic['features'])}")
    print(f"  Output   : {out_path}")
    print("=" * 56)
    print()
    print("Send the .noba-license file to the customer.")
    print("They upload it at: Settings → License")
    print()


if __name__ == "__main__":
    main()
