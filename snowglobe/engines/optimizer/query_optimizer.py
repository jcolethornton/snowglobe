from typing import List
from snowglobe.models.optimizer import QueryOptimizationResult, ExpensiveOperator
from snowglobe.models.query import QueryProfile


class QueryOptimizerEngine:

    def __init__(self, profile: List[QueryProfile]):
        self.profile = profile

    def get_suggestions(self) -> QueryOptimizationResult:
        """Run all detection rules and return deduplicated suggestions."""
        profile = self.profile
        suggestions = []

        suggestions.extend(self.detect_join_explosion(profile))
        suggestions.extend(self.detect_disk_spill(profile))
        suggestions.extend(self.detect_pruning_failure(profile))
        suggestions.extend(self.detect_cartesian_join(profile))
        suggestions.extend(self.detect_large_scan(profile))
        suggestions.extend(self.detect_large_window(profile))
        suggestions.extend(self.detect_large_aggregation(profile))
        suggestions.extend(self.detect_heavy_network(profile))
        suggestions.extend(self.detect_filter_after_join(profile))
        suggestions.extend(self.detect_skew(profile))
        suggestions.extend(self.detect_sort_without_limit(profile))

        # Deduplicate while preserving order
        suggestions = list(dict.fromkeys(suggestions))

        return QueryOptimizationResult(suggestions=suggestions)

    def build_score_map(self):
        """Build a map of (step_id, operator_id) -> score info."""
        scores = {}
        for op in self.profile:
            score, detail, time_pct = self._calculate_operator_cost(op)
            key = (op.step_id, op.operator_id)
            scores[key] = {
                "score": score,
                "detail": detail,
                "time_pct": time_pct,
            }
        return scores

    def _calculate_operator_cost(self, op):
        """
        Calculate operator cost using execution_time_breakdown as primary signal.
        Falls back to heuristic scoring when time data is unavailable.
        Returns (score, detail_dict, time_pct).
        """
        time_breakdown = op.execution_time_breakdown or {}
        time_pct = time_breakdown.get("overall_percentage", 0)

        stats = op.operator_statistics or {}
        io = stats.get("io", {})
        network = stats.get("network", {})

        bytes_scanned = io.get("bytes_scanned", 0)
        network_bytes = network.get("network_bytes", 0)
        input_rows = stats.get("input_rows", 0)
        output_rows = stats.get("output_rows", 0)
        spill_local = stats.get("bytes_spilled_local_storage", 0)
        spill_remote = stats.get("bytes_spilled_remote_storage", 0)

        scan_mb = bytes_scanned / 1_000_000
        network_mb = network_bytes / 1_000_000
        rows_m = input_rows / 1_000_000
        spill_mb = (spill_local + spill_remote) / 1_000_000

        # Primary score: use time percentage when available (0-100 scale)
        if time_pct > 0:
            score = time_pct
        else:
            # Fallback heuristic when no time breakdown available
            score = (
                scan_mb * 5
                + network_mb * 3
                + rows_m * 1
                + spill_mb * 10
            )

        detail = {
            "scan_mb": scan_mb,
            "network_mb": network_mb,
            "rows_m": rows_m,
            "spill_mb": spill_mb,
            "output_rows": output_rows,
            "time_breakdown": time_breakdown,
        }

        return score, detail, time_pct

    # Keep backward compat for external callers
    def calculate_operator_cost(self, op):
        score, detail, _ = self._calculate_operator_cost(op)
        return score, detail

    def calculate_cost_attribution(self):
        """Attribute cost to operator types, using time % as primary signal."""
        attribution = {}
        total_score = 0

        for op in self.profile:
            score, _, _ = self._calculate_operator_cost(op)
            if score <= 0:
                continue
            op_type = op.operator_type
            attribution.setdefault(op_type, 0)
            attribution[op_type] += score
            total_score += score

        results = []
        for op_type, score in attribution.items():
            pct = (score / total_score) * 100 if total_score else 0
            results.append({
                "operator_type": op_type,
                "score": score,
                "percent": pct,
            })

        results.sort(key=lambda x: x["score"], reverse=True)
        return results

    def get_expensive_operators(self, limit=5):
        """Return top expensive operators ranked by cost score."""
        ranked = []

        for op in self.profile:
            score, detail, time_pct = self._calculate_operator_cost(op)
            if score > 0:
                ranked.append(
                    ExpensiveOperator(
                        operator_type=op.operator_type,
                        operator_id=op.operator_id,
                        score=score,
                        detail=detail,
                        time_pct=time_pct,
                    )
                )

        ranked.sort(key=lambda x: x.score, reverse=True)
        return ranked[:limit]

    # --- Detection rules ---

    def detect_join_explosion(self, operators: List[QueryProfile]):
        suggestions = []
        for op in operators:
            if "Join" in op.operator_type:
                stats = op.operator_statistics or {}
                produced = stats.get("output_rows", 0)
                consumed = stats.get("input_rows", 1)
                if consumed and produced > consumed * 10:
                    suggestions.append(
                        f"Join explosion at operator {op.operator_id} "
                        f"({produced:,} output vs {consumed:,} input rows). "
                        "Review join keys or filter earlier."
                    )
        return suggestions

    def detect_disk_spill(self, operators: List[QueryProfile]):
        suggestions = []
        for op in operators:
            stats = op.operator_statistics or {}
            local_spill = stats.get("bytes_spilled_local_storage", 0)
            remote_spill = stats.get("bytes_spilled_remote_storage", 0)
            if remote_spill > 0:
                suggestions.append(
                    f"Remote disk spill at operator {op.operator_id} "
                    f"({remote_spill / 1e9:.1f} GB). "
                    "Increase warehouse size or reduce data volume."
                )
            elif local_spill > 0:
                suggestions.append(
                    f"Local disk spill at operator {op.operator_id} "
                    f"({local_spill / 1e9:.1f} GB). "
                    "Consider a larger warehouse if this impacts performance."
                )
        return suggestions

    def detect_pruning_failure(self, operators: List[QueryProfile]):
        suggestions = []
        for op in operators:
            if op.operator_type == "TableScan":
                attrs = op.operator_attributes or {}
                scanned = attrs.get("partitions_scanned", 0)
                total = attrs.get("partitions_total", 0)
                if total > 0 and scanned / total > 0.9:
                    suggestions.append(
                        f"Partition pruning ineffective at operator {op.operator_id} "
                        f"({scanned}/{total} partitions scanned). "
                        "Add selective filters or consider clustering."
                    )
        return suggestions

    def detect_large_scan(self, operators):
        suggestions = []
        for op in operators:
            if op.operator_type == "TableScan":
                stats = op.operator_statistics or {}
                io = stats.get("io", {})
                bytes_scanned = io.get("bytes_scanned", 0)
                if bytes_scanned > 1_000_000_000:
                    suggestions.append(
                        f"Large table scan ({bytes_scanned / 1e9:.1f} GB) at operator {op.operator_id}. "
                        "Consider clustering, adding filters, or using search optimization."
                    )
        return suggestions

    def detect_cartesian_join(self, operators):
        suggestions = []
        for op in operators:
            if op.operator_type == "CartesianJoin":
                suggestions.append(
                    f"Cartesian join at operator {op.operator_id}. "
                    "This produces every combination of rows — check join conditions."
                )
        return suggestions

    def detect_large_window(self, operators):
        suggestions = []
        for op in operators:
            if op.operator_type == "WindowFunction":
                stats = op.operator_statistics or {}
                rows = stats.get("input_rows", 0)
                if rows > 100_000_000:
                    suggestions.append(
                        f"Window function over {rows:,} rows at operator {op.operator_id}. "
                        "Pre-aggregate or add a PARTITION BY clause to reduce window size."
                    )
        return suggestions

    def detect_large_aggregation(self, operators):
        suggestions = []
        for op in operators:
            if op.operator_type == "Aggregate":
                stats = op.operator_statistics or {}
                rows = stats.get("input_rows", 0)
                if rows > 100_000_000:
                    suggestions.append(
                        f"Aggregation over {rows:,} rows at operator {op.operator_id}. "
                        "Pre-filter data or use approximate functions (APPROX_COUNT_DISTINCT)."
                    )
        return suggestions

    def detect_heavy_network(self, operators):
        suggestions = []
        for op in operators:
            stats = op.operator_statistics or {}
            network = stats.get("network", {})
            bytes_sent = network.get("network_bytes", 0)
            if bytes_sent > 1_000_000_000:
                suggestions.append(
                    f"Heavy network shuffle ({bytes_sent / 1e9:.1f} GB) at operator {op.operator_id}. "
                    "Reduce join or aggregation input size to minimize data redistribution."
                )
        return suggestions

    def detect_filter_after_join(self, operators: List[QueryProfile]):
        """Detect Filter operators consuming large row counts from parent Joins."""
        suggestions = []
        op_map = {(op.step_id, op.operator_id): op for op in operators}

        for op in operators:
            if op.operator_type == "Filter":
                stats = op.operator_statistics or {}
                input_rows = stats.get("input_rows", 0)
                output_rows = stats.get("output_rows", 0)

                # Only flag if the filter removes a large fraction (>50%) of many rows
                if input_rows > 1_000_000 and output_rows < input_rows * 0.5:
                    # Check if parent is a Join
                    if op.parent_operators:
                        for parent_id in op.parent_operators:
                            parent_key = (op.step_id, parent_id)
                            parent = op_map.get(parent_key)
                            if parent and "Join" in parent.operator_type:
                                suggestions.append(
                                    f"Filter at operator {op.operator_id} removes "
                                    f"{((1 - output_rows / input_rows) * 100):.0f}% of rows after join. "
                                    "Push the filter into a subquery before the join for better performance."
                                )
                                break
        return suggestions

    def detect_skew(self, operators: List[QueryProfile]):
        """Detect when a single operator consumes a disproportionate share of execution time."""
        suggestions = []
        if len(operators) < 3:
            return suggestions

        for op in operators:
            time_breakdown = op.execution_time_breakdown or {}
            time_pct = time_breakdown.get("overall_percentage", 0)
            if time_pct > 60:
                suggestions.append(
                    f"Operator {op.operator_id} ({op.operator_type}) consumes "
                    f"{time_pct:.0f}% of total execution time. "
                    "This is the primary bottleneck — focus optimization here."
                )
        return suggestions

    def detect_sort_without_limit(self, operators: List[QueryProfile]):
        """Detect Sort operators with high row counts that have no downstream Limit."""
        suggestions = []
        # Build child map
        child_types = {}  # operator_id -> list of child operator types
        for op in operators:
            if op.parent_operators:
                for parent_id in op.parent_operators:
                    child_types.setdefault((op.step_id, parent_id), []).append(op.operator_type)

        for op in operators:
            if op.operator_type == "Sort":
                stats = op.operator_statistics or {}
                rows = stats.get("input_rows", 0)
                if rows > 10_000_000:
                    # Check if any child is a Limit
                    children = child_types.get((op.step_id, op.operator_id), [])
                    if "Limit" not in children:
                        suggestions.append(
                            f"Sort over {rows:,} rows at operator {op.operator_id} with no LIMIT. "
                            "Add a LIMIT clause or remove unnecessary ORDER BY."
                        )
        return suggestions
