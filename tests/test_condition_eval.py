"""Tests for healing.condition_eval: safe_eval_single, safe_eval, flatten_metrics."""
from __future__ import annotations


from server.healing.condition_eval import flatten_metrics, safe_eval, safe_eval_single


class TestSafeEvalSingle:
    def test_greater_than_true(self):
        assert safe_eval_single("cpu_percent > 90", {"cpu_percent": 95.0}) is True

    def test_greater_than_false(self):
        assert safe_eval_single("cpu_percent > 90", {"cpu_percent": 80.0}) is False

    def test_less_than_true(self):
        assert safe_eval_single("cpu_temp < 70", {"cpu_temp": 50.0}) is True

    def test_less_than_false(self):
        assert safe_eval_single("cpu_temp < 70", {"cpu_temp": 80.0}) is False

    def test_missing_metric_returns_false(self):
        assert safe_eval_single("cpu_percent > 90", {}) is False

    def test_injection_attempt_returns_false(self):
        # Code injection in condition string should fail to parse and return False
        assert safe_eval_single("__import__('os').system('id') > 0", {}) is False

    def test_greater_equal(self):
        assert safe_eval_single("disk_percent >= 85", {"disk_percent": 85.0}) is True

    def test_less_equal(self):
        assert safe_eval_single("mem_percent <= 50", {"mem_percent": 50.0}) is True

    def test_equal(self):
        assert safe_eval_single("cpu_percent == 100", {"cpu_percent": 100.0}) is True

    def test_not_equal(self):
        assert safe_eval_single("cpu_percent != 50", {"cpu_percent": 75.0}) is True

    def test_flat_key_syntax_stripped(self):
        # Condition strings that include flat['key'] notation should still work
        assert safe_eval_single("flat['cpu_percent'] > 80", {"cpu_percent": 90.0}) is True


class TestSafeEval:
    def test_single_condition_true(self):
        assert safe_eval("cpu_percent > 80", {"cpu_percent": 90.0}) is True

    def test_single_condition_false(self):
        assert safe_eval("cpu_percent > 80", {"cpu_percent": 70.0}) is False

    def test_and_both_true(self):
        assert safe_eval(
            "cpu_percent > 80 AND mem_percent > 70",
            {"cpu_percent": 90.0, "mem_percent": 80.0},
        ) is True

    def test_and_one_false(self):
        assert safe_eval(
            "cpu_percent > 80 AND mem_percent > 70",
            {"cpu_percent": 90.0, "mem_percent": 50.0},
        ) is False

    def test_and_both_false(self):
        assert safe_eval(
            "cpu_percent > 80 AND mem_percent > 70",
            {"cpu_percent": 50.0, "mem_percent": 50.0},
        ) is False

    def test_or_one_true(self):
        assert safe_eval(
            "cpu_percent > 80 OR mem_percent > 70",
            {"cpu_percent": 50.0, "mem_percent": 80.0},
        ) is True

    def test_or_both_false(self):
        assert safe_eval(
            "cpu_percent > 80 OR mem_percent > 70",
            {"cpu_percent": 50.0, "mem_percent": 50.0},
        ) is False

    def test_or_both_true(self):
        assert safe_eval(
            "cpu_percent > 80 OR mem_percent > 70",
            {"cpu_percent": 90.0, "mem_percent": 80.0},
        ) is True


class TestFlattenMetrics:
    def test_scalar_values_preserved(self):
        stats = {"cpu_percent": 55.0, "mem_percent": 40, "hostname": "srv1"}
        flat = flatten_metrics(stats)
        assert flat["cpu_percent"] == 55.0
        assert flat["mem_percent"] == 40
        assert flat["hostname"] == "srv1"

    def test_nested_list_of_dicts(self):
        stats = {
            "disks": [
                {"name": "sda", "percent": 80.0},
                {"name": "sdb", "percent": 60.0},
            ]
        }
        flat = flatten_metrics(stats)
        assert flat["disks[0].percent"] == 80.0
        assert flat["disks[1].percent"] == 60.0

    def test_non_numeric_nested_values_skipped(self):
        stats = {
            "disks": [
                {"name": "sda", "percent": 80.0},
            ]
        }
        flat = flatten_metrics(stats)
        # "name" is a string, not numeric — should be excluded from flat
        assert "disks[0].name" not in flat
        assert "disks[0].percent" in flat

    def test_empty_stats(self):
        assert flatten_metrics({}) == {}

    def test_list_of_non_dicts_ignored(self):
        # A list that contains plain values (not dicts) should not be expanded
        stats = {"values": [1, 2, 3]}
        flat = flatten_metrics(stats)
        assert "values" not in flat
        assert "values[0]" not in flat
