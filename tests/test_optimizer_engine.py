from snowglobe.engines.optimizer.query_optimizer import QueryOptimizerEngine
from snowglobe.models.query import QueryProfile


def _op(operator_type="TableScan", operator_id=1, step_id=1, parent_operators=None,
         input_rows=0, output_rows=0, bytes_scanned=0, network_bytes=0,
         spill_local=0, spill_remote=0, partitions_scanned=0, partitions_total=0,
         overall_percentage=0):
    """Helper to build a QueryProfile with common defaults."""
    stats = {
        "input_rows": input_rows,
        "output_rows": output_rows,
        "io": {"bytes_scanned": bytes_scanned},
        "network": {"network_bytes": network_bytes},
        "bytes_spilled_local_storage": spill_local,
        "bytes_spilled_remote_storage": spill_remote,
    }
    attrs = {}
    if partitions_scanned or partitions_total:
        attrs["partitions_scanned"] = partitions_scanned
        attrs["partitions_total"] = partitions_total

    time_breakdown = {"overall_percentage": overall_percentage} if overall_percentage else {}

    return QueryProfile(
        query_id="test-id",
        step_id=step_id,
        operator_id=operator_id,
        parent_operators=parent_operators or [],
        operator_type=operator_type,
        operator_statistics=stats,
        execution_time_breakdown=time_breakdown,
        operator_attributes=attrs,
    )


class TestJoinExplosion:
    def test_detects_explosion(self):
        op = _op("InnerJoin", input_rows=1000, output_rows=50000)
        engine = QueryOptimizerEngine([op])
        suggestions = engine.detect_join_explosion([op])
        assert len(suggestions) == 1
        assert "Join explosion" in suggestions[0]

    def test_no_explosion_when_ratio_normal(self):
        op = _op("InnerJoin", input_rows=1000, output_rows=2000)
        engine = QueryOptimizerEngine([op])
        suggestions = engine.detect_join_explosion([op])
        assert len(suggestions) == 0


class TestDiskSpill:
    def test_detects_remote_spill(self):
        op = _op(spill_remote=5_000_000_000)
        engine = QueryOptimizerEngine([op])
        suggestions = engine.detect_disk_spill([op])
        assert len(suggestions) == 1
        assert "Remote disk spill" in suggestions[0]

    def test_detects_local_spill(self):
        op = _op(spill_local=2_000_000_000)
        engine = QueryOptimizerEngine([op])
        suggestions = engine.detect_disk_spill([op])
        assert len(suggestions) == 1
        assert "Local disk spill" in suggestions[0]

    def test_no_spill_when_zero(self):
        op = _op()
        engine = QueryOptimizerEngine([op])
        suggestions = engine.detect_disk_spill([op])
        assert len(suggestions) == 0


class TestPruningFailure:
    def test_detects_poor_pruning(self):
        op = _op(partitions_scanned=950, partitions_total=1000)
        engine = QueryOptimizerEngine([op])
        suggestions = engine.detect_pruning_failure([op])
        assert len(suggestions) == 1
        assert "pruning" in suggestions[0].lower()

    def test_no_issue_with_good_pruning(self):
        op = _op(partitions_scanned=10, partitions_total=1000)
        engine = QueryOptimizerEngine([op])
        suggestions = engine.detect_pruning_failure([op])
        assert len(suggestions) == 0


class TestCartesianJoin:
    def test_detects_cartesian(self):
        op = _op("CartesianJoin")
        engine = QueryOptimizerEngine([op])
        suggestions = engine.detect_cartesian_join([op])
        assert len(suggestions) == 1
        assert "Cartesian" in suggestions[0]


class TestLargeScan:
    def test_detects_large_scan(self):
        op = _op(bytes_scanned=5_000_000_000)
        engine = QueryOptimizerEngine([op])
        suggestions = engine.detect_large_scan([op])
        assert len(suggestions) == 1
        assert "5.0 GB" in suggestions[0]

    def test_no_alert_for_small_scan(self):
        op = _op(bytes_scanned=100_000_000)
        engine = QueryOptimizerEngine([op])
        suggestions = engine.detect_large_scan([op])
        assert len(suggestions) == 0


class TestLargeWindow:
    def test_detects_large_window(self):
        op = _op("WindowFunction", input_rows=200_000_000)
        engine = QueryOptimizerEngine([op])
        suggestions = engine.detect_large_window([op])
        assert len(suggestions) == 1

    def test_no_alert_for_small_window(self):
        op = _op("WindowFunction", input_rows=1_000_000)
        engine = QueryOptimizerEngine([op])
        suggestions = engine.detect_large_window([op])
        assert len(suggestions) == 0


class TestLargeAggregation:
    def test_detects_large_agg(self):
        op = _op("Aggregate", input_rows=500_000_000)
        engine = QueryOptimizerEngine([op])
        suggestions = engine.detect_large_aggregation([op])
        assert len(suggestions) == 1

    def test_no_alert_for_small_agg(self):
        op = _op("Aggregate", input_rows=50_000)
        engine = QueryOptimizerEngine([op])
        suggestions = engine.detect_large_aggregation([op])
        assert len(suggestions) == 0


