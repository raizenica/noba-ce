"""Noba -- Heal executor: async action execution with condition verification."""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from .condition_eval import flatten_metrics, safe_eval
from .models import HealOutcome, HealPlan

logger = logging.getLogger("noba")

_DEFAULT_SETTLE_TIMES: dict[str, float] = {
    "restart_container": 15, "restart_service": 15,
    "scale_container": 15, "clear_cache": 15, "flush_dns": 15,
    "run_playbook": 120, "trigger_backup": 60,
    "run": 15, "webhook": 15, "automation": 15, "agent_command": 30,
    "failover_dns": 30,
}


def _get_fresh_metrics() -> dict:
    """Fetch current metrics from the background collector."""
    try:
        from ..collector import bg_collector
        return bg_collector.get() or {}
    except Exception:
        return {}


class HealExecutor:
    """Execute heal actions asynchronously with condition-based verification."""

    def __init__(self, settle_times: dict[str, float] | None = None) -> None:
        self._settle_times = settle_times or _DEFAULT_SETTLE_TIMES

    def execute(
        self, plan: HealPlan,
        on_complete: Callable[[HealOutcome], None],
    ) -> None:
        """Non-blocking: spawns a daemon thread to run action + verify."""
        threading.Thread(
            target=self._execute_and_verify,
            args=(plan, on_complete),
            daemon=True,
            name=f"heal-{plan.request.correlation_key}:{plan.escalation_step}",
        ).start()

    def _execute_and_verify(
        self, plan: HealPlan,
        on_complete: Callable[[HealOutcome], None],
    ) -> None:
        from ..remediation import execute_action

        start = time.time()
        metrics_before = {}
        if plan.request.events:
            metrics_before = plan.request.events[0].metrics

        try:
            result = execute_action(
                plan.action_type, plan.action_params,
                triggered_by=f"heal:{plan.request.correlation_key}",
                trigger_type="healing_pipeline",
            )
        except Exception as exc:
            logger.error("Heal executor action failed: %s", exc)
            outcome = HealOutcome(
                plan=plan, action_success=False, verified=False,
                verification_detail=f"Exception: {exc}",
                duration_s=round(time.time() - start, 2),
                metrics_before=metrics_before,
            )
            on_complete(outcome)
            return

        action_ok = result.get("success", False)

        if not action_ok:
            outcome = HealOutcome(
                plan=plan, action_success=False, verified=False,
                verification_detail=result.get("error", "Action failed"),
                duration_s=round(time.time() - start, 2),
                metrics_before=metrics_before,
            )
            on_complete(outcome)
            return

        # Wait settle time
        settle = self._settle_times.get(plan.action_type, 15)
        time.sleep(settle)

        # Verify: re-evaluate original conditions
        raw_metrics = _get_fresh_metrics()
        flat = flatten_metrics(raw_metrics)
        metrics_after = flat

        all_resolved = True
        details: list[str] = []
        for event in plan.request.events:
            still_firing = safe_eval(event.condition, flat)
            if still_firing:
                all_resolved = False
                details.append(f"{event.condition} still true")
            else:
                details.append(f"{event.condition} resolved")

        outcome = HealOutcome(
            plan=plan,
            action_success=True,
            verified=all_resolved,
            verification_detail="; ".join(details),
            duration_s=round(time.time() - start, 2),
            metrics_before=metrics_before,
            metrics_after=metrics_after,
        )
        on_complete(outcome)
