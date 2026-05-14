from typing import List
from snowglobe.models.optimizer import QueryOptimizationResult, ExpensiveOperator
from snowglobe.models.query import QueryProfile

class QueryOptimizerEngine:

    def __init__(self, profile: List[QueryProfile]):
        self.profile = profile

    def get_suggestions(self) -> QueryOptimizationResult:

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

        suggestions = list(dict.fromkeys(suggestions))

        return QueryOptimizationResult(
            suggestions=list(dict.fromkeys(suggestions))
        )

    def build_score_map(self):

        operators = self.profile

        scores = {}
        for op in operators:

            score, detail = self.calculate_operator_cost(op)
            key = (op.step_id, op.operator_id)
            scores[key] = {
                "score": score,
                "detail": detail
            }

        return scores

    def calculate_operator_cost(self, op):

        stats = op.operator_statistics or {}

        io = stats.get("io", {})
        network = stats.get("network", {})

        bytes_scanned = io.get("bytes_scanned", 0)
        network_bytes = network.get("network_bytes", 0)

        input_rows = stats.get("input_rows", 0)
        output_rows = stats.get("output_rows", 0)

        spill_local = stats.get("bytes_spilled_local_storage", 0)
        spill_remote = stats.get("bytes_spilled_remote_storage", 0)

        # Normalize units
        scan_mb = bytes_scanned / 1_000_000
        network_mb = network_bytes / 1_000_000
        rows_m = input_rows / 1_000_000
        spill_mb = (spill_local + spill_remote) / 1_000_000

        score = (
            scan_mb * 5
            + network_mb * 3
            + rows_m * 1
            + spill_mb * 10
        )

        return score, {
            "scan_mb": scan_mb,
            "network_mb": network_mb,
            "rows_m": rows_m,
            "spill_mb": spill_mb
        }

    def calculate_cost_attribution(self):

        operators = self.profile
        attribution = {}
        total_score = 0

        for op in operators:

            score, _ = self.calculate_operator_cost(op)

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
                "percent": pct
            })

        results.sort(key=lambda x: x["score"], reverse=True)

        return results

    def get_expensive_operators(self, limit=5):

        operators = self.profile

        ranked = []

        for op in operators:

            score, detail = self.calculate_operator_cost(op)

            if score > 0:

                ranked.append(
                    ExpensiveOperator(
                        operator_type=op.operator_type,
                        operator_id=op.operator_id,
                        score=score,
                        detail=detail
                    )
                )

        ranked.sort(key=lambda x: x.score, reverse=True)

        return ranked[:limit]


    def detect_join_explosion(self, operators: List[QueryProfile]):

        suggestions = []

        for op in operators:

            if "Join" in op.operator_type:

                stats = op.operator_statistics or {}

                produced = stats.get("output_rows", 0)
                consumed = stats.get("input_rows", 1)

                if consumed and produced > consumed * 10:

                    suggestions.append(
                        f"Join explosion detected at operator (step={op.step_id}, id={op.operator_id}). "
                        "Consider filtering earlier or reviewing join keys."
                    )

        return suggestions

    def detect_disk_spill(self, operators: List[QueryProfile]):

        suggestions = []

        for op in operators:

            stats = op.operator_statistics or {}

            local_spill = stats.get("bytes_spilled_local_storage", 0)
            remote_spill = stats.get("bytes_spilled_remote_storage", 0)

            if local_spill > 0 or remote_spill > 0:

                suggestions.append(
                    f"Disk spill detected at operator {op.operator_id}. "
                    "Consider increasing warehouse size or optimizing joins/aggregations."
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
                        f"Partition pruning ineffective at operator {op.operator_id}. "
                        "Consider more selective filters."
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
                        f"Large table scan detected ({bytes_scanned / 1e9:.2f} GB). "
                        "Consider clustering or filtering earlier."
                    )

        return suggestions

    def detect_cartesian_join(self, operators):

        suggestions = []

        for op in operators:
            if op.operator_type == "CartesianJoin":

                suggestions.append(
                    "Cartesian join detected. Check join conditions — this can cause massive row explosion."
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
                        f"Large window function over {rows:,} rows. Consider pre-aggregating or filtering earlier."
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
                        f"Large aggregation over {rows:,} rows. Consider pre-filtering or clustering."
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
                    f"Heavy network shuffle detected ({bytes_sent/1e9:.1f} GB). Consider reducing join or aggregation size."
                )

        return suggestions
