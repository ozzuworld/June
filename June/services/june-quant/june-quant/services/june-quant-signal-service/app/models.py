from pydantic import BaseModel, Field
from typing import List, Optional

class FeatureVector(BaseModel):
    symbol: str = Field(..., description="Asset symbol, e.g. BTCUSDT or AAPL")
    features: List[float] = Field(..., description="Feature vector for the model")
    current_price: Optional[float] = None
    account_equity: Optional[float] = None

class SignalResponse(BaseModel):
    action: str              # "LONG", "SHORT", "FLAT"
    expected_return: float   # predicted return, e.g. 0.004 = 0.4%
    confidence: float        # simple proxy for magnitude of prediction
    risk_fraction: float     # fraction of equity to risk (0..1)
