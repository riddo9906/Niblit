"""Safe, bounded arithmetic expression evaluator for Niblit's native layer."""
from __future__ import annotations

import ast
from decimal import Decimal, DivisionByZero, InvalidOperation, localcontext


MAX_EXPRESSION_CHARS = 256
MAX_AST_NODES = 64
MAX_EXPONENT = 12
_ALLOWED_BINARY = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.FloorDiv: lambda a, b: a // b,
    ast.Mod: lambda a, b: a % b,
    ast.Pow: lambda a, b: a ** int(b),
}
_ALLOWED_UNARY = {ast.UAdd: lambda x: x, ast.USub: lambda x: -x}


class MathExpressionError(ValueError):
    pass


def evaluate_expression(expression: str) -> dict:
    if not isinstance(expression, str) or not expression.strip() or len(expression) > MAX_EXPRESSION_CHARS:
        raise MathExpressionError("expression must be non-empty and bounded")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise MathExpressionError("invalid arithmetic syntax") from exc
    nodes = list(ast.walk(tree))
    if len(nodes) > MAX_AST_NODES:
        raise MathExpressionError("expression is too complex")
    with localcontext() as context:
        context.prec = 28
        value = _evaluate(tree.body)
    return {
        "expression": expression,
        "value": format(value, "f"),
        "numeric_type": "decimal",
        "operator_count": sum(isinstance(n, ast.BinOp) for n in nodes),
        "tree": _tree_summary(tree.body),
    }


def _evaluate(node) -> Decimal:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return Decimal(str(node.value))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_UNARY:
        return _ALLOWED_UNARY[type(node.op)](_evaluate(node.operand))
    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINARY:
        left, right = _evaluate(node.left), _evaluate(node.right)
        if isinstance(node.op, ast.Pow):
            if right != right.to_integral_value() or abs(right) > MAX_EXPONENT:
                raise MathExpressionError("exponent outside bounded integer range")
        if isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mod)) and right == 0:
            raise MathExpressionError("division by zero")
        try:
            return _ALLOWED_BINARY[type(node.op)](left, right)
        except (DivisionByZero, InvalidOperation, OverflowError, ValueError) as exc:
            raise MathExpressionError("arithmetic operation failed") from exc
    raise MathExpressionError(f"unsupported expression element: {type(node).__name__}")


def _tree_summary(node) -> dict:
    if isinstance(node, ast.Constant):
        return {"kind": "number", "value": str(node.value)}
    if isinstance(node, ast.UnaryOp):
        return {"kind": "unary", "operator": type(node.op).__name__,
                "operand": _tree_summary(node.operand)}
    if isinstance(node, ast.BinOp):
        return {"kind": "binary", "operator": type(node.op).__name__,
                "left": _tree_summary(node.left), "right": _tree_summary(node.right)}
    return {"kind": "unsupported"}
