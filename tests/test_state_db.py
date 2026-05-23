import tempfile
from datetime import date, timedelta, datetime, timezone

from snowglobe.state.db import StateDB


def _make_db():
    """Create a StateDB backed by a temp directory."""
    tmpdir = tempfile.mkdtemp()
    return StateDB(path=tmpdir)


class TestCostTrendSnapshots:
    def test_save_and_get_round_trip(self):
        db = _make_db()
        today = date.today().isoformat()
        yesterday = (date.today() - timedelta(days=1)).isoformat()

        db.save_cost_trend_snapshot([
            {"snapshot_date": yesterday, "total_credits": 100.5, "rolling_7d_avg": 95.3},
            {"snapshot_date": today, "total_credits": 110.2, "rolling_7d_avg": 98.1},
        ])

        cached = db.get_cost_trend_cache(30)
        assert cached is not None
        assert len(cached) == 2
        assert cached[0]["total_credits"] == 100.5
        assert cached[1]["total_credits"] == 110.2

    def test_filters_by_date_range(self):
        db = _make_db()
        old_date = (date.today() - timedelta(days=60)).isoformat()
        recent_date = date.today().isoformat()

        db.save_cost_trend_snapshot([
            {"snapshot_date": old_date, "total_credits": 50.0, "rolling_7d_avg": 50.0},
            {"snapshot_date": recent_date, "total_credits": 100.0, "rolling_7d_avg": 100.0},
        ])

        # Request only last 30 days — old_date should be excluded
        cached = db.get_cost_trend_cache(30)
        assert cached is not None
        assert len(cached) == 1
        assert cached[0]["total_credits"] == 100.0

    def test_returns_none_when_empty(self):
        db = _make_db()
        cached = db.get_cost_trend_cache(30)
        assert cached is None


class TestCostStorageSnapshots:
    def test_save_and_get_round_trip(self):
        db = _make_db()
        today = date.today().isoformat()

        db.save_cost_storage_snapshot(today, [
            {"DATABASE_NAME": "MY_DB", "ACTIVE_BYTES": 1e12, "FAILSAFE_BYTES": 5e10, "STAGE_BYTES": 0},
            {"DATABASE_NAME": "OTHER_DB", "ACTIVE_BYTES": 2e11, "FAILSAFE_BYTES": 0, "STAGE_BYTES": 1e9},
        ])

        cached = db.get_cost_storage_cache()
        assert cached is not None
        assert len(cached) == 2
        assert cached[0]["DATABASE_NAME"] == "MY_DB"
        assert cached[0]["ACTIVE_BYTES"] == 1e12

    def test_returns_none_for_different_date(self):
        db = _make_db()
        yesterday = (date.today() - timedelta(days=1)).isoformat()

        db.save_cost_storage_snapshot(yesterday, [
            {"DATABASE_NAME": "DB", "ACTIVE_BYTES": 1e12, "FAILSAFE_BYTES": 0, "STAGE_BYTES": 0},
        ])

        # get_cost_storage_cache only returns today's data
        cached = db.get_cost_storage_cache()
        assert cached is None


class TestJsonCache:
    def test_round_trip(self):
        db = _make_db()
        data = [{"SERVICE": "Cortex Agent", "TOTAL_CREDITS": 42.5, "PCT": 60.0}]

        db.set_json_cache("test_key", data)
        result = db.get_json_cache("test_key")
        assert result == data

    def test_returns_none_on_miss(self):
        db = _make_db()
        assert db.get_json_cache("nonexistent") is None

    def test_overwrites_existing(self):
        db = _make_db()
        db.set_json_cache("key", [{"a": 1}])
        db.set_json_cache("key", [{"b": 2}])
        result = db.get_json_cache("key")
        assert result == [{"b": 2}]


class TestCostCacheAge:
    def test_returns_age_after_marking(self):
        db = _make_db()
        db.set_metadata("test_cache_key", datetime.now(timezone.utc).isoformat())

        age = db.get_cost_cache_age("test_cache_key")
        assert age is not None
        assert age >= 0
        assert age < 5  # Should be less than 5 seconds

    def test_returns_none_when_unset(self):
        db = _make_db()
        age = db.get_cost_cache_age("never_set")
        assert age is None
