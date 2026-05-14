__all__ = [
    "format_json",
    "print_table",
    "format_access_text",
]
import pandas as pd

def format_json(explain: dict):
    from rich import print_json
    return print_json(data=explain)

def print_table(df: pd.DataFrame, title=None, no_wrap=True):
    from rich.table import Table
    from rich.console import Console

    console = Console()
    table = Table(title=title or "", header_style="bold cyan", row_styles=["none", "dim"])

    for col in df.columns:
        table.add_column(str(col), no_wrap=no_wrap, max_width=None if not no_wrap else 80)

    for row in df.itertuples(index=False):
        formatted_row = [
            str(cell).replace("\n", " ").replace("\r", " ") if no_wrap else str(cell)
            for cell in row
        ]
        table.add_row(*formatted_row)

    console.print(table)


def format_access_text(explain: dict) -> str:
    lines = []


    if explain.get("roles_with_privilege"):

        lines.append(f"User '{explain['user']}' CAN '{explain['privilege']}' on {explain['object_name']}")
        
        for privilege, chains in explain['user_access_paths'].items():
            lines.append(f"\nPrivilege: {privilege}")
            for i, chain in enumerate(chains, start=1):
                lines.append(f"  Path {i}: {' -> '.join(chain)}")

    else:
        lines.append(f"User '{explain['user']}' CANNOT '{explain['privilege']}' on {explain['object_name']}")
        lines.append("Roles with privilege:")
        for role in explain['roles_with_privilege']:
            lines.append(f"  - {role}")

    return "\n".join(lines)

def format_optimizer_suggestions(query_id, suggestions):

        output = f"\nQuery Optimization Suggestions for '{query_id}'.\n"
        output += "-" * 50 + "\n"

        if not suggestions:
            output += "No obvious improvements found.\n"
        else:
            for s in suggestions:
                output += f"• {s}\n"

        return output

def print_operator_tree(op_tree, scores=None):
    tree = op_tree["tree"]
    op_map = op_tree["op_map"]
    roots = op_tree["roots"]

    scores = scores or {}

    def _print(node_id, prefix="", is_last=True):

        if node_id == -1:
            print(f"{prefix}└── QueryPlan")

        else:
            op = op_map[node_id]
            connector = "└── " if is_last else "├── "

            score = scores.get(node_id, {}).get("score", 0)

            heat = ""
            if score > 200:
                heat = " 🔥"
            elif score > 50:
                heat = " ⚠"

            if score > 0:
                label = f"{op.operator_type} (step={op.step_id}, id={op.operator_id}, score={score:.1f}){heat}"
            else:
                label = f"{op.operator_type} (step={op.step_id}, id={op.operator_id})"

            print(f"{prefix}{connector}{label}")

        children = tree.get(node_id, [])

        for i, child_id in enumerate(children):
            last = i == len(children) - 1
            new_prefix = prefix + ("    " if is_last else "│   ")
            _print(child_id, new_prefix, last)

    # Virtual root
    tree[-1] = roots
    _print(-1)

def format_expensive_operators(expensive):

    output = "\nTop Expensive Operators\n"
    output += "-" * 50 + "\n"

    for i, op in enumerate(expensive, 1):

        scan = op.detail["scan_mb"]
        rows = op.detail["rows_m"]

        output += (
            f"{i}. {op.operator_type} (id={op.operator_id}) "
            f"[scan={scan:.1f}MB rows={rows:.1f}M]\n"
        )

    return output

def format_cost_attribution(results):

    output = "\nQuery Cost Breakdown\n"
    output += "-" * 50 + "\n\n"

    for r in results:

        output += f"{r['operator_type']:<18} {r['percent']:.1f}%\n"

    return output
