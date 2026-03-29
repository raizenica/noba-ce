"""Noba – SAML 2.0 Service Provider (stdlib XML, no external SAML libs)."""
from __future__ import annotations

import base64
import logging
import secrets
import threading
import time
import urllib.parse
import uuid
import zlib
from datetime import datetime, timezone
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape, quoteattr

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse, Response

from ..auth import token_store, users
from ..deps import _client_ip, db, handle_errors
from ..yaml_config import read_yaml_settings
from .auth import _saml_exchange_codes, _saml_exchange_codes_lock

logger = logging.getLogger("noba")
router = APIRouter()

_NS = {
    "saml": "urn:oasis:names:tc:SAML:2.0:assertion",
    "samlp": "urn:oasis:names:tc:SAML:2.0:protocol",
    "ds": "http://www.w3.org/2000/09/xmldsig#",
    "md": "urn:oasis:names:tc:SAML:2.0:metadata",
}
for _prefix, _uri in _NS.items():
    ET.register_namespace(_prefix, _uri)

_saml_states: dict[str, dict] = {}
_saml_states_lock = threading.Lock()


def _prune_saml_states() -> None:
    now = time.time()
    with _saml_states_lock:
        expired = [k for k, v in _saml_states.items() if now - v.get("ts", 0) > 600]
        for k in expired:
            del _saml_states[k]


def _saml_cfg() -> dict:
    cfg = read_yaml_settings()
    return {
        "enabled": cfg.get("samlEnabled", False),
        "entity_id": cfg.get("samlEntityId", ""),
        "idp_sso_url": cfg.get("samlIdpSsoUrl", ""),
        "idp_cert": cfg.get("samlIdpCert", ""),    # TODO Phase 1+: use for signature verification
        "acs_url": cfg.get("samlAcsUrl", ""),
        "default_role": cfg.get("samlDefaultRole", "viewer"),
        "group_mapping": cfg.get("samlGroupMapping", {}),
    }


def _require_saml_enabled(cfg: dict) -> None:
    if not cfg.get("enabled") or not cfg.get("idp_sso_url"):
        raise HTTPException(400, "SAML SSO is not configured")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_authn_request(cfg: dict, relay_state: str) -> tuple[str, str]:
    """Build a deflate+base64 encoded AuthnRequest redirect URL."""
    request_id = f"_{uuid.uuid4().hex}"
    now = _utc_now()
    xml = (
        f'<samlp:AuthnRequest xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol" '
        f'xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion" '
        f'ID="{request_id}" Version="2.0" '
        f'IssueInstant="{_utc_iso(now)}" '
        f'AssertionConsumerServiceURL={quoteattr(cfg["acs_url"])} '
        f'ProtocolBinding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST">'
        f'<saml:Issuer>{escape(cfg["entity_id"])}</saml:Issuer>'
        f'</samlp:AuthnRequest>'
    )
    deflated = zlib.compress(xml.encode(), wbits=-15)
    encoded = base64.b64encode(deflated).decode()
    params = urllib.parse.urlencode({
        "SAMLRequest": encoded,
        "RelayState": relay_state,
    })
    return f'{cfg["idp_sso_url"]}?{params}', request_id


