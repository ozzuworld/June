from fastapi import FastAPI, HTTPException
from .models import OrderRequest, OrderResponse, Position, EquitySnapshot
from .state import SimState

app = FastAPI(title="june-quant-execution-sim", version="0.1.0")

state = SimState()

@app.get("/health")
def health():
    return {"status": "ok", "service": "june-quant-execution-sim"}

@app.post("/order", response_model=OrderResponse)
def submit_order(order: OrderRequest):
    try:
        order_id = state.process_order(
            symbol=order.symbol,
            side=order.side,
            qty=order.quantity,
            price=order.entry_price,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return OrderResponse(
        order_id=order_id,
        symbol=order.symbol,
        side=order.side,
        quantity=order.quantity,
        entry_price=order.entry_price,
        status="FILLED",
        take_profit=order.take_profit,
        stop_loss=order.stop_loss,
    )

@app.get("/equity", response_model=EquitySnapshot)
def get_equity():
    # For PoC we assume zero unrealized PnL (no price updates yet)
    positions = [
        Position(
            symbol=p.symbol,
            quantity=p.quantity,
            avg_entry_price=p.avg_entry_price,
            unrealized_pnl=0.0,
        )
        for p in state.positions.values()
    ]

    equity = state.cash  # + unrealized PnL (0 for now)

    return EquitySnapshot(
        equity=equity,
        cash=state.cash,
        positions=positions,
    )
