from unittest.mock import patch

class TestSamlDisabled:
    def test_login_when_disabled_returns_400(self, client):
        with patch("server.routers.saml._saml_cfg",
                   return_value={"enabled": False, "idp_sso_url": ""}):
            resp = client.get("/api/saml/login")
        assert resp.status_code == 400

    def test_metadata_when_disabled_returns_400(self, client):
        with patch("server.routers.saml._saml_cfg",
                   return_value={"enabled": False, "idp_sso_url": ""}):
            resp = client.get("/api/saml/metadata")
        assert resp.status_code == 400

    def test_acs_when_disabled_returns_400(self, client):
        with patch("server.routers.saml._saml_cfg",
                   return_value={"enabled": False, "idp_sso_url": ""}):
            resp = client.post("/api/saml/acs", data={"SAMLResponse": "x"})
        assert resp.status_code == 400

class TestSamlEnabled:
    _cfg = {
        "enabled": True,
        "idp_sso_url": "https://idp.example.com/sso",
        "entity_id": "https://noba.example.com",
        "acs_url": "https://noba.example.com/api/saml/acs",
        "idp_cert": "",
        "default_role": "viewer",
        "group_mapping": {},
    }

    def test_login_redirects_to_idp(self, client):
        with patch("server.routers.saml._saml_cfg", return_value=self._cfg):
            resp = client.get("/api/saml/login", follow_redirects=False)
        assert resp.status_code in (302, 307)
        assert "idp.example.com" in resp.headers["location"]

    def test_metadata_returns_xml(self, client):
        with patch("server.routers.saml._saml_cfg", return_value=self._cfg):
            resp = client.get("/api/saml/metadata")
        assert resp.status_code == 200
        assert "EntityDescriptor" in resp.text
        assert resp.headers["content-type"].startswith("application/xml")

    def test_acs_rejects_missing_response(self, client):
        with patch("server.routers.saml._saml_cfg", return_value=self._cfg):
            resp = client.post("/api/saml/acs", data={})
        assert resp.status_code == 400

    def test_acs_rejects_invalid_base64(self, client):
        from server.routers.saml import _saml_states, _saml_states_lock
        import time
        relay = "testrelaystate123"
        with _saml_states_lock:
            _saml_states[relay] = {"ts": time.time()}
        with patch("server.routers.saml._saml_cfg", return_value=self._cfg):
            resp = client.post("/api/saml/acs",
                               data={"SAMLResponse": "not-valid-base64!!", "RelayState": relay})
        assert resp.status_code in (400, 401)

    def test_acs_rejects_missing_relay_state(self, client):
        """ACS must reject requests without a relay state (IdP-initiated SSO)."""
        valid_b64 = __import__("base64").b64encode(b"<xml/>").decode()
        with patch("server.routers.saml._saml_cfg", return_value=self._cfg):
            resp = client.post("/api/saml/acs",
                               data={"SAMLResponse": valid_b64})
        assert resp.status_code == 400

    def test_acs_rejects_unknown_relay_state(self, client):
        """ACS must reject relay states that were never issued."""
        valid_b64 = __import__("base64").b64encode(b"<xml/>").decode()
        with patch("server.routers.saml._saml_cfg", return_value=self._cfg):
            resp = client.post("/api/saml/acs",
                               data={"SAMLResponse": valid_b64,
                                     "RelayState": "neverissued12345"})
        assert resp.status_code == 400

    def test_acs_rejects_replayed_relay_state(self, client):
        """Relay state can only be used once (consumed on first ACS post)."""
        import time
        from server.routers.saml import _saml_states, _saml_states_lock
        relay = "replayrelay123456"
        with _saml_states_lock:
            _saml_states[relay] = {"ts": time.time()}
        valid_b64 = __import__("base64").b64encode(b"<xml/>").decode()
        with patch("server.routers.saml._saml_cfg", return_value=self._cfg):
            # First use — relay state consumed
            client.post("/api/saml/acs",
                        data={"SAMLResponse": valid_b64, "RelayState": relay})
            # Second use — must be rejected
            resp = client.post("/api/saml/acs",
                               data={"SAMLResponse": valid_b64, "RelayState": relay})
        assert resp.status_code == 400

class TestSamlStatePruning:
    def test_prune_saml_states_removes_old(self):
        import time
        from server.routers.saml import _saml_states, _saml_states_lock, _prune_saml_states
        with _saml_states_lock:
            _saml_states["stale"] = {"ts": time.time() - 700}
            _saml_states["fresh"] = {"ts": time.time()}
        _prune_saml_states()
        with _saml_states_lock:
            assert "stale" not in _saml_states
            assert "fresh" in _saml_states
            _saml_states.pop("fresh", None)
