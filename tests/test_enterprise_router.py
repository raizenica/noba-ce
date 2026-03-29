from __future__ import annotations


def test_get_saml_requires_auth(client):
    r = client.get("/api/enterprise/saml")
    assert r.status_code in (401, 403)


def test_put_saml_requires_auth(client):
    r = client.put("/api/enterprise/saml", json={})
    assert r.status_code in (401, 403)


def test_post_saml_test_requires_auth(client):
    r = client.post("/api/enterprise/saml/test")
    assert r.status_code in (401, 403)


def test_get_scim_status_requires_auth(client):
    r = client.get("/api/enterprise/scim/status")
    assert r.status_code in (401, 403)


def test_get_webauthn_credentials_requires_auth(client):
    r = client.get("/api/enterprise/webauthn/credentials")
    assert r.status_code in (401, 403)


def test_delete_webauthn_credential_requires_auth(client):
    r = client.delete("/api/enterprise/webauthn/credentials/some-uuid")
    assert r.status_code in (401, 403)


def test_get_db_status_requires_auth(client):
    r = client.get("/api/enterprise/db/status")
    assert r.status_code in (401, 403)
