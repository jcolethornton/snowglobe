"""TUI Tune screen — engine-output contract test.

This guards against drift between QueryOptimizerEngine return shapes and
the Tune screen's rendering code. It uses the *real* engine (no stubs)
to build the score map + operator tree, then mounts the real TuneScreen
and drives an analyse end-to-end via Textual's Pilot.

Regression: an early Phase 7 stub fed the screen a flat `{key: float}`
score map, but the real engine returns `{key: {"score": ..., "detail": ...,
"time_pct": ...}}`. The screen's f-string formatter crashed with
"unsupported format string passed to dict.__format__" — this test would
have caught it.
"""
import asyncio

from snowglobe.engines.optimizer.query_optimizer import QueryOptimizerEngine
from snowglobe.models.query import QueryProfile


def _op(
    *,
    step_id: int = 1,
    operator_id: int = 0,
    operator_type: str = "TableScan",
    parents: list[int] | None = None,
    output_rows: int = 0,
    input_rows: int = 0,
    bytes_scanned: int = 0,
    spill_local: int = 0,
    overall_percentage: float = 0,
) -> QueryProfile:
    return QueryProfile(
        query_id="test-query-id",
        step_id=step_id,
        operator_id=operator_id,
        parent_operators=parents or [],
        operator_type=operator_type,
        operator_statistics={
            "input_rows": input_rows,
            "output_rows": output_rows,
            "io": {"bytes_scanned": bytes_scanned},
            "network": {"network_bytes": 0},
            "bytes_spilled_local_storage": spill_local,
            "bytes_spilled_remote_storage": 0,
        },
        execution_time_breakdown=(
            {"overall_percentage": overall_percentage} if overall_percentage else {}
        ),
        operator_attributes={},
    )


class _FakeOptimizerService:
    """
    Minimal QueryOptimizerService stand-in.

    The Snowflake-touching methods (collect_query_profile, collect_insights,
    ai_suggestion) are stubbed, but everything that produces data for the
    screen runs through the real QueryOptimizerEngine — so any return-shape
    drift between the engine and the screen surfaces here.
    """

    def __init__(self, profiles: list[QueryProfile]):
        self.query_profile = profiles
        self.sql_text = "SELECT 1"
        self.query_insights: list[dict] = []
        self.optimizer: QueryOptimizerEngine | None = None
        self.result_suggestions = None
        self.result_cost_attribution = None

    def collect_query_profile(self, query_id: str) -> None:
        # Real impl would hit Snowflake; here the profile is already in memory.
        pass

    def analyze_query(self) -> None:
        self.optimizer = QueryOptimizerEngine(self.query_profile)

    def collect_insights(self) -> list[dict]:
        return self.query_insights

    def suggestions(self):
        result = self.optimizer.get_suggestions()
        self.result_suggestions = result
        return result

    def score(self):
        # The real shape: {key: {"score": float, "detail": dict, "time_pct": float}}
        return self.optimizer.build_score_map()

    def build_operator_tree(self) -> dict:
        # Copied verbatim from QueryOptimizerService.build_operator_tree so the
        # test exercises the same tree shape the real code produces.
        def key(op):
            return (op.step_id, op.operator_id)

        op_map = {key(op): op for op in self.query_profile}
        tree: dict = {key(op): [] for op in self.query_profile}
        child_keys = set()
        for op in self.query_profile:
            for parent_id in op.parent_operators:
                parent_key = (op.step_id, parent_id)
                tree.setdefault(parent_key, []).append(key(op))
                child_keys.add(key(op))
        roots = [k for k in op_map.keys() if k not in child_keys]
        return {"roots": roots, "tree": tree, "op_map": op_map}

    def expensive_operators(self):
        return self.optimizer.get_expensive_operators()

    def cost_attribution(self):
        self.result_cost_attribution = self.optimizer.calculate_cost_attribution()
        return self.result_cost_attribution

    def ai_suggestion(self, model: str = "claude-haiku-4-5") -> str:
        return "# Stubbed AI\n\nNo Cortex call in tests."


def _run(coro):
    """Run an async test using a fresh event loop — no pytest-asyncio needed."""
    return asyncio.run(coro)


def test_tune_screen_renders_real_engine_output():
    """
    Drives the Tune screen against the real QueryOptimizerEngine.
    Asserts the score map + operator tree render without format errors.
    """
    from snowglobe.core import optimizer as opt_mod
    from snowglobe.tui.app import SnowglobeApp
    from snowglobe.tui.screens.tune import TuneScreen
    from textual.widgets import DataTable, Input, Tree

    profiles = [
        _op(step_id=1, operator_id=0, operator_type="TableScan",
            overall_percentage=60.0, output_rows=100_000_000,
            bytes_scanned=2_000_000_000),
        _op(step_id=1, operator_id=1, operator_type="HashAggregate",
            parents=[0], overall_percentage=30.0,
            input_rows=100_000_000, output_rows=10_000_000,
            spill_local=1_500_000_000),
        _op(step_id=1, operator_id=2, operator_type="Result",
            parents=[1], overall_percentage=10.0, output_rows=100_000),
    ]

    async def go():
        # Patch QueryOptimizerService constructor BEFORE the app mounts so the
        # analyse worker picks up the fake.
        opt_mod.QueryOptimizerService = lambda ctx: _FakeOptimizerService(profiles)

        app = SnowglobeApp()
        async with app.run_test() as pilot:
            await pilot.pause()

            # Jump to Tune
            await pilot.press("5")
            await pilot.pause()

            screen = app.query_one(TuneScreen)
            screen.query_one("#tu-query-id", Input).value = "test-query-id"
            screen._start_analysis()

            # Allow the worker to complete and the call_from_thread to render
            for _ in range(20):
                tree = screen.query_one("#tu-tree", Tree)
                if tree.root.children:
                    break
                await pilot.pause(0.1)

            # --- Tree rendered without crashing ---
            tree = screen.query_one("#tu-tree", Tree)
            assert tree.root.children, "tree should have nodes after analysis"

            # Every operator node label must include 'score' and '% time'
            def walk(node):
                yield str(node.label)
                for child in node.children:
                    yield from walk(child)

            labels = list(walk(tree.root))
            assert "Operator tree" in labels[0], f"unexpected root: {labels[0]!r}"
            assert len(labels) == 4, f"expected 1 root + 3 ops, got {len(labels)}"
            for label in labels[1:]:
                assert "score" in label, f"missing score in: {label!r}"
                assert "% time" in label, f"missing time% in: {label!r}"
                # All three time_pct values are non-zero — must render as floats, not dicts
                assert "{" not in label, f"raw dict leaked into label: {label!r}"

            # --- Expensive ops table populated ---
            exp = screen.query_one("#tu-exp-table", DataTable)
            assert exp.row_count > 0, "expensive ops should include the heavy operators"

            # --- Heuristic suggestions reached the screen ---
            assert screen._last_data is not None, "screen should cache analysis data"
            suggestions = screen._last_data["suggestions"]
            assert suggestions, "engine should return at least one suggestion"
            # 1.5 GB spill triggers the disk-spill detector
            assert any("spill" in s.lower() for s in suggestions), \
                f"expected disk-spill finding among: {suggestions}"

    _run(go())
