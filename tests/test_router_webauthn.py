
class TestWebAuthnRegister:
    def test_register_begin_requires_auth(self, client):
        resp = client.post("/api/webauthn/register/begin")
        assert resp.status_code == 401

    def test_register_begin_returns_options(self, client, admin_headers):
        resp = client.post("/api/webauthn/register/begin", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "challenge" in data
        assert "rp" in data
        assert "user" in data

    def test_register_complete_requires_auth(self, client):
        resp = client.post("/api/webauthn/register/complete", json={})
        assert resp.status_code == 401

class TestWebAuthnLogin:
    def test_login_begin_requires_username(self, client):
        resp = client.post("/api/webauthn/login/begin", json={})
        assert resp.status_code == 400

    def test_login_begin_unknown_user(self, client):
        resp = client.post("/api/webauthn/login/begin", json={"username": "noexist"})
        assert resp.status_code == 404

    def test_login_begin_no_credentials(self, client, admin_headers):
        resp = client.post("/api/webauthn/login/begin", json={"username": "admin"})
        assert resp.status_code == 404  # no credentials registered

class TestBackupCodes:
    def test_generate_requires_auth(self, client):
        resp = client.post("/api/webauthn/backup-codes/generate")
        assert resp.status_code == 401

    def test_generate_returns_10_codes(self, client, admin_headers):
        resp = client.post("/api/webauthn/backup-codes/generate", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["codes"]) == 10

    def test_verify_invalid_code(self, client):
        resp = client.post("/api/webauthn/backup-codes/verify",
                           json={"username": "admin", "code": "BADCODE1"})
        assert resp.status_code == 401

    def test_verify_valid_code_issues_token(self, client, admin_headers):
        gen = client.post("/api/webauthn/backup-codes/generate", headers=admin_headers)
        code = gen.json()["codes"][0]
        resp = client.post("/api/webauthn/backup-codes/verify",
                           json={"username": "admin", "code": code})
        assert resp.status_code == 200
        assert "token" in resp.json()

    def test_code_can_only_be_used_once(self, client, admin_headers):
        gen = client.post("/api/webauthn/backup-codes/generate", headers=admin_headers)
        code = gen.json()["codes"][0]
        client.post("/api/webauthn/backup-codes/verify",
                    json={"username": "admin", "code": code})
        resp = client.post("/api/webauthn/backup-codes/verify",
                           json={"username": "admin", "code": code})
        assert resp.status_code == 401

class TestWebAuthnCredentials:
    def test_list_requires_auth(self, client):
        resp = client.get("/api/webauthn/credentials")
        assert resp.status_code == 401

    def test_list_empty_initially(self, client, admin_headers):
        resp = client.get("/api/webauthn/credentials", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["credentials"] == []


class TestWebAuthnSecurity:
    def test_register_begin_challenge_is_unique(self, client, admin_headers):
        r1 = client.post("/api/webauthn/register/begin", headers=admin_headers)
        r2 = client.post("/api/webauthn/register/begin", headers=admin_headers)
        assert r1.json()["challenge"] != r2.json()["challenge"]

    def test_login_begin_returns_credentials_list(self, client, admin_headers):
        # Can't test full flow without real hardware, but verify structure
        # First register a fake credential via DB directly
        from server.deps import db
        fake_cred_id = b"fakecredid123456"
        db.webauthn_store_credential("admin", fake_cred_id, b"fakepem", 0)
        resp = client.post("/api/webauthn/login/begin", json={"username": "admin"})
        assert resp.status_code == 200
        data = resp.json()
        assert "challenge" in data
        assert "allowCredentials" in data
        assert len(data["allowCredentials"]) == 1
        # Cleanup
        db.webauthn_delete_credential(fake_cred_id)

    def test_backup_codes_second_generation_invalidates_first(self, client, admin_headers):
        """HTTP-level test: generating new codes must invalidate previous batch."""
        gen1 = client.post("/api/webauthn/backup-codes/generate", headers=admin_headers)
        old_code = gen1.json()["codes"][0]
        # Generate again — replaces all codes
        client.post("/api/webauthn/backup-codes/generate", headers=admin_headers)
        # Old code must now be invalid
        resp = client.post("/api/webauthn/backup-codes/verify",
                           json={"username": "admin", "code": old_code})
        assert resp.status_code == 401

    def test_backup_codes_verify_missing_username(self, client):
        resp = client.post("/api/webauthn/backup-codes/verify",
                           json={"code": "ABCD1234"})
        assert resp.status_code == 400

    def test_delete_credential_not_found(self, client, admin_headers):
        resp = client.delete("/api/webauthn/credentials/dW5rbm93bg", headers=admin_headers)
        assert resp.status_code == 404

    def test_list_credentials_returns_registered(self, client, admin_headers):
        from server.deps import db
        fake_cred_id = b"testcredlist12345"
        db.webauthn_store_credential("admin", fake_cred_id, b"fakepem", 0, "My Key")
        resp = client.get("/api/webauthn/credentials", headers=admin_headers)
        assert resp.status_code == 200
        creds = resp.json()["credentials"]
        assert len(creds) == 1
        assert creds[0]["name"] == "My Key"
        # Cleanup
        db.webauthn_delete_credential(fake_cred_id)
