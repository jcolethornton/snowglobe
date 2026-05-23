from snowglobe.output.cli import format_query_insights, format_expensive_operators, format_cost_attribution
from snowglobe.models.optimizer import ExpensiveOperator


class TestFormatQueryInsights:
    def test_renders_insights(self):
        insights = [
            {
                "type_id": "QUERY_INSIGHT_EXPLODING_JOIN",
                "message": "Join produces too many rows",
                "suggestions": ["Add a filter before the join", "Check join keys"],
                "is_opportunity": True,
                "topic": "JOIN",
            }
        ]
        output = format_query_insights("test-query-id", insights)
        assert "QUERY_INSIGHT_EXPLODING_JOIN" in output
        assert "JOIN" in output
        assert "Add a filter before the join" in output
        assert "Check join keys" in output
        assert "[!]" in output  # is_opportunity marker

    def test_renders_info_insights(self):
        insights = [
            {
                "type_id": "QUERY_INSIGHT_FILTER_WITH_CLUSTERING_KEY",
                "message": "Query uses clustering key",
                "suggestions": None,
                "is_opportunity": False,
                "topic": "TABLE_SCAN",
            }
        ]
        output = format_query_insights("test-query-id", insights)
        assert "[i]" in output  # informational marker
        assert "TABLE_SCAN" in output

    def test_empty_insights(self):
        output = format_query_insights("test-query-id", [])
        assert "No insights" in output

    def test_handles_dict_message(self):
        insights = [
            {
                "type_id": "TEST",
                "message": {"message": "Detailed info", "extra": "data"},
                "suggestions": [],
                "is_opportunity": True,
                "topic": "TEST",
            }
        ]
        output = format_query_insights("id", insights)
        assert "Detailed info" in output


class TestFormatExpensiveOperators:
    def test_shows_time_pct_when_present(self):
        operators = [
            ExpensiveOperator(
                operator_type="Sort",
                operator_id=1,
                score=70.0,
                detail={"scan_mb": 100.0, "rows_m": 5.0},
                time_pct=70.0,
            )
        ]
        output = format_expensive_operators(operators)
        assert "time=70%" in output
        assert "Sort" in output

    def test_no_time_when_zero(self):
        operators = [
            ExpensiveOperator(
                operator_type="TableScan",
                operator_id=2,
                score=50.0,
                detail={"scan_mb": 50.0, "rows_m": 2.0},
                time_pct=0.0,
            )
        ]
        output = format_expensive_operators(operators)
        assert "time=" not in output


class TestFormatCostAttribution:
    def test_renders_attribution(self):
        results = [
            {"operator_type": "Sort", "score": 70, "percent": 70.0},
            {"operator_type": "TableScan", "score": 30, "percent": 30.0},
        ]
        output = format_cost_attribution(results)
        assert "Sort" in output
        assert "70.0%" in output
        assert "TableScan" in output
        assert "30.0%" in output
