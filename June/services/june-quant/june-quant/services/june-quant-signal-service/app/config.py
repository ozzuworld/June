TARGET_RETURN = 0.0035       # 0.35%
COST_ESTIMATE = 0.0005       # 0.05% (fees + spread) - tune later
BUFFER = 0.0003              # 0.03% safety margin

MIN_EDGE_LONG = TARGET_RETURN + COST_ESTIMATE + BUFFER
MIN_EDGE_SHORT = -TARGET_RETURN - COST_ESTIMATE - BUFFER

RISK_PER_TRADE = 0.003       # 0.3% of equity per trade (risk fraction)