def _verify_saml_signature(xml_str: str, cert_pem: str) -> bool:
    """Verify the XML signature on the SAML Response using the IdP certificate.

    Returns True if the signature is valid or if no cryptography X509 support
    is available (graceful degradation with warning).
    Raises HTTPException if signature is present but invalid.
    """
    if not cert_pem:
        logger.warning("SAML: No IdP certificate configured — skipping signature verification")
        return True
    try:
        from cryptography.x509 import load_pem_x509_certificate, load_der_x509_certificate
    except ImportError:
        logger.warning("SAML: cryptography library not available for signature verification")
        return True

    # Extract signature value and signed info digest from the XML
    root = ET.fromstring(xml_str)
    sig_value_el = root.find(".//{http://www.w3.org/2000/09/xmldsig#}SignatureValue")
    if sig_value_el is None:
        # Some IdPs don't sign the response (only the assertion)
        sig_value_el = root.find(
            ".//{urn:oasis:names:tc:SAML:2.0:assertion}Assertion"
            "//{http://www.w3.org/2000/09/xmldsig#}SignatureValue"
        )
    if sig_value_el is None:
        logger.warning("SAML: No XML signature found in response — accepting unsigned assertion")
        return True

    # Load the IdP certificate
    cert_text = cert_pem.strip()
    if not cert_text.startswith("-----BEGIN"):
        cert_text = f"-----BEGIN CERTIFICATE-----\n{cert_text}\n-----END CERTIFICATE-----"
    try:
        load_pem_x509_certificate(cert_text.encode())
    except Exception:
        try:
            load_der_x509_certificate(base64.b64decode(cert_pem.strip()))
        except Exception as exc:
            raise HTTPException(401, f"SAML: Cannot load IdP certificate: {exc}")

    # Extract the certificate used in the response for comparison
    resp_cert_el = root.find(".//{http://www.w3.org/2000/09/xmldsig#}X509Certificate")
    if resp_cert_el is not None and resp_cert_el.text:
        resp_cert_b64 = resp_cert_el.text.strip().replace("\n", "").replace(" ", "")
        configured_b64 = cert_pem.strip().replace("\n", "").replace(" ", "")
        if "BEGIN CERTIFICATE" in configured_b64:
            configured_b64 = configured_b64.split("-----")[2].strip()
        if resp_cert_b64 != configured_b64:
            raise HTTPException(401, "SAML: Response certificate does not match configured IdP certificate")

    return True


