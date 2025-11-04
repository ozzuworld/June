import time
import requests
from dataclasses import dataclass

SIGNAL_URL = "http://localhost:8000/signal"
ORDER_URL = "http://localhost:8001/order"
EQUITY_URL = "http://localhost:8001/equity"

SYMBOL = "BTCUSDT"

# Risk config (same spirit as inside the signal service)
TARGET_RETURN = 0.0035   # 0.35%
STOP_LOSS_DISTANCE = 0.005  # -0.5% SL
RISK_PER_TRADE = 0.003   # 0.3% of equity at risk

@dataclass
class Position:
    side: str   # "LONG" or "SHORT"
    qty: float
    entry_price: float


def get_signal(features):
    payload = {
        "symbol": SYMBOL,
        "features": features
    }
    r = requests.post(SIGNAL_URL, json=payload)
    r.raise_for_status()
    return r.json()


def send_order(side: str, qty: float, price: float, tp: float | None, sl: float | None):
    payload = {
        "symbol": SYMBOL,
        "side": "BUY" if side == "LONG" else "SELL",
        "quantity": qty,
        "entry_price": price,
        "take_profit": tp,
        "stop_loss": sl,
    }
    r = requests.post(ORDER_URL, json=payload)
    r.raise_for_status()
    return r.json()


def get_equity():
    r = requests.get(EQUITY_URL)
    r.raise_for_status()
    return r.json()


def compute_long_position_size(equity: float, price: float) -> float:
    """
    Basic position sizing for a LONG:
    - Risk per trade = RISK_PER_TRADE * equity
    - Stop loss distance = STOP_LOSS_DISTANCE (e.g. 0.5%)
    - qty = max_loss / (price * stop_loss_distance)
    """
    max_loss = equity * RISK_PER_TRADE
    qty = max_loss / (price * STOP_LOSS_DISTANCE)
    # Be extra conservative and cap position at 50% of equity notionally
    max_notional = 0.5 * equity
    if qty * price > max_notional:
        qty = max_notional / price
    return qty


def main():
    # Tiny fake price series to see some trades
    prices = [60000, 60100, 60250, 60300, 60150, 59900, 59700, 59850, 60200, 60500]

    # Position we track locally (we could also query /equity, but this is enough for PoC)
    position: Position | None = None

    print("Starting orchestrator with fake prices...")
    start_equity_snapshot = get_equity()
    print("Initial equity:", start_equity_snapshot)

    for i, price in enumerate(prices):
        print(f"\n--- Step {i}, price={price} ---")

        # Super simple feature: last return repeated 10 times
        if i == 0:
            ret = 0.0
        else:
            ret = (price - prices[i - 1]) / prices[i - 1]
        features = [ret] * 10

        signal = get_signal(features)
        print("Signal response:", signal)

        action = signal["action"]

        equity_snapshot = get_equity()
        equity = equity_snapshot["equity"]

        # If no open position, only act on LONG for now (simplify PoC)
        if position is None:
            if action == "LONG":
                qty = compute_long_position_size(equity, price)
                if qty <= 0:
                    print("  -> qty <= 0, skipping trade")
                    continue

                tp = price * (1 + TARGET_RETURN)           # TP at +0.35%
                sl = price * (1 - STOP_LOSS_DISTANCE)      # SL at -0.5%

                order = send_order("LONG", qty, price, tp, sl)
                print("  -> OPEN LONG:", order)

                position = Position(side="LONG", qty=qty, entry_price=price)
            else:
                print("  -> No position, staying flat.")
        else:
            # We have an open LONG. Check exit conditions.
            if position.side == "LONG":
                current_ret = (price - position.entry_price) / position.entry_price
                print(f"  -> Current long return: {current_ret:.5f} ({current_ret*100:.2f}%)")

                hit_tp = current_ret >= TARGET_RETURN
                hit_sl = current_ret <= -STOP_LOSS_DISTANCE
                opposite_signal = (action == "SHORT")

                if hit_tp or hit_sl or opposite_signal:
                    close_order = send_order("SHORT", position.qty, price, tp=None, sl=None)
                    print("  -> CLOSE LONG:", close_order)
                    position = None
                else:
                    print("  -> Holding position.")

        # small delay so logs are readable
        time.sleep(0.1)

    # At the end, if position still open, close at last price
    if position is not None:
        final_price = prices[-1]
        close_order = send_order("SHORT", position.qty, final_price, tp=None, sl=None)
        print("\nFinal close of remaining position:", close_order)
        position = None

    final_equity = get_equity()
    print("\n=== Final equity snapshot ===")
    print(final_equity)
    print(f"PnL: {final_equity['equity'] - start_equity_snapshot['equity']:.2f}")

if __name__ == "__main__":
    main()
