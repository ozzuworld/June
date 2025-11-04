from typing import Dict
from dataclasses import dataclass, field

@dataclass
class SimPosition:
    symbol: str
    quantity: float = 0.0
    avg_entry_price: float = 0.0

@dataclass
class SimState:
    cash: float = 10_000.0  # starting cash for PoC
    positions: Dict[str, SimPosition] = field(default_factory=dict)
    next_order_id: int = 1

    def process_order(self, symbol: str, side: str, qty: float, price: float) -> int:
        """
        Very simplistic fill logic: assume immediate fill at requested price.
        Adjusts cash and positions.
        """
        if side not in ("BUY", "SELL"):
            raise ValueError("side must be BUY or SELL")

        position = self.positions.get(symbol, SimPosition(symbol=symbol))

        if side == "BUY":
            cost = qty * price
            if cost > self.cash:
                raise ValueError("Insufficient cash")
            self.cash -= cost

            new_qty = position.quantity + qty
            if new_qty == 0:
                position.avg_entry_price = 0.0
            else:
                position.avg_entry_price = (
                    (position.avg_entry_price * position.quantity + cost) / new_qty
                )
            position.quantity = new_qty

        else:  # SELL
            if qty > position.quantity:
                raise ValueError("Insufficient position to sell")
            proceeds = qty * price
            self.cash += proceeds

            position.quantity -= qty
            if position.quantity == 0:
                position.avg_entry_price = 0.0

        if position.quantity == 0:
            self.positions.pop(symbol, None)
        else:
            self.positions[symbol] = position

        order_id = self.next_order_id
        self.next_order_id += 1
        return order_id
