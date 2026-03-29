"""Tests for db.login_restrict: tenant-scoped login IP allowlists."""
from __future__ import annotations

import sqlite3
import threading

import pytest

from server.db.login_restrict import (
    add_allowed_cidr,
    delete_allowed_cidr,
    init_schema,
    is_ip_allowed,
    list_allowed_cidrs,
)


@pytest.fixture()
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    lock = threading.Lock()
    init_schema(conn)
    return conn, lock


class TestNoRulesAllowsAll:
    def test_any_ip_allowed_when_no_rules(self, db):
        conn, lock = db
        assert is_ip_allowed(conn, lock, "default", "192.168.1.1") is True

    def test_any_ip_allowed_different_tenant(self, db):
        conn, lock = db
        assert is_ip_allowed(conn, lock, "tenant-x", "10.0.0.1") is True


class TestAddAndList:
    def test_add_returns_id(self, db):
        conn, lock = db
        rid = add_allowed_cidr(conn, lock, "default", "10.0.0.0/24", "Office")
        assert isinstance(rid, int)
        assert rid > 0

    def test_list_returns_added_rules(self, db):
        conn, lock = db
        add_allowed_cidr(conn, lock, "default", "10.0.0.0/24", "Office")
        add_allowed_cidr(conn, lock, "default", "172.16.0.0/16", "VPN")
        rules = list_allowed_cidrs(conn, lock, "default")
        assert len(rules) == 2
        assert rules[0]["cidr"] == "10.0.0.0/24"
        assert rules[0]["label"] == "Office"
        assert rules[1]["cidr"] == "172.16.0.0/16"

    def test_invalid_cidr_raises(self, db):
        conn, lock = db
        with pytest.raises(ValueError):
            add_allowed_cidr(conn, lock, "default", "not-a-cidr", "Bad")


class TestIpInCidrAllowed:
    def test_ip_within_range(self, db):
        conn, lock = db
        add_allowed_cidr(conn, lock, "default", "10.0.0.0/24")
        assert is_ip_allowed(conn, lock, "default", "10.0.0.42") is True

    def test_ip_at_network_boundary(self, db):
        conn, lock = db
        add_allowed_cidr(conn, lock, "default", "10.0.0.0/24")
        assert is_ip_allowed(conn, lock, "default", "10.0.0.0") is True
        assert is_ip_allowed(conn, lock, "default", "10.0.0.255") is True


class TestIpOutsideCidrBlocked:
    def test_ip_outside_range(self, db):
        conn, lock = db
        add_allowed_cidr(conn, lock, "default", "10.0.0.0/24")
        assert is_ip_allowed(conn, lock, "default", "10.0.1.1") is False

    def test_completely_different_subnet(self, db):
        conn, lock = db
        add_allowed_cidr(conn, lock, "default", "10.0.0.0/24")
        assert is_ip_allowed(conn, lock, "default", "192.168.1.1") is False


class TestMultipleCidrs:
    def test_ip_matches_any_rule(self, db):
        conn, lock = db
        add_allowed_cidr(conn, lock, "default", "10.0.0.0/24")
        add_allowed_cidr(conn, lock, "default", "192.168.1.0/24")
        assert is_ip_allowed(conn, lock, "default", "10.0.0.5") is True
        assert is_ip_allowed(conn, lock, "default", "192.168.1.100") is True
        assert is_ip_allowed(conn, lock, "default", "172.16.0.1") is False


class TestSingleIpCidr:
    def test_slash_32_exact_match(self, db):
        conn, lock = db
        add_allowed_cidr(conn, lock, "default", "10.0.0.42/32")
        assert is_ip_allowed(conn, lock, "default", "10.0.0.42") is True
        assert is_ip_allowed(conn, lock, "default", "10.0.0.43") is False


class TestDeleteCidr:
    def test_delete_reverts_to_allow_all(self, db):
        conn, lock = db
        rid = add_allowed_cidr(conn, lock, "default", "10.0.0.0/24")
        # With rule: outside IP blocked
        assert is_ip_allowed(conn, lock, "default", "192.168.1.1") is False
        # Delete the rule
        delete_allowed_cidr(conn, lock, rid)
        # No rules left → allow all
        assert is_ip_allowed(conn, lock, "default", "192.168.1.1") is True

    def test_delete_one_of_many(self, db):
        conn, lock = db
        r1 = add_allowed_cidr(conn, lock, "default", "10.0.0.0/24")
        add_allowed_cidr(conn, lock, "default", "192.168.1.0/24")
        delete_allowed_cidr(conn, lock, r1)
        # 10.x no longer allowed, 192.168.1.x still is
        assert is_ip_allowed(conn, lock, "default", "10.0.0.5") is False
        assert is_ip_allowed(conn, lock, "default", "192.168.1.5") is True


class TestTenantIsolation:
    def test_rules_scoped_to_tenant(self, db):
        conn, lock = db
        add_allowed_cidr(conn, lock, "t1", "10.0.0.0/24")
        add_allowed_cidr(conn, lock, "t2", "192.168.1.0/24")
        # t1 allows 10.x only
        assert is_ip_allowed(conn, lock, "t1", "10.0.0.1") is True
        assert is_ip_allowed(conn, lock, "t1", "192.168.1.1") is False
        # t2 allows 192.168.1.x only
        assert is_ip_allowed(conn, lock, "t2", "192.168.1.1") is True
        assert is_ip_allowed(conn, lock, "t2", "10.0.0.1") is False

    def test_list_scoped_to_tenant(self, db):
        conn, lock = db
        add_allowed_cidr(conn, lock, "t1", "10.0.0.0/24")
        add_allowed_cidr(conn, lock, "t2", "192.168.1.0/24")
        assert len(list_allowed_cidrs(conn, lock, "t1")) == 1
        assert len(list_allowed_cidrs(conn, lock, "t2")) == 1

    def test_tenant_without_rules_open(self, db):
        conn, lock = db
        add_allowed_cidr(conn, lock, "t1", "10.0.0.0/24")
        # t2 has no rules → open
        assert is_ip_allowed(conn, lock, "t2", "1.2.3.4") is True