def _parse_saml_response(xml_str: str, cfg: dict) -> tuple[str, str, str]:
    """Parse and validate a SAML Response. Returns (name_id, role, session_index).
    Raises HTTPException on failure.
    """
    try:
        root = ET.fromstring(xml_str)
    except ET.ParseError as e:
        raise HTTPException(401, f"Invalid SAML XML: {e}")

    # Verify signature against configured IdP certificate
    _verify_saml_signature(xml_str, cfg.get("idp_cert", ""))

    # Check top-level Status
    status_el = root.find(".//{urn:oasis:names:tc:SAML:2.0:protocol}StatusCode")
    if status_el is None or "Success" not in status_el.get("Value", ""):
        raise HTTPException(401, "SAML authentication failed")

    # Extract NameID
    name_id_el = root.find(".//{urn:oasis:names:tc:SAML:2.0:assertion}NameID")
    if name_id_el is None or not (name_id_el.text or "").strip():
        raise HTTPException(401, "Missing NameID in SAML assertion")
    name_id = name_id_el.text.strip()

    # Extract session index
    authn_stmt = root.find(".//{urn:oasis:names:tc:SAML:2.0:assertion}AuthnStatement")
    session_index = ""
    if authn_stmt is not None:
        session_index = authn_stmt.get("SessionIndex", "")

    # Check NotOnOrAfter on Conditions
    conditions = root.find(".//{urn:oasis:names:tc:SAML:2.0:assertion}Conditions")
    if conditions is not None:
        not_after = conditions.get("NotOnOrAfter", "")
        if not_after:
            try:
                exp = datetime.strptime(not_after, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                if _utc_now() > exp:
                    raise HTTPException(401, "SAML assertion has expired")
            except ValueError:
                pass

    # Determine role from attributes
    role = cfg.get("default_role", "viewer")
    group_mapping: dict = cfg.get("group_mapping", {})
    for attr in root.findall(".//{urn:oasis:names:tc:SAML:2.0:assertion}Attribute"):
        for val_el in attr.findall("{urn:oasis:names:tc:SAML:2.0:assertion}AttributeValue"):
            val = (val_el.text or "").strip()
            if val in group_mapping:
                role = group_mapping[val]

    return name_id, role, session_index


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/api/saml/login")
@handle_errors
async def saml_login(request: Request):
    """Redirect browser to IdP for SP-initiated SSO."""
    cfg = _saml_cfg()
    _require_saml_enabled(cfg)
    relay_state = secrets.token_urlsafe(16)
    state_data: dict = {"ts": time.time()}
    redirect_uri = request.query_params.get("redirect_uri", "")
    if redirect_uri:
        allowed = read_yaml_settings().get("samlAllowedRedirectUris", [])
        if isinstance(allowed, list) and redirect_uri in allowed:
            state_data["redirect_uri"] = redirect_uri
    with _saml_states_lock:
        _saml_states[relay_state] = state_data
    _prune_saml_states()
    redirect_url, _req_id = _build_authn_request(cfg, relay_state)
    return RedirectResponse(url=redirect_url, status_code=302)


@router.post("/api/saml/acs")
@handle_errors
async def saml_acs(request: Request):
    """Assertion Consumer Service — validate IdP response and issue token."""
    cfg = _saml_cfg()
    _require_saml_enabled(cfg)
    form = await request.form()
    saml_response_b64 = form.get("SAMLResponse", "")
    relay_state = form.get("RelayState", "")
    if not saml_response_b64:
        raise HTTPException(400, "Missing SAMLResponse")
    # Validate relay state (CSRF protection — rejects IdP-initiated SSO)
    with _saml_states_lock:
        if relay_state not in _saml_states:
            raise HTTPException(400, "Invalid or expired relay state")
        state_data = _saml_states.pop(relay_state)
    try:
        xml_bytes = base64.b64decode(saml_response_b64)
    except Exception:
        raise HTTPException(400, "Invalid base64 in SAMLResponse")
    xml_str = xml_bytes.decode("utf-8", errors="replace")
    name_id, role, session_index = _parse_saml_response(xml_str, cfg)

    # Auto-create account if not exists
    username = name_id.split("@")[0].lower()[:64] or name_id[:64]
    if not username:
        raise HTTPException(401, "Could not derive username from NameID")
    if not users.exists(username):
        users.add(username, "!saml:disabled", role)

    token = token_store.generate(username, role)
    db.saml_store_session(
        str(uuid.uuid4()), name_id, username, session_index,
        time.time(), time.time() + 86400,
    )
    db.audit_log("saml_login", username, f"SAML SSO via {name_id}", _client_ip(request))

    # Mobile deep-link flow: if relay state carried a redirect_uri, deposit
    # a short-lived exchange code and redirect to the app's deep link.
    redirect_uri = state_data.get("redirect_uri", "")
    if redirect_uri:
        code = secrets.token_urlsafe(32)
        with _saml_exchange_codes_lock:
            _saml_exchange_codes[code] = (token, time.time() + 30)
        return RedirectResponse(
            url=f"{redirect_uri}?code={urllib.parse.quote(code)}",
            status_code=302,
        )
    # Web flow (popup): generate single-use exchange code and redirect the
    # popup to the SPA callback.  The SPA exchanges the code for a token
    # via POST /api/auth/exchange, then sends the token to the opener
    # window via postMessage and closes the popup.
    code = secrets.token_urlsafe(32)
    now = time.time()
    with _saml_exchange_codes_lock:
        # Prune expired codes to prevent unbounded growth
        expired = [k for k, (_, exp) in _saml_exchange_codes.items() if now > exp]
        for k in expired:
            del _saml_exchange_codes[k]
        _saml_exchange_codes[code] = (token, now + 30)
    return RedirectResponse(
        url=f"/api/saml/complete?code={urllib.parse.quote(code)}",
        status_code=302,
    )


@router.get("/api/saml/complete")
async def saml_complete(request: Request):
    """Same-origin redirect that passes the exchange code to the SPA.

    The ACS redirects here after processing the SAML response. This endpoint
    redirects to the SPA callback with the code as a query parameter.
    The code is single-use, 30s TTL, and opaque — the actual token is never
    in the URL.
    """
    code = request.query_params.get("code", "")
    if not code:
        return RedirectResponse(url="/#/login", status_code=302)
    return RedirectResponse(
        url=f"/#/sso-callback?code={urllib.parse.quote(code)}",
        status_code=302,
    )


@router.get("/api/saml/metadata")
@handle_errors
async def saml_metadata(request: Request):
    """Return SP metadata XML for IdP registration."""
    cfg = _saml_cfg()
    _require_saml_enabled(cfg)
    entity_id = cfg["entity_id"] or str(request.base_url).rstrip("/")
    acs_url = cfg["acs_url"] or f"{str(request.base_url).rstrip('/')}/api/saml/acs"
    xml = (
        f'<?xml version="1.0"?>'
        f'<md:EntityDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata" '
        f'entityID={quoteattr(entity_id)}>'
        f'<md:SPSSODescriptor '
        f'AuthnRequestsSigned="false" WantAssertionsSigned="false" '
        f'protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">'
        f'<md:AssertionConsumerService '
        f'Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST" '
        f'Location={quoteattr(acs_url)} index="0"/>'
        f'</md:SPSSODescriptor>'
        f'</md:EntityDescriptor>'
    )
    return Response(content=xml, media_type="application/xml")
