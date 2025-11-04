from pydantic import BaseModel, Field
from typing import Optional, List

class OrderRequest(BaseModel):
    symbol: str
    side: str = Field(..., description='"BUY" or "SELL"')
    quantity: float
    entry_price: float
    take_profit: Optional[float] = None
    stop_loss: Optional[float] = None

class OrderResponse(BaseModel):
    order_id: int
    symbol: str
    side: str
    quantity: float
    entry_price: float
    status: str
    take_profit: Optional[float]
    stop_loss: Optional[float]

class Position(BaseModel):
    symbol: str
    quantity: float
    avg_entry_price: float
    unrealized_pnl: float

class EquitySnapshot(BaseModel):
    equity: float
    cash: float
    positions: List[Position]
