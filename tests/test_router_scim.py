"""Tests for SCIM 2.0 router."""
from __future__ import annotations

import pytest


class TestScimAuth:
    def test_no_token_rejected(self, client):
        resp = client.get("/api/scim/v2/Users")
        assert resp.status_code == 401

    def test_wrong_token_rejected(self, client):
        resp = client.get("/api/scim/v2/Users",
                          headers={"Authorization": "Bearer wrongtoken"})
        assert resp.status_code == 401


class TestScimDiscovery:
    @pytest.fixture(autouse=True)
    def setup_token(self, client, admin_headers):
        resp = client.post("/api/admin/scim-token", headers=admin_headers)
        assert resp.status_code == 200
        self.token = resp.json()["token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def test_service_provider_config(self, client):
        resp = client.get("/api/scim/v2/ServiceProviderConfig", headers=self.headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "schemas" in data

    def test_schemas_endpoint(self, client):
        resp = client.get("/api/scim/v2/Schemas", headers=self.headers)
        assert resp.status_code == 200

    def test_resource_types_endpoint(self, client):
        resp = client.get("/api/scim/v2/ResourceTypes", headers=self.headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["totalResults"] == 1


class TestScimUsers:
    @pytest.fixture(autouse=True)
    def setup_token(self, client, admin_headers):
        resp = client.post("/api/admin/scim-token", headers=admin_headers)
        self.token = resp.json()["token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def test_list_users_returns_list_response(self, client):
        resp = client.get("/api/scim/v2/Users", headers=self.headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["schemas"] == ["urn:ietf:params:scim:api:messages:2.0:ListResponse"]
        assert "totalResults" in data
        assert "Resources" in data

    def test_create_user(self, client):
        resp = client.post("/api/scim/v2/Users", headers=self.headers, json={
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "userName": "scim_testuser",
            "active": True,
            "roles": [{"value": "viewer"}],
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["userName"] == "scim_testuser"

    def test_create_duplicate_user_returns_409(self, client):
        client.post("/api/scim/v2/Users", headers=self.headers, json={
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "userName": "scim_dup",
            "active": True,
        })
        resp = client.post("/api/scim/v2/Users", headers=self.headers, json={
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "userName": "scim_dup",
            "active": True,
        })
        assert resp.status_code == 409

    def test_get_user(self, client):
        client.post("/api/scim/v2/Users", headers=self.headers, json={
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "userName": "scim_getme",
            "active": True,
        })
        resp = client.get("/api/scim/v2/Users/scim_getme", headers=self.headers)
        assert resp.status_code == 200
        assert resp.json()["userName"] == "scim_getme"

    def test_get_nonexistent_user_returns_404(self, client):
        resp = client.get("/api/scim/v2/Users/noone", headers=self.headers)
        assert resp.status_code == 404

    def test_patch_user_active_false(self, client):
        client.post("/api/scim/v2/Users", headers=self.headers, json={
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "userName": "scim_patch",
            "active": True,
        })
        resp = client.patch("/api/scim/v2/Users/scim_patch", headers=self.headers, json={
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "replace", "path": "active", "value": False}],
        })
        assert resp.status_code == 200

    def test_delete_user(self, client):
        client.post("/api/scim/v2/Users", headers=self.headers, json={
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "userName": "scim_del",
            "active": True,
        })
        resp = client.delete("/api/scim/v2/Users/scim_del", headers=self.headers)
        assert resp.status_code == 204

    def test_put_user_updates_role(self, client):
        client.post("/api/scim/v2/Users", headers=self.headers, json={
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "userName": "scim_put",
            "active": True,
            "roles": [{"value": "viewer"}],
        })
        resp = client.put("/api/scim/v2/Users/scim_put", headers=self.headers, json={
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "userName": "scim_put",
            "active": True,
            "roles": [{"value": "operator"}],
        })
        assert resp.status_code == 200
        assert resp.json()["roles"][0]["value"] == "operator"


class TestAdminScimToken:
    def test_generate_token_requires_admin(self, client, operator_headers):
        resp = client.post("/api/admin/scim-token", headers=operator_headers)
        assert resp.status_code == 403

    def test_generate_token_returns_plaintext(self, client, admin_headers):
        resp = client.post("/api/admin/scim-token", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "token" in data
        assert len(data["token"]) > 20
