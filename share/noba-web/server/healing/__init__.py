"""Noba -- Self-healing pipeline."""
from __future__ import annotations

import logging
import threading

from .correlation import HealCorrelator
from .executor import HealExecutor
from .governor import check_circuit_breaker, effective_trust
from .models import HealEvent, HealOutcome, HealPlan
from .planner import HealPlanner

logger = logging.getLogger("noba")


def dispatch_notifications(
    severity: str, message: str,
    notif_cfg: dict | None = None, channels: list | None = None,
) -> None:
    """Dispatch notifications via the alerts module."""
    try:
        from ..alerts import dispatch_notifications as _dispatch
        from ..yaml_config import read_yaml_settings
        cfg = read_yaml_settings()
        nc = notif_cfg or cfg.get("notifications", {})
        _dispatch(severity, message, nc, channels)
    except Exception as exc:
        logger.error("Heal notification failed: %s", exc)


class HealPipeline:
    """Main pipeline orchestrator. Non-blocking, thread-safe."""

    def __init__(self, db, rules_cfg: dict, settle_times: dict | None = None) -> None:
        self._db = db
        self._rules_cfg = rules_cfg  # {rule_id: {escalation_chain: [...]}}
        self._correlator = HealCorrelator()
        self._planner = HealPlanner()
        self._executor = HealExecutor(settle_times=settle_times)
        self.on_outcome = None  # optional callback for testing

    def update_rule_config(self, rule_id: str, config: dict) -> None:
        """Update or add a rule's config (thread-safe)."""
        self._rules_cfg[rule_id] = config

    def handle_heal_event(self, event: HealEvent) -> None:
        """Non-blocking pipeline entry point. Safe to call from any thread."""
        request = self._correlator.correlate(event)
        if request is None:
            return  # absorbed

        rule_cfg = self._rules_cfg.get(event.rule_id, {})
        chain = rule_cfg.get("escalation_chain", [
            {"action": "restart_container", "params": {}, "verify_timeout": 30},
        ])

        trust = effective_trust(event.rule_id, event.source, self._db)

        # Check circuit breaker
        if check_circuit_breaker(event.rule_id, self._db):
            trust = "notify"

        plan = self._planner.select_action(request, chain, self._db, effective_trust=trust)
        if plan is None:
            return  # escalation in progress or chain exhausted

        if plan.trust_level == "notify":
            self._handle_notify(plan, event)
        elif plan.trust_level == "approve":
            self._handle_approve(plan, event)
        else:
            self._handle_execute(plan, chain)

    def _handle_notify(self, plan: HealPlan, event: HealEvent) -> None:
        from . import ledger
        outcome = HealOutcome(
            plan=plan, action_success=None, verified=None,
            verification_detail="notify only", duration_s=0,
            metrics_before=event.metrics,
        )
        ledger.record(outcome, self._db)
        dispatch_notifications(plan.request.severity, plan.reason)
        if self.on_outcome:
            self.on_outcome(outcome)
        self._planner.clear_escalation(plan.request.correlation_key)

    def _handle_approve(self, plan: HealPlan, event: HealEvent) -> None:
        from . import ledger
        approval_id = None
        try:
            approval_id = self._db.insert_approval(
                automation_id=event.rule_id,
                trigger=f"heal:{plan.request.correlation_key}",
                trigger_source="healing_pipeline",
                action_type=plan.action_type,
                action_params=plan.action_params,
                target=plan.request.primary_target,
                requested_by=f"heal:{event.source}",
            )
        except Exception as exc:
            logger.error("Heal approval insert failed: %s", exc)

        outcome = HealOutcome(
            plan=plan, action_success=None, verified=None,
            verification_detail="queued for approval", duration_s=0,
            metrics_before=event.metrics, approval_id=approval_id,
        )
        ledger.record(outcome, self._db)
        dispatch_notifications(
            plan.request.severity,
            f"[APPROVAL NEEDED] {plan.reason}",
        )
        if self.on_outcome:
            self.on_outcome(outcome)
        self._planner.clear_escalation(plan.request.correlation_key)

    def _handle_execute(self, plan: HealPlan, chain: list[dict]) -> None:
        from . import ledger

        def on_complete(outcome: HealOutcome) -> None:
            ledger.record(outcome, self._db)
            if self.on_outcome:
                self.on_outcome(outcome)

            if outcome.verified:
                self._planner.clear_escalation(plan.request.correlation_key)
                return

            # Escalation
            trust = effective_trust(
                plan.request.events[0].rule_id if plan.request.events else "",
                plan.request.events[0].source if plan.request.events else "alert",
                self._db,
            )
            next_plan = self._planner.advance(outcome, chain, self._db, effective_trust=trust)
            if next_plan:
                self._executor.execute(next_plan, on_complete=on_complete)

        self._executor.execute(plan, on_complete=on_complete)


_singleton: HealPipeline | None = None
_singleton_lock = threading.Lock()


def create_pipeline(db, rules_cfg: dict, settle_times: dict | None = None) -> HealPipeline:
    """Factory function for creating a pipeline instance (used in tests)."""
    return HealPipeline(db, rules_cfg, settle_times=settle_times)


def get_pipeline() -> HealPipeline:
    """Get or create the module-level singleton pipeline.

    Uses the shared DB instance from deps. Correlation and escalation state
    persist across calls — this is critical for correct behavior.
    """
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                from ..db import db as _db
                _singleton = HealPipeline(_db, {})
    return _singleton
