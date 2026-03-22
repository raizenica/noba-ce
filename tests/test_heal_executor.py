"""Tests for healing executor: async execution + condition verification."""
from __future__ import annotations

import threading
import time
from unittest.mock import patch


def _make_plan(action_type="restart_container", condition="cpu_percent > 90"):
    from server.healing.models import HealEvent, HealRequest, HealPlan
    event = HealEvent(
        source="alert", rule_id="r1", condition=condition,
        target="nginx", severity="warning",
        timestamp=time.time(), metrics={"cpu_percent": 95},
    )
    request = HealRequest(
        correlation_key="nginx", events=[event],
        primary_target="nginx", severity="warning",
        created_at=time.time(),
    )
    return HealPlan(
        request=request, action_type=action_type,
        action_params={"container": "nginx"},
        escalation_step=0, trust_level="execute",
    )


class TestExecutor:
    @patch("server.healing.executor._get_fresh_metrics")
    @patch("server.remediation.execute_action")
    def test_successful_heal(self, mock_exec, mock_metrics):
        from server.healing.executor import HealExecutor
        mock_exec.return_value = {"success": True, "output": "OK", "duration_s": 1.0}
        # After heal, cpu drops below threshold
        mock_metrics.return_value = {"cpu_percent": 40}

        results = []
        done = threading.Event()

        def on_complete(outcome):
            results.append(outcome)
            done.set()

        executor = HealExecutor(settle_times={"restart_container": 0.01})
        executor.execute(_make_plan(), on_complete)
        done.wait(timeout=5)

        assert len(results) == 1
        assert results[0].action_success is True
        assert results[0].verified is True

    @patch("server.healing.executor._get_fresh_metrics")
    @patch("server.remediation.execute_action")
    def test_unverified_heal(self, mock_exec, mock_metrics):
        from server.healing.executor import HealExecutor
        mock_exec.return_value = {"success": True, "output": "OK", "duration_s": 1.0}
        # After heal, cpu still above threshold
        mock_metrics.return_value = {"cpu_percent": 95}

        results = []
        done = threading.Event()

        def on_complete(outcome):
            results.append(outcome)
            done.set()

        executor = HealExecutor(settle_times={"restart_container": 0.01})
        executor.execute(_make_plan(), on_complete)
        done.wait(timeout=5)

        assert len(results) == 1
        assert results[0].action_success is True
        assert results[0].verified is False

    @patch("server.remediation.execute_action")
    def test_failed_action(self, mock_exec):
        from server.healing.executor import HealExecutor
        mock_exec.return_value = {"success": False, "error": "boom", "duration_s": 0.5}

        results = []
        done = threading.Event()

        def on_complete(outcome):
            results.append(outcome)
            done.set()

        executor = HealExecutor(settle_times={"restart_container": 0.01})
        executor.execute(_make_plan(), on_complete)
        done.wait(timeout=5)

        assert len(results) == 1
        assert results[0].action_success is False

    def test_execute_is_nonblocking(self):
        from server.healing.executor import HealExecutor
        executor = HealExecutor(settle_times={"restart_container": 10})
        start = time.time()
        with patch("server.remediation.execute_action", return_value={"success": True}):
            executor.execute(_make_plan(), lambda o: None)
        elapsed = time.time() - start
        assert elapsed < 1.0  # Must return immediately
