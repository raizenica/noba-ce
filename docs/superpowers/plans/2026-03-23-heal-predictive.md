# Self-Healing Predictive Implementation Plan (Phase 4 of 6)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the prediction engine, anomaly detection, and health score into the healing pipeline for proactive healing. Conservative approach: predictions only trigger low-risk actions, anomalies get the same treatment, health score degradation triggers suggestions and lightweight cleanup.

**Architecture:** New `server/healing/predictive.py` module evaluates predictions and anomalies on a 15-minute scheduler cycle. Emits `HealEvent(source="prediction"|"anomaly")` into the existing pipeline. Stale data protection prevents phantom heals. Health score integration adds category-specific thresholds that trigger heal suggestions.

**Tech Stack:** Python 3.11+, SQLite WAL, threading, pytest

**Spec:** `docs/superpowers/specs/2026-03-22-full-self-healing-design.md` (Section 6)

**Predecessor:** Phase 3 (`feature/heal-controls`) — approvals, maintenance, rollback

---

## File Map

### New files
| File | Responsibility |
|------|---------------|
| `server/healing/predictive.py` | Prediction evaluator, anomaly wiring, stale data guard, health score triggers |
| `tests/test_predictive.py` | Tests for prediction evaluation, anomaly events, stale guard, health triggers |

### Modified files
| File | Change |
|------|--------|
| `server/scheduler.py` | Add 15-minute predictive evaluation cycle |
| `server/healing/__init__.py` | Accept source="prediction" and source="anomaly" events with conservative trust cap |

---

## Task 1: Predictive Evaluation Module

**Files:**
- Create: `share/noba-web/server/healing/predictive.py`
- Create: `tests/test_predictive.py`

## Task 2: Stale Data Protection

Built into the predictive module — guard against phantom heals from stale collector data.

## Task 3: Wire Predictions into Scheduler

Add 15-minute evaluation cycle to scheduler.py.

## Task 4: Conservative Trust Cap for Predictive Events

Ensure prediction-sourced events are trust-capped one level below the rule's current trust.

## Task 5: Health Score Integration

Health score category thresholds trigger lightweight heal actions.

## Task 6: Notification Enrichment

Enriched heal notifications with full context (trigger, evidence, action, result, rollback status).

## Task 7: Lint + Final Integration
