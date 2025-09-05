def get_weather(city: str) -> str:
    # Replace with real API (OpenWeather, WeatherAPI, etc.)
    if city.lower() == "bogotá":
        return "Sunny, 25°C"
    return f"No weather data available for {city}"

def calculator(expression: str) -> str:
    """Safely evaluate simple math expressions.
    Allowed: integers/floats, + - * / % **, parentheses, unary +/-."""
    import ast, operator as op

    # Supported operators
    ops = {
        ast.Add: op.add,
        ast.Sub: op.sub,
        ast.Mult: op.mul,
        ast.Div: op.truediv,
        ast.Mod: op.mod,
        ast.Pow: op.pow,
        ast.USub: op.neg,
        ast.UAdd: op.pos,
    }

    def _eval(node):
        if isinstance(node, ast.Num):
            return node.n
        if isinstance(node, ast.BinOp) and type(node.op) in ops:
            return ops[type(node.op)](_eval(node.left), _eval(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in ops:
            return ops[type(node.op)](_eval(node.operand))
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        raise ValueError("Unsupported expression")

    try:
        tree = ast.parse(expression, mode="eval")
        return str(_eval(tree))
    except Exception:
        return "Error in calculation"
