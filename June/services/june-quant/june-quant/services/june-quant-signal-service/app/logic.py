from .config import MIN_EDGE_LONG, MIN_EDGE_SHORT, RISK_PER_TRADE

def decide_action(predicted_return: float) -> tuple[str, float]:
    """
    Decide LONG / SHORT / FLAT based on predicted return and thresholds.

    Returns (action, risk_fraction).
    """
    if predicted_return > MIN_EDGE_LONG:
        return "LONG", RISK_PER_TRADE
    elif predicted_return < MIN_EDGE_SHORT:
        return "SHORT", RISK_PER_TRADE
    else:
        return "FLAT", 0.0
