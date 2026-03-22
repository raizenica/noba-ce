"""Tests for healing trust governor: promotion, demotion, effective trust."""
from __future__ import annotations



class TestEffectiveTrust:
    def _db(self):
        from server.db.core import Database
        db = Database(":memory:")
        db.init()
        return db

    def test_no_state_returns_notify(self):
        from server.healing.governor import effective_trust
        db = self._db()
        assert effective_trust("rule1", "alert", db) == "notify"

    def test_returns_stored_level(self):
        from server.healing.governor import effective_trust
        db = self._db()
        db.upsert_trust_state("rule1", "approve", "execute")
        assert effective_trust("rule1", "alert", db) == "approve"

    def test_prediction_source_caps_one_below(self):
        from server.healing.governor import effective_trust
        db = self._db()
        db.upsert_trust_state("rule1", "execute", "execute")
        assert effective_trust("rule1", "prediction", db) == "approve"

    def test_prediction_at_notify_stays_notify(self):
        from server.healing.governor import effective_trust
        db = self._db()
        db.upsert_trust_state("rule1", "notify", "execute")
        assert effective_trust("rule1", "prediction", db) == "notify"


class TestCircuitBreaker:
    def _db(self):
        from server.db.core import Database
        db = Database(":memory:")
        db.init()
        return db

    def test_three_failures_demotes(self):
        from server.healing.governor import check_circuit_breaker
        db = self._db()
        db.upsert_trust_state("rule1", "execute", "execute")
        for _ in range(3):
            db.insert_heal_outcome(
                correlation_key="test", rule_id="rule1",
                condition="cpu > 90", target="nginx",
                action_type="restart_container",
                action_success=True, verified=False,
                duration_s=1.0, metrics_before={"cpu": 95},
                trust_level="execute",
                source="alert",
            )
        tripped = check_circuit_breaker("rule1", db)
        assert tripped is True
        state = db.get_trust_state("rule1")
        assert state["current_level"] == "notify"