class TestHeavyNetwork:
    def test_detects_heavy_network(self):
        op = _op(network_bytes=3_000_000_000)
        engine = QueryOptimizerEngine([op])
        suggestions = engine.detect_heavy_network([op])
        assert len(suggestions) == 1

    def test_no_alert_for_light_network(self):
        op = _op(network_bytes=100_000)
        engine = QueryOptimizerEngine([op])
        suggestions = engine.detect_heavy_network([op])
        assert len(suggestions) == 0


class TestFilterAfterJoin:
    def test_detects_filter_after_join(self):
        join_op = _op("InnerJoin", operator_id=1, input_rows=500_000, output_rows=2_000_000)
        filter_op = _op("Filter", operator_id=2, parent_operators=[1],
                        input_rows=2_000_000, output_rows=100_000)
        engine = QueryOptimizerEngine([join_op, filter_op])
        suggestions = engine.detect_filter_after_join([join_op, filter_op])
        assert len(suggestions) == 1
        assert "after join" in suggestions[0].lower()

    def test_no_alert_when_filter_keeps_most_rows(self):
        join_op = _op("InnerJoin", operator_id=1, input_rows=1000, output_rows=1000)
        filter_op = _op("Filter", operator_id=2, parent_operators=[1],
                        input_rows=1000, output_rows=900)
        engine = QueryOptimizerEngine([join_op, filter_op])
        suggestions = engine.detect_filter_after_join([join_op, filter_op])
        assert len(suggestions) == 0


class TestSkewDetection:
    def test_detects_skew(self):
        ops = [
            _op("Result", operator_id=0, overall_percentage=5),
            _op("Sort", operator_id=1, overall_percentage=75),
            _op("TableScan", operator_id=2, overall_percentage=20),
        ]
        engine = QueryOptimizerEngine(ops)
        suggestions = engine.detect_skew(ops)
        assert len(suggestions) == 1
        assert "75%" in suggestions[0]

    def test_no_skew_when_balanced(self):
        ops = [
            _op("Result", operator_id=0, overall_percentage=30),
            _op("Sort", operator_id=1, overall_percentage=35),
            _op("TableScan", operator_id=2, overall_percentage=35),
        ]
        engine = QueryOptimizerEngine(ops)
        suggestions = engine.detect_skew(ops)
        assert len(suggestions) == 0


class TestSortWithoutLimit:
    def test_detects_sort_without_limit(self):
        sort_op = _op("Sort", operator_id=1, input_rows=50_000_000)
        engine = QueryOptimizerEngine([sort_op])
        suggestions = engine.detect_sort_without_limit([sort_op])
        assert len(suggestions) == 1
        assert "no LIMIT" in suggestions[0]

    def test_no_alert_when_limit_exists(self):
        sort_op = _op("Sort", operator_id=1, input_rows=50_000_000)
        limit_op = _op("Limit", operator_id=2, parent_operators=[1])
        engine = QueryOptimizerEngine([sort_op, limit_op])
        suggestions = engine.detect_sort_without_limit([sort_op, limit_op])
        assert len(suggestions) == 0

    def test_no_alert_for_small_sort(self):
        sort_op = _op("Sort", operator_id=1, input_rows=1000)
        engine = QueryOptimizerEngine([sort_op])
        suggestions = engine.detect_sort_without_limit([sort_op])
        assert len(suggestions) == 0


class TestScoring:
    def test_uses_time_pct_when_available(self):
        op = _op(overall_percentage=45, bytes_scanned=10_000_000_000)
        engine = QueryOptimizerEngine([op])
        scores = engine.build_score_map()
        score_info = scores[(1, 1)]
        # Should use time_pct (45) not heuristic (which would be much higher due to 10GB scan)
        assert score_info["score"] == 45
        assert score_info["time_pct"] == 45

    def test_falls_back_to_heuristic(self):
        op = _op(bytes_scanned=2_000_000)  # 2MB scan, no time breakdown
        engine = QueryOptimizerEngine([op])
        scores = engine.build_score_map()
        score_info = scores[(1, 1)]
        # Heuristic: scan_mb * 5 = 2 * 5 = 10
        assert score_info["score"] == 10.0
        assert score_info["time_pct"] == 0

    def test_expensive_operators_ranked_by_score(self):
        ops = [
            _op("Sort", operator_id=1, overall_percentage=60),
            _op("TableScan", operator_id=2, overall_percentage=30),
            _op("Result", operator_id=3, overall_percentage=10),
        ]
        engine = QueryOptimizerEngine(ops)
        expensive = engine.get_expensive_operators()
        assert expensive[0].operator_type == "Sort"
        assert expensive[0].score == 60
        assert expensive[1].operator_type == "TableScan"

    def test_cost_attribution_sums_to_100(self):
        ops = [
            _op("Sort", operator_id=1, overall_percentage=60),
            _op("TableScan", operator_id=2, overall_percentage=30),
            _op("Result", operator_id=3, overall_percentage=10),
        ]
        engine = QueryOptimizerEngine(ops)
        attribution = engine.calculate_cost_attribution()
        total_pct = sum(a["percent"] for a in attribution)
        assert abs(total_pct - 100.0) < 0.01
