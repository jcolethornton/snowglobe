"""Tune — query optimizer (Phase 7).

Layout:
  ┌─ Query ID: ___________________  [Analyse]  ────────────────────────┐
  │ <status line>                                                      │
  │ ┌─ SQL ───────────────────┐ ┌─ Analysis ────────────────────────┐ │
  │ │ syntax-highlighted SQL  │ │ Heuristics | Insights | Tree |    │ │
  │ │                         │ │ Expensive ops | AI                │ │
  │ └─────────────────────────┘ └────────────────────────────────────┘ │

All Snowflake calls run in `@work` thread workers. The AI tab triggers a
separate Cortex worker (slower) only when the user clicks 'Generate'.
"""
from typing import Any

from rich.syntax import Syntax

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Button, DataTable, Input, Markdown, Static, TabbedContent, TabPane, Tree,
)


class TuneScreen(Vertical):
    """Query analyzer — operator tree, heuristics, native insights, AI."""

    _optimizer: Any | None = None    # holds last QueryOptimizerService
    _last_data: dict | None = None   # holds rendered result for re-renders

    def compose(self) -> ComposeResult:
        yield Static("Tune — Query optimizer", classes="screen-title")

        with Horizontal(id="tu-controls"):
            yield Static("Query ID:", classes="form-label")
            yield Input(
                placeholder="01b3a-… (paste from Cost ▸ Top queries)",
                id="tu-query-id", classes="form-input",
            )
            yield Button("Analyse", id="tu-run", variant="primary")

        yield Static("Paste a Snowflake query ID and click Analyse.",
                     id="tu-status", classes="hint")

        with Horizontal(id="tu-body"):
            with Vertical(id="tu-sql-pane", classes="panel"):
                yield Static("SQL", classes="panel-title")
                with VerticalScroll(id="tu-sql-scroll"):
                    yield Static("Run an analysis to see SQL here.",
                                 id="tu-sql", classes="sql-pane")
            with Vertical(id="tu-analysis-pane", classes="panel"):
                yield Static("Analysis", classes="panel-title")
                with TabbedContent(initial="tu-tab-heuristics"):
                    with TabPane("Heuristics", id="tu-tab-heuristics"):
                        with VerticalScroll(id="tu-heuristics-scroll"):
                            yield Static("Pending.", id="tu-heuristics")
                    with TabPane("Insights", id="tu-tab-insights"):
                        yield DataTable(id="tu-insights-table",
                                        cursor_type="row", zebra_stripes=True)
                    with TabPane("Operator tree", id="tu-tab-tree"):
                        yield Tree("Pending.", id="tu-tree")
                    with TabPane("Expensive ops", id="tu-tab-exp"):
                        yield DataTable(id="tu-exp-table",
                                        cursor_type="row", zebra_stripes=True)
                    with TabPane("AI", id="tu-tab-ai"):
                        with Horizontal(classes="actions-row"):
                            yield Button("Generate AI suggestion (Cortex)",
                                         id="tu-ai-run", variant="warning")
                        with VerticalScroll(id="tu-ai-scroll"):
                            yield Markdown(
                                "AI suggestions will appear here after you Analyse "
                                "and then click Generate.",
                                id="tu-ai",
                            )

    # --- Events -------------------------------------------------------

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "tu-run":
            self._start_analysis()
        elif event.button.id == "tu-ai-run":
            self._start_ai()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "tu-query-id":
            self._start_analysis()

    # --- Analyse worker ----------------------------------------------

    def _start_analysis(self) -> None:
        query_id = self.query_one("#tu-query-id", Input).value.strip()
        if not query_id:
            self.app.notify("Query ID required.", severity="warning")
            return
        self.query_one("#tu-status", Static).update(
            f"Fetching profile for {query_id[:30]}… (Snowflake call)"
        )
        self.query_one("#tu-run", Button).disabled = True
        self._analyse_worker(query_id=query_id)

    @work(thread=True, exclusive=True, group="snowflake")
    def _analyse_worker(self, *, query_id: str) -> None:
        from snowglobe.core.optimizer import QueryOptimizerService
        try:
            svc = QueryOptimizerService(self.app.context)
            svc.collect_query_profile(query_id)
            svc.analyze_query()
            insights = svc.collect_insights()
            result = svc.suggestions()
            tree = svc.build_operator_tree()
            scores = svc.score()
            cost_attr = svc.cost_attribution()
            expensive = svc.expensive_operators()
        except Exception as e:
            self.app.call_from_thread(self._analysis_failed, e)
            return

        data = {
            "query_id": query_id,
            "sql": svc.sql_text or "",
            "insights": insights or [],
            "suggestions": result.suggestions or [],
            "tree": tree,
            "scores": scores,
            "cost_attribution": cost_attr,
            "expensive": expensive,
        }
        # Cache the service so AI generation can reuse the loaded profile.
        self._optimizer = svc
        self.app.call_from_thread(self._render_analysis, data)

    def _analysis_failed(self, err: Exception) -> None:
        self.query_one("#tu-status", Static).update(f"Analysis failed: {err}")
        self.query_one("#tu-run", Button).disabled = False
        self.app.notify(f"Analysis failed: {err}", severity="error", timeout=8)

    def _render_analysis(self, data: dict) -> None:
        self._last_data = data
        self.query_one("#tu-status", Static).update(
            f"Loaded profile for {data['query_id'][:30]}… — "
            f"{len(data['tree']['op_map'])} operators, "
            f"{len(data['suggestions'])} heuristic finding(s)"
        )
        self.query_one("#tu-run", Button).disabled = False

        # --- SQL with syntax highlight ---
        sql = data["sql"] or "(no SQL text returned)"
        self.query_one("#tu-sql", Static).update(
            Syntax(sql, "sql", theme="github-dark", word_wrap=True, line_numbers=True)
        )

        # --- Heuristics ---
        if data["suggestions"]:
            text = "\n".join(f"• {s}" for s in data["suggestions"])
        else:
            text = "(no heuristic findings — query likely well-tuned for its size)"
        self.query_one("#tu-heuristics", Static).update(text)

        # --- Native insights ---
        it = self.query_one("#tu-insights-table", DataTable)
        it.clear(columns=True)
        if data["insights"]:
            keys = list(data["insights"][0].keys())
            it.add_columns(*keys)
            for row in data["insights"]:
                it.add_row(*[str(row.get(k, "")) for k in keys])
        else:
            it.add_columns("(no Snowflake QUERY_INSIGHTS for this query)")

        # --- Operator tree ---
        tree_widget = self.query_one("#tu-tree", Tree)
        tree_widget.clear()
        op_count = len(data["tree"]["op_map"])
        tree_widget.root.label = f"Operator tree — {op_count} operator(s)"
        tree_widget.root.expand()
        for root_key in data["tree"]["roots"]:
            self._add_op_node(tree_widget.root, root_key,
                              data["tree"]["tree"], data["tree"]["op_map"], data["scores"])

        # --- Expensive operators ---
        ex = self.query_one("#tu-exp-table", DataTable)
        ex.clear(columns=True)
        if data["expensive"]:
            ex.add_columns("OPERATOR", "ID", "SCORE", "TIME %")
            for e in data["expensive"]:
                ex.add_row(
                    str(e.operator_type),
                    str(e.operator_id),
                    f"{e.score:.1f}",
                    f"{e.time_pct:.1f}%",
                )
        else:
            ex.add_columns("(no operators flagged as expensive)")

        # Reset AI tab to its placeholder so users know to regenerate
        self.query_one("#tu-ai", Markdown).update(
            "AI suggestions will appear here after you click Generate."
        )

    def _add_op_node(self, parent, op_key, edges, op_map, scores) -> None:
        op = op_map.get(op_key)
        if op is None:
            return
        # `scores` is {op_key: {"score": float, "detail": dict, "time_pct": float}}.
        score_entry = (scores or {}).get(op_key)
        if isinstance(score_entry, dict):
            score_val = score_entry.get("score", 0.0)
            time_pct = score_entry.get("time_pct", 0.0)
        else:
            score_val = score_entry if score_entry is not None else 0.0
            time_pct = (op.execution_time_breakdown or {}).get("overall_percentage", 0)
        try:
            score_val = float(score_val)
        except (TypeError, ValueError):
            score_val = 0.0
        try:
            time_pct = float(time_pct)
        except (TypeError, ValueError):
            time_pct = 0.0
        label = (
            f"{op.operator_type}  ·  step {op_key[0]}.{op_key[1]}  ·  "
            f"score {score_val:.1f}  ·  {time_pct:.1f}% time"
        )
        node = parent.add(label, expand=True)
        for child_key in edges.get(op_key, []):
            self._add_op_node(node, child_key, edges, op_map, scores)

    # --- AI worker ----------------------------------------------------

    def _start_ai(self) -> None:
        if self._optimizer is None:
            self.app.notify("Run Analyse first.", severity="warning")
            return
        self.query_one("#tu-ai", Markdown).update(
            "Generating AI suggestion via Snowflake Cortex…"
        )
        self.query_one("#tu-ai-run", Button).disabled = True
        self._ai_worker()

    @work(thread=True, exclusive=True, group="cortex")
    def _ai_worker(self) -> None:
        try:
            text = self._optimizer.ai_suggestion()
        except Exception as e:
            self.app.call_from_thread(self._ai_failed, e)
            return
        self.app.call_from_thread(self._render_ai, text)

    def _ai_failed(self, err: Exception) -> None:
        self.query_one("#tu-ai", Markdown).update(f"**AI generation failed:** {err}")
        self.query_one("#tu-ai-run", Button).disabled = False
        self.app.notify(f"AI generation failed: {err}", severity="error", timeout=8)

    def _render_ai(self, text) -> None:
        from snowglobe.output.cli import format_ai_suggestion
        self.query_one("#tu-ai", Markdown).update(format_ai_suggestion(text) or "(empty AI response)")
        self.query_one("#tu-ai-run", Button).disabled = False
